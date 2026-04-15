"""InstrumentRegistry — persistent JSON cache of symbol → instrument-ID."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.instruments import InstrumentRegistry
from xtb_api.types.instrument import InstrumentSearchResult


def _isr(symbol: str, instrument_id: int) -> InstrumentSearchResult:
    return InstrumentSearchResult(
        symbol=symbol,
        symbol_key=f"{symbol}_9",
        instrument_id=instrument_id,
        name=symbol,
        description=symbol,
        asset_class="STK",
    )


def test_registry_is_empty_when_file_missing(tmp_path: Path) -> None:
    reg = InstrumentRegistry(tmp_path / "ids.json")
    assert reg.get("CIG.PL") is None


def test_registry_persists_on_set(tmp_path: Path) -> None:
    path = tmp_path / "ids.json"
    reg = InstrumentRegistry(path)
    reg.set("CIG.PL", 42)
    assert path.exists()
    assert json.loads(path.read_text()) == {"CIG.PL": 42}


def test_registry_loads_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "ids.json"
    path.write_text(json.dumps({"AAPL.US": 123}))
    reg = InstrumentRegistry(path)
    assert reg.get("AAPL.US") == 123


def test_registry_get_is_case_sensitive(tmp_path: Path) -> None:
    reg = InstrumentRegistry(tmp_path / "ids.json")
    reg.set("CIG.PL", 42)
    assert reg.get("CIG.PL") == 42
    assert reg.get("cig.pl") is None  # Callers must normalize.


def test_registry_accepts_str_path(tmp_path: Path) -> None:
    reg = InstrumentRegistry(str(tmp_path / "ids.json"))
    reg.set("X", 1)
    assert reg.get("X") == 1


@pytest.mark.asyncio
async def test_populate_matches_symbols(tmp_path: Path) -> None:
    reg = InstrumentRegistry(tmp_path / "ids.json")
    client = MagicMock()
    client.search_instrument = AsyncMock(return_value=[
        _isr("CIG.PL", 100),
        _isr("AAPL.US", 200),
        _isr("EURUSD", 300),
    ])

    matched = await reg.populate(client, ["CIG.PL", "AAPL.US"])

    assert matched == {"CIG.PL": 100, "AAPL.US": 200}
    assert reg.get("CIG.PL") == 100
    assert reg.get("AAPL.US") == 200
    assert reg.get("EURUSD") is None  # not in the requested universe


@pytest.mark.asyncio
async def test_populate_dotless_fallback(tmp_path: Path) -> None:
    """`BRK.B.US` isn't in the cache, but `BRKB.US` is — match it."""
    reg = InstrumentRegistry(tmp_path / "ids.json")
    client = MagicMock()
    client.search_instrument = AsyncMock(return_value=[_isr("BRKB.US", 777)])

    matched = await reg.populate(client, ["BRK.B.US"])

    assert matched == {"BRK.B.US": 777}
    assert reg.get("BRK.B.US") == 777


@pytest.mark.asyncio
async def test_populate_persists_results(tmp_path: Path) -> None:
    path = tmp_path / "ids.json"
    reg = InstrumentRegistry(path)
    client = MagicMock()
    client.search_instrument = AsyncMock(return_value=[_isr("X.PL", 1)])

    await reg.populate(client, ["X.PL"])

    assert json.loads(path.read_text()) == {"X.PL": 1}


@pytest.mark.asyncio
async def test_populate_merges_with_existing(tmp_path: Path) -> None:
    """Populate should not wipe previously-cached entries."""
    path = tmp_path / "ids.json"
    path.write_text(json.dumps({"OLD.PL": 99}))
    reg = InstrumentRegistry(path)
    client = MagicMock()
    client.search_instrument = AsyncMock(return_value=[_isr("NEW.PL", 2)])

    result = await reg.populate(client, ["NEW.PL"])

    # Return value covers only matches from THIS call, not pre-existing entries.
    assert result == {"NEW.PL": 2}
    # But the persisted file preserves the prior entries.
    saved = json.loads(path.read_text())
    assert saved == {"OLD.PL": 99, "NEW.PL": 2}
