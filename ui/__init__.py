"""
Пакет пользовательского интерфейса (ui)
Экспортирует основные модули: layout, views, components, theme.
"""

from ui.components.command_bar import CommandBar
from ui.components.trade_modal import TradeModal
from ui.layout import AppLayout
from ui.theme import (
    BG_APP,
    BG_SURFACE,
    BG_SURFACE_LIGHT,
    BORDER_COLOR,
    COLOR_ACCENT,
    COLOR_AMBER,
    COLOR_INDIGO,
    COLOR_LONG,
    COLOR_PURPLE,
    COLOR_SHORT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)
from ui.views.dashboard import DashboardView
from ui.views.journal import JournalView

__all__ = [
    "AppLayout",
    "CommandBar",
    "DashboardView",
    "JournalView",
    "TradeModal",
    "BG_APP",
    "BG_SURFACE",
    "BG_SURFACE_LIGHT",
    "BORDER_COLOR",
    "COLOR_ACCENT",
    "COLOR_AMBER",
    "COLOR_INDIGO",
    "COLOR_LONG",
    "COLOR_PURPLE",
    "COLOR_SHORT",
    "TEXT_PRIMARY",
    "TEXT_SECONDARY",
    "TEXT_MUTED",
]
