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
    assert hasattr(dash, "pnl_calendar")
    assert hasattr(dash, "tilt_switch")
    assert dash.content is not None

    # Verify session matrix card renders cleanly
    session_card = dash._build_session_matrix_card(trades=[])
    assert session_card is not None


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

    # 3. Command Bar (Ctrl+K palette)
    cb = CommandBar(on_action_selected=lambda a: None, db_manager=mock_db)
    assert cb is not None

    # 4. PnL Calendar Widget
    cal = PnLCalendar(trades=[], on_date_selected=lambda d: None)
    assert cal is not None
