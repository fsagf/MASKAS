"""
Модальное окно сделки (ui/components/trade_modal.py)
Создание и редактирование сделок, живой расчет Net PnL, Risk ($) и R-Multiple,
проверка чек-листа сетапа с детектором риска тильта, захват скриншотов из буфера (Ctrl+V)
и системный выбор файлов (FilePicker).
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional
import flet as ft

from analytics import AnalyticsService
from database import DatabaseManager, Trade, calculate_gross_pnl
from ui.theme import (
    ACCENT_PRIMARY,
    ACCENT_SECONDARY,
    ANIM_FAST_MS,
    ANIMATIONS_ENABLED,
    BG_APP,
    SURFACE_OVERLAY,
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

try:
    from PIL import ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class TradeModal(ft.AlertDialog):
    """
    Продвинутое модальное окно для создания и редактирования сделки.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        on_trade_saved: Optional[Callable[[], None]] = None,
    ):
        self.db = db_manager
        self.on_trade_saved = on_trade_saved
        self.editing_trade_id: Optional[int] = None
        self.screenshot_path_val: Optional[str] = None

        # FilePicker для выбора скриншота
        self.screenshot_picker = ft.FilePicker(on_result=self._on_file_picked)

        # DatePicker для выбора даты закрытия
        self.date_picker = ft.DatePicker(on_change=self._on_date_picked)

        # Поля ввода
        self.ticker_field = ft.TextField(
            label="Тикер инструмента",
            hint_text="BTC/USDT, NVDA, AAPL",
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            bgcolor=SURFACE_1,
            color=TEXT_PRIMARY,
            border_radius=10,
            text_size=13,
            text_style=ft.TextStyle(font_family=FONT_MONO),
            expand=True,
        )

        self.direction_dropdown = ft.Dropdown(
            label="Направление",
            options=[
                ft.dropdown.Option("LONG", "LONG (Покупка)"),
                ft.dropdown.Option("SHORT", "SHORT (Продажа)"),
            ],
            value="LONG",
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            bgcolor=SURFACE_1,
            color=TEXT_PRIMARY,
            border_radius=10,
            width=180,
            on_change=lambda _: self._update_pnl_preview(),
        )

        self.strategy_field = ft.TextField(
            label="Стратегия / Сетап",
            hint_text="Breakout, Trend Following, Scalping...",
            value="Breakout",
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            bgcolor=SURFACE_1,
            color=TEXT_PRIMARY,
            border_radius=10,
            text_size=13,
            expand=True,
        )

        self.entry_price_field = ft.TextField(
            label="Цена входа ($)",
            keyboard_type=ft.KeyboardType.NUMBER,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            bgcolor=SURFACE_1,
            color=TEXT_PRIMARY,
            border_radius=10,
            text_size=13,
            text_style=ft.TextStyle(font_family=FONT_MONO),
            expand=True,
            on_change=lambda _: self._update_pnl_preview(),
        )

        self.exit_price_field = ft.TextField(
            label="Цена выхода ($)",
            keyboard_type=ft.KeyboardType.NUMBER,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            bgcolor=SURFACE_1,
            color=TEXT_PRIMARY,
            border_radius=10,
            text_size=13,
            text_style=ft.TextStyle(font_family=FONT_MONO),
            expand=True,
            on_change=lambda _: self._update_pnl_preview(),
        )

        self.volume_field = ft.TextField(
            label="Объем позиции",
            keyboard_type=ft.KeyboardType.NUMBER,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            bgcolor=SURFACE_1,
            color=TEXT_PRIMARY,
            border_radius=10,
            text_size=13,
            text_style=ft.TextStyle(font_family=FONT_MONO),
            expand=True,
            on_change=lambda _: self._update_pnl_preview(),
        )

        self.stop_loss_field = ft.TextField(
            label="Стоп-лосс (SL $)",
            keyboard_type=ft.KeyboardType.NUMBER,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            bgcolor=SURFACE_1,
            color=TEXT_PRIMARY,
            border_radius=10,
            text_size=13,
            text_style=ft.TextStyle(font_family=FONT_MONO),
            expand=True,
            on_change=lambda _: self._update_pnl_preview(),
        )

        self.take_profit_field = ft.TextField(
            label="Тейк-профит (TP $)",
            keyboard_type=ft.KeyboardType.NUMBER,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            bgcolor=SURFACE_1,
            color=TEXT_PRIMARY,
            border_radius=10,
            text_size=13,
            text_style=ft.TextStyle(font_family=FONT_MONO),
            expand=True,
        )

        self.commission_field = ft.TextField(
            label="Комиссия ($)",
            value="0.0",
            keyboard_type=ft.KeyboardType.NUMBER,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            bgcolor=SURFACE_1,
            color=TEXT_PRIMARY,
            border_radius=10,
            text_size=13,
            text_style=ft.TextStyle(font_family=FONT_MONO),
            expand=True,
            on_change=lambda _: self._update_pnl_preview(),
        )

        self.notes_field = ft.TextField(
            label="Заметки по сделке (эмоции, контекст рынка, ошибки)",
            multiline=True,
            min_lines=2,
            max_lines=3,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            bgcolor=SURFACE_1,
            color=TEXT_PRIMARY,
            border_radius=10,
            text_size=12,
        )

        # Выбранная дата
        self.selected_date = datetime.now()
        self.date_btn = ft.OutlinedButton(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CALENDAR_TODAY_ROUNDED, size=15, color=ACCENT_PRIMARY),
                    ft.Text(f"{self.selected_date.strftime('%d.%m.%Y')}", size=12, font_family=FONT_MONO),
                ],
                spacing=6,
                tight=True,
            ),
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                side=ft.BorderSide(1, BORDER_SUBTLE),
            ),
            on_click=lambda _: self._open_date_picker(),
        )

        # Чекбоксы торгового плана
        self.check_trend = ft.Checkbox(label="По тренду старшего ТФ", value=True, active_color=ACCENT_PRIMARY, on_change=lambda _: self._on_checklist_change())
        self.check_risk = ft.Checkbox(label="Риск < 1% от депозита", value=True, active_color=ACCENT_PRIMARY, on_change=lambda _: self._on_checklist_change())
        self.check_volume = ft.Checkbox(label="Подтверждение объемом", value=True, active_color=ACCENT_PRIMARY, on_change=lambda _: self._on_checklist_change())
        self.check_emotion = ft.Checkbox(label="Вход строго без эмоций", value=True, active_color=ACCENT_PRIMARY, on_change=lambda _: self._on_checklist_change())

        # Предупреждение о риске тильта
        self.tilt_warning_badge = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=16, color=WARNING_TILT),
                    ft.Text("Внимание: сделка вне системы (высокий риск тильта)", size=11, color=WARNING_TILT, weight=ft.FontWeight.W_600),
                ],
                spacing=6,
            ),
            bgcolor=f"{WARNING_TILT}1A",
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            border_radius=6,
            border=ft.border.all(1, f"{WARNING_TILT}55"),
            visible=False,
        )

        # Индикаторы живого калькулятора
        self.preview_net_pnl = ft.Text("$0.00", size=18, weight=ft.FontWeight.BOLD, color=TEXT_SECONDARY, font_family=FONT_MONO)
        self.preview_risk = ft.Text("$0.00", size=15, weight=ft.FontWeight.BOLD, color=TEXT_MUTED, font_family=FONT_MONO)
        self.preview_r_mult = ft.Text("0.0 R", size=15, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY, font_family=FONT_MONO)

        # Статус скриншота
        self.screenshot_status_text = ft.Text("Скриншот не прикреплен", size=11, color=TEXT_MUTED)

        self.error_text = ft.Text("", color=LOSS, size=12)
        self.dialog_title_text = ft.Text("Новая сделка", size=18, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)

        super().__init__(
            modal=True,
            title=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.ADD_CHART_ROUNDED, color=ACCENT_PRIMARY, size=22),
                    self.dialog_title_text,
                ],
                spacing=8,
            ),
            content=self._build_content(),
            actions=[
                ft.TextButton(
                    content=ft.Text("Отмена", color=TEXT_SECONDARY),
                    on_click=lambda _: self.close(),
                ),
                ft.Container(
                    content=ft.ElevatedButton(
                        content=ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.CHECK_ROUNDED, size=18),
                                ft.Text("Сохранить в журнал", weight=ft.FontWeight.BOLD),
                            ],
                            tight=True,
                            spacing=6,
                        ),
                        style=ft.ButtonStyle(
                            bgcolor=ACCENT_PRIMARY,
                            color=TEXT_PRIMARY,
                            padding=ft.padding.symmetric(horizontal=20, vertical=12),
                            shape=ft.RoundedRectangleBorder(radius=10),
                        ),
                        on_click=self._submit_trade,
                    ),
                    shadow=create_neon_box_shadow(ACCENT_PRIMARY, blur=12, opacity="44"),
                    border_radius=10,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor=SURFACE_OVERLAY,
            shape=ft.RoundedRectangleBorder(radius=16),
        )

    def _build_content(self) -> ft.Container:
        # Калькулятор живого расчета (Live Preview)
        calculator_bar = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text("ОЖИДАЕМЫЙ NET PnL", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                            self.preview_net_pnl,
                        ],
                        spacing=2,
                    ),
                    ft.VerticalDivider(width=1, color=BORDER_SUBTLE),
                    ft.Column(
                        controls=[
                            ft.Text("РИСК (1R)", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                            self.preview_risk,
                        ],
                        spacing=2,
                    ),
                    ft.VerticalDivider(width=1, color=BORDER_SUBTLE),
                    ft.Column(
                        controls=[
                            ft.Text("R-MULTIPLE", size=10, color=TEXT_MUTED, font_family=FONT_MONO),
                            self.preview_r_mult,
                        ],
                        spacing=2,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_AROUND,
            ),
            bgcolor=BG_APP,
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            border_radius=10,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

        # Чек-лист сетапа
        checklist_block = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.CHECKLIST_RTL_ROUNDED, size=16, color=ACCENT_PRIMARY),
                            ft.Text("Чек-лист дисциплины и сетапа", size=12, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY),
                        ],
                        spacing=6,
                    ),
                    ft.ResponsiveRow(
                        controls=[
                            ft.Container(self.check_trend, col={"sm": 6}),
                            ft.Container(self.check_risk, col={"sm": 6}),
                            ft.Container(self.check_volume, col={"sm": 6}),
                            ft.Container(self.check_emotion, col={"sm": 6}),
                        ],
                        run_spacing=2,
                    ),
                    self.tilt_warning_badge,
                ],
                spacing=6,
            ),
            padding=12,
            bgcolor=BG_APP,
            border_radius=10,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

        # Блок прикрепления скриншотов
        screenshot_block = ft.Container(
            content=ft.Row(
                controls=[
                    ft.ElevatedButton(
                        content=ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.PASTE_ROUNDED, size=15),
                                ft.Text("Вставить скриншот (Ctrl+V)", size=11),
                            ],
                            tight=True,
                            spacing=4,
                        ),
                        style=ft.ButtonStyle(
                            bgcolor=SURFACE_1,
                            shape=ft.RoundedRectangleBorder(radius=8),
                        ),
                        on_click=lambda _: self._paste_screenshot_from_clipboard(),
                    ),
                    ft.OutlinedButton(
                        content=ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.UPLOAD_FILE_ROUNDED, size=15),
                                ft.Text("Обзор", size=11),
                            ],
                            tight=True,
                            spacing=4,
                        ),
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=8),
                            side=ft.BorderSide(1, BORDER_SUBTLE),
                        ),
                        on_click=lambda _: self.screenshot_picker.pick_files(allowed_extensions=["png", "jpg", "webp"]),
                    ),
                    ft.Container(content=self.screenshot_status_text, expand=True),
                ],
                spacing=8,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            bgcolor=BG_APP,
            border_radius=8,
            border=ft.border.all(1, BORDER_SUBTLE),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    self.screenshot_picker,
                    self.date_picker,
                    calculator_bar,
                    ft.Row([self.ticker_field, self.direction_dropdown], spacing=10),
                    ft.Row([self.strategy_field, self.date_btn], spacing=10),
                    ft.Row([self.entry_price_field, self.exit_price_field, self.volume_field], spacing=10),
                    ft.Row([self.stop_loss_field, self.take_profit_field, self.commission_field], spacing=10),
                    self.notes_field,
                    checklist_block,
                    screenshot_block,
                    self.error_text,
                ],
                spacing=10,
                tight=True,
            ),
            width=620,
            padding=ft.padding.only(top=6),
        )

    def _safe_update(self) -> None:
        """Безопасный вызов update с защитой от отсутствия монтирования к Page."""
        try:
            self.update()
        except (AssertionError, Exception):
            pass

    def _open_date_picker(self):
        self.date_picker.pick_date()

    def _on_date_picked(self, e):
        if self.date_picker.value:
            self.selected_date = self.date_picker.value
            self.date_btn.content.controls[1].value = self.selected_date.strftime("%d.%m.%Y")
            self._safe_update()

    def _on_file_picked(self, e: ft.FilePickerResultEvent):
        if e.files:
            file_path = e.files[0].path
            self.screenshot_path_val = file_path
            self.screenshot_status_text.value = f"Скриншот: {Path(file_path).name}"
            self.screenshot_status_text.color = PROFIT
            self._safe_update()

    def _paste_screenshot_from_clipboard(self):
        """Захватывает изображение из системного буфера обмена через PIL.ImageGrab."""
        if not PIL_AVAILABLE:
            self.screenshot_status_text.value = "Pillow не доступен, используйте кнопку Обзор"
            self._safe_update()
            return

        try:
            img = ImageGrab.grabclipboard()
            if img is not None:
                save_dir = Path(__file__).resolve().parent.parent.parent / "assets" / "screenshots"
                save_dir.mkdir(parents=True, exist_ok=True)
                fn = f"tv_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                out_path = save_dir / fn
                img.save(str(out_path), "PNG")
                self.screenshot_path_val = str(out_path)
                self.screenshot_status_text.value = f"Вставлен из буфера: {fn}"
                self.screenshot_status_text.color = PROFIT
                self._safe_update()
            else:
                self.screenshot_status_text.value = "Буфер обмена не содержит изображение"
                self.screenshot_status_text.color = WARNING_TILT
                self._safe_update()
        except Exception as ex:
            self.screenshot_status_text.value = f"Ошибка вставки: {ex}"
            self._safe_update()

    def _on_checklist_change(self):
        """Проверяет соблюдение торгового плана."""
        checked_count = sum([
            bool(self.check_trend.value),
            bool(self.check_risk.value),
            bool(self.check_volume.value),
            bool(self.check_emotion.value),
        ])
        self.tilt_warning_badge.visible = (checked_count < 3)
        self._safe_update()

    def _update_pnl_preview(self) -> None:
        """Пересчитывает ожидаемые Net PnL, Risk ($) и R-Multiple на лету."""
        try:
            entry = float(self.entry_price_field.value.replace(",", "."))
            exit_p = float(self.exit_price_field.value.replace(",", "."))
            vol = float(self.volume_field.value.replace(",", "."))
            comm = float(self.commission_field.value.replace(",", ".") if self.commission_field.value else 0.0)
            direction = self.direction_dropdown.value or "LONG"

            gross = calculate_gross_pnl(direction, entry, exit_p, vol)
            net = round(gross - comm, 2)

            color = PROFIT if net > 0 else (LOSS if net < 0 else TEXT_SECONDARY)
            self.preview_net_pnl.value = f"{'+' if net > 0 else ''}${net:,.2f}"
            self.preview_net_pnl.color = color

            # Расчет риска
            sl_str = self.stop_loss_field.value or ""
            if sl_str:
                sl_val = float(sl_str.replace(",", "."))
                risk = round(abs(entry - sl_val) * vol, 2)
            else:
                risk = round(entry * vol * 0.015, 2)

            self.preview_risk.value = f"${risk:,.2f}"

            if risk > 0:
                r_mult = round(net / risk, 2)
                self.preview_r_mult.value = f"{r_mult:+.2f} R"
                self.preview_r_mult.color = PROFIT if r_mult > 0 else LOSS
            else:
                self.preview_r_mult.value = "0.0 R"
                self.preview_r_mult.color = ACCENT_PRIMARY

            self.error_text.value = ""
        except (ValueError, AttributeError):
            self.preview_net_pnl.value = "$0.00"
            self.preview_net_pnl.color = TEXT_SECONDARY
            self.preview_risk.value = "$0.00"
            self.preview_r_mult.value = "0.0 R"

        self._safe_update()

    def open_for_create(self) -> None:
        """Инициализация модалки для создания новой сделки."""
        self.editing_trade_id = None
        self.dialog_title_text.value = "Новая сделка"
        self.ticker_field.value = ""
        self.entry_price_field.value = ""
        self.exit_price_field.value = ""
        self.volume_field.value = ""
        self.stop_loss_field.value = ""
        self.take_profit_field.value = ""
        self.commission_field.value = "0.0"
        self.notes_field.value = ""
        self.screenshot_path_val = None
        self.screenshot_status_text.value = "Скриншот не прикреплен"
        self.screenshot_status_text.color = TEXT_MUTED
        self.selected_date = datetime.now()
        self.date_btn.content.controls[1].value = self.selected_date.strftime("%d.%m.%Y")
        self.error_text.value = ""
        self._update_pnl_preview()
        self.open = True
        if self.page:
            self.page.update()

    def open_for_edit(self, trade: Trade) -> None:
        """Инициализация модалки для редактирования существующей сделки."""
        self.editing_trade_id = trade.id
        self.dialog_title_text.value = f"Редактирование сделки #{trade.id} ({trade.ticker})"
        self.ticker_field.value = trade.ticker
        self.direction_dropdown.value = trade.direction.upper()
        self.strategy_field.value = trade.strategy_tag
        self.entry_price_field.value = str(trade.entry_price)
        self.exit_price_field.value = str(trade.exit_price)
        self.volume_field.value = str(trade.volume)
        self.stop_loss_field.value = str(trade.stop_loss) if trade.stop_loss else ""
        self.take_profit_field.value = str(trade.take_profit) if trade.take_profit else ""
        self.commission_field.value = str(trade.commission)
        self.notes_field.value = trade.notes or ""
        self.screenshot_path_val = trade.screenshot_path
        self.screenshot_status_text.value = f"Скриншот: {Path(trade.screenshot_path).name}" if trade.screenshot_path else "Скриншот не прикреплен"
        self.screenshot_status_text.color = PROFIT if trade.screenshot_path else TEXT_MUTED
        self.selected_date = trade.closed_at
        self.date_btn.content.controls[1].value = self.selected_date.strftime("%d.%m.%Y")
        self.error_text.value = ""
        self._update_pnl_preview()
        self.open = True
        if self.page:
            self.page.update()

    def _submit_trade(self, _) -> None:
        """Валидация, Behavioral проверка тильта и сохранение сделки в БД."""
        ticker = (self.ticker_field.value or "").strip().upper()
        if not ticker:
            self.error_text.value = "Ошибка: Укажите тикер финансового инструмента."
            self._safe_update()
            return

        try:
            entry = float(self.entry_price_field.value.replace(",", "."))
            exit_p = float(self.exit_price_field.value.replace(",", "."))
            vol = float(self.volume_field.value.replace(",", "."))
            comm = float(self.commission_field.value.replace(",", ".") if self.commission_field.value else 0.0)
            sl = float(self.stop_loss_field.value.replace(",", ".")) if self.stop_loss_field.value else None
            tp = float(self.take_profit_field.value.replace(",", ".")) if self.take_profit_field.value else None

            if entry <= 0 or exit_p <= 0 or vol <= 0:
                raise ValueError()
        except (ValueError, AttributeError):
            self.error_text.value = "Ошибка: Цены и объем должны быть строго положительными числами."
            self._safe_update()
            return

        direction = self.direction_dropdown.value or "LONG"
        strategy = (self.strategy_field.value or "Общая").strip()
        notes = (self.notes_field.value or "").strip()

        checklist_ok = (
            bool(self.check_trend.value)
            and bool(self.check_risk.value)
            and bool(self.check_volume.value)
            and bool(self.check_emotion.value)
        )

        # Детектор тильта
        recent_trades = self.db.get_all_trades(order_by_date_desc=True)
        candidate_dict = {
            "checklist_passed": checklist_ok,
            "opened_at": self.selected_date - timedelta(hours=2),
            "volume": vol,
            "risk_amount": abs(entry - sl) * vol if sl else (entry * vol * 0.015),
        }
        is_tilt, tilt_reason = AnalyticsService.detect_tilt(candidate_dict, recent_trades)

        if self.editing_trade_id is None:
            # Создание новой сделки
            self.db.add_trade(
                ticker=ticker,
                direction=direction,
                entry_price=entry,
                exit_price=exit_p,
                volume=vol,
                strategy_tag=strategy,
                stop_loss=sl,
                take_profit=tp,
                commission=comm,
                opened_at=self.selected_date - timedelta(hours=2),
                closed_at=self.selected_date,
                checklist_passed=checklist_ok,
                is_tilt=is_tilt,
                tilt_reason=tilt_reason,
                notes=notes,
                screenshot_path=self.screenshot_path_val,
            )
            msg = f"Сделка {ticker} ({direction}) успешно зафиксирована!"
        else:
            # Обновление существующей сделки
            self.db.update_trade(
                self.editing_trade_id,
                ticker=ticker,
                direction=direction,
                entry_price=entry,
                exit_price=exit_p,
                volume=vol,
                strategy_tag=strategy,
                stop_loss=sl,
                take_profit=tp,
                commission=comm,
                closed_at=self.selected_date,
                checklist_passed=checklist_ok,
                is_tilt=is_tilt,
                tilt_reason=tilt_reason,
                notes=notes,
                screenshot_path=self.screenshot_path_val,
            )
            msg = f"Сделка #{self.editing_trade_id} {ticker} успешно обновлена!"

        self.close()

        if self.page:
            self.page.show_snack_bar(
                ft.SnackBar(
                    content=ft.Text(msg),
                    bgcolor=WARNING_TILT if is_tilt else PROFIT,
                )
            )

        if self.on_trade_saved:
            self.on_trade_saved()

    def close(self) -> None:
        if self.page:
            try:
                self.page.close(self)
            except Exception:
                self.open = False
                self.page.update()
        else:
            self.open = False
