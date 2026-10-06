"""Siteverify contracts; completely offline, no SQL and no real credentials."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock
from unittest.mock import Mock
from urllib.parse import parse_qs
from uuid import UUID
import json

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from app.core.config import Settings, settings
from app.services import turnstile as ts


TOKEN = "test.opaque-token_123"
DUMMY_SECRET = "1x0000000000000000000000000000000AA"
REAL_POST = ts._post
FIXED_NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW.astimezone(tz) if tz is not None else FIXED_NOW.replace(tzinfo=None)


def success(**changes):
    return {"success": True, "action": "login", "hostname": "localhost",
            "challenge_ts": FIXED_NOW.isoformat(), "error-codes": []} | changes


def reply(body=None, status=200):
    return httpx.Response(status, json=success() if body is None else body)


@pytest.fixture(autouse=True)
def isolated_turnstile(monkeypatch):
    # Fixtures and parametrized responses use the same clock even if collection
    # precedes this module's execution by a long full-suite run.
    monkeypatch.setattr(ts, "datetime", FrozenDatetime)
    monkeypatch.setattr(settings, "turnstile_mode", "test")
    monkeypatch.setattr(settings, "turnstile_secret_key", SecretStr(DUMMY_SECRET))
    monkeypatch.setattr(settings, "turnstile_expected_hostnames", "localhost,127.0.0.1")
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(ts, "verify_budget", ts.VerifyBudget())
    # All test cases must opt into a double, never accidentally call the network.
    monkeypatch.setattr(ts, "_post", Mock(side_effect=AssertionError("Network forbidden")))


def rejected(call, status):
    with pytest.raises(HTTPException) as exc:
        call()
    assert exc.value.status_code == status
    assert TOKEN not in str(exc.value) and DUMMY_SECRET not in str(exc.value)
    assert exc.value.headers["Cache-Control"] == "no-store"
    return exc.value


@pytest.mark.parametrize("mode", ["disabled", "test", "enabled"])
def test_config_modes(mode):
    config = Settings(_env_file=None, turnstile_mode=mode)
    assert config.turnstile_mode == mode
    assert isinstance(config.turnstile_secret_key, SecretStr)


@pytest.mark.parametrize("field,value", [
    ("turnstile_mode", "automatic"), ("turnstile_verify_timeout_seconds", 0),
    ("turnstile_verify_timeout_seconds", 11), ("turnstile_verify_global_per_minute", 0),
    ("turnstile_verify_concurrency", 0), ("turnstile_verify_concurrency", 33),
])
def test_config_bounds(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_disabled_explicit_no_secret_or_hostname(monkeypatch):
    monkeypatch.setattr(settings, "turnstile_mode", "disabled")
    monkeypatch.setattr(settings, "turnstile_secret_key", SecretStr(""))
    monkeypatch.setattr(settings, "turnstile_expected_hostnames", "")
    assert not ts.enabled()
    ts.validate_turnstile_config()
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    ts._post.assert_not_called()


@pytest.mark.parametrize("mode,secret,valid", [
    ("test", DUMMY_SECRET, True),
    ("test", "2x0000000000000000000000000000000AA", True),
    ("test", "3x0000000000000000000000000000000AA", True),
    ("test", "private-stub-key", False), ("enabled", DUMMY_SECRET, False),
    ("enabled", "private-stub-key", True), ("enabled", "", False),
    ("test", "", False), ("enabled", "private key with whitespace", False),
])
def test_keys_fail_fast(mode, secret, valid, monkeypatch):
    monkeypatch.setattr(settings, "turnstile_mode", mode)
    monkeypatch.setattr(settings, "turnstile_secret_key", SecretStr(secret))
    if valid:
        ts.validate_turnstile_config()
    else:
        with pytest.raises(RuntimeError, match="^Invalid Turnstile configuration$"):
            ts.validate_turnstile_config()
    assert secret == "" or secret not in repr(settings)


def test_test_mode_forbidden_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(RuntimeError):
        ts.validate_turnstile_config()


@pytest.mark.parametrize("hostnames", ["", " ", "localhost,", "https://example.com", "*.example.com",
    "example.com:443", "example.com/path", "evil@localhost", "EXAMPLE.COM", "-bad.com",
    "bad..com", "bad_host.com", "a"*64+".com", "example.com\n.evil"])
def test_hostname_allowlist_fail_fast(hostnames, monkeypatch):
    monkeypatch.setattr(settings, "turnstile_expected_hostnames", hostnames)
    with pytest.raises(RuntimeError):
        ts.validate_turnstile_config()
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    ts._post.assert_not_called()


def test_allowlist_multiple_exact_hosts(monkeypatch):
    monkeypatch.setattr(settings, "turnstile_expected_hostnames", "localhost, app.example.invalid")
    assert ts.expected_hostnames() == {"localhost", "app.example.invalid"}
    ts._post.side_effect = None
    ts._post.return_value = reply(success(hostname="app.example.invalid"))
    ts.verify(TOKEN, "login")


@pytest.mark.parametrize("token", [None, "", " ", "a b", "a\n", "<script>", "é", "a"*2049,
    123, True, [], {}, SecretStr(TOKEN)])
def test_local_invalid_token_never_spends_external_budget(token):
    exc = rejected(lambda: ts.verify(token, "login"), 428)
    assert exc.public_body == {"detail": ts.CHALLENGE_MESSAGE, "challenge_required": True,
                               "challenge_action": "login"}
    ts._post.assert_not_called()
    assert not ts.verify_budget.requests and ts.verify_budget.active == 0


@pytest.mark.parametrize("token", [TOKEN, "a"*2048, "XXXX.DUMMY.TOKEN.XXXX"])
def test_success_and_maximum_token(token):
    ts._post.side_effect = None
    ts._post.return_value = reply()
    ts.verify(token, "login")
    assert ts.verify_budget.active == 0
    assert len(ts.verify_budget.requests) == 1


@pytest.mark.parametrize("action", sorted(ts.ACTIONS))
def test_distinct_expected_actions(action):
    ts._post.side_effect = None
    ts._post.return_value = reply(success(action=action))
    ts.verify(TOKEN, action)


@pytest.mark.parametrize("expected,actual", [(expected, actual)
    for expected in sorted(ts.ACTIONS) for actual in sorted(ts.ACTIONS) if expected != actual])
def test_actions_are_never_interchangeable(expected, actual):
    ts._post.side_effect = None
    ts._post.return_value = reply(success(action=actual))
    rejected(lambda: ts.verify(TOKEN, expected), 428)
    ts._post.assert_called_once()
    assert ts.verify_budget.active == 0


@pytest.mark.parametrize("action", ["test", "LOGIN", "login ", "admin", "initial_password", ""])
def test_no_other_actions_can_initiate_verification(action):
    rejected(lambda: ts.verify(TOKEN, action), 503)
    ts._post.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"action": "access_request"}, {"action": "LOGIN"}, {"action": "login "},
    {"hostname": "localhost.evil.invalid"}, {"hostname": "LOCALHOST"},
    {"hostname": "127.0.0.2"}, {"hostname": "https://localhost"}, {"hostname": "localhost:80"},
    {"challenge_ts": (FIXED_NOW-timedelta(seconds=301)).isoformat()},
    {"challenge_ts": (FIXED_NOW+timedelta(seconds=35)).isoformat()},
])
def test_success_still_rejects_action_hostname_or_expiry(changes):
    ts._post.side_effect = None
    ts._post.return_value = reply(success(**changes))
    rejected(lambda: ts.verify(TOKEN, "login"), 428)
    ts._post.assert_called_once()
    assert ts.verify_budget.active == 0


@pytest.mark.parametrize("body", [[], "private-response", {}, {"success": 1}, {"success": "true"},
    {"success": None}, success(action=None), success(hostname=None), success(challenge_ts=None),
    success(challenge_ts="invalid"), success(challenge_ts="2026-01-01T00:00:00"),
    success(**{"error-codes": "private-error"}), success(**{"error-codes": [None]}),
    success(**{"error-codes": ["internal-error"]}), {"success": False},
])
def test_malformed_response_fail_closed_without_retry(body):
    ts._post.side_effect = None
    ts._post.return_value = reply(body)
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    ts._post.assert_called_once()
    assert ts.verify_budget.active == 0


@pytest.mark.parametrize("code", ["invalid-input-response", "missing-input-response", "timeout-or-duplicate"])
def test_invalid_and_duplicate_tokens_never_retry(code):
    ts._post.side_effect = None
    ts._post.return_value = reply({"success": False, "error-codes": [code]})
    rejected(lambda: ts.verify(TOKEN, "login"), 428)
    ts._post.assert_called_once()


@pytest.mark.parametrize("code", ["invalid-input-secret", "missing-input-secret", "bad-request", "unrecognized-private-error"])
def test_provider_configuration_error_fail_closed(code):
    ts._post.side_effect = None
    ts._post.return_value = reply({"success": False, "error-codes": [code]})
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    ts._post.assert_called_once()


@pytest.mark.parametrize("first", [httpx.ReadTimeout("private-token"), httpx.ConnectError("private-secret"),
    httpx.RemoteProtocolError("private"), reply(status=408), reply(status=429), reply(status=500),
    reply(status=502), reply(status=503), reply(status=504),
    reply({"success": False, "error-codes": ["internal-error"]})])
def test_transient_retry_same_uuid_and_payload(first):
    ts._post.side_effect = [first, reply()]
    ts.verify(TOKEN, "login")
    assert ts._post.call_count == 2
    first_payload, second_payload = [call.args[0] for call in ts._post.call_args_list]
    assert first_payload == second_payload
    assert UUID(first_payload["idempotency_key"]).version == 4
    assert set(first_payload) == {"secret", "response", "idempotency_key"}
    assert len(ts.verify_budget.requests) == 2 and ts.verify_budget.active == 0


@pytest.mark.parametrize("error", [httpx.ReadTimeout("private"), httpx.ConnectError("private"),
    reply(status=503), reply({"success": False, "error-codes": ["internal-error"]})])
def test_at_most_one_retry_unavailable(error):
    ts._post.side_effect = [error, error]
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    assert ts._post.call_count == 2 and ts.verify_budget.active == 0


@pytest.mark.parametrize("response", [reply(status=301), reply(status=400), reply(status=403),
    httpx.Response(200, content=b"{"), httpx.Response(200, content=b"a"*16385)])
def test_no_redirects_malformed_json_or_blind_retries(response):
    ts._post.side_effect = None
    ts._post.return_value = response
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    ts._post.assert_called_once()


def test_internal_exception_never_propagates_secrets(caplog):
    ts._post.side_effect = RuntimeError(TOKEN + DUMMY_SECRET)
    exc = rejected(lambda: ts.verify(TOKEN, "login"), 503)
    assert exc.__suppress_context__
    assert TOKEN not in caplog.text and DUMMY_SECRET not in caplog.text
    ts._post.assert_called_once()


@pytest.mark.parametrize("response", [object(), httpx.Response(200, content=b"["*4000+b"]"*4000)])
def test_unexpected_provider_response_internals_still_return_503(response):
    ts._post.side_effect = None
    ts._post.return_value = response
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    ts._post.assert_called_once()
    assert ts.verify_budget.active == 0


def test_logging_contains_only_fixed_events_and_actions(caplog):
    caplog.set_level("INFO", logger=ts.__name__)
    ts._post.side_effect = [reply(), reply({"success": False, "error-codes": ["timeout-or-duplicate"]})]
    ts.verify(TOKEN, "login")
    rejected(lambda: ts.verify(TOKEN, "login"), 428)
    assert "turnstile_required" in caplog.text
    assert "turnstile_success" in caplog.text
    assert "turnstile_failure" in caplog.text
    assert TOKEN not in caplog.text and DUMMY_SECRET not in caplog.text
    assert "timeout-or-duplicate" not in caplog.text and "challenge_ts" not in caplog.text


def test_token_single_use_authority_stays_at_cloudflare():
    consumed = set()
    def provider(payload):
        if payload["response"] in consumed:
            return reply({"success": False, "error-codes": ["timeout-or-duplicate"]})
        consumed.add(payload["response"])
        return reply()
    ts._post.side_effect = provider
    ts.verify(TOKEN, "login")
    rejected(lambda: ts.verify(TOKEN, "login"), 428)
    assert ts._post.call_count == 2
    # Tokens never enter the local budget, whose only values are clock numbers.
    assert all(isinstance(item, (float, int)) for item in ts.verify_budget.requests)


def test_simultaneous_replay_has_one_success_one_rejection():
    consumed, authority_lock, barrier = set(), Lock(), Barrier(2)
    def provider(payload):
        barrier.wait(timeout=5)
        with authority_lock:
            if payload["response"] in consumed:
                return reply({"success": False, "error-codes": ["timeout-or-duplicate"]})
            consumed.add(payload["response"])
            return reply()
    ts._post.side_effect = provider
    def attempt(_):
        try:
            ts.verify(TOKEN, "login")
            return 200
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [200, 428]
    assert ts.verify_budget.active == 0
    calls = [call.args[0] for call in ts._post.call_args_list]
    assert calls[0]["idempotency_key"] != calls[1]["idempotency_key"]


def test_http_challenge_contract_top_level_no_sensitive_input(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.session import get_db
    from app.services import login_protection
    monkeypatch.setattr(login_protection, "adaptive_reserve", Mock(side_effect=ts.challenge("login")))
    app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/auth/login", json={
                "correo": "hidden@example.invalid", "password": "private-password", "turnstile_token": TOKEN})
        assert response.status_code == 428
        assert response.json() == {"detail": ts.CHALLENGE_MESSAGE, "challenge_required": True,
                                   "challenge_action": "login"}
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "Retry-After" not in response.headers
        assert TOKEN not in response.text and "private-password" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_startup_fails_when_enabled_secret_absent(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr(settings, "turnstile_mode", "enabled")
    monkeypatch.setattr(settings, "turnstile_secret_key", SecretStr(""))
    with pytest.raises(RuntimeError, match="^Invalid Turnstile configuration$"):
        with TestClient(app):
            pytest.fail("Startup must fail before serving HTTP")


def test_budget_rejection_does_not_extend_window(monkeypatch):
    now = [0.0]
    budget = ts.VerifyBudget(clock=lambda: now[0])
    monkeypatch.setattr(settings, "turnstile_verify_global_per_minute", 1)
    budget.acquire(); budget.release()
    now[0] = 59
    rejected(budget.acquire, 503)
    assert list(budget.requests) == [0]
    now[0] = 60
    budget.acquire(); budget.release()


def test_retry_charges_actual_http_and_never_exceeds_budget(monkeypatch):
    monkeypatch.setattr(settings, "turnstile_verify_global_per_minute", 1)
    ts._post.side_effect = httpx.ConnectTimeout("private")
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    ts._post.assert_called_once()
    assert ts.verify_budget.active == 0


def test_parallel_external_slots_bounded_without_waiting():
    budget = ts.VerifyBudget()
    barrier = Barrier(12)
    def attempt(_):
        barrier.wait(timeout=5)
        try:
            budget.acquire()
            return True
        except HTTPException:
            return False
    with ThreadPoolExecutor(max_workers=12) as pool:
        admitted = sum(pool.map(attempt, range(12)))
    assert admitted == 4 and budget.active == 4 and len(budget.requests) == 4
    for _ in range(admitted):
        budget.release()
    assert budget.active == 0


def test_parallel_timeouts_release_all_slots():
    barrier = Barrier(4)
    def timeout(_):
        barrier.wait(timeout=5)
        raise httpx.ReadTimeout("private")
    ts._post.side_effect = timeout
    def attempt(_):
        return rejected(lambda: ts.verify(TOKEN, "login"), 503).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(attempt, range(4))) == [503]*4
    assert ts._post.call_count == 8 and ts.verify_budget.active == 0


def test_busy_budget_lock_fails_immediately():
    with ts.verify_budget.lock:
        rejected(lambda: ts.verify(TOKEN, "login"), 503)
    ts._post.assert_not_called()


def test_transport_endpoint_timeout_no_remoteip_or_proxy_headers(monkeypatch):
    requests = []
    original_client = httpx.Client

    def provider(request):
        requests.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(success()).encode()))

    factory = Mock(side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(provider), **kwargs))
    monkeypatch.setattr(ts.httpx, "Client", factory)
    payload = {"secret": DUMMY_SECRET, "response": TOKEN, "idempotency_key": "uuid"}
    assert REAL_POST(payload).json() == success()
    factory.assert_called_once_with(timeout=5, follow_redirects=False, trust_env=False)
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == ts.SITEVERIFY_URL and request.method == "POST"
    assert parse_qs(request.content.decode()) == {key: [value] for key, value in payload.items()}
    assert not {"remoteip", "x-forwarded-for", "x-real-ip", "forwarded", "cf-connecting-ip"} & set(request.headers)
    assert request.extensions["timeout"] == dict(connect=5, read=5, write=5, pool=5)


@pytest.mark.parametrize("age,status", [(-35, 428), (-30.000001, 428), (-30, 200),
    (0, 200), (300, 200), (300.000001, 428)])
def test_timestamp_security_boundaries_use_one_clock(age, status):
    ts._post.side_effect = None
    ts._post.return_value = reply(success(challenge_ts=(FIXED_NOW-timedelta(seconds=age)).isoformat()))
    if status == 200:
        ts.verify(TOKEN, "login")
    else:
        rejected(lambda: ts.verify(TOKEN, "login"), status)
    assert ts.verify_budget.active == 0


@pytest.mark.parametrize("stamp", [
    "2026-10-05\u202812:00:00+00:00", "2026-10-05\x0012:00:00+00:00",
    "2026-10-05\U0001f60012:00:00+00:00", "2026-10-05T12:00:00+00:00:01",
    "2026-10-05T12:00:00,123Z", "20261005T120000Z", "2026-W41-1T12:00:00Z",
    "2026-10-05T12:00:00+99:00", "2026-02-30T12:00:00Z", "x"*12000,
    "2026-10-05T13:39:00+00:99",
], ids=["line-separator", "nul", "emoji", "offset-seconds", "comma", "basic", "week-date",
        "offset-range", "calendar", "huge", "offset-minutes"])
def test_non_wire_timestamp_forms_fail_closed(stamp):
    ts._post.side_effect = None
    ts._post.return_value = reply(success(challenge_ts=stamp))
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    ts._post.assert_called_once()
    assert ts.verify_budget.active == 0


@pytest.mark.parametrize("field,value", [(field, value)
    for field in ["success", "action", "hostname", "challenge_ts"]
    for value in [None, 1, [], {}, True] if not (field == "success" and value is True)])
def test_adversarial_required_field_types(field, value):
    ts._post.side_effect = None
    ts._post.return_value = reply(success(**{field: value}))
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    assert ts.verify_budget.active == 0


@pytest.mark.parametrize("field", ["success", "action", "hostname", "challenge_ts"])
def test_missing_required_provider_fields(field):
    body = success()
    del body[field]
    ts._post.side_effect = None
    ts._post.return_value = reply(body)
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    ts._post.assert_called_once()
    assert ts.verify_budget.active == 0


@pytest.mark.parametrize("extra", [
    '"success":false,', '"metadata":{"x":1,"x":2},',
    '"metadata":NaN,', '"metadata":Infinity,', '"metadata":-Infinity,',
    '"metadata":'+ '['*100+'0'+']'*100+',',
    '"metadata":'+ '['+','.join('0' for _ in range(4000))+']'+',',
], ids=["duplicate-success", "nested-duplicate", "nan", "infinity", "negative-infinity", "depth", "huge-list"])
def test_ambiguous_or_excessive_json_is_unavailable(extra):
    wire = '{' + extra + json.dumps(success())[1:]
    ts._post.side_effect = None
    ts._post.return_value = httpx.Response(200, content=wire.encode())
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    ts._post.assert_called_once()
    assert ts.verify_budget.active == 0


@pytest.mark.parametrize("codes", [["invalid-input-response"]*400, ["x"*12000], ["\ud800"],
    ["\u202einternal-error"], ["internal-error", "invalid-input-response"], {"private": "bad"}])
def test_adversarial_error_codes_fail_closed(codes):
    ts._post.side_effect = None
    # json.dumps intentionally emits isolated surrogate escapes as hostile JSON.
    ts._post.return_value = httpx.Response(200, content=json.dumps({"success": False, "error-codes": codes}).encode())
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    ts._post.assert_called_once()
    assert ts.verify_budget.active == 0


@pytest.mark.parametrize("raw", [b"", b"null", b"false", b"42", b"\xff", b"[]", b"a"*100000],
    ids=["empty", "null", "false", "number", "non-utf8", "array", "huge-body"])
def test_invalid_wire_json_never_retries_or_leaks_slots(raw):
    ts._post.side_effect = None
    ts._post.return_value = httpx.Response(200, content=raw)
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    ts._post.assert_called_once()
    assert ts.verify_budget.active == 0


class HostileStream(httpx.SyncByteStream):
    def __init__(self, chunk, count=100):
        self.chunk, self.count, self.reads, self.closed = chunk, count, 0, False

    def __iter__(self):
        for _ in range(self.count):
            self.reads += 1
            yield self.chunk

    def close(self):
        self.closed = True


@pytest.mark.parametrize("encoding", [None, "gzip"])
def test_transport_stops_oversize_or_encoded_body_before_buffering(monkeypatch, encoding):
    stream = HostileStream(b"x"*1024)
    original_client = httpx.Client
    headers = {} if encoding is None else {"Content-Encoding": encoding}
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, stream=stream, headers=headers)

    factory = Mock(side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(ts.httpx, "Client", factory)
    monkeypatch.setattr(ts, "_post", REAL_POST)
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    assert stream.closed and stream.reads <= (17 if encoding is None else 0)
    assert len(requests) == 1 and ts.verify_budget.active == 0
    assert requests[0].headers["Accept-Encoding"] == "identity"


@pytest.mark.parametrize("length", ["16385", "999999999999999999", "-1", "private", "1, 1"])
def test_transport_rejects_bad_length_without_reading(monkeypatch, length):
    stream = HostileStream(b"x"*1024)
    original_client = httpx.Client
    factory = Mock(side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, stream=stream, headers={"Content-Length": length})), **kwargs))
    monkeypatch.setattr(ts.httpx, "Client", factory)
    monkeypatch.setattr(ts, "_post", REAL_POST)
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    assert stream.closed and stream.reads == 0
    assert factory.call_count == 1 and ts.verify_budget.active == 0


@pytest.mark.parametrize("status", [201, 204, 301, 400, 403, 408, 429, 500, 503])
def test_transport_never_downloads_error_bodies(monkeypatch, status):
    streams = []
    original_client = httpx.Client

    def provider(_):
        stream = HostileStream(b"x"*1024)
        streams.append(stream)
        return httpx.Response(status, stream=stream)

    monkeypatch.setattr(ts.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(provider), **kwargs))
    monkeypatch.setattr(ts, "_post", REAL_POST)
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    assert len(streams) == (2 if status in {408, 429, 500, 503} else 1)
    assert all(stream.closed and stream.reads == 0 for stream in streams)
    assert ts.verify_budget.active == 0


@pytest.mark.parametrize("fault", ["reset", "timeout", "slow-stream"])
def test_transport_read_fault_closes_connections_and_retry_budget(monkeypatch, fault):
    original_client = httpx.Client
    streams, payloads, now = [], [], [0.0]

    class FaultStream(HostileStream):
        def __iter__(self):
            if fault == "reset":
                raise httpx.ReadError("private upstream reset")
            if fault == "timeout":
                raise httpx.ReadTimeout("private upstream timeout")
            for _ in range(100):
                self.reads += 1
                now[0] += 3
                yield b" "

    def provider(request):
        payloads.append(request.content)
        stream = FaultStream(b"")
        streams.append(stream)
        return httpx.Response(200, stream=stream)

    monkeypatch.setattr(ts, "monotonic", lambda: now[0])
    monkeypatch.setattr(ts.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(provider), **kwargs))
    monkeypatch.setattr(ts, "_post", REAL_POST)
    rejected(lambda: ts.verify(TOKEN, "login"), 503)
    assert len(streams) == 2 and payloads[0] == payloads[1]
    assert all(stream.closed and stream.reads <= 2 for stream in streams)
    assert ts.verify_budget.active == 0 and len(ts.verify_budget.requests) == 2


@pytest.mark.parametrize("stamp", ["2026-10-05T12:00:00Z", "2026-10-05T12:00:00.000000Z",
    "2026-10-05T18:00:00+06:00", "2026-10-05T06:00:00-06:00"])
def test_valid_timestamp_wire_forms(stamp):
    ts._post.side_effect = None
    ts._post.return_value = reply(success(challenge_ts=stamp))
    ts.verify(TOKEN, "login")
    assert ts.verify_budget.active == 0


def test_future_sample_ages_between_collection_and_execution(monkeypatch):
    # Explains changes9: a +35 s sample is only +29 s after six seconds of suite
    # execution. Its expectation needs the same frozen clock as the validator.
    elapsed = [0]

    class AdvancingDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return (FIXED_NOW + timedelta(seconds=elapsed[0])).astimezone(tz)

    monkeypatch.setattr(ts, "datetime", AdvancingDatetime)
    ts._post.side_effect = None
    ts._post.return_value = reply(success(challenge_ts=(FIXED_NOW+timedelta(seconds=35)).isoformat()))
    rejected(lambda: ts.verify(TOKEN, "login"), 428)
    elapsed[0] = 6
    ts.verify(TOKEN, "login")
