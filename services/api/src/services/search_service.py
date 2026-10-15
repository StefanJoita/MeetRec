# services/api/src/services/search_service.py
# ============================================================
# Search Service — căutare în transcrieri
# ============================================================
# Două căutări, combinate în pagina de căutare:
#
#   Exactă (full-text):  PostgreSQL TSVECTOR + GIN pe fiecare segment, configurația
#                        romanian_unaccent (stemmer românesc, insensibil la diacritice).
#                        websearch_to_tsquery: "frază exactă", OR, -exclus.
#   După sens (semantic): vectorul întrebării (search-indexer /embed) comparat cu
#                        vectorii segmentelor (pgvector, distanță cosinus, index HNSW).
#
# Combinarea: Reciprocal Rank Fusion — se adună 1/(60 + poziția) din fiecare listă.
# Scorurile celor două căutări sunt pe scări diferite, pozițiile nu.
# Rezultatele se grupează pe ședință; separat, ședințele care se potrivesc
# după titlu, descriere, locație sau participanți.
# ============================================================

import asyncio
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.audit_log import User
from src.schemas.recording import (
    CombinedSearchResult, RecordingMatch, SearchGroup, SearchResult, SemanticSearchResult,
)

TS_CONFIG = "romanian_unaccent"
TS_QUERY = f"websearch_to_tsquery('{TS_CONFIG}', :query)"

RRF_K = 60              # constanta standard din Reciprocal Rank Fusion
CANDIDATES = 200        # câte rezultate se iau din fiecare căutare înainte de combinare
HITS_PER_GROUP = 3      # câte fragmente se afișează pentru o ședință
MIN_SIMILARITY = 0.3    # sub acest prag, căutarea după sens aduce mai mult zgomot decât rezultate


# Cuvinte de legătură ignorate când întrebarea e în limbaj natural (PostgreSQL nu are
# listă de stopwords pentru română): altfel „în” sau „de” s-ar potrivi aproape peste tot.
STOPWORDS = {
    "a", "ai", "al", "ale", "am", "ar", "are", "as", "au", "ca", "care", "ce", "cel", "cea", "cei",
    "cu", "da", "dar", "de", "deci", "din", "după", "dupa", "e", "ea", "el", "este", "eu", "fi",
    "fie", "fost", "i", "ii", "îi", "in", "în", "intr", "într", "la", "le", "li", "lui", "m", "ma",
    "mă", "mai", "mi", "ne", "nici", "nu", "o", "pe", "pentru", "prin", "s", "sa", "să", "se",
    "si", "și", "sunt", "te", "tot", "toate", "un", "una", "unei", "unui", "va", "vă", "cum",
    "cine", "când", "cand", "unde", "despre", "spre", "sau", "ori", "ce", "că",
}
_OPERATORS = re.compile(r'"|(^|\s)-\S|\sOR\s')


def any_terms_query(query: str) -> str:
    """
    Întrebare în limbaj natural („proteste violente în Franța”) → termenii legați cu OR,
    fără cuvintele de legătură; relevanța ordonează apoi fragmentele cu mai mulți termeni.
    Dacă utilizatorul a folosit sintaxa ("frază", OR, -exclus), interogarea rămâne neschimbată.
    """
    if _OPERATORS.search(query):
        return query
    words = [w for w in re.findall(r"[\w-]+", query) if w.lower() not in STOPWORDS]
    return " OR ".join(words) if len(words) > 1 else query


def _participant_filter_sql(user: Optional[User]) -> tuple[str, dict]:
    """
    Returnează un fragment SQL și parametrii corespunzători pentru filtrul participant.

    Echivalentul în SQL text al participant_access_clause() din src/models/recording.py,
    sursa unică a regulii: participantul vede doar înregistrările la care e linkat
    în recording_participants, fără nicio condiție de dată. Păstrați-le sincronizate.
    """
    if user is None or not user.is_participant:
        return "", {}

    return (
        """
        AND EXISTS (
            SELECT 1 FROM recording_participants rp
            WHERE rp.recording_id = r.id
              AND rp.user_id = :participant_user_id
        )
        """,
        {"participant_user_id": user.id},
    )


def _as_date(value) -> Optional[date]:
    """asyncpg cere obiecte date pentru coloanele DATE, nu text."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


@dataclass
class SearchFilters:
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    location: Optional[str] = None
    min_duration: Optional[int] = None
    speaker: Optional[uuid.UUID] = None       # utilizatorul asociat vorbitorului (speaker_mapping)
    language: Optional[str] = None

    def sql(self, user: Optional[User], segments: bool = True) -> Tuple[str, dict]:
        """Condițiile AND și parametrii lor. `segments=False`: fără filtrele pe segment."""
        parts, params = [], {}
        if self.date_from:
            parts.append("AND r.meeting_date >= :date_from")
            params["date_from"] = _as_date(self.date_from)
        if self.date_to:
            parts.append("AND r.meeting_date <= :date_to")
            params["date_to"] = _as_date(self.date_to)
        if self.location:
            parts.append("AND r.location ILIKE :location")
            params["location"] = f"%{self.location}%"
        if self.min_duration:
            parts.append("AND r.duration_seconds >= :min_duration")
            params["min_duration"] = self.min_duration
        if segments and self.speaker:
            parts.append("AND r.speaker_mapping ->> seg.speaker_id = :speaker")
            params["speaker"] = str(self.speaker)
        if segments and self.language:
            parts.append("AND t.language = :language")
            params["language"] = self.language
        participant_sql, participant_params = _participant_filter_sql(user)
        params.update(participant_params)
        return "\n".join(parts) + participant_sql, params


@dataclass
class _Fused:
    result: CombinedSearchResult
    score: float = 0.0


@dataclass
class CombinedOutcome:
    groups: List[SearchGroup]
    recordings: List[RecordingMatch]
    total_groups: int
    total_hits: int
    fts_count: int
    semantic_count: int
    both_count: int
    semantic_available: bool
    pages: int = 0
    extra: Dict = field(default_factory=dict)


class SearchService:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Căutarea exactă ──────────────────────────────────────

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        language: Optional[str] = None,
        current_user: Optional[User] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        location: Optional[str] = None,
        min_duration: Optional[int] = None,
        speaker: Optional[uuid.UUID] = None,
    ) -> Tuple[List[SearchResult], int]:
        """
        Returns (results, total_count).
        total_count = câte segmente corespund query-ului (înainte de LIMIT/OFFSET).

        websearch_to_tsquery acceptă text natural ca plainto_tsquery, plus:
        "frază exactă", termen1 OR termen2, -termen_exclus.
        """
        filters = SearchFilters(date_from, date_to, location, min_duration, speaker, language)
        filter_sql, filter_params = filters.sql(current_user)
        params: dict = {"query": query, "limit": limit, "offset": offset, **filter_params}

        where = f"""
            WHERE
                t.status = 'completed'
                AND seg.search_vector @@ {TS_QUERY}
                {filter_sql}
        """

        # ── Query 1: numărul total de rezultate (pentru paginare) ──────────
        count_sql = text(f"""
            SELECT COUNT(*)
            FROM transcript_segments seg
            JOIN transcripts t ON t.id = seg.transcript_id
            JOIN recordings  r ON r.id = t.recording_id
            {where}
        """)
        total_count: int = (await self.db.scalar(count_sql, params)) or 0

        # ── Query 2: rezultatele efective cu paginare ──────────────────────
        # Scorul e al segmentului (nu al transcrierii întregi): ts_rank_cd ține
        # cont și de cât de apropiați sunt termenii căutați.
        sql = text(f"""
            SELECT
                r.id            AS recording_id,
                r.title         AS recording_title,
                r.meeting_date  AS meeting_date,
                seg.id          AS segment_id,
                seg.start_time  AS start_time,
                seg.end_time    AS end_time,
                seg.text        AS text,
                seg.speaker_id  AS speaker_id,
                ts_headline(
                    '{TS_CONFIG}',
                    seg.text,
                    {TS_QUERY},
                    'StartSel=<b>, StopSel=</b>, MaxWords=25, MinWords=8'
                )               AS headline,
                ts_rank_cd(seg.search_vector, {TS_QUERY}) AS rank
            FROM transcript_segments seg
            JOIN transcripts t    ON t.id = seg.transcript_id
            JOIN recordings r     ON r.id = t.recording_id
            {where}
            ORDER BY rank DESC, r.meeting_date DESC, seg.start_time
            LIMIT :limit OFFSET :offset
        """)

        rows = (await self.db.execute(sql, params)).mappings().all()
        results = [
            SearchResult(
                recording_id=row["recording_id"],
                recording_title=row["recording_title"],
                meeting_date=row["meeting_date"],
                segment_id=row["segment_id"],
                start_time=float(row["start_time"]),
                end_time=float(row["end_time"]),
                text=row["text"],
                headline=row["headline"],
                rank=float(row["rank"]),
                speaker_id=row.get("speaker_id"),
            )
            for row in rows
        ]
        return results, total_count

    def pages(self, total: int, limit: int) -> int:
        """Calculează numărul total de pagini."""
        return math.ceil(total / limit) if total > 0 else 0

    # ── Căutarea după sens ───────────────────────────────────

    async def semantic_search(
        self,
        query: str,
        limit: int = 20,
        current_user: Optional[User] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        location: Optional[str] = None,
        min_duration: Optional[int] = None,
        speaker: Optional[uuid.UUID] = None,
        embedding: Optional[Tuple[List[float], str]] = None,
    ) -> Tuple[List[SemanticSearchResult], bool]:
        """
        Returns (results, available). available=False: search-indexer indisponibil
        — interfața spune asta, în loc să arate „niciun rezultat”.

        Se compară doar cu vectorii produși de același model (embedding_model):
        după o schimbare de model, segmentele încă necalculate nu apar.
        """
        if embedding is None:
            embedding = await self._get_query_embedding(query)
        if embedding is None:
            return [], False
        vector, model = embedding

        # Vectorul e embeddat direct în SQL (float-uri generate de noi — fără risc de injecție):
        # SQLAlchemy confundă :param cu ::cast
        vector_literal = "[" + ",".join(f"{float(x):.8f}" for x in vector) + "]"
        filters = SearchFilters(date_from, date_to, location, min_duration, speaker)
        filter_sql, filter_params = filters.sql(current_user)

        # Indexul HNSW întoarce implicit 40 de candidați înainte de filtre;
        # cu filtre (participant, dată, vorbitor) ar rămâne prea puțini.
        await self.db.execute(text(f"SET LOCAL hnsw.ef_search = {max(100, min(limit * 2, 1000))}"))

        sql = text(f"""
            SELECT
                r.id            AS recording_id,
                r.title         AS recording_title,
                r.meeting_date  AS meeting_date,
                seg.id          AS segment_id,
                seg.start_time  AS start_time,
                seg.end_time    AS end_time,
                seg.text        AS text,
                seg.speaker_id  AS speaker_id,
                1 - (seg.embedding <=> '{vector_literal}'::vector) AS similarity
            FROM transcript_segments seg
            JOIN transcripts t ON t.id = seg.transcript_id
            JOIN recordings r  ON r.id = t.recording_id
            WHERE
                t.status = 'completed'
                AND seg.embedding IS NOT NULL
                AND seg.embedding_model = :model
                AND 1 - (seg.embedding <=> '{vector_literal}'::vector) > {MIN_SIMILARITY}
                {filter_sql}
            ORDER BY seg.embedding <=> '{vector_literal}'::vector ASC
            LIMIT :limit
        """)

        rows = (await self.db.execute(sql, {"limit": limit, "model": model, **filter_params})).mappings().all()
        results = [
            SemanticSearchResult(
                recording_id=row["recording_id"],
                recording_title=row["recording_title"],
                meeting_date=row["meeting_date"],
                segment_id=row["segment_id"],
                start_time=float(row["start_time"]),
                end_time=float(row["end_time"]),
                text=row["text"],
                similarity=round(float(row["similarity"]), 4),
                speaker_id=row.get("speaker_id"),
            )
            for row in rows
        ]
        return results, True

    # ── Ședințe după titlu / detalii ─────────────────────────

    async def recording_matches(
        self, query: str, current_user: Optional[User], filters: SearchFilters, limit: int = 10,
    ) -> List[RecordingMatch]:
        """Ședințele al căror titlu, descriere, locație sau listă de participanți se potrivește."""
        filter_sql, filter_params = filters.sql(current_user, segments=False)
        doc = ("concat_ws(' ', r.title, r.description, r.location, "
               "array_to_string(r.participants, ', '))")
        sql = text(f"""
            SELECT
                r.id AS recording_id, r.title, r.meeting_date, r.location,
                ts_headline('{TS_CONFIG}', {doc}, {TS_QUERY},
                            'StartSel=<b>, StopSel=</b>, MaxWords=25, MinWords=8') AS headline,
                ts_rank_cd(to_tsvector('{TS_CONFIG}', {doc}), {TS_QUERY}) AS rank
            FROM recordings r
            JOIN transcripts t ON t.recording_id = r.id
            WHERE t.status = 'completed'
              AND to_tsvector('{TS_CONFIG}', {doc}) @@ {TS_QUERY}
              {filter_sql}
            ORDER BY rank DESC, r.meeting_date DESC
            LIMIT :limit
        """)
        rows = (await self.db.execute(sql, {"query": query, "limit": limit, **filter_params})).mappings().all()
        return [
            RecordingMatch(recording_id=row["recording_id"], title=row["title"],
                           meeting_date=row["meeting_date"], location=row["location"],
                           headline=row["headline"])
            for row in rows
        ]

    # ── Căutarea combinată ───────────────────────────────────

    async def combined_search(
        self,
        query: str,
        page: int = 1,
        page_size: int = 10,
        current_user: Optional[User] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        location: Optional[str] = None,
        min_duration: Optional[int] = None,
        speaker: Optional[uuid.UUID] = None,
    ) -> CombinedOutcome:
        """
        Căutare exactă + după sens, combinate prin Reciprocal Rank Fusion și grupate
        pe ședință (paginarea e pe ședințe, câte `page_size`).
        """
        filters = SearchFilters(date_from, date_to, location, min_duration, speaker)
        kwargs = dict(current_user=current_user, date_from=date_from, date_to=date_to,
                      location=location, min_duration=min_duration, speaker=speaker)

        # Vectorul întrebării se cere în paralel cu căutarea exactă. Interogările SQL
        # rulează pe rând: o sesiune SQLAlchemy nu acceptă operații simultane.
        embedding_task = asyncio.create_task(self._get_query_embedding(query))
        fts_results, _ = await self.search(query=any_terms_query(query), limit=CANDIDATES, **kwargs)
        sem_results, semantic_available = await self.semantic_search(
            query=query, limit=CANDIDATES, embedding=await embedding_task, **kwargs)
        recordings = await self.recording_matches(any_terms_query(query), current_user, filters)

        fused: Dict[str, _Fused] = {}
        for rank, r in enumerate(fts_results, 1):
            fused[str(r.segment_id)] = _Fused(CombinedSearchResult(
                recording_id=r.recording_id, recording_title=r.recording_title,
                meeting_date=r.meeting_date, segment_id=r.segment_id, start_time=r.start_time,
                end_time=r.end_time, text=r.text, headline=r.headline, rank=r.rank,
                similarity=None, source="fts", speaker_id=r.speaker_id,
            ), 1 / (RRF_K + rank))
        for rank, r in enumerate(sem_results, 1):
            item = fused.get(str(r.segment_id))
            if item:
                item.result.similarity = r.similarity
                item.result.source = "both"
                item.score += 1 / (RRF_K + rank)
            else:
                fused[str(r.segment_id)] = _Fused(CombinedSearchResult(
                    recording_id=r.recording_id, recording_title=r.recording_title,
                    meeting_date=r.meeting_date, segment_id=r.segment_id, start_time=r.start_time,
                    end_time=r.end_time, text=r.text, headline=None, rank=None,
                    similarity=r.similarity, source="semantic", speaker_id=r.speaker_id,
                ), 1 / (RRF_K + rank))
        for item in fused.values():
            item.result.score = round(item.score, 6)

        # ── Grupare pe ședință: ordinea după cel mai bun fragment ─────────
        by_recording: Dict[uuid.UUID, List[CombinedSearchResult]] = {}
        for item in sorted(fused.values(), key=lambda f: -f.score):
            by_recording.setdefault(item.result.recording_id, []).append(item.result)
        all_groups = [
            SearchGroup(
                recording_id=rid, recording_title=hits[0].recording_title,
                meeting_date=hits[0].meeting_date, score=hits[0].score,
                total_hits=len(hits), hits=hits[:HITS_PER_GROUP],
            )
            for rid, hits in by_recording.items()
        ]

        start = (page - 1) * page_size
        await self._resolve_speakers(all_groups[start:start + page_size])
        sources = [f.result.source for f in fused.values()]
        return CombinedOutcome(
            groups=all_groups[start:start + page_size],
            recordings=recordings,
            total_groups=len(all_groups),
            total_hits=len(fused),
            fts_count=sum(s in ("fts", "both") for s in sources),
            semantic_count=sum(s in ("semantic", "both") for s in sources),
            both_count=sources.count("both"),
            semantic_available=semantic_available,
            pages=self.pages(len(all_groups), page_size),
        )

    async def _resolve_speakers(self, groups: List[SearchGroup]) -> None:
        """Numele vorbitorului pe fiecare fragment: persoana asociată sau „Vorbitor N”."""
        hits = [h for g in groups for h in g.hits if h.speaker_id]
        if not hits:
            return
        rec_ids = list({h.recording_id for h in hits})
        rows = (await self.db.execute(text("""
            SELECT r.id AS recording_id, m.key AS speaker_id, COALESCE(u.full_name, u.username) AS name
            FROM recordings r
            CROSS JOIN LATERAL jsonb_each_text(r.speaker_mapping) m
            JOIN users u ON u.id::text = m.value
            WHERE r.id = ANY(:ids)
        """), {"ids": rec_ids})).mappings().all()
        names = {(row["recording_id"], row["speaker_id"]): row["name"] for row in rows}
        for h in hits:
            h.speaker_name = names.get((h.recording_id, h.speaker_id)) or _speaker_label(h.speaker_id)

    async def speakers(self, current_user: Optional[User]) -> List[dict]:
        """Persoanele asociate cu vorbitori în ședințele vizibile utilizatorului (filtrul „Vorbitor”)."""
        participant_sql, params = _participant_filter_sql(current_user)
        rows = (await self.db.execute(text(f"""
            SELECT DISTINCT u.id, COALESCE(u.full_name, u.username) AS name
            FROM recordings r
            CROSS JOIN LATERAL jsonb_each_text(r.speaker_mapping) m
            JOIN users u ON u.id::text = m.value
            WHERE TRUE {participant_sql}
            ORDER BY name
        """), params)).mappings().all()
        return [{"id": row["id"], "name": row["name"]} for row in rows]

    async def _get_query_embedding(self, query: str) -> Optional[Tuple[List[float], str]]:
        """
        (vector, model) pentru întrebare, de la search-indexer.
        None dacă serviciul nu e disponibil (graceful degradation).
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(f"{settings.search_indexer_url}/embed", json={"text": query})
                resp.raise_for_status()
                body = resp.json()
                return body["embedding"], body["model"]
        except Exception:
            return None


def _speaker_label(speaker_id: str) -> str:
    from src.services.audit_describe import speaker_label
    return speaker_label(speaker_id)
