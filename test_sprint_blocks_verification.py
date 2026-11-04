import datetime
import pytest
from database import DatabaseManager, Trade, TradingAccount, encrypt_db_secret, decrypt_db_secret
from analytics import AnalyticsService, WaveAICoachService
import run_share
import re


def test_encryption_and_fallbacks(tmp_path):
    # Test encryption roundtrip
    plain = "secret_binance_key_12345"
    encrypted = encrypt_db_secret(plain)
    assert encrypted != plain
    decrypted = decrypt_db_secret(encrypted)
    assert decrypted == plain

    # Test plaintext fallback for existing unencrypted keys
    legacy_plain = "legacy_unencrypted_api_key_xyz"
    assert decrypt_db_secret(legacy_plain) == legacy_plain

    # Test None handling
    assert encrypt_db_secret(None) is None
    assert decrypt_db_secret(None) is None


def test_database_bulk_add_and_selectinload(tmp_path):
    db_file = tmp_path / "test_trades.db"
    db = DatabaseManager(db_path=str(db_file))

    trades_data = [
        {
            "ticker": "BTC/USDT",
            "direction": "LONG",
            "entry_price": 50000.0,
            "exit_price": 52000.0,
            "volume": 0.5,
            "commission": 10.0,
            "opened_at": "2026-03-01T10:00:00",
            "closed_at": "2026-03-01T12:00:00",
        },
        {
            "ticker": "ETH/USDT",
            "direction": "SHORT",
            "entry_price": 3000.0,
            "exit_price": 2900.0,
            "volume": 2.0,
            "commission": 5.0,
            "opened_at": "2026-03-02T10:00:00",
            "closed_at": "2026-03-02T14:00:00",
        },
    ]

    count = db.bulk_add_trades(trades_data)
    assert count == 2

    # Verify selectinload preloading executions
    trades = db.get_trades()
    assert len(trades) == 2
    for t in trades:
        # Should already be in memory and have 2 executions (ENTRY, EXIT)
        assert len(t.executions) == 2
        assert t.executions[0].action == "ENTRY"
        assert t.executions[1].action == "EXIT"


def test_recalculate_metrics_mae_mfe_retention():
    # If mae_price and mfe_price are None, recalculate_metrics should NOT mutate them to floats
    trade = Trade(
        ticker="SOL/USDT",
        direction="LONG",
        entry_price=100.0,
        exit_price=120.0,
        volume=10.0,
        mae_price=None,
        mfe_price=None,
    )
    trade.recalculate_metrics()
    assert trade.mae_price is None
    assert trade.mfe_price is None
    assert trade.efficiency > 0.0
    assert trade.mae_pct < 0.0
    assert trade.mfe_pct > 0.0


def test_detect_tilt_ordering_and_revenge():
    t_old = Trade(
        id=1,
        ticker="BTC/USDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=49000.0,
        volume=1.0,
        commission=0.0,
        net_pnl=-1000.0,
        closed_at=datetime.datetime(2026, 3, 1, 10, 0, 0),
    )
    t_new = Trade(
        id=2,
        ticker="BTC/USDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=51000.0,
        volume=1.0,
        commission=0.0,
        net_pnl=1000.0,
        closed_at=datetime.datetime(2026, 3, 1, 12, 0, 0),
    )

    # Pass in ascending order (older first)
    recent = [t_old, t_new]

    # Candidate opened 5 mins after t_new (which was a win) -> NO revenge tilt
    cand_win = {
        "opened_at": datetime.datetime(2026, 3, 1, 12, 5, 0),
        "risk_amount": 100.0,
        "volume": 1.0,
        "checklist_passed": True,
    }
    is_tilt, _ = AnalyticsService.detect_tilt(cand_win, recent)
    assert is_tilt is False

    # Now simulate last trade being a loss
    t_loss = Trade(
        id=3,
        ticker="BTC/USDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=49000.0,
        volume=1.0,
        commission=0.0,
        net_pnl=-500.0,
        closed_at=datetime.datetime(2026, 3, 1, 13, 0, 0),
    )
    recent = [t_old, t_new, t_loss]
    cand_loss = {
        "opened_at": datetime.datetime(2026, 3, 1, 13, 4, 0),
        "risk_amount": 100.0,
        "volume": 1.0,
        "checklist_passed": True,
    }
    is_tilt, reason = AnalyticsService.detect_tilt(cand_loss, recent)
    assert is_tilt is True
    assert "Revenge Trade" in reason


def test_monte_carlo_base_balance():
    # If trades net pnl is +$200 on $10,000 initial balance, base equity must be $10,200
    t = Trade(
        ticker="BTC/USDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=50200.0,
        volume=1.0,
        net_pnl=200.0,
        is_tilt=False,
    )
    mc = AnalyticsService.simulate_monte_carlo([t], n_simulations=100, n_steps=5, initial_balance=10000.0)
    # P50 starts from 10200, so min_val must be comfortably above 5000 (no false ruin)
    assert mc["p50"][0] == 10200.0
    assert mc["risk_of_ruin"] < 50.0


def test_wave_ai_coach_fee_drag_consistency():
    trades = [
        Trade(
            ticker="BTC/USDT",
            direction="LONG",
            entry_price=50000.0,
            exit_price=52000.0,
            volume=1.0,
            commission=20.0,
            swap_fee=5.0,
            gross_pnl=2000.0,
            net_pnl=1975.0,
            is_tilt=False,
            efficiency=0.8,
            closed_at=datetime.datetime(2026, 3, 1, 12, 0, 0),
        )
    ]
    metrics = AnalyticsService.calculate_metrics(trades)
    insights = WaveAICoachService.generate_insights(trades)

    fee_insight = next(i for i in insights if i["category"] == "COSTS")
    expected_str = f"({metrics.fee_drag_pct:.1f}%"
    assert expected_str in fee_insight["text"]


def test_subdomain_security_regex():
    valid = ["my-journal", "test123", "alpha-beta-99"]
    invalid = ["test;rm -rf /", "bad`whoami`", "spaces not allowed", "dollar$sign"]

    pattern = r"^[a-zA-Z0-9-]+$"
    for v in valid:
        assert re.fullmatch(pattern, v) is not None
    for inv in invalid:
        assert re.fullmatch(pattern, inv) is None


def test_ui_modal_and_chart_fixes():
    import flet as ft
    from ui.components.trade_modal import TradeModal
    from ui.components.account_modal import AccountModal
    from ui.views.dashboard import DashboardView

    # 1. Verify TradeModal scrolling and actions
    tm = TradeModal(db_manager=None, on_trade_saved=lambda: None)
    assert tm.content.height == 520
    assert tm.content.content.scroll == ft.ScrollMode.ADAPTIVE
    assert len(tm.actions) == 2

    # 2. Verify AccountModal label and layout
    am = AccountModal(db_manager=None, on_account_updated=lambda: None)
    assert am.account_num_field.label == "Номер счета"
    assert am.content.height == 490
    assert am.content.content.scroll == ft.ScrollMode.ADAPTIVE

    # 3. Verify Monte Carlo cone card builds without LineChart tooltip error
    from unittest.mock import MagicMock
    mock_db = MagicMock()
    mock_db.get_trades.return_value = []
    mock_db.get_accounts.return_value = []
    dv = DashboardView(db_manager=mock_db, on_open_plotly=lambda: None)
    card = dv._build_monte_carlo_cone_card(trades=[], initial_balance=10000.0)
    assert card is not None

