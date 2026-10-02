"""Durable local mail processor. Only resolved/approved subjects can be recipients.

Only token hashes are persisted. Each retry replaces its operation's previous
token, keeping the original expiration. At most one live link per subject and
purpose survives. SMTP can deliver duplicates; obsolete links fail closed.
"""
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr
import hashlib
import hmac
import re
import secrets
import smtplib
import ssl
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import select, or_, and_, update
from app.core.config import settings
from app.models.entities import Usuario
from app.models.account_access import AccessRequest, AuthActionToken, AuthMailJob
from app.schemas.account_access import valid_address
from app.services.account_actions import now_utc, fingerprint, queue_action

INITIAL_PASSWORD_TTL_SECONDS = 1800


def validate_mail_config():
    try:
        url = urlsplit(settings.public_frontend_url)
        local = settings.app_env == 'development' and url.hostname in {'localhost', '127.0.0.1', '::1'}
        if (not settings.smtp_host or settings.smtp_security not in {'ssl','starttls'}
            or not url.hostname or url.username is not None or url.password is not None
            or '?' in settings.public_frontend_url or '#' in settings.public_frontend_url
            or (url.scheme != 'https' and not (local and url.scheme == 'http'))
            or any(c in settings.smtp_from_name for c in '\r\n')
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in settings.public_frontend_url)
            or '\\' in settings.public_frontend_url or '%' in url.netloc
            or url.port == 0):
            raise ValueError()
        valid_address(settings.smtp_from_address)
    except (ValueError, TypeError):
        raise HTTPException(503, 'Servicio de correo no disponible') from None


def send_smtp(recipient, kind, raw_token=None):
    validate_mail_config()
    valid_address(recipient)  # Defence against malformed manually provisioned data.
    if kind not in {'INITIAL_PASSWORD', 'PASSWORD_RESET', 'PASSWORD_CHANGED'}:
        raise ValueError('Invalid outbound action')
    if kind != 'PASSWORD_CHANGED' and not re.fullmatch(r'[A-Za-z0-9_-]{43}', raw_token or ''):
        raise ValueError('Invalid action token')
    message = EmailMessage()
    message['From'] = formataddr((settings.smtp_from_name, settings.smtp_from_address))
    message['To'] = recipient
    if kind == 'PASSWORD_CHANGED':
        message['Subject'] = 'Tu contraseña fue cambiada'
        body = ('Tu contraseña fue cambiada. Si no reconoces esta operación, contacta al administrador.\n'
                'No respondas con contraseñas ni códigos de acceso.')
    else:
        initial = kind == 'INITIAL_PASSWORD'
        page = 'establecer_password' if initial else 'restablecer_password'
        url = settings.public_frontend_url.rstrip('/') + '/index.php?pagina=' + page + '#token=' + raw_token
        message['Subject'] = 'Establece tu contraseña inicial' if initial else 'Restablece tu contraseña'
        body = ('Tu acceso fue aprobado. Establece tu contraseña.' if initial else 'Se solicitó restablecer tu contraseña.')
        ttl = INITIAL_PASSWORD_TTL_SECONDS if initial else settings.password_reset_ttl_seconds
        body += (f'\n\n{url}\n\nEste enlace es de un solo uso y vence como máximo en '
                 f'{ttl // 60} minutos desde el primer intento de envío. Abrirlo no lo consume.\n'
                 f'Si JavaScript está deshabilitado, abre {url.split("#", 1)[0]} '
                 f'y pega este código en el formulario: {raw_token}\n'
                 'Si no solicitaste esta operación, puedes ignorar este mensaje.')
    message.set_content(body)
    context = ssl.create_default_context()
    if settings.smtp_security == 'ssl':
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
            timeout=settings.smtp_timeout_seconds, context=context)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds)
    with server:
        if settings.smtp_security == 'starttls':
            server.starttls(context=context)
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        server.send_message(message)


def claim(factory):
    with factory() as db:
        now = now_utc()
        job = db.scalar(select(AuthMailJob).where(or_(
            and_(AuthMailJob.status == 'PENDING', AuthMailJob.available_at <= now),
            and_(AuthMailJob.status == 'PROCESSING', AuthMailJob.locked_until <= now),
        )).order_by(AuthMailJob.available_at, AuthMailJob.id).limit(1).with_for_update(skip_locked=True))
        if job is None:
            db.rollback()
            return None
        maximum_age = timedelta(hours=24) if job.kind == 'PASSWORD_CHANGED' else timedelta(hours=1)
        if job.attempts >= 3 or job.created_at < now - maximum_age:
            job.status, job.lease, job.locked_until = 'FAILED', None, None
            job_id = job.id
            db.commit()
            return job_id, None
        job.lease = secrets.token_hex(16)
        job.status = 'PROCESSING'
        job.attempts += 1
        job.locked_until = now + timedelta(seconds=120)
        result = job.id, job.lease
        db.commit()
        return result


def owned_job(db, job_id, lease):
    return db.scalar(select(AuthMailJob).where(AuthMailJob.id == job_id, AuthMailJob.lease == lease,
        AuthMailJob.status == 'PROCESSING', AuthMailJob.locked_until > now_utc())
        .with_for_update().execution_options(populate_existing=True))


def prepare(factory, job_id, lease):
    with factory() as db:
        job = db.get(AuthMailJob, job_id)
        if job is None:
            return None
        kind, identifier, user_id, request_id = job.kind, job.identifier, job.usuario_id, job.access_request_id
        db.rollback()
        # Subject -> job -> token lock order; never retain a claim transaction.
        if kind == 'LOOKUP_RESET':
            subject = db.scalar(select(Usuario).where(Usuario.correo_normalizado == identifier).with_for_update())
        elif kind == 'INITIAL_PASSWORD':
            subject = db.scalar(select(AccessRequest).where(AccessRequest.id == request_id).with_for_update())
        else:
            subject = db.scalar(select(Usuario).where(Usuario.id == user_id).with_for_update())
        job = owned_job(db, job_id, lease)
        if job is None:
            db.rollback()
            return None
        eligible = subject is not None
        if kind == 'INITIAL_PASSWORD':
            eligible = eligible and subject.status == 'APPROVED' and subject.usuario_id is None
            if eligible:
                eligible = db.scalar(select(Usuario.id).where(Usuario.correo_normalizado == subject.identifier)) is None
        else:
            eligible = eligible and subject.activo
        if eligible and kind != 'LOOKUP_RESET':
            eligible = job.state_fingerprint is not None and hmac.compare_digest(job.state_fingerprint, fingerprint(subject))
        if not eligible:
            job.status, job.lease, job.locked_until = ('DONE' if kind == 'LOOKUP_RESET' else 'CANCELLED'), None, None
            db.commit()
            return None
        if kind == 'LOOKUP_RESET':
            # Public input NEVER crosses into recipient. Only Usuario.correo does.
            valid_address(subject.correo)
            queue_action(db, subject, 'PASSWORD_RESET')
            job.status, job.lease, job.locked_until = 'DONE', None, None
            db.commit()
            return None
        recipient = subject.identifier if kind == 'INITIAL_PASSWORD' else subject.correo
        valid_address(recipient)
        job.recipient = recipient
        raw = None
        if kind != 'PASSWORD_CHANGED':
            now = now_utc()
            if job.token_expires_at is None:
                ttl = INITIAL_PASSWORD_TTL_SECONDS if kind == 'INITIAL_PASSWORD' else settings.password_reset_ttl_seconds
                job.token_expires_at = now + timedelta(seconds=ttl)
            if job.token_expires_at <= now:
                job.status, job.lease, job.locked_until = 'FAILED', None, None
                db.commit()
                return None
            # The subject lock serializes retries, newer requests and consumption.
            db.execute(update(AuthActionToken).where(AuthActionToken.mail_job_id == job.id,
                AuthActionToken.consumed_at.is_(None)).values(consumed_at=now))
            raw = secrets.token_urlsafe(32)
            db.add(AuthActionToken(token_hash=hashlib.sha256(raw.encode()).digest(), purpose=kind, mail_job_id=job.id,
                usuario_id=subject.id if kind == 'PASSWORD_RESET' else None,
                access_request_id=subject.id if kind == 'INITIAL_PASSWORD' else None,
                state_fingerprint=fingerprint(subject),
                expires_at=job.token_expires_at))
        db.commit()
        return recipient, kind, raw


def finish(factory, job_id, lease, success):
    with factory() as db:
        job = owned_job(db, job_id, lease)
        if job is not None:
            job.status = 'DONE' if success else ('FAILED' if job.attempts >= 3 else 'PENDING')
            job.available_at = now_utc() + timedelta(seconds=30 * (2 ** (job.attempts - 1)))
            job.lease, job.locked_until = None, None
            db.commit()


def process_one(factory, sender=send_smtp):
    claimed = claim(factory)
    if claimed is None:
        return False
    job_id, lease = claimed
    if lease is None:
        return True
    try:
        prepared = prepare(factory, job_id, lease)
        if prepared is not None:
            # All sessions/transactions from prepare are closed before SMTP.
            sender(*prepared)
            finish(factory, job_id, lease, True)
    except Exception:
        # SMTP/driver exceptions may contain recipients or credentials. No logging.
        finish(factory, job_id, lease, False)
    return True
