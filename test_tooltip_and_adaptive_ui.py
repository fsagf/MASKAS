"""
Тесты верификации отображения подсказок (tooltips),
адаптивности элементов управления и валидации данных.
"""

import pytest
import flet as ft
from ui.theme import patch_flet_chart_tooltips
from ui.views.backtest import BacktestView
from ui.views.dashboard import DashboardView
from database import DatabaseManager, Trade
from analytics import AnalyticsService


def test_tooltip_unicode_patch():
    """Проверяет, что тултип LineChartDataPoint не подвергается двойному экранированию в JSON."""
    patch_flet_chart_tooltips()
    point = ft.LineChartDataPoint(
        x=1,
        y=100.5,
        tooltip="Сделка #5 • EUR/USD\nРезультат: +150.00 USD\nДепозит: 10,150.00 USD",
        show_tooltip=True,
    )
    point._before_build_command()
    attr_val = point._Control__attrs.get("tooltip")
    assert attr_val is not None
    # Значение должно быть сырой строкой без кавычек JSON и без \\u044
    assert attr_val[0] == "Сделка #5 • EUR/USD\nРезультат: +150.00 USD\nДепозит: 10,150.00 USD"
    assert "\\u044" not in attr_val[0]
    assert not attr_val[0].startswith('"')


def test_backtest_view_adaptive_structure():
    """Проверяет корректность инициализации адаптивной панели управления бэктестом."""
    view = BacktestView()
    assert hasattr(view, "volume_field")
    assert hasattr(view, "sl_field")
    assert hasattr(view, "tp_field")
    assert hasattr(view, "play_btn")
    assert view.play_btn.text == "Play"
    assert view.chart_canvas.expand is True
    assert view.chart_container.expand is True


def test_analytics_metrics_validation():
    """Проверяет отсутствие NaN и деления на ноль в расчете метрик."""
    metrics = AnalyticsService.calculate_metrics([])
    assert metrics.total_trades == 0
    assert metrics.winrate == 0.0
    assert metrics.profit_factor == 0.0
    assert metrics.net_pnl == 0.0

