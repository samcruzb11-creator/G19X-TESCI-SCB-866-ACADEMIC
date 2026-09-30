"""Compensation boundaries for a newly stored file and one SQL transaction.

No retries. Once COMMIT has been attempted, unknown outcomes retain the file.
Only MySQL's explicit deadlock rollback (1213) proves a commit rejection here.
"""
import logging

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class CommitOutcomeUnknown(RuntimeError):
    """The caller must reconcile before retrying this business operation."""


def rollback_safely(db: Session) -> bool:
    try:
        db.rollback()
        return True
    except Exception:
        # Do not log driver messages: they may contain connection credentials.
        logger.error("file_transaction: rollback failed; reconciliation required")
        return False


def discard_uncommitted_file(db: Session, storage: StorageService, key: str) -> None:
    """Call only before COMMIT or after a proven server-side transaction rollback."""
    if not rollback_safely(db):
        logger.error("file_transaction: file retained after rollback failure")
        return
    try:
        removed = storage.delete_file(key)
    except Exception:
        removed = False
    if not removed:
        logger.error("file_transaction: cleanup incomplete; reconciliation required")


def commit_stored_file(db: Session, storage: StorageService, key: str) -> None:
    """All entities/events must already have been flushed by the caller.

    A successful rollback after a transport failure does NOT prove that COMMIT
    failed on the server. Never delete in that case, even if the session resets.
    Post-commit refresh/serialization must remain outside this function.
    """
    try:
        db.commit()
    except Exception as exc:
        rejected = (
            isinstance(exc, DBAPIError)
            and not exc.connection_invalidated
            and getattr(exc.orig, "args", ())[:1] == (1213,)
        )
        if rejected:
            discard_uncommitted_file(db, storage, key)
            raise
        rollback_safely(db)
        logger.error("file_transaction: commit outcome unknown; file retained; do not retry blindly")
        raise CommitOutcomeUnknown(
            "No fue posible confirmar el registro. Comprueba su estado antes de reenviar."
        ) from exc
