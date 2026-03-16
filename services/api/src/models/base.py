#services/api/src/models/base.py
#================================================================
#Clasa de aza pentru modelele SQLAlchemy
#================================================================
#ORM (Object-Relational Mapping) 101:
#
#Fara ORM -scriem SQL manual:
#   cursor.execute("INSERT INTO recordings (id, title) VALUES (%s, %s)", (id, title))
#   row = cursor.fetchone()
#   recording = {"id": row[0], "title": row[1]}   ← fragil, erori ușoare
#
#Cu ORM -definim clase Python care reprezintă tabelele:
# Cu ORM — scriem Python:
#   recording = Recording(title="Ședința")
#   session.add(recording)
#   await session.commit()   ← SQLAlchemy generează SQL-ul
#
#Avantaje ORM:
#-Type safety: IDE stie ca recording.title e string
#-Refactoring : redenumesti campul -> compilatorul te avertizeaza
#-Portabilitate : acelasi cod permite schimbarea bazei de date (Postgres, MySQL, SQLite)
#-Relatii: poti defini usor relatii intre tabele (ForeignKey, OneToMany, etc)
#================================================================

import uuid
from datetime import datetime,timezone
from sqlalchemy import Column, String, DateTime, Integer, Enum,func
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped
from sqlalchemy.dialects.postgresql import UUID as PG_UUID  


def utcnow()->datetime:
    """Returnează ora curentă în UTC — întotdeauna folosim UTC în DB."""
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    """
    Clasa de baza pe care o mostenesc TOATE modelele.
    definim aici campurile comune tuturor tabelelor, cum ar fi id, created_at, updated_at.
    Mostenire in Python:
        class Recording(Base):<- Recording mosteneste tot din Base
            __tablename__="recordings"
            title: Mapped[str] <- camp specific Recordings
    """
    pass