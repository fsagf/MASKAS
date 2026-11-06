"""
ui/components/time_heatmap.py
Интерактивная квант-матрица прибыльности Day-of-Week & Hour-of-Day (Тепловая карта времени).
Позволяет трейдеру выявить свои самые прибыльные часы и дни недели,
а также обнаружить «слепые зоны» и часы тильта.
"""

from typing import Any, Dict, List, Optional
import flet as ft

from database import Trade
from analytics import AnalyticsService
from ui.theme import (
    ACCENT_PRIMARY,
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
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)

DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


class TimeHeatmap(ft.Container):
    """
    Интерактивный компонент тепловой карты доходности по дням недели и часам суток.
    """

    def __init__(self, trades: Optional[List[Trade]] = None):
        super().__init__()
        self.trades = trades or []
        self.bgcolor = SURFACE_1
        self.padding = 16
        self.border_radius = RADIUS_LG
        self.border = ft.border.all(1, BORDER_SUBTLE)
        self.content = self._build_content()

    def set_trades(self, trades: List[Trade]) -> None:
        self.trades = trades
        self.content = self._build_content()
        if self.page:
            self.update()

    def _get_cell_color(self, pnl: float, count: int, max_pos: float, max_neg: float) -> str:
        """Возвращает цвет ячейки тепловой карты с адаптивной прозрачностью."""
        if count == 0:
            return SURFACE_2

        if pnl > 0:
            ratio = min(max(pnl / max(max_pos, 1.0), 0.25), 0.9)
            return ft.Colors.with_opacity(ratio, PROFIT)
        elif pnl < 0:
            ratio = min(max(abs(pnl) / max(max_neg, 1.0), 0.25), 0.9)
            return ft.Colors.with_opacity(ratio, LOSS)
        else:
            return SURFACE_3

    def _build_content(self) -> ft.Control:
        data = AnalyticsService.calculate_time_heatmap(self.trades)
        cells = data["cells"]
        day_aggs = data["day_aggregates"]
        hour_aggs = data["hour_aggregates"]
        max_pos = data["max_pos_pnl"]
        max_neg = data["max_neg_pnl"]
        best_day = data["best_day"]
        worst_day = data["worst_day"]
        best_hour = data["best_hour"]

        # 1. Шапка компонента
        best_day_text = (
            f"Лучший день: {best_day['day_name']} ({best_day['net_pnl']:+,.1f} $ • {best_day['winrate']:.0f}% WR)"
            if best_day and best_day["count"] > 0
            else "Тепловая карта времени синхронизирована (UTC)"
        )

        header_row = ft.Row(
            controls=[
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.GRID_ON_ROUNDED, color=ACCENT_PRIMARY, size=18),
                        ft.Text("Тепловая карта времени", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                        ft.Text("(Day & Hour PnL Matrix)", size=11, color=TEXT_MUTED, font_family=FONT_MONO),
                    ],
                    spacing=8,
                ),
                ft.Container(
                    content=ft.Text(best_day_text, size=10, color=ACCENT_PRIMARY, font_family=FONT_MONO),
                    bgcolor=ft.Colors.with_opacity(0.12, ACCENT_PRIMARY),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    border_radius=RADIUS_SM,
                    border=ft.border.all(1, ft.Colors.with_opacity(0.25, ACCENT_PRIMARY)),
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # 2. Построение матрицы: колонка часов (00..23) + колонка "ИТОГ"
        # Заголовок часов:
        hour_header_cells = [
            ft.Container(
                content=ft.Text("ДЕНЬ", size=10, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO),
                width=42,
                alignment=ft.alignment.center,
            )
        ]

        # Отображаем 24 часовых слота
        for h in range(24):
            hour_header_cells.append(
                ft.Container(
                    content=ft.Text(f"{h:02d}", size=9, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    width=26,
                    height=20,
                    alignment=ft.alignment.center,
                )
            )

        hour_header_cells.append(
            ft.Container(
                content=ft.Text("ИТОГ", size=9, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
                width=68,
                alignment=ft.alignment.center_right,
            )
        )

        matrix_rows = [ft.Row(controls=hour_header_cells, spacing=2)]

        # 7 строк для дней недели (Пн .. Вс)
        for d in range(7):
            day_name = DAYS_RU[d]
            row_cells = [
                ft.Container(
                    content=ft.Text(day_name, size=11, weight=ft.FontWeight.W_600, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                    width=42,
                    alignment=ft.alignment.center_left,
                )
            ]

            for h in range(24):
                c = cells[d][h]
                count = c["count"]
                pnl = c["net_pnl"]
                wr = c["winrate"]

                cell_bg = self._get_cell_color(pnl, count, max_pos, max_neg)

                tooltip_msg = (
                    f"{day_name}, {h:02d}:00–{h:02d}:59 UTC\n"
                    f"Net PnL: ${pnl:+,.2f}\n"
                    f"Сделок: {count} | Винрейт: {wr:.1f}%"
                    if count > 0
                    else f"{day_name}, {h:02d}:00 UTC: сделок нет"
                )

                # Тонкая рамка ячейки
                cell_border = (
                    ft.border.all(1, ft.Colors.with_opacity(0.3, PROFIT if pnl > 0 else LOSS))
                    if count > 0
                    else ft.border.all(0.5, ft.Colors.with_opacity(0.15, BORDER_SUBTLE))
                )

                cell_widget = ft.Container(
                    width=26,
                    height=22,
                    bgcolor=cell_bg,
                    border_radius=ft.border_radius.all(3),
                    border=cell_border,
                    tooltip=tooltip_msg,
                    alignment=ft.alignment.center,
                    content=ft.Text(
                        f"{int(count)}" if count > 0 else "",
                        size=8,
                        weight=ft.FontWeight.BOLD,
                        color=TEXT_PRIMARY if count > 0 else ft.Colors.TRANSPARENT,
                        font_family=FONT_MONO,
                    ),
                )
                row_cells.append(cell_widget)

            # Итоговый блок дня (справа)
            day_agg = day_aggs[d]
            day_pnl = day_agg["net_pnl"]
            day_count = day_agg["count"]
            day_col = PROFIT if day_pnl > 0 else (LOSS if day_pnl < 0 else TEXT_MUTED)

            row_cells.append(
                ft.Container(
                    content=ft.Text(
                        f"{day_pnl:+,.0f} $" if day_count > 0 else "0 $",
                        size=10,
                        weight=ft.FontWeight.BOLD,
                        color=day_col,
                        font_family=FONT_MONO,
                    ),
                    width=68,
                    alignment=ft.alignment.center_right,
                )
            )

            matrix_rows.append(ft.Row(controls=row_cells, spacing=2))

        # Легенда и сводка
        peak_hour_str = f"Пиковый час: {best_hour['hour']:02d}:00 UTC ({best_hour['net_pnl']:+,.1f} $)" if best_hour and best_hour["count"] > 0 else "Пиковый час: —"

        legend_row = ft.Row(
            controls=[
                ft.Row(
                    controls=[
                        ft.Container(width=10, height=10, bgcolor=ft.Colors.with_opacity(0.8, LOSS), border_radius=RADIUS_SM),
                        ft.Text("Убыток", size=10, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                        ft.Container(width=6),
                        ft.Container(width=10, height=10, bgcolor=SURFACE_2, border=ft.border.all(1, BORDER_SUBTLE), border_radius=RADIUS_SM),
                        ft.Text("Нет сделок", size=10, color=TEXT_MUTED, font_family=FONT_FAMILY),
                        ft.Container(width=6),
                        ft.Container(width=10, height=10, bgcolor=ft.Colors.with_opacity(0.8, PROFIT), border_radius=RADIUS_SM),
                        ft.Text("Прибыль", size=10, color=TEXT_SECONDARY, font_family=FONT_FAMILY),
                    ],
                    spacing=5,
                ),
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.ACCESS_TIME_ROUNDED, size=13, color=ACCENT_PRIMARY),
                        ft.Text(peak_hour_str, size=10, color=TEXT_SECONDARY, font_family=FONT_MONO),
                    ],
                    spacing=5,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # Контейнер со скроллом по горизонтали, чтобы матрица 24ч плавно помещалась на узких экранах
        scrollable_matrix = ft.Row(
            controls=[
                ft.Column(
                    controls=matrix_rows,
                    spacing=3,
                )
            ],
            scroll=ft.ScrollMode.ADAPTIVE,
        )

        return ft.Column(
            controls=[
                header_row,
                ft.Divider(color=BORDER_SUBTLE, height=8),
                scrollable_matrix,
                ft.Divider(color=BORDER_SUBTLE, height=8),
                legend_row,
            ],
            spacing=8,
        )

