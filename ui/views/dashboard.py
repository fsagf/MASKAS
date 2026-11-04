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
        self.pnl_calendar = PnLCalendar(on_date_selected=self.on_date_selected)

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

    def _build_monte_carlo_cone_card(self, trades: List[Trade], initial_balance: float = 10000.0) -> ft.Container:
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
            height=145,
            expand=True,
        )

        return ft.Container(
            content=ft.Row(
                controls=[
                    # Левая колонка: компактный инфо-блок (expand=2)
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Icon(ft.Icons.QUERY_STATS_ROUNDED, color=ACCENT_PRIMARY, size=24),
                                        ft.Text("Симуляция Монте-Карло", size=15, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                        ft.Container(
                                            content=ft.Text("10 000 ИТЕРАЦИЙ", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                            bgcolor=ft.Colors.with_opacity(0.14, ACCENT_PRIMARY),
                                            padding=ft.padding.symmetric(horizontal=8, vertical=2),
                                            border_radius=RADIUS_SM,
                                            border=ft.border.all(1, ft.Colors.with_opacity(0.3, ACCENT_PRIMARY)),
                                        ),
                                    ],
                                    spacing=8,
                                ),
                                ft.Text(
                                    "Векторный бутстрэп 10 000 возможных траекторий депозита на 20 шагов вперед. "
                                    "Расчет риска банкротства, 95% доверительного интервала и ожидаемого роста.",
                                    size=11,
                                    color=TEXT_SECONDARY,
                                    font_family=FONT_FAMILY,
                                ),
                                ft.Container(height=4),
                                ft.Row(
                                    controls=[
                                        self._metric_mini_box("Risk of Ruin", f"< {mc['risk_of_ruin']}%", PROFIT if mc["risk_of_ruin"] < 5 else LOSS),
                                        self._metric_mini_box("95% VaR Max DD", f"-{mc['var_95_max_dd']}%", LOSS),
                                        self._metric_mini_box("Expectancy Run", f"{mc['expectancy_run']:+,.1f}%", PROFIT if mc["expectancy_run"] >= 0 else LOSS),
                                    ],
                                    spacing=8,
                                ),
                            ],
                            spacing=6,
                        ),
                        expand=2,
                    ),

                    ft.VerticalDivider(width=1, color=BORDER_SUBTLE),

                    # Правая колонка: интерактивный веер траекторий (expand=3)
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Row(
                                            controls=[
                                                ft.Icon(ft.Icons.TIMELINE_ROUNDED, size=14, color=ACCENT_PRIMARY),
                                                ft.Text("Веер траекторий капитала (20 шагов)", size=11, color=TEXT_SECONDARY, font_family=FONT_MONO),
                                            ],
                                            spacing=6,
                                        ),
                                        ft.Text("P95 (Бычий) → P05 (Стресс-тест)", size=10, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                                cone_chart,
                            ],
                            spacing=6,
                            expand=True,
                        ),
                        expand=3,
                    ),
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
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
                    ft.Text(label, size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                    ft.Text(val, size=12, weight=ft.FontWeight.BOLD, color=color, font_family=FONT_MONO),
                ],
                spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            bgcolor=SURFACE_2,
            border_radius=RADIUS_SM,
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
            self.page.show_snack_bar(
                ft.SnackBar(
                    content=ft.Text(
                        "Тильт-фильтр активирован: показан чистый edge стратегии без эмоциональных ошибок." if is_on
                        else "Тильт-фильтр отключен: отображаются все сделки портфеля.",
                        color=TEXT_PRIMARY,
                        font_family=FONT_FAMILY,
                    ),
                    bgcolor=SURFACE_1,
                )
            )

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
                    self._build_metric_card("Сделок", str(metrics.total_trades), subtitle=f"Ср: {metrics.avg_trade_pnl:+.2f}$"),
                    col={"sm": 6, "md": 4, "lg": 1.4},
                ),
                ft.Container(
                    self._build_metric_card(
                        "R-Multiple",
                        r_multiple_val,
                        subtitle="Ср. риск/прибыль",
                        tag="QUANT",
                        val_color=ACCENT_PRIMARY,
                        has_glow=(metrics.avg_r_multiple >= 2.0),
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
            self.monte_carlo_container.content = self._build_monte_carlo_cone_card(trades, initial_balance=init_bal)
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

        if self.page:
            self.update()
