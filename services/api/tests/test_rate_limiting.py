# services/api/tests/test_rate_limiting.py
# ============================================================
# Teste pentru rate limiting pe IP-ul real și blocarea per username
# ============================================================
# În producție uvicorn rulează cu:
#   --proxy-headers --forwarded-allow-ips=172.30.10.0/24   (entrypoint.sh)
# Aici împachetăm aplicația în același ProxyHeadersMiddleware din uvicorn,
# iar ASGITransport(client=...) simulează IP-ul conexiunii TCP:
#   - 172.30.10.x = nginx (de încredere) → X-Forwarded-For e folosit
#   - alt IP      = client direct        → X-Forwarded-For e ignorat
#
# Scenarii:
#   1. Două IP-uri diferite (prin nginx) au limite separate la /auth/login
#   2. X-Forwarded-For de la un IP care nu e de încredere e ignorat
#   3. Blocarea per username: al 6-lea login e respins chiar cu parola corectă
#   4. Login reușit resetează contorul; blocarea expiră după 15 minute
#   5. /inbox/* nu are limite; toate routerele folosesc limiter-ul comun
# ============================================================

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport
from redis.exceptions import ConnectionError as RedisConnectionError
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from src.main import app
from src.database import get_db
from src.limiter import limiter
from src.models.audit_log import AuditLog, User
from src.services.login_lockout import LOCKOUT_SECONDS, LoginLockout, get_login_lockout

TRUSTED_PROXY_SUBNET = "172.30.10.0/24"   # valoarea implicită din entrypoint.sh
NGINX_IP = "172.30.10.2"
UNTRUSTED_IP = "203.0.113.9"
PASSWORD = "parola-corecta"


# ── Redis fals (get / delete / pipeline INCR+EXPIRE) cu ceas controlabil ──

class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.expires_at: dict[str, float] = {}
        self.now = 0.0

    def _purge(self, key: str) -> None:
        if key in self.expires_at and self.expires_at[key] <= self.now:
            self.data.pop(key, None)
            self.expires_at.pop(key, None)

    async def get(self, key):
        self._purge(key)
        return self.data.get(key)

    async def delete(self, key):
        self.data.pop(key, None)
        self.expires_at.pop(key, None)

    def pipeline(self, transaction=True):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis: FakeRedis):
        self.redis = redis
        self.ops = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def incr(self, key):
        self.ops.append(("incr", key))

    def expire(self, key, seconds):
        self.ops.append(("expire", key, seconds))

    async def execute(self):
        results = []
        for op in self.ops:
            key = op[1]
            self.redis._purge(key)
            if op[0] == "incr":
                value = int(self.redis.data.get(key, 0)) + 1
                self.redis.data[key] = str(value)
                results.append(value)
            else:
                self.redis.expires_at[key] = self.redis.now + op[2]
                results.append(True)
        return results


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def fake_user():
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "ion"
    return user


@pytest.fixture(autouse=True)
def setup_app(fake_redis, mock_db):
    limiter.reset()

    async def _mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[get_login_lockout] = lambda: LoginLockout(fake_redis)
    yield
    app.dependency_overrides.clear()
    limiter.reset()


@pytest.fixture
def auth_backend(fake_user):
    """authenticate_user real cere DB; aici: parola corectă = PASSWORD."""
    async def _authenticate(username, password, db):
        return fake_user if username == fake_user.username and password == PASSWORD else None

    with patch("src.routers.auth.authenticate_user", side_effect=_authenticate) as mocked:
        yield mocked


def make_client(connection_ip: str) -> AsyncClient:
    """Client HTTP a cărui conexiune TCP vine de la connection_ip, ca în producție."""
    proxied_app = ProxyHeadersMiddleware(app, trusted_hosts=TRUSTED_PROXY_SUBNET)
    transport = ASGITransport(app=proxied_app, client=(connection_ip, 40000))
    return AsyncClient(transport=transport, base_url="http://test")


async def login(client: AsyncClient, username: str, password: str, forwarded_for: str = None):
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    return await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers=headers,
    )


def audit_events(mock_db) -> list[str]:
    return [
        c.args[0].details.get("event")
        for c in mock_db.add.call_args_list
        if isinstance(c.args[0], AuditLog) and c.args[0].action == "LOGIN"
    ]


# ============================================================
# 1–2. Limita per IP pe /auth/login
# ============================================================

class TestLoginRateLimitPerIp:

    @pytest.mark.asyncio
    async def test_two_client_ips_behind_nginx_have_separate_limits(self, auth_backend):
        async with make_client(NGINX_IP) as client:
            # Username-uri diferite: testăm doar limita per IP, nu blocarea per username
            for i in range(5):
                resp = await login(client, f"user{i}", "gresit", forwarded_for="10.0.0.1")
                assert resp.status_code == 401
            resp = await login(client, "user5", "gresit", forwarded_for="10.0.0.1")
            assert resp.status_code == 429

            # Alt client, prin același nginx → limită proprie, încă neatinsă
            resp = await login(client, "ion", PASSWORD, forwarded_for="10.0.0.2")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_forwarded_for_from_untrusted_ip_is_ignored(self, auth_backend):
        async with make_client(UNTRUSTED_IP) as client:
            # Fiecare request pretinde alt IP; toate se numără pe UNTRUSTED_IP
            for i in range(5):
                resp = await login(client, f"user{i}", "gresit", forwarded_for=f"10.0.1.{i}")
                assert resp.status_code == 401
            resp = await login(client, "ion", PASSWORD, forwarded_for="10.0.1.99")
            assert resp.status_code == 429

    @pytest.mark.asyncio
    async def test_untrusted_ip_cannot_use_quota_of_spoofed_ip(self, auth_backend):
        """Un client direct care pretinde IP-ul 10.0.0.1 nu consumă limita acelui IP."""
        async with make_client(UNTRUSTED_IP) as attacker:
            for i in range(6):
                await login(attacker, f"user{i}", "gresit", forwarded_for="10.0.0.1")

        async with make_client(NGINX_IP) as client:
            resp = await login(client, "ion", PASSWORD, forwarded_for="10.0.0.1")
            assert resp.status_code == 200


# ============================================================
# 3–4. Blocarea per username
# ============================================================

class TestUsernameLockout:

    @pytest.mark.asyncio
    async def test_sixth_attempt_is_blocked_even_with_correct_password(self, auth_backend, mock_db):
        async with make_client(NGINX_IP) as client:
            # IP-uri diferite → limita per IP nu intervine; blocarea e per username
            for i in range(5):
                resp = await login(client, "ion", "gresit", forwarded_for=f"10.0.2.{i}")
                assert resp.status_code == 401

            resp = await login(client, "ion", PASSWORD, forwarded_for="10.0.2.100")

        assert resp.status_code == 401
        # Același mesaj ca la parolă greșită: nu dezvăluie blocarea
        assert resp.json() == {"detail": "Nume de utilizator sau parolă incorectă."}
        # Al 6-lea request nu mai verifică parola
        assert auth_backend.call_count == 5
        assert audit_events(mock_db) == ["account_locked", "login_rejected_locked"]

    @pytest.mark.asyncio
    async def test_lock_event_is_audited_and_committed(self, auth_backend, mock_db):
        async with make_client(NGINX_IP) as client:
            for i in range(5):
                await login(client, "ion", "gresit", forwarded_for=f"10.0.3.{i}")

        entry = next(c.args[0] for c in mock_db.add.call_args_list if isinstance(c.args[0], AuditLog))
        assert entry.success is False
        assert entry.user_ip == "10.0.3.4"
        assert entry.details == {
            "event": "account_locked",
            "username": "ion",
            "max_failed_attempts": 5,
            "lockout_minutes": 15,
        }
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_same_response_for_unknown_and_locked_username(self, auth_backend):
        async with make_client(NGINX_IP) as client:
            unknown = await login(client, "nu_exista", "x", forwarded_for="10.0.4.1")
            for i in range(5):
                await login(client, "ion", "gresit", forwarded_for=f"10.0.4.{i + 10}")
            locked = await login(client, "ion", PASSWORD, forwarded_for="10.0.4.99")

        assert unknown.status_code == locked.status_code == 401
        assert unknown.json() == locked.json()
        assert unknown.headers.get("www-authenticate") == locked.headers.get("www-authenticate")

    @pytest.mark.asyncio
    async def test_successful_login_resets_counter(self, auth_backend, fake_redis):
        async with make_client(NGINX_IP) as client:
            for i in range(4):
                assert (await login(client, "ion", "gresit", forwarded_for=f"10.0.5.{i}")).status_code == 401
            assert (await login(client, "ion", PASSWORD, forwarded_for="10.0.5.50")).status_code == 200
            assert fake_redis.data == {}

            # Fără reset, al 5-lea eșec de aici ar bloca (4 + 1 = 5)
            for i in range(4):
                assert (await login(client, "ion", "gresit", forwarded_for=f"10.0.5.{i + 10}")).status_code == 401
            assert (await login(client, "ion", PASSWORD, forwarded_for="10.0.5.60")).status_code == 200

    @pytest.mark.asyncio
    async def test_lock_expires_after_15_minutes(self, auth_backend, fake_redis):
        async with make_client(NGINX_IP) as client:
            for i in range(5):
                await login(client, "ion", "gresit", forwarded_for=f"10.0.6.{i}")

            fake_redis.now += LOCKOUT_SECONDS - 1
            assert (await login(client, "ion", PASSWORD, forwarded_for="10.0.6.50")).status_code == 401

            fake_redis.now += 1
            assert (await login(client, "ion", PASSWORD, forwarded_for="10.0.6.51")).status_code == 200

    @pytest.mark.asyncio
    async def test_lockout_is_per_username(self, auth_backend, fake_user):
        async with make_client(NGINX_IP) as client:
            for i in range(5):
                await login(client, "altcineva", "gresit", forwarded_for=f"10.0.7.{i}")
            resp = await login(client, "ion", PASSWORD, forwarded_for="10.0.7.50")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_login_works_when_redis_is_unavailable(self, auth_backend):
        broken = MagicMock()
        broken.get = AsyncMock(side_effect=RedisConnectionError("down"))
        broken.delete = AsyncMock(side_effect=RedisConnectionError("down"))
        app.dependency_overrides[get_login_lockout] = lambda: LoginLockout(broken)

        async with make_client(NGINX_IP) as client:
            resp = await login(client, "ion", PASSWORD, forwarded_for="10.0.8.1")

        assert resp.status_code == 200


# ============================================================
# 5. Configurarea limiter-ului
# ============================================================

class TestLimiterConfiguration:

    def test_app_uses_shared_limiter(self):
        assert app.state.limiter is limiter

    def test_rate_limited_routes_are_registered_on_shared_limiter(self):
        limited = set(limiter._route_limits)
        assert "src.routers.auth.login" in limited
        assert "src.routers.search.search_transcripts" in limited
        assert "src.routers.search.semantic_search_transcripts" in limited
        assert "src.routers.export.export_transcript" in limited

    def test_inbox_routes_have_no_limits(self):
        assert not [name for name in limiter._route_limits if name.startswith("src.routers.inbox.")]
        assert not limiter._default_limits
