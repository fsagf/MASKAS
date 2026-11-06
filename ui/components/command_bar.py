"""
ui/components/command_bar.py
Командная палитра Command Bar (Ctrl + K) в терминальном стиле Linear / Bloomberg.
Оверлей со списком быстрых команд, динамической фильтрацией по стратегиям и поиском сделок.
"""

from typing import Callable, Optional, List, Tuple
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
    Всплывающая палитра команд в стиле Linear / Bloomberg Terminal / VSCode Command Palette.
    Полностью темный фон, мгновенный показ быстрых действий, фильтрация по стратегиям и поиск по сделкам.
    """

    CATEGORIES = [
        ("all", "Все"),
        ("actions", "⚡ Действия"),
        ("strategies", "🏷️ Стратегии"),
        ("trades", "📜 Сделки"),
    ]

    def __init__(
        self,
        on_action_selected: Callable[[str], None],
        db_manager: Optional[DatabaseManager] = None,
    ):
        self.on_action_selected = on_action_selected
        self.db = db_manager
        self.current_category = "all"
        self._current_filtered_codes: List[str] = []

        self.search_input = ft.TextField(
            hint_text="Введите команду, тикер или стратегию (например: Breakout, BTC, Тильт)...",
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
            on_submit=lambda _: self._execute_first_command(),
        )

        self.category_chips_row = ft.Row(
            spacing=6,
            scroll=ft.ScrollMode.ADAPTIVE,
        )
        self._build_category_chips()

        self.commands_listview = ft.ListView(
            spacing=6,
            height=320,
        )

        # Подвал с подсказками горячих клавиш в стиле Linear
        footer_shortcuts = ft.Row(
            controls=[
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Text("↵", size=10, weight=ft.FontWeight.BOLD, color=TEXT_SECONDARY, font_family=FONT_MONO),
                            bgcolor=SURFACE_2,
                            padding=ft.padding.symmetric(horizontal=5, vertical=2),
                            border_radius=3,
                            border=ft.border.all(1, BORDER_SUBTLE),
                        ),
                        ft.Text("Выбрать", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                    ],
                    spacing=4,
                ),
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Text("ESC", size=10, weight=ft.FontWeight.BOLD, color=TEXT_SECONDARY, font_family=FONT_MONO),
                            bgcolor=SURFACE_2,
                            padding=ft.padding.symmetric(horizontal=5, vertical=2),
                            border_radius=3,
                            border=ft.border.all(1, BORDER_SUBTLE),
                        ),
                        ft.Text("Закрыть", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                    ],
                    spacing=4,
                ),
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Text("Ctrl+K", size=10, weight=ft.FontWeight.BOLD, color=TEXT_SECONDARY, font_family=FONT_MONO),
                            bgcolor=SURFACE_2,
                            padding=ft.padding.symmetric(horizontal=5, vertical=2),
                            border_radius=3,
                            border=ft.border.all(1, BORDER_SUBTLE),
                        ),
                        ft.Text("Быстрый вызов", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                    ],
                    spacing=4,
                ),
            ],
            spacing=16,
            alignment=ft.MainAxisAlignment.START,
        )

        super().__init__(
            modal=True,
            title=ft.Row(
                controls=[
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.KEYBOARD_COMMAND_KEY_ROUNDED, color=ACCENT_PRIMARY, size=20),
                            ft.Text("Command Palette", size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                        ],
                        spacing=8,
                    ),
                    ft.Container(
                        content=ft.Text("PRO TERMINAL", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                        bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                        padding=ft.padding.symmetric(horizontal=7, vertical=3),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, ft.Colors.with_opacity(0.3, ACCENT_PRIMARY)),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        self.search_input,
                        self.category_chips_row,
                        ft.Divider(color=BORDER_SUBTLE, height=8),
                        self.commands_listview,
                        ft.Divider(color=BORDER_SUBTLE, height=8),
                        footer_shortcuts,
                    ],
                    spacing=6,
                    tight=True,
                ),
                width=580,
                bgcolor=SURFACE_OVERLAY,
            ),
            bgcolor=SURFACE_OVERLAY,
            shape=ft.RoundedRectangleBorder(radius=RADIUS_LG),
        )
        self._filter_commands()

    def _build_category_chips(self):
        chips = []
        for cat_id, cat_title in self.CATEGORIES:
            is_active = self.current_category == cat_id
            bg = ft.Colors.with_opacity(0.18, ACCENT_PRIMARY) if is_active else SURFACE_2
            border_c = ACCENT_PRIMARY if is_active else BORDER_SUBTLE
            text_c = TEXT_PRIMARY if is_active else TEXT_MUTED

            chip = ft.Container(
                content=ft.Text(cat_title, size=11, weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL, color=text_c, font_family=FONT_FAMILY),
                bgcolor=bg,
                padding=ft.padding.symmetric(horizontal=10, vertical=4),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, border_c),
                ink=True,
                on_click=lambda _, c=cat_id: self._select_category(c),
            )
            chips.append(chip)
        self.category_chips_row.controls = chips

    def _select_category(self, cat_id: str):
        self.current_category = cat_id
        self._build_category_chips()
        self._filter_commands()
        if self.page:
            self.update()

    def _get_base_commands(self) -> List[Tuple[str, str, str, str, str, str, str]]:
        """
        Возвращает кортежи команд:
        (code, title, desc, icon, color, hotkey, category)
        """
        cmds: List[Tuple[str, str, str, str, str, str, str]] = [
            ("new_trade", "➕ Создать новую сделку", "Зафиксировать позицию в журнале", ft.Icons.ADD_CHART_ROUNDED, ACCENT_PRIMARY, "N", "actions"),
            ("open_ai_coach", "🧠 Wave AI Coach — Квантовый анализ", "Персональные рекомендации и аудит торговли", ft.Icons.PSYCHOLOGY_ROUNDED, "#A855F7", "C", "actions"),
            ("toggle_tilt", "🔥 Включить/Выключить фильтр Тильта (What-If)", "Показать/скрыть эмоциональные сделки", ft.Icons.PSYCHOLOGY_ROUNDED, WARNING_TILT, "T", "actions"),
            ("open_journal", "📊 Перейти в Журнал операций", "Таблица сделок, ордера и риск-инспектор", ft.Icons.TABLE_CHART_ROUNDED, ACCENT_PRIMARY, "J", "actions"),
            ("open_backtest", "🕯️ Открыть Симулятор Бэктеста", "Ручное пошаговое тестирование со свечами", ft.Icons.PLAY_CIRCLE_FILLED_ROUNDED, ACCENT_SECONDARY, "B", "actions"),
            ("manage_accounts", "🔄 Синхронизировать счета по API", "Управление Binance, Bybit, MT5", ft.Icons.MANAGE_ACCOUNTS_ROUNDED, ACCENT_PRIMARY, "A", "actions"),
            ("export_csv", "📥 Экспортировать базу в CSV", "Выгрузить все сделки в trades_export.csv", ft.Icons.DOWNLOAD_ROUNDED, PROFIT, "E", "actions"),
            ("open_plotly", "📈 Интерактивный отчет Plotly HTML", "Equity Curve и аналитика в браузере", ft.Icons.INSIGHTS_ROUNDED, ACCENT_SECONDARY, "P", "actions"),
            ("reseed_demo", "🔄 Сбросить и наполнить демо-данными", "Пересоздать реалистичные сделки", ft.Icons.REFRESH_ROUNDED, LOSS, "R", "actions"),
        ]

        # Добавляем динамические стратегии из базы данных
        strategies_seen = set()
        if self.db:
            try:
                all_trades = self.db.get_all_trades()
                for t in all_trades:
                    tag = (t.strategy_tag or "").strip()
                    if tag and tag not in strategies_seen:
                        strategies_seen.add(tag)
            except Exception:
                pass

        # Если в базе нет стратегий, используем классический набор сетапов
        if not strategies_seen:
            strategies_seen = {"Breakout", "SMC Order Block", "Pullback", "Trend Following", "Scalping", "Range"}

        for tag in sorted(list(strategies_seen)):
            cmds.append((
                f"strategy_{tag}",
                f"🏷️ Стратегия: {tag}",
                f"Отфильтровать журнал сделок по сетапу '{tag}'",
                ft.Icons.SELL_ROUNDED,
                "#F59E0B",
                "TAG",
                "strategies",
            ))

        # Добавляем последние сделки из БД для быстрого поиска по тикерам
        if self.db:
            try:
                recent_trades = self.db.get_trades(limit=7, order_by_date_desc=True)
                for t in recent_trades:
                    pnl_sign = "+" if t.net_pnl >= 0 else ""
                    pnl_col = PROFIT if t.net_pnl >= 0 else LOSS
                    icon_t = ft.Icons.TRENDING_UP_ROUNDED if t.net_pnl >= 0 else ft.Icons.TRENDING_DOWN_ROUNDED
                    cmds.append((
                        f"trade_{t.id}",
                        f"Сделка #{t.id}: {t.ticker} ({t.direction})",
                        f"Net PnL: {pnl_sign}${t.net_pnl:,.2f} • {t.strategy_tag or 'Без тега'}",
                        icon_t,
                        pnl_col,
                        f"{pnl_sign}${abs(t.net_pnl):,.0f}",
                        "trades",
                    ))
            except Exception:
                pass

        return cmds

    def _filter_commands(self):
        query = (self.search_input.value or "").strip().lower()
        items = []
        filtered_codes = []

        all_cmds = self._get_base_commands()
        for code, title, desc, icon, color, hotkey, category in all_cmds:
            # 1. Фильтр по категории
            if self.current_category != "all" and category != self.current_category:
                continue

            # 2. Текстовый поиск (по названию, описанию, коду или тегу)
            if query and query not in title.lower() and query not in desc.lower() and query not in code.lower():
                continue

            filtered_codes.append(code)

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

        if not items:
            items.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.SEARCH_OFF_ROUNDED, size=28, color=TEXT_MUTED),
                            ft.Text("Команды или сделки не найдены", size=13, color=TEXT_MUTED, font_family=FONT_FAMILY),
                            ft.Text("Попробуйте изменить поисковый запрос или переключить категорию", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=6,
                    ),
                    padding=24,
                    alignment=ft.alignment.center,
                )
            )

        self._current_filtered_codes = filtered_codes
        self.commands_listview.controls = items
        if self.page:
            self.update()

    def _execute_first_command(self):
        """Выполняет первую команду в отфильтрованном списке при нажатии Enter."""
        if self._current_filtered_codes:
            self._execute_action(self._current_filtered_codes[0])

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
        self.current_category = "all"
        self._build_category_chips()
        self._filter_commands()
        try:
            page.open(self)
        except Exception:
            page.dialog = self
            self.open = True
            page.update()

    def open_bar(self, page: ft.Page):
        self.show(page)
