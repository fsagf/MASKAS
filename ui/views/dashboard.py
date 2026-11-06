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
        self.pnl_calendar = PnLCalendar(on_date_selected=self.on_date_selected)
        self.time_heatmap = TimeHeatmap()

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

        return ft.Column(
            controls=[
                header,
                ft.Divider(color=BORDER_SUBTLE, height=12),
                self.metrics_grid,
                ft.Container(height=4),
                chart_card,
                ft.Container(height=4),
                calendar_and_quant,
                ft.Container(height=4),
                self.session_matrix_container,
                ft.Container(height=4),
                self.strategy_leaderboard_container,
                ft.Container(height=4),
                self.duration_analysis_container,
                ft.Container(height=4),
                self.asset_allocation_container,
                ft.Container(height=4),
                self.psychology_matrix_container,
                ft.Container(height=4),
                self.drawdown_recovery_container,
                ft.Container(height=4),
                self.time_heatmap,
                ft.Container(height=40),  # Свободный скролл
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

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

        # 6. Обновление тепловой карты времени (Error Boundary)
        try:
            self.time_heatmap.set_trades(trades)
        except Exception as ex_hm:
            logging.exception(f"[DashboardView] Error updating Time Heatmap: {ex_hm}")

        if self.page:
            self.update()
