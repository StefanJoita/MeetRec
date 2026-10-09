# services/api/tests/test_participant_access.py
# ============================================================
# Teste RBAC pentru rolul participant
# ============================================================
# Regula (sursă unică: participant_access_clause din src/models/recording.py):
#   participantul are acces la o înregistrare dacă și numai dacă există
#   un rând (recording_id, user_id) în recording_participants.
#   NU contează dacă înregistrarea a fost creată înainte de contul lui.
#
# Strategie:
#   FakeDB primește statement-urile reale (SQLAlchemy / SQL text) și le
#   evaluează pe date în memorie, aplicând filtrele pe care le găsește în SQL:
#     - id-ul înregistrării
#     - EXISTS pe recording_participants (linkul participant ↔ înregistrare)
#     - orice comparație "created_at >" (cum ar face PostgreSQL)
#   Astfel, o condiție de dată reintrodusă în oricare query face testele să pice.
#
# Scenarii:
#   1. Participant linkat la o înregistrare creată ÎNAINTE de contul lui → acces
#   2. Participant nelinkat → 404 / 403 / lipsă din căutare
#   3. Operator / admin → acces la tot, fără filtru participant
# ============================================================

import re
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.dialects import postgresql

from src.main import app
from src.database import get_db
from src.middleware.auth import get_current_user
from src.models.audit_log import User
from src.schemas.recording import RecordingResponse
from src.services.recording_service import RecordingService
from src.services.search_service import SearchService, _participant_filter_sql


# ── Date de test ──────────────────────────────────────────────

ACCOUNT_CREATED = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)

# Creată înainte de contul participantului, linkată la el
OLD_LINKED_ID = uuid.uuid4()
# Creată înainte de contul participantului, NElinkată
OLD_UNLINKED_ID = uuid.uuid4()
# Creată după contul participantului, NElinkată (data nu acordă acces)
NEW_UNLINKED_ID = uuid.uuid4()


def make_user(role: str) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = f"user_{role}"
    user.role = role
    user.is_active = True
    user.is_admin = role == "admin"
    user.is_participant = role == "participant"
    user.must_change_password = False
    user.created_at = ACCOUNT_CREATED
    return user


def make_recording(rec_id: uuid.UUID, title: str, created_at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=rec_id,
        title=title,
        meeting_date=date(2025, 12, 1),
        audio_format="mp3",
        duration_formatted="00:05:00",
        duration_seconds=300,
        file_size_mb=1.0,
        status="completed",
        created_at=created_at,
        speaker_mapping={},
        transcript=SimpleNamespace(status="completed"),
    )


def make_transcript(recording_id: uuid.UUID) -> SimpleNamespace:
    segment = SimpleNamespace(
        id=uuid.uuid4(),
        segment_index=0,
        start_time=0.0,
        end_time=4.5,
        text="Bună ziua, deschidem ședința.",
        confidence=0.9,
        speaker_id=None,
        language="ro",
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        recording_id=recording_id,
        status="completed",
        language="ro",
        model_used="large-v3",
        word_count=4,
        confidence_avg=0.9,
        processing_time_sec=10,
        created_at=ACCOUNT_CREATED,
        completed_at=ACCOUNT_CREATED,
        segments=[segment],
        full_text=segment.text,
    )


# ── FakeDB ────────────────────────────────────────────────────

class _Result:
    def __init__(self, items: list):
        self._items = items

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalar(self):
        return self.scalar_one_or_none()

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._items))

    def mappings(self):
        return SimpleNamespace(all=lambda: list(self._items))

    def all(self):
        return list(self._items)


class FakeDB:
    """Sesiune DB falsă care evaluează filtrele din SQL pe date în memorie."""

    def __init__(self, recordings: list, links: set):
        self.recordings = {r.id: r for r in recordings}
        self.transcripts = {r.id: make_transcript(r.id) for r in recordings}
        self.links = links                      # {(recording_id, user_id)}
        self.statements: list[tuple[str, dict]] = []
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.flush = AsyncMock()

    @staticmethod
    def _compile(stmt, params) -> tuple[str, dict]:
        if params is not None:                  # SQL text + parametri expliciți
            return str(stmt), dict(params)
        compiled = stmt.compile(dialect=postgresql.dialect())
        return str(compiled), dict(compiled.params)

    def _visible_recordings(self, sql: str, params: dict) -> list:
        values = list(params.values())
        recs = list(self.recordings.values())

        rec_ids = [v for v in values if v in self.recordings]
        if rec_ids:
            recs = [r for r in recs if r.id in rec_ids]

        if "recording_participants" in sql:
            user_ids = [v for v in values if isinstance(v, uuid.UUID) and v not in self.recordings]
            recs = [r for r in recs if any((r.id, u) in self.links for u in user_ids)]

        if re.search(r"created_at\s*>", sql):
            cutoffs = [v for v in values if isinstance(v, datetime)]
            recs = [r for r in recs if all(r.created_at > c for c in cutoffs)]

        return recs

    def _evaluate(self, stmt, params) -> list:
        sql, params = self._compile(stmt, params)
        self.statements.append((sql, params))

        if "transcript_segments seg" in sql:    # căutare FTS / semantică
            return [
                {
                    "recording_id": r.id,
                    "recording_title": r.title,
                    "meeting_date": r.meeting_date,
                    "segment_id": uuid.uuid4(),
                    "start_time": 0.0,
                    "end_time": 4.5,
                    "text": "buget local",
                    "headline": "<b>buget</b> local",
                    "rank": 0.5,
                    "similarity": 0.8,
                }
                for r in self._visible_recordings(sql, params)
            ]

        if re.search(r"FROM transcripts\b", sql):
            rec_ids = [v for v in params.values() if v in self.transcripts]
            return [self.transcripts[i] for i in rec_ids]

        recs = self._visible_recordings(sql, params)

        if "GROUP BY recordings.status" in sql:  # /recordings/stats — count per status
            statuses = sorted({r.status for r in recs})
            return [SimpleNamespace(status=st, cnt=sum(r.status == st for r in recs)) for st in statuses]
        if "sum(recordings.duration_seconds)" in sql:  # /recordings/stats — durată totală
            return [sum(r.duration_seconds for r in recs if r.status == "completed")]

        return recs

    async def execute(self, stmt, params=None):
        return _Result(self._evaluate(stmt, params))

    async def scalar(self, stmt, params=None):
        sql = str(stmt)
        items = self._evaluate(stmt, params)
        return len(items) if "count(" in sql.lower() else (items[0] if items else None)


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def participant():
    return make_user("participant")


@pytest.fixture
def fake_db(participant):
    return FakeDB(
        recordings=[
            make_recording(OLD_LINKED_ID, "Ședință veche linkată", datetime(2025, 12, 1, tzinfo=timezone.utc)),
            make_recording(OLD_UNLINKED_ID, "Ședință veche nelinkată", datetime(2025, 11, 1, tzinfo=timezone.utc)),
            make_recording(NEW_UNLINKED_ID, "Ședință nouă nelinkată", datetime(2026, 2, 1, tzinfo=timezone.utc)),
        ],
        links={(OLD_LINKED_ID, participant.id)},
    )


def make_client(db: FakeDB, user) -> AsyncClient:
    async def _mock_get_db():
        yield db

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def patch_recording_response():
    """to_recording_response citește participanții prin JOIN pe users — nu face parte din test."""
    async def _to_response(self, rec):
        return RecordingResponse(
            id=rec.id, title=rec.title, description=None, meeting_date=rec.meeting_date,
            location=None, participants=[], original_filename="x.mp3",
            file_size_bytes=1024, audio_format="mp3", duration_seconds=300,
            duration_formatted="00:05:00", file_size_mb=1.0, status="completed",
            error_message=None, created_at=rec.created_at, updated_at=rec.created_at,
            retain_until=None, transcript=None,
        )

    with patch.object(RecordingService, "to_recording_response", _to_response):
        yield


def assert_no_date_condition(db: FakeDB):
    for sql, params in db.statements:
        assert not re.search(r"created_at\s*>", sql), sql
        assert "participant_created_at" not in params


# ============================================================
# 1. Participant linkat la o înregistrare creată ÎNAINTE de cont
# ============================================================

class TestLinkedParticipantOlderRecording:

    @pytest.mark.asyncio
    async def test_list_returns_200_and_contains_recording(self, fake_db, participant):
        async with make_client(fake_db, participant) as client:
            resp = await client.get("/api/v1/recordings/")

        assert resp.status_code == 200
        body = resp.json()
        assert [item["id"] for item in body["items"]] == [str(OLD_LINKED_ID)]
        assert body["total"] == 1
        assert_no_date_condition(fake_db)

    @pytest.mark.asyncio
    async def test_get_recording_returns_200(self, fake_db, participant, patch_recording_response):
        async with make_client(fake_db, participant) as client:
            resp = await client.get(f"/api/v1/recordings/{OLD_LINKED_ID}")

        assert resp.status_code == 200
        assert resp.json()["id"] == str(OLD_LINKED_ID)
        assert_no_date_condition(fake_db)

    @pytest.mark.asyncio
    async def test_get_transcript_returns_200(self, fake_db, participant):
        async with make_client(fake_db, participant) as client:
            resp = await client.get(f"/api/v1/transcripts/recording/{OLD_LINKED_ID}")

        assert resp.status_code == 200
        assert resp.json()["recording_id"] == str(OLD_LINKED_ID)
        assert_no_date_condition(fake_db)

    @pytest.mark.asyncio
    async def test_export_returns_200(self, fake_db, participant):
        async with make_client(fake_db, participant) as client:
            resp = await client.get(f"/api/v1/export/recording/{OLD_LINKED_ID}?format=txt")

        assert resp.status_code == 200
        assert "Ședință veche linkată" in resp.content.decode("utf-8")
        assert_no_date_condition(fake_db)

    @pytest.mark.asyncio
    async def test_stats_counts_recording(self, fake_db, participant):
        async with make_client(fake_db, participant) as client:
            resp = await client.get("/api/v1/recordings/stats")

        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["completed"] == 1
        assert_no_date_condition(fake_db)
        assert all("recording_participants" in sql for sql, _ in fake_db.statements)

    @pytest.mark.asyncio
    async def test_fts_search_uses_link_filter_only(self, fake_db, participant):
        async with make_client(fake_db, participant) as client:
            resp = await client.get("/api/v1/search/?q=buget")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_results"] == 1
        assert {r["recording_id"] for r in body["results"]} == {str(OLD_LINKED_ID)}

        search_statements = [(s, p) for s, p in fake_db.statements if "transcript_segments seg" in s]
        assert len(search_statements) == 2     # COUNT + rezultate
        for sql, params in search_statements:
            assert "EXISTS" in sql
            assert "rp.user_id = :participant_user_id" in sql
            assert params["participant_user_id"] == participant.id
        assert_no_date_condition(fake_db)

    @pytest.mark.asyncio
    async def test_semantic_search_finds_recording(self, fake_db, participant):
        with patch.object(SearchService, "_get_query_embedding", AsyncMock(return_value=[0.0] * 384)):
            async with make_client(fake_db, participant) as client:
                resp = await client.get("/api/v1/search/semantic?q=buget")

        assert resp.status_code == 200
        assert {r["recording_id"] for r in resp.json()["results"]} == {str(OLD_LINKED_ID)}
        assert_no_date_condition(fake_db)


class TestParticipantFilterSql:

    def test_fragment_has_link_condition_and_no_date(self, participant):
        sql, params = _participant_filter_sql(participant)

        assert "EXISTS" in sql
        assert "recording_participants rp" in sql
        assert "rp.recording_id = r.id" in sql
        assert "rp.user_id = :participant_user_id" in sql
        assert "created_at" not in sql
        assert params == {"participant_user_id": participant.id}

    @pytest.mark.parametrize("role", ["operator", "admin"])
    def test_no_filter_for_operator_and_admin(self, role):
        assert _participant_filter_sql(make_user(role)) == ("", {})

    def test_no_filter_without_user(self):
        assert _participant_filter_sql(None) == ("", {})


# ============================================================
# 2. Participant nelinkat
# ============================================================

class TestUnlinkedParticipant:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("rec_id", [OLD_UNLINKED_ID, NEW_UNLINKED_ID])
    async def test_get_recording_returns_404(self, fake_db, participant, patch_recording_response, rec_id):
        async with make_client(fake_db, participant) as client:
            resp = await client.get(f"/api/v1/recordings/{rec_id}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.parametrize("rec_id", [OLD_UNLINKED_ID, NEW_UNLINKED_ID])
    async def test_get_transcript_returns_403(self, fake_db, participant, rec_id):
        async with make_client(fake_db, participant) as client:
            resp = await client.get(f"/api/v1/transcripts/recording/{rec_id}")

        assert resp.status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.parametrize("rec_id", [OLD_UNLINKED_ID, NEW_UNLINKED_ID])
    async def test_export_returns_403(self, fake_db, participant, rec_id):
        async with make_client(fake_db, participant) as client:
            resp = await client.get(f"/api/v1/export/recording/{rec_id}?format=txt")

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_list_excludes_unlinked(self, fake_db, participant):
        async with make_client(fake_db, participant) as client:
            resp = await client.get("/api/v1/recordings/")

        ids = {item["id"] for item in resp.json()["items"]}
        assert str(OLD_UNLINKED_ID) not in ids
        assert str(NEW_UNLINKED_ID) not in ids

    @pytest.mark.asyncio
    async def test_search_does_not_return_unlinked(self, fake_db, participant):
        async with make_client(fake_db, participant) as client:
            resp = await client.get("/api/v1/search/?q=buget")

        ids = {r["recording_id"] for r in resp.json()["results"]}
        assert str(OLD_UNLINKED_ID) not in ids
        assert str(NEW_UNLINKED_ID) not in ids

    @pytest.mark.asyncio
    async def test_participant_without_links_sees_nothing(self, fake_db):
        other = make_user("participant")

        async with make_client(fake_db, other) as client:
            list_resp = await client.get("/api/v1/recordings/")
            get_resp = await client.get(f"/api/v1/recordings/{OLD_LINKED_ID}")
            search_resp = await client.get("/api/v1/search/?q=buget")

        assert list_resp.json()["total"] == 0
        assert get_resp.status_code == 404
        assert search_resp.json()["total_results"] == 0


# ============================================================
# 3. Operator / admin — neafectați
# ============================================================

class TestOperatorAndAdminUnaffected:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["operator", "admin"])
    async def test_list_contains_all_without_participant_filter(self, fake_db, role):
        async with make_client(fake_db, make_user(role)) as client:
            resp = await client.get("/api/v1/recordings/")

        assert resp.status_code == 200
        assert resp.json()["total"] == 3
        assert not any("recording_participants" in sql for sql, _ in fake_db.statements)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["operator", "admin"])
    async def test_get_transcript_and_export_any_recording(self, fake_db, patch_recording_response, role):
        async with make_client(fake_db, make_user(role)) as client:
            get_resp = await client.get(f"/api/v1/recordings/{OLD_UNLINKED_ID}")
            tr_resp = await client.get(f"/api/v1/transcripts/recording/{OLD_UNLINKED_ID}")
            exp_resp = await client.get(f"/api/v1/export/recording/{OLD_UNLINKED_ID}?format=txt")

        assert get_resp.status_code == 200
        assert tr_resp.status_code == 200
        assert exp_resp.status_code == 200
        assert not any("recording_participants" in sql for sql, _ in fake_db.statements)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["operator", "admin"])
    async def test_search_returns_all(self, fake_db, role):
        async with make_client(fake_db, make_user(role)) as client:
            resp = await client.get("/api/v1/search/?q=buget")

        assert resp.json()["total_results"] == 3
        assert not any("recording_participants" in sql for sql, _ in fake_db.statements)
