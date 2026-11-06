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






