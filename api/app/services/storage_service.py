"""Servicio de almacenamiento físico y cómputo criptográfico SHA-256 en streaming."""

from __future__ import annotations

import hashlib
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, NamedTuple
from uuid import uuid4

from app.core.config import settings


class StoredFileInfo(NamedTuple):
    """Información forense y física de un archivo almacenado."""
    storage_key: str
    sha256: str
    tamano_bytes: int
    mime_type: str
    nombre_original: str
    absolute_path: str


class StorageService:
    """Gestiona el almacenamiento seguro y el cálculo de integridad en streaming."""

    def __init__(self, base_path: str | Path | None = None, chunk_size: int = 65536) -> None:
        raw_path = base_path or settings.storage_path
        self.base_path = Path(raw_path).resolve()
        self.chunk_size = chunk_size
        self._ensure_base_directory()

    def _ensure_base_directory(self) -> None:
        """Crea el directorio raíz de almacenamiento si no existe."""
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, filename: str) -> str:
        """Limpia el nombre del archivo para prevenir ataques de path traversal."""
        clean = Path(filename).name.strip()
        return clean if clean else "archivo_sin_nombre"

    def _guess_mime_type(self, filename: str, explicit_mime: str | None) -> str:
        """Resuelve el MIME type priorizando el explícito si no es genérico."""
        if explicit_mime and explicit_mime not in ("application/octet-stream", "binary/octet-stream"):
            return explicit_mime
        guessed, _ = mimetypes.guess_type(filename)
        return guessed or explicit_mime or "application/octet-stream"

    def save_file(
        self,
        file_stream: BinaryIO,
        filename: str,
        content_type: str | None = None,
        category: str = "documents",
    ) -> StoredFileInfo:
        """Guarda un archivo en disco mediante streaming y calcula su hash SHA-256 en tiempo real.

        Evita saturar la memoria RAM leyendo en bloques (chunks) de tamaño configurable.
        """
        now = datetime.now(timezone.utc)
        clean_name = self._sanitize_filename(filename)
        extension = Path(clean_name).suffix.lower()
        file_uuid = uuid4().hex

        # Particionado por categoría y año/mes para escalabilidad de I/O en disco
        partition = now.strftime("%Y/%m")
        unique_filename = f"{file_uuid}{extension}"
        storage_key = f"{category}/{partition}/{unique_filename}"

        target_path = (self.base_path / category / partition / unique_filename).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        hasher = hashlib.sha256()
        total_bytes = 0

        # Escritura atómica a archivo temporal primero
        temp_target = target_path.with_suffix(f"{extension}.tmp_{file_uuid}")
        try:
            with open(temp_target, "wb") as f_out:
                while True:
                    chunk = file_stream.read(self.chunk_size)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    f_out.write(chunk)
                    total_bytes += len(chunk)

            # Renombrado atómico
            temp_target.replace(target_path)
        except Exception:
            if temp_target.exists():
                try:
                    temp_target.unlink()
                except OSError:
                    pass
            raise

        sha256_hex = hasher.hexdigest()
        resolved_mime = self._guess_mime_type(clean_name, content_type)

        return StoredFileInfo(
            storage_key=storage_key,
            sha256=sha256_hex,
            tamano_bytes=total_bytes,
            mime_type=resolved_mime,
            nombre_original=clean_name,
            absolute_path=str(target_path),
        )

    def delete_file(self, storage_key: str) -> bool:
        """Elimina el archivo físico asociado a un storage_key (rollback/cleanup on failure)."""
        if not storage_key:
            return False
        target_path = (self.base_path / storage_key).resolve()
        # Verificar que la ruta no escape de base_path (seguridad)
        if not str(target_path).startswith(str(self.base_path)):
            return False
        if target_path.exists() and target_path.is_file():
            try:
                target_path.unlink()
                return True
            except OSError:
                return False
        return False

    def get_absolute_path(self, storage_key: str) -> Path:
        """Retorna la ruta absoluta verificando restricciones de path traversal."""
        target = (self.base_path / storage_key).resolve()
        if not str(target).startswith(str(self.base_path)):
            raise ValueError(f"Acceso de ruta no permitido para storage_key: {storage_key}")
        return target

    def verify_file_integrity(self, storage_key: str, expected_sha256: str) -> bool:
        """Verifica en streaming que el archivo en disco no haya sido alterado o corrompido."""
        target = self.get_absolute_path(storage_key)
        if not target.exists() or not target.is_file():
            return False

        hasher = hashlib.sha256()
        with open(target, "rb") as f_in:
            while chunk := f_in.read(self.chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest().lower() == expected_sha256.lower()


# Instancia singleton predeterminada
storage_service = StorageService()
