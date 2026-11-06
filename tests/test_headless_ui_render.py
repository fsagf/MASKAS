from unittest.mock import MagicMock
import flet as ft
import pytest

from database import DatabaseManager, Trade
from ui.layout import AppLayout
from ui.views.dashboard import DashboardView
from ui.views.journal import JournalView
from ui.views.backtest import BacktestView
from ui.components.trade_modal import TradeModal
from ui.components.account_modal import AccountModal
from ui.components.command_bar import CommandBar
from ui.components.pnl_calendar import PnLCalendar
from ui.components.time_heatmap import TimeHeatmap


def create_mock_db():
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.get_trades.return_value = []
    mock_db.get_all_trades.return_value = []
    mock_db.get_accounts.return_value = []
    mock_db.get_distinct_strategies.return_value = []
    return mock_db


def test_dashboard_view_headless_render():
    """Verify DashboardView instantiates, renders KPI cards and charts without errors."""
    mock_db = create_mock_db()
    dash = DashboardView(
        db_manager=mock_db,
        on_open_plotly=lambda: None,
        on_date_selected=lambda d: None,
    )
    assert dash is not None
    assert dash.expand is True
    # Verify main UI controls exist
    assert hasattr(dash, "metrics_grid")
    assert hasattr(dash, "chart_container")
    assert hasattr(dash, "monte_carlo_container")
    assert hasattr(dash, "session_matrix_container")
    assert hasattr(dash, "strategy_leaderboard_container")
    assert hasattr(dash, "duration_analysis_container")
    assert hasattr(dash, "asset_allocation_container")
    assert hasattr(dash, "psychology_matrix_container")
    assert hasattr(dash, "drawdown_recovery_container")
    assert hasattr(dash, "excursion_matrix_container")
    assert hasattr(dash, "monthly_phase_container")
    assert hasattr(dash, "sizing_simulator_container")
    assert hasattr(dash, "time_heatmap")
    assert hasattr(dash, "pnl_calendar")
    assert hasattr(dash, "tilt_switch")
    assert dash.content is not None

    # Verify session matrix card renders cleanly
    session_card = dash._build_session_matrix_card(trades=[])
    assert session_card is not None

    # Verify strategy leaderboard card renders cleanly
    strat_card = dash._build_strategy_leaderboard_card(trades=[])
    assert strat_card is not None

    # Verify duration analysis card renders cleanly
    dur_card = dash._build_duration_analysis_card(trades=[])
    assert dur_card is not None

    # Verify asset allocation card renders cleanly
    asset_card = dash._build_asset_allocation_card(trades=[])
    assert asset_card is not None

    # Verify psychology matrix card renders cleanly
    psy_card = dash._build_psychology_matrix_card(trades=[])
    assert psy_card is not None

    # Verify drawdown recovery card renders cleanly
    dd_card = dash._build_drawdown_recovery_card(trades=[])
    assert dd_card is not None

    # Verify excursion matrix card renders cleanly
    exc_card = dash._build_excursion_card(trades=[])
    assert exc_card is not None

    # Verify monthly phase card renders cleanly
    phase_card = dash._build_monthly_phase_card(trades=[])
    assert phase_card is not None

    # Verify position sizing simulator card renders cleanly
    sizing_card = dash._build_position_sizing_simulator_card(trades=[])
    assert sizing_card is not None

    # Verify time heatmap component renders cleanly
    assert dash.time_heatmap.content is not None


def test_journal_view_headless_render():
    """Verify JournalView instantiates and loads trade table container."""
    mock_db = create_mock_db()
    journal = JournalView(
        db_manager=mock_db,
        on_trade_deleted=lambda: None,
        on_edit_requested=lambda t: None,
    )
    assert journal is not None
    assert journal.expand is True
    assert hasattr(journal, "trades_listview")
    assert hasattr(journal, "search_field")
    assert hasattr(journal, "inspector_panel")
    assert journal.content is not None


def test_backtest_view_headless_render():
    """Verify BacktestView instantiates with responsive canvas and execution controls."""
    backtest = BacktestView()
    assert backtest is not None
    assert backtest.expand is True
    assert hasattr(backtest, "chart_canvas")
    assert hasattr(backtest, "balance_text")
    assert hasattr(backtest, "winrate_text")


def test_modals_and_components_headless_render():
    """Verify modals and interactive components initialize with adaptive scroll containers."""
    mock_db = create_mock_db()

    # 1. Trade Modal
    tm = TradeModal(db_manager=mock_db, on_trade_saved=lambda: None)
    assert tm is not None
    assert tm.content.height in (490, 520)
    assert tm.content.content.scroll == ft.ScrollMode.ADAPTIVE
    assert len(tm.actions) == 2

    # 2. Account Modal
    am = AccountModal(db_manager=mock_db, on_account_updated=lambda: None)
    assert am is not None
    assert am.content.height in (470, 490)
    assert am.content.content.scroll == ft.ScrollMode.ADAPTIVE

    # 3. Command Bar (Ctrl+K palette with Linear categories & strategy filters)
    action_recorded = []
    cb = CommandBar(on_action_selected=lambda a: action_recorded.append(a), db_manager=mock_db)
    assert cb is not None
    assert hasattr(cb, "category_chips_row")
    assert len(cb.CATEGORIES) == 4
    assert hasattr(cb, "search_input")
    assert cb.commands_listview is not None
    # Test category switching
    cb._select_category("strategies")
    assert cb.current_category == "strategies"
    # Test search filter
    cb.search_input.value = "breakout"
    cb._filter_commands()
    # Test execute first command
    cb._execute_first_command()
    assert len(action_recorded) == 1
    assert "breakout" in action_recorded[0].lower()

    # 4. PnL Calendar Widget
    cal = PnLCalendar(trades=[], on_date_selected=lambda d: None)
    assert cal is not None

    # 5. Time Heatmap Widget
    thm = TimeHeatmap(trades=[])
    assert thm is not None
    assert thm.content is not None
