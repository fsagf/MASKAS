import datetime
from unittest.mock import patch
import httpx
import pytest

from database import DatabaseManager, Trade
from services.chart_service import (
    fetch_binance_candles,
    generate_synthetic_candles,
    generate_trade_chart,
)
from services.sync_service import SyncService


def test_synthetic_candles_fallback_generation():
    """Verify synthetic candle generator produces valid, non-empty OHLCV series."""
    trade = Trade(
        ticker="BTC/USDT",
        direction="LONG",
        entry_price=65000.0,
        exit_price=67500.0,
        volume=1.0,
        opened_at=datetime.datetime(2026, 3, 1, 10, 0),
        closed_at=datetime.datetime(2026, 3, 1, 14, 0),
        mae_price=64200.0,
        mfe_price=68000.0,
    )

    candles = generate_synthetic_candles(
        trade=trade,
        start_time=trade.opened_at - datetime.timedelta(hours=2),
        end_time=trade.closed_at + datetime.timedelta(hours=2),
        interval_minutes=15,
    )

    assert len(candles) >= 10
    required_keys = {"time", "open", "high", "low", "close", "volume"}
    for c in candles:
        assert required_keys.issubset(c.keys())
        assert c["high"] >= c["low"]
        assert c["high"] >= c["open"]
        assert c["high"] >= c["close"]
        assert c["low"] <= c["open"]
        assert c["low"] <= c["close"]

    # Verify timestamps are monotonically increasing
    timestamps = [c["time"] for c in candles]
    assert timestamps == sorted(timestamps)


def test_binance_candles_timeout_resilience():
    """Verify fetch_binance_candles returns None on network timeout without unhandled crash."""
    with patch("httpx.Client.get", side_effect=httpx.TimeoutException("Connection timed out")):
        candles = fetch_binance_candles(
            symbol="BTCUSDT",
            start_time=datetime.datetime(2026, 3, 1, 10, 0),
            end_time=datetime.datetime(2026, 3, 1, 12, 0),
        )
        assert candles is None


def test_generate_trade_chart_with_fallback(tmp_path):
    """Verify HTML chart generation succeeds seamlessly via fallback when offline."""
    trade = Trade(
        ticker="ETH/USDT",
        direction="SHORT",
        entry_price=3500.0,
        exit_price=3300.0,
        volume=2.0,
        stop_loss=3600.0,
        take_profit=3200.0,
        opened_at=datetime.datetime(2026, 3, 1, 10, 0),
        closed_at=datetime.datetime(2026, 3, 1, 13, 0),
    )

    out_file = str(tmp_path / "chart.html")
    # Mock network call to force synthetic fallback
    with patch("services.chart_service.fetch_binance_candles", return_value=None):
        html_path = generate_trade_chart(trade, output_html_path=out_file)
        assert html_path == out_file
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "TradingView Lightweight Charts" in content
            assert "ETH/USDT" in content


def test_sync_service_invalid_account(tmp_path):
    """Verify SyncService returns safe error dictionary when account doesn't exist."""
    db_file = tmp_path / "resilience.db"
    db = DatabaseManager(db_path=str(db_file))

    res = SyncService.sync_account(account_id=999999, db=db)
    assert res["success"] is False
    assert "не найден" in res["message"]

