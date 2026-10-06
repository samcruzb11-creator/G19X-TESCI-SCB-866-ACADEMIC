"""Adaptive challenge verification, outside SQL transactions and hashing slots.

Cloudflare owns token expiry/single-use. Nothing here persists tokens or trusts
forwarded IPs. Local outgoing budgets require ONE FastAPI process, as in 6B.4A.
"""
from collections import deque
from datetime import datetime, timezone
import json
import logging
import re
from threading import Lock
from time import monotonic
from uuid import uuid4

import httpx
from fastapi import HTTPException

from app.core.config import settings

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
ACTIONS = frozenset({"login", "access_request", "password_reset_request"})
CHALLENGE_MESSAGE = "Se requiere verificación adicional."
UNAVAILABLE_MESSAGE = "No podemos completar la verificación en este momento. Intenta más tarde."
# Public dummy secrets, deliberately never used as a default.
TEST_SECRETS = frozenset({
    "1x0000000000000000000000000000000AA",
    "2x0000000000000000000000000000000AA",
    "3x0000000000000000000000000000000AA",
})
_HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\Z", re.ASCII)
# Tokens are opaque: reject control/space/non-ASCII/HTML rather than assuming a
# particular Cloudflare prefix or minimum length not guaranteed by its contract.
_TOKEN = re.compile(r"[A-Za-z0-9_.=-]+\Z", re.ASCII)
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                        r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z", re.ASCII)
_ERROR_CODE = re.compile(r"[a-z-]{1,64}\Z", re.ASCII)
_RESPONSE_LIMIT = 16384
_INVALID_TOKEN_CODES = frozenset({"missing-input-response", "invalid-input-response", "timeout-or-duplicate"})
_TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})
logger = logging.getLogger(__name__)


class ChallengeRequired(HTTPException):
    def __init__(self, action: str):
        super().__init__(428, detail=CHALLENGE_MESSAGE, headers={"Cache-Control": "no-store"})
        self.public_body = {"detail": CHALLENGE_MESSAGE, "challenge_required": True,
                            "challenge_action": action}


def challenge(action: str) -> ChallengeRequired:
    if action not in ACTIONS:
        raise unavailable()
    logger.info("event=turnstile_required action=%s", action)
    return ChallengeRequired(action)


def unavailable() -> HTTPException:
    # Do not attach upstream exceptions: requests/responses may contain secrets.
    logger.warning("event=turnstile_unavailable")
    return HTTPException(503, detail=UNAVAILABLE_MESSAGE,
                         headers={"Cache-Control": "no-store"})


def enabled() -> bool:
    # An invalid operational mode must never become an automatic fail-open.
    return settings.turnstile_mode != "disabled"


def expected_hostnames() -> frozenset[str]:
    raw = settings.turnstile_expected_hostnames
    if not isinstance(raw, str) or not raw:
        raise ValueError("Invalid Turnstile configuration")
    names = [name.strip() for name in raw.split(",")]
    if any(not name or len(name) > 253 or not _HOSTNAME.fullmatch(name) for name in names):
        raise ValueError("Invalid Turnstile configuration")
    return frozenset(names)


def validate_turnstile_config() -> None:
    """Startup validation; secret values never enter exception messages."""
    if settings.turnstile_mode == "disabled":
        return
    try:
        if settings.turnstile_mode not in {"enabled", "test"}:
            raise ValueError
        secret = settings.turnstile_secret_key.get_secret_value()
        if not secret or len(secret) > 1024 or not _TOKEN.fullmatch(secret):
            raise ValueError
        if (settings.turnstile_mode == "test") != (secret in TEST_SECRETS):
            raise ValueError
        if settings.turnstile_mode == "test" and settings.app_env.lower() == "production":
            raise ValueError
        expected_hostnames()
        if not (0.1 <= settings.turnstile_verify_timeout_seconds <= 10
                and 1 <= settings.turnstile_verify_global_per_minute <= 100000
                and 1 <= settings.turnstile_verify_concurrency <= 32):
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise RuntimeError("Invalid Turnstile configuration") from None


class VerifyBudget:
    """Bound actual HTTP attempts (including retries) and active validations."""
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.lock = Lock()
        self.requests = deque()
        self.active = 0

    def acquire(self, *, retry: bool = False) -> None:
        if not self.lock.acquire(blocking=False):
            raise unavailable()
        try:
            now = self.clock()
            while self.requests and self.requests[0] <= now - 60:
                self.requests.popleft()
            if (len(self.requests) >= settings.turnstile_verify_global_per_minute
                    or (not retry and self.active >= settings.turnstile_verify_concurrency)):
                raise unavailable()
            self.requests.append(now)
            if not retry:
                self.active += 1
        finally:
            self.lock.release()

    def release(self) -> None:
        with self.lock:
            self.active -= 1


verify_budget = VerifyBudget()


def _post(payload: dict) -> httpx.Response:
    # Fixed URL, no redirects, no inherited proxy credentials/environment and no
    # request headers or remoteip. Only this function touches the network.
    started = monotonic()
    with httpx.Client(timeout=settings.turnstile_verify_timeout_seconds,
                      follow_redirects=False, trust_env=False) as client:
        # Bound the download, not just the already-buffered response. Declining
        # compression also avoids decompression bombs before our byte limit.
        with client.stream("POST", SITEVERIFY_URL, data=payload,
                           headers={"Accept-Encoding": "identity"}) as response:
            if response.status_code != 200:
                return httpx.Response(response.status_code)
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("Invalid verification response")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isascii() or not length.isdecimal()
                                       or int(length) > _RESPONSE_LIMIT):
                raise ValueError("Invalid verification response")
            body = bytearray()
            for chunk in response.iter_raw():
                if len(body) + len(chunk) > _RESPONSE_LIMIT:
                    raise ValueError("Invalid verification response")
                if monotonic() - started > settings.turnstile_verify_timeout_seconds:
                    raise httpx.ReadTimeout("Verification deadline exceeded")
                body.extend(chunk)
            # Detached response: never retain the outgoing secret/token request.
            return httpx.Response(response.status_code, content=bytes(body))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Invalid verification response")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Invalid verification response")


def _response_json(content: bytes):
    # The standard JSON decoder otherwise accepts duplicate keys and NaN. An
    # ambiguous success/failure object must not authorize an operation.
    body = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=_invalid_constant)
    pending, visited = [(body, 0)], 0
    while pending:
        value, depth = pending.pop()
        visited += 1
        if depth > 16 or visited > 256:
            raise ValueError("Invalid verification response")
        if isinstance(value, dict):
            pending.extend((item, depth + 1) for pair in value.items() for item in pair)
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
        elif isinstance(value, str):
            if len(value) > 2048:
                raise ValueError("Invalid verification response")
            value.encode("utf-8")  # Reject unpaired surrogate escapes, too.
    return body


def _failure(action: str) -> None:
    logger.info("event=turnstile_failure action=%s", action)
    raise ChallengeRequired(action)


def _validate_success(body: dict, action: str) -> None:
    if not all(isinstance(body.get(key), str) for key in ("action", "hostname", "challenge_ts")):
        raise unavailable()
    if body["action"] != action or body["hostname"] not in expected_hostnames():
        _failure(action)
    try:
        if not _TIMESTAMP.fullmatch(body["challenge_ts"]):
            raise ValueError
        stamp = datetime.fromisoformat(body["challenge_ts"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
    except (ValueError, TypeError, OverflowError):
        raise unavailable() from None
    # Cloudflare enforces 300 s too. Permit at most 30 s future clock skew, never
    # extend the 300-second past age. Hosts should synchronize their clocks.
    if age > 300 or age < -30:
        _failure(action)


def verify(token: object, action: str) -> None:
    """Verify only AFTER the caller has decided a challenge is required.

    Callers must re-admit after return, because hard limits may change during
    HTTP. No method here acquires an SQL transaction, hashes or resets counters.
    """
    try:
        validate_turnstile_config()
    except RuntimeError:
        raise unavailable() from None
    if not enabled() or action not in ACTIONS:
        raise unavailable()
    logger.info("event=turnstile_required action=%s", action)
    if type(token) is not str or not token or len(token) > 2048 or not _TOKEN.fullmatch(token):
        raise ChallengeRequired(action)

    verify_budget.acquire()
    try:
        payload = {"secret": settings.turnstile_secret_key.get_secret_value(),
                   "response": token, "idempotency_key": str(uuid4())}
        # Exactly two attempts maximum, with one UUID and an outgoing-budget
        # charge per HTTP attempt. Token errors and malformed replies never retry.
        for attempt in range(2):
            if attempt:
                verify_budget.acquire(retry=True)
            try:
                response = _post(payload)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                if attempt == 0:
                    continue
                raise unavailable() from None
            except Exception:
                raise unavailable() from None
            if response.status_code in _TRANSIENT_STATUS:
                if attempt == 0:
                    continue
                raise unavailable()
            if response.status_code != 200 or len(response.content) > _RESPONSE_LIMIT:
                raise unavailable()
            try:
                body = _response_json(response.content)
            except (ValueError, UnicodeError):
                raise unavailable() from None
            if not isinstance(body, dict) or type(body.get("success")) is not bool:
                raise unavailable()
            codes = body.get("error-codes", [])
            if (not isinstance(codes, list) or len(codes) > 16
                    or any(not isinstance(code, str) or not _ERROR_CODE.fullmatch(code) for code in codes)):
                raise unavailable()
            if body["success"]:
                if codes:
                    raise unavailable()
                _validate_success(body, action)
                logger.info("event=turnstile_success action=%s", action)
                return
            if codes and set(codes) <= _INVALID_TOKEN_CODES:
                _failure(action)
            if codes == ["internal-error"] and attempt == 0:
                continue
            # Provider/configuration errors and unknown codes are unavailable,
            # never an invitation to enter credentials while verification failed.
            raise unavailable()
        raise unavailable()
    except HTTPException:
        raise
    except Exception:
        # Includes malformed/over-nested JSON and unforeseen client internals.
        # Neither upstream exception text nor credentials reach server logging.
        raise unavailable() from None
    finally:
        verify_budget.release()
