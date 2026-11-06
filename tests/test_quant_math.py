import datetime
import math
import numpy as np
import pytest
from database import Trade
from analytics import AnalyticsService, DashboardMetrics, WaveAICoachService


def test_metrics_empty_trades():
    """Verify metrics calculation on empty trade list handles ZeroDivisionError gracefully."""
    metrics = AnalyticsService.calculate_metrics([])
    assert metrics.total_trades == 0
    assert metrics.net_pnl == 0.0
    assert metrics.winrate == 0.0
    assert metrics.profit_factor == 0.0
    assert metrics.expectancy == 0.0
    assert metrics.max_win == 0.0
    assert metrics.max_loss == 0.0
    assert not math.isnan(metrics.profit_factor)
    assert not math.isinf(metrics.profit_factor)


def test_metrics_all_winners_and_all_losers():
    """Verify profit factor and winrate when only wins or only losses exist."""
    # All winners
    win_trade = Trade(
        ticker="BTC/USDT",
        direction="LONG",
        entry_price=60000.0,
        exit_price=63000.0,
        volume=1.0,
        gross_pnl=3000.0,
        net_pnl=2950.0,
        commission=50.0,
        r_multiple=3.0,
        closed_at=datetime.datetime(2026, 3, 1, 10, 0),
    )
    m_win = AnalyticsService.calculate_metrics([win_trade])
    assert m_win.total_trades == 1
    assert m_win.winrate == 100.0
    assert m_win.profit_factor >= 1.0  # Not inf / NaN
    assert not math.isnan(m_win.profit_factor)
    assert not math.isinf(m_win.profit_factor)

    # All losers
    loss_trade = Trade(
        ticker="ETH/USDT",
        direction="SHORT",
        entry_price=3000.0,
        exit_price=3100.0,
        volume=2.0,
        gross_pnl=-200.0,
        net_pnl=-210.0,
        commission=10.0,
        r_multiple=-1.0,
        closed_at=datetime.datetime(2026, 3, 1, 12, 0),
    )
    m_loss = AnalyticsService.calculate_metrics([loss_trade])
    assert m_loss.total_trades == 1
    assert m_loss.winrate == 0.0
    assert m_loss.profit_factor == 0.0


def test_r_multiple_clamping():
    """Verify R-multiples are clamped within [-10, 20] to avoid skewed metrics from data anomalies."""
    t_outlier_high = Trade(
        ticker="SOL/USDT",
        direction="LONG",
        entry_price=100.0,
        exit_price=200.0,
        volume=10.0,
        net_pnl=1000.0,
        risk_amount=5.0,  # Would produce R = 200 without clamping
        closed_at=datetime.datetime(2026, 3, 1, 14, 0),
    )
    t_outlier_high.recalculate_metrics()
    assert t_outlier_high.r_multiple <= 20.0

    t_outlier_low = Trade(
        ticker="SOL/USDT",
        direction="LONG",
        entry_price=100.0,
        exit_price=50.0,
        volume=10.0,
        net_pnl=-500.0,
        risk_amount=5.0,  # Would produce R = -100 without clamping
        closed_at=datetime.datetime(2026, 3, 1, 15, 0),
    )
    t_outlier_low.recalculate_metrics()
    assert t_outlier_low.r_multiple >= -10.0


def test_monte_carlo_bootstrap_simulation():
    """Verify Monte Carlo simulation produces reliable statistical percentiles."""
    trades = [
        Trade(ticker="BTC/USDT", direction="LONG", entry_price=50000.0, exit_price=50150.0, volume=1.0, closed_at=datetime.datetime(2026, 3, 1, 10, 0)),
        Trade(ticker="BTC/USDT", direction="LONG", entry_price=50000.0, exit_price=49920.0, volume=1.0, closed_at=datetime.datetime(2026, 3, 1, 11, 0)),
        Trade(ticker="BTC/USDT", direction="LONG", entry_price=50000.0, exit_price=50220.0, volume=1.0, closed_at=datetime.datetime(2026, 3, 1, 12, 0)),
        Trade(ticker="BTC/USDT", direction="LONG", entry_price=50000.0, exit_price=49950.0, volume=1.0, closed_at=datetime.datetime(2026, 3, 1, 13, 0)),
        Trade(ticker="BTC/USDT", direction="LONG", entry_price=50000.0, exit_price=50310.0, volume=1.0, closed_at=datetime.datetime(2026, 3, 1, 14, 0)),
    ]
    initial_balance = 10000.0
    total_net = sum(t.net_pnl for t in trades)
    expected_start = initial_balance + total_net

    mc = AnalyticsService.simulate_monte_carlo(
        trades=trades,
        n_simulations=1000,
        n_steps=20,
        initial_balance=initial_balance,
    )

    assert "p05" in mc
    assert "p50" in mc
    assert "p95" in mc
    assert "risk_of_ruin" in mc
    assert len(mc["p50"]) == 21
    # Check baseline starts exactly at current equity
    assert mc["p50"][0] == pytest.approx(expected_start, rel=1e-4)
    # 95th percentile should be greater than or equal to 5th percentile at the end
    assert mc["p95"][-1] >= mc["p05"][-1]
    assert 0.0 <= mc["risk_of_ruin"] <= 100.0


def test_tilt_detection_rules():
    """Verify tilt detection logic for revenge trading and over-risking."""
    prev_trade_loss = Trade(
        id=1,
        ticker="BTC/USDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=49000.0,
        volume=1.0,
        stop_loss=49000.0,
        closed_at=datetime.datetime(2026, 3, 2, 10, 0, 0),
    )
    assert prev_trade_loss.net_pnl < 0

    # 1. Revenge Trading (new trade entered within 10 minutes of loss)
    candidate_revenge = {
        "opened_at": datetime.datetime(2026, 3, 2, 10, 5, 0),
        "risk_amount": 100.0,
        "volume": 1.0,
        "checklist_passed": True,
    }
    is_tilt, reason = AnalyticsService.detect_tilt(candidate_revenge, [prev_trade_loss])
    assert is_tilt is True
    assert "Revenge" in reason

    # 2. Calm trade (entered after 30 minutes, normal risk) -> No tilt
    candidate_calm = {
        "opened_at": datetime.datetime(2026, 3, 2, 10, 35, 0),
        "risk_amount": 100.0,
        "volume": 1.0,
        "checklist_passed": True,
    }
    is_tilt, _ = AnalyticsService.detect_tilt(candidate_calm, [prev_trade_loss])
    assert is_tilt is False

    # 3. Over-risking (risk is >= 2x the baseline after losses)
    t1_loss = Trade(
        id=1,
        ticker="BTC/USDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=49900.0,
        volume=1.0,
        stop_loss=49900.0,  # risk_amount = 100.0
        closed_at=datetime.datetime(2026, 3, 2, 10, 0, 0),
    )
    t2_loss = Trade(
        id=2,
        ticker="BTC/USDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=49900.0,
        volume=1.0,
        stop_loss=49900.0,  # risk_amount = 100.0
        closed_at=datetime.datetime(2026, 3, 2, 10, 40, 0),
    )
    candidate_overrisk = {
        "opened_at": datetime.datetime(2026, 3, 2, 11, 20, 0),
        "risk_amount": 300.0,  # 3x the 100.0 baseline
        "volume": 1.0,
        "checklist_passed": True,
    }
    is_tilt, reason = AnalyticsService.detect_tilt(candidate_overrisk, [t1_loss, t2_loss])
    assert is_tilt is True
    assert "риска" in reason.lower() or "risk" in reason.lower()


def test_sqn_and_sharpe_sortino_metrics():
    """Verify System Quality Number (Van Tharp) and Sharpe / Sortino quant ratios."""
    # Create a sequence of trades with consistent positive R-multiples
    trades = [
        Trade(
            ticker="BTC/USDT",
            direction="LONG",
            entry_price=50000.0,
            exit_price=52000.0,
            volume=1.0,
            stop_loss=49000.0,  # Risk = 1000, PnL = +2000 -> R = +2.0
            closed_at=datetime.datetime(2026, 3, 1, 10, 0),
        ),
        Trade(
            ticker="ETH/USDT",
            direction="LONG",
            entry_price=3000.0,
            exit_price=3150.0,
            volume=10.0,
            stop_loss=2900.0,  # Risk = 1000, PnL = +1500 -> R = +1.5
            closed_at=datetime.datetime(2026, 3, 1, 12, 0),
        ),
        Trade(
            ticker="SOL/USDT",
            direction="LONG",
            entry_price=100.0,
            exit_price=118.0,
            volume=100.0,
            stop_loss=90.0,  # Risk = 1000, PnL = +1800 -> R = +1.8
            closed_at=datetime.datetime(2026, 3, 1, 14, 0),
        ),
        Trade(
            ticker="AVAX/USDT",
            direction="LONG",
            entry_price=40.0,
            exit_price=38.0,
            volume=500.0,
            stop_loss=38.0,  # Risk = 1000, PnL = -1000 -> R = -1.0
            closed_at=datetime.datetime(2026, 3, 1, 16, 0),
        ),
    ]

    metrics = AnalyticsService.calculate_metrics(trades)

    # 1. SQN should be positive and classified
    assert metrics.sqn > 0.0
    assert metrics.sqn_rating != "N/A"
    assert any(term in metrics.sqn_rating for term in ("Слабая", "Средняя", "Хорошая", "Отличная", "Великолепная"))

    # 2. Sharpe and Sortino ratios should be calculated
    assert metrics.sharpe_ratio > 0.0
    assert metrics.sortino_ratio >= metrics.sharpe_ratio  # Sortino typically >= Sharpe when upside dominates


def test_session_performance_matrix():
    """Verify session mapping and quant metrics for Asian, London, NY, and Off-Hours sessions."""
    # Empty trades test
    empty_res = AnalyticsService.calculate_session_matrix([])
    assert "sessions" in empty_res
    assert set(empty_res["sessions"].keys()) == {"ASIAN", "LONDON", "NEW_YORK", "OFF_HOURS"}
    assert empty_res["best_session"] is None
    assert empty_res["worst_session"] is None

    # Mixed sessions trades
    t_asia = Trade(
        ticker="BTC/USDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=51000.0,
        volume=1.0,
        opened_at=datetime.datetime(2026, 3, 2, 3, 30, 0),  # 03:30 -> ASIAN
    )
    t_london_win = Trade(
        ticker="EUR/USD",
        direction="LONG",
        entry_price=1.0800,
        exit_price=1.0900,
        volume=100000.0,
        opened_at=datetime.datetime(2026, 3, 2, 9, 15, 0),  # 09:15 -> LONDON
    )
    t_london_loss = Trade(
        ticker="GBP/USD",
        direction="SHORT",
        entry_price=1.2700,
        exit_price=1.2750,
        volume=50000.0,
        opened_at=datetime.datetime(2026, 3, 2, 11, 45, 0),  # 11:45 -> LONDON
    )
    t_ny = Trade(
        ticker="NVDA",
        direction="LONG",
        entry_price=120.0,
        exit_price=135.0,
        volume=50.0,
        opened_at=datetime.datetime(2026, 3, 2, 15, 30, 0),  # 15:30 -> NEW_YORK
    )
    t_off = Trade(
        ticker="ETH/USDT",
        direction="SHORT",
        entry_price=3000.0,
        exit_price=3100.0,
        volume=2.0,
        opened_at=datetime.datetime(2026, 3, 2, 22, 10, 0),  # 22:10 -> OFF_HOURS
    )

    trades = [t_asia, t_london_win, t_london_loss, t_ny, t_off]
    res = AnalyticsService.calculate_session_matrix(trades)
    s = res["sessions"]

    assert s["ASIAN"]["trades_count"] == 1
    assert s["ASIAN"]["net_pnl"] == 1000.0
    assert s["ASIAN"]["winrate"] == 100.0

    assert s["LONDON"]["trades_count"] == 2
    assert s["LONDON"]["win_trades"] == 1
    assert s["LONDON"]["loss_trades"] == 1
    assert s["LONDON"]["winrate"] == 50.0

    assert s["NEW_YORK"]["trades_count"] == 1
    assert s["NEW_YORK"]["net_pnl"] == 750.0

    assert s["OFF_HOURS"]["trades_count"] == 1
    assert s["OFF_HOURS"]["net_pnl"] == -200.0
    assert s["OFF_HOURS"]["winrate"] == 0.0

    # Best session should be ASIAN or LONDON (highest net_pnl), worst should be OFF_HOURS
    assert res["worst_session"] == "OFF_HOURS"
    assert res["best_session"] in ("ASIAN", "LONDON")


def test_time_heatmap_matrix():
    """Verify Day-of-Week and Hour-of-Day aggregation and cell calculations."""
    # Empty trades test
    empty_hm = AnalyticsService.calculate_time_heatmap([])
    assert "cells" in empty_hm
    assert len(empty_hm["cells"]) == 7
    for d in range(7):
        assert len(empty_hm["cells"][d]) == 24
    assert empty_hm["best_day"] is None
    assert empty_hm["best_hour"] is None

    # Populate test trades on specific days/hours
    # Wednesday (weekday 2), 14:00 UTC (hour 14) -> +$500
    t_wed = Trade(
        ticker="BTC/USDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=50500.0,
        volume=1.0,
        opened_at=datetime.datetime(2026, 3, 4, 14, 20, 0),  # Wednesday
    )
    # Friday (weekday 4), 18:00 UTC (hour 18) -> -$300
    t_fri = Trade(
        ticker="ETH/USDT",
        direction="LONG",
        entry_price=3000.0,
        exit_price=2850.0,
        volume=2.0,
        opened_at=datetime.datetime(2026, 3, 6, 18, 5, 0),  # Friday
    )

    hm = AnalyticsService.calculate_time_heatmap([t_wed, t_fri])
    cells = hm["cells"]

    # Check Wednesday 14:00
    c_wed = cells[2][14]
    assert c_wed["count"] == 1
    assert c_wed["net_pnl"] == 500.0
    assert c_wed["winrate"] == 100.0

    # Check Friday 18:00
    c_fri = cells[4][18]
    assert c_fri["count"] == 1
    assert c_fri["net_pnl"] == -300.0
    assert c_fri["winrate"] == 0.0

    # Check unpopulated cell
    assert cells[0][0]["count"] == 0
    assert cells[0][0]["net_pnl"] == 0.0

    # Day aggregates
    assert hm["day_aggregates"][2]["net_pnl"] == 500.0
    assert hm["day_aggregates"][4]["net_pnl"] == -300.0
    assert hm["best_day"]["day_idx"] == 2
    assert hm["worst_day"]["day_idx"] == 4
    assert hm["best_hour"]["hour"] == 14


def test_kelly_criterion_and_streaks():
    """Verify Kelly Criterion position sizing and consecutive win/loss streaks calculation."""
    # 1. Empty trades
    empty_kelly = AnalyticsService.calculate_kelly_criterion([])
    assert empty_kelly["kelly_fraction_pct"] == 0.0
    assert empty_kelly["is_edge_positive"] is False

    empty_streaks = AnalyticsService.calculate_streaks([])
    assert empty_streaks["max_win_streak"] == 0
    assert empty_streaks["current_streak"] == 0

    # 2. Sequence of trades: Win, Win, Win, Loss, Loss, Win
    trades = [
        Trade(direction="LONG", entry_price=100.0, exit_price=120.0, volume=10.0, closed_at=datetime.datetime(2026, 3, 1, 10, 0)),   # +200
        Trade(direction="LONG", entry_price=100.0, exit_price=115.0, volume=10.0, closed_at=datetime.datetime(2026, 3, 1, 11, 0)),   # +150
        Trade(direction="LONG", entry_price=100.0, exit_price=130.0, volume=10.0, closed_at=datetime.datetime(2026, 3, 1, 12, 0)),   # +300
        Trade(direction="LONG", entry_price=100.0, exit_price=90.0, volume=10.0, closed_at=datetime.datetime(2026, 3, 1, 13, 0)),    # -100
        Trade(direction="LONG", entry_price=100.0, exit_price=88.0, volume=10.0, closed_at=datetime.datetime(2026, 3, 1, 14, 0)),    # -120
        Trade(direction="LONG", entry_price=100.0, exit_price=118.0, volume=10.0, closed_at=datetime.datetime(2026, 3, 1, 15, 0)),   # +180
    ]

    metrics = AnalyticsService.calculate_metrics(trades)
    assert metrics.kelly_fraction_pct > 0.0
    assert metrics.half_kelly_pct > 0.0
    assert metrics.half_kelly_pct == pytest.approx(metrics.kelly_fraction_pct / 2.0, abs=0.1)

    streaks = AnalyticsService.calculate_streaks(trades)
    assert streaks["max_win_streak"] == 3
    assert streaks["max_loss_streak"] == 2
    assert streaks["current_streak"] == 1

    # Verify metrics fields align
    assert metrics.max_win_streak == 3
    assert metrics.max_loss_streak == 2
    assert metrics.current_streak == 1


def test_strategy_leaderboard_matrix():
    """Verify strategy grouping, profit factor, winrate, and ranking in strategy leaderboard."""
    # 1. Empty trades
    assert AnalyticsService.calculate_strategy_leaderboard([]) == []

    # 2. Trades with distinct strategies
    t_bo1 = Trade(strategy_tag="Breakout", direction="LONG", entry_price=100.0, exit_price=150.0, volume=10.0, stop_loss=90.0)    # +$500
    t_bo2 = Trade(strategy_tag="Breakout", direction="LONG", entry_price=100.0, exit_price=130.0, volume=10.0, stop_loss=90.0)    # +$300
    t_mr_win = Trade(strategy_tag="Mean Reversion", direction="LONG", entry_price=100.0, exit_price=120.0, volume=10.0, stop_loss=90.0)  # +$200
    t_mr_loss = Trade(strategy_tag="Mean Reversion", direction="LONG", entry_price=100.0, exit_price=60.0, volume=10.0, stop_loss=90.0)   # -$400
    t_scalp = Trade(strategy_tag="Scalp", direction="SHORT", entry_price=100.0, exit_price=110.0, volume=10.0, stop_loss=110.0)   # -$100

    trades = [t_bo1, t_bo2, t_mr_win, t_mr_loss, t_scalp]
    board = AnalyticsService.calculate_strategy_leaderboard(trades)

    assert len(board) == 3

    # Rank 1: Breakout (+800)
    assert board[0]["tag"] == "Breakout"
    assert board[0]["rank"] == 1
    assert board[0]["net_pnl"] == 800.0
    assert board[0]["winrate"] == 100.0
    assert board[0]["trades_count"] == 2

    # Rank 2: Scalp (-100)
    assert board[1]["tag"] == "Scalp"
    assert board[1]["rank"] == 2
    assert board[1]["net_pnl"] == -100.0

    # Rank 3: Mean Reversion (-200)
    assert board[2]["tag"] == "Mean Reversion"
    assert board[2]["rank"] == 3
    assert board[2]["net_pnl"] == -200.0
    assert board[2]["winrate"] == 50.0


def test_trade_duration_matrix():
    """Verify holding time categorization across Scalp, Short/Mid Intraday, Day Trade, and Swing."""
    # 1. Empty trades
    empty_dur = AnalyticsService.calculate_duration_matrix([])
    assert "brackets" in empty_dur
    assert set(empty_dur["brackets"].keys()) == {"SCALP", "SHORT_INTRA", "MID_INTRA", "DAY_TRADE", "SWING"}
    assert empty_dur["best_duration"] is None

    # 2. Trades with specific durations
    now = datetime.datetime(2026, 3, 1, 10, 0, 0)

    # 5 mins -> SCALP (+250)
    t_scalp = Trade(
        direction="LONG", entry_price=100.0, exit_price=125.0, volume=10.0,
        opened_at=now, closed_at=now + datetime.timedelta(minutes=5),
    )
    # 30 mins -> SHORT_INTRA (+180)
    t_short = Trade(
        direction="LONG", entry_price=100.0, exit_price=118.0, volume=10.0,
        opened_at=now, closed_at=now + datetime.timedelta(minutes=30),
    )
    # 2.5 hours -> MID_INTRA (+600)
    t_mid = Trade(
        direction="LONG", entry_price=100.0, exit_price=160.0, volume=10.0,
        opened_at=now, closed_at=now + datetime.timedelta(hours=2, minutes=30),
    )
    # 8 hours -> DAY_TRADE (-350)
    t_day = Trade(
        direction="LONG", entry_price=100.0, exit_price=65.0, volume=10.0,
        opened_at=now, closed_at=now + datetime.timedelta(hours=8),
    )
    # 36 hours -> SWING (+1200)
    t_swing = Trade(
        direction="LONG", entry_price=100.0, exit_price=220.0, volume=10.0,
        opened_at=now, closed_at=now + datetime.timedelta(hours=36),
    )

    trades = [t_scalp, t_short, t_mid, t_day, t_swing]
    matrix = AnalyticsService.calculate_duration_matrix(trades)
    b = matrix["brackets"]

    assert b["SCALP"]["trades_count"] == 1
    assert b["SCALP"]["net_pnl"] == 250.0

    assert b["SHORT_INTRA"]["trades_count"] == 1
    assert b["SHORT_INTRA"]["net_pnl"] == 180.0

    assert b["MID_INTRA"]["trades_count"] == 1
    assert b["MID_INTRA"]["net_pnl"] == 600.0

    assert b["DAY_TRADE"]["trades_count"] == 1
    assert b["DAY_TRADE"]["net_pnl"] == -350.0

    assert b["SWING"]["trades_count"] == 1
    assert b["SWING"]["net_pnl"] == 1200.0

    assert matrix["best_duration"] == "SWING"
    assert matrix["worst_duration"] == "DAY_TRADE"


def test_asset_allocation_matrix():
    """Verify asset class categorization, turnover volume weighting, and concentration risk triggers."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_asset_allocation_matrix([])
    assert "asset_classes" in empty_mat
    assert set(empty_mat["asset_classes"].keys()) == {"CRYPTO", "FOREX", "EQUITIES", "COMMODITIES"}
    assert empty_mat["best_class"] is None
    assert empty_mat["concentration_warning"] is None

    # 2. Multi-asset portfolio
    t_btc = Trade(ticker="BTCUSDT", direction="LONG", entry_price=100.0, exit_price=150.0, volume=10.0)    # +500, vol=1000
    t_eth = Trade(ticker="ETHUSDT", direction="LONG", entry_price=100.0, exit_price=120.0, volume=10.0)    # +200, vol=1000
    t_fx = Trade(ticker="EUR/USD", direction="LONG", entry_price=100.0, exit_price=110.0, volume=10.0)     # +100, vol=1000
    t_stock = Trade(ticker="AAPL", direction="LONG", entry_price=100.0, exit_price=80.0, volume=10.0)      # -200, vol=1000
    t_gold = Trade(ticker="XAU/USD", direction="LONG", entry_price=100.0, exit_price=130.0, volume=10.0)   # +300, vol=1000

    trades = [t_btc, t_eth, t_fx, t_stock, t_gold]
    matrix = AnalyticsService.calculate_asset_allocation_matrix(trades)
    classes = matrix["asset_classes"]

    # Verify classification
    assert classes["CRYPTO"]["trades_count"] == 2
    assert classes["CRYPTO"]["net_pnl"] == 700.0
    assert classes["CRYPTO"]["winrate"] == 100.0

    assert classes["FOREX"]["trades_count"] == 1
    assert classes["FOREX"]["net_pnl"] == 100.0

    assert classes["COMMODITIES"]["trades_count"] == 1
    assert classes["COMMODITIES"]["net_pnl"] == 300.0

    assert classes["EQUITIES"]["trades_count"] == 1
    assert classes["EQUITIES"]["net_pnl"] == -200.0

    assert matrix["best_class"] == "CRYPTO"
    assert matrix["worst_class"] == "EQUITIES"
    assert len(matrix["top_symbols"]) <= 6

    # 3. High concentration risk trigger test (>40% volume)
    t_heavy = Trade(ticker="SOLUSDT", direction="LONG", entry_price=100.0, exit_price=150.0, volume=80.0)  # vol=8000
    t_light1 = Trade(ticker="EUR/USD", direction="LONG", entry_price=100.0, exit_price=110.0, volume=5.0)  # vol=500
    t_light2 = Trade(ticker="AAPL", direction="LONG", entry_price=100.0, exit_price=105.0, volume=5.0)     # vol=500

    conc_matrix = AnalyticsService.calculate_asset_allocation_matrix([t_heavy, t_light1, t_light2])
    assert conc_matrix["concentration_warning"] is not None
    assert "SOLUSDT" in conc_matrix["concentration_warning"]


def test_psychology_matrix():
    """Verify Edgewonk-style discipline scoring, tilt cost drag, and emotional leak identification."""
    # 1. Empty trades
    empty_psy = AnalyticsService.calculate_psychology_matrix([])
    assert empty_psy["discipline_score_pct"] == 100.0
    assert empty_psy["tilt_drag_amount"] == 0.0
    assert empty_psy["primary_emotional_leak"] is None
    assert len(empty_psy["reasons_breakdown"]) == 0

    # 2. Fully disciplined portfolio
    t_clean1 = Trade(ticker="BTCUSDT", direction="LONG", entry_price=100.0, exit_price=150.0, volume=10.0, is_tilt=False)
    t_clean2 = Trade(ticker="ETHUSDT", direction="LONG", entry_price=100.0, exit_price=90.0, volume=10.0, is_tilt=False)
    clean_mat = AnalyticsService.calculate_psychology_matrix([t_clean1, t_clean2])
    assert clean_mat["discipline_score_pct"] == 100.0
    assert clean_mat["tilt_drag_amount"] == 0.0
    assert clean_mat["tilt_trades"] == 0

    # 3. Mixed portfolio with Revenge and FOMO errors
    t_bo = Trade(ticker="BTCUSDT", direction="LONG", entry_price=100.0, exit_price=150.0, volume=10.0, is_tilt=False)     # +500
    t_eth = Trade(ticker="ETHUSDT", direction="LONG", entry_price=100.0, exit_price=130.0, volume=10.0, is_tilt=False)    # +300
    t_stop = Trade(ticker="SOLUSDT", direction="LONG", entry_price=100.0, exit_price=90.0, volume=10.0, is_tilt=False)    # -100
    t_revenge = Trade(ticker="SOLUSDT", direction="LONG", entry_price=100.0, exit_price=60.0, volume=10.0, is_tilt=True, tilt_reason="Revenge trade after stop")  # -400
    t_fomo = Trade(ticker="DOGEUSDT", direction="LONG", entry_price=100.0, exit_price=85.0, volume=10.0, is_tilt=True, tilt_reason="FOMO entry on peak")        # -150

    trades = [t_bo, t_eth, t_stop, t_revenge, t_fomo]
    psy_mat = AnalyticsService.calculate_psychology_matrix(trades)

    assert psy_mat["total_trades"] == 5
    assert psy_mat["disciplined_trades"] == 3
    assert psy_mat["tilt_trades"] == 2
    assert psy_mat["discipline_score_pct"] == 60.0
    assert psy_mat["disciplined_net_pnl"] == 700.0
    assert psy_mat["tilt_net_pnl"] == -550.0
    assert psy_mat["actual_net_pnl"] == 150.0
    assert psy_mat["tilt_drag_amount"] == 550.0
    assert "Revenge" in psy_mat["primary_emotional_leak"]
    assert len(psy_mat["reasons_breakdown"]) == 2


def test_drawdown_recovery_matrix():
    """Verify TraderSync-style drawdown calculation, peak-to-valley tracking, and recovery factor."""
    # 1. Empty trades
    empty_dd = AnalyticsService.calculate_drawdown_recovery_matrix([])
    assert empty_dd["max_drawdown_amount"] == 0.0
    assert empty_dd["recovery_factor"] == 0.0
    assert empty_dd["ulcer_index"] == 0.0

    # 2. Sequential trades
    now = datetime.datetime(2026, 3, 1, 10, 0, 0)
    # T1: +1000 (Peak = 11000)
    t1 = Trade(direction="LONG", entry_price=100.0, exit_price=110.0, volume=100.0, closed_at=now + datetime.timedelta(hours=1))
    # T2: -400 (Equity = 10600, DD = 400)
    t2 = Trade(direction="LONG", entry_price=100.0, exit_price=96.0, volume=100.0, closed_at=now + datetime.timedelta(hours=2))
    # T3: -600 (Equity = 10000, DD = 1000, Valley!)
    t3 = Trade(direction="LONG", entry_price=100.0, exit_price=94.0, volume=100.0, closed_at=now + datetime.timedelta(hours=3))
    # T4: +1500 (Equity = 11500, New Peak = 11500, Recovery!)
    t4 = Trade(direction="LONG", entry_price=100.0, exit_price=115.0, volume=100.0, closed_at=now + datetime.timedelta(hours=4))
    # T5: -300 (Equity = 11200, Current DD = 300)
    t5 = Trade(direction="LONG", entry_price=100.0, exit_price=97.0, volume=100.0, closed_at=now + datetime.timedelta(hours=5))

    trades = [t1, t2, t3, t4, t5]
    dd_mat = AnalyticsService.calculate_drawdown_recovery_matrix(trades, initial_balance=10000.0)

    assert dd_mat["max_drawdown_amount"] == 1000.0
    assert dd_mat["max_drawdown_pct"] == pytest.approx(9.1, abs=0.1)
    assert dd_mat["net_pnl"] == 1200.0
    assert dd_mat["recovery_factor"] == pytest.approx(1.2, abs=0.05)
    assert dd_mat["peak_to_valley_trades"] == 2
    assert dd_mat["current_drawdown_amount"] == 300.0
    assert dd_mat["ulcer_index"] > 0.0

    # 3. Verify DashboardMetrics population
    metrics = AnalyticsService.calculate_metrics(trades)
    assert metrics.max_drawdown_amount == 1000.0
    assert metrics.recovery_factor == pytest.approx(1.2, abs=0.05)
    assert metrics.ulcer_index > 0.0


def test_excursion_matrix():
    """Verify TradeZella-style MAE/MFE execution quality, Edge Ratio, and left-on-table retention."""
    # 1. Empty trades
    empty_exc = AnalyticsService.calculate_excursion_matrix([])
    assert empty_exc["total_trades"] == 0
    assert empty_exc["edge_ratio"] == 0.0
    assert empty_exc["edge_rating"] == "N/A"

    # 2. Trades with explicit MAE/MFE prices
    # T1: Long 100 -> exit 140 (PnL +400). MAE price = 98 (-2.0%), MFE price = 150 (+50.0%)
    t1 = Trade(
        direction="LONG", entry_price=100.0, exit_price=140.0, volume=10.0,
        mae_price=98.0, mfe_price=150.0,
    )
    # T2: Long 100 -> exit 120 (PnL +200). MAE price = 96 (-4.0%), MFE price = 130 (+30.0%)
    t2 = Trade(
        direction="LONG", entry_price=100.0, exit_price=120.0, volume=10.0,
        mae_price=96.0, mfe_price=130.0,
    )

    trades = [t1, t2]
    exc = AnalyticsService.calculate_excursion_matrix(trades)

    assert exc["total_trades"] == 2
    assert exc["avg_mae_pct"] == pytest.approx(3.0, abs=0.1)
    assert exc["avg_mfe_pct"] == pytest.approx(40.0, abs=0.1)
    assert exc["edge_ratio"] > 5.0
    assert "Превосходный" in exc["edge_rating"]
    assert exc["avg_efficiency_pct"] > 0.0


def test_monthly_phase_matrix():
    """Verify TraderSync/Edgewonk-style monthly decade partitioning and seasonal cyclicity."""
    # 1. Empty trades
    empty_p = AnalyticsService.calculate_monthly_phase_matrix([])
    assert set(empty_p["phases"].keys()) == {"EARLY_MONTH", "MID_MONTH", "LATE_MONTH"}
    assert empty_p["best_phase"] is None

    # 2. Trades in different decades of March 2026
    # Early (day 5): +500
    t_early = Trade(
        direction="LONG", entry_price=100.0, exit_price=150.0, volume=10.0,
        closed_at=datetime.datetime(2026, 3, 5, 12, 0),
    )
    # Mid (day 15): +200
    t_mid = Trade(
        direction="LONG", entry_price=100.0, exit_price=120.0, volume=10.0,
        closed_at=datetime.datetime(2026, 3, 15, 12, 0),
    )
    # Late (day 25): -100
    t_late = Trade(
        direction="LONG", entry_price=100.0, exit_price=90.0, volume=10.0,
        closed_at=datetime.datetime(2026, 3, 25, 12, 0),
    )

    trades = [t_early, t_mid, t_late]
    mat = AnalyticsService.calculate_monthly_phase_matrix(trades)
    phases = mat["phases"]

    assert phases["EARLY_MONTH"]["trades_count"] == 1
    assert phases["EARLY_MONTH"]["net_pnl"] == 500.0
    assert phases["EARLY_MONTH"]["winrate"] == 100.0

    assert phases["MID_MONTH"]["trades_count"] == 1
    assert phases["MID_MONTH"]["net_pnl"] == 200.0

    assert phases["LATE_MONTH"]["trades_count"] == 1
    assert phases["LATE_MONTH"]["net_pnl"] == -100.0
    assert phases["LATE_MONTH"]["winrate"] == 0.0

    assert mat["best_phase"] == "EARLY_MONTH"
    assert mat["worst_phase"] == "LATE_MONTH"
    assert "Начало месяца" in mat["seasonal_insight"]


def test_position_sizing_simulator():
    """Verify QuantConnect-style position sizing simulation across Flat 1%, Kelly, and Fixed risk."""
    # 1. Empty trades
    empty_sim = AnalyticsService.simulate_position_sizing_models([])
    assert set(empty_sim["models"].keys()) == {"FLAT_1PCT", "HALF_KELLY", "FULL_KELLY", "FIXED_DOLLAR"}
    assert empty_sim["optimal_model"] == "HALF_KELLY"

    # 2. Sequential trades with positive edge
    now = datetime.datetime(2026, 3, 1, 10, 0, 0)
    t1 = Trade(direction="LONG", entry_price=100.0, exit_price=120.0, volume=10.0, stop_loss=90.0, closed_at=now + datetime.timedelta(hours=1))  # R = +2.0
    t2 = Trade(direction="LONG", entry_price=100.0, exit_price=115.0, volume=10.0, stop_loss=90.0, closed_at=now + datetime.timedelta(hours=2))  # R = +1.5
    t3 = Trade(direction="LONG", entry_price=100.0, exit_price=90.0, volume=10.0, stop_loss=90.0, closed_at=now + datetime.timedelta(hours=3))   # R = -1.0
    t4 = Trade(direction="LONG", entry_price=100.0, exit_price=130.0, volume=10.0, stop_loss=90.0, closed_at=now + datetime.timedelta(hours=4))  # R = +3.0

    trades = [t1, t2, t3, t4]
    sim = AnalyticsService.simulate_position_sizing_models(trades, initial_balance=10000.0)
    models = sim["models"]

    # All models should show positive growth with these net winning trades
    assert models["FLAT_1PCT"]["final_equity"] > 10000.0
    assert models["HALF_KELLY"]["final_equity"] > 10000.0
    assert models["FIXED_DOLLAR"]["final_equity"] > 10000.0

    assert sim["optimal_model"] in models
    assert len(sim["optimal_insight"]) > 10


def test_market_regime_matrix():
    """Verify market regime alignment across Bull Trend, Bear Trend, Range Chop, and Breakout Expansion."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_market_regime_matrix([])
    assert set(empty_mat["regimes"].keys()) == {"BULL_TREND", "BEAR_TREND", "RANGE_CHOP", "BREAKOUT_EXPANSION"}
    assert empty_mat["best_regime"] is None

    # 2. Categorized trades
    t_bull = Trade(strategy_tag="Trend Long", notes="Восходящий тренд", direction="LONG", entry_price=100.0, exit_price=130.0, volume=10.0) # +300
    t_bear = Trade(strategy_tag="Short Selloff", notes="Нисходящий тренд", direction="SHORT", entry_price=100.0, exit_price=80.0, volume=10.0) # +200
    t_chop = Trade(strategy_tag="Range Mean Reversion", notes="Флэт у границы", direction="LONG", entry_price=100.0, exit_price=85.0, volume=10.0) # -150
    t_bo = Trade(strategy_tag="Breakout Momentum", notes="Импульсный пробой ATH", direction="LONG", entry_price=100.0, exit_price=160.0, volume=10.0) # +600

    trades = [t_bull, t_bear, t_chop, t_bo]
    mat = AnalyticsService.calculate_market_regime_matrix(trades)
    regimes = mat["regimes"]

    assert regimes["BULL_TREND"]["trades_count"] == 1
    assert regimes["BULL_TREND"]["net_pnl"] == 300.0
    assert regimes["BULL_TREND"]["winrate"] == 100.0

    assert regimes["BEAR_TREND"]["trades_count"] == 1
    assert regimes["BEAR_TREND"]["net_pnl"] == 200.0

    assert regimes["RANGE_CHOP"]["trades_count"] == 1
    assert regimes["RANGE_CHOP"]["net_pnl"] == -150.0
    assert regimes["RANGE_CHOP"]["winrate"] == 0.0

    assert regimes["BREAKOUT_EXPANSION"]["trades_count"] == 1
    assert regimes["BREAKOUT_EXPANSION"]["net_pnl"] == 600.0

    assert mat["best_regime"] == "BREAKOUT_EXPANSION"
    assert mat["worst_regime"] == "RANGE_CHOP"
    assert len(mat["regime_insight"]) > 5


def test_r_distribution_matrix():
    """Verify R-multiple frequency distribution, binning, skewness and kurtosis calculations."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_r_distribution_matrix([])
    assert len(empty_mat["bins"]) == 7
    assert empty_mat["skewness"] == 0.0
    assert empty_mat["kurtosis"] == 0.0
    assert empty_mat["total_trades"] == 0

    # 2. Trades across distinct R buckets (all risk = 100)
    # R = +4.0 (>3R)
    t_hr = Trade(direction="LONG", entry_price=100.0, exit_price=140.0, volume=10.0, stop_loss=90.0)
    # R = +2.5 (2R..3R)
    t_runner = Trade(direction="LONG", entry_price=100.0, exit_price=125.0, volume=10.0, stop_loss=90.0)
    # R = +1.5 (1R..2R)
    t_target = Trade(direction="LONG", entry_price=100.0, exit_price=115.0, volume=10.0, stop_loss=90.0)
    # R = +0.3 (0R..1R)
    t_scratch = Trade(direction="LONG", entry_price=100.0, exit_price=103.0, volume=10.0, stop_loss=90.0)
    # R = -0.9 (-1R..0R)
    t_stop = Trade(direction="LONG", entry_price=100.0, exit_price=91.0, volume=10.0, stop_loss=90.0)
    # R = -2.5 (<-2R)
    t_fat = Trade(direction="LONG", entry_price=100.0, exit_price=75.0, volume=10.0, stop_loss=90.0)

    trades = [t_hr, t_runner, t_target, t_scratch, t_stop, t_fat]
    mat = AnalyticsService.calculate_r_distribution_matrix(trades)

    assert mat["total_trades"] == 6
    assert mat["home_runs_count"] == 1
    assert mat["fat_tail_losses_count"] == 1
    assert mat["avg_winner_r"] > 0
    assert mat["avg_loser_r"] < 0

    bin_map = {b["key"]: b for b in mat["bins"]}
    assert bin_map["GT_3R"]["trades_count"] == 1
    assert bin_map["TWO_TO_3R"]["trades_count"] == 1
    assert bin_map["ONE_TO_2R"]["trades_count"] == 1
    assert bin_map["ZERO_TO_1R"]["trades_count"] == 1
    assert bin_map["MINUS_1_TO_0R"]["trades_count"] == 1
    assert bin_map["LT_MINUS_2R"]["trades_count"] == 1
    assert bin_map["MINUS_2_TO_1R"]["trades_count"] == 0

    assert isinstance(mat["skewness"], float)
    assert isinstance(mat["kurtosis"], float)
    assert len(mat["distribution_profile"]) > 10


def test_rr_efficiency_matrix():
    """Verify planned vs realized R:R execution efficiency and leakage calculations."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_rr_efficiency_matrix([])
    assert empty_mat["execution_efficiency_pct"] == 0.0
    assert empty_mat["total_leakage_dollars"] == 0.0
    assert empty_mat["execution_grade"] == "N/A"

    # 2. Disciplined vs Premature exits
    # Trade 1: Entry=100, SL=90, TP=130 (Planned R:R = 3.0), Exit=130 (Hit full target)
    t_full = Trade(direction="LONG", entry_price=100.0, exit_price=130.0, volume=10.0, stop_loss=90.0, take_profit=130.0) # Net PnL = +300, Eff = 100%
    # Trade 2: Entry=100, SL=90, TP=130 (Planned R:R = 3.0), Exit=115 (Early fear exit)
    t_early = Trade(direction="LONG", entry_price=100.0, exit_price=115.0, volume=10.0, stop_loss=90.0, take_profit=130.0) # Net PnL = +150, Target=300, Leakage=150, Eff=50%
    # Trade 3: Entry=100, SL=90, TP=130, Exit=90 (Stop hit)
    t_loss = Trade(direction="LONG", entry_price=100.0, exit_price=90.0, volume=10.0, stop_loss=90.0, take_profit=130.0) # Net PnL = -100

    trades = [t_full, t_early, t_loss]
    mat = AnalyticsService.calculate_rr_efficiency_matrix(trades)

    assert mat["avg_planned_rr"] == 3.0
    assert mat["total_leakage_dollars"] == 150.0
    assert mat["disciplined_exits_count"] == 1
    assert mat["premature_exits_count"] == 1
    assert mat["execution_efficiency_pct"] == 75.0
    assert "B" in mat["execution_grade"]
    assert len(mat["leakage_insight"]) > 5


def test_rule_violation_matrix():
    """Verify rule violation categorization, financial drag and discipline grading."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_rule_violation_matrix([])
    assert len(empty_mat["rules"]) == 6
    assert empty_mat["rules_followed_rate_pct"] == 100.0
    assert empty_mat["total_rule_drag"] == 0.0

    # 2. Trades with specific rule violations
    t_clean = Trade(direction="LONG", entry_price=100.0, exit_price=120.0, volume=10.0, stop_loss=90.0, notes="Идеально по сетапу") # +200
    t_no_sl = Trade(direction="LONG", entry_price=100.0, exit_price=80.0, volume=10.0, stop_loss=None, notes="без стопа") # -200
    t_fomo = Trade(direction="LONG", entry_price=100.0, exit_price=70.0, volume=10.0, stop_loss=90.0, notes="FOMO погоня") # -300
    t_revenge = Trade(direction="LONG", entry_price=100.0, exit_price=60.0, volume=10.0, stop_loss=90.0, notes="тильт реванш", is_tilt=True) # -400
    t_early = Trade(direction="LONG", entry_price=100.0, exit_price=105.0, volume=10.0, stop_loss=90.0, notes="вышел рано от страха") # +50
    t_over = Trade(direction="LONG", entry_price=100.0, exit_price=85.0, volume=10.0, stop_loss=90.0, notes="завышенный объем") # -150

    trades = [t_clean, t_no_sl, t_fomo, t_revenge, t_early, t_over]
    mat = AnalyticsService.calculate_rule_violation_matrix(trades)

    assert mat["total_trades"] == 6
    assert mat["clean_trades_count"] == 1
    assert mat["rules_followed_rate_pct"] == pytest.approx(16.7, abs=0.2)
    assert mat["total_rule_drag"] == 1050.0
    assert mat["most_costly_violation"] == "Тильт / Реванш"

    rule_map = {r["key"]: r for r in mat["rules"]}
    assert rule_map["NO_STOP_LOSS"]["count"] == 1
    assert rule_map["NO_STOP_LOSS"]["dollar_loss"] == 200.0

    assert rule_map["CHASING_FOMO"]["count"] == 1
    assert rule_map["CHASING_FOMO"]["dollar_loss"] == 300.0

    assert rule_map["REVENGE_TRADING"]["count"] == 1
    assert rule_map["REVENGE_TRADING"]["dollar_loss"] == 400.0

    assert rule_map["EARLY_EXIT"]["count"] == 1
    assert rule_map["OVER_LEVERAGED"]["count"] == 1
    assert rule_map["OVER_LEVERAGED"]["dollar_loss"] == 150.0

    assert "F" in mat["discipline_grade"]
    assert len(mat["discipline_insight"]) > 5


def test_mtf_alignment_matrix():
    """Verify multi-timeframe trend alignment, confluence categorization and edge ratios."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_mtf_alignment_matrix([])
    assert set(empty_mat["alignments"].keys()) == {"TRIPLE_ALIGNED", "DOUBLE_ALIGNED", "PULLBACK_COUNTER", "CHOP_UNALIGNED"}
    assert empty_mat["best_alignment"] is None
    assert empty_mat["mtf_edge_ratio"] == 1.0

    # 2. Trades across MTF categories
    t_triple = Trade(direction="LONG", entry_price=100.0, exit_price=150.0, volume=10.0, notes="HTF+LTF институциональный тренд") # +500
    t_double = Trade(direction="LONG", entry_price=100.0, exit_price=120.0, volume=10.0, notes="Trend продолжение") # +200
    t_pullback = Trade(direction="LONG", entry_price=100.0, exit_price=85.0, volume=10.0, notes="контртренд откат") # -150
    t_chop = Trade(direction="LONG", entry_price=100.0, exit_price=75.0, volume=10.0, notes="боковик распил") # -250

    trades = [t_triple, t_double, t_pullback, t_chop]
    mat = AnalyticsService.calculate_mtf_alignment_matrix(trades)
    al = mat["alignments"]

    assert mat["total_trades"] == 4
    assert al["TRIPLE_ALIGNED"]["trades_count"] == 1
    assert al["TRIPLE_ALIGNED"]["net_pnl"] == 500.0
    assert al["TRIPLE_ALIGNED"]["winrate"] == 100.0

    assert al["DOUBLE_ALIGNED"]["trades_count"] == 1
    assert al["DOUBLE_ALIGNED"]["net_pnl"] == 200.0

    assert al["PULLBACK_COUNTER"]["trades_count"] == 1
    assert al["PULLBACK_COUNTER"]["net_pnl"] == -150.0

    assert al["CHOP_UNALIGNED"]["trades_count"] == 1
    assert al["CHOP_UNALIGNED"]["net_pnl"] == -250.0
    assert al["CHOP_UNALIGNED"]["winrate"] == 0.0

    assert mat["best_alignment"] == "TRIPLE_ALIGNED"
    assert mat["mtf_edge_ratio"] > 1.0
    assert len(mat["mtf_insight"]) > 10


def test_compliance_routine_matrix():
    """Verify pre-trade checklist compliance, score distribution and alpha correlation."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_compliance_routine_matrix([])
    assert set(empty_mat["brackets"].keys()) == {"HIGH", "MODERATE", "LOW"}
    assert empty_mat["avg_compliance_pct"] == 0.0
    assert empty_mat["compliance_grade"] == "N/A"

    # 2. Trades with distinct compliance profiles
    # High: SL set, R:R 3.0, clean, strategy tag
    t_high = Trade(direction="LONG", entry_price=100.0, exit_price=130.0, volume=10.0, stop_loss=90.0, take_profit=130.0, strategy_tag="Breakout", notes="по плану") # +300
    # Moderate: SL set, no hard TP, clean, strategy tag
    t_mod = Trade(direction="LONG", entry_price=100.0, exit_price=110.0, volume=10.0, stop_loss=90.0, strategy_tag="Scalp", notes="") # +100
    # Low: No SL, no TP, no strategy, tilt in notes
    t_low = Trade(direction="LONG", entry_price=100.0, exit_price=70.0, volume=10.0, stop_loss=None, notes="тильт FOMO вход", is_tilt=True) # -300

    trades = [t_high, t_mod, t_low]
    mat = AnalyticsService.calculate_compliance_routine_matrix(trades)
    b = mat["brackets"]

    assert mat["total_trades"] == 3
    assert b["HIGH"]["trades_count"] >= 1
    assert b["LOW"]["trades_count"] == 1
    assert b["LOW"]["net_pnl"] == -300.0
    assert b["LOW"]["winrate"] == 0.0

    assert mat["avg_compliance_pct"] > 50.0
    assert mat["criteria_compliance"]["STOP_LOSS"] == pytest.approx(66.7, abs=0.5)
    assert len(mat["compliance_insight"]) > 10


def test_session_overlap_matrix():
    """Verify session overlap liquidity window classification, alpha ratios and PnL breakdown."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_session_overlap_matrix([])
    assert set(empty_mat["windows"].keys()) == {"LONDON_NY_OVERLAP", "ASIA_LONDON_TRANSITION", "NY_AFTERNOON_CLOSE", "OFF_PEAK_CHOP"}
    assert empty_mat["best_window"] is None
    assert empty_mat["overlap_alpha_ratio"] == 1.0

    # 2. Trades in distinct institutional liquidity windows
    # 14:30 UTC -> LONDON_NY_OVERLAP (+400)
    t_overlap = Trade(direction="LONG", entry_price=100.0, exit_price=140.0, volume=10.0, closed_at=datetime.datetime(2026, 3, 2, 14, 30))
    # 08:00 UTC -> ASIA_LONDON_TRANSITION (+200)
    t_trans = Trade(direction="LONG", entry_price=100.0, exit_price=120.0, volume=10.0, closed_at=datetime.datetime(2026, 3, 2, 8, 0))
    # 18:30 UTC -> NY_AFTERNOON_CLOSE (+150)
    t_ny = Trade(direction="LONG", entry_price=100.0, exit_price=115.0, volume=10.0, closed_at=datetime.datetime(2026, 3, 2, 18, 30))
    # 02:00 UTC -> OFF_PEAK_CHOP (-100)
    t_off = Trade(direction="LONG", entry_price=100.0, exit_price=90.0, volume=10.0, closed_at=datetime.datetime(2026, 3, 2, 2, 0))

    trades = [t_overlap, t_trans, t_ny, t_off]
    mat = AnalyticsService.calculate_session_overlap_matrix(trades)
    w = mat["windows"]

    assert mat["total_trades"] == 4
    assert w["LONDON_NY_OVERLAP"]["trades_count"] == 1
    assert w["LONDON_NY_OVERLAP"]["net_pnl"] == 400.0
    assert w["LONDON_NY_OVERLAP"]["winrate"] == 100.0

    assert w["ASIA_LONDON_TRANSITION"]["trades_count"] == 1
    assert w["ASIA_LONDON_TRANSITION"]["net_pnl"] == 200.0

    assert w["NY_AFTERNOON_CLOSE"]["trades_count"] == 1
    assert w["NY_AFTERNOON_CLOSE"]["net_pnl"] == 150.0

    assert w["OFF_PEAK_CHOP"]["trades_count"] == 1
    assert w["OFF_PEAK_CHOP"]["net_pnl"] == -100.0
    assert w["OFF_PEAK_CHOP"]["winrate"] == 0.0

    assert mat["best_window"] == "LONDON_NY_OVERLAP"
    assert mat["worst_window"] == "OFF_PEAK_CHOP"
    assert mat["overlap_alpha_ratio"] > 1.0
    assert len(mat["overlap_insight"]) > 10


def test_setup_grading_matrix():
    """Verify playbook setup quality grading (A+/A/B/C), winrates, drag calculation and alpha insights."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_setup_grading_matrix([])
    assert set(empty_mat["tiers"].keys()) == {"A_PLUS", "A_TIER", "B_TIER", "C_TIER"}
    assert empty_mat["best_tier"] is None
    assert empty_mat["a_tier_discipline_pct"] == 0.0

    # 2. Trades in distinct quality tiers
    # A+ Setup: full target, high RR, clear strategy
    t_a_plus = Trade(direction="LONG", entry_price=100.0, exit_price=150.0, volume=10.0, stop_loss=90.0, take_profit=150.0, strategy_tag="Order Block", notes="A+ эталон") # +500
    # A Setup: good target, standard RR
    t_a = Trade(direction="LONG", entry_price=100.0, exit_price=125.0, volume=10.0, stop_loss=90.0, take_profit=125.0, strategy_tag="Breakout", notes="класс a") # +250
    # B Setup: acceptable secondary setup
    t_b = Trade(direction="LONG", entry_price=100.0, exit_price=115.0, volume=10.0, stop_loss=90.0, strategy_tag="Scalp", notes="класс b") # +150
    # C Setup: sub-optimal / noise
    t_c = Trade(direction="LONG", entry_price=100.0, exit_price=80.0, volume=10.0, stop_loss=None, notes="хлам вход") # -200

    trades = [t_a_plus, t_a, t_b, t_c]
    mat = AnalyticsService.calculate_setup_grading_matrix(trades)
    tiers = mat["tiers"]

    assert mat["total_trades"] == 4
    assert tiers["A_PLUS"]["trades_count"] == 1
    assert tiers["A_PLUS"]["net_pnl"] == 500.0
    assert tiers["A_PLUS"]["winrate"] == 100.0

    assert tiers["A_TIER"]["trades_count"] == 1
    assert tiers["A_TIER"]["net_pnl"] == 250.0

    assert tiers["B_TIER"]["trades_count"] == 1
    assert tiers["B_TIER"]["net_pnl"] == 150.0

    assert tiers["C_TIER"]["trades_count"] == 1
    assert tiers["C_TIER"]["net_pnl"] == -200.0
    assert tiers["C_TIER"]["winrate"] == 0.0

    assert mat["best_tier"] == "A_PLUS"
    assert mat["a_tier_discipline_pct"] == 50.0
    assert mat["c_tier_loss_drag"] == 200.0
    assert len(mat["setup_grading_insight"]) > 10


def test_tag_attribution_matrix():
    """Verify trade tag performance cloud, factor extraction from hashtags/notes, and factor attribution."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_tag_attribution_matrix([])
    assert empty_mat["tags"] == []
    assert empty_mat["top_profitable_tag"] is None
    assert empty_mat["top_drag_tag"] is None
    assert empty_mat["unique_tags_count"] == 0

    # 2. Trades with strategy tags and hashtags
    t1 = Trade(direction="LONG", entry_price=100.0, exit_price=150.0, volume=10.0, strategy_tag="Breakout", notes="#FVG пробой")
    t2 = Trade(direction="LONG", entry_price=100.0, exit_price=120.0, volume=10.0, strategy_tag="Breakout", notes="#News")
    t3 = Trade(direction="LONG", entry_price=100.0, exit_price=70.0, volume=10.0, strategy_tag="Scalp", notes="тильт вход #Chop")

    trades = [t1, t2, t3]
    mat = AnalyticsService.calculate_tag_attribution_matrix(trades)

    assert mat["total_trades"] == 3
    assert mat["unique_tags_count"] >= 3
    assert mat["top_profitable_tag"] in ("Breakout", "FVG")
    assert mat["top_drag_tag"] in ("Scalp", "Chop", "Тильт")

    tags_dict = {item["tag"]: item for item in mat["tags"]}
    assert "Breakout" in tags_dict
    assert tags_dict["Breakout"]["net_pnl"] == 700.0
    assert tags_dict["Breakout"]["winrate"] == 100.0
    assert tags_dict["Breakout"]["category"] == "PROFIT_DRIVER"

    assert "Scalp" in tags_dict
    assert tags_dict["Scalp"]["net_pnl"] == -300.0
    assert tags_dict["Scalp"]["category"] == "DRAWDOWN_LEAK"
    assert len(mat["attribution_insight"]) > 5


def test_rolling_edge_matrix():
    """Verify rolling 30-day Sharpe, winrate momentum, and edge decay detection."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_rolling_edge_matrix([])
    assert empty_mat["edge_momentum"] == "INSUFFICIENT_DATA"
    assert empty_mat["decay_alert"] is False
    assert empty_mat["current_window"]["trades_count"] == 0

    # 2. Expanding edge: Prior period is break-even/slight, current period is highly profitable
    now = datetime.datetime.now()
    t_old1 = Trade(direction="LONG", entry_price=100.0, exit_price=110.0, volume=10.0, closed_at=now - datetime.timedelta(days=45)) # +100
    t_old2 = Trade(direction="LONG", entry_price=100.0, exit_price=90.0, volume=10.0, closed_at=now - datetime.timedelta(days=40))  # -100

    t_new1 = Trade(direction="LONG", entry_price=100.0, exit_price=130.0, volume=10.0, closed_at=now - datetime.timedelta(days=10)) # +300
    t_new2 = Trade(direction="LONG", entry_price=100.0, exit_price=125.0, volume=10.0, closed_at=now - datetime.timedelta(days=5))  # +250
    t_new3 = Trade(direction="LONG", entry_price=100.0, exit_price=120.0, volume=10.0, closed_at=now - datetime.timedelta(days=2))  # +200

    trades_expanding = [t_old1, t_old2, t_new1, t_new2, t_new3]
    mat_exp = AnalyticsService.calculate_rolling_edge_matrix(trades_expanding, window_days=30)

    assert mat_exp["current_window"]["trades_count"] == 3
    assert mat_exp["current_window"]["winrate"] == 100.0
    assert mat_exp["current_window"]["net_pnl"] == 750.0
    assert mat_exp["prior_window"]["trades_count"] == 2
    assert mat_exp["prior_window"]["winrate"] == 50.0
    assert mat_exp["prior_window"]["net_pnl"] == 0.0
    assert mat_exp["winrate_delta"] == 50.0
    assert mat_exp["edge_momentum"] == "EXPANDING_EDGE"
    assert mat_exp["decay_alert"] is False

    # 3. Decaying edge: Prior period profitable, current period experiencing sharp losses
    t_decay1 = Trade(direction="LONG", entry_price=100.0, exit_price=70.0, volume=10.0, closed_at=now - datetime.timedelta(days=8)) # -300
    t_decay2 = Trade(direction="LONG", entry_price=100.0, exit_price=60.0, volume=10.0, closed_at=now - datetime.timedelta(days=3)) # -400

    trades_decaying = [t_new1, t_new2, t_decay1, t_decay2]
    # Emulate by setting old trades as profitable, recent trades as decaying
    t_old_win1 = Trade(direction="LONG", entry_price=100.0, exit_price=130.0, volume=10.0, closed_at=now - datetime.timedelta(days=40)) # +300
    t_old_win2 = Trade(direction="LONG", entry_price=100.0, exit_price=125.0, volume=10.0, closed_at=now - datetime.timedelta(days=35)) # +250
    trades_decay = [t_old_win1, t_old_win2, t_decay1, t_decay2]

    mat_dec = AnalyticsService.calculate_rolling_edge_matrix(trades_decay, window_days=30)
    assert mat_dec["current_window"]["net_pnl"] == -700.0
    assert mat_dec["current_window"]["winrate"] == 0.0
    assert mat_dec["prior_window"]["net_pnl"] == 550.0
    assert mat_dec["edge_momentum"] == "DECAYING_EDGE"
    assert mat_dec["decay_alert"] is True
    assert "Внимание" in mat_dec["edge_insight"]


def test_prop_consistency_radar():
    """Verify prop firm consistency rule scoring (single trade/day profit concentration, lot size variance)."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_prop_consistency_radar([])
    assert empty_mat["consistency_score"] == 0.0
    assert empty_mat["readiness_status"] == "NO_DATA"
    assert empty_mat["total_trades"] == 0

    now = datetime.datetime.now()
    # 2. Well-distributed trades (pass consistency)
    trades_consistent = [
        Trade(direction="LONG", entry_price=100.0, exit_price=120.0, volume=1.0, closed_at=now - datetime.timedelta(days=5)),
        Trade(direction="LONG", entry_price=100.0, exit_price=125.0, volume=1.0, closed_at=now - datetime.timedelta(days=4)),
        Trade(direction="LONG", entry_price=100.0, exit_price=118.0, volume=1.0, closed_at=now - datetime.timedelta(days=3)),
        Trade(direction="LONG", entry_price=100.0, exit_price=122.0, volume=1.0, closed_at=now - datetime.timedelta(days=2)),
        Trade(direction="LONG", entry_price=100.0, exit_price=115.0, volume=1.0, closed_at=now - datetime.timedelta(days=1)),
    ]
    mat_cons = AnalyticsService.calculate_prop_consistency_radar(trades_consistent)
    assert mat_cons["readiness_status"] == "FUNDED_READY"
    assert mat_cons["trade_concentration_pass"] is True
    assert mat_cons["day_concentration_pass"] is True
    assert mat_cons["sizing_uniformity_pass"] is True
    assert mat_cons["consistency_score"] >= 80.0

    # 3. Lottery Trade concentration (single outlier trade > 50% of profit)
    trades_lottery = [
        Trade(direction="LONG", entry_price=100.0, exit_price=200.0, volume=10.0, closed_at=now - datetime.timedelta(days=5)),
        Trade(direction="LONG", entry_price=100.0, exit_price=105.0, volume=1.0, closed_at=now - datetime.timedelta(days=4)),
        Trade(direction="LONG", entry_price=100.0, exit_price=104.0, volume=1.0, closed_at=now - datetime.timedelta(days=3)),
    ]
    mat_lottery = AnalyticsService.calculate_prop_consistency_radar(trades_lottery)
    assert mat_lottery["best_trade_share_pct"] > 90.0
    assert mat_lottery["trade_concentration_pass"] is False
    assert mat_lottery["readiness_status"] == "LOTTERY_DEPENDENCY"
    assert "Риск дисквалификации" in mat_lottery["consistency_insight"]


def test_order_placement_efficiency():
    """Verify Edgewonk SL/TP placement efficiency, premature stop-outs and MFE capture ratio."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_order_placement_efficiency([])
    assert empty_mat["target_capture_efficiency_pct"] == 0.0
    assert empty_mat["premature_stopout_count"] == 0
    assert empty_mat["placement_grade"] == "N/A"

    # 2. Winning trades with high capture efficiency
    t_win1 = Trade(direction="LONG", entry_price=100.0, exit_price=140.0, volume=10.0)
    t_win1.mfe = 450.0
    t_win2 = Trade(direction="LONG", entry_price=100.0, exit_price=130.0, volume=10.0)
    t_win2.mfe = 320.0
    trades_optimal = [t_win1, t_win2]

    mat_opt = AnalyticsService.calculate_order_placement_efficiency(trades_optimal)
    assert mat_opt["target_capture_efficiency_pct"] > 85.0
    assert mat_opt["premature_stopout_count"] == 0
    assert mat_opt["premature_stopout_drag"] == 0.0
    assert mat_opt["placement_grade"] in ("A+", "A")

    # 3. Trades with premature stop-out and early leakage
    t_loss_premature = Trade(direction="LONG", entry_price=100.0, exit_price=85.0, volume=10.0, notes="выбило стоп и полетело")
    t_loss_premature.mfe = 300.0
    t_win_early = Trade(direction="LONG", entry_price=100.0, exit_price=110.0, volume=10.0)
    t_win_early.mfe = 400.0

    trades_leaking = [t_loss_premature, t_win_early]
    mat_leak = AnalyticsService.calculate_order_placement_efficiency(trades_leaking)

    assert mat_leak["premature_stopout_count"] == 1
    assert mat_leak["premature_stopout_drag"] == 150.0
    assert mat_leak["early_exit_leakage"] == 300.0
    assert "Стоп-лосс слишком тесный" in mat_leak["placement_insight"]
    assert mat_leak["optimal_sl_buffer_recommendation"] == "+25% (Расширить SL)"


def test_factor_information_coefficient():
    """Verify Factor Information Coefficient (Rank IC), Spearman correlation, and predictive alpha classification."""
    # 1. Empty trades
    empty_mat = AnalyticsService.calculate_factor_information_coefficient([])
    assert empty_mat["factors"] == []
    assert empty_mat["top_factor"] is None
    assert empty_mat["total_trades"] == 0

    # 2. Trades with distinct factor signals and outcomes
    t1 = Trade(direction="LONG", entry_price=100.0, exit_price=160.0, stop_loss=80.0, take_profit=160.0, volume=10.0, notes="3x triple confluence")
    t2 = Trade(direction="LONG", entry_price=100.0, exit_price=130.0, stop_loss=85.0, take_profit=130.0, volume=5.0, notes="h1 trend")
    t3 = Trade(direction="LONG", entry_price=100.0, exit_price=80.0, stop_loss=70.0, take_profit=110.0, volume=2.0, notes="тильт вход fomo")

    trades = [t1, t2, t3]
    mat = AnalyticsService.calculate_factor_information_coefficient(trades)

    assert mat["total_trades"] == 3
    assert len(mat["factors"]) == 4
    assert mat["top_factor"] is not None
    assert mat["top_factor_ic"] >= 0.5
    assert any(f["category"] in ("ELITE_ALPHA", "MODERATE_ALPHA") for f in mat["factors"])
    assert len(mat["ic_insight"]) > 10

























