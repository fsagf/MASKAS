"""
ui/layout.py
Оболочка макета приложения Trading Journal Pro в терминальном стиле.
Включает:
- Верхнюю панель с Dropdown переключения торговых счетов ("Все счета", Binance, MT5)
  и кнопкой вызова модального окна управления счетами и API-синхронизации (AccountModal).
- Быстрые действия: вызов палитры команд (Ctrl+K), экспорт Plotly HTML, индикатор состояния БД.
- Боковую навигацию NavigationRail с адаптивным сворачиванием, акцентным индикатором и брендингом.
- Анимированное переключение экранов (AnimatedSwitcher Fade).
- Интерактивную связку P&L Календаря с переходом в Журнал по клику на день.
"""

from datetime import date
from pathlib import Path
from typing import Callable, Optional
import flet as ft

from analytics import AnalyticsService
from database import DatabaseManager, Trade
from ui.components.account_modal import AccountModal
from ui.components.command_bar import CommandBar
from ui.components.trade_modal import TradeModal
from ui.theme import (
    ACCENT_PRIMARY,
    ACCENT_SECONDARY,
    ANIM_FAST_MS,
    ANIM_NORMAL_MS,
    ANIMATIONS_ENABLED,
    BG_APP,
    BG_SURFACE,
    BORDER_HIGHLIGHT,
    BORDER_SUBTLE,
    FONT_FAMILY,
    FONT_MONO,
    PROFIT,
    RADIUS_MD,
    RADIUS_PILL,
    RADIUS_SM,
    SURFACE_1,
    SURFACE_2,
    SURFACE_3,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    create_neon_box_shadow,
    get_animation,
)
from ui.views.backtest import BacktestView
from ui.views.dashboard import DashboardView
from ui.views.journal import JournalView


class AppLayout(ft.Row):
    """
    Корневой макет приложения с адаптивным NavigationRail и динамической рабочей областью.
    """

    def __init__(self, page: ft.Page, db_manager: DatabaseManager, on_open_plotly: Callable[[], None]):
        super().__init__(expand=True, spacing=0)
        self.page = page
        self.db = db_manager
        self.on_open_plotly = on_open_plotly

        self.selected_account_id: Optional[int] = None

        # 1. Инициализация экранов
        self.dashboard_view = DashboardView(
            self.db,
            on_open_plotly=self.on_open_plotly,
            on_date_selected=self._on_calendar_date_selected,
            page=self.page,
        )
        self.journal_view = JournalView(
            self.db,
            on_trade_deleted=self._on_trade_data_changed,
            on_edit_requested=self.open_edit_trade_modal,
            page=self.page,
        )
        self.backtest_view = BacktestView(page=self.page)

        self.views = [self.dashboard_view, self.journal_view, self.backtest_view]
        self.current_index = 0

        # 2. Модальные окна
        self.trade_modal = TradeModal(self.db, on_trade_saved=self._on_trade_data_changed)
        self.account_modal = AccountModal(self.db, on_account_updated=self._on_accounts_updated)

        # 3. Командная палитра Command Palette (Ctrl+K)
        self.command_bar = CommandBar(on_action_selected=self.handle_command_bar_action, db_manager=self.db)

        # Текстовый индикатор подключения базы данных SQLite
        self.db_status_text = ft.Text("SQLite Connected", size=11, color=TEXT_SECONDARY, font_family=FONT_MONO)

        # 4. Дропдаун мульти-аккаунтов в шапке
        self.account_dropdown = ft.Dropdown(
            label="Активный счет",
            label_style=ft.TextStyle(size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
            width=260,
            dense=True,
            bgcolor=SURFACE_2,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            color=TEXT_PRIMARY,
            text_size=12,
            border_radius=RADIUS_MD,
            on_change=self._on_account_dropdown_changed,
        )
        self._populate_account_options()

        # 5. Контейнер отображения текущего экрана (прямая замена без наложения)
        self.content_container = ft.Container(
            content=self.dashboard_view,
            expand=True,
            padding=ft.padding.only(left=20, right=24, top=14, bottom=16),
            bgcolor=BG_APP,
        )
        self.content_area = self.content_container

        # 6. Верхняя панель (Header Bar)
        top_header_bar = self._build_top_header()

        # 7. Боковая навигация NavigationRail
        self.nav_rail = self._build_navigation_rail()
        self._update_db_status()

        # Правая рабочая колонка: Top Header + Разделитель + Контент экрана
        main_workspace = ft.Column(
            controls=[
                top_header_bar,
                self.content_container,
            ],
            expand=True,
            spacing=0,
        )

        self.controls = [
            self.nav_rail,
            ft.VerticalDivider(width=1, color=BORDER_SUBTLE),
            main_workspace,
        ]

    def did_mount(self):
        """Гарантирует передачу ссылки на page всем дочерним экранам."""
        if self.page:
            self.dashboard_view._page_ref = self.page
            self.journal_view._page_ref = self.page
            self.backtest_view._page_ref = self.page

    def _build_top_header(self) -> ft.Container:
        """Создает шапку приложения с переключателем счетов и быстрыми действиями."""
        accounts_btn = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.MANAGE_ACCOUNTS_OUTLINED, size=15, color=ACCENT_PRIMARY),
                    ft.Text("Счета & API", size=12, color=TEXT_PRIMARY, weight=ft.FontWeight.W_600),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_2,
            
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            ink=True,
            on_click=lambda _: self.open_account_modal(),
            tooltip="Управление подключенными биржами, API ключами и автосинхронизацией",
        )

        cmd_pill = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SEARCH_ROUNDED, size=14, color=TEXT_MUTED),
                    ft.Text("Палитра команд", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                    ft.Container(
                        content=ft.Text("Ctrl+K", size=9, weight=ft.FontWeight.BOLD, color=TEXT_SECONDARY, font_family=FONT_MONO),
                        bgcolor=BG_APP,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                        border_radius=4,
                        
                    ),
                ],
                spacing=8,
            ),
            bgcolor=SURFACE_2,
            
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=12, vertical=7),
            ink=True,
            on_click=lambda _: self.command_bar.open_bar(self.page),
            tooltip="Открыть терминальную палитру команд (Ctrl+K)",
        )

        plotly_pill = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.INSIGHTS_ROUNDED, size=14, color=ACCENT_SECONDARY),
                    ft.Text("Plotly HTML", size=11, color=TEXT_PRIMARY, weight=ft.FontWeight.W_600),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_2,
            
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=10, vertical=7),
            ink=True,
            on_click=lambda _: self.on_open_plotly(),
            tooltip="Интерактивный анализ эквити и просадок в браузере (Plotly)",
        )

        status_pill = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        width=7,
                        height=7,
                        border_radius=RADIUS_PILL,
                        bgcolor=PROFIT,
                        shadow=ft.BoxShadow(spread_radius=1, blur_radius=6, color=ft.Colors.with_opacity(0.5, PROFIT)),
                    ),
                    self.db_status_text,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=SURFACE_2,
            
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=12, vertical=7),
        )

        sync_quick_btn = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SYNC_ROUNDED, size=15, color=ACCENT_SECONDARY),
                    ft.Text("Синхронизировать", size=12, color=ACCENT_SECONDARY, weight=ft.FontWeight.W_600),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_2,
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=12, vertical=7),
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, ACCENT_SECONDARY)),
            on_click=lambda _: self._quick_sync_current(),
            tooltip="Синхронизировать выбранный счет (или все счета)",
        )

        return ft.Container(
            content=ft.Row(
                [
                    ft.Row(
                        [
                            self.account_dropdown,
                            accounts_btn,
                            sync_quick_btn,
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            cmd_pill,
                            plotly_pill,
                            status_pill,
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=SURFACE_1,
            border=ft.Border(bottom=ft.BorderSide(1, BORDER_SUBTLE)),
            padding=ft.padding.symmetric(horizontal=20, vertical=8),
        )

    def _quick_sync_current(self) -> None:
        """Быстрая автосинхронизация текущего выбранного счета или всех счетов."""
        from services.sync_service import SyncService
        acc_id = self.selected_account_id
        if acc_id is None:
            accounts = self.db.get_accounts()
            tot = 0
            for a in accounts:
                res = SyncService.sync_account(a.id, self.db)
                tot += res.get("new_trades", 0)
            msg = f"Синхронизация завершена: импортировано {tot} новых сделок (0 дубликатов)"
        else:
            res = SyncService.sync_account(acc_id, self.db)
            msg = res.get("message", "Синхронизация завершена")

        self.dashboard_view.refresh(account_id=self.selected_account_id)
        self.journal_view.refresh(account_id=self.selected_account_id)
        self._update_db_status()
        if self.page:
            sb = ft.SnackBar(
                content=ft.Text(msg, color="#FFFFFF", size=13),
                bgcolor=SURFACE_2,
                duration=4000,
            )
            self.page.overlay.append(sb)
            sb.open = True
            self.page.update()

    def _populate_account_options(self) -> None:
        """Заполняет опции выпадающего списка счетов."""
        accounts = self.db.get_accounts()
        options = [ft.dropdown.Option("-1", "Все торговые счета (Портфель)")]
        for acc in accounts:
            label = acc.name
            btype = (acc.exchange_type or "").upper()
            if btype == "BINANCE" and not label.startswith("[Binance]"):
                label = f"[Binance] {label}"
            elif btype == "BYBIT" and not label.startswith("[Bybit]"):
                label = f"[Bybit] {label}"
            elif btype == "MT5" and not label.startswith("[MT5]"):
                label = f"[MT5] {label}"
            options.append(ft.dropdown.Option(str(acc.id), label))

        self.account_dropdown.options = options
        if self.selected_account_id is None:
            self.account_dropdown.value = "-1"
        else:
            self.account_dropdown.value = str(self.selected_account_id)

    def _on_account_dropdown_changed(self, e: ft.ControlEvent) -> None:
        """Реактивная фильтрация всех экранов при смене активного счета."""
        val = e.control.value
        if val == "-1" or val is None:
            self.selected_account_id = None
        else:
            self.selected_account_id = int(val)

        # Мгновенная фильтрация дашборда и журнала
        self.dashboard_view.refresh(account_id=self.selected_account_id)
        self.journal_view.refresh(account_id=self.selected_account_id)
        self._update_db_status()
        self.page.update()

    def _on_accounts_updated(self) -> None:
        """Вызывается после добавления счета или синхронизации сделок."""
        self._populate_account_options()
        self.dashboard_view.refresh(account_id=self.selected_account_id)
        self.journal_view.refresh(account_id=self.selected_account_id)
        self._update_db_status()
        self.page.update()

    def _on_calendar_date_selected(self, target_date: date) -> None:
        """Переход из PnL Календаря в Журнал с фильтрацией по выбранному дню."""
        self.switch_to_view(1)
        self.journal_view.filter_by_exact_date(target_date)
        if self.page:
            self.page.update()

    def _build_navigation_rail(self) -> ft.NavigationRail:
        # Логотип и брендинг терминала
        self.logo_icon = ft.Container(
            content=ft.Icon(ft.Icons.CANDLESTICK_CHART_ROUNDED, color=ACCENT_PRIMARY, size=20),
            padding=8,
            bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
            border_radius=RADIUS_MD,
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, ACCENT_PRIMARY)),
        )

        self.logo_text_col = ft.Column(
            controls=[
                ft.Row(
                    [
                        ft.Text("TRADING", size=13, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                        ft.Container(
                            content=ft.Text("PRO", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                            bgcolor=ft.Colors.with_opacity(0.15, ACCENT_PRIMARY),
                            padding=ft.padding.symmetric(horizontal=5, vertical=1),
                            border_radius=4,
                            border=ft.border.all(1, ft.Colors.with_opacity(0.3, ACCENT_PRIMARY)),
                        ),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text("TERMINAL EDITION", size=9, color=TEXT_MUTED, font_family=FONT_MONO, weight=ft.FontWeight.W_500),
            ],
            spacing=2,
        )

        self.brand_row = ft.Row(
            controls=[
                self.logo_icon,
                self.logo_text_col,
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # Акцентная кнопка добавления новой сделки
        self.add_trade_text = ft.Text("Новая сделка", size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY)
        self.add_trade_btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.ADD_ROUNDED, size=18, color=TEXT_PRIMARY),
                    self.add_trade_text,
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8,
            ),
            bgcolor=ACCENT_PRIMARY,
            padding=ft.padding.symmetric(horizontal=12, vertical=11),
            border_radius=RADIUS_MD,
            shadow=create_neon_box_shadow(ACCENT_PRIMARY, blur=14, opacity=0.25),
            ink=True,
            on_click=lambda _: self.open_add_trade_modal(),
            tooltip="Зафиксировать новую сделку в журнале (Ctrl+K -> N)",
            width=192,
        )

        # Верхний блок брендинга и кнопки
        leading_block = ft.Container(
            content=ft.Column(
                controls=[
                    self.brand_row,
                    ft.Container(height=10),
                    self.add_trade_btn,
                    ft.Container(height=6),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.START,
                spacing=4,
            ),
            padding=ft.padding.only(top=16, bottom=12, left=12, right=12),
        )

        # Нижний блок сайдбара: переключатель ширины и инфо версии
        self.collapse_btn = ft.IconButton(
            icon=ft.Icons.KEYBOARD_DOUBLE_ARROW_LEFT_ROUNDED,
            icon_color=TEXT_MUTED,
            icon_size=18,
            tooltip="Свернуть / Развернуть меню",
            on_click=self._toggle_rail_extended,
        )

        self.version_info = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.TERMINAL_ROUNDED, size=13, color=TEXT_MUTED),
                    ft.Text("v2.4 • PRO", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                ],
                spacing=6,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            padding=ft.padding.only(bottom=10),
        )

        trailing_block = ft.Container(
            content=ft.Column(
                controls=[
                    self.collapse_btn,
                    self.version_info,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            padding=ft.padding.only(bottom=12),
        )

        return ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=68,
            min_extended_width=220,
            extended=True,
            leading=leading_block,
            trailing=trailing_block,
            bgcolor=SURFACE_1,
            indicator_color=ft.Colors.with_opacity(0.18, ACCENT_PRIMARY),
            indicator_shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
            selected_label_text_style=ft.TextStyle(font_family=FONT_FAMILY, size=12, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY),
            unselected_label_text_style=ft.TextStyle(font_family=FONT_FAMILY, size=12, weight=ft.FontWeight.W_500, color=TEXT_MUTED),
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.Icons.DASHBOARD_OUTLINED,
                    selected_icon=ft.Icons.DASHBOARD_ROUNDED,
                    label="Дашборд",
                    padding=ft.padding.symmetric(vertical=6),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.TABLE_CHART_OUTLINED,
                    selected_icon=ft.Icons.TABLE_CHART_ROUNDED,
                    label="Журнал",
                    padding=ft.padding.symmetric(vertical=6),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.PLAY_CIRCLE_OUTLINE_ROUNDED,
                    selected_icon=ft.Icons.PLAY_CIRCLE_FILLED_ROUNDED,
                    label="Бэктест",
                    padding=ft.padding.symmetric(vertical=6),
                ),
            ],
            on_change=self._on_nav_change,
        )

    def _toggle_rail_extended(self, e: ft.ControlEvent) -> None:
        """Переключение между развернутым и компактным режимом NavigationRail."""
        new_extended = not self.nav_rail.extended
        self.nav_rail.extended = new_extended
        self.collapse_btn.icon = ft.Icons.KEYBOARD_DOUBLE_ARROW_LEFT_ROUNDED if new_extended else ft.Icons.KEYBOARD_DOUBLE_ARROW_RIGHT_ROUNDED
        self.logo_text_col.visible = new_extended
        self.add_trade_text.visible = new_extended
        self.add_trade_btn.width = 192 if new_extended else 44
        self.version_info.visible = new_extended
        self.nav_rail.update()

    def _update_db_status(self) -> None:
        """Обновляет индикатор количества сделок в базе SQLite с учетом выбранного аккаунта."""
        try:
            trades = self.db.get_trades(account_id=self.selected_account_id)
            acc_str = f" • Счет #{self.selected_account_id}" if self.selected_account_id else " • Все счета"
            self.db_status_text.value = f"SQLite ({len(trades)} сделок{acc_str})"
        except Exception:
            self.db_status_text.value = "SQLite Connected"
        try:
            self.db_status_text.update()
        except Exception:
            pass

    def _on_nav_change(self, e: ft.ControlEvent) -> None:
        """Переключение экранов через NavigationRail."""
        idx = e.control.selected_index
        self.switch_to_view(idx)

    def switch_to_view(self, index: int) -> None:
        """Переключение на указанный экран с вызовом refresh()."""
        self.current_index = index
        self.nav_rail.selected_index = index

        target_view = self.views[index]
        if hasattr(target_view, "refresh"):
            if target_view in (self.dashboard_view, self.journal_view):
                target_view.refresh(account_id=self.selected_account_id)
            else:
                target_view.refresh()

        self.content_area.content = target_view
        self.content_container.content = target_view
        if self.page:
            self.page.update()

    def open_add_trade_modal(self) -> None:
        """Открытие модального окна добавления новой сделки."""
        self.trade_modal.open_for_create()
        try:
            self.page.open(self.trade_modal)
        except Exception:
            self.page.dialog = self.trade_modal
            self.trade_modal.open = True
            self.page.update()

    def open_edit_trade_modal(self, trade: Trade) -> None:
        """Открытие модального окна редактирования выбранной сделки."""
        self.trade_modal.open_for_edit(trade)
        try:
            self.page.open(self.trade_modal)
        except Exception:
            self.page.dialog = self.trade_modal
            self.trade_modal.open = True
            self.page.update()

    def open_account_modal(self) -> None:
        """Открытие модального окна управления торговыми счетами."""
        self.account_modal.open_modal()
        try:
            self.page.open(self.account_modal)
        except Exception:
            self.page.dialog = self.account_modal
            self.account_modal.open = True
            self.page.update()

    def handle_command_bar_action(self, action_code: str) -> None:
        """Обработка команд из Command Palette (Ctrl+K)."""
        if action_code == "new_trade":
            self.open_add_trade_modal()

        elif action_code == "open_ai_coach":
            self.switch_to_view(0)
            self.dashboard_view._open_ai_coach_modal()

        elif action_code == "manage_accounts":
            self.open_account_modal()

        elif action_code == "open_journal":
            self.switch_to_view(1)

        elif action_code == "open_backtest":
            self.switch_to_view(2)

        elif action_code.startswith("trade_"):
            try:
                t_id = int(action_code.split("_")[1])
                self.switch_to_view(1)
                t_obj = self.db.get_trade_by_id(t_id)
                if t_obj:
                    self.journal_view.open_inspector(t_obj)
            except Exception:
                pass

        elif action_code.startswith("strategy_"):
            tag = action_code[len("strategy_"):]
            self.switch_to_view(1)
            self.journal_view.search_field.value = tag
            self.journal_view.refresh()
            try:
                sb = ft.SnackBar(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.FILTER_LIST_ROUNDED, color="#F59E0B", size=18),
                            ft.Text(f"Журнал отфильтрован по стратегии: '{tag}'", color=TEXT_PRIMARY, size=13),
                        ],
                        spacing=8,
                    ),
                    bgcolor=SURFACE_1,
                    duration=3000,
                )
                self.page.overlay.append(sb)
                sb.open = True
                self.page.update()
            except Exception:
                pass

        elif action_code == "toggle_tilt":
            new_val = not self.dashboard_view.tilt_switch.value
            self.dashboard_view.tilt_switch.value = new_val
            self.dashboard_view._on_tilt_toggle(None)
            self.switch_to_view(0)

        elif action_code == "export_csv":
            trades = self.db.get_all_trades()
            export_path = Path("data") / "trades_export.csv"
            out_file = AnalyticsService.export_trades_to_csv(trades, str(export_path))
            try:
                sb = ft.SnackBar(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.DOWNLOAD_DONE_ROUNDED, color=PROFIT, size=18),
                            ft.Text(f"Успешно экспортировано {len(trades)} сделок в {out_file}", color=TEXT_PRIMARY, size=13),
                        ],
                        spacing=8,
                    ),
                    bgcolor=SURFACE_1,
                    duration=3000,
                )
                self.page.overlay.append(sb)
                sb.open = True
                self.page.update()
            except Exception:
                pass

        elif action_code == "import_csv":
            self.switch_to_view(1)
            self.journal_view.csv_import_picker.pick_files(
                allowed_extensions=["csv"],
                dialog_title="Выберите CSV-файл со сделками",
            )

        elif action_code == "open_plotly":
            self.on_open_plotly()

        elif action_code == "reseed_demo":
            self.db.clear_all_trades()
            self.db.seed_demo_data_if_empty()
            self._on_trade_data_changed()
            try:
                sb = ft.SnackBar(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.REFRESH_ROUNDED, color="#22D3EE", size=18),
                            ft.Text("База сброшена и наполнена реалистичными сделками.", color=TEXT_PRIMARY, size=13),
                        ],
                        spacing=8,
                    ),
                    bgcolor=SURFACE_1,
                    duration=3000,
                )
                self.page.overlay.append(sb)
                sb.open = True
                self.page.update()
            except Exception:
                pass

    def _on_trade_data_changed(self) -> None:
        """Синхронное обновление всех экранов и счетчиков при изменении данных."""
        self.dashboard_view.refresh(account_id=self.selected_account_id)
        self.journal_view.refresh(account_id=self.selected_account_id)
        self._update_db_status()
        self.page.update()
