"""Separate 6C budgets. Global admission assumes one API process, as in 6B.4A."""
from collections import defaultdict, deque
import logging
from threading import Lock
from time import monotonic
from datetime import timedelta
from math import ceil
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.dialects.mysql import insert
from app.core.config import settings
from app.models.account_access import AuthActionLimit
from app.services import turnstile

PUBLIC_CHALLENGES = {'ACCESS_REQUEST': 'access_request', 'RESET_REQUEST': 'password_reset_request'}


def limited(seconds=1):
    logging.getLogger(__name__).info('event=auth_hard_rate_limit scope=account_action')
    return HTTPException(429, detail={'code': 'auth_action_rate_limited',
        'message': 'Demasiados intentos. Intente nuevamente más tarde.'},
        headers={'Retry-After': str(max(1, ceil(seconds)))})


class ActionBudget:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.lock = Lock()
        self.windows = defaultdict(deque)
        self.hash_active = False

    def take(self, scope, maximum, hashing=False):
        if not self.lock.acquire(blocking=False):
            raise limited()
        try:
            now = self.clock()
            window = self.windows[scope]
            while window and window[0] <= now - 60:
                window.popleft()
            if len(window) >= maximum:
                raise limited(window[0] + 60 - now)
            if hashing and self.hash_active:
                raise limited()
            window.append(now)
            if hashing:
                self.hash_active = True
        finally:
            self.lock.release()

    def release_hash(self):
        with self.lock:
            self.hash_active = False

    def challenge_required(self, action):
        maximum = {'ACCESS_REQUEST': settings.access_request_global_per_minute,
                   'RESET_REQUEST': settings.reset_request_global_per_minute}[action]
        with self.lock:
            now = self.clock()
            window = self.windows[action]
            while window and window[0] <= now - 60:
                window.popleft()
            return len(window) >= ceil(maximum / 2)


budget = ActionBudget()


def admit(db, action, identifier, *, commit=True, challenge_verified=False):
    maximum, duration = {
        'RESET_REQUEST': (settings.reset_request_per_hour, 3600),
        'ACCESS_REQUEST': (settings.access_request_per_day, 86400),
        'PASSWORD_RESET': (settings.action_confirm_per_minute, 60),
        'INITIAL_PASSWORD': (settings.action_confirm_per_minute, 60),
        'INITIAL_SEND': (settings.reset_request_per_hour, 3600),
    }[action]
    try:
        now = db.scalar(select(func.utc_timestamp(6)))
        stmt = insert(AuthActionLimit).values(action=action, identifier=identifier,
            window_start=now, count=0, expires_at=now + timedelta(seconds=duration))
        db.execute(stmt.on_duplicate_key_update(identifier=AuthActionLimit.identifier))
        row = db.scalar(select(AuthActionLimit).where(AuthActionLimit.action == action,
            AuthActionLimit.identifier == identifier).with_for_update().execution_options(populate_existing=True))
        now = db.scalar(select(func.utc_timestamp(6)))
        if now >= row.window_start + timedelta(seconds=duration):
            row.window_start, row.count = now, 0
        if row.count >= maximum:
            raise limited((row.window_start + timedelta(seconds=duration) - now).total_seconds())
        if (action in PUBLIC_CHALLENGES and turnstile.enabled() and not challenge_verified
                and (row.count >= 1 or budget.challenge_required(action))):
            raise turnstile.challenge(PUBLIC_CHALLENGES[action])
        row.count += 1
        row.expires_at = row.window_start + timedelta(seconds=duration)
        if commit:
            db.commit()
        else:
            db.flush()
    except Exception:
        db.rollback()
        raise


def adaptive_admit(db, action, identifier, token=None):
    """One external verification at most, between two short DB admissions."""
    try:
        return admit(db, action, identifier)
    except turnstile.ChallengeRequired:
        # admit's rollback also undoes a new bucket/expired window reset.
        turnstile.verify(token.get_secret_value() if token is not None else None, PUBLIC_CHALLENGES[action])
    return admit(db, action, identifier, challenge_verified=True)


class ActionAdmissionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        import re
        from fastapi import HTTPException
        from starlette.responses import JSONResponse
        from starlette.datastructures import MutableHeaders
        prefix = settings.api_v1_prefix
        private = scope['type'] == 'http' and (scope['path'].startswith(prefix + '/auth/')
            or scope['path'].startswith(prefix + '/access-requests'))

        async def protected_send(message):
            if private and message['type'] == 'http.response.start':
                headers = MutableHeaders(scope=message)
                headers['Cache-Control'] = 'no-store'
                headers['Referrer-Policy'] = 'no-referrer'
            await send(message)

        if scope['type'] == 'http' and scope['method'] == 'POST':
            routes = {
                prefix + '/auth/access-requests': ('ACCESS_REQUEST', settings.access_request_global_per_minute),
                prefix + '/auth/password-reset/request': ('RESET_REQUEST', settings.reset_request_global_per_minute),
                prefix + '/auth/password-reset/confirm': ('CONFIRM', settings.action_confirm_global_per_minute),
                prefix + '/auth/initial-password/confirm': ('CONFIRM', settings.action_confirm_global_per_minute),
            }
            rule = routes.get(scope['path'].rstrip('/'))
            if re.fullmatch(re.escape(prefix) + r'/access-requests/[^/]+/(?:approve|resend)/?', scope['path']):
                rule = ('INITIAL_SEND', settings.reset_request_global_per_minute)
            if rule:
                try:
                    budget.take(*rule)
                except HTTPException as exc:
                    await JSONResponse({'detail': exc.detail}, status_code=429,
                        headers=exc.headers)(scope, receive, protected_send)
                    return
        await self.app(scope, receive, protected_send)
