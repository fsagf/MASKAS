"""
ui/components/command_bar.py
Командная палитра Command Bar (Ctrl + K) в терминальном стиле.
Оверлей со списком быстрых команд (Bloomberg Terminal / VSCode Command Palette).
"""

from typing import Callable, Optional, List
import flet as ft

from database import DatabaseManager, Trade
from ui.theme import (
    ACCENT_PRIMARY,
    ACCENT_SECONDARY,
    ANIM_FAST_MS,
    ANIMATIONS_ENABLED,
    BG_APP,
    BG_SURFACE,
    BORDER_HIGHLIGHT,
    BORDER_SUBTLE,
    FONT_FAMILY,
    FONT_MONO,
    LOSS,
    PROFIT,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    SURFACE_1,
    SURFACE_2,
    SURFACE_OVERLAY,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING_TILT,
    create_neon_box_shadow,
    get_animation,
)


class CommandBar(ft.AlertDialog):
    """
    Всплывающая палитра команд в стиле Bloomberg Terminal / VSCode Command Palette.
    Полностью темный фон, мгновенный показ быстрых действий и поиск по последним сделкам.
    """

    def __init__(
        self,
        on_action_selected: Callable[[str], None],
        db_manager: Optional[DatabaseManager] = None,
    ):
        self.on_action_selected = on_action_selected
        self.db = db_manager

        self.search_input = ft.TextField(
            hint_text="Введите команду или тикер (например: Новая сделка, Тильт, BTC)...",
            hint_style=ft.TextStyle(font_family=FONT_FAMILY, size=12, color=TEXT_MUTED),
            prefix_icon=ft.Icons.TERMINAL_ROUNDED,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            bgcolor=SURFACE_1,
            color=TEXT_PRIMARY,
            border_radius=RADIUS_MD,
            text_size=13,
            dense=True,
            autofocus=True,
            on_change=lambda _: self._filter_commands(),
        )

        self.commands_listview = ft.ListView(
            spacing=6,
            height=300,
        )

        super().__init__(
            modal=True,
            title=ft.Row(
                controls=[
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.KEYBOARD_COMMAND_KEY_ROUNDED, color=ACCENT_PRIMARY, size=20),
                            ft.Text("Command Palette (Ctrl + K)", size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                        ],
                        spacing=8,
                    ),
                    ft.Container(
                        content=ft.Text("ESC to close", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, BORDER_SUBTLE),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        self.search_input,
                        ft.Divider(color=BORDER_SUBTLE, height=10),
                        self.commands_listview,
                    ],
                    spacing=6,
                    tight=True,
                ),
                width=560,
                bgcolor=SURFACE_OVERLAY,
            ),
            bgcolor=SURFACE_OVERLAY,
            shape=ft.RoundedRectangleBorder(radius=RADIUS_LG),
        )
        self._filter_commands()

    def _get_base_commands(self):
        cmds = [
            ("new_trade", "➕ Создать новую сделку", "Зафиксировать позицию в журнале", ft.Icons.ADD_CHART_ROUNDED, ACCENT_PRIMARY, "N"),
            ("open_ai_coach", "🧠 Wave AI Coach — Квантовый анализ", "Персональные рекомендации и аудит торговли", ft.Icons.PSYCHOLOGY_ROUNDED, "#A855F7", "C"),
            ("toggle_tilt", "🔥 Включить/Выключить фильтр Тильта (What-If)", "Показать/скрыть эмоциональные сделки", ft.Icons.PSYCHOLOGY_ROUNDED, WARNING_TILT, "T"),
            ("open_journal", "📊 Перейти в Журнал операций", "Таблица сделок, ордера и риск-инспектор", ft.Icons.TABLE_CHART_ROUNDED, ACCENT_PRIMARY, "J"),
            ("open_backtest", "🕯️ Открыть Симулятор Бэктеста", "Ручное пошаговое тестирование со свечами", ft.Icons.PLAY_CIRCLE_FILLED_ROUNDED, ACCENT_SECONDARY, "B"),
            ("manage_accounts", "🔄 Синхронизировать счета по API", "Управление Binance, Bybit, MT5", ft.Icons.MANAGE_ACCOUNTS_ROUNDED, ACCENT_PRIMARY, "A"),
            ("export_csv", "📥 Экспортировать базу в CSV", "Выгрузить все сделки в trades_export.csv", ft.Icons.DOWNLOAD_ROUNDED, PROFIT, "E"),
            ("open_plotly", "📈 Интерактивный отчет Plotly HTML", "Equity Curve и аналитика в браузере", ft.Icons.INSIGHTS_ROUNDED, ACCENT_SECONDARY, "P"),
            ("reseed_demo", "🔄 Сбросить и наполнить демо-данными", "Пересоздать реалистичные сделки", ft.Icons.REFRESH_ROUNDED, LOSS, "R"),
        ]

        # Добавляем последние сделки из БД для быстрого поиска
        if self.db:
            try:
                recent_trades = self.db.get_trades(limit=5, order_by_date_desc=True)
                for t in recent_trades:
                    pnl_sign = "+" if t.net_pnl >= 0 else ""
                    pnl_col = PROFIT if t.net_pnl >= 0 else LOSS
                    icon_t = ft.Icons.TRENDING_UP_ROUNDED if t.net_pnl >= 0 else ft.Icons.TRENDING_DOWN_ROUNDED
                    cmds.append((
                        f"trade_{t.id}",
                        f"Сделка #{t.id}: {t.ticker} ({t.direction})",
                        f"Net PnL: {pnl_sign}${t.net_pnl:,.2f} • {t.strategy_tag}",
                        icon_t,
                        pnl_col,
                        f"{pnl_sign}${abs(t.net_pnl):,.0f}",
                    ))
            except Exception:
                pass

        return cmds

    def _filter_commands(self):
        query = (self.search_input.value or "").strip().lower()
        items = []

        all_cmds = self._get_base_commands()
        for code, title, desc, icon, color, hotkey in all_cmds:
            if query and query not in title.lower() and query not in desc.lower() and query not in code.lower():
                continue

            btn = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Icon(icon, size=18, color=color),
                            padding=6,
                            bgcolor=ft.Colors.with_opacity(0.12, color),
                            border_radius=RADIUS_SM,
                            border=ft.border.all(1, ft.Colors.with_opacity(0.3, color)),
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(title, size=13, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                ft.Text(desc, size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                            ],
                            spacing=1,
                            expand=True,
                        ),
                        ft.Container(
                            content=ft.Text(hotkey, size=10, weight=ft.FontWeight.BOLD, color=TEXT_SECONDARY, font_family=FONT_MONO),
                            bgcolor=SURFACE_2,
                            padding=ft.padding.symmetric(horizontal=8, vertical=4),
                            border_radius=4,
                            border=ft.border.all(1, BORDER_SUBTLE),
                        ),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                bgcolor=SURFACE_1,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                ink=True,
                on_click=lambda _, c=code: self._execute_action(c),
            )
            items.append(btn)

        self.commands_listview.controls = items
        if self.page:
            self.update()

    def _execute_action(self, action_code: str):
        if self.page:
            try:
                self.page.close(self)
            except Exception:
                self.open = False
                self.page.update()
        else:
            self.open = False
        self.on_action_selected(action_code)

    def show(self, page: ft.Page):
        self.search_input.value = ""
        self._filter_commands()
        try:
            page.open(self)
        except Exception:
            page.dialog = self
            self.open = True
            page.update()

    def open_bar(self, page: ft.Page):
        self.show(page)
