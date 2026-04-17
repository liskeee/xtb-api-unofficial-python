"""AuthManager.session_source exposes whether a run reused a cached TGT.

Motivation: XTB emails users on every fresh login. Consumers (including
validate_live.py and downstream automation) need a stable, typed signal to
confirm that session reuse is actually happening — otherwise "remember
device" regressions are invisible until the next inbox notification.
"""

from __future__ import annotations

import json
import os
import stat
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from xtb_api.auth.auth_manager import AuthManager, SessionSource
from xtb_api.types.websocket import CASLoginSuccess


def _write_session(path, tgt: str, expires_at: datetime) -> None:
    data = {
        "tgt": tgt,
        "extracted_at": datetime.now(UTC).isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    try:
        os.write(fd, json.dumps(data).encode())
    finally:
        os.close(fd)


def test_session_source_starts_uncached(tmp_path) -> None:
    auth = AuthManager(email="a@b.c", password="p", session_file=tmp_path / ".xtb")
    assert auth.session_source is SessionSource.UNCACHED
    assert auth.session_expires_at is None


@pytest.mark.asyncio
async def test_session_source_is_session_file_after_cache_hit(tmp_path) -> None:
    session_file = tmp_path / ".xtb"
    expires = datetime.now(UTC) + timedelta(hours=4)
    _write_session(session_file, "TGT-cached-abc", expires)

    auth = AuthManager(email="a@b.c", password="p", session_file=session_file)
    tgt = await auth.get_tgt()

    assert tgt == "TGT-cached-abc"
    assert auth.session_source is SessionSource.SESSION_FILE
    assert auth.session_expires_at is not None
    assert abs(auth.session_expires_at - expires.timestamp()) < 1.0


@pytest.mark.asyncio
async def test_session_source_is_cas_login_after_fresh_rest_login(tmp_path) -> None:
    auth = AuthManager(email="a@b.c", password="p", session_file=tmp_path / ".xtb")
    auth._cas.login = AsyncMock(  # type: ignore[method-assign]
        return_value=CASLoginSuccess(tgt="TGT-fresh", expires_at=time.time() + 8 * 3600)
    )

    tgt = await auth.get_tgt()

    assert tgt == "TGT-fresh"
    assert auth.session_source is SessionSource.CAS_LOGIN
    assert auth.session_expires_at is not None


@pytest.mark.asyncio
async def test_session_source_is_memory_on_second_call_within_same_process(tmp_path) -> None:
    auth = AuthManager(email="a@b.c", password="p", session_file=tmp_path / ".xtb")
    auth._cas.login = AsyncMock(  # type: ignore[method-assign]
        return_value=CASLoginSuccess(tgt="TGT-x", expires_at=time.time() + 8 * 3600)
    )

    await auth.get_tgt()
    await auth.get_tgt()

    assert auth.session_source is SessionSource.MEMORY
    auth._cas.login.assert_awaited_once()  # type: ignore[attr-defined]
