"""Servicio de almacenamiento físico y cómputo criptográfico SHA-256 en streaming.

Responsabilidades:
- Guardar archivos en disco con escritura atómica (temp + rename).
- Calcular hash SHA-256 en bloques de 64 KB (sin saturar RAM).
- Generar ``storage_key`` determinista/único con particionado por año/mes.
- Exponer adaptadores para ``BinaryIO`` (tests) y ``UploadFile`` de FastAPI.
- Eliminar archivos físicos para rollback (cleanup on failure).
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, NamedTuple
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)

# UploadFile se importa de forma lazy para no crear dependencia dura en tests
# que usen el servicio sin FastAPI instalado.
try:
    from fastapi import UploadFile
    _HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    _HAS_FASTAPI = False
    UploadFile = None  # type: ignore[assignment,misc]


class StoredFileInfo(NamedTuple):
    """Información forense y física de un archivo almacenado con éxito."""

    storage_key: str   # Ruta relativa dentro del storage root (e.g. "evidence/2026/09/abc.pdf")
    sha256: str        # SHA-256 hexadecimal del contenido (64 chars)
    tamano_bytes: int  # Tamaño exacto en bytes
    mime_type: str     # MIME type resuelto
    nombre_original: str  # Nombre de archivo saneado (sin path traversal)
    absolute_path: str    # Ruta absoluta en disco (solo para uso interno del proceso)


class StorageService:
    """Gestiona el almacenamiento seguro y el cálculo de integridad en streaming.

    Diseño:
    - Particionado por ``{category}/{YYYY}/{MM}/{uuid4_hex}{ext}`` para escalar I/O.
    - Escritura atómica: primero escribe a ``.tmp_{uuid}`` y luego hace ``rename()``.
    - SHA-256 calculado en streaming durante la escritura (una sola pasada por el archivo).
    - Solo se compensan archivos nuevos de transacciones no confirmadas.
      Una interrupción de proceso puede dejar huérfanos: el verificador los informa.
    """

    def __init__(self, base_path: str | Path | None = None, chunk_size: int = 65_536) -> None:
        raw_path = base_path or settings.storage_path
        self.base_path = Path(raw_path).resolve()
        self.chunk_size = chunk_size
        # Construction and read-only verification must not create directories.

    # ------------------------------------------------------------------
    # Infraestructura interna
    # ------------------------------------------------------------------

    def _ensure_base_directory(self) -> None:
        """Crea el directorio raíz de almacenamiento si no existe."""
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, filename: str) -> str:
        """Elimina rutas y caracteres peligrosos para prevenir path traversal."""
        clean = Path(filename).name.strip()
        return clean if clean else "archivo_sin_nombre"

    def _guess_mime_type(self, filename: str, explicit_mime: str | None) -> str:
        """Resuelve el MIME type priorizando el explícito si no es genérico."""
        if explicit_mime and explicit_mime not in (
            "application/octet-stream",
            "binary/octet-stream",
        ):
            return explicit_mime
        guessed, _ = mimetypes.guess_type(filename)
        return guessed or explicit_mime or "application/octet-stream"

    def _build_target_path(self, category: str, extension: str) -> tuple[str, Path]:
        """Genera un ``storage_key`` único y la ruta absoluta correspondiente."""
        now = datetime.now(timezone.utc)
        partition = now.strftime("%Y/%m")
        file_uuid = uuid4().hex
        unique_filename = f"{file_uuid}{extension}"
        storage_key = f"{category}/{partition}/{unique_filename}"
        target_path = self.get_absolute_path(storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        return storage_key, target_path

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def save_file(
        self,
        file_stream: BinaryIO,
        filename: str,
        content_type: str | None = None,
        category: str = "documents",
    ) -> StoredFileInfo:
        """Guarda un stream binario en disco mediante streaming SHA-256 + escritura atómica.

        Args:
            file_stream:  Stream binario abierto en modo lectura (``BinaryIO``).
            filename:     Nombre de archivo original (se sanitiza internamente).
            content_type: MIME type declarado por el cliente (puede ser ``None``).
            category:     Sub-directorio de categoría (``"documents"`` o ``"evidence"``).

        Returns:
            :class:`StoredFileInfo` con todos los metadatos forenses.

        Raises:
            OSError: Si el sistema de archivos no puede crear el archivo.
        """
        clean_name = self._sanitize_filename(filename)
        mime_type = self._guess_mime_type(clean_name, content_type)
        extension = Path(clean_name).suffix.lower()
        storage_key, target_path = self._build_target_path(category, extension)

        hasher = hashlib.sha256()
        total_bytes = 0
        temp_target = target_path.with_suffix(f"{extension}.tmp_{uuid4().hex}")

        try:
            with open(temp_target, "wb") as f_out:
                while True:
                    chunk = file_stream.read(self.chunk_size)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    f_out.write(chunk)
                    total_bytes += len(chunk)

                f_out.flush()
                os.fsync(f_out.fileno())

            info = StoredFileInfo(
                storage_key=storage_key, sha256=hasher.hexdigest(),
                tamano_bytes=total_bytes, mime_type=mime_type,
                nombre_original=clean_name, absolute_path=str(target_path),
            )

            # Rename atómico: nunca deja un archivo a medias en la ruta final
            temp_target.replace(target_path)

        except Exception:
            if temp_target.exists():
                try:
                    temp_target.unlink()
                except OSError:
                    logger.error("storage: temporary cleanup failed; verification required")
            raise

        return info

    def save_upload_file(
        self,
        upload_file: "UploadFile",
        category: str = "documents",
    ) -> StoredFileInfo:
        """Adaptador para ``fastapi.UploadFile`` — extrae el stream y delega a ``save_file()``.

        Args:
            upload_file: Objeto ``UploadFile`` recibido en el endpoint FastAPI.
            category:    Sub-directorio de categoría.

        Returns:
            :class:`StoredFileInfo` con todos los metadatos forenses.
        """
        if not _HAS_FASTAPI:  # pragma: no cover
            raise RuntimeError("FastAPI no está instalado — usa save_file() con un BinaryIO.")

        return self.save_file(
            file_stream=upload_file.file,
            filename=upload_file.filename or "archivo_sin_nombre",
            content_type=upload_file.content_type,
            category=category,
        )

    def delete_file(self, storage_key: str) -> bool:
        """Elimina el archivo físico asociado a un ``storage_key`` (rollback/cleanup on failure).

        Returns:
            ``True`` si el archivo fue eliminado, ``False`` si no existía o si falló la operación.
        """
        if not storage_key:
            return False
        target_path = (self.base_path / storage_key).resolve()
        # Seguridad: la ruta resuelta debe permanecer dentro de base_path
        if not target_path.is_relative_to(self.base_path):
            return False
        if target_path.exists() and target_path.is_file():
            try:
                target_path.unlink()
                return True
            except OSError:
                return False
        return False

    def get_absolute_path(self, storage_key: str) -> Path:
        """Retorna la ruta absoluta verificando restricciones de path traversal.

        Raises:
            ValueError: Si ``storage_key`` intenta escapar del ``base_path``.
        """
        key = Path(storage_key.replace("\\", "/"))
        if key.is_absolute() or key.drive or ".." in key.parts or ":" in storage_key:
            raise ValueError("Ruta de almacenamiento no permitida")
        target = (self.base_path / key).resolve()
        if not target.is_relative_to(self.base_path):
            raise ValueError("Ruta de almacenamiento no permitida")
        return target

    def verify_file_integrity(self, storage_key: str, expected_sha256: str) -> bool:
        """Verifica en streaming que el archivo en disco no haya sido alterado o corrompido.

        Returns:
            ``True`` si el SHA-256 calculado coincide con ``expected_sha256``.
        """
        try:
            target = self.get_absolute_path(storage_key)
        except ValueError:
            return False

        if not target.exists() or not target.is_file():
            return False

        hasher = hashlib.sha256()
        with open(target, "rb") as f_in:
            while chunk := f_in.read(self.chunk_size):
                hasher.update(chunk)

        return hasher.hexdigest().lower() == expected_sha256.lower()


# ---------------------------------------------------------------------------
# Instancia singleton — reutilizada por los servicios de dominio
# ---------------------------------------------------------------------------
storage_service = StorageService()
