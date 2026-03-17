#services/api/src/models/database.py
#===================================================================
#Conxiunea la baza de date PostgreSQL folosind SQLAlchemy Async
#====================================================================
#SQLAlchemy 2.0 cu async suporta doua stiluri:
#1. Core: query-urile se scriu manual, e mai flexibil, dar mai verbos
#2. ORM: query-urile se scriu folosind obiecte Python, e mai concis, dar mai putin flexibil
#Noi folosim stilul ORM, care e mai potrivit pentru majoritatea cazurilor si se integreaza bine cu FastAPI
#====================================================================   

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.pool import NullPool
 
from src.config import settings
from src.models.base import Base

#---Engine-----------------   
#Engine= conexiunea de baza la PostgreSQL
#pool_size=10: maxim 10 conexiuni simultane
#echo=True in dev: afiseaza sql-urile generate in consola pentru debugging
engine: AsyncEngine=create_async_engine(
    settings.database_url,
    echo=(settings.app_env == "development"),
    pool_size=10,
    max_overflow=20, #permite pana la 20 conexiuni suplimentare temporare daca pool-ul e plin
    pool_pre_ping=True, #verifica conexiunea inainte de a o folosi, evita erori "connection closed"
)

#---Session Factory----------------
# async_sessionmaker = fabrică de sesiuni (o sesiune = o "conversație" cu DB)
# expire_on_commit=False: obiectele rămân accesibile după commit
#   (altfel, accesarea unui atribut după commit ar face un query nou)
session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Dependency pentru FastAPI ──────────────────────────────
# Dependency Injection în FastAPI:
# Funcțiile marcate cu Depends() sunt apelate automat de FastAPI
# și rezultatul e injectat în router.
#
# Exemplu de folosire în router:
#   @router.get("/recordings")
#   async def list_recordings(db: AsyncSession = Depends(get_db)):
#       recordings = await db.execute(select(Recording))
#
# "async generator" cu yield:
#   - tot ce e înainte de yield = setup (obținem sesiunea)
#   - yield = dăm sesiunea router-ului
#   - tot ce e după yield = teardown (închidem sesiunea)
#   Garantat să ruleze chiar dacă apare o excepție!
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency care furnizează o sesiune DB per request.
    Sesiunea se închide automat după ce request-ul e gata.
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()   # commit automat dacă nu a fost excepție
        except Exception:
            await session.rollback() # rollback automat la excepție
            raise
 
 
async def create_tables() -> None:
    """
    Creează toate tabelele definite în modele.
    Folosit în development — în producție folosim Alembic migrations!
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
 
 
async def drop_tables() -> None:
    """Șterge toate tabelele — DOAR pentru teste!"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)