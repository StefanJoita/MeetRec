# services/api/src/services/search_service.py
# ============================================================
# Search Service — Full-text search în transcrieri
# ============================================================
# Folosim PostgreSQL TSVECTOR + GIN index pentru căutare rapidă.
#
# Flow:
#   1. Convertim query-ul utilizatorului în tsquery
#   2. Căutăm în search_vector din tabela transcripts (actualizat de trigger)
#   3. Returnăm segmentele relevante cu headline (fragment evidențiat)
# ============================================================

import asyncio
import math
from typing import List, Optional, Tuple

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.audit_log import User
from src.schemas.recording import SearchResult, SemanticSearchResult, CombinedSearchResult


def _participant_filter_sql(user: Optional[User]) -> tuple[str, dict]:
    """
    Returnează un fragment SQL și parametrii corespunzători pentru filtrul participant.
    Participantul vede doar înregistrările la care e linkat și create după contul lui.
    """
    if user is None or not user.is_participant:
        return "", {}

    return (
        """
        AND EXISTS (
            SELECT 1 FROM recording_participants rp
            WHERE rp.recording_id = r.id
              AND rp.user_id = :participant_user_id
              AND r.created_at > :participant_created_at
        )
        """,
        {
            "participant_user_id": user.id,
            "participant_created_at": user.created_at,
        },
    )


class SearchService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        language: Optional[str] = None,
        current_user: Optional[User] = None,
    ) -> Tuple[List[SearchResult], int]:
        """
        Returns (results, total_count).
        total_count = câte segmente corespund query-ului (înainte de LIMIT/OFFSET).
        """
        """
        Caută în toate transcripturile completate.

        Folosește plainto_tsquery care acceptă text natural:
        - "buget 2024" → caută ambele cuvinte
        - "hotărâre consiliu" → caută ambele cuvinte
        Nu folosim to_tsquery care necesită sintaxă specială (& | !).
        """
        lang_filter = "AND t.language = :language" if language else ""
        participant_sql, participant_params = _participant_filter_sql(current_user)

        params: dict = {"query": query, "limit": limit, "offset": offset}
        if language:
            params["language"] = language
        params.update(participant_params)

        # ── Query 1: numărul total de rezultate (pentru paginare) ──────────
        count_sql = text(f"""
            SELECT COUNT(*)
            FROM transcript_segments seg
            JOIN transcripts t ON t.id = seg.transcript_id
            JOIN recordings  r ON r.id = t.recording_id
            WHERE
                t.status = 'completed'
                AND seg.search_vector @@ plainto_tsquery('romanian', :query)
                {lang_filter}
                {participant_sql}
        """)
        total_count: int = (await self.db.scalar(count_sql, params)) or 0

        # ── Query 2: rezultatele efective cu paginare ──────────────────────
        sql = text(f"""
            SELECT
                r.id            AS recording_id,
                r.title         AS recording_title,
                r.meeting_date  AS meeting_date,
                seg.id          AS segment_id,
                seg.start_time  AS start_time,
                seg.end_time    AS end_time,
                seg.text        AS text,
                ts_headline(
                    'romanian',
                    seg.text,
                    plainto_tsquery('romanian', :query),
                    'StartSel=<b>, StopSel=</b>, MaxWords=15, MinWords=5'
                )               AS headline,
                ts_rank(t.search_vector, plainto_tsquery('romanian', :query)) AS rank
            FROM transcript_segments seg
            JOIN transcripts t    ON t.id = seg.transcript_id
            JOIN recordings r     ON r.id = t.recording_id
            WHERE
                t.status = 'completed'
                AND seg.search_vector @@ plainto_tsquery('romanian', :query)
                {lang_filter}
                {participant_sql}
            ORDER BY rank DESC, r.meeting_date DESC
            LIMIT :limit OFFSET :offset
        """)

        result = await self.db.execute(sql, params)
        rows = result.mappings().all()

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
            )
            for row in rows
        ]

        return results, total_count

    def pages(self, total: int, limit: int) -> int:
        """Calculează numărul total de pagini."""
        return math.ceil(total / limit) if total > 0 else 0

    async def semantic_search(
        self,
        query: str,
        limit: int = 20,
        current_user: Optional[User] = None,
    ) -> Tuple[List[SemanticSearchResult], int]:
        """
        Căutare semantică folosind embeddings vectoriale (pgvector).

        Flow:
          1. Trimite query-ul la search-indexer → primește embedding vector(384)
          2. Execută query pgvector cu distanță cosinus (<=>)
          3. Returnează segmentele cele mai similare semantic

        Avantaj față de FTS:
          - Găsește și sinonime/parafraze: "buget alocat" ≈ "fonduri disponibile"
          - Nu necesită cuvinte cheie exacte
          - Funcționează bine pentru întrebări naturale
        """
        # ── Pas 1: obținem embedding-ul pentru query ──────────────────
        embedding = await self._get_query_embedding(query)
        if embedding is None:
            # Search indexer indisponibil — returnăm lista goală
            return [], 0

        # Convertim vectorul în string pgvector
        # Embeddat direct în SQL (valori float generate de noi — fără risc SQL injection)
        # SQLAlchemy confundă :param cu ::cast, deci evităm parametrul pentru vector
        vector_literal = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
        participant_sql, participant_params = _participant_filter_sql(current_user)

        sql = text(f"""
            SELECT
                r.id            AS recording_id,
                r.title         AS recording_title,
                r.meeting_date  AS meeting_date,
                seg.id          AS segment_id,
                seg.start_time  AS start_time,
                seg.end_time    AS end_time,
                seg.text        AS text,
                1 - (seg.embedding <=> '{vector_literal}'::vector) AS similarity
            FROM transcript_segments seg
            JOIN transcripts t ON t.id = seg.transcript_id
            JOIN recordings r  ON r.id = t.recording_id
            WHERE
                t.status = 'completed'
                AND seg.embedding IS NOT NULL
                AND 1 - (seg.embedding <=> '{vector_literal}'::vector) > 0.3
                {participant_sql}
            ORDER BY seg.embedding <=> '{vector_literal}'::vector ASC
            LIMIT :limit
        """)

        sem_params = {"limit": limit}
        sem_params.update(participant_params)
        result = await self.db.execute(sql, sem_params)
        rows = result.mappings().all()

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
            )
            for row in rows
        ]

        return results, len(results)

    async def combined_search(
        self,
        query: str,
        limit: int = 20,
        current_user: Optional[User] = None,
    ) -> Tuple[List[CombinedSearchResult], dict]:
        """
        Rulează FTS și semantic în paralel și merge rezultatele.
        Returnează (results, stats) unde stats = {fts_count, semantic_count, both_count}.

        Deduplicare: dacă același segment_id apare în ambele surse,
        apare o singură dată cu source='both' și ambele scoruri.

        Sortare: 'both' primele (cele mai relevante), apoi rank/similarity descrescător.
        """
        fts_task = self.search(query=query, limit=limit, current_user=current_user)
        sem_task = self.semantic_search(query=query, limit=limit, current_user=current_user)

        (fts_results, _), (sem_results, _) = await asyncio.gather(fts_task, sem_task)

        # Indexăm după segment_id pentru merge rapid
        fts_by_segment: dict = {str(r.segment_id): r for r in fts_results}
        sem_by_segment: dict = {str(r.segment_id): r for r in sem_results}

        merged: dict[str, CombinedSearchResult] = {}

        for seg_id, r in fts_by_segment.items():
            merged[seg_id] = CombinedSearchResult(
                recording_id=r.recording_id,
                recording_title=r.recording_title,
                meeting_date=r.meeting_date,
                segment_id=r.segment_id,
                start_time=r.start_time,
                end_time=r.end_time,
                text=r.text,
                headline=r.headline,
                rank=r.rank,
                similarity=None,
                source="fts",
            )

        for seg_id, r in sem_by_segment.items():
            if seg_id in merged:
                # Apare în ambele — upgrade la 'both'
                merged[seg_id].similarity = r.similarity
                merged[seg_id].source = "both"
            else:
                merged[seg_id] = CombinedSearchResult(
                    recording_id=r.recording_id,
                    recording_title=r.recording_title,
                    meeting_date=r.meeting_date,
                    segment_id=r.segment_id,
                    start_time=r.start_time,
                    end_time=r.end_time,
                    text=r.text,
                    headline=None,
                    rank=None,
                    similarity=r.similarity,
                    source="semantic",
                )

        # Sortăm: 'both' primele, apoi semantic, apoi fts
        # În cadrul fiecărei surse sortăm descrescător după scor
        source_order = {"both": 0, "semantic": 1, "fts": 2}

        def sort_key(r: CombinedSearchResult):
            score = (r.similarity or 0) * 0.6 + (r.rank or 0) * 0.4
            return (source_order[r.source], -score)

        results = sorted(merged.values(), key=sort_key)[:limit]

        stats = {
            "fts_count": sum(1 for r in results if r.source in ("fts", "both")),
            "semantic_count": sum(1 for r in results if r.source in ("semantic", "both")),
            "both_count": sum(1 for r in results if r.source == "both"),
        }

        return results, stats

    async def _get_query_embedding(self, text: str) -> Optional[List[float]]:
        """
        Apelează search-indexer-ul pentru a genera embedding-ul query-ului.
        Returnează None dacă serviciul nu e disponibil (graceful degradation).
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{settings.search_indexer_url}/embed",
                    json={"text": text},
                )
                resp.raise_for_status()
                return resp.json()["embedding"]
        except Exception:
            return None
