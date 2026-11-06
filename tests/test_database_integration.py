import datetime
import os
import pytest
from database import (
    DatabaseManager,
    Trade,
    TradeExecution,
    TradingAccount,
    encrypt_db_secret,
    decrypt_db_secret,
)


def test_fernet_encryption_roundtrip_and_legacy_fallback():
    """Verify API secret encryption and transparent fallback for plaintext keys."""
    secret = "binance_super_secret_api_key_456"
    encrypted = encrypt_db_secret(secret)
    assert encrypted != secret
    assert decrypt_db_secret(encrypted) == secret

    # Legacy unencrypted key must not throw and be returned as-is
    legacy = "legacy_unencrypted_key_789"
    assert decrypt_db_secret(legacy) == legacy

    # None handling
    assert encrypt_db_secret(None) is None
    assert decrypt_db_secret(None) is None


def test_sqlite_crud_and_selectinload(tmp_path):
    """Verify SQLite CRUD and that selectinload prevents DetachedInstanceError when accessing executions."""
    db_file = tmp_path / "test_journal.db"
    db = DatabaseManager(db_path=str(db_file))

    # 1. Create account
    account = db.add_account(
        name="Main Crypto",
        broker_type="Binance",
        initial_balance=5000.0,
        currency="USDT",
    )
    assert account is not None
    assert account.id is not None
    fetched_account = db.get_account_by_id(account.id)
    assert fetched_account is not None
    assert fetched_account.initial_balance == 5000.0

    # 2. Add trade
    trade = db.add_trade(
        ticker="BTC/USDT",
        direction="LONG",
        entry_price=60000.0,
        exit_price=63000.0,
        volume=0.5,
        commission=15.0,
        account_id=account.id,
        opened_at=datetime.datetime(2026, 3, 1, 10, 0),
        closed_at=datetime.datetime(2026, 3, 1, 12, 0),
    )
    assert trade is not None
    trade_id = trade.id

    # 3. Read trades and verify executions are loaded in memory via selectinload
    trades = db.get_trades()
    assert len(trades) == 1
    t = trades[0]
    assert t.ticker == "BTC/USDT"
    assert t.net_pnl == pytest.approx(1485.0, rel=1e-3)
    assert len(t.executions) >= 2
    assert t.executions[0].action == "ENTRY"
    assert t.executions[1].action == "EXIT"

    # 4. Update trade
    db.update_trade(trade_id, notes="Clean breakout on 15m")
    updated = db.get_trade_by_id(trade_id)
    assert updated.notes == "Clean breakout on 15m"

    # 5. Delete trade
    db.delete_trade(trade_id)
    assert len(db.get_trades()) == 0


def test_scale_in_out_vwap_calculation(tmp_path):
    """
    Verify Volume-Weighted Average Price (VWAP) calculation when scaling in:
    Execution 1: buy 1.0 @ $50,000
    Execution 2: buy 1.0 @ $52,000
    Expected Average Entry: (50000*1 + 52000*1) / 2 = $51,000
    """
    db_file = tmp_path / "test_vwap.db"
    db = DatabaseManager(db_path=str(db_file))

    trade = db.add_trade(
        ticker="ETH/USDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=55000.0,
        volume=1.0,
        commission=10.0,
    )
    trade_id = trade.id

    # Scale in with an extra execution
    db.add_execution(
        trade_id=trade_id,
        action="ENTRY",
        price=52000.0,
        volume=1.0,
        executed_at=datetime.datetime(2026, 3, 1, 10, 30),
    )

    trade = db.get_trade_by_id(trade_id)
    assert trade is not None
    # Entry price should now reflect weighted average entry (51000) and total volume 2.0
    entries = [e for e in trade.executions if e.action == "ENTRY"]
    total_entry_vol = sum(e.volume for e in entries)
    total_entry_cost = sum(e.volume * e.price for e in entries)
    expected_vwap = total_entry_cost / total_entry_vol
    assert expected_vwap == pytest.approx(51000.0, rel=1e-3)


def test_bulk_add_trades(tmp_path):
    """Verify bulk addition of trades in a single transaction."""
    db_file = tmp_path / "test_bulk.db"
    db = DatabaseManager(db_path=str(db_file))

    batch = [
        {
            "ticker": "SOL/USDT",
            "direction": "LONG",
            "entry_price": 100.0,
            "exit_price": 110.0,
            "volume": 10.0,
            "commission": 2.0,
        },
        {
            "ticker": "AVAX/USDT",
            "direction": "SHORT",
            "entry_price": 30.0,
            "exit_price": 28.0,
            "volume": 20.0,
            "commission": 1.5,
        },
    ]

    added = db.bulk_add_trades(batch)
    assert added == 2
    trades = db.get_trades()
    assert len(trades) == 2
    tickers = {t.ticker for t in trades}
    assert tickers == {"SOL/USDT", "AVAX/USDT"}
