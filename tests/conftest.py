"""Shared test fixtures."""

import pytest


@pytest.fixture
def demo_ws_url():
    """Demo WebSocket URL."""
    return "wss://api5demoa.x-station.eu/v1/xstation"


@pytest.fixture
def real_ws_url():
    """Real WebSocket URL."""
    return "wss://api5reala.x-station.eu/v1/xstation"


@pytest.fixture
def sample_account_number():
    """Sample account number for tests."""
    return 12345678
