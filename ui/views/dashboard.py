"""
ui/views/dashboard.py
Экран аналитического дашборда Trading Journal Pro в стиле Dark Premium Terminal.
Включает:
- Hero-карточку Net PnL с глубоким градиентом, бейджем Dual-Channel Accessibility и Live Metric Counter.
- Интерактивную сетку ключевых метрик с hover-эффектом и микро-спарклайнами.
- Карточку брокерских издержек (Fee Drag).
- Скелетон-заглушки загрузки.
- Живой интерактивный график Equity Curve с тумблером What-If фильтрации тильта.
- Интегрированный P&L Календарь и квантовый веер симуляции Монте-Карло (10 000 итераций).
"""

from datetime import date
import logging
import threading
import time
from typing import Any, Callable, List, Optional
import flet as ft

from analytics import AnalyticsService, DashboardMetrics
from database import DatabaseManager, Trade
from ui.components.pnl_calendar import PnLCalendar
from ui.components.time_heatmap import TimeHeatmap
from ui.theme import (
    ACCENT_PRIMARY,
    ACCENT_SECONDARY,
    ANIM_FAST_MS,
    ANIMATIONS_ENABLED,
    BG_APP,
    BG_SURFACE,
    BORDER_COLOR,
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
    SURFACE_3,
    SURFACE_OVERLAY,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING_TILT,
    create_neon_box_shadow,
    get_animation,
)

# Обратная совместимость для внешних импортов
TradingMetrics = DashboardMetrics


def create_sparkline(data_points_y: List[float], color: str) -> ft.Container:
    """Создает крошечный спарклайн-график без осей для карточки метрики."""
    if len(data_points_y) < 2:
        data_points_y = [data_points_y[0] if data_points_y else 0.0, data_points_y[0] if data_points_y else 0.0]

    min_val = min(data_points_y)
    max_val = max(data_points_y)
    padding = max(abs(max_val - min_val) * 0.2, 0.5)

    points = [ft.LineChartDataPoint(i, val) for i, val in enumerate(data_points_y)]

    chart = ft.LineChart(
        data_series=[
            ft.LineChartData(
                data_points=points,
                stroke_width=2,
                color=color,
                curved=True,
                stroke_cap_round=True,
                below_line_gradient=ft.LinearGradient(
                    begin=ft.alignment.top_center,
                    end=ft.alignment.bottom_center,
                    colors=[ft.Colors.with_opacity(0.24, color), ft.Colors.with_opacity(0.0, color)],
                ),
            )
        ],
        border=None,
        horizontal_grid_lines=ft.ChartGridLines(width=0),
        vertical_grid_lines=ft.ChartGridLines(width=0),
        left_axis=ft.ChartAxis(visible=False),
        bottom_axis=ft.ChartAxis(visible=False),
        min_y=min_val - padding,
        max_y=max_val + padding,
        height=26,
        expand=True,
    )
    return ft.Container(content=chart, height=26, padding=ft.padding.only(top=4))


class DashboardView(ft.Container):
    """
    Главный аналитический экран с микро-интерактивностью и квантовым веером Монте-Карло.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        on_open_plotly: Callable[[], None],
        on_date_selected: Optional[Callable[[date], None]] = None,
        page: Optional[ft.Page] = None,
    ):
        super().__init__(expand=True)
        self.db = db_manager
        self.on_open_plotly = on_open_plotly
        self.on_date_selected = on_date_selected
        self._page_ref = page
        self.current_account_id: Optional[int] = None

        self.metrics_grid = ft.ResponsiveRow(spacing=12, run_spacing=12)
        self.chart_container = ft.Container(expand=True)
        self.monte_carlo_container = ft.Container()
        self.session_matrix_container = ft.Container()
        self.strategy_leaderboard_container = ft.Container()
        self.duration_analysis_container = ft.Container()
        self.asset_allocation_container = ft.Container()
        self.psychology_matrix_container = ft.Container()
        self.drawdown_recovery_container = ft.Container()
        self.excursion_matrix_container = ft.Container()
        self.monthly_phase_container = ft.Container()
        self.sizing_simulator_container = ft.Container()
        self.market_regime_container = ft.Container()
        self.r_distribution_container = ft.Container()
        self.rr_efficiency_container = ft.Container()
        self.rule_violation_container = ft.Container()
        self.mtf_alignment_container = ft.Container()
        self.compliance_routine_container = ft.Container()
        self.session_overlap_container = ft.Container()
        self.setup_grading_container = ft.Container()
        self.tag_attribution_container = ft.Container()
        self.rolling_edge_container = ft.Container()
        self.prop_consistency_container = ft.Container()
        self.order_placement_container = ft.Container()
        self.factor_ic_container = ft.Container()
        self.trade_management_container = ft.Container()
        self.liquidity_sweep_container = ft.Container()
        self.broker_cost_drag_container = ft.Container()
        self.pnl_calendar = PnLCalendar(on_date_selected=self.on_date_selected)
        self.time_heatmap = TimeHeatmap()

        # Модульная навигация аналитического хаба (Analytics Hub)
        self.active_category: str = "sessions"
        self.category_tabs_row = ft.Row(spacing=8, scroll=ft.ScrollMode.ADAPTIVE)
        self.category_search_input = ft.TextField(
            hint_text="Поиск модуля (тильт, сессия, IC, ордера, ликвидность...)",
            hint_style=ft.TextStyle(size=12, color=TEXT_MUTED, font_family=FONT_FAMILY),
            text_style=ft.TextStyle(size=12, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
            prefix_icon=ft.Icons.SEARCH_ROUNDED,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            dense=True,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border_radius=RADIUS_MD,
            bgcolor=SURFACE_1,
            width=320,
            on_change=self._on_search_change,
        )
        self.category_modules_column = ft.Column(spacing=10)

        # Переключатель тильт-фильтра
        self.tilt_switch = ft.Switch(
            label="Отфильтровать тильт",
            label_style=ft.TextStyle(font_family=FONT_FAMILY, size=12, color=TEXT_SECONDARY),
            value=False,
            active_color=WARNING_TILT,
            tooltip="Исключает из расчетов эмоциональные сделки с нарушением риск-менеджмента",
            on_change=self._on_tilt_toggle,
        )
        self.tilt_badge = ft.Container(
            content=ft.Text("OFF", size=10, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO),
            bgcolor=SURFACE_2,
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
        )

        self.content = self._build_layout()
        self.refresh()

    @property
    def host_page(self) -> Optional[ft.Page]:
        try:
            return self.page or getattr(self, "_page_ref", None)
        except Exception:
            return getattr(self, "_page_ref", None)

    def _build_layout(self) -> ft.Control:
        header = ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text("Аналитический дашборд", size=22, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                        ft.Text("Метрики эффективности, динамика капитала и симуляция риска Монте-Карло", size=13, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                    ],
                    spacing=2,
                ),
                ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.PSYCHOLOGY_ROUNDED, size=16, color="#A855F7"),
                                    ft.Text("AI Анализ (Quant Coach)", size=12, color=TEXT_PRIMARY, weight=ft.FontWeight.W_600, font_family=FONT_FAMILY),
                                ],
                                spacing=8,
                            ),
                            bgcolor=SURFACE_2,
                            border_radius=RADIUS_MD,
                            border=ft.border.all(1, ft.Colors.with_opacity(0.35, "#A855F7")),
                            padding=ft.padding.symmetric(horizontal=12, vertical=8),
                            ink=True,
                            on_click=lambda _: self._open_ai_coach_modal(),
                            tooltip="Открыть персональные AI & Quant рекомендации по вашей торговле",
                        ),
                        ft.Container(
                            content=ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.INSIGHTS_ROUNDED, size=16, color=ACCENT_SECONDARY),
                                    ft.Text("Интерактивный Plotly", size=12, color=TEXT_PRIMARY, weight=ft.FontWeight.W_600, font_family=FONT_FAMILY),
                                ],
                                spacing=8,
                            ),
                            bgcolor=SURFACE_2,
                            border_radius=RADIUS_MD,
                            border=ft.border.all(1, ft.Colors.with_opacity(0.35, ACCENT_SECONDARY)),
                            padding=ft.padding.symmetric(horizontal=12, vertical=8),
                            ink=True,
                            on_click=lambda _: self.on_open_plotly(),
                            tooltip="Открыть интерактивную аналитику и кривую доходности в Plotly HTML",
                        ),
                    ],
                    spacing=10,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # Карточка графика Equity Curve
        chart_card = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.AUTO_GRAPH_ROUNDED, color=ACCENT_PRIMARY, size=20),
                                    ft.Text("Динамика капитала (Equity Curve)", size=15, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Container(
                                        content=ft.Text("LIVE INTERACTIVE", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                        bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                        border_radius=4,
                                        border=ft.border.all(1, ft.Colors.with_opacity(0.3, ACCENT_PRIMARY)),
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Row(
                                controls=[
                                    self.tilt_switch,
                                    self.tilt_badge,
                                ],
                                spacing=6,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(color=BORDER_SUBTLE, height=12),
                    self.chart_container,
                ],
                spacing=8,
            ),
            padding=20,
            bgcolor=SURFACE_1,
            border_radius=RADIUS_LG,
            height=350,
        )

        self.pnl_calendar.col = {"sm": 12, "lg": 7}
        self.monte_carlo_container.col = {"sm": 12, "lg": 5}
        calendar_and_quant = ft.ResponsiveRow(
            controls=[
                self.pnl_calendar,
                self.monte_carlo_container,
            ],
            spacing=14,
            run_spacing=14,
        )

        # Инициализация переключателя категорий и фильтра
        self._rebuild_category_tabs()
        self.category_modules_column.controls = self._get_category_controls(self.active_category, "")

        analytics_hub_bar = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.ANALYTICS_ROUNDED, color=ACCENT_PRIMARY, size=18),
                                    ft.Text("Квантовый хаб аналитики (Analytics Hub)", size=15, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Container(
                                        content=ft.Text("MODULAR", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                        bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                        border_radius=4,
                                        border=ft.border.all(1, ft.Colors.with_opacity(0.3, ACCENT_PRIMARY)),
                                    ),
                                ],
                                spacing=8,
                            ),
                            self.category_search_input,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(
                        "Модульные срезы эффективности: выберите категорию для фокусного аудита или переключитесь на полный просмотр.",
                        size=12,
                        color=TEXT_SECONDARY,
                        font_family=FONT_FAMILY,
                    ),
                    ft.Container(height=2),
                    self.category_tabs_row,
                ],
                spacing=8,
            ),
            padding=ft.padding.symmetric(horizontal=16, vertical=12),
            bgcolor=SURFACE_1,
            border_radius=RADIUS_MD,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

        return ft.Column(
            controls=[
                header,
                ft.Divider(color=BORDER_SUBTLE, height=12),
                self.metrics_grid,
                ft.Container(height=4),
                chart_card,
                ft.Container(height=4),
                calendar_and_quant,
                ft.Container(height=8),
                analytics_hub_bar,
                ft.Container(height=4),
                self.category_modules_column,
                ft.Container(height=40),  # Свободный скролл
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _rebuild_category_tabs(self) -> None:
        """Перестраивает интерактивные чипсы-вкладки категорий аналитики."""
        categories = [
            ("sessions", "⏱️ Время & Сессии", "5", ft.Icons.ACCESS_TIME_ROUNDED),
            ("psychology", "🧠 Психология & Риск", "5", ft.Icons.PSYCHOLOGY_ROUNDED),
            ("setups", "🎯 Сетапы & Альфа", "8", ft.Icons.TRACK_CHANGES_ROUNDED),
            ("execution", "⚡ Исполнение & Сделки", "7", ft.Icons.BOLT_ROUNDED),
            ("prop", "🏆 Проп-Трейдинг", "1", ft.Icons.EMOJI_EVENTS_ROUNDED),
            ("all", "📑 Все модули сразу", "26", ft.Icons.DASHBOARD_ROUNDED),
        ]

        pills = []
        for key, title, count_badge, icon in categories:
            is_active = (key == self.active_category)
            bg = ft.Colors.with_opacity(0.18, ACCENT_PRIMARY) if is_active else SURFACE_2
            border_col = ACCENT_PRIMARY if is_active else BORDER_SUBTLE
            text_col = TEXT_PRIMARY if is_active else TEXT_SECONDARY
            badge_bg = ACCENT_PRIMARY if is_active else SURFACE_3
            badge_text_col = ft.Colors.WHITE if is_active else TEXT_MUTED

            def _create_handler(cat_key=key):
                return lambda _: self._on_category_select(cat_key)

            pill = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(icon, size=15, color=ACCENT_PRIMARY if is_active else TEXT_MUTED),
                        ft.Text(title, size=12, weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.W_500, color=text_col, font_family=FONT_FAMILY),
                        ft.Container(
                            content=ft.Text(count_badge, size=9, weight=ft.FontWeight.BOLD, color=badge_text_col, font_family=FONT_MONO),
                            bgcolor=badge_bg,
                            padding=ft.padding.symmetric(horizontal=5, vertical=2),
                            border_radius=RADIUS_SM,
                        ),
                    ],
                    spacing=6,
                    tight=True,
                ),
                bgcolor=bg,
                border_radius=RADIUS_MD,
                border=ft.border.all(1.2 if is_active else 1, border_col),
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                ink=True,
                on_click=_create_handler(key),
            )
            pills.append(pill)

        self.category_tabs_row.controls = pills

    def _on_category_select(self, cat_key: str) -> None:
        self.active_category = cat_key
        self._rebuild_category_tabs()
        query = getattr(self.category_search_input, "value", "") or ""
        self.category_modules_column.controls = self._get_category_controls(self.active_category, query)
        if self.page:
            try:
                self.category_tabs_row.update()
                self.category_modules_column.update()
            except Exception:
                pass

    def _on_search_change(self, e) -> None:
        query = getattr(e.control, "value", "") or ""
        self.category_modules_column.controls = self._get_category_controls(self.active_category, query)
        if self.page:
            try:
                self.category_modules_column.update()
            except Exception:
                pass

    def _get_category_controls(self, cat_key: str, search_query: str = "") -> List[ft.Control]:
        """Возвращает список аналитических контейнеров для выбранной категории с учетом фильтрации."""
        category_map = {
            "sessions": [
                ("Матрица торговых сессий", self.session_matrix_container),
                ("Арбитраж перекрытия сессий", self.session_overlap_container),
                ("Время удержания позиций", self.duration_analysis_container),
                ("Тепловая карта времени 7x24", self.time_heatmap),
                ("Фазы месяца и сезонность", self.monthly_phase_container),
            ],
            "psychology": [
                ("Аудит психологии и дисциплины", self.psychology_matrix_container),
                ("Утечки нарушения торгового плана", self.rule_violation_container),
                ("Анализ просадки и восстановления", self.drawdown_recovery_container),
                ("Симулятор риск-менеджмента и сайзинга", self.sizing_simulator_container),
                ("Контроль дисциплины и пре-трейд рутины", self.compliance_routine_container),
            ],
            "setups": [
                ("Лидерборд стратегий и сетапов", self.strategy_leaderboard_container),
                ("Грейдинг качества сетапов (A+/B/C)", self.setup_grading_container),
                ("Снятие ликвидности & Footprint Order Flow", self.liquidity_sweep_container),
                ("Облако факторных тегов", self.tag_attribution_container),
                ("Предсказательная сила факторов (IC)", self.factor_ic_container),
                ("Согласованность с рыночным режимом", self.market_regime_container),
                ("Мульти-таймфрейм согласованность (MTF)", self.mtf_alignment_container),
                ("Аллокация по активам и концентрация", self.asset_allocation_container),
            ],
            "execution": [
                ("Аудит управления позицией (BE & Trailing)", self.trade_management_container),
                ("Эффективность расстановки SL и TP", self.order_placement_container),
                ("Матрица экскурсий MAE / MFE", self.excursion_matrix_container),
                ("Распределение исходов R-Multiple", self.r_distribution_container),
                ("Кривая эффективности Риск/Прибыль", self.rr_efficiency_container),
                ("Скользящий 30-дневный импульс эджа", self.rolling_edge_container),
                ("Аудит комиссий и издержек брокера", self.broker_cost_drag_container),
            ],
            "prop": [
                ("Радар соответствия правилам проп-фирм", self.prop_consistency_container),
            ],
        }

        q = (search_query or "").strip().lower()
        controls = []

        if cat_key == "all":
            for cat_id, items in category_map.items():
                for title, ctrl in items:
                    if not q or q in title.lower():
                        controls.append(ctrl)
                        controls.append(ft.Container(height=4))
        else:
            items = category_map.get(cat_key, [])
            for title, ctrl in items:
                if not q or q in title.lower():
                    controls.append(ctrl)
                    controls.append(ft.Container(height=4))

        if not controls:
            controls.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.SEARCH_OFF_ROUNDED, size=38, color=TEXT_MUTED),
                            ft.Text(f"Модулей по запросу «{search_query}» не найдено", size=14, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ft.Text("Попробуйте сбросить поиск или переключиться на вкладку «Все модули»", size=12, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=6,
                    ),
                    padding=36,
                    alignment=ft.alignment.center,
                )
            )

        return controls

    def _build_skeleton_grid(self) -> List[ft.Control]:
        """Возвращает заглушки-скелетоны для индикации плавной загрузки дашборда."""
        return [
            ft.Container(self._build_skeleton_card(height=110), col={"sm": 12, "md": 6, "lg": 3}),
            ft.Container(self._build_skeleton_card(height=110), col={"sm": 6, "md": 4, "lg": 1.8}),
            ft.Container(self._build_skeleton_card(height=110), col={"sm": 6, "md": 4, "lg": 1.7}),
            ft.Container(self._build_skeleton_card(height=110), col={"sm": 6, "md": 4, "lg": 1.4}),
            ft.Container(self._build_skeleton_card(height=110), col={"sm": 6, "md": 4, "lg": 1.6}),
            ft.Container(self._build_skeleton_card(height=110), col={"sm": 12, "md": 6, "lg": 2.5}),
        ]

    def _build_skeleton_card(self, height: int = 110) -> ft.Container:
        """Создает отдельную карточку-скелетон со сдержанными слоями."""
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(width=76, height=12, border_radius=4, bgcolor=SURFACE_3),
                    ft.Container(width=130, height=24, border_radius=6, bgcolor=SURFACE_2),
                    ft.Container(width=90, height=10, border_radius=4, bgcolor=SURFACE_3),
                ],
                spacing=10,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            padding=16,
            height=height,
            bgcolor=SURFACE_1,
            border_radius=RADIUS_MD,
        )

    def _build_hero_card(self, metrics: DashboardMetrics, is_tilt_filtered: bool) -> ft.Container:
        """Создает доминирующую Hero-карточку Net PnL с глубоким градиентом, бейджем доступности и Live Counter."""
        is_positive = metrics.net_pnl >= 0
        accent = PROFIT if is_positive else LOSS
        sign_symbol = "+" if is_positive else "-"

        gradient_colors = ["#0A261D", SURFACE_1] if is_positive else ["#260D12", SURFACE_1]

        badge_text = "WHAT-IF (NO TILT)" if is_tilt_filtered else "PORTFOLIO"
        badge_color = "#38BDF8" if is_tilt_filtered else accent

        if is_tilt_filtered and metrics.tilt_loss_amount > 0:
            subtitle_text = f"+${metrics.tilt_loss_amount:,.2f} без тильта! (отсеяно {metrics.tilt_trades_count} сд.)"
            accent = "#38BDF8"
            gradient_colors = ["#0C2538", SURFACE_1]
        else:
            subtitle_text = f"Gross Profit: +${metrics.gross_profit:,.1f} | Gross Loss: -${metrics.gross_loss:,.1f}"

        pnl_val_text = ft.Text(
            f"{sign_symbol}${abs(metrics.net_pnl):,.2f}",
            size=24,
            color=accent,
            weight=ft.FontWeight.BOLD,
            font_family=FONT_MONO,
        )

        # Плавный Live Metric Counter (небольшое число шагов, обновление ТОЛЬКО pnl_val_text.update())
        if ANIMATIONS_ENABLED:
            def _animate_counter():
                steps = 4
                target = metrics.net_pnl
                start = target * 0.75 if target != 0 else 0
                for i in range(1, steps + 1):
                    val = start + (target - start) * (i / steps)
                    sign = "+" if val >= 0 else "-"
                    pnl_val_text.value = f"{sign}${abs(val):,.2f}"
                    try:
                        pnl_val_text.update()
                    except Exception:
                        break
                    time.sleep(0.02)
            threading.Thread(target=_animate_counter, daemon=True).start()

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("Чистый результат (Net PnL)", size=12, color=TEXT_SECONDARY, weight=ft.FontWeight.W_500, font_family=FONT_FAMILY),
                            ft.Container(
                                content=ft.Text(badge_text, size=9, weight=ft.FontWeight.BOLD, color=badge_color, font_family=FONT_MONO),
                                bgcolor=ft.Colors.with_opacity(0.16, badge_color),
                                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                border_radius=4,
                                border=ft.border.all(1, ft.Colors.with_opacity(0.3, badge_color)),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    pnl_val_text,
                    ft.Text(
                        subtitle_text,
                        size=11,
                        color=TEXT_MUTED,
                        font_family=FONT_MONO,
                    ),
                ],
                spacing=4,
            ),
            gradient=ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=gradient_colors,
            ),
            padding=16,
            border_radius=RADIUS_MD,
            border=ft.border.all(1.2, ft.Colors.with_opacity(0.45, accent)),
            shadow=create_neon_box_shadow(accent, blur=18, opacity=0.22),
            expand=True,
        )

    def _build_metric_card(
        self,
        title: str,
        value: str,
        subtitle: str = "",
        tag: Optional[str] = None,
        val_color: str = TEXT_PRIMARY,
        sparkline_data: Optional[List[float]] = None,
        has_glow: bool = False,
        is_placeholder: bool = False,
    ) -> ft.Container:
        """Создает карточку метрики с моноширинными лейблами, легким ховером и опциональным свечением."""
        header_controls = [
            ft.Text(title, size=12, color=TEXT_SECONDARY, weight=ft.FontWeight.W_500, font_family=FONT_FAMILY),
        ]
        if tag:
            t_color = ACCENT_PRIMARY if is_placeholder else ACCENT_SECONDARY
            header_controls.append(
                ft.Container(
                    content=ft.Text(tag, size=9, weight=ft.FontWeight.BOLD, color=t_color, font_family=FONT_MONO),
                    bgcolor=ft.Colors.with_opacity(0.14, t_color),
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    border_radius=4,
                    border=ft.border.all(1, ft.Colors.with_opacity(0.3, t_color)),
                )
            )

        column_controls = [
            ft.Row(controls=header_controls, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Text(value, size=21, color=val_color, weight=ft.FontWeight.BOLD, font_family=FONT_MONO),
        ]

        if sparkline_data:
            column_controls.append(create_sparkline(sparkline_data, val_color))
        elif subtitle:
            column_controls.append(ft.Text(subtitle, size=11, color=TEXT_MUTED, font_family=FONT_MONO))

        shadow = create_neon_box_shadow(val_color, blur=12, opacity=0.16) if has_glow else None

        card = ft.Container(
            content=ft.Column(controls=column_controls, spacing=3),
            padding=15,
            bgcolor=SURFACE_1,
            border_radius=RADIUS_MD,
            border=ft.border.all(1.2, ft.Colors.with_opacity(0.45, val_color) if has_glow else BORDER_SUBTLE),
            shadow=shadow,
            expand=True,
            animate=get_animation(ANIM_FAST_MS) if ANIMATIONS_ENABLED else None,
        )

        def _on_hover(e: ft.HoverEvent):
            if not ANIMATIONS_ENABLED:
                return
            if e.data == "true":
                card.border = ft.border.all(1.2, BORDER_HIGHLIGHT)
                card.bgcolor = SURFACE_2
            else:
                card.border = ft.border.all(1.2, ft.Colors.with_opacity(0.45, val_color) if has_glow else BORDER_SUBTLE)
                card.bgcolor = SURFACE_1
            try:
                card.update()
            except Exception:
                pass

        card.on_hover = _on_hover
        return card

    def _build_monte_carlo_cone_card(
        self,
        trades: List[Trade],
        initial_balance: float = 10000.0,
        metrics: Optional[Any] = None,
    ) -> ft.Container:
        """
        Блок 'Квантовая симуляция Монте-Карло' с веером вероятностей (Probability Cone).
        Основан на 10 000 итерациях векторного бутстрэпа из AnalyticsService.simulate_monte_carlo.
        """
        mc = AnalyticsService.simulate_monte_carlo(trades, n_simulations=10000, n_steps=20, initial_balance=initial_balance)

        percentiles_data = [
            (mc["p95"], "#818CF8", "P95 Оптимистичный"),
            (mc["p75"], "#6366F1", "P75 Умеренный рост"),
            (mc["p50"], "#A5B4FC", "P50 Медиана"),
            (mc["p25"], "#F472B6", "P25 Просадочный"),
            (mc["p05"], LOSS, "P05 Стресс-тест / VaR"),
        ]

        cone_series = []
        all_vals = []
        for path_pts, col, label in percentiles_data:
            pts = []
            for step_idx, val in enumerate(path_pts):
                all_vals.append(val)
                p_tag = label.split()[0]
                pts.append(
                    ft.LineChartDataPoint(
                        step_idx,
                        val,
                        tooltip=f"{p_tag} (шаг {step_idx}): ${val:,.0f}",
                        tooltip_style=ft.TextStyle(
                            font_family=FONT_MONO,
                            size=11,
                            color=TEXT_PRIMARY,
                            weight=ft.FontWeight.W_500,
                        ),
                        show_tooltip=True,
                    )
                )
            cone_series.append(
                ft.LineChartData(
                    data_points=pts,
                    stroke_width=2.0 if label.startswith("P50") else 1.3,
                    color=col,
                    curved=True,
                    stroke_cap_round=True,
                )
            )

        min_val = min(all_vals) if all_vals else 0.0
        max_val = max(all_vals) if all_vals else 1000.0
        y_span = max(max_val - min_val, 20.0)
        y_padding = y_span * 0.12

        # 4 разнесенные аккуратные метки оси Y без наслоений
        step_val = y_span / 3
        axis_y_values = sorted(list(set([
            round(min_val, -1),
            round(min_val + step_val, -1),
            round(min_val + step_val * 2, -1),
            round(max_val, -1),
        ])))

        axis_labels = [
            ft.ChartAxisLabel(
                value=y,
                label=ft.Container(
                    content=ft.Text(f"${y:,.0f}", size=10, font_family=FONT_MONO, color=TEXT_MUTED),
                    alignment=ft.alignment.center_right,
                    padding=ft.padding.only(right=6),
                ),
            )
            for y in axis_y_values
        ]

        cone_chart = ft.LineChart(
            data_series=cone_series,
            border=None,
            horizontal_grid_lines=ft.ChartGridLines(
                interval=step_val,
                color=BORDER_SUBTLE,
                width=1,
                dash_pattern=[3, 4],
            ),
            vertical_grid_lines=ft.ChartGridLines(width=0),
            left_axis=ft.ChartAxis(
                labels=axis_labels,
                labels_size=48,
            ),
            bottom_axis=ft.ChartAxis(visible=False),
            top_axis=ft.ChartAxis(visible=False),
            right_axis=ft.ChartAxis(visible=False),
            min_y=min_val - y_padding,
            max_y=max_val + y_padding,
            interactive=True,
            tooltip_bgcolor="#12151E",
            tooltip_tooltip_border_side=ft.BorderSide(1, BORDER_HIGHLIGHT),
            tooltip_rounded_radius=8,
            tooltip_margin=12,
            tooltip_padding=ft.padding.symmetric(horizontal=10, vertical=6),
            tooltip_max_content_width=220,
            tooltip_fit_inside_horizontally=True,
            tooltip_fit_inside_vertically=True,
            height=175,
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    # 1. Шапка симуляции
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.QUERY_STATS_ROUNDED, color=ACCENT_PRIMARY, size=20),
                                    ft.Text("Симуляция Монте-Карло", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                ],
                                spacing=6,
                            ),
                            ft.Container(
                                content=ft.Text("10 000 ИТЕРАЦИЙ", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                bgcolor=ft.Colors.with_opacity(0.14, ACCENT_PRIMARY),
                                padding=ft.padding.symmetric(horizontal=7, vertical=2),
                                border_radius=RADIUS_SM,
                                border=ft.border.all(1, ft.Colors.with_opacity(0.3, ACCENT_PRIMARY)),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),

                    # 2. Квантовые метрики и стресс-тест в 4 адаптивных бокса
                    ft.Row(
                        controls=[
                            self._metric_mini_box("Risk of Ruin", f"< {mc['risk_of_ruin']}%", PROFIT if mc["risk_of_ruin"] < 5 else LOSS),
                            self._metric_mini_box(
                                "SQN Ван Тарпа",
                                f"{metrics.sqn:.2f}" if metrics and metrics.sqn > 0 else "—",
                                PROFIT if (metrics and metrics.sqn >= 2.0) else (WARNING_TILT if (metrics and metrics.sqn >= 1.6) else TEXT_SECONDARY),
                            ),
                            self._metric_mini_box(
                                "Sharpe / Sortino",
                                f"{metrics.sharpe_ratio:.1f} / {metrics.sortino_ratio:.1f}" if metrics and (metrics.sharpe_ratio != 0 or metrics.sortino_ratio != 0) else "—",
                                PROFIT if (metrics and metrics.sharpe_ratio >= 1.0) else (WARNING_TILT if (metrics and metrics.sharpe_ratio >= 0) else LOSS),
                            ),
                            self._metric_mini_box("Expectancy Run", f"{mc['expectancy_run']:+,.1f}%", PROFIT if mc["expectancy_run"] >= 0 else LOSS),
                        ],
                        spacing=8,
                    ),

                    ft.Divider(color=BORDER_SUBTLE, height=10),

                    # 3. Подзаголовок графика веера
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.TIMELINE_ROUNDED, size=13, color=ACCENT_PRIMARY),
                                    ft.Text("Веер траекторий капитала (20 шагов)", size=11, color=TEXT_SECONDARY, font_family=FONT_MONO),
                                ],
                                spacing=5,
                            ),
                            ft.Text("P95 (Бычий) → P05 (Стресс)", size=9, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),

                    # 4. Полноразмерный график веера вероятностей
                    cone_chart,

                    # 5. Описание метода бутстрэпа и Kelly-рекомендация
                    ft.Text(
                        f"Бутстрэп 10 000 траекторий • Риск по Келли (Half-Kelly): {metrics.half_kelly_pct:.1f}% • Серия: {metrics.current_streak:+d}"
                        if metrics and metrics.half_kelly_pct > 0
                        else "Векторный бутстрэп 10 000 траекторий депозита • 95% доверительный интервал",
                        size=10,
                        color=TEXT_MUTED,
                        font_family=FONT_FAMILY,
                    ),
                ],
                spacing=8,
            ),
            gradient=ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=["#141724", SURFACE_1],
            ),
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1.2, ft.Colors.with_opacity(0.35, ACCENT_PRIMARY)),
            shadow=create_neon_box_shadow(ACCENT_PRIMARY, blur=16, opacity=0.18),
        )

    def _metric_mini_box(self, label: str, val: str, color: str) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(label, size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                    ft.Text(val, size=12, weight=ft.FontWeight.BOLD, color=color, font_family=FONT_MONO),
                ],
                spacing=2,
            ),
            bgcolor=SURFACE_2,
            padding=ft.padding.symmetric(horizontal=8, vertical=6),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, BORDER_SUBTLE),
            expand=True,
        )

    def _build_session_matrix_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивная квант-матрица торговых сессий (Asia, London, New York, Off-Hours).
        """
        matrix = AnalyticsService.calculate_session_matrix(trades)
        sessions = matrix["sessions"]
        best_key = matrix["best_session"]
        worst_key = matrix["worst_session"]

        session_cards = []
        for s_key in ["ASIAN", "LONDON", "NEW_YORK", "OFF_HOURS"]:
            s = sessions[s_key]
            is_best = (s_key == best_key and s["trades_count"] > 0 and s["net_pnl"] > 0)
            is_worst = (s_key == worst_key and s["trades_count"] > 0 and s["net_pnl"] < 0)

            border_color = PROFIT if is_best else (LOSS if is_worst else BORDER_SUBTLE)
            pnl_color = PROFIT if s["net_pnl"] > 0 else (LOSS if s["net_pnl"] < 0 else TEXT_MUTED)
            wr_color = PROFIT if s["winrate"] >= 50 else (LOSS if s["trades_count"] > 0 else TEXT_MUTED)

            if is_best:
                status_badge = ft.Container(
                    content=ft.Text("ТОП СЕССИЯ", size=9, weight=ft.FontWeight.BOLD, color=PROFIT, font_family=FONT_MONO),
                    bgcolor=ft.Colors.with_opacity(0.15, PROFIT),
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    border_radius=RADIUS_SM,
                    border=ft.border.all(1, ft.Colors.with_opacity(0.35, PROFIT)),
                )
            elif is_worst:
                status_badge = ft.Container(
                    content=ft.Text("ЗОНА РИСКА", size=9, weight=ft.FontWeight.BOLD, color=LOSS, font_family=FONT_MONO),
                    bgcolor=ft.Colors.with_opacity(0.15, LOSS),
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    border_radius=RADIUS_SM,
                    border=ft.border.all(1, ft.Colors.with_opacity(0.35, LOSS)),
                )
            else:
                status_badge = ft.Container(
                    content=ft.Text(s["time_range"], size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                )

            wr_ratio = (s["winrate"] / 100.0) if s["trades_count"] > 0 else 0.0
            progress_bar = ft.ProgressBar(
                value=wr_ratio,
                color=wr_color,
                bgcolor=SURFACE_3,
                height=4,
                border_radius=ft.border_radius.all(2),
            )

            card_content = ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Container(
                                        width=8,
                                        height=8,
                                        border_radius=ft.border_radius.all(4),
                                        bgcolor=s["color"],
                                    ),
                                    ft.Text(s["name"], size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                ],
                                spacing=6,
                            ),
                            status_badge,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(s["sub"], size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                    ft.Divider(color=BORDER_SUBTLE, height=8),
                    ft.Row(
                        controls=[
                            ft.Text(
                                f"{s['net_pnl']:+,.2f} $" if s["trades_count"] > 0 else "0.00 $",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=pnl_color,
                                font_family=FONT_MONO,
                            ),
                            ft.Text(
                                f"{s['winrate']:.1f}% WR" if s["trades_count"] > 0 else "—",
                                size=11,
                                weight=ft.FontWeight.W_600,
                                color=wr_color,
                                font_family=FONT_MONO,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    progress_bar,
                    ft.Row(
                        controls=[
                            ft.Text(f"{s['trades_count']} сд.", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                            ft.Text(f"PF: {s['profit_factor']:.2f}" if s["trades_count"] > 0 else "PF: —", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                            ft.Text(f"Exp: {s['expectancy']:+,.1f}$" if s["trades_count"] > 0 else "Exp: —", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ],
                spacing=5,
            )

            session_card = ft.Container(
                content=card_content,
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1.2 if (is_best or is_worst) else 1, border_color),
                col={"sm": 12, "md": 6, "lg": 3},
            )
            session_cards.append(session_card)

        if best_key and sessions[best_key]["trades_count"] > 0:
            b = sessions[best_key]
            insight_text = f"Лидер: {b['name']} ({b['net_pnl']:+,.2f} $ • WR {b['winrate']:.0f}%)"
        else:
            insight_text = "Торговые сессии синхронизированы по UTC"

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.PUBLIC_ROUNDED, color=ACCENT_PRIMARY, size=18),
                                    ft.Text("Матрица торговых сессий", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Asia • London • New York • Off-Hours)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            ft.Container(
                                content=ft.Text(insight_text, size=10, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                border_radius=RADIUS_SM,
                                border=ft.border.all(1, ft.Colors.with_opacity(0.25, ACCENT_PRIMARY)),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(
                        controls=session_cards,
                        spacing=12,
                        run_spacing=12,
                    ),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_strategy_leaderboard_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный лидерборд торговых стратегий и сетапов (Edgewonk Strategy Matrix).
        """
        leaderboard = AnalyticsService.calculate_strategy_leaderboard(trades)

        if not leaderboard:
            items_content = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=16, color=TEXT_MUTED),
                        ft.Text("Добавьте теги стратегий к сделкам для формирования рейтинга доходности", size=12, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                    ],
                    spacing=8,
                ),
                padding=12,
            )
            top_insight = "Рейтинг сетапов формируется автоматически"
        else:
            top_s = leaderboard[0]
            top_insight = f"Топ-1 сетап: {top_s['tag']} ({top_s['net_pnl']:+,.2f} $ • PF: {top_s['profit_factor']:.2f})"

            rank_colors = {1: "#FBBF24", 2: "#E8EAF0", 3: "#FB923C"}

            rows = []
            for item in leaderboard[:6]:
                rk = item["rank"]
                rk_col = rank_colors.get(rk, TEXT_MUTED)
                pnl_col = PROFIT if item["net_pnl"] > 0 else (LOSS if item["net_pnl"] < 0 else TEXT_MUTED)

                row_widget = ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Text(f"#{rk}", size=11, weight=ft.FontWeight.BOLD, color=rk_col, font_family=FONT_MONO),
                                width=32,
                                alignment=ft.alignment.center_left,
                            ),
                            ft.Container(
                                content=ft.Text(item["tag"], size=12, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                width=140,
                            ),
                            ft.Container(
                                content=ft.Column(
                                    controls=[
                                        ft.Text(f"{item['winrate']:.1f}% WR ({item['win_trades']}/{item['trades_count']})", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                                        ft.ProgressBar(
                                            value=item["winrate"] / 100.0,
                                            color=PROFIT if item["winrate"] >= 50 else LOSS,
                                            bgcolor=SURFACE_3,
                                            height=4,
                                            border_radius=ft.border_radius.all(2),
                                        ),
                                    ],
                                    spacing=3,
                                ),
                                expand=True,
                            ),
                            ft.Container(
                                content=ft.Text(f"PF: {item['profit_factor']:.2f} • SQN: {item['sqn']:.1f}", size=10, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                width=130,
                                alignment=ft.alignment.center,
                            ),
                            ft.Container(
                                content=ft.Text(f"{item['net_pnl']:+,.2f} $", size=13, weight=ft.FontWeight.BOLD, color=pnl_col, font_family=FONT_MONO),
                                width=110,
                                alignment=ft.alignment.center_right,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    bgcolor=SURFACE_2,
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border_radius=RADIUS_MD,
                    border=ft.border.all(1, BORDER_SUBTLE),
                )
                rows.append(row_widget)

            items_content = ft.Column(controls=rows, spacing=6)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.LEADERBOARD_ROUNDED, color=ACCENT_PRIMARY, size=18),
                                    ft.Text("Лидерборд стратегий и сетапов", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Рейтинг эффективности Playbook)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            ft.Container(
                                content=ft.Text(top_insight, size=10, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                border_radius=RADIUS_SM,
                                border=ft.border.all(1, ft.Colors.with_opacity(0.25, ACCENT_PRIMARY)),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    items_content,
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_duration_analysis_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный анализ времени удержания сделок (Holding Duration vs Performance).
        """
        matrix = AnalyticsService.calculate_duration_matrix(trades)
        brackets = matrix["brackets"]
        best_b = matrix["best_duration"]

        cards = []
        for b_key in ["SCALP", "SHORT_INTRA", "MID_INTRA", "DAY_TRADE", "SWING"]:
            b = brackets[b_key]
            is_best = (b_key == best_b and b["trades_count"] > 0 and b["net_pnl"] > 0)
            pnl_col = PROFIT if b["net_pnl"] > 0 else (LOSS if b["net_pnl"] < 0 else TEXT_MUTED)
            wr_col = PROFIT if b["winrate"] >= 50 else (LOSS if b["trades_count"] > 0 else TEXT_MUTED)

            status_tag = (
                ft.Container(
                    content=ft.Text("ТОП ДИАПАЗОН", size=8, weight=ft.FontWeight.BOLD, color=PROFIT, font_family=FONT_MONO),
                    bgcolor=ft.Colors.with_opacity(0.15, PROFIT),
                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                    border_radius=RADIUS_SM,
                )
                if is_best
                else ft.Container(
                    content=ft.Text(f"~{b['avg_duration_min']:.0f}м" if b["trades_count"] > 0 else "—", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                )
            )

            c_content = ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(b["name"], size=11, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                            status_tag,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(b["range_label"], size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                    ft.Divider(color=BORDER_SUBTLE, height=6),
                    ft.Row(
                        controls=[
                            ft.Text(
                                f"{b['net_pnl']:+,.2f} $" if b["trades_count"] > 0 else "0.00 $",
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                color=pnl_col,
                                font_family=FONT_MONO,
                            ),
                            ft.Text(
                                f"{b['winrate']:.0f}% WR" if b["trades_count"] > 0 else "—",
                                size=11,
                                weight=ft.FontWeight.W_600,
                                color=wr_col,
                                font_family=FONT_MONO,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.ProgressBar(
                        value=(b["winrate"] / 100.0) if b["trades_count"] > 0 else 0.0,
                        color=wr_col,
                        bgcolor=SURFACE_3,
                        height=3,
                        border_radius=ft.border_radius.all(2),
                    ),
                    ft.Row(
                        controls=[
                            ft.Text(f"{b['trades_count']} сд.", size=9, color=TEXT_SECONDARY, font_family=FONT_MONO),
                            ft.Text(f"PF: {b['profit_factor']:.2f}" if b["trades_count"] > 0 else "PF: —", size=9, color=TEXT_SECONDARY, font_family=FONT_MONO),
                            ft.Text(f"КПД: {b['avg_efficiency']:.0f}%" if b["trades_count"] > 0 else "КПД: —", size=9, color=TEXT_SECONDARY, font_family=FONT_MONO),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ],
                spacing=4,
            )

            card_widget = ft.Container(
                content=c_content,
                bgcolor=SURFACE_2,
                padding=10,
                border_radius=RADIUS_MD,
                border=ft.border.all(1.2 if is_best else 1, PROFIT if is_best else BORDER_SUBTLE),
                col={"sm": 12, "md": 4, "lg": 2.4},
            )
            cards.append(card_widget)

        if best_b and brackets[best_b]["trades_count"] > 0:
            best_meta = brackets[best_b]
            insight_label = f"Оптимальный горизонт: {best_meta['name']} ({best_meta['range_label']}) -> {best_meta['net_pnl']:+,.2f} $"
        else:
            insight_label = "Анализ времени удержания (Holding Duration) активен"

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.HOURGLASS_BOTTOM_ROUNDED, color=ACCENT_PRIMARY, size=18),
                                    ft.Text("Анализ времени удержания сделок", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Duration vs PnL & КПД)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            ft.Container(
                                content=ft.Text(insight_label, size=10, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                border_radius=RADIUS_SM,
                                border=ft.border.all(1, ft.Colors.with_opacity(0.25, ACCENT_PRIMARY)),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=cards, spacing=10, run_spacing=10),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_asset_allocation_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный анализ распределения по классам активов и концентрации риска (Asset Class & Ticker Matrix).
        """
        matrix = AnalyticsService.calculate_asset_allocation_matrix(trades)
        classes = matrix["asset_classes"]
        top_symbols = matrix["top_symbols"]
        warning = matrix["concentration_warning"]
        best_c = matrix["best_class"]

        class_cards = []
        icon_map = {
            "CRYPTO": ft.Icons.CURRENCY_BITCOIN_ROUNDED,
            "FOREX": ft.Icons.CURRENCY_EXCHANGE_ROUNDED,
            "EQUITIES": ft.Icons.CANDLESTICK_CHART_ROUNDED,
            "COMMODITIES": ft.Icons.DIAMOND_ROUNDED,
        }

        for c_key in ["CRYPTO", "FOREX", "EQUITIES", "COMMODITIES"]:
            c = classes[c_key]
            is_best = (best_c == c_key and c["trades_count"] > 0)

            pnl_val = c["net_pnl"]
            pnl_color = PROFIT if pnl_val >= 0 else LOSS
            pnl_sign = "+" if pnl_val >= 0 else ""
            icon_ctrl = icon_map.get(c_key, ft.Icons.CATEGORY_ROUNDED)

            leader_chip = ft.Container(
                content=ft.Text("TOP ASSET", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.15, ACCENT_PRIMARY),
                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, ft.Colors.with_opacity(0.4, ACCENT_PRIMARY)),
            ) if is_best else ft.Container()

            card_widget = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Container(
                                            content=ft.Icon(icon_ctrl, size=15, color=c["color"]),
                                            padding=5,
                                            bgcolor=ft.Colors.with_opacity(0.12, c["color"]),
                                            border_radius=RADIUS_SM,
                                        ),
                                        ft.Column(
                                            controls=[
                                                ft.Text(c["name"], size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                                ft.Text(f"Доля: {c['share_pct']}% • {c['trades_count']} сделок", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                                            ],
                                            spacing=1,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                                leader_chip,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(height=4),
                        ft.ProgressBar(
                            value=c["share_pct"] / 100.0,
                            color=c["color"],
                            bgcolor=SURFACE_2,
                            height=4,
                            border_radius=RADIUS_SM,
                        ),
                        ft.Container(height=4),
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text("Net PnL", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{pnl_sign}${pnl_val:,.2f}", size=12, weight=ft.FontWeight.BOLD, color=pnl_color, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Winrate", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{c['winrate']}%", size=11, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Profit Factor", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{c['profit_factor']:.2f}", size=11, weight=ft.FontWeight.W_600, color=TEXT_SECONDARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, ft.Colors.with_opacity(0.3, c["color"]) if is_best else BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 6, "lg": 3},
            )
            class_cards.append(card_widget)

        symbol_chips = []
        for s in top_symbols:
            s_pnl = s["net_pnl"]
            s_color = PROFIT if s_pnl >= 0 else LOSS
            s_sign = "+" if s_pnl >= 0 else ""
            chip = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Text(s["ticker"], size=11, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
                        ft.Container(
                            content=ft.Text(f"{s['share_pct']}%", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                            bgcolor=SURFACE_1,
                            padding=ft.padding.symmetric(horizontal=4, vertical=1),
                            border_radius=3,
                        ),
                        ft.Text(f"{s_sign}${s_pnl:,.0f}", size=10, weight=ft.FontWeight.W_600, color=s_color, font_family=FONT_MONO),
                    ],
                    spacing=6,
                    tight=True,
                ),
                bgcolor=SURFACE_2,
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, BORDER_SUBTLE),
            )
            symbol_chips.append(chip)

        header_right_controls = []
        if warning:
            header_right_controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=WARNING_TILT, size=14),
                            ft.Text(warning, size=10, weight=ft.FontWeight.BOLD, color=WARNING_TILT, font_family=FONT_MONO),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    bgcolor=ft.Colors.with_opacity(0.15, WARNING_TILT),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    border_radius=RADIUS_SM,
                    border=ft.border.all(1, ft.Colors.with_opacity(0.35, WARNING_TILT)),
                )
            )
        else:
            header_right_controls.append(
                ft.Container(
                    content=ft.Text(f"Оборот: ${matrix['total_volume']:,.0f} • Концентрация в норме", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                    bgcolor=SURFACE_2,
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    border_radius=RADIUS_SM,
                    border=ft.border.all(1, BORDER_SUBTLE),
                )
            )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.PIE_CHART_ROUNDED, color=ACCENT_PRIMARY, size=18),
                                    ft.Text("Классы активов и риск концентрации", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Asset Allocation Matrix)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            ft.Row(controls=header_right_controls, spacing=8),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=class_cards, spacing=10, run_spacing=10),
                    ft.Container(height=4),
                    ft.Row(
                        controls=[
                            ft.Text("Ключевые тикеры портфеля:", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                            ft.Row(controls=symbol_chips, spacing=8, wrap=True),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ) if symbol_chips else ft.Container(),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_psychology_matrix_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный квантовый аудит психологии и стоимости тильта (Edgewonk Emotional Tilt Matrix).
        """
        matrix = AnalyticsService.calculate_psychology_matrix(trades)
        disc_score = matrix["discipline_score_pct"]
        tilt_drag = matrix["tilt_drag_amount"]
        leak = matrix["primary_emotional_leak"]
        reasons = matrix["reasons_breakdown"]

        score_color = PROFIT if disc_score >= 80 else (WARNING_TILT if disc_score >= 50 else LOSS)

        # 3 KPI карточки: Discipline Score, Чистый Edge, Главная утечка
        kpi_cards = [
            # 1. Discipline Score
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text("Discipline Score", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text(f"{disc_score:.0f}%", size=10, weight=ft.FontWeight.BOLD, color=score_color, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, score_color),
                                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                    border_radius=3,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.ProgressBar(
                            value=disc_score / 100.0,
                            color=score_color,
                            bgcolor=SURFACE_2,
                            height=4,
                            border_radius=RADIUS_SM,
                        ),
                        ft.Text(
                            f"{matrix['disciplined_trades']} из {matrix['total_trades']} сделок строго по системе",
                            size=10,
                            color=TEXT_SECONDARY,
                            font_family=FONT_FAMILY,
                        ),
                    ],
                    spacing=6,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 4, "md": 4},
            ),
            # 2. Чистый edge против факта
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Чистый результат без тильта", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Row(
                            controls=[
                                ft.Text(f"+${matrix['disciplined_net_pnl']:,.2f}", size=15, weight=ft.FontWeight.BOLD, color=PROFIT, font_family=FONT_MONO),
                                ft.Text(f"Факт: ${matrix['actual_net_pnl']:,.2f}", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(
                            f"Тильт-сделки ({matrix['tilt_trades']}): -${tilt_drag:,.2f}" if tilt_drag > 0 else "Тильт-убытки не зафиксированы",
                            size=10,
                            color=LOSS if tilt_drag > 0 else PROFIT,
                            font_family=FONT_MONO,
                        ),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 4, "md": 4},
            ),
            # 3. Главная эмоциональная утечка
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Ключевой фактор утечки PnL", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.FIRE_EXTINGUISHER_ROUNDED if leak else ft.Icons.VERIFIED_ROUNDED, size=16, color=WARNING_TILT if leak else PROFIT),
                                ft.Text(leak or "Все сделки по правилам", size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                            ],
                            spacing=6,
                        ),
                        ft.Text(
                            "Устранение этой ошибки вернет прибыль" if leak else "Отличная дисциплина и контроль риска",
                            size=10,
                            color=TEXT_MUTED,
                            font_family=FONT_FAMILY,
                        ),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 4, "md": 4},
            ),
        ]

        # Список классифицированных ошибок
        reason_pills = []
        for r in reasons:
            pill = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Icon(ft.Icons.WARNING_ROUNDED, size=12, color=r["color"]),
                            padding=3,
                            bgcolor=ft.Colors.with_opacity(0.12, r["color"]),
                            border_radius=3,
                        ),
                        ft.Text(r["name"], size=11, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                        ft.Text(f"{r['trades_count']} шт.", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                        ft.Text(f"${r['net_pnl']:+,.2f}", size=11, weight=ft.FontWeight.BOLD, color=LOSS if r["net_pnl"] < 0 else PROFIT, font_family=FONT_MONO),
                    ],
                    spacing=6,
                    tight=True,
                ),
                bgcolor=SURFACE_2,
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, ft.Colors.with_opacity(0.25, r["color"])),
            )
            reason_pills.append(pill)

        header_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SHIELD_ROUNDED if tilt_drag == 0 else ft.Icons.LOCAL_FIRE_DEPARTMENT_ROUNDED, size=14, color=PROFIT if tilt_drag == 0 else LOSS),
                    ft.Text(
                        "100% Дисциплина • Edge чист" if tilt_drag == 0 else f"Утечка капитала: -${tilt_drag:,.2f}",
                        size=10,
                        weight=ft.FontWeight.BOLD,
                        color=PROFIT if tilt_drag == 0 else LOSS,
                        font_family=FONT_MONO,
                    ),
                ],
                spacing=4,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, PROFIT if tilt_drag == 0 else LOSS),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, PROFIT if tilt_drag == 0 else LOSS)),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.PSYCHOLOGY_ROUNDED, color="#A855F7", size=18),
                                    ft.Text("Аудит дисциплины и психологии", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Edgewonk Tilt & Alpha Leak Matrix)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_chip,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=kpi_cards, spacing=10, run_spacing=10),
                    ft.Container(height=4),
                    ft.Row(
                        controls=[
                            ft.Text("Категории нарушений:", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                            ft.Row(controls=reason_pills, spacing=8, wrap=True),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ) if reason_pills else ft.Container(),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_drawdown_recovery_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный анализ просадок и устойчивости портфеля (TraderSync Drawdown & Recovery Factor).
        """
        matrix = AnalyticsService.calculate_drawdown_recovery_matrix(trades)
        max_dd_amt = matrix["max_drawdown_amount"]
        max_dd_pct = matrix["max_drawdown_pct"]
        curr_dd_pct = matrix["current_drawdown_pct"]
        rf = matrix["recovery_factor"]
        ui = matrix["ulcer_index"]
        p2v = matrix["peak_to_valley_trades"]

        if rf >= 3.0:
            rf_grade = "Отличный (>3.0)"
            rf_col = PROFIT
        elif rf >= 1.5:
            rf_grade = "Умеренный (1.5-3.0)"
            rf_col = "#F59E0B"
        else:
            rf_grade = "Слабый (<1.5)"
            rf_col = LOSS if rf < 1.0 else TEXT_MUTED

        if ui < 3.0:
            ui_grade = "Низкий стресс (Плавный рост)"
            ui_col = PROFIT
        elif ui < 7.0:
            ui_grade = "Умеренный стресс"
            ui_col = "#F59E0B"
        else:
            ui_grade = "Высокий стресс (Глубокие ямы)"
            ui_col = LOSS

        kpi_boxes = [
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Максимальная просадка", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Row(
                            controls=[
                                ft.Text(f"-${max_dd_amt:,.2f}", size=15, weight=ft.FontWeight.BOLD, color=LOSS if max_dd_amt > 0 else PROFIT, font_family=FONT_MONO),
                                ft.Container(
                                    content=ft.Text(f"-{max_dd_pct:.1f}%", size=10, weight=ft.FontWeight.BOLD, color=LOSS if max_dd_pct > 0 else PROFIT, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, LOSS if max_dd_pct > 0 else PROFIT),
                                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                    border_radius=3,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(
                            f"Пик: ${matrix['peak_equity']:,.2f} -> Дно: ${matrix['peak_equity'] - max_dd_amt:,.2f}",
                            size=10,
                            color=TEXT_MUTED,
                            font_family=FONT_MONO,
                        ),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Фактор восстановления (RF)", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Row(
                            controls=[
                                ft.Text(f"{rf:.2f}", size=15, weight=ft.FontWeight.BOLD, color=rf_col, font_family=FONT_MONO),
                                ft.Text("Net PnL / Max DD", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(rf_grade, size=10, color=rf_col, font_family=FONT_FAMILY),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Индекс язвы (Ulcer Index)", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Row(
                            controls=[
                                ft.Text(f"{ui:.2f}", size=15, weight=ft.FontWeight.BOLD, color=ui_col, font_family=FONT_MONO),
                                ft.Icon(ft.Icons.SPA_ROUNDED if ui < 3.0 else ft.Icons.HEALTH_AND_SAFETY_ROUNDED, size=15, color=ui_col),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(ui_grade, size=10, color=ui_col, font_family=FONT_FAMILY),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Длительность просадки", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Row(
                            controls=[
                                ft.Text(f"{p2v} сделок", size=15, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                ft.Text("Peak-to-Valley", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text("Количество трейдов под пиком ATH", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
        ]

        is_ath = (curr_dd_pct == 0.0)
        status_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.ROCKET_LAUNCH_ROUNDED if is_ath else ft.Icons.TRENDING_DOWN_ROUNDED, size=13, color=PROFIT if is_ath else LOSS),
                    ft.Text(
                        "Капитал на пике (ATH) 🚀" if is_ath else f"Текущая просадка: -{curr_dd_pct:.1f}% (-${matrix['current_drawdown_amount']:,.2f})",
                        size=10,
                        weight=ft.FontWeight.BOLD,
                        color=PROFIT if is_ath else LOSS,
                        font_family=FONT_MONO,
                    ),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, PROFIT if is_ath else LOSS),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, PROFIT if is_ath else LOSS)),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.WATER_DROP_ROUNDED, color="#38BDF8", size=18),
                                    ft.Text("Анализ просадки и устойчивости", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(TraderSync Drawdown & Recovery)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            status_chip,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=kpi_boxes, spacing=10, run_spacing=10),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_excursion_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный анализ качества входов и выходов (TradeZella MAE / MFE Excursion Matrix).
        """
        matrix = AnalyticsService.calculate_excursion_matrix(trades)
        ratio = matrix["edge_ratio"]
        avg_mae = matrix["avg_mae_pct"]
        avg_mfe = matrix["avg_mfe_pct"]
        eff = matrix["avg_efficiency_pct"]
        table_leak = matrix["left_on_table_amount"]
        grade = matrix["edge_rating"]

        ratio_col = PROFIT if ratio >= 2.0 else ("#F59E0B" if ratio >= 1.5 else LOSS)
        eff_col = PROFIT if eff >= 60.0 else ("#F59E0B" if eff >= 40.0 else LOSS)

        kpi_cards = [
            # 1. Edge Ratio
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Edge Ratio (MFE / MAE)", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Row(
                            controls=[
                                ft.Text(f"{ratio:.2f}", size=15, weight=ft.FontWeight.BOLD, color=ratio_col, font_family=FONT_MONO),
                                ft.Container(
                                    content=ft.Text("MFE / |MAE|", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                                    bgcolor=SURFACE_1,
                                    padding=ft.padding.symmetric(horizontal=4, vertical=1),
                                    border_radius=3,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(grade, size=10, color=ratio_col, font_family=FONT_FAMILY),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 2. Avg MFE
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Ср. MFE (Потенциал сделок)", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Row(
                            controls=[
                                ft.Text(f"+{avg_mfe:.2f}%", size=15, weight=ft.FontWeight.BOLD, color=PROFIT, font_family=FONT_MONO),
                                ft.Icon(ft.Icons.TRENDING_UP_ROUNDED, size=15, color=PROFIT),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text("Максимальный ход в сторону профита", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 3. Avg MAE
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Ср. MAE (Просадка в позиции)", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Row(
                            controls=[
                                ft.Text(f"-{avg_mae:.2f}%", size=15, weight=ft.FontWeight.BOLD, color=LOSS, font_family=FONT_MONO),
                                ft.Icon(ft.Icons.TRENDING_DOWN_ROUNDED, size=15, color=LOSS),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text("Максимальный откат против позиции", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 4. Retention Efficiency
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text("КПД удержания (Retention)", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Text(f"{eff:.0f}%", size=11, weight=ft.FontWeight.BOLD, color=eff_col, font_family=FONT_MONO),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.ProgressBar(
                            value=eff / 100.0,
                            color=eff_col,
                            bgcolor=SURFACE_1,
                            height=4,
                            border_radius=RADIUS_SM,
                        ),
                        ft.Text(
                            f"Оставлено на столе: -${table_leak:,.2f}" if table_leak > 0 else "Оптимальная фиксация прибыли",
                            size=10,
                            color=LOSS if table_leak > 0 else PROFIT,
                            font_family=FONT_MONO,
                        ),
                    ],
                    spacing=5,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
        ]

        header_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SPEED_ROUNDED, size=13, color=ratio_col),
                    ft.Text(
                        f"Edge Ratio: {ratio:.2f}x",
                        size=10,
                        weight=ft.FontWeight.BOLD,
                        color=ratio_col,
                        font_family=FONT_MONO,
                    ),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, ratio_col),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, ratio_col)),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.CALL_SPLIT_ROUNDED, color="#22D3EE", size=18),
                                    ft.Text("Качество исполнения MAE / MFE", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(TradeZella Excursion Matrix)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_chip,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=kpi_cards, spacing=10, run_spacing=10),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_monthly_phase_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный анализ сезонности и фаз месяца (TraderSync / Edgewonk Monthly Phase Matrix).
        """
        matrix = AnalyticsService.calculate_monthly_phase_matrix(trades)
        phases = matrix["phases"]
        best_p = matrix["best_phase"]
        insight = matrix["seasonal_insight"]

        icon_map = {
            "EARLY_MONTH": ft.Icons.CALENDAR_TODAY_ROUNDED,
            "MID_MONTH": ft.Icons.EVENT_REPEAT_ROUNDED,
            "LATE_MONTH": ft.Icons.EVENT_AVAILABLE_ROUNDED,
        }

        cards = []
        for p_key in ["EARLY_MONTH", "MID_MONTH", "LATE_MONTH"]:
            p = phases[p_key]
            is_best = (best_p == p_key and p["trades_count"] > 0)

            pnl_val = p["net_pnl"]
            pnl_color = PROFIT if pnl_val >= 0 else LOSS
            pnl_sign = "+" if pnl_val >= 0 else ""
            icon_ctrl = icon_map.get(p_key, ft.Icons.CALENDAR_MONTH_ROUNDED)

            leader_chip = ft.Container(
                content=ft.Text("PEAK EDGE", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.15, ACCENT_PRIMARY),
                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, ft.Colors.with_opacity(0.4, ACCENT_PRIMARY)),
            ) if is_best else ft.Container()

            card_widget = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Container(
                                            content=ft.Icon(icon_ctrl, size=15, color=p["color"]),
                                            padding=5,
                                            bgcolor=ft.Colors.with_opacity(0.12, p["color"]),
                                            border_radius=RADIUS_SM,
                                        ),
                                        ft.Column(
                                            controls=[
                                                ft.Text(p["name"], size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                                ft.Text(p["sub"], size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                                            ],
                                            spacing=1,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                                leader_chip,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(height=4),
                        ft.ProgressBar(
                            value=p["winrate"] / 100.0 if p["trades_count"] > 0 else 0.0,
                            color=p["color"],
                            bgcolor=SURFACE_2,
                            height=4,
                            border_radius=RADIUS_SM,
                        ),
                        ft.Container(height=4),
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text("Net PnL", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{pnl_sign}${pnl_val:,.2f}", size=13, weight=ft.FontWeight.BOLD, color=pnl_color, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Winrate", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{p['winrate']}% ({p['trades_count']} сд.)", size=11, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Profit Factor", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{p['profit_factor']:.2f}", size=11, weight=ft.FontWeight.W_600, color=TEXT_SECONDARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, ft.Colors.with_opacity(0.3, p["color"]) if is_best else BORDER_SUBTLE),
                col={"xs": 12, "sm": 4, "md": 4},
            )
            cards.append(card_widget)

        header_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=13, color=ACCENT_PRIMARY),
                    ft.Text(
                        insight,
                        size=10,
                        weight=ft.FontWeight.BOLD,
                        color=ACCENT_PRIMARY,
                        font_family=FONT_MONO,
                    ),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, ACCENT_PRIMARY)),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.CALENDAR_MONTH_ROUNDED, color="#10B981", size=18),
                                    ft.Text("Фазы месяца и циклическая сезонность", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Day-of-Month Cycle)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_chip,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=cards, spacing=10, run_spacing=10),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_position_sizing_simulator_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный симулятор мани-менеджмента и моделей риска (Position Sizing Simulator).
        """
        sim = AnalyticsService.simulate_position_sizing_models(trades, initial_balance=10000.0)
        models = sim["models"]
        optimal_k = sim["optimal_model"]
        insight = sim["optimal_insight"]

        cards = []
        for m_key in ["FLAT_1PCT", "HALF_KELLY", "FULL_KELLY", "FIXED_DOLLAR"]:
            m = models[m_key]
            is_opt = (m_key == optimal_k)

            ret_val = m["total_return_pct"]
            ret_col = PROFIT if ret_val >= 0 else LOSS
            ret_sign = "+" if ret_val >= 0 else ""

            leader_chip = ft.Container(
                content=ft.Text("OPTIMAL", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.15, ACCENT_PRIMARY),
                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, ft.Colors.with_opacity(0.4, ACCENT_PRIMARY)),
            ) if is_opt else ft.Container()

            card_widget = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text(m["name"], size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                        ft.Text(m["sub"], size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                leader_chip,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(height=4),
                        # Метрики Equity, Return, Max DD
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text("Итоговый баланс", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"${m['final_equity']:,.2f}", size=13, weight=ft.FontWeight.BOLD, color=ret_col, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Доходность", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{ret_sign}{ret_val:,.1f}%", size=11, weight=ft.FontWeight.W_600, color=ret_col, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Max Просадка", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"-{m['max_drawdown_pct']:.1f}%", size=11, weight=ft.FontWeight.W_600, color=LOSS if m['max_drawdown_pct'] > 0 else TEXT_MUTED, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(height=4),
                        ft.Container(
                            content=ft.Text(m["badge"], size=9, color=m["color"], font_family=FONT_MONO),
                            bgcolor=ft.Colors.with_opacity(0.12, m["color"]),
                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                            border_radius=RADIUS_SM,
                        ),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, ft.Colors.with_opacity(0.35, m["color"]) if is_opt else BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            )
            cards.append(card_widget)

        header_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SAVINGS_ROUNDED, size=13, color=ACCENT_PRIMARY),
                    ft.Text(
                        insight,
                        size=10,
                        weight=ft.FontWeight.BOLD,
                        color=ACCENT_PRIMARY,
                        font_family=FONT_MONO,
                    ),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, ACCENT_PRIMARY)),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.MONETIZATION_ON_ROUNDED, color="#7C5CFF", size=18),
                                    ft.Text("Симулятор моделей мани-менеджмента", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Position Sizing & Kelly)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_chip,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=cards, spacing=10, run_spacing=10),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_market_regime_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный анализ эффективности в фазах рынка (Market Regime Alignment Matrix).
        """
        matrix = AnalyticsService.calculate_market_regime_matrix(trades)
        regimes = matrix["regimes"]
        best_r = matrix["best_regime"]
        insight = matrix["regime_insight"]

        icon_map = {
            "BULL_TREND": ft.Icons.TRENDING_UP_ROUNDED,
            "BEAR_TREND": ft.Icons.TRENDING_DOWN_ROUNDED,
            "RANGE_CHOP": ft.Icons.SYNC_ALT_ROUNDED,
            "BREAKOUT_EXPANSION": ft.Icons.BOLT_ROUNDED,
        }

        cards = []
        for r_key in ["BULL_TREND", "BEAR_TREND", "RANGE_CHOP", "BREAKOUT_EXPANSION"]:
            r = regimes[r_key]
            is_best = (r_key == best_r and r["trades_count"] > 0)

            pnl_val = r["net_pnl"]
            pnl_color = PROFIT if pnl_val >= 0 else LOSS
            pnl_sign = "+" if pnl_val >= 0 else ""
            icon_ctrl = icon_map.get(r_key, ft.Icons.AUTO_GRAPH_ROUNDED)

            leader_chip = ft.Container(
                content=ft.Text("TOP REGIME", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.15, ACCENT_PRIMARY),
                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, ft.Colors.with_opacity(0.4, ACCENT_PRIMARY)),
            ) if is_best else ft.Container()

            card_widget = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Container(
                                            content=ft.Icon(icon_ctrl, size=15, color=r["color"]),
                                            padding=5,
                                            bgcolor=ft.Colors.with_opacity(0.12, r["color"]),
                                            border_radius=RADIUS_SM,
                                        ),
                                        ft.Column(
                                            controls=[
                                                ft.Text(r["name"], size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                                ft.Text(r["sub"], size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                                            ],
                                            spacing=1,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                                leader_chip,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(height=4),
                        ft.ProgressBar(
                            value=r["winrate"] / 100.0 if r["trades_count"] > 0 else 0.0,
                            color=r["color"],
                            bgcolor=SURFACE_2,
                            height=4,
                            border_radius=RADIUS_SM,
                        ),
                        ft.Container(height=4),
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text("Net PnL", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{pnl_sign}${pnl_val:,.2f}", size=13, weight=ft.FontWeight.BOLD, color=pnl_color, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Winrate", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{r['winrate']}% ({r['trades_count']} сд.)", size=11, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Profit Factor", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{r['profit_factor']:.2f}", size=11, weight=ft.FontWeight.W_600, color=TEXT_SECONDARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(height=4),
                        ft.Container(
                            content=ft.Text(f"Сетап: {r['top_strategy']}", size=9, color=TEXT_SECONDARY, font_family=FONT_MONO),
                            bgcolor=SURFACE_1,
                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                            border_radius=RADIUS_SM,
                            border=ft.border.all(1, BORDER_SUBTLE),
                        ),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, ft.Colors.with_opacity(0.35, r["color"]) if is_best else BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            )
            cards.append(card_widget)

        header_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.INSIGHTS_ROUNDED, size=13, color="#EC4899"),
                    ft.Text(
                        insight,
                        size=10,
                        weight=ft.FontWeight.BOLD,
                        color="#EC4899",
                        font_family=FONT_MONO,
                    ),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, "#EC4899"),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, "#EC4899")),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.AUTO_GRAPH_ROUNDED, color="#EC4899", size=18),
                                    ft.Text("Рыночные фазы и соответствие режимам", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Market Regime Alignment)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_chip,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=cards, spacing=10, run_spacing=10),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_r_distribution_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивная гистограмма частотного распределения R-Multiple и квантовая асимметрия (Skewness / Kurtosis).
        """
        matrix = AnalyticsService.calculate_r_distribution_matrix(trades)
        bins = matrix["bins"]
        skewness = matrix["skewness"]
        kurtosis = matrix["kurtosis"]
        profile = matrix["distribution_profile"]
        color = matrix["insight_color"]
        tot_trades = matrix["total_trades"]

        max_share = max((b["share_pct"] for b in bins), default=1.0)
        if max_share <= 0:
            max_share = 1.0

        bar_columns = []
        for b in bins:
            pct = b["share_pct"]
            cnt = b["trades_count"]
            b_color = b["color"]
            # Нормализация высоты бара (от 6 до 85 пикселей)
            h = max(6, int((pct / max_share) * 85)) if tot_trades > 0 else 6

            pnl_val = b["net_pnl"]
            pnl_sign = "+" if pnl_val >= 0 else ""

            bar_widget = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text(f"{pct:.0f}%", size=10, weight=ft.FontWeight.W_600, color=TEXT_SECONDARY, font_family=FONT_MONO),
                        ft.Container(
                            width=32,
                            height=h,
                            bgcolor=b_color if cnt > 0 else SURFACE_2,
                            border_radius=ft.border_radius.only(top_left=RADIUS_SM, top_right=RADIUS_SM),
                            border=ft.border.all(1, ft.Colors.with_opacity(0.4, b_color)) if cnt > 0 else ft.border.all(1, BORDER_SUBTLE),
                            tooltip=f"Корзина: {b['name']}\nСделок: {cnt} ({pct:.1f}%)\nNet PnL: {pnl_sign}${pnl_val:,.2f}\nСр. R: {b['avg_r']:+.2f}R",
                        ),
                        ft.Text(b["label"], size=10, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
                        ft.Text(f"{cnt} сд.", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.END,
                    spacing=3,
                ),
                padding=ft.padding.symmetric(horizontal=4, vertical=2),
                col={"xs": 6, "sm": 3, "md": 1.7},
            )
            bar_columns.append(bar_widget)

        # 4 компактные карточки квантовых метрик
        stat_cards = [
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Асимметрия (Skew)", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Text(f"{skewness:+0.2f}", size=14, weight=ft.FontWeight.BOLD, color=color, font_family=FONT_MONO),
                        ft.Text("Right-tailed alpha" if skewness >= 0 else "Left-tailed risk", size=9, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                    ],
                    spacing=2,
                ),
                bgcolor=SURFACE_2,
                padding=10,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 6, "sm": 3},
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Эксцесс (Kurtosis)", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Text(f"{kurtosis:+0.2f}", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
                        ft.Text("Островершинность", size=9, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                    ],
                    spacing=2,
                ),
                bgcolor=SURFACE_2,
                padding=10,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 6, "sm": 3},
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Ср. Тейк / Стоп", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Text(f"+{matrix['avg_winner_r']:.2f}R / {matrix['avg_loser_r']:.2f}R", size=13, weight=ft.FontWeight.BOLD, color=PROFIT, font_family=FONT_MONO),
                        ft.Text(f"Exp: {matrix['expectancy_r']:+.2f}R", size=9, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=2,
                ),
                bgcolor=SURFACE_2,
                padding=10,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 6, "sm": 3},
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Home Runs (>3R)", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Text(f"{matrix['home_runs_count']} сд.", size=14, weight=ft.FontWeight.BOLD, color="#7C5CFF", font_family=FONT_MONO),
                        ft.Text(f"Хвост <-2R: {matrix['fat_tail_losses_count']} сд.", size=9, color=LOSS if matrix['fat_tail_losses_count'] > 0 else TEXT_MUTED, font_family=FONT_FAMILY),
                    ],
                    spacing=2,
                ),
                bgcolor=SURFACE_2,
                padding=10,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 6, "sm": 3},
            ),
        ]

        header_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.AUTO_GRAPH_ROUNDED, size=13, color=color),
                    ft.Text(profile, size=10, weight=ft.FontWeight.BOLD, color=color, font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, color),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, color)),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.BAR_CHART_ROUNDED, color="#7C5CFF", size=18),
                                    ft.Text("Частотное распределение доходности по риску", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(R-Multiple Distribution)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_chip,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    # Гистограмма
                    ft.Container(
                        content=ft.ResponsiveRow(controls=bar_columns, alignment=ft.MainAxisAlignment.SPACE_AROUND),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=12, vertical=10),
                        border_radius=RADIUS_MD,
                        border=ft.border.all(1, BORDER_SUBTLE),
                    ),
                    ft.Container(height=4),
                    # Сетка метрик
                    ft.ResponsiveRow(controls=stat_cards, spacing=10, run_spacing=10),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_rr_efficiency_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный анализ соблюдения запланированного R:R и утечки прибыли (R:R Execution Efficiency & Leakage).
        """
        matrix = AnalyticsService.calculate_rr_efficiency_matrix(trades)
        grade = matrix["execution_grade"]
        color = matrix["grade_color"]
        insight = matrix["leakage_insight"]

        # 4 карточки KPI
        cards = [
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Ср. план R:R", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Text(f"1 : {matrix['avg_planned_rr']:.2f}", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
                        ft.Text("Целевое соотношение", size=9, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                    ],
                    spacing=2,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 6, "sm": 3},
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Ср. факт R:R", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Text(f"{matrix['avg_realized_rr']:+.2f} R", size=14, weight=ft.FontWeight.BOLD, color=PROFIT if matrix['avg_realized_rr'] >= 0 else LOSS, font_family=FONT_MONO),
                        ft.Text("Фактически взято", size=9, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                    ],
                    spacing=2,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 6, "sm": 3},
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text("R:R Эффективность", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Text(f"{matrix['execution_efficiency_pct']:.1f}%", size=10, weight=ft.FontWeight.BOLD, color=color, font_family=FONT_MONO),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.ProgressBar(
                            value=min(1.0, matrix['execution_efficiency_pct'] / 100.0) if matrix['evaluated_trades_count'] > 0 else 0.0,
                            color=color,
                            bgcolor=SURFACE_1,
                            height=6,
                            border_radius=RADIUS_SM,
                        ),
                        ft.Text(f"{matrix['disciplined_exits_count']} по плану • {matrix['premature_exits_count']} рано", size=9, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 6, "sm": 3},
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Упущенный тейк", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Text(f"-${matrix['total_leakage_dollars']:,.2f}", size=14, weight=ft.FontWeight.BOLD, color=WARNING_TILT if matrix['total_leakage_dollars'] > 0 else PROFIT, font_family=FONT_MONO),
                        ft.Text("Недосиживание прибыли", size=9, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                    ],
                    spacing=2,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 6, "sm": 3},
            ),
        ]

        header_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.TRACK_CHANGES_ROUNDED, size=13, color=color),
                    ft.Text(grade, size=10, weight=ft.FontWeight.BOLD, color=color, font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, color),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, color)),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.TRACK_CHANGES_ROUNDED, color="#06B6D4", size=18),
                                    ft.Text("Эффективность исполнения плана R:R", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Planned vs Realized R:R)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_chip,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=cards, spacing=10, run_spacing=10),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.LIGHTBULB_OUTLINE_ROUNDED, size=13, color=TEXT_MUTED),
                                ft.Text(insight, size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, BORDER_SUBTLE),
                    ),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_rule_violation_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный аудит нарушений правил торгового плана и расчет финансового ущерба (Rule Violations & Financial Drag).
        """
        matrix = AnalyticsService.calculate_rule_violation_matrix(trades)
        rules = matrix["rules"]
        grade = matrix["discipline_grade"]
        color = matrix["grade_color"]
        insight = matrix["discipline_insight"]

        icon_map = {
            "NO_STOP_LOSS": ft.Icons.SHIELD_OUTLINED,
            "CHASING_FOMO": ft.Icons.ROCKET_LAUNCH_ROUNDED,
            "REVENGE_TRADING": ft.Icons.LOCAL_FIRE_DEPARTMENT_ROUNDED,
            "EARLY_EXIT": ft.Icons.TIMER_OUTLINED,
            "OVER_LEVERAGED": ft.Icons.SCALE_ROUNDED,
            "COUNTER_TREND": ft.Icons.SWAP_CALLS_ROUNDED,
        }

        rule_cards = []
        for r in rules:
            r_icon = icon_map.get(r["key"], ft.Icons.WARNING_AMBER_ROUNDED)
            cnt = r["count"]
            loss_val = r["dollar_loss"]
            sev = r["severity"]

            sev_color = "#DC2626" if sev == "CRITICAL" else ("#F59E0B" if sev == "HIGH" else ("#38BDF8" if sev == "MODERATE" else "#10B981"))
            sev_label = "КРИТИЧНО" if sev == "CRITICAL" else ("ВЫСОКИЙ" if sev == "HIGH" else ("УМЕРЕННЫЙ" if sev == "MODERATE" else "ЧИСТО"))

            sev_chip = ft.Container(
                content=ft.Text(sev_label, size=9, weight=ft.FontWeight.BOLD, color=sev_color, font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.12, sev_color),
                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, ft.Colors.with_opacity(0.3, sev_color)),
            )

            rc = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Container(
                                            content=ft.Icon(r_icon, size=15, color=r["color"]),
                                            padding=5,
                                            bgcolor=ft.Colors.with_opacity(0.12, r["color"]),
                                            border_radius=RADIUS_SM,
                                        ),
                                        ft.Text(r["name"], size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ],
                                    spacing=7,
                                ),
                                sev_chip,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(height=2),
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text("Ущерб", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"-${loss_val:,.2f}" if loss_val > 0 else "$0.00", size=13, weight=ft.FontWeight.BOLD, color=LOSS if loss_val > 0 else PROFIT, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Нарушений", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{cnt} сд. ({r['violation_rate_pct']}%)", size=11, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Winrate", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{r['winrate']}%", size=11, weight=ft.FontWeight.W_600, color=TEXT_SECONDARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=10,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, ft.Colors.with_opacity(0.3, sev_color) if sev in ("CRITICAL", "HIGH") else BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 4},
            )
            rule_cards.append(rc)

        header_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.GAVEL_ROUNDED, size=13, color=color),
                    ft.Text(f"{matrix['rules_followed_rate_pct']}% дисциплина ({grade})", size=10, weight=ft.FontWeight.BOLD, color=color, font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, color),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, color)),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.GAVEL_ROUNDED, color="#F59E0B", size=18),
                                    ft.Text("Аудит соблюдения правил и штрафных утечек", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Rule Violations & Drag)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_chip,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=rule_cards, spacing=10, run_spacing=10),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.LIGHTBULB_OUTLINE_ROUNDED, size=13, color=TEXT_MUTED),
                                ft.Text(insight, size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, BORDER_SUBTLE),
                    ),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_mtf_alignment_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный анализ мульти-таймфрейм согласованности тренда (Multi-Timeframe Trend Alignment Matrix).
        """
        matrix = AnalyticsService.calculate_mtf_alignment_matrix(trades)
        alignments = matrix["alignments"]
        best_al = matrix["best_alignment"]
        insight = matrix["mtf_insight"]

        icon_map = {
            "TRIPLE_ALIGNED": ft.Icons.LAYERS_ROUNDED,
            "DOUBLE_ALIGNED": ft.Icons.FILTER_2_ROUNDED,
            "PULLBACK_COUNTER": ft.Icons.U_TURN_LEFT_ROUNDED,
            "CHOP_UNALIGNED": ft.Icons.CLOSE_ROUNDED,
        }

        cards = []
        for key in ["TRIPLE_ALIGNED", "DOUBLE_ALIGNED", "PULLBACK_COUNTER", "CHOP_UNALIGNED"]:
            al = alignments[key]
            is_best = (key == best_al and al["trades_count"] > 0)
            pnl_val = al["net_pnl"]
            pnl_color = PROFIT if pnl_val >= 0 else LOSS
            pnl_sign = "+" if pnl_val >= 0 else ""
            r_icon = icon_map.get(key, ft.Icons.AUTO_GRAPH_ROUNDED)

            leader_chip = ft.Container(
                content=ft.Text("TOP EDGE", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.15, ACCENT_PRIMARY),
                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, ft.Colors.with_opacity(0.4, ACCENT_PRIMARY)),
            ) if is_best else ft.Container()

            card_widget = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Container(
                                            content=ft.Icon(r_icon, size=15, color=al["color"]),
                                            padding=5,
                                            bgcolor=ft.Colors.with_opacity(0.12, al["color"]),
                                            border_radius=RADIUS_SM,
                                        ),
                                        ft.Column(
                                            controls=[
                                                ft.Text(al["name"], size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                                ft.Text(al["sub"], size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                                            ],
                                            spacing=1,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                                leader_chip,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(height=4),
                        ft.ProgressBar(
                            value=al["winrate"] / 100.0 if al["trades_count"] > 0 else 0.0,
                            color=al["color"],
                            bgcolor=SURFACE_2,
                            height=4,
                            border_radius=RADIUS_SM,
                        ),
                        ft.Container(height=4),
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text("Net PnL", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{pnl_sign}${pnl_val:,.2f}", size=13, weight=ft.FontWeight.BOLD, color=pnl_color, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Winrate", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{al['winrate']}% ({al['trades_count']} сд.)", size=11, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Profit Factor", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{al['profit_factor']:.2f}", size=11, weight=ft.FontWeight.W_600, color=TEXT_SECONDARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, ft.Colors.with_opacity(0.35, al["color"]) if is_best else BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            )
            cards.append(card_widget)

        header_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.LAYERS_ROUNDED, size=13, color="#8B5CF6"),
                    ft.Text(f"Edge Ratio: {matrix['mtf_edge_ratio']}x", size=10, weight=ft.FontWeight.BOLD, color="#8B5CF6", font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, "#8B5CF6"),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, "#8B5CF6")),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.LAYERS_ROUNDED, color="#8B5CF6", size=18),
                                    ft.Text("Мульти-таймфрейм согласованность тренда", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(MTF Alignment Matrix)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_chip,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=cards, spacing=10, run_spacing=10),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.LIGHTBULB_OUTLINE_ROUNDED, size=13, color=TEXT_MUTED),
                                ft.Text(insight, size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, BORDER_SUBTLE),
                    ),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_compliance_routine_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный анализ соблюдения чек-листа перед входом в сделку и регламента (Pre-Trade Routine & Checklist Compliance).
        """
        matrix = AnalyticsService.calculate_compliance_routine_matrix(trades)
        brackets = matrix["brackets"]
        crits = matrix["criteria_compliance"]
        grade = matrix["compliance_grade"]
        color = matrix["grade_color"]
        insight = matrix["compliance_insight"]

        bracket_cards = []
        for key in ["HIGH", "MODERATE", "LOW"]:
            b = brackets[key]
            pnl_val = b["net_pnl"]
            pnl_color = PROFIT if pnl_val >= 0 else LOSS
            pnl_sign = "+" if pnl_val >= 0 else ""

            b_card = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text(b["name"], size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text(f"{b['trades_count']} сд.", size=9, weight=ft.FontWeight.BOLD, color=b["color"], font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.14, b["color"]),
                                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                    border_radius=RADIUS_SM,
                                    border=ft.border.all(1, ft.Colors.with_opacity(0.35, b["color"])),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(height=2),
                        ft.ProgressBar(
                            value=b["winrate"] / 100.0 if b["trades_count"] > 0 else 0.0,
                            color=b["color"],
                            bgcolor=SURFACE_2,
                            height=4,
                            border_radius=RADIUS_SM,
                        ),
                        ft.Container(height=2),
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text("Net PnL", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{pnl_sign}${pnl_val:,.2f}", size=13, weight=ft.FontWeight.BOLD, color=pnl_color, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Winrate", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{b['winrate']}%", size=11, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Profit Factor", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{b['profit_factor']:.2f}", size=11, weight=ft.FontWeight.W_600, color=TEXT_SECONDARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, ft.Colors.with_opacity(0.35, b["color"]) if key == "HIGH" else BORDER_SUBTLE),
                col={"xs": 12, "sm": 4},
            )
            bracket_cards.append(b_card)

        # 4 компактных критерия чек-листа в ряд
        crit_widgets = [
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text("Стоп-лосс", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Text(f"{crits.get('STOP_LOSS', 0.0):.0f}%", size=10, weight=ft.FontWeight.BOLD, color=PROFIT, font_family=FONT_MONO),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.ProgressBar(value=crits.get("STOP_LOSS", 0.0) / 100.0, color=PROFIT, bgcolor=SURFACE_1, height=4, border_radius=RADIUS_SM),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=8,
                border_radius=RADIUS_SM,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 6, "sm": 3},
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text("R:R >= 2.0", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Text(f"{crits.get('RR_RATIO', 0.0):.0f}%", size=10, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.ProgressBar(value=crits.get("RR_RATIO", 0.0) / 100.0, color=ACCENT_PRIMARY, bgcolor=SURFACE_1, height=4, border_radius=RADIUS_SM),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=8,
                border_radius=RADIUS_SM,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 6, "sm": 3},
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text("Самоконтроль", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Text(f"{crits.get('EMOTION_CONTROL', 0.0):.0f}%", size=10, weight=ft.FontWeight.BOLD, color="#38BDF8", font_family=FONT_MONO),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.ProgressBar(value=crits.get("EMOTION_CONTROL", 0.0) / 100.0, color="#38BDF8", bgcolor=SURFACE_1, height=4, border_radius=RADIUS_SM),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=8,
                border_radius=RADIUS_SM,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 6, "sm": 3},
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text("Сетап-триггер", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Text(f"{crits.get('SETUP_TRIGGER', 0.0):.0f}%", size=10, weight=ft.FontWeight.BOLD, color="#A855F7", font_family=FONT_MONO),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.ProgressBar(value=crits.get("SETUP_TRIGGER", 0.0) / 100.0, color="#A855F7", bgcolor=SURFACE_1, height=4, border_radius=RADIUS_SM),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=8,
                border_radius=RADIUS_SM,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 6, "sm": 3},
            ),
        ]

        header_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECKLIST_ROUNDED, size=13, color=color),
                    ft.Text(f"{matrix['avg_compliance_pct']}% Регламент ({grade})", size=10, weight=ft.FontWeight.BOLD, color=color, font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, color),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, color)),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.CHECKLIST_ROUNDED, color="#10B981", size=18),
                                    ft.Text("Соблюдение чек-листа и торгового регламента", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Pre-Trade Compliance)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_chip,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=bracket_cards, spacing=10, run_spacing=10),
                    ft.Container(height=2),
                    ft.ResponsiveRow(controls=crit_widgets, spacing=8, run_spacing=8),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.LIGHTBULB_OUTLINE_ROUNDED, size=13, color=TEXT_MUTED),
                                ft.Text(insight, size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, BORDER_SUBTLE),
                    ),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_session_overlap_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный анализ окон ликвидности и перекрытия торговых сессий (Market Session Overlap Alpha Matrix).
        """
        matrix = AnalyticsService.calculate_session_overlap_matrix(trades)
        windows = matrix["windows"]
        best_w = matrix["best_window"]
        insight = matrix["overlap_insight"]

        icon_map = {
            "LONDON_NY_OVERLAP": ft.Icons.PUBLIC_ROUNDED,
            "ASIA_LONDON_TRANSITION": ft.Icons.WB_TWILIGHT_ROUNDED,
            "NY_AFTERNOON_CLOSE": ft.Icons.WB_SUNNY_ROUNDED,
            "OFF_PEAK_CHOP": ft.Icons.BEDTIME_ROUNDED,
        }

        cards = []
        for key in ["LONDON_NY_OVERLAP", "ASIA_LONDON_TRANSITION", "NY_AFTERNOON_CLOSE", "OFF_PEAK_CHOP"]:
            w = windows[key]
            is_best = (key == best_w and w["trades_count"] > 0)
            pnl_val = w["net_pnl"]
            pnl_color = PROFIT if pnl_val >= 0 else LOSS
            pnl_sign = "+" if pnl_val >= 0 else ""
            w_icon = icon_map.get(key, ft.Icons.AUTO_GRAPH_ROUNDED)

            leader_chip = ft.Container(
                content=ft.Text("TOP WINDOW", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.15, ACCENT_PRIMARY),
                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, ft.Colors.with_opacity(0.4, ACCENT_PRIMARY)),
            ) if is_best else ft.Container()

            card_widget = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Container(
                                            content=ft.Icon(w_icon, size=15, color=w["color"]),
                                            padding=5,
                                            bgcolor=ft.Colors.with_opacity(0.12, w["color"]),
                                            border_radius=RADIUS_SM,
                                        ),
                                        ft.Column(
                                            controls=[
                                                ft.Text(w["name"], size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                                ft.Text(f"{w['time_span']} • {w['desc']}", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                                            ],
                                            spacing=1,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                                leader_chip,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(height=4),
                        ft.ProgressBar(
                            value=w["winrate"] / 100.0 if w["trades_count"] > 0 else 0.0,
                            color=w["color"],
                            bgcolor=SURFACE_2,
                            height=4,
                            border_radius=RADIUS_SM,
                        ),
                        ft.Container(height=4),
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text("Net PnL", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{pnl_sign}${pnl_val:,.2f}", size=13, weight=ft.FontWeight.BOLD, color=pnl_color, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Winrate", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{w['winrate']}% ({w['trades_count']} сд.)", size=11, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Profit Factor", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{w['profit_factor']:.2f}", size=11, weight=ft.FontWeight.W_600, color=TEXT_SECONDARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, ft.Colors.with_opacity(0.35, w["color"]) if is_best else BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            )
            cards.append(card_widget)

        header_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.PUBLIC_ROUNDED, size=13, color="#0284C7"),
                    ft.Text(f"Alpha: {matrix['overlap_alpha_ratio']}x", size=10, weight=ft.FontWeight.BOLD, color="#0284C7", font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, "#0284C7"),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, "#0284C7")),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.PUBLIC_ROUNDED, color="#0284C7", size=18),
                                    ft.Text("Окна ликвидности и перекрытие сессий", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Session Overlap Alpha)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_chip,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=cards, spacing=10, run_spacing=10),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.LIGHTBULB_OUTLINE_ROUNDED, size=13, color=TEXT_MUTED),
                                ft.Text(insight, size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, BORDER_SUBTLE),
                    ),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_setup_grading_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный анализ качества сетапов и градация по плейбуку (Playbook Setup Quality Grading Matrix).
        """
        matrix = AnalyticsService.calculate_setup_grading_matrix(trades)
        tiers = matrix["tiers"]
        best_t = matrix["best_tier"]
        insight = matrix["setup_grading_insight"]

        icon_map = {
            "A_PLUS": ft.Icons.VERIFIED_ROUNDED,
            "A_TIER": ft.Icons.CHECK_CIRCLE_ROUNDED,
            "B_TIER": ft.Icons.REMOVE_CIRCLE_OUTLINE_ROUNDED,
            "C_TIER": ft.Icons.CANCEL_ROUNDED,
        }

        cards = []
        for key in ["A_PLUS", "A_TIER", "B_TIER", "C_TIER"]:
            t = tiers[key]
            is_best = (key == best_t and t["trades_count"] > 0)
            pnl_val = t["net_pnl"]
            pnl_color = PROFIT if pnl_val >= 0 else LOSS
            pnl_sign = "+" if pnl_val >= 0 else ""
            t_icon = icon_map.get(key, ft.Icons.STAR_ROUNDED)

            leader_chip = ft.Container(
                content=ft.Text("PRIME TIER", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.15, ACCENT_PRIMARY),
                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, ft.Colors.with_opacity(0.4, ACCENT_PRIMARY)),
            ) if is_best else ft.Container()

            card_widget = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Container(
                                            content=ft.Icon(t_icon, size=15, color=t["color"]),
                                            padding=5,
                                            bgcolor=ft.Colors.with_opacity(0.12, t["color"]),
                                            border_radius=RADIUS_SM,
                                        ),
                                        ft.Column(
                                            controls=[
                                                ft.Text(t["name"], size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                                ft.Text(t["sub"], size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                                            ],
                                            spacing=1,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                                leader_chip,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(height=4),
                        ft.ProgressBar(
                            value=t["winrate"] / 100.0 if t["trades_count"] > 0 else 0.0,
                            color=t["color"],
                            bgcolor=SURFACE_2,
                            height=4,
                            border_radius=RADIUS_SM,
                        ),
                        ft.Container(height=4),
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text("Net PnL", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{pnl_sign}${pnl_val:,.2f}", size=13, weight=ft.FontWeight.BOLD, color=pnl_color, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Winrate", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{t['winrate']}% ({t['trades_count']} сд.)", size=11, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Profit Factor", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{t['profit_factor']:.2f}", size=11, weight=ft.FontWeight.W_600, color=TEXT_SECONDARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, ft.Colors.with_opacity(0.35, t["color"]) if is_best else BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            )
            cards.append(card_widget)

        header_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.VERIFIED_ROUNDED, size=13, color="#7C5CFF"),
                    ft.Text(f"A/A+ Дисциплина: {matrix['a_tier_discipline_pct']}%", size=10, weight=ft.FontWeight.BOLD, color="#7C5CFF", font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, "#7C5CFF"),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, "#7C5CFF")),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.VERIFIED_ROUNDED, color="#7C5CFF", size=18),
                                    ft.Text("Градация качества сетапов", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Playbook Setup Grading)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_chip,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=cards, spacing=10, run_spacing=10),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.LIGHTBULB_OUTLINE_ROUNDED, size=13, color=TEXT_MUTED),
                                ft.Text(insight, size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, BORDER_SUBTLE),
                    ),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_tag_attribution_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный анализ атрибуции торговых тегов и факторов (Trade Tag Performance Cloud & Factor Attribution).
        """
        matrix = AnalyticsService.calculate_tag_attribution_matrix(trades)
        tag_list = matrix["tags"]
        top_prof = matrix["top_profitable_tag"]
        top_drag = matrix["top_drag_tag"]
        most_freq = matrix["most_frequent_tag"]
        unique_cnt = matrix["unique_tags_count"]
        insight = matrix["attribution_insight"]

        summary_chips = [
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.TRENDING_UP_ROUNDED, size=13, color=PROFIT),
                        ft.Text(f"Драйвер: #{top_prof}" if top_prof else "Драйвер: —", size=10, weight=ft.FontWeight.BOLD, color=PROFIT, font_family=FONT_MONO),
                    ],
                    spacing=4,
                    tight=True,
                ),
                bgcolor=ft.Colors.with_opacity(0.12, PROFIT),
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, ft.Colors.with_opacity(0.3, PROFIT)),
            ),
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.TRENDING_DOWN_ROUNDED, size=13, color=LOSS),
                        ft.Text(f"Утечка: #{top_drag}" if top_drag else "Утечка: —", size=10, weight=ft.FontWeight.BOLD, color=LOSS, font_family=FONT_MONO),
                    ],
                    spacing=4,
                    tight=True,
                ),
                bgcolor=ft.Colors.with_opacity(0.12, LOSS),
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, ft.Colors.with_opacity(0.3, LOSS)),
            ),
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.TAG_ROUNDED, size=13, color=ACCENT_PRIMARY),
                        ft.Text(f"Факторов: {unique_cnt}", size=10, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                    ],
                    spacing=4,
                    tight=True,
                ),
                bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, ft.Colors.with_opacity(0.3, ACCENT_PRIMARY)),
            ),
        ]

        tag_cards = []
        for item in tag_list[:8]:  # Топ-8 ключевых факторов
            t_name = item["tag"]
            t_color = item["color"]
            pnl_val = item["net_pnl"]
            pnl_sign = "+" if pnl_val >= 0 else ""
            pnl_color = PROFIT if pnl_val >= 0 else LOSS

            card_w = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Container(
                                            content=ft.Icon(ft.Icons.LABEL_ROUNDED, size=13, color=t_color),
                                            padding=4,
                                            bgcolor=ft.Colors.with_opacity(0.12, t_color),
                                            border_radius=RADIUS_SM,
                                        ),
                                        ft.Text(f"#{t_name}", size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                    ],
                                    spacing=6,
                                ),
                                ft.Container(
                                    content=ft.Text(f"{item['share_pct']}% сделок", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                                    bgcolor=SURFACE_1,
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(height=3),
                        ft.ProgressBar(
                            value=item["winrate"] / 100.0 if item["trades_count"] > 0 else 0.0,
                            color=t_color,
                            bgcolor=SURFACE_1,
                            height=4,
                            border_radius=RADIUS_SM,
                        ),
                        ft.Container(height=3),
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text("Net PnL", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{pnl_sign}${pnl_val:,.2f}", size=12, weight=ft.FontWeight.BOLD, color=pnl_color, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Winrate", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{item['winrate']}% ({item['trades_count']})", size=11, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text("Profit Factor", size=9, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                        ft.Text(f"{item['profit_factor']:.2f}", size=11, weight=ft.FontWeight.W_600, color=TEXT_SECONDARY, font_family=FONT_MONO),
                                    ],
                                    spacing=1,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=2,
                ),
                bgcolor=SURFACE_2,
                padding=10,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, ft.Colors.with_opacity(0.35, t_color) if item["category"] in ("PROFIT_DRIVER", "DRAWDOWN_LEAK") else BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            )
            tag_cards.append(card_w)

        if not tag_cards:
            tag_cards.append(
                ft.Container(
                    content=ft.Text("Нет размеченных сделок или хэштегов в заметках для анализа атрибуции.", size=11, color=TEXT_MUTED),
                    padding=10,
                    col=12,
                )
            )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.LOCAL_OFFER_ROUNDED, color="#EC4899", size=18),
                                    ft.Text("Атрибуция тегов и факторов сетапов", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Tag Performance Cloud)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            ft.Row(controls=summary_chips, spacing=6),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=tag_cards, spacing=10, run_spacing=10),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.INSIGHTS_ROUNDED, size=13, color=TEXT_MUTED),
                                ft.Text(insight, size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, BORDER_SUBTLE),
                    ),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_rolling_edge_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный аудит устойчивости преимущества и детектор затухания альфы (Rolling 30D Edge Momentum).
        """
        matrix = AnalyticsService.calculate_rolling_edge_matrix(trades, window_days=30)
        curr = matrix["current_window"]
        prior = matrix["prior_window"]
        mom = matrix["edge_momentum"]
        mom_color = matrix["momentum_color"]
        decay_alert = matrix["decay_alert"]
        insight = matrix["edge_insight"]

        mom_labels = {
            "EXPANDING_EDGE": "РАСШИРЕНИЕ АЛЬФЫ (EXPANDING)",
            "STABLE_EDGE": "СТАБИЛЬНОЕ ПРЕИМУЩЕСТВО",
            "DECAYING_EDGE": "ЗАТУХАНИЕ ПРЕИМУЩЕСТВА (DECAY)",
            "INSUFFICIENT_DATA": "МАЛО ДАННЫХ",
        }
        status_label = mom_labels.get(mom, mom)

        header_badge = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.WARNING_AMBER_ROUNDED if decay_alert else (ft.Icons.TRENDING_UP_ROUNDED if mom == "EXPANDING_EDGE" else ft.Icons.CHECK_CIRCLE_ROUNDED),
                        size=13,
                        color=mom_color,
                    ),
                    ft.Text(status_label, size=10, weight=ft.FontWeight.BOLD, color=mom_color, font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, mom_color),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, mom_color)),
        )

        def make_delta_badge(delta: float, is_pct: bool = False, is_pnl: bool = False) -> ft.Container:
            col = PROFIT if delta > 0 else (LOSS if delta < 0 else TEXT_MUTED)
            sign = "+" if delta > 0 else ""
            fmt = f"{sign}${delta:,.2f}" if is_pnl else (f"{sign}{delta:.1f}%" if is_pct else f"{sign}{delta:+.2f}")
            return ft.Container(
                content=ft.Text(f"Δ {fmt}", size=9, weight=ft.FontWeight.BOLD, color=col, font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.12, col),
                padding=ft.padding.symmetric(horizontal=5, vertical=2),
                border_radius=RADIUS_SM,
            )

        kpis = [
            # 1. Rolling Sharpe
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Rolling 30D Sharpe", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                make_delta_badge(matrix["sharpe_delta"]),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{curr['sharpe']:.2f}", size=18, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
                        ft.Text(f"Базовый период: {prior['sharpe']:.2f}", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 2. Rolling Winrate
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Rolling 30D Winrate", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                make_delta_badge(matrix["winrate_delta"], is_pct=True),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{curr['winrate']}%", size=18, weight=ft.FontWeight.BOLD, color=PROFIT if curr['winrate'] >= 50.0 else LOSS, font_family=FONT_MONO),
                        ft.ProgressBar(
                            value=curr["winrate"] / 100.0,
                            color=PROFIT if curr['winrate'] >= 50.0 else LOSS,
                            bgcolor=SURFACE_1,
                            height=4,
                            border_radius=RADIUS_SM,
                        ),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 3. Rolling Net PnL
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Rolling 30D Net PnL", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                make_delta_badge(matrix["pnl_delta"], is_pnl=True),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{'+' if curr['net_pnl'] >= 0 else ''}${curr['net_pnl']:,.2f}", size=18, weight=ft.FontWeight.BOLD, color=PROFIT if curr['net_pnl'] >= 0 else LOSS, font_family=FONT_MONO),
                        ft.Text(f"Пред. 30 дней: ${prior['net_pnl']:,.2f}", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 4. Activity & Profit Factor
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Сделок за 30 дней", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text(f"PF: {curr['profit_factor']:.2f}", size=9, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
                                    bgcolor=SURFACE_1,
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{curr['trades_count']} сделок", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                        ft.Text(f"Базовый период: {prior['trades_count']} сделок", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
        ]

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.TIMELINE_ROUNDED, color="#38BDF8", size=18),
                                    ft.Text("Динамика и устойчивость преимущества", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Rolling 30D Edge Momentum)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_badge,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=kpis, spacing=10, run_spacing=10),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.LIGHTBULB_OUTLINE_ROUNDED if not decay_alert else ft.Icons.WARNING_ROUNDED, size=13, color=mom_color),
                                ft.Text(insight, size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, ft.Colors.with_opacity(0.35, mom_color) if decay_alert else BORDER_SUBTLE),
                    ),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_prop_consistency_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный радар консистентности и оценка готовности к проп-челленджам (Prop Firm Consistency Radar).
        """
        matrix = AnalyticsService.calculate_prop_consistency_radar(trades)
        score = matrix["consistency_score"]
        status = matrix["readiness_status"]
        status_color = matrix["status_color"]
        insight = matrix["consistency_insight"]

        status_labels = {
            "FUNDED_READY": "ГОТОВ К ЧЕЛЛЕНДЖУ (FUNDED READY)",
            "QUALIFIED": "КВАЛИФИЦИРОВАН (QUALIFIED)",
            "LOTTERY_DEPENDENCY": "РИСК: СЛУЧАЙНЫЙ ВЫБРОС",
            "HIGH_VARIANCE": "ВЫСОКАЯ ДИСПЕРСИЯ",
            "NO_DATA": "НЕТ ДАННЫХ",
        }
        status_text = status_labels.get(status, status)

        header_badge = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.VERIFIED_ROUNDED if status in ("FUNDED_READY", "QUALIFIED") else ft.Icons.SHIELD_ROUNDED,
                        size=13,
                        color=status_color,
                    ),
                    ft.Text(f"{status_text} • {score}%", size=10, weight=ft.FontWeight.BOLD, color=status_color, font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, status_color),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, status_color)),
        )

        kpis = [
            # 1. Overall Consistency Score
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Consistency Score", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text("ЦЕЛЬ >= 80%", size=9, weight=ft.FontWeight.BOLD, color=status_color, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, status_color),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{score}%", size=18, weight=ft.FontWeight.BOLD, color=status_color, font_family=FONT_MONO),
                        ft.ProgressBar(
                            value=score / 100.0,
                            color=status_color,
                            bgcolor=SURFACE_1,
                            height=4,
                            border_radius=RADIUS_SM,
                        ),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 2. Single Day Profit Share
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Доля лучшего дня", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text("PASS" if matrix["day_concentration_pass"] else "FAIL", size=9, weight=ft.FontWeight.BOLD, color=PROFIT if matrix["day_concentration_pass"] else LOSS, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, PROFIT if matrix["day_concentration_pass"] else LOSS),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{matrix['best_day_share_pct']}%", size=18, weight=ft.FontWeight.BOLD, color=PROFIT if matrix["day_concentration_pass"] else LOSS, font_family=FONT_MONO),
                        ft.Text(f"Лимит FTMO: <33% • +${matrix['best_day_pnl']:,.2f}", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 3. Single Trade Profit Share
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Доля лучшей сделки", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text("PASS" if matrix["trade_concentration_pass"] else "FAIL", size=9, weight=ft.FontWeight.BOLD, color=PROFIT if matrix["trade_concentration_pass"] else LOSS, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, PROFIT if matrix["trade_concentration_pass"] else LOSS),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{matrix['best_trade_share_pct']}%", size=18, weight=ft.FontWeight.BOLD, color=PROFIT if matrix["trade_concentration_pass"] else LOSS, font_family=FONT_MONO),
                        ft.Text(f"Лимит: <25% • +${matrix['best_trade_pnl']:,.2f}", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 4. Sizing Uniformity & Daily DD
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Стабильность сайзинга", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text("СТАБИЛЕН" if matrix["sizing_uniformity_pass"] else "НЕСТАБИЛЕН", size=9, weight=ft.FontWeight.BOLD, color=PROFIT if matrix["sizing_uniformity_pass"] else WARNING_TILT, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, PROFIT if matrix["sizing_uniformity_pass"] else WARNING_TILT),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"CV {matrix['lot_size_cv']:.2f}", size=18, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
                        ft.Text(f"Макс. дневной убыток: -${matrix['max_daily_loss']:,.2f}", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
        ]

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.SHIELD_ROUNDED, color="#10B981", size=18),
                                    ft.Text("Готовность к проп-челленджам и радар консистентности", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Prop Firm Consistency Radar)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_badge,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=kpis, spacing=10, run_spacing=10),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.SECURITY_ROUNDED if status in ("FUNDED_READY", "QUALIFIED") else ft.Icons.WARNING_ROUNDED, size=13, color=status_color),
                                ft.Text(insight, size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, ft.Colors.with_opacity(0.35, status_color) if status in ("LOTTERY_DEPENDENCY", "HIGH_VARIANCE") else BORDER_SUBTLE),
                    ),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_order_placement_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный аудит эффективности размещения Stop Loss и Take Profit (Edgewonk Order Placement Audit).
        """
        matrix = AnalyticsService.calculate_order_placement_efficiency(trades)
        grade = matrix["placement_grade"]
        grade_color = matrix["grade_color"]
        capture_pct = matrix["target_capture_efficiency_pct"]
        premature_drag = matrix["premature_stopout_drag"]
        early_leak = matrix["early_exit_leakage"]
        sl_buffer = matrix["optimal_sl_buffer_recommendation"]
        insight = matrix["placement_insight"]

        header_badge = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.GPS_FIXED_ROUNDED, size=13, color=grade_color),
                    ft.Text(f"ГРЕЙД: {grade} • Захват: {capture_pct}%", size=10, weight=ft.FontWeight.BOLD, color=grade_color, font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, grade_color),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, grade_color)),
        )

        kpis = [
            # 1. Target Capture Efficiency
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Эффективность тейков", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text("MFE ЗАХВАТ", size=9, weight=ft.FontWeight.BOLD, color=grade_color, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, grade_color),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{capture_pct}%", size=18, weight=ft.FontWeight.BOLD, color=grade_color, font_family=FONT_MONO),
                        ft.ProgressBar(
                            value=capture_pct / 100.0,
                            color=grade_color,
                            bgcolor=SURFACE_1,
                            height=4,
                            border_radius=RADIUS_SM,
                        ),
                    ],
                    spacing=4,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 2. Premature Stop-Out Drag
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Преждевременные стопы", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text(f"{matrix['premature_stopout_count']} сделок", size=9, weight=ft.FontWeight.BOLD, color=LOSS if premature_drag > 0 else PROFIT, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, LOSS if premature_drag > 0 else PROFIT),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"-${premature_drag:,.2f}" if premature_drag > 0 else "$0.00", size=18, weight=ft.FontWeight.BOLD, color=LOSS if premature_drag > 0 else PROFIT, font_family=FONT_MONO),
                        ft.Text("Убыток до хода к цели", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 3. Early Exit Leakage
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Утечка ранних выходов", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text("НА СТОЛЕ", size=9, weight=ft.FontWeight.BOLD, color=WARNING_TILT, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, WARNING_TILT),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"${early_leak:,.2f}", size=18, weight=ft.FontWeight.BOLD, color=WARNING_TILT, font_family=FONT_MONO),
                        ft.Text("Недополученный профит MFE", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 4. SL Buffer Recommendation
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Буфер Stop Loss", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text("КАЛИБРОВКА", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(sl_buffer, size=15, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
                        ft.Text("Рекомендация по ATR буферу", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
        ]

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.GPS_FIXED_ROUNDED, color="#A855F7", size=18),
                                    ft.Text("Эффективность размещения Stop Loss и Take Profit", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Edgewonk Placement Audit)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_badge,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=kpis, spacing=10, run_spacing=10),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=13, color=grade_color),
                                ft.Text(insight, size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, BORDER_SUBTLE),
                    ),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_factor_ic_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный квантовый аудит предсказательной силы факторов альфы (Factor Information Coefficient & Alpha Persistence).
        """
        matrix = AnalyticsService.calculate_factor_information_coefficient(trades)
        factors = matrix["factors"]
        top_f = matrix["top_factor"]
        top_ic = matrix["top_factor_ic"]
        factor_ir = matrix["factor_ir"]
        insight = matrix["ic_insight"]

        header_badge = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.QUERY_STATS_ROUNDED, size=13, color="#38BDF8"),
                    ft.Text(f"Топ-фактор: {top_f or '—'} (IC {top_ic:+}) • Factor IR: {factor_ir}", size=10, weight=ft.FontWeight.BOLD, color="#38BDF8", font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, "#38BDF8"),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, "#38BDF8")),
        )

        cards = []
        for f in factors:
            ic_val = f["ic"]
            ic_color = f["color"]
            card_w = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text(f["factor"], size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text(f["rating"], size=9, weight=ft.FontWeight.BOLD, color=ic_color, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, ic_color),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f["description"], size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Row(
                            controls=[
                                ft.Text(f"Rank IC: {ic_val:+,.2f}", size=16, weight=ft.FontWeight.BOLD, color=ic_color, font_family=FONT_MONO),
                                ft.Icon(
                                    ft.Icons.TRENDING_UP_ROUNDED if ic_val > 0 else (ft.Icons.TRENDING_DOWN_ROUNDED if ic_val < 0 else ft.Icons.REMOVE_ROUNDED),
                                    size=16,
                                    color=ic_color,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, ft.Colors.with_opacity(0.35, ic_color) if f["category"] in ("ELITE_ALPHA", "INVERSE_DRAG") else BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            )
            cards.append(card_w)

        if not cards:
            cards.append(
                ft.Container(
                    content=ft.Text("Нет данных по сделкам для расчета ранговой корреляции факторов.", size=11, color=TEXT_MUTED),
                    padding=10,
                    col=12,
                )
            )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.QUERY_STATS_ROUNDED, color="#38BDF8", size=18),
                                    ft.Text("Коэффициент предсказательной силы факторов", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Alpha Factor Information Coefficient)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_badge,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=cards, spacing=10, run_spacing=10),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.INSIGHTS_ROUNDED, size=13, color="#38BDF8"),
                                ft.Text(insight, size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, BORDER_SUBTLE),
                    ),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_trade_management_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивный аудит эффективности управления позицией (TraderSync Trade Management Audit).
        """
        matrix = AnalyticsService.calculate_trade_management_matrix(trades)
        delta = matrix["management_alpha_delta"]
        has_pos = matrix["has_positive_alpha"]
        alpha_col = matrix["alpha_color"]
        be_cnt = matrix["be_choke_count"]
        be_cost = matrix["be_choke_opportunity_cost"]
        optimal_style = matrix["optimal_archetype"]
        insight = matrix["management_insight"]
        archs = matrix["archetypes"]

        sign = "+" if delta >= 0 else ""
        header_badge = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.TRENDING_UP_ROUNDED if has_pos else ft.Icons.TRENDING_DOWN_ROUNDED,
                        size=13,
                        color=alpha_col,
                    ),
                    ft.Text(f"Альфа управления: {sign}${delta:,.2f}", size=10, weight=ft.FontWeight.BOLD, color=alpha_col, font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, alpha_col),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, alpha_col)),
        )

        sf_data = archs.get("SET_AND_FORGET", {"trades_count": 0, "net_pnl": 0.0, "winrate": 0.0})
        scale_data = archs.get("SCALED_MANAGEMENT", {"trades_count": 0, "net_pnl": 0.0, "winrate": 0.0})

        kpis = [
            # 1. Management Alpha Delta
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Альфа / Драг управления", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text("ALPHA" if has_pos else "DRAG", size=9, weight=ft.FontWeight.BOLD, color=alpha_col, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, alpha_col),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{sign}${delta:,.2f}", size=18, weight=ft.FontWeight.BOLD, color=alpha_col, font_family=FONT_MONO),
                        ft.Text("Разница против Set & Forget", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 2. Premature Breakeven Choke
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Удушение в Б/У (BE Choke)", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text(f"{be_cnt} сделок", size=9, weight=ft.FontWeight.BOLD, color=LOSS if be_cost > 0 else PROFIT, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, LOSS if be_cost > 0 else PROFIT),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"-${be_cost:,.2f}" if be_cost > 0 else "$0.00", size=18, weight=ft.FontWeight.BOLD, color=LOSS if be_cost > 0 else PROFIT, font_family=FONT_MONO),
                        ft.Text("Упущенный профит после раннего Б/У", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 3. Scaled & Partial Exits
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Частичные фиксации (Scale Out)", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text(f"{scale_data['winrate']}% WR", size=9, weight=ft.FontWeight.BOLD, color=PROFIT if scale_data['winrate'] >= 50 else TEXT_MUTED, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, PROFIT if scale_data['winrate'] >= 50 else TEXT_MUTED),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{'+' if scale_data['net_pnl'] >= 0 else ''}${scale_data['net_pnl']:,.2f}", size=18, weight=ft.FontWeight.BOLD, color=PROFIT if scale_data['net_pnl'] >= 0 else LOSS, font_family=FONT_MONO),
                        ft.Text(f"{scale_data['trades_count']} сделок с дроблением", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
            # 4. Optimal Archetype
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Оптимальный стиль", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text("LEADER", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(optimal_style, size=13, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(f"Set & Forget: ${sf_data['net_pnl']:,.2f} ({sf_data['trades_count']} сд.)", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"xs": 12, "sm": 6, "md": 3},
            ),
        ]

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.TUNE_ROUNDED, color="#7C5CFF", size=18),
                                    ft.Text("Эффективность управления позицией", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("(Trade Management Audit)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                                ],
                                spacing=8,
                            ),
                            header_badge,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=4),
                    ft.ResponsiveRow(controls=kpis, spacing=10, run_spacing=10),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.LIGHTBULB_OUTLINE_ROUNDED if has_pos else ft.Icons.WARNING_ROUNDED, size=13, color=alpha_col),
                                ft.Text(insight, size=11, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ],
                            spacing=6,
                        ),
                        bgcolor=SURFACE_2,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=RADIUS_SM,
                        border=ft.border.all(1, ft.Colors.with_opacity(0.35, alpha_col) if not has_pos else BORDER_SUBTLE),
                    ),
                ],
                spacing=6,
            ),
            bgcolor=SURFACE_1,
            padding=16,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_liquidity_sweep_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивная матрица снятия ликвидности и потока ордеров (TradeZella & Bookmap Order Flow Engine).
        """
        matrix = AnalyticsService.calculate_liquidity_sweep_matrix(trades)
        total = matrix["total_trades"]
        confl_cnt = matrix["confluence_trades_count"]
        sw_wr = matrix["sweep_winrate"]
        naive_wr = matrix["naive_winrate"]
        wr_alpha = matrix["winrate_alpha"]
        sw_pf = matrix["sweep_profit_factor"]
        sw_net = matrix["sweep_net_pnl"]
        naive_net = matrix["naive_net_pnl"]
        abs_eff = matrix["absorption_efficiency_pct"]
        top_arch = matrix["top_archetype"]
        archs = matrix["archetypes"]
        badge_col = matrix["badge_color"]
        insight = matrix["actionable_insight"]

        sign = "+" if wr_alpha >= 0 else ""
        header_badge = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.AUTO_GRAPH_ROUNDED if wr_alpha >= 0 else ft.Icons.WARNING_AMBER_ROUNDED,
                        size=13,
                        color=badge_col,
                    ),
                    ft.Text(f"Эдж ликвидности: {sign}{wr_alpha}% WR", size=10, weight=ft.FontWeight.BOLD, color=badge_col, font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, badge_col),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, badge_col)),
        )

        kpis = [
            # 1. Winrate Alpha
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Винрейт со снятием ликвидности", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text(f"{sign}{wr_alpha}%", size=9, weight=ft.FontWeight.BOLD, color=badge_col, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, badge_col),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{sw_wr:.1f}%", size=18, weight=ft.FontWeight.BOLD, color=badge_col, font_family=FONT_MONO),
                        ft.Text(f"Против {naive_wr:.1f}% у обычных пробоев", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"sm": 12, "md": 6, "lg": 3},
            ),
            # 2. Absorption Efficiency %
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Эффективность поглощения", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Icon(ft.Icons.SHIELD_ROUNDED, size=14, color="#38BDF8"),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{abs_eff:.1f}%", size=18, weight=ft.FontWeight.BOLD, color="#38BDF8", font_family=FONT_MONO),
                        ft.Text("Сделки без существенной просадки", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"sm": 12, "md": 6, "lg": 3},
            ),
            # 3. Sweep Net PnL vs Naive
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Net PnL со снятием ликвидности", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Text(f"{confl_cnt} сд.", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(
                            f"{'+' if sw_net >= 0 else ''}${sw_net:,.2f}",
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            color=PROFIT if sw_net >= 0 else LOSS,
                            font_family=FONT_MONO,
                        ),
                        ft.Text(f"Обычные входы: {'+' if naive_net >= 0 else ''}${naive_net:,.2f}", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"sm": 12, "md": 6, "lg": 3},
            ),
            # 4. Top Institutional Pattern
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Лучший паттерн потока ордеров", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text(f"PF {sw_pf:.2f}", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(top_arch.split("(")[0].strip(), size=15, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                        ft.Text("Максимальная доходность на сделку", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"sm": 12, "md": 6, "lg": 3},
            ),
        ]

        def _make_arch_chip(label: str, stats: dict, color: str) -> ft.Container:
            cnt = stats.get("count", 0)
            wr = stats.get("winrate", 0.0)
            pnl = stats.get("net_pnl", 0.0)
            pf = stats.get("profit_factor", 0.0)
            pnl_s = "+" if pnl >= 0 else ""

            return ft.Container(
                content=ft.Row(
                    [
                        ft.Container(width=6, height=6, border_radius=3, bgcolor=color),
                        ft.Text(label, size=11, color=TEXT_PRIMARY, weight=ft.FontWeight.W_600, font_family=FONT_FAMILY),
                        ft.Text(f"({cnt} сд.)", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                        ft.Text(f"WR {wr:.0f}%", size=10, weight=ft.FontWeight.BOLD, color=PROFIT if wr >= 50 else LOSS, font_family=FONT_MONO),
                        ft.Text(f"PF {pf:.2f}", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                        ft.Text(f"{pnl_s}${pnl:,.1f}", size=10, weight=ft.FontWeight.BOLD, color=PROFIT if pnl >= 0 else LOSS, font_family=FONT_MONO),
                    ],
                    spacing=8,
                    tight=True,
                ),
                bgcolor=SURFACE_3,
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, BORDER_SUBTLE),
            )

        arch_chips = ft.Row(
            controls=[
                _make_arch_chip("Sweep + Order Flow", archs.get("FULL_CONFLUENCE", {}), "#10B981"),
                _make_arch_chip("Liquidity Sweep Only", archs.get("SWEEP_ONLY", {}), "#38BDF8"),
                _make_arch_chip("Order Flow Imbalance", archs.get("FLOW_ONLY", {}), "#A855F7"),
                _make_arch_chip("Наивные пробои", archs.get("NAIVE_ENTRY", {}), "#64748B"),
            ],
            wrap=True,
            spacing=8,
            run_spacing=8,
        )

        insight_bar = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.LIGHTBULB_ROUNDED, size=15, color=badge_col),
                    ft.Text(
                        insight,
                        size=11,
                        color=TEXT_PRIMARY,
                        weight=ft.FontWeight.W_500,
                        font_family=FONT_FAMILY,
                        expand=True,
                    ),
                ],
                spacing=8,
            ),
            bgcolor=SURFACE_2,
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, badge_col)),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.WATERFALL_CHART_ROUNDED, color=ACCENT_PRIMARY, size=18),
                                    ft.Text("Матрица ликвидности & Footprint Order Flow", size=14, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Container(
                                        content=ft.Text("ORDER FLOW", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                        bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                        border_radius=4,
                                        border=ft.border.all(1, ft.Colors.with_opacity(0.3, ACCENT_PRIMARY)),
                                    ),
                                ],
                                spacing=8,
                            ),
                            header_badge,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(color=BORDER_SUBTLE, height=8),
                    ft.ResponsiveRow(controls=kpis, spacing=10, run_spacing=10),
                    ft.Container(height=4),
                    arch_chips,
                    ft.Container(height=2),
                    insight_bar,
                ],
                spacing=8,
            ),
            padding=16,
            bgcolor=SURFACE_1,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _build_broker_cost_drag_card(self, trades: List[Trade]) -> ft.Container:
        """
        Интерактивная декомпозиция издержек брокера, комиссий и скрытого проскальзывания (TradeMetria Cost Drag Engine).
        """
        matrix = AnalyticsService.calculate_broker_cost_drag_matrix(trades)
        total_drag = matrix["total_broker_drag"]
        total_comm = matrix["total_commissions"]
        total_swap = matrix["total_swap_fees"]
        total_slip = matrix["total_slippage"]
        fee_pct = matrix["fee_drag_pct"]
        avg_cost = matrix["avg_cost_per_trade"]
        vamp_cnt = matrix["vampire_strategies_count"]
        vamp_strats = matrix["vampire_strategies"]
        eff_grade = matrix["efficiency_grade"]
        grade_col = matrix["grade_color"]
        insight = matrix["actionable_insight"]

        header_badge = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.CHECK_CIRCLE_ROUNDED if eff_grade in ("EXCELLENT", "HEALTHY") else ft.Icons.WARNING_ROUNDED,
                        size=13,
                        color=grade_col,
                    ),
                    ft.Text(f"Драг издержек: {fee_pct}% ({eff_grade})", size=10, weight=ft.FontWeight.BOLD, color=grade_col, font_family=FONT_MONO),
                ],
                spacing=5,
                tight=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, grade_col),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, grade_col)),
        )

        kpis = [
            # 1. Total Broker Cost Drag
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Суммарный драг брокера", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text(f"-{fee_pct}%", size=9, weight=ft.FontWeight.BOLD, color=grade_col, font_family=FONT_MONO),
                                    bgcolor=ft.Colors.with_opacity(0.12, grade_col),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"-${total_drag:,.2f}", size=18, weight=ft.FontWeight.BOLD, color=grade_col, font_family=FONT_MONO),
                        ft.Text(f"Комиссии: ${total_comm:,.1f} • Своп: ${total_swap:,.1f}", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"sm": 12, "md": 6, "lg": 3},
            ),
            # 2. Avg Cost Per Trade
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Ср. расход на сделку", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Icon(ft.Icons.RECEIPT_LONG_ROUNDED, size=14, color="#38BDF8"),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"${avg_cost:,.2f}", size=18, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
                        ft.Text("Плата брокеру за вход/выход", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"sm": 12, "md": 6, "lg": 3},
            ),
            # 3. Vampire Strategies Count
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Вампир-сетапы", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Container(
                                    content=ft.Text(
                                        "В НОРМЕ" if vamp_cnt == 0 else f"{vamp_cnt} СЕТАПА",
                                        size=9,
                                        weight=ft.FontWeight.BOLD,
                                        color="#10B981" if vamp_cnt == 0 else "#EF4444",
                                        font_family=FONT_MONO,
                                    ),
                                    bgcolor=ft.Colors.with_opacity(0.12, "#10B981" if vamp_cnt == 0 else "#EF4444"),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=RADIUS_SM,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{vamp_cnt}", size=18, weight=ft.FontWeight.BOLD, color="#10B981" if vamp_cnt == 0 else "#EF4444", font_family=FONT_MONO),
                        ft.Text("В плюсе без учета сборов брокера", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"sm": 12, "md": 6, "lg": 3},
            ),
            # 4. Net Retained Capital %
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            [
                                ft.Text("Чистое сохранение прибыли", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY),
                                ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED, size=14, color="#10B981"),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"{max(0.0, 100.0 - fee_pct):.1f}%", size=18, weight=ft.FontWeight.BOLD, color="#10B981", font_family=FONT_MONO),
                        ft.Text("Остается трейдеру от валового профита", size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=3,
                ),
                bgcolor=SURFACE_2,
                padding=12,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
                col={"sm": 12, "md": 6, "lg": 3},
            ),
        ]

        def _make_cost_chip(title: str, amount: float, color: str, sub: str) -> ft.Container:
            return ft.Container(
                content=ft.Row(
                    [
                        ft.Container(width=6, height=6, border_radius=3, bgcolor=color),
                        ft.Text(title, size=11, color=TEXT_PRIMARY, weight=ft.FontWeight.W_600, font_family=FONT_FAMILY),
                        ft.Text(f"${amount:,.2f}", size=11, weight=ft.FontWeight.BOLD, color=color, font_family=FONT_MONO),
                        ft.Text(f"({sub})", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                    ],
                    spacing=8,
                    tight=True,
                ),
                bgcolor=SURFACE_3,
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                border_radius=RADIUS_SM,
                border=ft.border.all(1, BORDER_SUBTLE),
            )

        cost_chips = ft.Row(
            controls=[
                _make_cost_chip("Комиссии биржи", total_comm, "#38BDF8", "Trading Fee"),
                _make_cost_chip("Свопы / Финансирование", total_swap, "#F59E0B", "Overnight Funding"),
                _make_cost_chip("Скрытое проскальзывание", total_slip, "#A855F7", "Execution Slippage"),
            ],
            wrap=True,
            spacing=8,
            run_spacing=8,
        )

        insight_bar = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.LIGHTBULB_ROUNDED, size=15, color=grade_col),
                    ft.Text(
                        insight,
                        size=11,
                        color=TEXT_PRIMARY,
                        weight=ft.FontWeight.W_500,
                        font_family=FONT_FAMILY,
                        expand=True,
                    ),
                ],
                spacing=8,
            ),
            bgcolor=SURFACE_2,
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border_radius=RADIUS_SM,
            border=ft.border.all(1, ft.Colors.with_opacity(0.3, grade_col)),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.MONETIZATION_ON_ROUNDED, color=ACCENT_PRIMARY, size=18),
                                    ft.Text("Аудит комиссий и скрытых издержек брокера", size=14, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Container(
                                        content=ft.Text("BROKER AUDIT", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                        bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                        border_radius=4,
                                        border=ft.border.all(1, ft.Colors.with_opacity(0.3, ACCENT_PRIMARY)),
                                    ),
                                ],
                                spacing=8,
                            ),
                            header_badge,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(color=BORDER_SUBTLE, height=8),
                    ft.ResponsiveRow(controls=kpis, spacing=10, run_spacing=10),
                    ft.Container(height=4),
                    cost_chips,
                    ft.Container(height=2),
                    insight_bar,
                ],
                spacing=8,
            ),
            padding=16,
            bgcolor=SURFACE_1,
            border_radius=RADIUS_LG,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

    def _on_tilt_toggle(self, _):
        """Интерактивный отклик переключателя тильт-фильтра."""
        is_on = self.tilt_switch.value
        if is_on:
            self.tilt_badge.content = ft.Text("АКТИВЕН", size=10, weight=ft.FontWeight.BOLD, color=WARNING_TILT, font_family=FONT_MONO)
            self.tilt_badge.bgcolor = ft.Colors.with_opacity(0.16, WARNING_TILT)
            self.tilt_badge.border = ft.border.all(1, ft.Colors.with_opacity(0.4, WARNING_TILT))
        else:
            self.tilt_badge.content = ft.Text("OFF", size=10, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO)
            self.tilt_badge.bgcolor = SURFACE_2
            self.tilt_badge.border = ft.border.all(1, BORDER_SUBTLE)

        self.refresh()

        if self.page:
            try:
                sb = ft.SnackBar(
                    content=ft.Text(
                        "Тильт-фильтр активирован: показан чистый edge стратегии без эмоциональных ошибок." if is_on
                        else "Тильт-фильтр отключен: отображаются все сделки портфеля.",
                        color=TEXT_PRIMARY,
                    ),
                    bgcolor=SURFACE_1,
                    duration=3000,
                )
                self.page.overlay.append(sb)
                sb.open = True
                self.page.update()
            except Exception:
                pass

    def _open_ai_coach_modal(self) -> None:
        """Открывает модальное окно с квантовыми AI инсайтами трейдера (Wave AI Coach)."""
        from analytics import WaveAICoachService
        trades = self.db.get_trades(account_id=self.current_account_id)
        insights = WaveAICoachService.generate_insights(trades)

        cards = []
        for ins in insights:
            col = ins.get("color", "#38BDF8")
            cards.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(getattr(ft.Icons, ins.get("icon", "LIGHTBULB_ROUNDED"), ft.Icons.LIGHTBULB_ROUNDED), size=18, color=col),
                                    ft.Text(ins["title"], size=13, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Container(
                                        content=ft.Text(ins.get("category", "QUANT"), size=9, weight=ft.FontWeight.BOLD, color=col, font_family=FONT_MONO),
                                        bgcolor=ft.Colors.with_opacity(0.12, col),
                                        border=ft.border.all(1, ft.Colors.with_opacity(0.3, col)),
                                        border_radius=4,
                                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                    ),
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Text(ins["text"], size=12, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                            ft.Container(
                                content=ft.Row(
                                    [
                                        ft.Icon(ft.Icons.TIPS_AND_UPDATES_OUTLINED, size=14, color=col),
                                        ft.Text(f"Рекомендация: {ins.get('recommendation', '')}", size=11, color=TEXT_MUTED, font_family=FONT_FAMILY, expand=True),
                                    ],
                                    spacing=6,
                                ),
                                bgcolor=SURFACE_2,
                                border_radius=6,
                                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                            ),
                        ],
                        spacing=6,
                    ),
                    bgcolor=SURFACE_1,
                    border=ft.border.all(1, ft.Colors.with_opacity(0.25, col)),
                    border_radius=RADIUS_MD,
                    padding=12,
                )
            )

        modal = ft.AlertDialog(
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.PSYCHOLOGY_ROUNDED, size=22, color="#A855F7"),
                    ft.Text("Wave AI Coach — Квантовый анализ торговли", size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                ],
                spacing=8,
            ),
            content=ft.Container(
                content=ft.Column(cards, spacing=10, scroll=ft.ScrollMode.AUTO),
                width=650,
                height=420,
            ),
            actions=[
                ft.TextButton("Закрыть", on_click=lambda _: self._close_dialog(modal))
            ],
            bgcolor=SURFACE_OVERLAY,
            shape=ft.RoundedRectangleBorder(radius=RADIUS_LG),
        )

        target_page = self.host_page
        if target_page:
            target_page.dialog = modal
            modal.open = True
            target_page.update()

    def _close_dialog(self, dlg: ft.AlertDialog) -> None:
        target_page = self.host_page
        if target_page:
            dlg.open = False
            target_page.update()

    def _build_broker_costs_card(self, metrics: DashboardMetrics) -> ft.Container:
        """Карточка издержек брокера и скрытых комиссий с визуальным соотношением (Fee Drag)."""
        fee_drag = metrics.fee_drag_pct
        drag_badge_col = LOSS if fee_drag > 15 else (WARNING_TILT if fee_drag > 5 else PROFIT)

        net_val = max(metrics.net_pnl, 0.0)
        costs_val = max(metrics.total_broker_costs, 0.0)
        total_sum = net_val + costs_val

        if total_sum > 0:
            net_flex = max(int((net_val / total_sum) * 100), 5)
            costs_flex = max(int((costs_val / total_sum) * 100), 5)
        else:
            net_flex, costs_flex = 50, 50

        ratio_bar = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Container(
                            expand=net_flex,
                            height=5,
                            bgcolor=PROFIT,
                            border_radius=ft.border_radius.horizontal(left=4),
                        ),
                        ft.Container(
                            expand=costs_flex,
                            height=5,
                            bgcolor=WARNING_TILT,
                            border_radius=ft.border_radius.horizontal(right=4),
                        ),
                    ],
                    spacing=2,
                ),
                ft.Row(
                    controls=[
                        ft.Text(f"Net: ${metrics.net_pnl:,.0f}", size=9, color=PROFIT, font_family=FONT_MONO),
                        ft.Text(f"Fee: -${metrics.total_broker_costs:,.0f}", size=9, color=WARNING_TILT, font_family=FONT_MONO),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=3,
        )

        card = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("Издержки брокера", size=12, color=TEXT_SECONDARY, weight=ft.FontWeight.W_500, font_family=FONT_FAMILY),
                            ft.Container(
                                content=ft.Text(f"DRAG {fee_drag:.1f}%", size=9, weight=ft.FontWeight.BOLD, color=drag_badge_col, font_family=FONT_MONO),
                                bgcolor=ft.Colors.with_opacity(0.14, drag_badge_col),
                                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                border_radius=4,
                                border=ft.border.all(1, ft.Colors.with_opacity(0.3, drag_badge_col)),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(
                        f"-${metrics.total_broker_costs:,.2f}",
                        size=20,
                        color=WARNING_TILT,
                        weight=ft.FontWeight.BOLD,
                        font_family=FONT_MONO,
                    ),
                    ratio_bar,
                    ft.Text(
                        f"Комиссии: ${metrics.total_commission:,.2f} | Свопы: ${metrics.total_swap_fees:,.2f}",
                        size=9,
                        color=TEXT_MUTED,
                        font_family=FONT_MONO,
                    ),
                ],
                spacing=3,
            ),
            padding=15,
            bgcolor=SURFACE_1,
            border_radius=RADIUS_MD,
            border=ft.border.all(1.2, BORDER_SUBTLE),
            expand=True,
            animate=get_animation(ANIM_FAST_MS) if ANIMATIONS_ENABLED else None,
        )

        def _on_hover(e: ft.HoverEvent):
            if not ANIMATIONS_ENABLED:
                return
            if e.data == "true":
                card.border = ft.border.all(1.2, BORDER_HIGHLIGHT)
                card.bgcolor = SURFACE_2
            else:
                card.border = ft.border.all(1.2, BORDER_SUBTLE)
                card.bgcolor = SURFACE_1
            try:
                card.update()
            except Exception:
                pass

        card.on_hover = _on_hover
        return card

    def refresh(self, account_id: Any = "KEEP") -> None:
        """Перерасчет аналитики и обновление интерфейса."""
        if account_id != "KEEP":
            self.current_account_id = None if (account_id is None or account_id == -1) else account_id

        trades = self.db.get_trades(account_id=self.current_account_id, order_by_date_desc=False)
        is_tilt_filtered = bool(self.tilt_switch.value)
        metrics: DashboardMetrics = AnalyticsService.calculate_metrics(trades, exclude_tilt=is_tilt_filtered)

        # Вычисляем начальный баланс активного счёта или сумму всех счетов
        if self.current_account_id:
            acc = self.db.get_account_by_id(self.current_account_id)
            init_bal = acc.initial_balance if acc else 10000.0
        else:
            accs = self.db.get_accounts()
            init_bal = sum(a.initial_balance for a in accs) if accs else 10000.0

        # 1. P&L Календарь (Error Boundary)
        try:
            self.pnl_calendar.set_trades(trades)
        except Exception as e:
            logging.exception(f"[DashboardView] Error setting PnL calendar trades: {e}")

        # 2. Сетка KPI метрик (Error Boundary)
        try:
            winrate_spark = metrics.winrate_sparkline if metrics.winrate_sparkline else [50.0, 50.0]
            pf_spark = metrics.profit_factor_sparkline if metrics.profit_factor_sparkline else [1.5, 1.5]

            # R-Multiple и Expectancy
            if metrics.avg_r_multiple != 0.0:
                r_multiple_val = f"{metrics.avg_r_multiple:+.2f} R"
            else:
                r_multiple_val = "0.00 R"

            self.metrics_grid.controls = [
                ft.Container(self._build_hero_card(metrics, is_tilt_filtered), col={"sm": 12, "md": 6, "lg": 3}),
                ft.Container(
                    self._build_metric_card(
                        "Винрейт (Winrate)",
                        f"{metrics.winrate:.1f}%",
                        val_color=PROFIT if metrics.winrate >= 50 else LOSS,
                        sparkline_data=winrate_spark,
                        has_glow=metrics.winrate >= 55,
                    ),
                    col={"sm": 6, "md": 4, "lg": 1.8},
                ),
                ft.Container(
                    self._build_metric_card(
                        "Профит-фактор",
                        f"{metrics.profit_factor:.2f}",
                        val_color=PROFIT if metrics.profit_factor >= 1.5 else (WARNING_TILT if metrics.profit_factor >= 1.0 else LOSS),
                        sparkline_data=pf_spark,
                        has_glow=metrics.profit_factor >= 2.0,
                    ),
                    col={"sm": 6, "md": 4, "lg": 1.7},
                ),
                ft.Container(
                    self._build_metric_card(
                        "Сделок",
                        str(metrics.total_trades),
                        subtitle=f"Серия: {metrics.current_streak:+d} • Ср: {metrics.avg_trade_pnl:+.1f}$" if metrics.total_trades > 0 else "Ср: 0.00$",
                    ),
                    col={"sm": 6, "md": 4, "lg": 1.4},
                ),
                ft.Container(
                    self._build_metric_card(
                        "R-Multiple",
                        r_multiple_val,
                        subtitle=f"SQN {metrics.sqn:.2f} • {metrics.sqn_rating.split()[0]}" if metrics.sqn_rating != "N/A" else "Ср. риск/прибыль",
                        tag="QUANT",
                        val_color=ACCENT_PRIMARY,
                        has_glow=(metrics.avg_r_multiple >= 2.0 or metrics.sqn >= 2.0),
                    ),
                    col={"sm": 6, "md": 4, "lg": 1.6},
                ),
                ft.Container(
                    self._build_broker_costs_card(metrics),
                    col={"sm": 12, "md": 6, "lg": 2.5},
                ),
            ]
        except Exception as e:
            logging.exception(f"[DashboardView] Error rendering KPI metrics: {e}")
            self.metrics_grid.controls = [
                ft.Container(content=ft.Text(f"Ошибка рендеринга блока KPI: {e}", color="#EF4444"), padding=12)
            ]

        # 3. Обновление блока Монте-Карло (Error Boundary)
        try:
            self.monte_carlo_container.content = self._build_monte_carlo_cone_card(trades, initial_balance=init_bal, metrics=metrics)
        except Exception as e:
            logging.exception(f"[DashboardView] Error rendering Monte Carlo: {e}")
            self.monte_carlo_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга блока Монте-Карло: {e}", color="#EF4444"),
                padding=12,
            )

        # 4. Отрисовка интерактивной живой Equity Curve (Error Boundary)
        try:
            if not trades:
                self.chart_container.content = ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.SHOW_CHART_ROUNDED, size=46, color=TEXT_MUTED),
                            ft.Text("Сделок в базе пока нет", size=15, color=TEXT_SECONDARY, weight=ft.FontWeight.W_500, font_family=FONT_FAMILY),
                            ft.Text("Добавьте сделки через кнопку на панели навигации", size=12, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    alignment=ft.alignment.center,
                    height=220,
                )
            else:
                all_df = AnalyticsService.trades_to_dataframe(trades)
                all_df["equity"] = all_df["net_pnl"].cumsum()
                line_color = PROFIT if all_df["equity"].iloc[-1] >= 0 else LOSS

                if hasattr(ft, "LineChart"):
                    tt_style = ft.TextStyle(font_family=FONT_MONO, size=11, color=TEXT_PRIMARY, weight=ft.FontWeight.W_500)
                    points = [ft.LineChartDataPoint(0, 0, tooltip="Старт: 0.00 USD", tooltip_style=tt_style, show_tooltip=True)]
                    min_y = 0.0
                    max_y = 0.0

                    for idx, row in enumerate(all_df.itertuples(), start=1):
                        eq = float(row.equity)
                        pnl_sign = "+" if row.net_pnl >= 0 else ""
                        points.append(
                            ft.LineChartDataPoint(
                                idx,
                                eq,
                                tooltip=f"({row.ticker})\nNet PnL: ${row.net_pnl:+,.2f}\nДепозит: ${eq:,.2f}",
                                tooltip_style=tt_style,
                                show_tooltip=True,
                            )
                        )
                        min_y = min(min_y, eq)
                        max_y = max(max_y, eq)

                    # Основная линия портфеля
                    series_list = [
                        ft.LineChartData(
                            data_points=points,
                            stroke_width=2.5,
                            color=line_color,
                            curved=True,
                            stroke_cap_round=True,
                            below_line_gradient=ft.LinearGradient(
                                begin=ft.alignment.top_center,
                                end=ft.alignment.bottom_center,
                                colors=[
                                    ft.Colors.with_opacity(0.24, line_color),
                                    ft.Colors.with_opacity(0.04, line_color),
                                    ft.Colors.with_opacity(0.0, line_color),
                                ],
                            ),
                        )
                    ]

                    # Вторая линия: What-If капитал без тильт-сделок (пунктир #38BDF8)
                    if is_tilt_filtered:
                        whatif_points = [ft.LineChartDataPoint(0, 0, tooltip="Старт (Без тильта): 0.00 USD", tooltip_style=tt_style, show_tooltip=True)]
                        curr_eq = 0.0
                        for idx, t in enumerate(trades, start=1):
                            if not t.is_tilt:
                                curr_eq += t.net_pnl
                            whatif_points.append(
                                ft.LineChartDataPoint(
                                    idx,
                                    round(curr_eq, 2),
                                    tooltip=f"What-If #{idx} (Без тильта)\nДепозит: ${curr_eq:,.2f}",
                                    tooltip_style=tt_style,
                                    show_tooltip=True,
                                )
                            )
                            min_y = min(min_y, curr_eq)
                            max_y = max(max_y, curr_eq)

                        whatif_color = "#38BDF8"
                        series_list.append(
                            ft.LineChartData(
                                data_points=whatif_points,
                                stroke_width=2.5,
                                color=whatif_color,
                                curved=True,
                                dash_pattern=[5, 4],
                                stroke_cap_round=True,
                            )
                        )

                    y_padding = max(abs(max_y - min_y) * 0.18, 12.0)

                    chart = ft.LineChart(
                        data_series=series_list,
                        border=ft.border.all(1, BORDER_SUBTLE),
                        horizontal_grid_lines=ft.ChartGridLines(
                            interval=max(1.0, (max_y - min_y) / 5),
                            color=BORDER_SUBTLE,
                            width=1,
                            dash_pattern=[4, 4],
                        ),
                        vertical_grid_lines=ft.ChartGridLines(
                            interval=max(1, len(all_df) // 6),
                            color=BORDER_SUBTLE,
                            width=1,
                            dash_pattern=[4, 4],
                        ),
                        left_axis=ft.ChartAxis(
                            labels_size=60,
                        ),
                        min_y=min_y - y_padding,
                        max_y=max_val if (max_val := max_y + y_padding) != (min_y - y_padding) else min_y + 10,
                        min_x=0,
                        max_x=len(all_df),
                        interactive=True,
                        tooltip_bgcolor="#12151E",
                        tooltip_tooltip_border_side=ft.BorderSide(1, BORDER_HIGHLIGHT),
                        tooltip_rounded_radius=8,
                        tooltip_margin=12,
                        tooltip_padding=ft.padding.symmetric(horizontal=12, vertical=8),
                        tooltip_max_content_width=320,
                        tooltip_fit_inside_horizontally=True,
                        tooltip_fit_inside_vertically=True,
                        height=240,
                        expand=True,
                    )
                    self.chart_container.content = chart
                else:
                    self.chart_container.content = ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Icon(ft.Icons.QUERY_STATS_ROUNDED, size=40, color=PROFIT),
                                ft.Text(f"Итоговый депозит: {all_df['equity'].iloc[-1]:+,.2f} $", size=16, color=line_color, weight=ft.FontWeight.BOLD, font_family=FONT_MONO),
                                ft.ElevatedButton("Посмотреть в Plotly", on_click=lambda _: self.on_open_plotly()),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        height=220,
                        alignment=ft.alignment.center,
                    )
        except Exception as ex:
            logging.exception(f"[DashboardView] Error rendering Equity Chart: {ex}")
            self.chart_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга блока графика: {ex}", color=ft.Colors.ERROR),
                alignment=ft.alignment.center,
                height=240,
            )

        # 5. Обновление матрицы торговых сессий (Error Boundary)
        try:
            self.session_matrix_container.content = self._build_session_matrix_card(trades)
        except Exception as ex_sess:
            logging.exception(f"[DashboardView] Error rendering Session Matrix: {ex_sess}")
            self.session_matrix_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга матрицы сессий: {ex_sess}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.1 Обновление лидерборда стратегий (Error Boundary)
        try:
            self.strategy_leaderboard_container.content = self._build_strategy_leaderboard_card(trades)
        except Exception as ex_lead:
            logging.exception(f"[DashboardView] Error rendering Strategy Leaderboard: {ex_lead}")
            self.strategy_leaderboard_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга лидерборда стратегий: {ex_lead}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.2 Обновление анализа времени удержания (Error Boundary)
        try:
            self.duration_analysis_container.content = self._build_duration_analysis_card(trades)
        except Exception as ex_dur:
            logging.exception(f"[DashboardView] Error rendering Duration Analysis: {ex_dur}")
            self.duration_analysis_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга анализа длительности: {ex_dur}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.3 Обновление матрицы распределения активов (Error Boundary)
        try:
            self.asset_allocation_container.content = self._build_asset_allocation_card(trades)
        except Exception as ex_asset:
            logging.exception(f"[DashboardView] Error rendering Asset Allocation: {ex_asset}")
            self.asset_allocation_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга матрицы активов: {ex_asset}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.4 Обновление аудита психологии и тильта (Error Boundary)
        try:
            self.psychology_matrix_container.content = self._build_psychology_matrix_card(trades)
        except Exception as ex_psy:
            logging.exception(f"[DashboardView] Error rendering Psychology Matrix: {ex_psy}")
            self.psychology_matrix_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга аудита психологии: {ex_psy}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.5 Обновление анализа просадки и устойчивости (Error Boundary)
        try:
            self.drawdown_recovery_container.content = self._build_drawdown_recovery_card(trades)
        except Exception as ex_dd:
            logging.exception(f"[DashboardView] Error rendering Drawdown Recovery: {ex_dd}")
            self.drawdown_recovery_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга анализа просадки: {ex_dd}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.6 Обновление матрицы исполнения MAE / MFE (Error Boundary)
        try:
            self.excursion_matrix_container.content = self._build_excursion_card(trades)
        except Exception as ex_exc:
            logging.exception(f"[DashboardView] Error rendering Excursion Matrix: {ex_exc}")
            self.excursion_matrix_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга матрицы экскурсий: {ex_exc}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.7 Обновление фаз месяца и сезонности (Error Boundary)
        try:
            self.monthly_phase_container.content = self._build_monthly_phase_card(trades)
        except Exception as ex_phase:
            logging.exception(f"[DashboardView] Error rendering Monthly Phase Matrix: {ex_phase}")
            self.monthly_phase_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга фаз месяца: {ex_phase}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.8 Обновление симулятора мани-менеджмента (Error Boundary)
        try:
            self.sizing_simulator_container.content = self._build_position_sizing_simulator_card(trades)
        except Exception as ex_sim:
            logging.exception(f"[DashboardView] Error rendering Sizing Simulator: {ex_sim}")
            self.sizing_simulator_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга симулятора сайзинга: {ex_sim}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.9 Обновление матрицы рыночных фаз и режимов (Error Boundary)
        try:
            self.market_regime_container.content = self._build_market_regime_card(trades)
        except Exception as ex_reg:
            logging.exception(f"[DashboardView] Error rendering Market Regime Matrix: {ex_reg}")
            self.market_regime_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга фаз рынка: {ex_reg}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.10 Обновление распределения R-Multiple (Error Boundary)
        try:
            self.r_distribution_container.content = self._build_r_distribution_card(trades)
        except Exception as ex_r:
            logging.exception(f"[DashboardView] Error rendering R-Multiple Distribution: {ex_r}")
            self.r_distribution_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга R-распределения: {ex_r}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.11 Обновление эффективности исполнения R:R (Error Boundary)
        try:
            self.rr_efficiency_container.content = self._build_rr_efficiency_card(trades)
        except Exception as ex_rr:
            logging.exception(f"[DashboardView] Error rendering RR Efficiency Matrix: {ex_rr}")
            self.rr_efficiency_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга эффективности R:R: {ex_rr}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.12 Обновление матрицы нарушений правил (Error Boundary)
        try:
            self.rule_violation_container.content = self._build_rule_violation_card(trades)
        except Exception as ex_rv:
            logging.exception(f"[DashboardView] Error rendering Rule Violation Matrix: {ex_rv}")
            self.rule_violation_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга матрицы нарушений правил: {ex_rv}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.13 Обновление матрицы мульти-таймфрейм согласованности (Error Boundary)
        try:
            self.mtf_alignment_container.content = self._build_mtf_alignment_card(trades)
        except Exception as ex_mtf:
            logging.exception(f"[DashboardView] Error rendering MTF Alignment Matrix: {ex_mtf}")
            self.mtf_alignment_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга MTF матрицы: {ex_mtf}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.14 Обновление комплаенса предторгового чек-листа (Error Boundary)
        try:
            self.compliance_routine_container.content = self._build_compliance_routine_card(trades)
        except Exception as ex_cp:
            logging.exception(f"[DashboardView] Error rendering Compliance Routine: {ex_cp}")
            self.compliance_routine_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга чек-листа: {ex_cp}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.15 Обновление окон ликвидности и перекрытия сессий (Error Boundary)
        try:
            self.session_overlap_container.content = self._build_session_overlap_card(trades)
        except Exception as ex_ol:
            logging.exception(f"[DashboardView] Error rendering Session Overlap Matrix: {ex_ol}")
            self.session_overlap_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга перекрытия сессий: {ex_ol}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.16 Обновление матрицы градации сетапов (Error Boundary)
        try:
            self.setup_grading_container.content = self._build_setup_grading_card(trades)
        except Exception as ex_sg:
            logging.exception(f"[DashboardView] Error rendering Setup Grading Matrix: {ex_sg}")
            self.setup_grading_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга градации сетапов: {ex_sg}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.17 Обновление атрибуции торговых тегов и факторов (Error Boundary)
        try:
            self.tag_attribution_container.content = self._build_tag_attribution_card(trades)
        except Exception as ex_tag:
            logging.exception(f"[DashboardView] Error rendering Tag Attribution Matrix: {ex_tag}")
            self.tag_attribution_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга атрибуции тегов: {ex_tag}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.18 Обновление динамики и затухания преимущества (Error Boundary)
        try:
            self.rolling_edge_container.content = self._build_rolling_edge_card(trades)
        except Exception as ex_roll:
            logging.exception(f"[DashboardView] Error rendering Rolling Edge Matrix: {ex_roll}")
            self.rolling_edge_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга Rolling Edge матрицы: {ex_roll}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.19 Обновление радара готовности к проп-челленджам (Error Boundary)
        try:
            self.prop_consistency_container.content = self._build_prop_consistency_card(trades)
        except Exception as ex_prop:
            logging.exception(f"[DashboardView] Error rendering Prop Consistency Radar: {ex_prop}")
            self.prop_consistency_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга радара консистентности: {ex_prop}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.20 Обновление эффективности размещения SL/TP (Error Boundary)
        try:
            self.order_placement_container.content = self._build_order_placement_card(trades)
        except Exception as ex_op:
            logging.exception(f"[DashboardView] Error rendering Order Placement Card: {ex_op}")
            self.order_placement_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга эффективности ордеров: {ex_op}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.21 Обновление предсказательной силы факторов IC (Error Boundary)
        try:
            self.factor_ic_container.content = self._build_factor_ic_card(trades)
        except Exception as ex_ic:
            logging.exception(f"[DashboardView] Error rendering Factor IC Card: {ex_ic}")
            self.factor_ic_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга предсказательной силы факторов: {ex_ic}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.22 Обновление эффективности управления позицией (Error Boundary)
        try:
            self.trade_management_container.content = self._build_trade_management_card(trades)
        except Exception as ex_tm:
            logging.exception(f"[DashboardView] Error rendering Trade Management Card: {ex_tm}")
            self.trade_management_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга аудита управления: {ex_tm}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.23 Обновление матрицы снятия ликвидности и потока ордеров (Error Boundary)
        try:
            self.liquidity_sweep_container.content = self._build_liquidity_sweep_card(trades)
        except Exception as ex_ls:
            logging.exception(f"[DashboardView] Error rendering Liquidity Sweep Card: {ex_ls}")
            self.liquidity_sweep_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга матрицы ликвидности: {ex_ls}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 5.24 Обновление аудита издержек и комиссий брокера (Error Boundary)
        try:
            self.broker_cost_drag_container.content = self._build_broker_cost_drag_card(trades)
        except Exception as ex_bcd:
            logging.exception(f"[DashboardView] Error rendering Broker Cost Drag Card: {ex_bcd}")
            self.broker_cost_drag_container.content = ft.Container(
                content=ft.Text(f"Ошибка рендеринга аудита издержек брокера: {ex_bcd}", color=ft.Colors.ERROR),
                padding=12,
            )

        # 6. Обновление тепловой карты времени (Error Boundary)
        try:
            self.time_heatmap.set_trades(trades)
        except Exception as ex_hm:
            logging.exception(f"[DashboardView] Error updating Time Heatmap: {ex_hm}")

        # 7. Обновление контролов активной категории в Хабе Аналитики
        try:
            self._rebuild_category_tabs()
            query = getattr(self.category_search_input, "value", "") or ""
            self.category_modules_column.controls = self._get_category_controls(self.active_category, query)
        except Exception as ex_cat:
            logging.exception(f"[DashboardView] Error updating category controls: {ex_cat}")

        if self.page:
            self.update()
