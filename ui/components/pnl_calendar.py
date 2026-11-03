"""
ui/components/pnl_calendar.py
Интерактивный виджет «P&L Calendar Heatmap» в терминальном стиле.
Сетка 7x5/6 дней (Пн-Вс) с цветовой тепловой картой доходности (Net PnL),
количеством сделок и мгновенным переходом в журнал с фильтром по клику на день.
"""

import calendar
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional
import flet as ft

from database import Trade
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
    SURFACE_3,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    get_animation,
)

RU_MONTHS = [
    "",
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
]

RU_WEEKDAYS = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС", "ИТОГ"]


class PnLCalendar(ft.Container):
    """
    Интерактивный календарь доходности трейдера (PnL Heatmap).
    """

    def __init__(
        self,
        trades: Optional[List[Trade]] = None,
        on_date_selected: Optional[Callable[[date], None]] = None,
    ):
        self.trades = trades or []
        self.on_date_selected = on_date_selected

        today = date.today()
        self.current_year = today.year
        self.current_month = today.month

        # Заголовок месяца
        self.month_label = ft.Text(
            self._get_month_title(),
            size=14,
            weight=ft.FontWeight.BOLD,
            color=TEXT_PRIMARY,
            font_family=FONT_FAMILY,
        )

        # Суммарный Net PnL за выбранный месяц
        self.month_pnl_badge = ft.Container(
            content=ft.Text("$0.00", size=11, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            border_radius=RADIUS_SM,
            bgcolor=SURFACE_2,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

        # Сетка дней
        self.grid_container = ft.Column(spacing=6)

        # Навигация
        prev_btn = ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT_ROUNDED,
            icon_size=18,
            icon_color=TEXT_SECONDARY,
            tooltip="Предыдущий месяц",
            on_click=self._prev_month,
        )
        next_btn = ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT_ROUNDED,
            icon_size=18,
            icon_color=TEXT_SECONDARY,
            tooltip="Следующий месяц",
            on_click=self._next_month,
        )
        today_btn = ft.TextButton(
            "Сегодня",
            style=ft.ButtonStyle(color=ACCENT_PRIMARY, padding=ft.padding.symmetric(horizontal=8, vertical=4)),
            on_click=self._go_today,
        )

        header_row = ft.Row(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.CALENDAR_MONTH_ROUNDED, size=18, color=ACCENT_PRIMARY),
                        ft.Text("P&L КАЛЕНДАРЬ", size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                        self.month_label,
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    [
                        self.month_pnl_badge,
                        prev_btn,
                        today_btn,
                        next_btn,
                    ],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # Дни недели (ПН - ВС)
        weekdays_row = ft.Row(
            [
                ft.Container(
                    content=ft.Text(day, size=10, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO, text_align=ft.TextAlign.CENTER),
                    expand=True,
                    alignment=ft.alignment.center,
                )
                for day in RU_WEEKDAYS
            ],
            spacing=6,
        )

        content_layout = ft.Column(
            [
                header_row,
                ft.Divider(color=BORDER_SUBTLE, height=10),
                weekdays_row,
                self.grid_container,
            ],
            spacing=8,
        )

        super().__init__(
            content=content_layout,
            bgcolor=SURFACE_1,
            border=ft.border.all(1, BORDER_SUBTLE),
            border_radius=RADIUS_LG,
            padding=16,
        )

        self._render_calendar()

    def set_trades(self, trades: List[Trade]) -> None:
        """Обновляет сделки и перерисовывает календарь."""
        self.trades = trades
        self._render_calendar()
        if self.page:
            try:
                self.update()
            except Exception:
                pass
            self.page.update()

    def _get_month_title(self) -> str:
        return f"{RU_MONTHS[self.current_month]} {self.current_year}"

    def _prev_month(self, _) -> None:
        if self.current_month == 1:
            self.current_month = 12
            self.current_year -= 1
        else:
            self.current_month -= 1
        self.month_label.value = self._get_month_title()
        self._render_calendar()
        if self.page:
            try:
                self.update()
            except Exception:
                pass
            self.page.update()

    def _next_month(self, _) -> None:
        if self.current_month == 12:
            self.current_month = 1
            self.current_year += 1
        else:
            self.current_month += 1
        self.month_label.value = self._get_month_title()
        self._render_calendar()
        if self.page:
            try:
                self.update()
            except Exception:
                pass
            self.page.update()

    def _go_today(self, _) -> None:
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self.month_label.value = self._get_month_title()
        self._render_calendar()
        if self.page:
            try:
                self.update()
            except Exception:
                pass
            self.page.update()

    def _render_calendar(self) -> None:
        """Генерирует 7-колоночную сетку дней с подсветкой Net PnL и градиентным Heatmap."""
        self.grid_container.controls.clear()

        # Группируем сделки по дате закрытия
        daily_stats: Dict[date, Dict[str, Any]] = {}
        month_total_pnl = 0.0

        for t in self.trades:
            if not t.closed_at:
                continue
            dt = t.closed_at.date()
            if dt.year == self.current_year and dt.month == self.current_month:
                month_total_pnl += t.net_pnl

            if dt not in daily_stats:
                daily_stats[dt] = {"net_pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
            daily_stats[dt]["net_pnl"] += t.net_pnl
            daily_stats[dt]["trades"] += 1
            if t.net_pnl > 0:
                daily_stats[dt]["wins"] += 1
            elif t.net_pnl < 0:
                daily_stats[dt]["losses"] += 1

        # Обновляем плашку месяца
        sign = "+" if month_total_pnl > 0 else ""
        self.month_pnl_badge.content.value = f"Месяц: {sign}${month_total_pnl:,.2f}"
        if month_total_pnl > 0:
            self.month_pnl_badge.content.color = PROFIT
            self.month_pnl_badge.bgcolor = ft.Colors.with_opacity(0.14, PROFIT)
            self.month_pnl_badge.border = ft.border.all(1, ft.Colors.with_opacity(0.4, PROFIT))
        elif month_total_pnl < 0:
            self.month_pnl_badge.content.color = LOSS
            self.month_pnl_badge.bgcolor = ft.Colors.with_opacity(0.14, LOSS)
            self.month_pnl_badge.border = ft.border.all(1, ft.Colors.with_opacity(0.4, LOSS))
        else:
            self.month_pnl_badge.content.color = TEXT_MUTED
            self.month_pnl_badge.bgcolor = SURFACE_2
            self.month_pnl_badge.border = ft.border.all(1, BORDER_SUBTLE)

        # Календарная матрица недель
        cal = calendar.monthcalendar(self.current_year, self.current_month)

        for week in cal:
            week_row = ft.Row(spacing=6)
            week_pnl = 0.0
            week_trades = 0
            week_wins = 0

            for day in week:
                if day == 0:
                    # Пустая ячейка для выравнивания начала/конца месяца
                    week_row.controls.append(
                        ft.Container(
                            expand=True,
                            height=64,
                            bgcolor=ft.Colors.with_opacity(0.02, TEXT_MUTED),
                            border_radius=RADIUS_MD,
                        )
                    )
                else:
                    cell_date = date(self.current_year, self.current_month, day)
                    st = daily_stats.get(cell_date)
                    if st:
                        week_pnl += st["net_pnl"]
                        week_trades += st["trades"]
                        week_wins += st["wins"]
                    cell = self._create_day_cell(cell_date, st)
                    week_row.controls.append(cell)

            # 8-я колонка: ИТОГ НЕДЕЛИ
            week_wr = int((week_wins / week_trades) * 100) if week_trades > 0 else 0
            summary_cell = self._create_week_summary_cell(week_pnl, week_trades, week_wr)
            week_row.controls.append(summary_cell)

            self.grid_container.controls.append(week_row)

    def _create_week_summary_cell(self, net_pnl: float, trades_cnt: int, winrate: int) -> ft.Container:
        """Создает стилизованную ячейку 'Итог недели' (8-я колонка календаря)."""
        if trades_cnt > 0:
            sign = "+" if net_pnl > 0 else ""
            pnl_text = f"{sign}${net_pnl:,.0f}"
            intensity = min(max(abs(net_pnl) / 700.0, 0.12), 0.35)
            if net_pnl > 0:
                bg_col = ft.Colors.with_opacity(intensity, PROFIT)
                border_col = ft.Colors.with_opacity(0.45, PROFIT)
                text_col = PROFIT
            elif net_pnl < 0:
                bg_col = ft.Colors.with_opacity(intensity, LOSS)
                border_col = ft.Colors.with_opacity(0.45, LOSS)
                text_col = LOSS
            else:
                bg_col = SURFACE_2
                border_col = BORDER_SUBTLE
                text_col = TEXT_SECONDARY

            content = ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("ИТОГ", size=9, weight=ft.FontWeight.BOLD, color=ACCENT_SECONDARY, font_family=FONT_MONO),
                            ft.Text(f"{trades_cnt} сд", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=ft.Text(pnl_text, size=11, weight=ft.FontWeight.BOLD, color=text_col, font_family=FONT_MONO),
                        alignment=ft.alignment.center,
                    ),
                    ft.Container(
                        content=ft.Text(f"{trades_cnt} сд • {winrate}%", size=8, color=TEXT_MUTED, font_family=FONT_MONO),
                        alignment=ft.alignment.center,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                spacing=1,
            )
        else:
            bg_col = ft.Colors.with_opacity(0.03, TEXT_MUTED)
            border_col = ft.Colors.with_opacity(0.1, TEXT_MUTED)
            content = ft.Column(
                [
                    ft.Text("ИТОГ", size=9, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO),
                    ft.Container(
                        content=ft.Text("—", size=10, color=ft.Colors.with_opacity(0.25, TEXT_MUTED), font_family=FONT_MONO),
                        alignment=ft.alignment.center,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                spacing=2,
            )

        return ft.Container(
            content=content,
            expand=True,
            height=64,
            bgcolor=bg_col,
            border=ft.border.all(1, border_col),
            border_radius=RADIUS_MD,
            padding=ft.padding.all(6),
        )

    def _create_day_cell(self, cell_date: date, stat: Optional[Dict[str, Any]]) -> ft.Container:
        """Создает стилизованную ячейку дня с непрерывной градацией PnL (Continuous Heatmap)."""
        is_today = cell_date == date.today()

        if stat and stat["trades"] > 0:
            net_pnl = stat["net_pnl"]
            trades_cnt = stat["trades"]
            wins_cnt = stat.get("wins", 0)
            winrate = int((wins_cnt / trades_cnt) * 100) if trades_cnt > 0 else 0
            sign = "+" if net_pnl > 0 else ""
            pnl_text = f"{sign}${net_pnl:,.0f}"

            # Continuous heatmap opacity
            intensity = min(max(abs(net_pnl) / 500.0, 0.12), 0.35)

            if net_pnl > 0:
                bg_col = ft.Colors.with_opacity(intensity, PROFIT)
                border_col = ft.Colors.with_opacity(min(intensity * 2.2, 0.7), PROFIT)
                text_col = PROFIT
            elif net_pnl < 0:
                bg_col = ft.Colors.with_opacity(intensity, LOSS)
                border_col = ft.Colors.with_opacity(min(intensity * 2.2, 0.7), LOSS)
                text_col = LOSS
            else:
                bg_col = SURFACE_2
                border_col = BORDER_SUBTLE
                text_col = TEXT_SECONDARY

            cell_content = ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(str(cell_date.day), size=11, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_MONO),
                            ft.Text(f"{trades_cnt} сд", size=9, color=TEXT_MUTED, font_family=FONT_MONO),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=ft.Text(pnl_text, size=11, weight=ft.FontWeight.BOLD, color=text_col, font_family=FONT_MONO),
                        alignment=ft.alignment.center,
                    ),
                    ft.Container(
                        content=ft.Text(f"{trades_cnt} сд • {winrate}%", size=8, color=TEXT_MUTED, font_family=FONT_MONO),
                        alignment=ft.alignment.center,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                spacing=1,
            )
        else:
            # Дни без сделок: нейтральный темный фон
            bg_col = SURFACE_1
            border_col = BORDER_SUBTLE if not is_today else ACCENT_PRIMARY
            cell_content = ft.Column(
                [
                    ft.Text(
                        str(cell_date.day),
                        size=11,
                        weight=ft.FontWeight.BOLD if is_today else ft.FontWeight.NORMAL,
                        color=ACCENT_PRIMARY if is_today else TEXT_MUTED,
                        font_family=FONT_MONO,
                    ),
                    ft.Container(
                        content=ft.Text("—", size=10, color=ft.Colors.with_opacity(0.25, TEXT_MUTED), font_family=FONT_MONO),
                        alignment=ft.alignment.center,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                spacing=2,
            )

        card = ft.Container(
            content=cell_content,
            expand=True,
            height=64,
            bgcolor=bg_col,
            border=ft.border.all(1.5 if is_today else 1, border_col),
            border_radius=RADIUS_MD,
            padding=ft.padding.all(6),
            tooltip=f"{cell_date.strftime('%d.%m.%Y')} — Кликните для фильтрации в Журнале",
            on_click=lambda _, cd=cell_date: self._on_cell_clicked(cd),
        )

        def _on_hover(e: ft.HoverEvent, c=card, def_border=border_col, def_bg=bg_col):
            if not ANIMATIONS_ENABLED:
                return
            if e.data == "true":
                c.border = ft.border.all(1.5, BORDER_HIGHLIGHT)
            else:
                c.border = ft.border.all(1.5 if is_today else 1, def_border)
            try:
                c.update()
            except Exception:
                pass

        card.on_hover = _on_hover
        return card

    def _on_cell_clicked(self, clicked_date: date) -> None:
        """Переход в журнал с фильтрацией по дате."""
        if self.on_date_selected:
            self.on_date_selected(clicked_date)
