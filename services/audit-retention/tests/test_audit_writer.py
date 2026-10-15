# services/audit-retention/tests/test_audit_writer.py
# Detaliile din audit_logs sunt JSON valid indiferent de titlu (ghilimele, diacritice).

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.audit_writer import log_audit_purge, log_retention_delete


def make_pool():
    conn = AsyncMock()
    acq = AsyncMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acq)
    return pool, conn


@pytest.mark.asyncio
async def test_retention_delete_title_with_quotes():
    pool, conn = make_pool()

    await log_retention_delete(pool, "rec-1", 'Ședința "CA" \ martie')

    details = json.loads(conn.execute.call_args.args[3])
    assert details == {"resource_name": 'Ședința "CA" \ martie', "title": 'Ședința "CA" \ martie',
                       "reason": "retention_policy"}


@pytest.mark.asyncio
async def test_audit_purge_details():
    pool, conn = make_pool()

    await log_audit_purge(pool, 42)

    assert json.loads(conn.execute.call_args.args[2]) == {
        "deleted_count": 42, "reason": "audit_log_retention_policy"}
