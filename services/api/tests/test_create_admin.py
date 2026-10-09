# services/api/tests/test_create_admin.py
# ============================================================
# Teste pentru src/cli/create_admin.py (folosit de installere)
# ============================================================
# Mockăm session_factory: verificăm ce se scrie în DB fără PostgreSQL.

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cli import create_admin
from src.middleware.auth import hash_password, verify_password
from src.models.audit_log import User


def make_args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        username="admin",
        email="admin@firma.ro",
        full_name=None,
        update_existing=False,
        must_change_password=False,
        disable_default_operator=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def make_db(*lookup_results) -> MagicMock:
    """Sesiune mock: fiecare db.execute() returnează următorul user din listă."""
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    results = []
    for user in lookup_results:
        r = MagicMock()
        r.scalar_one_or_none.return_value = user
        results.append(r)
    db.execute = AsyncMock(side_effect=results)

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=db)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return db, factory


def make_user(username: str, password: str, role: str = "admin", active: bool = True) -> User:
    return User(
        username=username,
        email=f"{username}@meetrec.local",
        password_hash=hash_password(password),
        role=role,
        is_active=active,
        must_change_password=True,
    )


@pytest.mark.asyncio
async def test_creeaza_admin_nou():
    db, factory = make_db(None)

    with patch.object(create_admin, "session_factory", factory):
        code = await create_admin._run(make_args(), "ParolaNoua123")

    assert code == 0
    created = db.add.call_args[0][0]
    assert created.username == "admin"
    assert created.role == "admin"
    assert created.is_active is True
    assert verify_password("ParolaNoua123", created.password_hash)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_existent_fara_update_existing_esueaza():
    db, factory = make_db(make_user("admin", "admin123"))

    with patch.object(create_admin, "session_factory", factory):
        code = await create_admin._run(make_args(), "ParolaNoua123")

    assert code == 1
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_existing_inlocuieste_parola_implicita():
    """Contul seed 'admin'/'admin123' din init.sql primește parola aleasă la instalare."""
    seed_admin = make_user("admin", "admin123")
    db, factory = make_db(seed_admin)

    with patch.object(create_admin, "session_factory", factory):
        code = await create_admin._run(make_args(update_existing=True), "ParolaNoua123")

    assert code == 0
    assert verify_password("ParolaNoua123", seed_admin.password_hash)
    assert not verify_password("admin123", seed_admin.password_hash)
    assert seed_admin.must_change_password is False
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_dezactiveaza_operator_cu_parola_implicita():
    operator = make_user("operator", "operator123", role="operator")
    db, factory = make_db(None, operator)

    with patch.object(create_admin, "session_factory", factory):
        await create_admin._run(make_args(disable_default_operator=True), "ParolaNoua123")

    assert operator.is_active is False


@pytest.mark.asyncio
async def test_nu_dezactiveaza_operator_cu_parola_schimbata():
    operator = make_user("operator", "AltaParola456", role="operator")
    db, factory = make_db(None, operator)

    with patch.object(create_admin, "session_factory", factory):
        await create_admin._run(make_args(disable_default_operator=True), "ParolaNoua123")

    assert operator.is_active is True
