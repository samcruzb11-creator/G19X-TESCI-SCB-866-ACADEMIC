"""Read-only metadata/filesystem comparison. Never repairs or deletes files."""
from __future__ import annotations

import hashlib
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Evidencia, VersionDocumento
from app.services.storage_service import StorageService


@dataclass(frozen=True)
class FileReference:
    entity: str
    id: int
    key: str | None
    sha256: str | None
    size: int | None


@dataclass
class IntegrityReport:
    checked: int = 0
    issues: list[dict] = field(default_factory=list)

    def add(self, kind: str, *, ref: FileReference | None = None, key: str | None = None):
        issue = {"kind": kind}
        if ref is not None:
            issue.update(entity=ref.entity, id=ref.id)
        if key is not None:
            issue["key"] = key  # Only relative, validated managed paths.
        self.issues.append(issue)

    @property
    def counts(self) -> dict[str, int]:
        return dict(Counter(issue["kind"] for issue in self.issues))

    @property
    def exit_code(self) -> int:
        # An incomplete inspection must never be reported as a clean result.
        if any(i["kind"] in {"storage_unavailable", "scan_incomplete", "unreadable"} for i in self.issues):
            return 2
        return 1 if self.issues else 0


def read_references(db: Session) -> list[FileReference]:
    """SELECT only. Do not flush or commit even if supplied a dirty session."""
    result = []
    with db.no_autoflush:
        for model, entity in [(VersionDocumento, "version"), (Evidencia, "evidence")]:
            stmt = select(model.id, model.storage_key, model.sha256, model.tamano_bytes)
            if model is Evidencia:
                stmt = stmt.where((model.tipo == "FILE") | model.storage_key.is_not(None))
            for row in db.execute(stmt.execution_options(yield_per=200)):
                result.append(FileReference(entity, *row))
    return result


def scan_storage(references: Iterable[FileReference], root: Path, temporary_age: int = 3600) -> IntegrityReport:
    """Inspect managed documents/evidence directories; do not follow filesystem links.

    Run with uploads paused for a definitive snapshot. During active writes an
    unreferenced file may be in flight; all orphan reports are candidates only.
    """
    report = IntegrityReport()
    root = root.resolve()
    storage = StorageService(base_path=root)  # Constructor performs no writes.
    referenced: set[Path] = set()
    try:
        if not root.is_dir():
            report.add("storage_unavailable")
            return report
    except OSError:
        report.add("storage_unavailable")
        return report

    def linked(path: Path) -> bool:
        while path != root:
            if path.is_symlink() or path.is_junction():
                return True
            path = path.parent
        return False

    for ref in references:
        report.checked += 1
        try:
            if not isinstance(ref.key, str) or not ref.key:
                raise ValueError
            path = storage.get_absolute_path(ref.key)
            relative = Path(ref.key.replace("\\", "/"))
            if relative.parts[0] not in {"documents", "evidence"}:
                raise ValueError
            referenced.add(path)
            if linked(root / relative):
                report.add("unsafe_link", ref=ref)
                continue
            if not path.is_file():
                report.add("missing_file", ref=ref)
                continue
            with path.open("rb") as source:
                before = os.fstat(source.fileno())
                digest = hashlib.sha256()
                size = 0
                while chunk := source.read(65536):
                    size += len(chunk)
                    digest.update(chunk)
                after = os.fstat(source.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                report.add("changed_during_scan", ref=ref)
                continue
            if not isinstance(ref.sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", ref.sha256):
                report.add("invalid_hash_metadata", ref=ref)
            elif digest.hexdigest() != ref.sha256.lower():
                report.add("hash_mismatch", ref=ref)
            if ref.size is not None and ref.size != size:
                report.add("size_mismatch", ref=ref)
        except ValueError:
            report.add("invalid_storage_key", ref=ref)
        except OSError:
            report.add("unreadable", ref=ref)

    def walk(directory: Path):
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if entry.is_symlink() or path.is_junction():
                        report.add("unsafe_link")
                    elif entry.is_dir(follow_symlinks=False):
                        walk(path)
                    elif entry.is_file(follow_symlinks=False):
                        key = path.relative_to(root).as_posix()
                        if ".tmp_" in path.name or path.name.startswith(".tmp_"):
                            age = time.time() - entry.stat(follow_symlinks=False).st_mtime
                            report.add("temporary_abandoned_candidate" if age >= temporary_age else "temporary_recent", key=key)
                        elif path.resolve() not in referenced:
                            report.add("orphan_candidate", key=key)
        except OSError:
            report.add("scan_incomplete")

    for category in ("documents", "evidence"):
        directory = root / category
        if directory.is_symlink() or directory.is_junction():
            report.add("unsafe_link")
        elif directory.exists():
            walk(directory)
    return report
