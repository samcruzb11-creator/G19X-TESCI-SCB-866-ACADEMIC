"""Local login admission. Global budgets require exactly ONE API process.

No user lookup, origin trust, credentials, sleeps or external calls here.
MySQL collation is authoritative for identifier equivalence.
"""
from collections import deque
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from threading import Lock
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import select, update, func
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import normalize_email
from app.models.auth import AuthLoginLimit
from app.services import turnstile

MESSAGE = "Demasiados intentos. Intente nuevamente más tarde."
RETENTION_SECONDS = 1200


def limited(seconds=1):
    logging.getLogger(__name__).info('event=auth_hard_rate_limit action=login')
    return HTTPException(429, detail={"code": "login_rate_limited", "message": MESSAGE},
                         headers={"Retry-After": str(max(1, ceil(seconds)))})


def trusted_client_origin(request) -> str | None:
    # PHP is the network peer. No configured boundary authenticates forwarded IPs.
    return None


class GlobalLoginBudget:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.lock = Lock()
        self.requests = deque()
        self.verifications = deque()
        self.active = 0
        self.pending = set()

    def _budget(self, queue, limit, now):
        while queue and queue[0] <= now - 60:
            queue.popleft()
        if len(queue) >= limit:
            raise limited(queue[0] + 60 - now)

    def request(self):
        if not self.lock.acquire(blocking=False):
            raise limited()
        try:
            now = self.clock()
            self._budget(self.requests, settings.rate_limit_login_requests_per_minute, now)
            self.requests.append(now)
        finally:
            self.lock.release()

    def acquire_argon2(self):
        if not self.lock.acquire(blocking=False):
            raise limited()
        try:
            now = self.clock()
            self._budget(self.verifications, settings.rate_limit_argon2_per_minute, now)
            if self.active >= settings.rate_limit_argon2_concurrency:
                raise limited()
            self.verifications.append(now)
            self.active += 1
        finally:
            self.lock.release()

    def release_argon2(self):
        # Only a tiny bookkeeping critical section; never held during DB/Argon2.
        with self.lock:
            self.active -= 1

    def challenge_required(self):
        # Inspect the existing request window; never append or refresh on a check.
        with self.lock:
            now = self.clock()
            while self.requests and self.requests[0] <= now - 60:
                self.requests.popleft()
            return len(self.requests) >= ceil(settings.rate_limit_login_requests_per_minute / 2)

    def pending_count(self, identifier, window):
        with self.lock:
            return sum(r.identifier == identifier and r.window == window for r in self.pending)

    def track(self, reservation):
        with self.lock:
            self.pending.add(reservation)

    def finish(self, reservation):
        with self.lock:
            self.pending.discard(reservation)


global_budget = GlobalLoginBudget()


@dataclass(frozen=True)
class Reservation:
    identifier: str
    window: datetime
    attempt: object = None


def reserve(db: Session, identifier: str, *, challenge_verified=False) -> Reservation:
    """Commit a reservation only if identifier AND global Argon2 budgets admit it.

    Acquiring the in-memory slot inside this short transaction avoids refreshing
    retention on a global rejection. It performs no hashing or waiting for a slot.
    The caller owns the slot after return, even if its subsequent work fails.
    """
    identifier = normalize_email(identifier)
    acquired = False
    reservation = None
    try:
        now = db.scalar(select(func.utc_timestamp(6)))
        stmt = insert(AuthLoginLimit).values(identifier=identifier, request_window=now,
            request_count=0, failure_window=now, failure_count=0,
            expires_at=now + timedelta(seconds=RETENTION_SECONDS))
        # Atomic insert-or-lock, including equivalent spellings under MySQL.
        db.execute(stmt.on_duplicate_key_update(identifier=AuthLoginLimit.identifier))
        row = db.scalar(select(AuthLoginLimit).where(AuthLoginLimit.identifier == identifier)
                        .with_for_update().execution_options(populate_existing=True))
        now = db.scalar(select(func.utc_timestamp(6)))  # after acquiring the row
        if now >= row.request_window + timedelta(seconds=60):
            row.request_window, row.request_count = now, 0
        if now >= row.failure_window + timedelta(seconds=settings.rate_limit_failure_window_seconds):
            row.failure_window, row.failure_count = now, 0
        waits = []
        if row.request_count >= settings.rate_limit_identifier_requests_per_minute:
            waits.append((row.request_window + timedelta(seconds=60) - now).total_seconds())
        if row.failure_count >= settings.rate_limit_challenge_failures:
            waits.append((row.failure_window + timedelta(seconds=settings.rate_limit_failure_window_seconds) - now).total_seconds())
        if waits:
            raise limited(max(waits))
        adaptive = turnstile.enabled()
        if adaptive and not challenge_verified:
            # The stored spelling comes from MySQL's collation-equivalent row.
            # Pending Argon2 attempts are hard reservations, not real failures.
            failures = row.failure_count - global_budget.pending_count(row.identifier, row.failure_window)
            if failures >= 3 or global_budget.challenge_required():
                raise turnstile.challenge('login')
        global_budget.acquire_argon2()
        acquired = True
        row.request_count += 1
        row.failure_count += 1
        row.expires_at = now + timedelta(seconds=RETENTION_SECONDS)
        reservation = Reservation(row.identifier if adaptive else identifier, row.failure_window,
                                  object() if adaptive else None)
        if adaptive:
            # Register before committing (and releasing the row lock). Observers
            # cannot count this reservation as a completed credential failure.
            global_budget.track(reservation)
        db.commit()
        return reservation
    except Exception:
        try:
            db.rollback()
        finally:
            global_budget.finish(reservation)
            if acquired:
                global_budget.release_argon2()
        raise


def adaptive_reserve(db: Session, identifier: str, token=None) -> Reservation:
    try:
        return reserve(db, identifier)
    except turnstile.ChallengeRequired:
        # reserve rolled back: no SQL transaction/row lock during the HTTP call.
        turnstile.verify(token.get_secret_value() if token is not None else None, 'login')
    # Recheck current hard state under the same authoritative row lock. This is
    # one admitted request, not a second request/global-budget charge.
    return reserve(db, identifier, challenge_verified=True)


def release_reservation(db: Session, reservation: Reservation):
    """Release only this attempt, never a later window or the previous failures."""
    try:
        db.execute(update(AuthLoginLimit).where(
            AuthLoginLimit.identifier == reservation.identifier,
            AuthLoginLimit.failure_window == reservation.window,
            AuthLoginLimit.failure_count > 0,
        ).values(failure_count=AuthLoginLimit.failure_count - 1))
        # UPDATE holds the row lock: removing the pending marker here cannot
        # expose an undercount to another admission before the commit.
        global_budget.finish(reservation)
        db.commit()
    except Exception:
        try:
            db.rollback()
        finally:
            global_budget.finish(reservation)
        raise


class AuthResponseMiddleware:
    """Early cheap budget (before body parsing) and no-store for auth responses."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        from starlette.datastructures import MutableHeaders
        from starlette.responses import JSONResponse

        auth = scope["type"] == "http" and scope["path"].startswith(settings.api_v1_prefix + "/auth/")

        async def protected_send(message):
            if auth and message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        if auth and scope["method"] == "POST" and scope["path"].rstrip("/") == settings.api_v1_prefix + "/auth/login":
            try:
                global_budget.request()
            except HTTPException as exc:
                await JSONResponse({"detail": exc.detail}, status_code=429, headers=exc.headers)(scope, receive, protected_send)
                return
        await self.app(scope, receive, protected_send)
