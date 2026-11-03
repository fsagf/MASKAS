"""
ui/views/journal.py
Экран журнала сделок Trading Journal Pro в терминальном стиле Dark Premium Terminal.
Включает:
- Высокоплотную таблицу micro-typography с моноширинными котировками (FONT_MONO).
- Dual-channel accessibility бейджи направления (▲ LONG / ▼ SHORT).
- Двунаправленный визуальный бар PnL и скелетоны загрузки.
- Выдвижной Slide-over Drawer инспектора сделки с эффектом затемнения, деревом ордеров Scale-In/Out
  и интерактивным подводным графиком MAE/MFE.
- Интерактивный свечной график TradingView Lightweight Charts в модальном оверлее.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import webbrowser
import flet as ft
import flet.canvas as cv

from analytics import AnalyticsService, MarketDataService
from database import DatabaseManager, Trade, TradeExecution
from services.chart_service import generate_trade_chart, get_tradingview_url
from ui.theme import (
    ACCENT_PRIMARY,
    ACCENT_SECONDARY,
    ANIM_FAST_MS,
    ANIM_NORMAL_MS,
    ANIMATIONS_ENABLED,
    BG_APP,
    BG_SURFACE,
    BORDER_COLOR,
    BORDER_HIGHLIGHT,
    BORDER_SUBTLE,
    FONT_FAMILY,
    FONT_MONO,
    LOSS,
    LOSS_DARK,
    PROFIT,
    PROFIT_DARK,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    SURFACE_1,
    SURFACE_2,
    SURFACE_3,
    SURFACE_OVERLAY,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING_TILT,
    create_neon_box_shadow,
    create_pnl_badge,
    create_strategy_badge,
    get_animation,
)

COL_WIDTH_TICKER = 190
COL_WIDTH_PRICES = 140
COL_WIDTH_META = 140
COL_WIDTH_PNL = 210
COL_WIDTH_ACTION = 40


def create_dynamic_pnl_bar(pnl: float, max_abs_pnl: float) -> ft.Container:
    """
    Создает двунаправленный градиентный бар PnL, масштабируемый относительно max_abs_pnl.
    """
    scale = max(max_abs_pnl, 50.0)
    ratio = min(abs(pnl) / scale, 1.0)
    bar_width = max(ratio * 46.0, 4.0)

    is_win = pnl >= 0

    if is_win:
        content = ft.Row(
            controls=[
                ft.Container(width=46),
                ft.Container(width=2, height=12, bgcolor=BORDER_SUBTLE),
                ft.Container(
                    width=bar_width,
                    height=8,
                    gradient=ft.LinearGradient(
                        begin=ft.alignment.center_left,
                        end=ft.alignment.center_right,
                        colors=[PROFIT, PROFIT_DARK],
                    ),
                    border_radius=ft.border_radius.only(top_right=4, bottom_right=4),
                    shadow=create_neon_box_shadow(PROFIT, blur=6, opacity=0.25),
                ),
            ],
            spacing=0,
            alignment=ft.MainAxisAlignment.START,
        )
    else:
        left_empty = max(46.0 - bar_width, 0.0)
        content = ft.Row(
            controls=[
                ft.Container(width=left_empty),
                ft.Container(
                    width=bar_width,
                    height=8,
                    gradient=ft.LinearGradient(
                        begin=ft.alignment.center_left,
                        end=ft.alignment.center_right,
                        colors=[LOSS_DARK, LOSS],
                    ),
                    border_radius=ft.border_radius.only(top_left=4, bottom_left=4),
                    shadow=create_neon_box_shadow(LOSS, blur=6, opacity=0.25),
                ),
                ft.Container(width=2, height=12, bgcolor=BORDER_SUBTLE),
                ft.Container(width=46),
            ],
            spacing=0,
            alignment=ft.MainAxisAlignment.START,
        )

    return ft.Container(
        content=content,
        width=100,
        alignment=ft.alignment.center,
    )


class JournalView(ft.Container):
    """
    Экран 'Журнал операций' с чипсами фильтрации, деревом ордеров и инспектором.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        on_trade_deleted: Optional[Callable[[], None]] = None,
        on_edit_requested: Optional[Callable[[Trade], None]] = None,
        page: Optional[ft.Page] = None,
    ):
        super().__init__(expand=True, bgcolor=BG_APP)
        self.db = db_manager
        self.on_trade_deleted = on_trade_deleted
        self.on_edit_requested = on_edit_requested
        self._page_ref = page
        self.selected_trade: Optional[Trade] = None

        # Фильтры
        self.current_account_id: Optional[int] = None
        self.custom_date_filter: Optional[datetime.date] = None
        self.filter_period = "all"      # all, month, week, today, custom
        self.filter_result = "all"      # all, win, loss, tilt

        # FilePickers
        self.screenshot_picker = ft.FilePicker(on_result=self._on_screenshot_picked)
        self.csv_import_picker = ft.FilePicker(on_result=self._on_csv_import_selected)

        # Поле поиска в терминальном стиле
        self.search_field = ft.TextField(
            hint_text="Поиск по тикеру, стратегии, направлению или заметкам...",
            hint_style=ft.TextStyle(font_family=FONT_FAMILY, size=12, color=TEXT_MUTED),
            prefix_icon=ft.Icons.SEARCH_ROUNDED,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            bgcolor=SURFACE_1,
            color=TEXT_PRIMARY,
            border_radius=RADIUS_MD,
            dense=True,
            height=38,
            text_size=12,
            on_change=lambda _: self.refresh(),
            expand=True,
        )

        self.trades_listview = ft.ListView(
            expand=True,
            spacing=6,
            padding=ft.padding.only(right=6, bottom=16),
            )

        self.chips_container = ft.Container()
        self.inspector_panel = self._build_inspector_panel()
        self.content = self._build_layout()
        self.refresh()

    @property
    def host_page(self) -> Optional[ft.Page]:
        try:
            return self.page or self._page_ref
        except Exception:
            return self._page_ref

    def _build_layout(self) -> ft.Control:
        # Верхняя панель поиска и экспорта/импорта
        top_row = ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text("Журнал операций", size=22, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                        ft.Text("Дерево ордеров Scale-In/Out, риск-инспектор и экспорт данных", size=12, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                    ],
                    spacing=2,
                ),
                ft.Row(
                    controls=[
                        ft.Container(content=self.search_field, width=340),
                        ft.Container(
                            content=ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, size=15, color=PROFIT),
                                    ft.Text("Экспорт CSV", size=11, color=TEXT_PRIMARY, weight=ft.FontWeight.W_600, font_family=FONT_FAMILY),
                                ],
                                spacing=6,
                                tight=True,
                            ),
                            bgcolor=SURFACE_2,
                            
                            border_radius=RADIUS_MD,
                            padding=ft.padding.symmetric(horizontal=12, vertical=8),
                            ink=True,
                            tooltip="Выгрузить базу сделок в CSV",
                            on_click=lambda _: self._export_csv(),
                        ),
                        ft.Container(
                            content=ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.UPLOAD_FILE_ROUNDED, size=15, color=ACCENT_PRIMARY),
                                    ft.Text("Импорт CSV", size=11, color=TEXT_PRIMARY, weight=ft.FontWeight.W_600, font_family=FONT_FAMILY),
                                ],
                                spacing=6,
                                tight=True,
                            ),
                            bgcolor=SURFACE_2,
                            
                            border_radius=RADIUS_MD,
                            padding=ft.padding.symmetric(horizontal=12, vertical=8),
                            ink=True,
                            tooltip="Загрузить выписку Binance / Bybit / MT5",
                            on_click=lambda _: self.csv_import_picker.pick_files(allowed_extensions=["csv"]),
                        ),
                    ],
                    spacing=8,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # Панель быстрых чипсов фильтрации
        self.chips_container.content = self._build_chips_row()

        table_header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Text("ИНСТРУМЕНТ / СТРАТЕГИЯ", size=10, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO),
                        width=COL_WIDTH_TICKER,
                    ),
                    ft.Container(
                        content=ft.Text("ВХОД / ВЫХОД (VWAP)", size=10, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO),
                        width=COL_WIDTH_PRICES,
                    ),
                    ft.Container(
                        content=ft.Text("ОБЪЕМ / ВРЕМЯ", size=10, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO),
                        width=COL_WIDTH_META,
                    ),
                    ft.Container(
                        content=ft.Text("ФИНАНСОВЫЙ РЕЗУЛЬТАТ (PnL)", size=10, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO),
                        width=COL_WIDTH_PNL,
                    ),
                    ft.Container(
                        content=ft.Text("", size=10),
                        width=COL_WIDTH_ACTION,
                    ),
                ],
                alignment=ft.MainAxisAlignment.START,
                spacing=12,
            ),
            padding=ft.padding.symmetric(horizontal=16, vertical=8),
            bgcolor=SURFACE_1,
            border_radius=RADIUS_MD,
            
        )

        self.workspace = ft.Stack(
            controls=[
                ft.Column(
                    controls=[
                        self.chips_container,
                        table_header,
                        self.trades_listview,
                    ],
                    spacing=6,
                    expand=True,
                ),
                self.inspector_panel,
            ],
            expand=True,
        )

        return ft.Column(
            controls=[
                self.screenshot_picker,
                self.csv_import_picker,
                top_row,
                ft.Divider(color=BORDER_SUBTLE, height=10),
                self.workspace,
            ],
            spacing=8,
            expand=True,
        )

    def _build_skeleton_rows(self, count: int = 6) -> List[ft.Control]:
        """Генерирует строки-скелетоны для плавной индикации загрузки списка сделок."""
        rows = []
        for _ in range(count):
            row = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Container(width=160, height=18, border_radius=4, bgcolor=SURFACE_2),
                        ft.Container(width=120, height=18, border_radius=4, bgcolor=SURFACE_3),
                        ft.Container(width=110, height=18, border_radius=4, bgcolor=SURFACE_3),
                        ft.Container(width=180, height=18, border_radius=4, bgcolor=SURFACE_2),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                bgcolor=SURFACE_1,
                border_radius=RADIUS_MD,
                
            )
            rows.append(row)
        return rows

    def filter_by_exact_date(self, target_date) -> None:
        """Устанавливает фильтрацию по точной дате (из PnL Календаря)."""
        self.custom_date_filter = target_date
        self.filter_period = "custom"
        self.chips_container.content = self._build_chips_row()
        if self.chips_container.page:
            self.chips_container.update()
        self.refresh()
        if self.page:
            self.page.update()

    def _clear_custom_date(self) -> None:
        """Сбрасывает фильтрацию по точной дате."""
        self.custom_date_filter = None
        self.filter_period = "all"
        self.chips_container.content = self._build_chips_row()
        if self.chips_container.page:
            self.chips_container.update()
        self.refresh()
        if self.page:
            self.page.update()

    def _build_chips_row(self) -> ft.Control:
        """Динамическая генерация строки чипсов фильтрации с подсветкой активного выбора."""
        period_controls = [
            ft.Text("Период:", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
            self._create_filter_chip("Все время", "all", is_period=True),
            self._create_filter_chip("Месяц", "month", is_period=True),
            self._create_filter_chip("Неделя", "week", is_period=True),
            self._create_filter_chip("Сегодня", "today", is_period=True),
        ]

        # Добавляем чипс конкретной даты из календаря, если выбран
        if self.custom_date_filter and self.filter_period == "custom":
            dt_label = self.custom_date_filter.strftime("%d.%m.%Y")
            custom_chip = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.CALENDAR_MONTH, size=11, color=ACCENT_SECONDARY),
                        ft.Text(f"{dt_label} ✕", size=11, color=ACCENT_SECONDARY, weight=ft.FontWeight.BOLD, font_family=FONT_MONO),
                    ],
                    spacing=4,
                ),
                bgcolor=ft.Colors.with_opacity(0.14, ACCENT_SECONDARY),
                border=ft.border.all(1, ACCENT_SECONDARY),
                border_radius=RADIUS_SM,
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                ink=True,
                tooltip="Сбросить фильтр даты",
                on_click=lambda _: self._clear_custom_date(),
            )
            period_controls.append(custom_chip)

        return ft.Row(
            controls=[
                ft.Row(controls=period_controls, spacing=4),
                ft.VerticalDivider(width=1, color=BORDER_SUBTLE),
                ft.Row(
                    controls=[
                        ft.Text("Результат:", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                        self._create_filter_chip("Все", "all", is_period=False),
                        self._create_filter_chip("Прибыльные", "win", is_period=False),
                        self._create_filter_chip("Убыточные", "loss", is_period=False),
                        self._create_filter_chip("Тильт", "tilt", is_period=False),
                    ],
                    spacing=4,
                ),
            ],
            spacing=10,
        )

    def _create_filter_chip(self, label: str, val: str, is_period: bool = True) -> ft.Container:
        """Создает кликабельный фильтр-чипс с подсветкой активного состояния."""
        is_active = (self.filter_period == val) if is_period else (self.filter_result == val)
        bg = ft.Colors.with_opacity(0.16, ACCENT_PRIMARY) if is_active else SURFACE_1
        border_c = ACCENT_PRIMARY if is_active else BORDER_SUBTLE
        txt_c = ACCENT_PRIMARY if is_active else TEXT_SECONDARY

        if val == "tilt" and is_active:
            bg = ft.Colors.with_opacity(0.16, WARNING_TILT)
            border_c = WARNING_TILT
            txt_c = WARNING_TILT

        def on_click(_):
            if is_period:
                self.filter_period = val
            else:
                self.filter_result = val
            self.chips_container.content = self._build_chips_row()
            if self.chips_container.page:
                self.chips_container.update()
            self.refresh()

        return ft.Container(
            content=ft.Text(label, size=11, color=txt_c, weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL, font_family=FONT_FAMILY),
            bgcolor=bg,
            border=ft.border.all(1, border_c),
            border_radius=RADIUS_SM,
            padding=ft.padding.symmetric(horizontal=8, vertical=3),
            ink=True,
            on_click=on_click,
        )

    def _build_inspector_panel(self) -> ft.Container:
        """Создает выдвижную правую панель инспектора сделки (Slide-over Drawer)."""
        self.inspector_content = ft.Column(
            controls=[],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        return ft.Container(
            content=self.inspector_content,
            width=420,
            right=0,
            top=0,
            bottom=0,
            bgcolor=SURFACE_OVERLAY,
            border_radius=ft.border_radius.only(top_left=RADIUS_LG, bottom_left=RADIUS_LG),
            border=ft.border.all(1.2, BORDER_SUBTLE),
            shadow=create_neon_box_shadow(ACCENT_PRIMARY, blur=24, opacity=0.25),
            padding=16,
            visible=False,
            animate=get_animation(ANIM_NORMAL_MS) if ANIMATIONS_ENABLED else None,
        )

    def _build_mini_candlestick_chart(self, trade: Trade) -> ft.Container:
        """
        Встроенный свечной мини-терминал (BrokerView Candlestick Execution Chart):
        Отображает 20 свечей ДО входа, период удержания сделки и 15 свечей ПОСЛЕ выхода,
        маркеры входа (ENTRY) и выхода (EXIT), а также уровни SL, TP и VWAP.
        """
        from services.chart_service import get_binance_symbol, fetch_binance_candles, generate_synthetic_candles

        t_open = trade.opened_at or (datetime.now() - timedelta(hours=2))
        t_close = trade.closed_at or datetime.now()
        start_t = t_open - timedelta(minutes=20 * 15)  # 20 свечей по 15м
        end_t = t_close + timedelta(minutes=15 * 15)   # 15 свечей по 15м

        candles = None
        bsym = get_binance_symbol(trade.ticker)
        if bsym:
            candles = fetch_binance_candles(bsym, start_t, end_t, interval="15m")
        if not candles:
            candles = generate_synthetic_candles(trade, start_t, end_t, interval_minutes=15)

        if not candles or len(candles) < 5:
            return ft.Container(
                content=ft.Text("Нет данных для отображения свечей", color=TEXT_MUTED, size=11, font_family=FONT_MONO),
                alignment=ft.alignment.center,
                height=50,
                border=ft.border.all(1, BORDER_SUBTLE),
                border_radius=RADIUS_MD,
                padding=8,
            )

        # Окно свечей для компактного инспектора (370px)
        window = candles[-40:] if len(candles) > 40 else candles
        lows = [c["low"] for c in window]
        highs = [c["high"] for c in window]
        if trade.stop_loss and trade.stop_loss > 0:
            lows.append(trade.stop_loss)
            highs.append(trade.stop_loss)
        if trade.take_profit and trade.take_profit > 0:
            lows.append(trade.take_profit)
            highs.append(trade.take_profit)

        min_p = min(lows)
        max_p = max(highs)
        p_range = max(max_p - min_p, 0.0001)

        canvas_h = 130
        canvas_w = 370
        top_pad = 12
        bottom_pad = 16
        left_pad = 8
        right_pad = 42
        plot_w = canvas_w - left_pad - right_pad
        plot_h = canvas_h - top_pad - bottom_pad

        shapes = []
        n_candles = len(window)
        candle_step = plot_w / max(n_candles, 1)
        body_w = max(candle_step * 0.65, 2.0)

        entry_ts = int(t_open.timestamp())
        exit_ts = int(t_close.timestamp())
        closest_entry_idx = 0
        closest_exit_idx = n_candles - 1
        min_entry_diff = float("inf")
        min_exit_diff = float("inf")

        is_long = (trade.direction or "LONG").upper() == "LONG"

        for idx, c in enumerate(window):
            c_time = c["time"]
            if abs(c_time - entry_ts) < min_entry_diff:
                min_entry_diff = abs(c_time - entry_ts)
                closest_entry_idx = idx
            if abs(c_time - exit_ts) < min_exit_diff:
                min_exit_diff = abs(c_time - exit_ts)
                closest_exit_idx = idx

            xc = left_pad + idx * candle_step + (candle_step / 2)
            y_high = top_pad + (max_p - c["high"]) / p_range * plot_h
            y_low = top_pad + (max_p - c["low"]) / p_range * plot_h
            y_open = top_pad + (max_p - c["open"]) / p_range * plot_h
            y_close = top_pad + (max_p - c["close"]) / p_range * plot_h

            is_green = c["close"] >= c["open"]
            col = "#10B981" if is_green else "#EF4444"

            # Фитиль
            shapes.append(
                cv.Line(xc, y_high, xc, y_low, paint=ft.Paint(color=col, stroke_width=1.0))
            )
            # Тело свечи
            shapes.append(
                cv.Rect(xc - body_w / 2, min(y_open, y_close), body_w, max(abs(y_close - y_open), 1.5), paint=ft.Paint(color=col, style=ft.PaintingStyle.FILL))
            )

        def price_to_y(p: float) -> float:
            return top_pad + (max_p - p) / p_range * plot_h

        # Entry VWAP (синий пунктир)
        entry_y = price_to_y(trade.entry_price)
        shapes.append(
            cv.Line(left_pad, entry_y, left_pad + plot_w, entry_y, paint=ft.Paint(color="#38BDF8", stroke_width=1.0, stroke_dash_pattern=[4, 3], style=ft.PaintingStyle.STROKE))
        )

        # Stop-Loss (красный пунктир)
        if trade.stop_loss and trade.stop_loss > 0:
            sl_y = price_to_y(trade.stop_loss)
            shapes.append(
                cv.Line(left_pad, sl_y, left_pad + plot_w, sl_y, paint=ft.Paint(color="#EF4444", stroke_width=1.0, stroke_dash_pattern=[4, 3], style=ft.PaintingStyle.STROKE))
            )

        # Take-Profit (зеленый пунктир)
        if trade.take_profit and trade.take_profit > 0:
            tp_y = price_to_y(trade.take_profit)
            shapes.append(
                cv.Line(left_pad, tp_y, left_pad + plot_w, tp_y, paint=ft.Paint(color="#10B981", stroke_width=1.0, stroke_dash_pattern=[4, 3], style=ft.PaintingStyle.STROKE))
            )

        # Маркер входа (ENTRY)
        ent_xc = left_pad + closest_entry_idx * candle_step + (candle_step / 2)
        ent_yc = price_to_y(trade.entry_price)
        ent_col = "#10B981" if is_long else "#EF4444"
        shapes.append(
            cv.Circle(ent_xc, ent_yc, 3.5, paint=ft.Paint(color=ent_col, style=ft.PaintingStyle.FILL))
        )
        shapes.append(
            cv.Text(
                x=max(ent_xc - 22, left_pad),
                y=min(ent_yc + 4, canvas_h - 14),
                text=f"BUY @ ${trade.entry_price:,.0f}" if is_long else f"SELL @ ${trade.entry_price:,.0f}",
                style=ft.TextStyle(size=8, weight=ft.FontWeight.BOLD, color=ent_col, font_family=FONT_MONO),
            )
        )

        # Маркер выхода (EXIT)
        ext_xc = left_pad + closest_exit_idx * candle_step + (candle_step / 2)
        ext_yc = price_to_y(trade.exit_price)
        ext_col = "#10B981" if trade.net_pnl >= 0 else "#EF4444"
        shapes.append(
            cv.Circle(ext_xc, ext_yc, 3.5, paint=ft.Paint(color=ext_col, style=ft.PaintingStyle.FILL))
        )
        r_str = f"({trade.r_multiple:+.1f}R)" if getattr(trade, 'r_multiple', None) else ""
        shapes.append(
            cv.Text(
                x=max(ext_xc - 28, left_pad),
                y=max(ext_yc - 12, 2),
                text=f"EXIT @ ${trade.exit_price:,.0f} {r_str}",
                style=ft.TextStyle(size=8, weight=ft.FontWeight.BOLD, color=ext_col, font_family=FONT_MONO),
            )
        )

        canvas = cv.Canvas(
            shapes=shapes,
            width=canvas_w,
            height=canvas_h,
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.CANDLESTICK_CHART_ROUNDED, size=14, color=ACCENT_PRIMARY),
                                    ft.Text("BrokerView — Свечной график сделки", size=11, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                ],
                                spacing=5,
                            ),
                            ft.Container(
                                content=ft.Text("20 ДО • HOLD • 15 ПОСЛЕ", size=8, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                                padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                border_radius=4,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    canvas,
                ],
                spacing=4,
            ),
            padding=8,
            bgcolor=SURFACE_2,
            border_radius=RADIUS_MD,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_orders_tree(self, trade: Trade) -> ft.Container:
        """
        Блок 'Жизненный цикл позиции (Scale-In / Scale-Out)':
        визуальный таймлайн ордеров с ценами, объемами, комиссиями и пересчетом VWAP.
        """
        rows = []
        execs = trade.executions or []

        # Если ордеров еще нет в базе, генерируем визуальный таймлайн на основе входа и выхода
        if not execs:
            t_open = trade.opened_at or (datetime.now() - timedelta(hours=2))
            t_close = trade.closed_at or datetime.now()
            t_add = t_open + timedelta(minutes=20)

            sim_execs = [
                ("ENTRY", "Вход", trade.entry_price, round(trade.volume * 0.6, 3), round(trade.commission * 0.6, 2), t_open),
                ("ADD", "Добор", trade.entry_price, round(trade.volume * 0.4, 3), round(trade.commission * 0.4, 2), t_add),
                ("EXIT", "Закрытие", trade.exit_price, round(trade.volume, 3), 0.0, t_close),
            ]
            for act, label, pr, vl, fe, dt in sim_execs:
                is_entry = act in ["ENTRY", "ADD"]
                act_col = PROFIT if act == "ENTRY" else (ACCENT_SECONDARY if act == "ADD" else ACCENT_PRIMARY)
                icon_sym = "🟢" if act in ["ENTRY", "ADD"] else "🏁"

                rows.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(dt.strftime("%H:%M"), size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                                ft.Row(
                                    [
                                        ft.Text(icon_sym, size=10),
                                        ft.Text(f"{act} ({label})", size=10, weight=ft.FontWeight.BOLD, color=act_col, font_family=FONT_MONO),
                                    ],
                                    spacing=4,
                                ),
                                ft.Text(f"{vl:g} {trade.ticker.split('/')[0]}", size=10, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                ft.Text(f"@ ${pr:,.2f}", size=10, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                ft.Text(f"Fee: ${fe:.2f}", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        padding=ft.padding.symmetric(horizontal=8, vertical=4),
                        bgcolor=SURFACE_1,
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, ft.Colors.with_opacity(0.15, act_col)),
                    )
                )
        else:
            for ex in execs:
                is_entry = (ex.action or "ENTRY").upper() in ["ENTRY", "ADD"]
                act_col = ACCENT_SECONDARY if ex.action == "ADD" else (PROFIT if is_entry else ACCENT_PRIMARY)
                icon_data = ft.Icons.ARROW_FORWARD_ROUNDED if is_entry else (ft.Icons.PIE_CHART_ROUNDED if ex.action == "PARTIAL_TP" else ft.Icons.FLAG_ROUNDED)

                rows.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(ex.executed_at.strftime("%H:%M"), size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                                ft.Row(
                                    [
                                        ft.Icon(icon_data, size=12, color=act_col),
                                        ft.Text(ex.action, size=10, weight=ft.FontWeight.BOLD, color=act_col, font_family=FONT_MONO),
                                    ],
                                    spacing=4,
                                ),
                                ft.Text(f"{ex.volume:g} шт", size=10, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                ft.Text(f"@ ${ex.price:,.2f}", size=10, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                ft.Text(f"Fee: ${ex.fee:.2f}", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        padding=ft.padding.symmetric(horizontal=8, vertical=4),
                        bgcolor=SURFACE_1,
                        border_radius=RADIUS_SM,
                    )
                )

        # Форма быстрого добавления частичного ордера (Scale-In / Scale-Out)
        action_dropdown = ft.Dropdown(
            options=[
                ft.dropdown.Option("ADD", "ADD (Добор)"),
                ft.dropdown.Option("PARTIAL_TP", "PARTIAL TP (Част.)"),
                ft.dropdown.Option("EXIT", "EXIT (Закрытие)"),
            ],
            value="ADD",
            dense=True,
            text_size=11,
            width=120,
            border_color=BORDER_SUBTLE,
            bgcolor=SURFACE_2,
        )
        price_in = ft.TextField(hint_text="Цена", dense=True, height=32, text_size=11, text_style=ft.TextStyle(font_family=FONT_MONO), width=75, border_color=BORDER_SUBTLE, bgcolor=SURFACE_2)
        vol_in = ft.TextField(hint_text="Объем", dense=True, height=32, text_size=11, text_style=ft.TextStyle(font_family=FONT_MONO), width=65, border_color=BORDER_SUBTLE, bgcolor=SURFACE_2)
        fee_in = ft.TextField(hint_text="Fee ($)", dense=True, height=32, text_size=11, text_style=ft.TextStyle(font_family=FONT_MONO), width=60, border_color=BORDER_SUBTLE, bgcolor=SURFACE_2, value="1.5")

        def add_exec_click(_):
            try:
                pr = float(price_in.value.replace(",", "."))
                vl = float(vol_in.value.replace(",", "."))
                fe = float((fee_in.value or "0").replace(",", "."))
                if pr > 0 and vl > 0:
                    self.db.add_execution(trade.id, action_dropdown.value, pr, vl, fe)
                    fresh_trade = self.db.get_trade_by_id(trade.id)
                    if fresh_trade:
                        self.open_inspector(fresh_trade)
                    if self.on_trade_deleted:
                        self.on_trade_deleted()
            except Exception:
                pass

        add_row = ft.Row(
            controls=[
                action_dropdown,
                price_in,
                vol_in,
                fee_in,
                ft.IconButton(
                    icon=ft.Icons.ADD_CIRCLE_ROUNDED,
                    icon_color=ACCENT_PRIMARY,
                    icon_size=20,
                    tooltip="Добавить ордер и пересчитать VWAP",
                    on_click=add_exec_click,
                ),
            ],
            spacing=4,
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.ACCOUNT_TREE_ROUNDED, size=14, color=ACCENT_SECONDARY),
                                    ft.Text("Дерево ордеров (Scale-In / Scale-Out)", size=11, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                ],
                                spacing=6,
                            ),
                            ft.Text(f"Ордеров: {max(len(execs), 3)}", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Column(controls=rows, spacing=4),
                    ft.Divider(color=BORDER_SUBTLE, height=8),
                    ft.Text("+ Добавить ордер (Добор / Частичный выход):", size=10, color=TEXT_MUTED),
                    add_row,
                ],
                spacing=6,
            ),
            padding=10,
            bgcolor=SURFACE_2,
            border_radius=RADIUS_MD,
        )

    def _render_inspector_content(self, trade: Trade) -> None:
        """Наполняет панель инспектора всеми данными выбранной сделки."""
        is_win = trade.net_pnl >= 0
        pnl_color = PROFIT if is_win else LOSS

        # Получение кривой движения цены (Binance API + Fallback)
        path_points = MarketDataService.generate_price_path(trade)
        chart_data_pts = []

        if path_points:
            min_y = min([p["pct"] for p in path_points])
            max_y = max([p["pct"] for p in path_points])
            span = max(max_y - min_y, 2.0)

            for idx, pt in enumerate(path_points):
                chart_data_pts.append(
                    ft.LineChartDataPoint(
                        idx,
                        pt["pct"],
                        tooltip=f"Time: {pt['time'].strftime('%H:%M')}\nPrice: {pt['price']:,.2f} USD\nChange: {pt['pct']:+.2f}%",
                        show_tooltip=True,
                    )
                )
        else:
            min_y, max_y, span = -2.0, 4.0, 6.0
            chart_data_pts = [ft.LineChartDataPoint(0, 0), ft.LineChartDataPoint(1, 1)]

        underwater_chart = ft.LineChart(
            data_series=[
                ft.LineChartData(
                    data_points=chart_data_pts,
                    stroke_width=2.5,
                    color=pnl_color,
                    curved=True,
                    stroke_cap_round=True,
                    below_line_gradient=ft.LinearGradient(
                        begin=ft.alignment.top_center,
                        end=ft.alignment.bottom_center,
                        colors=[ft.Colors.with_opacity(0.24, pnl_color), ft.Colors.with_opacity(0.0, pnl_color)],
                    ),
                )
            ],
            
            horizontal_grid_lines=ft.ChartGridLines(interval=span / 3, color=BORDER_SUBTLE, width=1, dash_pattern=[3, 3]),
            vertical_grid_lines=ft.ChartGridLines(width=0),
            left_axis=ft.ChartAxis(labels_size=34, labels_interval=span / 2),
            bottom_axis=ft.ChartAxis(visible=False),
            min_y=min_y - 0.4,
            max_y=max_y + 0.4,
            interactive=True,
            height=115,
        )

        # Расчет MAE / MFE в долларах
        mae_dollars = abs(trade.entry_price * (trade.mae_pct / 100.0) * trade.volume) if trade.mae_pct else 0.0
        mfe_dollars = abs(trade.entry_price * (trade.mfe_pct / 100.0) * trade.volume) if trade.mfe_pct else 0.0

        eff_warning = ft.Container()
        if trade.efficiency < 0.50 and is_win:
            eff_warning = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=14, color=WARNING_TILT),
                        ft.Text(
                            f"Ранний выход: вы оставили на столе >50% движения (КПД: {int(trade.efficiency * 100)}%)",
                            size=10,
                            weight=ft.FontWeight.BOLD,
                            color=WARNING_TILT,
                            font_family=FONT_FAMILY,
                        ),
                    ],
                    spacing=6,
                ),
                bgcolor=ft.Colors.with_opacity(0.12, WARNING_TILT),
                border=ft.border.all(1, ft.Colors.with_opacity(0.3, WARNING_TILT)),
                border_radius=RADIUS_SM,
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
            )

        underwater_card = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.WATERFALL_CHART_ROUNDED, size=15, color=ACCENT_SECONDARY),
                                    ft.Text("Подводный график (MAE / MFE)", size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                ],
                                spacing=6,
                            ),
                            ft.Container(
                                content=ft.Text(f"EFF: {int(trade.efficiency * 100)}%", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_SECONDARY, font_family=FONT_MONO),
                                bgcolor=ft.Colors.with_opacity(0.14, ACCENT_SECONDARY),
                                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                border_radius=4,
                                border=ft.border.all(1, ft.Colors.with_opacity(0.3, ACCENT_SECONDARY)),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    underwater_chart,
                    ft.Row(
                        controls=[
                            self._mini_stat("MAE (Drawdown)", f"-${mae_dollars:,.1f} (-{trade.mae_pct:.1f}%)", LOSS),
                            self._mini_stat("MFE (Peak)", f"+${mfe_dollars:,.1f} (+{trade.mfe_pct:.1f}%)", PROFIT),
                            self._mini_stat("R:R Ratio", f"{trade.r_multiple:+.2f}R", ACCENT_PRIMARY),
                        ],
                        spacing=6,
                    ),
                    eff_warning,
                ],
                spacing=6,
            ),
            padding=10,
            bgcolor=SURFACE_2,
            border_radius=RADIUS_MD,
        )

        # Блок тильта (если флаг активен)
        tilt_block = ft.Container()
        if trade.is_tilt:
            tilt_block = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.PSYCHOLOGY_ROUNDED, size=18, color=WARNING_TILT),
                        ft.Column(
                            controls=[
                                ft.Text("Сделка помечена как тильт", size=11, weight=ft.FontWeight.BOLD, color=WARNING_TILT, font_family=FONT_FAMILY),
                                ft.Text(trade.tilt_reason or "Нарушение торгового плана", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                            ],
                            spacing=1,
                            expand=True,
                        ),
                    ],
                    spacing=8,
                ),
                bgcolor=ft.Colors.with_opacity(0.14, WARNING_TILT),
                padding=8,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, ft.Colors.with_opacity(0.35, WARNING_TILT)),
            )

        # Превью скриншота (если прикреплен)
        screenshot_preview = ft.Container()
        if trade.screenshot_path and Path(trade.screenshot_path).exists():
            screenshot_preview = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.IMAGE_ROUNDED, size=14, color=PROFIT),
                                ft.Text("Скриншот сетапа", size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ],
                            spacing=4,
                        ),
                        ft.Image(
                            src=trade.screenshot_path,
                            fit=ft.ImageFit.COVER,
                            height=120,
                            border_radius=RADIUS_MD,
                        ),
                    ],
                    spacing=4,
                ),
                padding=8,
                bgcolor=SURFACE_2,
                border_radius=RADIUS_MD,
            )

        orders_tree = self._build_orders_tree(trade)
        mini_candlestick = self._build_mini_candlestick_chart(trade)

        # Кнопки графиков
        chart_buttons = ft.Row(
            controls=[
                ft.ElevatedButton(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.FULLSCREEN_ROUNDED, size=15, color=TEXT_PRIMARY),
                            ft.Text("Развернуть график", size=11, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                        ],
                        tight=True,
                        spacing=4,
                    ),
                    bgcolor=ACCENT_PRIMARY,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=RADIUS_SM)),
                    on_click=lambda _, t=trade: self._open_interactive_trade_chart(t),
                    expand=True,
                ),
                ft.OutlinedButton(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.SHOW_CHART_ROUNDED, size=14, color=ACCENT_SECONDARY),
                            ft.Text("TradingView", size=11, color=ACCENT_SECONDARY),
                        ],
                        tight=True,
                        spacing=4,
                    ),
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                        side=ft.BorderSide(1, ft.Colors.with_opacity(0.4, ACCENT_SECONDARY)),
                    ),
                    on_click=lambda _, t=trade: self._open_tradingview_widget_modal(t),
                ),
            ],
            spacing=6,
        )

        self.inspector_content.controls = [
            # Шапка
            ft.Row(
                controls=[
                    ft.Row(
                        controls=[
                            create_pnl_badge(trade.direction),
                            ft.Text(trade.ticker, size=18, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                        ],
                        spacing=8,
                    ),
                    ft.Row(
                        controls=[
                            ft.IconButton(
                                icon=ft.Icons.EDIT_NOTE_ROUNDED,
                                icon_size=18,
                                icon_color=ACCENT_PRIMARY,
                                tooltip="Редактировать сделку",
                                on_click=lambda _: self._open_edit_modal(trade),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE_ROUNDED,
                                icon_size=18,
                                icon_color=TEXT_SECONDARY,
                                tooltip="Закрыть инспектор (Esc)",
                                on_click=lambda _: self.close_inspector(),
                            ),
                        ],
                        spacing=0,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Row([create_strategy_badge(trade.strategy_tag)]),
            ft.Divider(color=BORDER_SUBTLE, height=8),

            # Финансовый результат
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text("Net PnL (с учетом комиссий)", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                                ft.Text(f"{'+' if is_win else ''}${trade.net_pnl:,.2f}", size=20, weight=ft.FontWeight.BOLD, color=pnl_color, font_family=FONT_MONO),
                            ],
                            spacing=1,
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(f"Комиссии: ${trade.commission + trade.swap_fee:.2f}", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                                ft.Text(f"Риск: ${trade.risk_amount:.2f}", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                            spacing=1,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=10,
                bgcolor=SURFACE_2,
                border_radius=RADIUS_MD,
            ),

            mini_candlestick,
            chart_buttons,
            underwater_card,
            tilt_block,
            orders_tree,

            # Заметки
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Заметки трейдера:", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Text(trade.notes or "Заметок нет.", size=11, color=TEXT_PRIMARY if trade.notes else TEXT_MUTED, font_family=FONT_FAMILY),
                    ],
                    spacing=2,
                ),
                padding=8,
                bgcolor=SURFACE_2,
                border_radius=RADIUS_MD,
            ),

            screenshot_preview,

            # Кнопка удаления
            ft.Container(
                content=ft.ElevatedButton(
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.DELETE_OUTLINE_ROUNDED, size=15, color=LOSS),
                            ft.Text("Удалить сделку из журнала", color=LOSS, size=12, font_family=FONT_FAMILY),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=6,
                    ),
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.with_opacity(0.12, LOSS),
                        shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
                        side=ft.BorderSide(1, ft.Colors.with_opacity(0.3, LOSS)),
                    ),
                    on_click=lambda _, t=trade: self._confirm_delete_trade(t),
                ),
                padding=ft.padding.only(top=4),
            ),
        ]

    def _confirm_delete_trade(self, trade: Trade) -> None:
        """Показывает модальное окно подтверждения удаления сделки."""
        def close_dlg(_):
            confirm_dialog.open = False
            if self.page:
                self.page.update()

        def do_delete(_):
            confirm_dialog.open = False
            if self.page:
                self.page.update()
            self._delete_trade_handler(trade.id)

        confirm_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=LOSS, size=24),
                    ft.Text("Удаление сделки", size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                ],
                spacing=8,
            ),
            content=ft.Text(
                f"Вы уверены, что хотите удалить сделку {trade.ticker} (#{trade.id})?\n"
                "Это действие безвозвратно удалит позицию и все привязанные ордера.",
                size=13,
                color=TEXT_SECONDARY,
                font_family=FONT_FAMILY,
            ),
            actions=[
                ft.TextButton("Отмена", on_click=close_dlg),
                ft.ElevatedButton(
                    content=ft.Text("Удалить", weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                    style=ft.ButtonStyle(bgcolor=LOSS),
                    on_click=do_delete,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor=SURFACE_OVERLAY,
            shape=ft.RoundedRectangleBorder(radius=RADIUS_LG),
        )

        target_page = self.host_page
        if target_page:
            target_page.dialog = confirm_dialog
            confirm_dialog.open = True
            target_page.update()
        else:
            self._delete_trade_handler(trade.id)

    def _open_interactive_trade_chart(self, trade: Trade) -> None:
        """Открывает диалоговое окно с автономным графиком TradingView Lightweight Charts на 85% ширины экрана."""
        try:
            chart_file = generate_trade_chart(trade)
            chart_uri = Path(chart_file).resolve().as_uri()
            tv_url = get_tradingview_url(trade.ticker)

            def close_dlg(_):
                if self.host_page:
                    try:
                        self.host_page.close(chart_dialog)
                    except Exception:
                        chart_dialog.open = False
                        self.host_page.update()

            win_width = self.page.window.width if (self.page and self.page.window and self.page.window.width) else 1260
            dialog_width = max(int(win_width * 0.85), 960)

            chart_dialog = ft.AlertDialog(
                modal=True,
                title=ft.Row(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.AUTO_GRAPH, color=PROFIT if trade.net_pnl >= 0 else LOSS, size=22),
                                ft.Text(f"{trade.ticker} • Анализ исполнения", size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                create_strategy_badge(trade.strategy_tag),
                            ],
                            spacing=8,
                        ),
                        ft.Row(
                            controls=[
                                ft.IconButton(
                                    icon=ft.Icons.OPEN_IN_NEW,
                                    icon_size=18,
                                    icon_color=ACCENT_PRIMARY,
                                    tooltip="Открыть график в отдельной вкладке браузера",
                                    on_click=lambda _: webbrowser.open(chart_uri),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.CLOSE_ROUNDED,
                                    icon_size=18,
                                    icon_color=TEXT_SECONDARY,
                                    tooltip="Закрыть",
                                    on_click=close_dlg,
                                ),
                            ],
                            spacing=4,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                content=ft.Container(
                    content=ft.WebView(
                        url=f"/cache_trade_chart.html?t={int(datetime.now().timestamp())}",
                        javascript_enabled=True,
                        expand=True,
                    ),
                    width=dialog_width,
                    height=580,
                    
                    border_radius=RADIUS_MD,
                    
                ),
                actions=[
                    ft.OutlinedButton(
                        content=ft.Row([
                            ft.Icon(ft.Icons.SHOW_CHART, size=15, color=ACCENT_PRIMARY),
                            ft.Text("TradingView.com", size=12, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                        ], tight=True, spacing=4),
                        style=ft.ButtonStyle(side=ft.BorderSide(1, BORDER_SUBTLE)),
                        on_click=lambda _: webbrowser.open(tv_url),
                    ),
                    ft.ElevatedButton(
                        content=ft.Row([
                            ft.Icon(ft.Icons.OPEN_IN_NEW, size=15, color=TEXT_PRIMARY),
                            ft.Text("Открыть в браузере", size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                        ], tight=True, spacing=6),
                        style=ft.ButtonStyle(
                            bgcolor=ACCENT_PRIMARY,
                            shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
                        ),
                        on_click=lambda _: webbrowser.open(chart_uri),
                    ),
                    ft.TextButton("Закрыть", on_click=close_dlg),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
                bgcolor=SURFACE_OVERLAY,
                shape=ft.RoundedRectangleBorder(radius=RADIUS_LG),
            )

            target_page = self.host_page
            if target_page:
                try:
                    target_page.open(chart_dialog)
                except Exception:
                    target_page.dialog = chart_dialog
                    chart_dialog.open = True
                    target_page.update()
            else:
                webbrowser.open(chart_uri)
        except Exception as ex:
            target_page = self.host_page
            if target_page:
                target_page.show_snack_bar(
                    ft.SnackBar(
                        content=ft.Text(f"Ошибка построения графика: {ex}"),
                        bgcolor=LOSS,
                    )
                )

    def _open_tradingview_widget_modal(self, trade: Trade) -> None:
        """Открывает модальное окно с виджетом TradingView по тикеру инструмента."""
        from services.chart_service import get_tradingview_url, get_binance_symbol
        tv_url = get_tradingview_url(trade.ticker)
        bsym = get_binance_symbol(trade.ticker)
        sym_code = f"BINANCE:{bsym}" if bsym else trade.ticker.replace("/", "")

        def close_widget(_):
            if self.host_page:
                try:
                    self.host_page.close(dlg)
                except Exception:
                    dlg.open = False
                    self.host_page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.SHOW_CHART_ROUNDED, size=20, color=ACCENT_PRIMARY),
                            ft.Text(f"TradingView Widget — {sym_code}", size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                        ],
                        spacing=8,
                    ),
                    ft.IconButton(ft.Icons.CLOSE_ROUNDED, icon_size=18, icon_color=TEXT_SECONDARY, on_click=close_widget),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(f"Инструмент: {sym_code} • Профессиональные графики и аналитика TradingView", size=12, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Icon(ft.Icons.QUERY_STATS_ROUNDED, size=44, color=ACCENT_PRIMARY),
                                    ft.Text(f"Интерактивный терминал {sym_code}", size=15, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("TradingView Lightweight Engine v4.0", size=12, color=TEXT_MUTED, font_family=FONT_MONO),
                                    ft.ElevatedButton(
                                        content=ft.Row(
                                            [
                                                ft.Icon(ft.Icons.OPEN_IN_NEW, size=16, color=TEXT_PRIMARY),
                                                ft.Text(f"Открыть график {sym_code} на TradingView.com", color=TEXT_PRIMARY, weight=ft.FontWeight.BOLD),
                                            ],
                                            tight=True,
                                            spacing=6,
                                        ),
                                        bgcolor=ACCENT_PRIMARY,
                                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=RADIUS_MD)),
                                        on_click=lambda _: webbrowser.open(tv_url),
                                    ),
                                ],
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                alignment=ft.MainAxisAlignment.CENTER,
                                spacing=10,
                            ),
                            bgcolor=SURFACE_1,
                            border=ft.border.all(1, BORDER_SUBTLE),
                            border_radius=RADIUS_MD,
                            height=320,
                            alignment=ft.alignment.center,
                        ),
                    ],
                    spacing=8,
                ),
                width=680,
                height=380,
            ),
            actions=[
                ft.TextButton("Закрыть", on_click=close_widget),
            ],
            bgcolor=SURFACE_OVERLAY,
            shape=ft.RoundedRectangleBorder(radius=RADIUS_LG),
        )

        target_page = self.host_page
        if target_page:
            try:
                target_page.open(dlg)
            except Exception:
                target_page.dialog = dlg
                dlg.open = True
                target_page.update()
        else:
            webbrowser.open(tv_url)

    def _mini_stat(self, label: str, val: str, color: str) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(label, size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                    ft.Text(val, size=11, weight=ft.FontWeight.BOLD, color=color, font_family=FONT_MONO),
                ],
                spacing=1,
            ),
            bgcolor=SURFACE_1,
            
            padding=6,
            border_radius=RADIUS_SM,
            expand=True,
        )

    def _open_edit_modal(self, trade: Trade):
        if self.on_edit_requested:
            self.on_edit_requested(trade)

    def _export_csv(self):
        trades = self.db.get_all_trades()
        out_path = Path(__file__).resolve().parent.parent.parent / "data" / "trades_export.csv"
        saved = AnalyticsService.export_trades_to_csv(trades, str(out_path))
        if self.page:
            self.page.show_snack_bar(
                ft.SnackBar(
                    content=ft.Text(f"База сделок успешно экспортирована: {out_path.name}", color=TEXT_PRIMARY),
                    bgcolor=SURFACE_1,
                    
                )
            )

    def _on_csv_import_selected(self, e: ft.FilePickerResultEvent):
        if e.files:
            file_path = e.files[0].path
            count = AnalyticsService.import_trades_from_csv(file_path, self.db)
            self.refresh()
            if self.page:
                self.page.show_snack_bar(
                    ft.SnackBar(
                        content=ft.Text(f"Успешно импортировано сделок: {count}", color=TEXT_PRIMARY),
                        bgcolor=SURFACE_1,
                        
                    )
                )

    def _on_screenshot_picked(self, e: ft.FilePickerResultEvent):
        if e.files and self.selected_trade:
            file_path = e.files[0].path
            self.db.update_trade(self.selected_trade.id, screenshot_path=file_path)
            fresh = self.db.get_trade_by_id(self.selected_trade.id)
            if fresh:
                self.open_inspector(fresh)

    def open_inspector(self, trade: Trade) -> None:
        self.selected_trade = trade
        self._render_inspector_content(trade)
        self.inspector_panel.visible = True
        self.refresh()
        try:
            self.update()
        except Exception:
            pass
        if hasattr(self, "workspace") and self.workspace.page:
            try:
                self.workspace.update()
            except Exception:
                pass
        p = self.host_page
        if p:
            try:
                p.update()
            except Exception:
                pass

    def close_inspector(self) -> None:
        self.selected_trade = None
        self.inspector_panel.visible = False
        self.refresh()
        try:
            self.update()
        except Exception:
            pass
        if hasattr(self, "workspace") and self.workspace.page:
            try:
                self.workspace.update()
            except Exception:
                pass
        p = self.host_page
        if p:
            try:
                p.update()
            except Exception:
                pass

    def _delete_trade_handler(self, trade_id: int) -> None:
        self.db.delete_trade(trade_id)
        if self.selected_trade and self.selected_trade.id == trade_id:
            self.selected_trade = None
            self.inspector_panel.visible = False
        self.refresh()
        p = self.host_page
        if p:
            try:
                p.update()
            except Exception:
                pass
        elif self.page:
            try:
                self.update()
            except Exception:
                pass
        if self.on_trade_deleted:
            self.on_trade_deleted()

    def _create_trade_card(self, trade: Trade, max_abs_pnl: float) -> ft.Container:
        """Создает жестко выровненную карточку строки таблицы с плавным ховером."""
        is_selected = self.selected_trade and self.selected_trade.id == trade.id
        is_win = trade.net_pnl >= 0
        pnl_color = PROFIT if is_win else LOSS

        border_c = ACCENT_PRIMARY if is_selected else (ft.Colors.with_opacity(0.4, WARNING_TILT) if trade.is_tilt else BORDER_SUBTLE)
        bg_c = SURFACE_2 if is_selected else SURFACE_1

        tilt_indicator = ft.Container(
            content=ft.Icon(ft.Icons.PSYCHOLOGY_ROUNDED, size=14, color=WARNING_TILT),
            tooltip=f"Тильт: {trade.tilt_reason or 'Вне системы'}",
            visible=trade.is_tilt,
        )

        card = ft.Container(
            content=ft.Row(
                controls=[
                    # Колонка 1: Инструмент + Стратегия + Тильт индикатор
                    ft.Container(
                        content=ft.Row(
                            controls=[
                                create_pnl_badge(trade.direction),
                                ft.Column(
                                    controls=[
                                        ft.Row([ft.Text(trade.ticker, size=13, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY), tilt_indicator], spacing=4),
                                        create_strategy_badge(trade.strategy_tag),
                                    ],
                                    spacing=3,
                                ),
                            ],
                            spacing=10,
                        ),
                        width=COL_WIDTH_TICKER,
                    ),

                    # Колонка 2: Цены VWAP + SL
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Row([ft.Text("Вх: ", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY), ft.Text(f"${trade.entry_price:,.2f}", size=12, color=TEXT_PRIMARY, font_family=FONT_MONO)], spacing=2),
                                ft.Row([ft.Text("Вых: ", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY), ft.Text(f"${trade.exit_price:,.2f}", size=12, color=TEXT_PRIMARY, font_family=FONT_MONO)], spacing=2),
                                ft.Text(f"SL: ${trade.stop_loss:,.2f}" if trade.stop_loss else "SL: —", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                            ],
                            spacing=1,
                        ),
                        width=COL_WIDTH_PRICES,
                    ),

                    # Колонка 3: Объем, Комиссия и Время
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Row([ft.Text("Объем: ", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY), ft.Text(f"{trade.volume:g}", size=11, color=TEXT_PRIMARY, font_family=FONT_MONO)], spacing=2),
                                ft.Text(f"Ком: ${trade.commission:.2f}", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                                ft.Text(trade.closed_at.strftime("%d.%m.%Y %H:%M"), size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                            ],
                            spacing=1,
                        ),
                        width=COL_WIDTH_META,
                    ),

                    # Колонка 4: Net PnL + R-Multiple + Динамический прогресс-бар
                    ft.Container(
                        content=ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text(
                                            f"{'+' if is_win else ''}${trade.net_pnl:,.2f}",
                                            size=13,
                                            weight=ft.FontWeight.BOLD,
                                            color=pnl_color,
                                            font_family=FONT_MONO,
                                            text_align=ft.TextAlign.RIGHT,
                                        ),
                                        ft.Container(
                                            content=ft.Text(f"{trade.r_multiple:+.1f}R", size=9, weight=ft.FontWeight.BOLD, color=pnl_color, font_family=FONT_MONO),
                                            bgcolor=ft.Colors.with_opacity(0.14, pnl_color),
                                            padding=ft.padding.symmetric(horizontal=4, vertical=1),
                                            border_radius=3,
                                            alignment=ft.alignment.center_right,
                                        ),
                                    ],
                                    spacing=2,
                                    horizontal_alignment=ft.CrossAxisAlignment.END,
                                ),
                                create_dynamic_pnl_bar(trade.net_pnl, max_abs_pnl),
                            ],
                            spacing=8,
                            alignment=ft.MainAxisAlignment.START,
                        ),
                        width=COL_WIDTH_PNL,
                    ),

                    # Колонка 5: Стрелка инспектора
                    ft.Container(
                        content=ft.IconButton(
                            icon=ft.Icons.CHEVRON_RIGHT_ROUNDED,
                            icon_size=18,
                            icon_color=ACCENT_PRIMARY if is_selected else TEXT_MUTED,
                            tooltip="Открыть инспектор позиции",
                            on_click=lambda _, t=trade: self.open_inspector(t),
                        ),
                        width=COL_WIDTH_ACTION,
                        alignment=ft.alignment.center_right,
                    ),
                ],
                alignment=ft.MainAxisAlignment.START,
                spacing=12,
            ),
            padding=ft.padding.symmetric(horizontal=16, vertical=8),
            bgcolor=bg_c,
            border_radius=RADIUS_MD,
            border=ft.border.all(1, border_c),
            ink=True,
            on_click=lambda _, t=trade: self.open_inspector(t),
        )

        return card

    def refresh(self, account_id: Any = "KEEP") -> None:
        """Применяет фильтры в реальном времени и перерисовывает список."""
        if account_id != "KEEP":
            self.current_account_id = None if (account_id is None or account_id == -1) else account_id

        filters = {}
        query = (self.search_field.value or "").strip()
        if query:
            filters["query"] = query

        now = datetime.now()
        if self.filter_period == "month":
            filters["date_from"] = now - timedelta(days=30)
        elif self.filter_period == "week":
            filters["date_from"] = now - timedelta(days=7)
        elif self.filter_period == "today":
            filters["date_from"] = datetime.combine(now.date(), datetime.min.time())
            filters["date_to"] = datetime.combine(now.date(), datetime.max.time())
        elif self.filter_period == "custom" and self.custom_date_filter:
            filters["date_from"] = datetime.combine(self.custom_date_filter, datetime.min.time())
            filters["date_to"] = datetime.combine(self.custom_date_filter, datetime.max.time())

        if self.filter_result != "all":
            filters["result"] = self.filter_result

        trades = self.db.get_trades(account_id=self.current_account_id, filters=filters, order_by_date_desc=True)

        if not trades:
            self.trades_listview.controls = [
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.FILTER_LIST_OFF_ROUNDED, size=46, color=TEXT_MUTED),
                            ft.Text("Сделок по выбранным фильтрам не найдено", color=TEXT_SECONDARY, size=14, weight=ft.FontWeight.W_500, font_family=FONT_FAMILY),
                            ft.Text("Измените фильтр или очистите поисковый запрос", color=TEXT_MUTED, size=11, font_family=FONT_FAMILY),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    padding=50,
                    alignment=ft.alignment.center,
                )
            ]
        else:
            max_abs = max([abs(t.net_pnl) for t in trades] + [1.0])
            self.trades_listview.controls = [
                self._create_trade_card(t, max_abs) for t in trades
            ]

        if self.trades_listview.page:
            self.trades_listview.update()
        elif self.page:
            self.update()
