"""Approval and purpose-bound password actions; never sends SMTP."""
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.core.config import settings
from app.models.entities import Usuario
from app.models.auth import AuthSession
from app.models.account_access import AccessRequest, AuthActionToken, AuthMailJob
from app.services import auth_action_protection as protection
from app.schemas.account_access import valid_address, Role
from typing import get_args

RESET_MESSAGE = 'Si el correo corresponde a una cuenta habilitada, recibirás instrucciones para restablecer tu contraseña.'
ACCESS_MESSAGE = 'Recibimos tu solicitud. El equipo responsable revisará la información y se pondrá en contacto contigo si procede.'
INVALID_MESSAGE = 'Este enlace no es válido o ya no está disponible. Solicita uno nuevo.'


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fingerprint(subject):
    if isinstance(subject, Usuario):
        # updated_at also invalidates a deactivate/reactivate cycle and CLI edits.
        values = [subject.id, subject.password_hash, subject.correo, subject.correo_normalizado,
                  subject.activo, str(subject.updated_at)]
    else:
        values = [subject.id, subject.identifier, subject.nombre, subject.approved_role,
                  subject.status, subject.resolved_by, str(subject.resolved_at)]
    return hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).digest()


def invalid():
    return HTTPException(400, INVALID_MESSAGE)


def submit_access(db, payload):
    protection.adaptive_admit(db, 'ACCESS_REQUEST', payload.correo, payload.turnstile_token)
    try:
        stmt = insert(AccessRequest).values(identifier=payload.correo, nombre=payload.nombre,
            motivo=payload.motivo, status='PENDING', created_at=now_utc())
        db.execute(stmt.on_duplicate_key_update(identifier=AccessRequest.identifier))
        db.commit()
    except Exception:
        db.rollback()
        raise


def request_reset(db, identifier, turnstile_token=None):
    protection.adaptive_admit(db, 'RESET_REQUEST', identifier, turnstile_token)
    # This is lookup work, NOT outbound mail. No user lookup, recipient or token.
    try:
        db.add(AuthMailJob(kind='LOOKUP_RESET', identifier=identifier))
        db.commit()
    except Exception:
        db.rollback()
        raise


def queue_action(db, subject, purpose):
    """Caller holds the subject lock. A new operation supersedes older sends.

    SMTP may already be in flight; its token becomes unusable in this transaction.
    Only a resolved database subject supplies the recipient, never public input.
    """
    initial = purpose == 'INITIAL_PASSWORD'
    recipient = subject.identifier if initial else subject.correo
    valid_address(recipient)
    db.flush()  # Include newly approved data / updated_at in the fingerprint.
    token_subject = AuthActionToken.access_request_id if initial else AuthActionToken.usuario_id
    job_subject = AuthMailJob.access_request_id if initial else AuthMailJob.usuario_id
    db.execute(update(AuthActionToken).where(token_subject == subject.id,
        AuthActionToken.purpose == purpose, AuthActionToken.consumed_at.is_(None)).values(consumed_at=now_utc()))
    db.execute(update(AuthMailJob).where(job_subject == subject.id, AuthMailJob.kind == purpose,
        AuthMailJob.status.in_(['PENDING', 'PROCESSING'])).values(status='CANCELLED', lease=None, locked_until=None))
    job = AuthMailJob(kind=purpose, recipient=recipient, state_fingerprint=fingerprint(subject),
        access_request_id=subject.id if initial else None, usuario_id=None if initial else subject.id)
    db.add(job)
    return job


def resolve_access(db, admin_id, request_id, role=None, reason=None):
    try:
        admin = db.scalar(select(Usuario).where(Usuario.id == admin_id).with_for_update()
                          .execution_options(populate_existing=True))
        if admin is None or not admin.activo or admin.rol != 'ADMIN':
            raise HTTPException(403, 'Operacion no permitida')
        row = db.scalar(select(AccessRequest).where(AccessRequest.id == request_id).with_for_update()
                        .execution_options(populate_existing=True))
        if row is None:
            raise HTTPException(404, 'Recurso no encontrado')
        if row.status != 'PENDING':
            raise HTTPException(409, 'La solicitud ya fue resuelta')
        if role is not None:
            if role not in get_args(Role):
                raise HTTPException(422, 'Rol invalido')
            if db.scalar(select(Usuario.id).where(Usuario.correo_normalizado == row.identifier)) is not None:
                raise HTTPException(409, 'No se puede aprobar: el correo ya pertenece a una cuenta')
            protection.admit(db, 'INITIAL_SEND', row.identifier, commit=False)
            row.status, row.approved_role = 'APPROVED', role
        else:
            row.status, row.admin_reason = 'REJECTED', reason
        row.resolved_by, row.resolved_at = admin.id, now_utc()
        if role is not None:
            queue_action(db, row, 'INITIAL_PASSWORD')
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        raise


def resend_initial(db, admin_id, request_id):
    try:
        admin = db.scalar(select(Usuario).where(Usuario.id == admin_id).with_for_update()
                          .execution_options(populate_existing=True))
        if admin is None or not admin.activo or admin.rol != 'ADMIN':
            raise HTTPException(403, 'Operacion no permitida')
        row = db.scalar(select(AccessRequest).where(AccessRequest.id == request_id).with_for_update()
                        .execution_options(populate_existing=True))
        if row is None:
            raise HTTPException(404, 'Recurso no encontrado')
        if row.status != 'APPROVED' or row.usuario_id is not None or db.scalar(
                select(Usuario.id).where(Usuario.correo_normalizado == row.identifier)) is not None:
            raise HTTPException(409, 'La solicitud no admite reenvío')
        protection.admit(db, 'INITIAL_SEND', row.identifier, commit=False)
        queue_action(db, row, 'INITIAL_PASSWORD')
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        raise


def load_action(db, digest, purpose, locking=False):
    if purpose not in {'PASSWORD_RESET', 'INITIAL_PASSWORD'}:
        raise invalid()
    # Preliminary token lookup to locate subject; lock order is subject -> token.
    token = db.get(AuthActionToken, digest)
    if token is None or token.purpose != purpose:
        raise invalid()
    subject_type = Usuario if purpose == 'PASSWORD_RESET' else AccessRequest
    subject_id = token.usuario_id if purpose == 'PASSWORD_RESET' else token.access_request_id
    query = select(subject_type).where(subject_type.id == subject_id)
    if locking:
        query = query.with_for_update().execution_options(populate_existing=True)
    subject = db.scalar(query)
    if locking:
        token = db.scalar(select(AuthActionToken).where(AuthActionToken.token_hash == digest)
            .with_for_update().execution_options(populate_existing=True))
    if (subject is None or token is None or token.purpose != purpose or token.consumed_at is not None
            or token.expires_at <= now_utc() or not hmac.compare_digest(token.state_fingerprint, fingerprint(subject))):
        raise invalid()
    if purpose == 'PASSWORD_RESET':
        if not subject.activo:
            raise invalid()
    elif subject.status != 'APPROVED' or subject.usuario_id is not None:
        raise invalid()
    return token, subject


def confirm_password(db, purpose, raw_token, password):
    digest = hashlib.sha256(raw_token.encode()).digest()
    protection.admit(db, purpose, digest.hex())
    acquired = False
    try:
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', raw_token):
            raise invalid()
        load_action(db, digest, purpose)
        db.rollback()
        protection.budget.take('HASH', settings.action_hash_per_minute, hashing=True)
        acquired = True
        hashed = hash_password(password)  # No DB transaction or row lock.
        token, subject = load_action(db, digest, purpose, locking=True)
        now = now_utc()
        if purpose == 'PASSWORD_RESET':
            subject.password_hash = hashed
            db.execute(update(AuthActionToken).where(AuthActionToken.usuario_id == subject.id,
                AuthActionToken.purpose == purpose, AuthActionToken.consumed_at.is_(None)).values(consumed_at=now))
            db.execute(update(AuthSession).where(AuthSession.usuario_id == subject.id,
                AuthSession.revoked_at.is_(None)).values(revoked_at=now))
            db.execute(update(AuthMailJob).where(AuthMailJob.kind == 'PASSWORD_RESET',
                AuthMailJob.status.in_(['PENDING', 'PROCESSING']),
                AuthMailJob.usuario_id == subject.id
                ).values(status='CANCELLED', lease=None, locked_until=None))
            # Separate indexed predicates avoid a broad OR scan locking other users' jobs.
            db.execute(update(AuthMailJob).where(AuthMailJob.kind == 'LOOKUP_RESET',
                AuthMailJob.status.in_(['PENDING', 'PROCESSING']),
                AuthMailJob.identifier == subject.correo_normalizado
                ).values(status='CANCELLED', lease=None, locked_until=None))
            db.flush()
            db.add(AuthMailJob(kind='PASSWORD_CHANGED', usuario_id=subject.id, recipient=subject.correo,
                              state_fingerprint=fingerprint(subject)))
        else:
            if db.scalar(select(Usuario.id).where(Usuario.correo_normalizado == subject.identifier)) is not None:
                raise invalid()
            user = Usuario(nombre=subject.nombre, correo=subject.identifier, correo_normalizado=subject.identifier,
                           rol=subject.approved_role, password_hash=hashed, activo=True)
            db.add(user)
            db.flush()  # Database uniqueness is the final arbiter under concurrency.
            subject.status, subject.usuario_id = 'FULFILLED', user.id
            db.execute(update(AuthActionToken).where(AuthActionToken.access_request_id == subject.id,
                AuthActionToken.consumed_at.is_(None)).values(consumed_at=now))
            db.execute(update(AuthMailJob).where(AuthMailJob.access_request_id == subject.id,
                AuthMailJob.status.in_(['PENDING', 'PROCESSING'])).values(status='CANCELLED', lease=None, locked_until=None))
        token.consumed_at = now
        db.commit()
    except IntegrityError:
        db.rollback()
        raise invalid() from None
    except Exception:
        db.rollback()
        raise
    finally:
        if acquired:
            protection.budget.release_hash()
