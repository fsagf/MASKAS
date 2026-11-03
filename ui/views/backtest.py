"""
ui/views/backtest.py
Модуль ручного бэктестинга и рыночного симулятора (TraderWaves Market Replay).
Пошаговое воспроизведение исторических японских свечей через Canvas без заглядывания в будущее,
симуляция рыночных заявок (BUY / SELL / CLOSE), расчет плавающего (Unrealized)
и закрытого (Realized) P&L, винрейта и журнал сделок сессии.
"""

import asyncio
from datetime import datetime, timedelta
import math
import random
from typing import Any, Dict, List, Optional
import flet as ft
import flet.canvas as cv

from analytics import MarketDataService
from ui.theme import (
    ACCENT_PRIMARY,
    ACCENT_SECONDARY,
    ANIM_FAST_MS,
    ANIMATIONS_ENABLED,
    BG_APP,
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
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING_TILT,
    create_neon_box_shadow,
    get_animation,
)

SYMBOLS_CONFIG = {
    "BTC/USDT": {"base_price": 67500.0, "step": 150.0, "vol": 0.004, "decimals": 1, "default_lot": 0.5},
    "ETH/USDT": {"base_price": 2640.0, "step": 12.0, "vol": 0.006, "decimals": 2, "default_lot": 2.0},
    "SOL/USDT": {"base_price": 178.5, "step": 1.5, "vol": 0.008, "decimals": 2, "default_lot": 10.0},
    "EUR/USD": {"base_price": 1.0845, "step": 0.0008, "vol": 0.0015, "decimals": 4, "default_lot": 1.0},
    "NVDA": {"base_price": 141.2, "step": 1.2, "vol": 0.005, "decimals": 2, "default_lot": 20.0},
}


class BacktestView(ft.Container):
    """
    Экран симулятора рынка и ручного бэктестинга с японскими свечами Canvas.
    """

    def __init__(self, page: Optional[ft.Page] = None):
        super().__init__(expand=True)
        self._page_ref = page

        # Состояние сессии бэктеста
        self.initial_balance = 10000.0
        self.virtual_balance = 10000.0
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.session_trades: List[Dict[str, Any]] = []

        # Активная позиция: {"direction": "LONG"|"SHORT", "entry_price": float, "volume": float, "entry_step": int}
        self.active_position: Optional[Dict[str, Any]] = None

        # Состояние плеера
        self.selected_symbol = "BTC/USDT"
        self.selected_timeframe = "5m"
        self.all_candles: List[Dict[str, Any]] = []
        self.replay_index = 35
        self.is_playing = False
        self._play_task: Optional[asyncio.Task] = None

        # Инициализация интерфейса
        self._build_components()
        self._load_market_candles()
        self.content = self._build_layout()
        self._update_all_views()

    def _build_components(self) -> None:
        """Создает элементы управления и метрики."""
        # Селекторы
        self.symbol_dropdown = ft.Dropdown(
            label="Инструмент",
            options=[ft.dropdown.Option(s) for s in SYMBOLS_CONFIG.keys()],
            value=self.selected_symbol,
            width=160,
            bgcolor=SURFACE_2,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            text_size=12,
            border_radius=8,
            dense=True,
            on_change=self._on_symbol_changed,
        )

        self.timeframe_dropdown = ft.Dropdown(
            label="Таймфрейм",
            options=[
                ft.dropdown.Option("1m"),
                ft.dropdown.Option("5m"),
                ft.dropdown.Option("15m"),
                ft.dropdown.Option("1h"),
            ],
            value=self.selected_timeframe,
            width=110,
            bgcolor=SURFACE_2,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            text_size=12,
            border_radius=8,
            dense=True,
            on_change=self._on_tf_changed,
        )

        # Метрики баланса
        self.balance_text = ft.Text("$10,000.00", size=18, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO)
        self.unrealized_text = ft.Text("$0.00", size=14, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO)
        self.realized_text = ft.Text("$0.00", size=14, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO)
        self.winrate_text = ft.Text("0.0%", size=18, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO)
        self.winrate_subtext = ft.Text("0 из 0 прибыльных", size=10, color=TEXT_MUTED, font_family=FONT_MONO)

        # TradingView-style информационная строка OHLCV
        self.ohlcv_info_bar = ft.Row(
            controls=[],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.ADAPTIVE,
        )

        # Свечной график на основе flet.canvas
        self.chart_canvas = cv.Canvas(
            height=320,
            expand=True,
        )

        self.chart_container = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(
                        content=self.ohlcv_info_bar,
                        padding=ft.padding.only(left=12, top=8, bottom=4),
                    ),
                    self.chart_canvas,
                ],
                spacing=0,
            ),
            height=365,
            expand=True,
            bgcolor="#090A0F",
            border=ft.border.all(1, BORDER_SUBTLE),
            border_radius=RADIUS_MD,
            padding=0,
        )

        # Плеер управления
        self.candle_counter_text = ft.Text("Свеча: 35 / 100", size=12, color=TEXT_SECONDARY, font_family=FONT_MONO)
        self.current_price_text = ft.Text("Цена: $0.00", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO)

        self.play_btn = ft.ElevatedButton(
            text="Play",
            icon=ft.Icons.PLAY_ARROW_ROUNDED,
            bgcolor=ACCENT_PRIMARY,
            color=TEXT_PRIMARY,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
            ),
            on_click=self._on_play_toggle,
        )

        # Торговые операции
        cfg = SYMBOLS_CONFIG[self.selected_symbol]
        self.volume_field = ft.TextField(
            label="Объем (лот)",
            value=str(cfg["default_lot"]),
            width=110,
            bgcolor=SURFACE_2,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            color=TEXT_PRIMARY,
            text_size=12,
            border_radius=8,
            dense=True,
            text_style=ft.TextStyle(font_family=FONT_MONO),
        )

        self.sl_field = ft.TextField(
            label="SL (%)",
            value="1.5",
            width=90,
            bgcolor=SURFACE_2,
            border_color=BORDER_SUBTLE,
            focused_border_color=LOSS,
            color=TEXT_PRIMARY,
            text_size=12,
            border_radius=8,
            dense=True,
            text_style=ft.TextStyle(font_family=FONT_MONO),
        )

        self.tp_field = ft.TextField(
            label="TP (%)",
            value="3.0",
            width=90,
            bgcolor=SURFACE_2,
            border_color=BORDER_SUBTLE,
            focused_border_color=PROFIT,
            color=TEXT_PRIMARY,
            text_size=12,
            border_radius=8,
            dense=True,
            text_style=ft.TextStyle(font_family=FONT_MONO),
        )

        self.position_status_banner = ft.Container(
            content=ft.Text("ВНЕ ПОЗИЦИИ (FLAT)", size=12, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO),
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
            border_radius=8,
            bgcolor=BG_APP,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

        # Журнал сделок бэктеста
        self.trades_listview = ft.ListView(expand=True, spacing=6, height=180)

    def _build_layout(self) -> ft.Control:
        """Собирает рабочий стол симулятора."""
        header = ft.Row(
            [
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.CANDLESTICK_CHART_ROUNDED, color=ACCENT_PRIMARY, size=24),
                                ft.Text("Симулятор рынка & Ручной бэктестинг", size=20, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                                ft.Container(
                                    content=ft.Text("MARKET REPLAY", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_SECONDARY, font_family=FONT_MONO),
                                    bgcolor=f"{ACCENT_SECONDARY}18",
                                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                    border_radius=4,
                                    border=ft.border.all(1, f"{ACCENT_SECONDARY}44"),
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Text("Пошаговое тестирование стратегий на японских свечах с симуляцией ордеров", size=12, color=TEXT_SECONDARY),
                    ],
                    spacing=2,
                ),
                ft.Row(
                    [
                        self.symbol_dropdown,
                        self.timeframe_dropdown,
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.REPLAY_ROUNDED, size=15, color=LOSS), ft.Text("Сброс сессии", size=12, color=LOSS)], spacing=6),
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8), side=ft.BorderSide(1, ft.Colors.with_opacity(0.4, LOSS))),
                            on_click=self._on_reset_session,
                        ),
                    ],
                    spacing=10,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # Карточки метрик
        stat_cards = ft.Row(
            [
                self._build_mini_card("Виртуальный баланс", self.balance_text, "Старт: $10,000", ACCENT_PRIMARY),
                self._build_mini_card("Плавающий P&L (Unrealized)", self.unrealized_text, "Текущая позиция", WARNING_TILT),
                self._build_mini_card("Закрытый P&L (Realized)", self.realized_text, "Зафиксировано", PROFIT),
                self._build_mini_card("Винрейт (Сессия)", self.winrate_text, self.winrate_subtext, ACCENT_PRIMARY),
            ],
            spacing=12,
        )

        # Панель плеера и управления сделками (двухуровневая адаптивная компоновка)
        player_tier1 = ft.Row(
            controls=[
                ft.Row(
                    [
                        ft.IconButton(
                            icon=ft.Icons.FIRST_PAGE_ROUNDED,
                            icon_size=20,
                            icon_color=TEXT_MUTED,
                            tooltip="В начало (|<)",
                            on_click=lambda _: self._reset_to_start(),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.SKIP_PREVIOUS_ROUNDED,
                            icon_size=20,
                            icon_color=TEXT_PRIMARY,
                            tooltip="Назад на 1 свечу (<)",
                            on_click=lambda _: self._step_backward(),
                        ),
                        self.play_btn,
                        ft.IconButton(
                            icon=ft.Icons.SKIP_NEXT_ROUNDED,
                            icon_size=20,
                            icon_color=TEXT_PRIMARY,
                            tooltip="Вперед на 1 свечу (>)",
                            on_click=lambda _: self._step_forward(),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.FAST_FORWARD_ROUNDED,
                            icon_size=20,
                            icon_color=ACCENT_SECONDARY,
                            tooltip="Вперед на 5 свечей (>>)",
                            on_click=lambda _: self._step_forward(5),
                        ),
                    ],
                    spacing=4,
                ),
                ft.Row(
                    [
                        self.candle_counter_text,
                        ft.VerticalDivider(width=1, color=BORDER_SUBTLE),
                        self.current_price_text,
                    ],
                    spacing=12,
                ),
                self.position_status_banner,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        player_tier2 = ft.Row(
            controls=[
                ft.Row(
                    [
                        self.volume_field,
                        self.sl_field,
                        self.tp_field,
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    [
                        ft.ElevatedButton(
                            text="BUY Market",
                            icon=ft.Icons.ARROW_UPWARD_ROUNDED,
                            color=TEXT_PRIMARY,
                            bgcolor=PROFIT,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=8),
                                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                            ),
                            on_click=lambda _: self._execute_order("LONG"),
                        ),
                        ft.ElevatedButton(
                            text="SELL Market",
                            icon=ft.Icons.ARROW_DOWNWARD_ROUNDED,
                            color=TEXT_PRIMARY,
                            bgcolor=LOSS,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=8),
                                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                            ),
                            on_click=lambda _: self._execute_order("SHORT"),
                        ),
                        ft.ElevatedButton(
                            text="Закрыть",
                            icon=ft.Icons.CLOSE_ROUNDED,
                            color=TEXT_PRIMARY,
                            bgcolor=ACCENT_PRIMARY,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=8),
                                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                            ),
                            on_click=lambda _: self._close_current_position(),
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        player_bar = ft.Container(
            content=ft.Column(
                controls=[
                    player_tier1,
                    ft.Divider(height=1, color=BORDER_SUBTLE),
                    player_tier2,
                ],
                spacing=8,
            ),
            bgcolor=SURFACE_2,
            border=ft.border.all(1, BORDER_SUBTLE),
            border_radius=12,
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
        )

        # Карточка графика
        chart_card = ft.Container(
            content=ft.Column(
                [
                    player_bar,
                    self.chart_container,
                ],
                spacing=10,
            ),
            bgcolor=SURFACE_1,
            border=ft.border.all(1, BORDER_SUBTLE),
            border_radius=16,
            padding=16,
        )

        # Нижняя секция: Журнал бэктеста
        trades_section = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.FORMAT_LIST_BULLETED_ROUNDED, size=16, color=ACCENT_PRIMARY),
                                    ft.Text("СДЕЛКИ ТЕКУЩЕЙ СЕССИИ БЭКТЕСТА", size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                                ],
                                spacing=6,
                            ),
                            ft.Text(f"Всего закрыто: {len(self.session_trades)}", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(color=BORDER_SUBTLE, height=10),
                    self.trades_listview,
                ],
                spacing=8,
            ),
            bgcolor=SURFACE_1,
            border=ft.border.all(1, BORDER_SUBTLE),
            border_radius=14,
            padding=14,
        )

        return ft.Column(
            [
                header,
                ft.Divider(color=BORDER_SUBTLE, height=12),
                stat_cards,
                chart_card,
                trades_section,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )

    def _build_mini_card(self, title: str, text_ctl: ft.Text, subtitle: Union[str, ft.Text], color: str) -> ft.Container:
        sub_ctl = ft.Text(subtitle, size=10, color=TEXT_MUTED, font_family=FONT_MONO) if isinstance(subtitle, str) else subtitle
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(title, size=11, color=TEXT_SECONDARY, weight=ft.FontWeight.W_500),
                    text_ctl,
                    sub_ctl,
                ],
                spacing=2,
            ),
            bgcolor=SURFACE_1,
            border=ft.border.all(1, BORDER_SUBTLE),
            border_radius=12,
            padding=12,
            expand=True,
        )

    def _load_market_candles(self) -> None:
        """Генерирует 100 реалистичных исторических свечей для выбранного инструмента."""
        cfg = SYMBOLS_CONFIG.get(self.selected_symbol, SYMBOLS_CONFIG["BTC/USDT"])
        base = cfg["base_price"]
        vol = cfg["vol"]

        # Пытаемся получить живые свечи Binance если криптовалюта
        now = datetime.now()
        start = now - timedelta(hours=10)
        live = MarketDataService.fetch_market_klines(self.selected_symbol, start, now, interval=self.selected_timeframe)

        if live and len(live) >= 40:
            self.all_candles = live
        else:
            # Генератор геометрического броуновского движения для бэктеста
            candles = []
            curr_p = base
            curr_t = now - timedelta(minutes=100 * 5)
            dt_step = timedelta(minutes=5)

            for i in range(100):
                drift = random.uniform(-vol, vol)
                open_p = curr_p
                close_p = open_p * (1.0 + drift)
                high_p = max(open_p, close_p) * (1.0 + random.uniform(0.0005, vol * 0.8))
                low_p = min(open_p, close_p) * (1.0 - random.uniform(0.0005, vol * 0.8))

                candles.append({
                    "timestamp": curr_t,
                    "open": round(open_p, cfg["decimals"]),
                    "high": round(high_p, cfg["decimals"]),
                    "low": round(low_p, cfg["decimals"]),
                    "close": round(close_p, cfg["decimals"]),
                    "volume": round(random.uniform(50.0, 300.0), 1),
                })
                curr_p = close_p
                curr_t += dt_step

            self.all_candles = candles

        self.replay_index = min(35, len(self.all_candles) - 10)

    def _on_symbol_changed(self, _) -> None:
        self.selected_symbol = self.symbol_dropdown.value or "BTC/USDT"
        cfg = SYMBOLS_CONFIG[self.selected_symbol]
        self.volume_field.value = str(cfg["default_lot"])
        print(f"[BacktestView] Symbol changed to: {self.selected_symbol}")
        self._load_market_candles()
        self._close_current_position(silent=True)
        self._update_all_views()

    def _on_tf_changed(self, _) -> None:
        self.selected_timeframe = self.timeframe_dropdown.value or "5m"
        print(f"[BacktestView] Timeframe changed to: {self.selected_timeframe}")
        self._load_market_candles()
        self._update_all_views()

    def _reset_to_start(self) -> None:
        """Перемещает курсор на начальную свечу (10)."""
        self.replay_index = 10
        print("[BacktestView] Reset to start (candle 10)")
        self._update_unrealized_pnl()
        self._update_all_views()

    def _step_forward(self, count: int = 1) -> None:
        """Перемещает курсор воспроизведения вперед с проверкой срабатывания SL/TP."""
        max_idx = len(self.all_candles) - 1
        for _ in range(count):
            if self.replay_index < max_idx:
                self.replay_index += 1
                curr_c = self.all_candles[self.replay_index]
                if self.active_position:
                    pos = self.active_position
                    dir_pos = pos["direction"]
                    sl_p = pos.get("stop_loss")
                    tp_p = pos.get("take_profit")

                    hit_action = None
                    hit_price = None

                    if dir_pos == "LONG":
                        if sl_p and curr_c["low"] <= sl_p:
                            hit_action = "Stop-Loss"
                            hit_price = sl_p
                        elif tp_p and curr_c["high"] >= tp_p:
                            hit_action = "Take-Profit"
                            hit_price = tp_p
                    else:
                        if sl_p and curr_c["high"] >= sl_p:
                            hit_action = "Stop-Loss"
                            hit_price = sl_p
                        elif tp_p and curr_c["low"] <= tp_p:
                            hit_action = "Take-Profit"
                            hit_price = tp_p

                    if hit_action:
                        print(f"[BacktestView] {hit_action} triggered at price ${hit_price:,.2f}")
                        self._close_current_position(exit_price=hit_price, reason=hit_action)
                        break
            else:
                if self.is_playing:
                    self._stop_play()
                break

        print(f"[BacktestView] Step forward (+{count}) -> Candle {self.replay_index + 1}/{len(self.all_candles)}")
        self._update_unrealized_pnl()
        self._update_all_views()

    def _step_backward(self, count: int = 1) -> None:
        """Перемещает курсор воспроизведения назад."""
        if self.replay_index > 5:
            self.replay_index = max(5, self.replay_index - count)
            print(f"[BacktestView] Step backward (-{count}) -> Candle {self.replay_index + 1}/{len(self.all_candles)}")
            self._update_unrealized_pnl()
            self._update_all_views()

    def _on_play_toggle(self, _) -> None:
        if self.is_playing:
            self._stop_play()
        else:
            self._start_play()

    def _start_play(self) -> None:
        self.is_playing = True
        self.play_btn.text = "Pause"
        self.play_btn.icon = ft.Icons.PAUSE_ROUNDED
        self.play_btn.bgcolor = WARNING_TILT
        print(f"[BacktestView] Play started at candle {self.replay_index + 1}")
        if self.play_btn.page:
            self.play_btn.update()
        elif self.page:
            self.page.update()

        if self.page:
            self._play_task = self.page.run_task(self._auto_play_loop)

    def _stop_play(self) -> None:
        self.is_playing = False
        self.play_btn.text = "Play"
        self.play_btn.icon = ft.Icons.PLAY_ARROW_ROUNDED
        self.play_btn.bgcolor = ACCENT_PRIMARY
        print(f"[BacktestView] Play stopped at candle {self.replay_index + 1}")
        if self._play_task:
            self._play_task.cancel()
            self._play_task = None
        if self.play_btn.page:
            self.play_btn.update()
        elif self.page:
            self.page.update()

    async def _auto_play_loop(self) -> None:
        """Фоновый цикл автовоспроизведения свечей."""
        try:
            while self.is_playing:
                await asyncio.sleep(1.0)
                if not self.is_playing:
                    break
                if self.replay_index >= len(self.all_candles) - 1:
                    self._stop_play()
                    break
                self._step_forward(1)
        except asyncio.CancelledError:
            pass

    def _on_reset_session(self, _) -> None:
        """Сброс сессии бэктеста к исходному состоянию."""
        self._stop_play()
        self.virtual_balance = self.initial_balance
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.active_position = None
        self.session_trades.clear()
        self.replay_index = 35
        self._update_all_views()
        if self.page:
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("Сессия бэктеста сброшена ($10,000 баланс)"), bgcolor=ACCENT_PRIMARY))

    def _execute_order(self, direction: str) -> None:
        """Открытие рыночной позиции LONG или SHORT с установкой SL и TP."""
        if not self.all_candles:
            return

        current_candle = self.all_candles[self.replay_index]
        current_price = current_candle["close"]

        try:
            vol = float(self.volume_field.value.replace(",", "."))
        except (ValueError, AttributeError):
            vol = 1.0

        if vol <= 0:
            return

        try:
            sl_pct = float((self.sl_field.value or "1.5").replace(",", "."))
        except (ValueError, AttributeError):
            sl_pct = 1.5

        try:
            tp_pct = float((self.tp_field.value or "3.0").replace(",", "."))
        except (ValueError, AttributeError):
            tp_pct = 3.0

        if direction == "LONG":
            sl_price = round(current_price * (1.0 - sl_pct / 100.0), 2)
            tp_price = round(current_price * (1.0 + tp_pct / 100.0), 2)
        else:
            sl_price = round(current_price * (1.0 + sl_pct / 100.0), 2)
            tp_price = round(current_price * (1.0 - tp_pct / 100.0), 2)

        # Если уже была открыта противоположная позиция, сначала закрываем ее
        if self.active_position:
            self._close_current_position(silent=True)

        self.active_position = {
            "symbol": self.selected_symbol,
            "direction": direction,
            "entry_price": current_price,
            "volume": vol,
            "entry_step": self.replay_index,
            "opened_at": current_candle["timestamp"],
            "stop_loss": sl_price,
            "take_profit": tp_price,
        }

        self._update_unrealized_pnl()
        self._update_all_views()

        if self.page:
            col = PROFIT if direction == "LONG" else LOSS
            self.page.show_snack_bar(
                ft.SnackBar(
                    content=ft.Text(f"Исполнен {direction} {vol} {self.selected_symbol} @ ${current_price:,.2f} [SL: ${sl_price:,.2f} | TP: ${tp_price:,.2f}]"),
                    bgcolor=col,
                )
            )

    def _close_current_position(self, silent: bool = False, exit_price: Optional[float] = None, reason: str = "Market") -> None:
        """Закрытие открытой позиции и фиксация результата."""
        if not self.active_position:
            return

        current_candle = self.all_candles[self.replay_index]
        if exit_price is None:
            exit_price = current_candle["close"]
        pos = self.active_position

        dir_mult = 1.0 if pos["direction"] == "LONG" else -1.0
        gross = round((exit_price - pos["entry_price"]) * pos["volume"] * dir_mult, 2)
        comm = round(exit_price * pos["volume"] * 0.0006, 2)
        net = round(gross - comm, 2)

        self.virtual_balance += net
        self.realized_pnl += net
        self.unrealized_pnl = 0.0

        trade_record = {
            "id": len(self.session_trades) + 1,
            "symbol": pos["symbol"],
            "direction": pos["direction"],
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "volume": pos["volume"],
            "gross_pnl": gross,
            "commission": comm,
            "net_pnl": net,
            "opened_at": pos["opened_at"],
            "closed_at": current_candle["timestamp"],
            "steps": self.replay_index - pos["entry_step"],
            "exit_reason": reason,
        }
        self.session_trades.insert(0, trade_record)
        self.active_position = None

        self._update_all_views()

        if not silent and self.page:
            col = PROFIT if net >= 0 else LOSS
            sign = "+" if net >= 0 else ""
            if reason in ["Take-Profit", "Stop-Loss"]:
                notify_text = f"🎯 Сработал {reason}: {sign}${net:,.2f}!" if reason == "Take-Profit" else f"🛑 Сработал {reason}: {sign}${net:,.2f}"
            else:
                notify_text = f"Позиция закрыта: {sign}${net:,.2f}"
            self.page.show_snack_bar(
                ft.SnackBar(
                    content=ft.Text(notify_text, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                    bgcolor=col,
                )
            )

    def _update_unrealized_pnl(self) -> None:
        """Пересчитывает плавающий P&L на текущей свече."""
        if not self.active_position or not self.all_candles:
            self.unrealized_pnl = 0.0
            return

        curr_price = self.all_candles[self.replay_index]["close"]
        pos = self.active_position
        dir_mult = 1.0 if pos["direction"] == "LONG" else -1.0
        self.unrealized_pnl = round((curr_price - pos["entry_price"]) * pos["volume"] * dir_mult, 2)

    def _update_all_views(self) -> None:
        """Перерисовывает график, метрики и журнал сделок сессии."""
        if not self.all_candles:
            return

        current_candle = self.all_candles[self.replay_index]
        curr_price = current_candle["close"]

        # Обновление счетчиков
        self.candle_counter_text.value = f"Свеча: {self.replay_index + 1} / {len(self.all_candles)}"
        self.current_price_text.value = f"Цена: ${curr_price:,.2f}"

        # Метрики баланса
        self.balance_text.value = f"${self.virtual_balance + self.unrealized_pnl:,.2f}"
        if self.virtual_balance + self.unrealized_pnl >= self.initial_balance:
            self.balance_text.color = PROFIT
        else:
            self.balance_text.color = LOSS

        # Плавающий P&L
        un_sign = "+" if self.unrealized_pnl > 0 else ""
        self.unrealized_text.value = f"{un_sign}${self.unrealized_pnl:,.2f}"
        self.unrealized_text.color = PROFIT if self.unrealized_pnl > 0 else (LOSS if self.unrealized_pnl < 0 else TEXT_MUTED)

        # Закрытый P&L
        rl_sign = "+" if self.realized_pnl > 0 else ""
        self.realized_text.value = f"{rl_sign}${self.realized_pnl:,.2f}"
        self.realized_text.color = PROFIT if self.realized_pnl > 0 else (LOSS if self.realized_pnl < 0 else TEXT_MUTED)

        # Винрейт
        if self.session_trades:
            wins = len([t for t in self.session_trades if t["net_pnl"] > 0])
            total_cnt = len(self.session_trades)
            wr = round(wins / total_cnt * 100.0, 1) if total_cnt > 0 else 0.0
            self.winrate_text.value = f"{wr:.1f}%"
            self.winrate_subtext.value = f"{wins} из {total_cnt} прибыльных"
            self.winrate_text.color = PROFIT if wr >= 50 else LOSS
        else:
            self.winrate_text.value = "0.0%"
            self.winrate_subtext.value = "0 из 0 прибыльных"
            self.winrate_text.color = TEXT_MUTED

        # Баннер позиции
        if self.active_position:
            pos = self.active_position
            pnl_col = PROFIT if self.unrealized_pnl >= 0 else LOSS
            sign = "+" if self.unrealized_pnl >= 0 else ""
            self.position_status_banner.content = ft.Row(
                [
                    ft.Text(f"ПОЗИЦИЯ {pos['direction']}", size=11, weight=ft.FontWeight.BOLD, color=PROFIT if pos['direction'] == "LONG" else LOSS, font_family=FONT_MONO),
                    ft.Text(f"@ ${pos['entry_price']:,.2f}", size=11, color=TEXT_PRIMARY, font_family=FONT_MONO),
                    ft.Text(f"PnL: {sign}${self.unrealized_pnl:,.2f}", size=11, weight=ft.FontWeight.BOLD, color=pnl_col, font_family=FONT_MONO),
                ],
                spacing=6,
            )
            self.position_status_banner.border = ft.border.all(1, ft.Colors.with_opacity(0.6, pnl_col))
        else:
            self.position_status_banner.content = ft.Text("ВНЕ ПОЗИЦИИ (FLAT)", size=11, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO)
            self.position_status_banner.border = ft.border.all(1, BORDER_SUBTLE)

        # Отрисовка свечного графика с отсечкой будущего
        visible_candles = self.all_candles[: self.replay_index + 1]
        try:
            self._render_chart(visible_candles)
        except Exception as ex:
            print(f"[BacktestView] Error rendering chart: {ex}")

        # Отрисовка журнала сделок сессии
        try:
            self._render_session_trades()
        except Exception as ex:
            print(f"[BacktestView] Error rendering session trades: {ex}")

        if self.page:
            try:
                self.page.update()
            except Exception:
                pass

    def did_mount(self):
        super().did_mount()
        print("[BacktestView] did_mount: initializing view and rendering candles...")
        self._update_all_views()

    def refresh(self) -> None:
        """Публичный метод обновления бэктеста при смене экранов."""
        print("[BacktestView] Refresh called from layout/router.")
        if not self.all_candles:
            self._load_market_candles()
        self._update_all_views()
        if self.page:
            try:
                self.page.update()
            except Exception:
                pass

    def _render_chart(self, candles: List[Dict[str, Any]]) -> None:
        """
        Отрисовывает настоящие японские свечи (Candlestick Canvas)
        с телами, фитилями, шкалой цен справа, пунктирной сеткой
        и линией открытой позиции в стиле TradingView.
        """
        if not candles:
            self.chart_canvas.shapes = [
                cv.Text(
                    x=320,
                    y=160,
                    text="Нет данных для отображения свечей",
                    style=ft.TextStyle(size=14, color="#64748B", font_family=FONT_MONO),
                )
            ]
            return

        # Видимое окно: последние 60 свечей для оптимальной читаемости
        window_size = 60
        window = candles[-window_size:] if len(candles) > window_size else candles
        num_bars = len(window)

        # Геометрия графика (адаптивная ширина под экран)
        win_w = 980
        if self.page and hasattr(self.page, "width") and self.page.width:
            win_w = max(int(self.page.width) - 260, 750)
        elif self.page and self.page.window and self.page.window.width:
            win_w = max(int(self.page.window.width) - 260, 750)
        elif self._page_ref and hasattr(self._page_ref, "width") and self._page_ref.width:
            win_w = max(int(self._page_ref.width) - 260, 750)
        elif self._page_ref and hasattr(self._page_ref, "window") and self._page_ref.window and self._page_ref.window.width:
            win_w = max(int(self._page_ref.window.width) - 260, 750)

        canvas_w = win_w
        canvas_h = 320
        right_scale_w = 80
        top_pad = 12
        bottom_pad = 20
        left_pad = 12

        plot_w = max(canvas_w - left_pad - right_scale_w, 200)
        plot_h = max(canvas_h - top_pad - bottom_pad, 100)

        # Диапазон цен
        min_p = min(c["low"] for c in window)
        max_p = max(c["high"] for c in window)
        if min_p == max_p:
            min_p -= 1.0
            max_p += 1.0

        p_span = max_p - min_p
        min_p -= p_span * 0.05
        max_p += p_span * 0.05
        p_span = max_p - min_p

        def price_to_y(price: float) -> float:
            ratio = (price - min_p) / p_span
            return top_pad + plot_h - (ratio * plot_h)

        slot_w = plot_w / max(num_bars, 1)
        body_w = max(slot_w * 0.72, 3.0)

        shapes: List[cv.Shape] = []

        # 1. Фоновая горизонтальная пунктирная сетка и шкала цен справа
        num_grid_lines = 5
        for i in range(num_grid_lines):
            grid_price = min_p + (p_span * (i + 0.5) / num_grid_lines)
            y_line = price_to_y(grid_price)

            # Пунктирная линия сетки
            shapes.append(
                cv.Line(
                    x1=left_pad,
                    y1=y_line,
                    x2=left_pad + plot_w,
                    y2=y_line,
                    paint=ft.Paint(
                        color="#1E2333",
                        stroke_width=1.0,
                        stroke_dash_pattern=[4, 4],
                        style=ft.PaintingStyle.STROKE,
                    ),
                )
            )

            # Метка цены на правой шкале
            p_text = f"${grid_price:,.2f}" if grid_price >= 100 else f"${grid_price:,.4f}"
            shapes.append(
                cv.Text(
                    x=left_pad + plot_w + 8,
                    y=y_line - 6,
                    text=p_text,
                    style=ft.TextStyle(size=10, color="#64748B", font_family=FONT_MONO),
                )
            )

        # 2. Отрисовка японских свечей (фитили и тела)
        for i, c in enumerate(window):
            cx = left_pad + i * slot_w + (slot_w / 2.0)
            is_bull = c["close"] >= c["open"]
            c_color = "#10B981" if is_bull else "#EF4444"

            y_high = price_to_y(c["high"])
            y_low = price_to_y(c["low"])
            y_open = price_to_y(c["open"])
            y_close = price_to_y(c["close"])

            # Фитиль (High to Low)
            shapes.append(
                cv.Line(
                    x1=cx,
                    y1=y_high,
                    x2=cx,
                    y2=y_low,
                    paint=ft.Paint(color=c_color, stroke_width=1.5, style=ft.PaintingStyle.STROKE),
                )
            )

            # Тело свечи (Open to Close)
            body_top = min(y_open, y_close)
            body_bottom = max(y_open, y_close)
            body_h = max(body_bottom - body_top, 2.0)  # Мин 2px для доджи
            body_x = cx - (body_w / 2.0)

            shapes.append(
                cv.Rect(
                    x=body_x,
                    y=body_top,
                    width=body_w,
                    height=body_h,
                    border_radius=1,
                    paint=ft.Paint(color=c_color, style=ft.PaintingStyle.FILL),
                )
            )

        # 3. Скользящая средняя EMA 20 (тонкая голубая линия поверх свечей)
        all_closes = [c["close"] for c in candles]
        ema_mult = 2.0 / (20 + 1)
        ema_full = []
        if len(all_closes) >= 20:
            curr_ema = sum(all_closes[:20]) / 20.0
            ema_full.append(curr_ema)
            for p in all_closes[20:]:
                curr_ema = (p - curr_ema) * ema_mult + curr_ema
                ema_full.append(curr_ema)
            win_ema = ema_full[-num_bars:]
        else:
            win_ema = [c["close"] for c in window]

        for i in range(1, len(win_ema)):
            cx1 = left_pad + (i - 1) * slot_w + (slot_w / 2.0)
            cy1 = price_to_y(win_ema[i - 1])
            cx2 = left_pad + i * slot_w + (slot_w / 2.0)
            cy2 = price_to_y(win_ema[i])
            shapes.append(
                cv.Line(
                    x1=cx1,
                    y1=cy1,
                    x2=cx2,
                    y2=cy2,
                    paint=ft.Paint(color="#38BDF8", stroke_width=1.4, style=ft.PaintingStyle.STROKE),
                )
            )

        # 4. Линия текущей цены (Close последней свечи) с бейджем на правой оси
        last_candle = window[-1]
        curr_price = last_candle["close"]
        curr_y = price_to_y(curr_price)
        curr_is_bull = last_candle["close"] >= last_candle["open"]
        curr_color = "#10B981" if curr_is_bull else "#EF4444"

        shapes.append(
            cv.Line(
                x1=left_pad,
                y1=curr_y,
                x2=left_pad + plot_w + 6,
                y2=curr_y,
                paint=ft.Paint(
                    color=curr_color,
                    stroke_width=1.2,
                    stroke_dash_pattern=[3, 3],
                    style=ft.PaintingStyle.STROKE,
                ),
            )
        )
        badge_p_str = f"${curr_price:,.2f}" if curr_price >= 100 else f"${curr_price:,.4f}"
        shapes.append(
            cv.Rect(
                x=left_pad + plot_w + 6,
                y=curr_y - 9,
                width=72,
                height=18,
                border_radius=3,
                paint=ft.Paint(color=curr_color, style=ft.PaintingStyle.FILL),
            )
        )
        shapes.append(
            cv.Text(
                x=left_pad + plot_w + 10,
                y=curr_y - 7,
                text=badge_p_str,
                style=ft.TextStyle(size=10, weight=ft.FontWeight.BOLD, color="#FFFFFF", font_family=FONT_MONO),
            )
        )

        # 5. Линия открытой позиции (Entry, SL, TP)
        if self.active_position:
            pos_entry = self.active_position["entry_price"]
            pos_dir = self.active_position["direction"]
            pos_col = "#38BDF8" if pos_dir == "LONG" else "#F59E0B"
            pos_y = price_to_y(pos_entry)

            shapes.append(
                cv.Line(
                    x1=left_pad,
                    y1=pos_y,
                    x2=left_pad + plot_w + 6,
                    y2=pos_y,
                    paint=ft.Paint(
                        color=pos_col,
                        stroke_width=1.5,
                        stroke_dash_pattern=[5, 3],
                        style=ft.PaintingStyle.STROKE,
                    ),
                )
            )

            sign = "+" if self.unrealized_pnl >= 0 else ""
            pos_label = f"ENTRY {pos_dir} @ ${pos_entry:,.2f}  |  PnL: {sign}${self.unrealized_pnl:,.2f}"
            shapes.append(
                cv.Rect(
                    x=left_pad + 6,
                    y=pos_y - 12,
                    width=230,
                    height=22,
                    border_radius=4,
                    paint=ft.Paint(color="#12151E", style=ft.PaintingStyle.FILL),
                )
            )
            shapes.append(
                cv.Rect(
                    x=left_pad + 6,
                    y=pos_y - 12,
                    width=230,
                    height=22,
                    border_radius=4,
                    paint=ft.Paint(color=pos_col, stroke_width=1.0, style=ft.PaintingStyle.STROKE),
                )
            )
            shapes.append(
                cv.Text(
                    x=left_pad + 12,
                    y=pos_y - 8,
                    text=pos_label,
                    style=ft.TextStyle(size=10, weight=ft.FontWeight.BOLD, color=pos_col, font_family=FONT_MONO),
                )
            )

            # Пунктир Stop-Loss
            sl_val = self.active_position.get("stop_loss")
            if sl_val:
                sl_y = price_to_y(sl_val)
                shapes.append(
                    cv.Line(
                        x1=left_pad,
                        y1=sl_y,
                        x2=left_pad + plot_w,
                        y2=sl_y,
                        paint=ft.Paint(color="#EF4444", stroke_width=1.2, stroke_dash_pattern=[4, 3], style=ft.PaintingStyle.STROKE),
                    )
                )
                shapes.append(
                    cv.Text(
                        x=left_pad + 6,
                        y=sl_y - 12,
                        text=f"SL: ${sl_val:,.2f}",
                        style=ft.TextStyle(size=9, weight=ft.FontWeight.BOLD, color="#EF4444", font_family=FONT_MONO),
                    )
                )

            # Пунктир Take-Profit
            tp_val = self.active_position.get("take_profit")
            if tp_val:
                tp_y = price_to_y(tp_val)
                shapes.append(
                    cv.Line(
                        x1=left_pad,
                        y1=tp_y,
                        x2=left_pad + plot_w,
                        y2=tp_y,
                        paint=ft.Paint(color="#10B981", stroke_width=1.2, stroke_dash_pattern=[4, 3], style=ft.PaintingStyle.STROKE),
                    )
                )
                shapes.append(
                    cv.Text(
                        x=left_pad + 6,
                        y=tp_y - 12,
                        text=f"TP: ${tp_val:,.2f}",
                        style=ft.TextStyle(size=9, weight=ft.FontWeight.BOLD, color="#10B981", font_family=FONT_MONO),
                    )
                )

        self.chart_canvas.shapes = shapes

        # 5. Обновление информационной строки OHLCV в стиле TradingView
        pct_change = ((last_candle["close"] - last_candle["open"]) / last_candle["open"]) * 100.0 if last_candle["open"] > 0 else 0.0
        chg_sign = "+" if pct_change >= 0 else ""
        chg_col = "#10B981" if pct_change >= 0 else "#EF4444"
        vol_val = last_candle.get("volume", 142.5)

        self.ohlcv_info_bar.controls = [
            ft.Text(f"{self.selected_symbol} • {self.selected_timeframe}", size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
            ft.Text("O:", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
            ft.Text(f"{last_candle['open']:,.2f}", size=11, color=chg_col, font_family=FONT_MONO),
            ft.Text("H:", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
            ft.Text(f"{last_candle['high']:,.2f}", size=11, color=chg_col, font_family=FONT_MONO),
            ft.Text("L:", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
            ft.Text(f"{last_candle['low']:,.2f}", size=11, color=chg_col, font_family=FONT_MONO),
            ft.Text("C:", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
            ft.Text(f"{last_candle['close']:,.2f}", size=11, weight=ft.FontWeight.BOLD, color=chg_col, font_family=FONT_MONO),
            ft.Container(
                content=ft.Text(f"({chg_sign}{pct_change:.2f}%)", size=10, weight=ft.FontWeight.BOLD, color=chg_col, font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.14, chg_col),
                padding=ft.padding.symmetric(horizontal=6, vertical=1),
                border_radius=4,
            ),
            ft.Text(f"Vol: {vol_val:,.1f}", size=11, color=TEXT_SECONDARY, font_family=FONT_MONO),
        ]

    def _render_session_trades(self) -> None:
        """Отрисовывает закрытые сделки текущей сессии бэктеста."""
        self.trades_listview.controls.clear()

        if not self.session_trades:
            self.trades_listview.controls.append(
                ft.Container(
                    content=ft.Text("Сделок в текущей сессии еще не совершено. Нажмите [BUY] или [SELL] для входа.", color=TEXT_MUTED, size=12),
                    alignment=ft.alignment.center,
                    padding=20,
                )
            )
            return

        for t in self.session_trades:
            is_win = t["net_pnl"] >= 0
            pnl_col = PROFIT if is_win else LOSS
            sign = "+" if is_win else ""
            gross_val = t.get("gross_pnl", t["net_pnl"] + t.get("commission", 0.0))
            gross_sign = "+" if gross_val >= 0 else ""
            reason = t.get("exit_reason", "Market")
            reason_col = PROFIT if reason == "Take-Profit" else (LOSS if reason == "Stop-Loss" else ACCENT_SECONDARY)

            row = ft.Container(
                content=ft.Row(
                    [
                        ft.Row(
                            [
                                ft.Container(
                                    content=ft.Text(t["direction"], size=10, weight=ft.FontWeight.BOLD, color=PROFIT if t["direction"] == "LONG" else LOSS, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.15, PROFIT if t["direction"] == "LONG" else LOSS),
                                    padding=ft.padding.symmetric(horizontal=8, vertical=3),
                                    border_radius=4,
                                ),
                                ft.Text(t["symbol"], size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                                ft.Container(
                                    content=ft.Text(reason, size=9, weight=ft.FontWeight.BOLD, color=reason_col, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, reason_col),
                                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                    border_radius=4,
                                    border=ft.border.all(1, ft.Colors.with_opacity(0.3, reason_col)),
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Text(f"Вход: ${t['entry_price']:,.2f}", size=11, color=TEXT_SECONDARY, font_family=FONT_MONO),
                        ft.Text(f"Выход: ${t['exit_price']:,.2f}", size=11, color=TEXT_SECONDARY, font_family=FONT_MONO),
                        ft.Text(f"Объем: {t['volume']} ({t['steps']} св.)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                        ft.Text(f"Gross: {gross_sign}${gross_val:,.2f}", size=11, color=TEXT_SECONDARY, font_family=FONT_MONO),
                        ft.Text(f"Fee: ${t.get('commission', 0.0):.2f}", size=11, color=WARNING_TILT, font_family=FONT_MONO),
                        ft.Text(f"Net: {sign}${t['net_pnl']:,.2f}", size=12, weight=ft.FontWeight.BOLD, color=pnl_col, font_family=FONT_MONO),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=ft.padding.symmetric(horizontal=12, vertical=6),
                bgcolor=SURFACE_2,
                border_radius=8,
                border=ft.border.all(1, BORDER_SUBTLE),
            )
            self.trades_listview.controls.append(row)
