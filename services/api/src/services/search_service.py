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

from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.schemas.recording import SearchResult


class SearchService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        language: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Caută în toate transcripturile completate.

        Folosește plainto_tsquery care acceptă text natural:
        - "buget 2024" → caută ambele cuvinte
        - "hotărâre consiliu" → caută ambele cuvinte
        Nu folosim to_tsquery care necesită sintaxă specială (& | !).
        """
        # Filtru opțional de limbă
        lang_filter = "AND ts.language = :language" if language else ""

        # Query principal cu full-text search
        # ts_rank = scorul de relevanță (mai mare = mai relevant)
        # ts_headline = extrage fragmentul cu cuvântul evidențiat în <b>...</b>
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
                AND t.search_vector @@ plainto_tsquery('romanian', :query)
                {lang_filter}
            ORDER BY rank DESC, r.meeting_date DESC
            LIMIT :limit OFFSET :offset
        """)

        params = {"query": query, "limit": limit, "offset": offset}
        if language:
            params["language"] = language

        result = await self.db.execute(sql, params)
        rows = result.mappings().all()

        return [
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
