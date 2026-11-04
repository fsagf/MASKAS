"""
ui/components/account_modal.py
Модальное окно управления мульти-аккаунтами и прямой автосинхронизацией.
Поддержка Binance, Bybit (ccxt), MetaTrader 5 и ручных счетов.
Шифрование ключей, статус подключения и фоновая синхронизация с анимацией спиннера.
"""

from typing import Callable, Optional
import flet as ft

from database import DatabaseManager
from services.sync_service import SyncService, encrypt_secret
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


class AccountModal(ft.AlertDialog):
    """
    Модальное окно для управления торговыми счетами и прямой синхронизацией.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        on_account_updated: Optional[Callable[[], None]] = None,
    ):
        self.db = db_manager
        self.on_account_updated = on_account_updated

        self.title_text = ft.Text(
            "Управление торговыми счетами & API Синхронизация",
            size=18,
            weight=ft.FontWeight.BOLD,
            color=TEXT_PRIMARY,
        )

        self.status_banner = ft.Container(
            content=ft.Text("", size=12, color=TEXT_PRIMARY),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border_radius=8,
            visible=False,
        )

        # Контейнер списка существующих счетов
        self.accounts_list_view = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)

        # Форма добавления нового счета
        self.new_name_field = ft.TextField(
            label="Название счета",
            hint_text="Например: Binance Futures, MT5 Prop $50K",
            bgcolor=SURFACE_1,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            color=TEXT_PRIMARY,
            border_radius=RADIUS_MD,
            text_size=13,
            expand=True,
        )

        self.exchange_dropdown = ft.Dropdown(
            label="Тип подключения",
            bgcolor=SURFACE_1,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            color=TEXT_PRIMARY,
            border_radius=RADIUS_MD,
            text_size=13,
            width=180,
            options=[
                ft.dropdown.Option("BINANCE", "Binance Futures / Spot"),
                ft.dropdown.Option("BYBIT", "Bybit Linear / Unified"),
                ft.dropdown.Option("OKX", "OKX Perpetual / Swap"),
                ft.dropdown.Option("MT5", "MetaTrader 5 (Prop/Forex)"),
                ft.dropdown.Option("MANUAL", "Ручной счет (Manual)"),
            ],
            value="BINANCE",
        )

        self.initial_balance_field = ft.TextField(
            label="Депозит",
            hint_text="10000.0",
            value="10000.0",
            bgcolor=SURFACE_1,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            color=TEXT_PRIMARY,
            border_radius=RADIUS_MD,
            text_size=13,
            width=130,
        )

        self.currency_dropdown = ft.Dropdown(
            label="Валюта",
            bgcolor=SURFACE_1,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            color=TEXT_PRIMARY,
            border_radius=RADIUS_MD,
            text_size=13,
            width=100,
            options=[
                ft.dropdown.Option("USD", "USD"),
                ft.dropdown.Option("USDT", "USDT"),
                ft.dropdown.Option("EUR", "EUR"),
            ],
            value="USD",
        )

        self.api_key_field = ft.TextField(
            label="API Key / MT5 Login",
            password=True,
            can_reveal_password=True,
            bgcolor=SURFACE_1,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            color=TEXT_PRIMARY,
            border_radius=RADIUS_MD,
            text_size=13,
            expand=True,
        )

        self.api_secret_field = ft.TextField(
            label="API Secret / MT5 Pass & Server",
            password=True,
            can_reveal_password=True,
            bgcolor=SURFACE_1,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            color=TEXT_PRIMARY,
            border_radius=RADIUS_MD,
            text_size=13,
            expand=True,
        )

        self.account_num_field = ft.TextField(
            label="Номер счета",
            hint_text="Например: BIN-1029",
            bgcolor=SURFACE_1,
            border_color=BORDER_SUBTLE,
            focused_border_color=ACCENT_PRIMARY,
            color=TEXT_PRIMARY,
            border_radius=RADIUS_MD,
            text_size=13,
            width=180,
        )

        self.add_btn = ft.ElevatedButton(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.ADD_CARD_OUTLINED, size=16, color=TEXT_PRIMARY),
                    ft.Text("Подключить счет", size=13, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=6,
            ),
            bgcolor=ACCENT_PRIMARY,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self._on_add_account,
        )

        # Компоновка контента
        content_box = ft.Container(
            content=ft.Column(
                [
                    self.status_banner,
                    ft.Text("ПОДКЛЮЧЕННЫЕ СЧЕТА", size=11, weight=ft.FontWeight.BOLD, color=TEXT_MUTED),
                    ft.Container(
                        content=self.accounts_list_view,
                        height=160,
                        bgcolor=BG_APP,
                        border=ft.border.all(1, BORDER_SUBTLE),
                        border_radius=10,
                        padding=10,
                    ),
                    ft.Divider(color=BORDER_SUBTLE, height=15),
                    ft.Text("ПОДКЛЮЧЕНИЕ НОВОГО СЧЕТА", size=11, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
                    ft.Row([self.new_name_field, self.exchange_dropdown], spacing=10),
                    ft.Row([self.api_key_field, self.api_secret_field], spacing=10),
                    ft.Row(
                        [
                            self.account_num_field,
                            self.initial_balance_field,
                            self.currency_dropdown,
                            ft.Container(expand=True),
                            self.add_btn,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=14),  # Защитный отступ от панели действий
                ],
                spacing=12,
                scroll=ft.ScrollMode.ADAPTIVE,
                tight=True,
            ),
            width=680,
            height=470,
            padding=ft.padding.only(left=10, right=10, top=4, bottom=12),
        )

        super().__init__(
            title=self.title_text,
            content=content_box,
            content_padding=ft.padding.symmetric(horizontal=24, vertical=16),
            actions=[
                ft.OutlinedButton(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.SYNC, size=15, color=ACCENT_SECONDARY),
                            ft.Text("Синхронизировать ВСЕ счета", size=12, color=ACCENT_SECONDARY, font_family=FONT_FAMILY),
                        ],
                        spacing=6,
                    ),
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
                        side=ft.BorderSide(1, ACCENT_SECONDARY),
                    ),
                    on_click=self._sync_all_accounts,
                ),
                ft.TextButton(
                    "Закрыть",
                    style=ft.ButtonStyle(color=TEXT_SECONDARY),
                    on_click=self._close,
                ),
            ],
            actions_padding=ft.padding.only(left=24, right=24, bottom=16, top=8),
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            modal=True,
            bgcolor=SURFACE_OVERLAY,
            shape=ft.RoundedRectangleBorder(radius=RADIUS_LG),
        )

    def open_modal(self) -> None:
        """Открывает модальное окно и обновляет список счетов."""
        self.status_banner.visible = False
        self._refresh_accounts_list()
        self.open = True
        if self.page:
            self.page.update()

    def _close(self, _=None) -> None:
        if self.page:
            try:
                self.page.close(self)
            except Exception:
                self.open = False
                self.page.update()
        else:
            self.open = False

    def _refresh_accounts_list(self) -> None:
        """Перерисовывает список существующих счетов."""
        self.accounts_list_view.controls.clear()
        accounts = self.db.get_accounts()

        if not accounts:
            self.accounts_list_view.controls.append(
                ft.Container(
                    content=ft.Text("Нет подключенных торговых счетов.", color=TEXT_MUTED, size=13, font_family=FONT_FAMILY),
                    alignment=ft.alignment.center,
                    padding=20,
                )
            )
            return

        for acc in accounts:
            badge_color = (
                WARNING_TILT if acc.exchange_type == "BINANCE"
                else ACCENT_PRIMARY if acc.exchange_type == "BYBIT"
                else PROFIT if acc.exchange_type == "MT5"
                else TEXT_SECONDARY
            )

            # Бейдж биржи
            badge = ft.Container(
                content=ft.Text(acc.exchange_type, size=10, weight=ft.FontWeight.BOLD, color=badge_color, font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.14, badge_color),
                border=ft.border.all(1, ft.Colors.with_opacity(0.35, badge_color)),
                border_radius=RADIUS_SM,
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
            )

            # Индикатор количества сделок по счету
            trades_count = len(self.db.get_trades(account_id=acc.id))

            # Спиннер синхронизации
            spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, color=ACCENT_SECONDARY, visible=False)
            sync_btn_text = ft.Text("Синхронизировать", size=11, color=ACCENT_SECONDARY, font_family=FONT_FAMILY)

            sync_btn = ft.OutlinedButton(
                content=ft.Row([spinner, sync_btn_text], spacing=6),
                style=ft.ButtonStyle(
                    padding=ft.padding.symmetric(horizontal=10, vertical=4),
                    shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                    side=ft.BorderSide(1, ft.Colors.with_opacity(0.4, ACCENT_SECONDARY)),
                ),
                on_click=lambda e, a_id=acc.id, sp=spinner, bt=sync_btn_text: self._sync_single_account(a_id, sp, bt),
            )

            sync_info = acc.last_sync_at.strftime('%H:%M %d.%m') if getattr(acc, 'last_sync_at', None) else 'Никогда'
            row = ft.Container(
                content=ft.Row(
                    [
                        badge,
                        ft.Column(
                            [
                                ft.Text(acc.name, size=13, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                ft.Text(
                                    f"№ {acc.account_number or 'N/A'} • Депозит: ${getattr(acc, 'initial_balance', 10000.0):,.0f} {getattr(acc, 'currency', 'USD')} • Сделок: {trades_count} • Синхр: {sync_info}",
                                    size=11,
                                    color=TEXT_MUTED,
                                    font_family=FONT_MONO,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        sync_btn,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                bgcolor=SURFACE_1,
                border_radius=RADIUS_MD,
                border=ft.border.all(1, BORDER_SUBTLE),
            )
            self.accounts_list_view.controls.append(row)

    def _sync_single_account(self, account_id: int, spinner: ft.ProgressRing, btn_text: ft.Text) -> None:
        """Синхронизация одного счета с анимацией спиннера."""
        spinner.visible = True
        btn_text.value = "Синхронизация..."
        if self.page:
            self.page.update()

        try:
            res = SyncService.sync_account(account_id, self.db)
            spinner.visible = False
            btn_text.value = "Синхронизировать"

            self.status_banner.visible = True
            if res.get("success"):
                self.status_banner.bgcolor = ft.Colors.with_opacity(0.15, PROFIT)
                self.status_banner.border = ft.border.all(1, PROFIT)
                self.status_banner.content.value = f"✓ {res.get('message', 'Успешно синхронизировано.')}"
                self.status_banner.content.color = PROFIT
            else:
                self.status_banner.bgcolor = ft.Colors.with_opacity(0.15, LOSS)
                self.status_banner.border = ft.border.all(1, LOSS)
                self.status_banner.content.value = f"✕ {res.get('message', 'Ошибка синхронизации.')}"
                self.status_banner.content.color = LOSS
                self.status_banner.border = ft.border.all(1, LOSS)
                self.status_banner.content.value = f"✕ {res.get('message', 'Ошибка синхронизации.')}"
                self.status_banner.content.color = LOSS

            self._refresh_accounts_list()
            if self.on_account_updated:
                self.on_account_updated()
        except Exception as ex:
            spinner.visible = False
            btn_text.value = "Синхронизировать"
            self.status_banner.visible = True
            self.status_banner.content.value = f"Ошибка: {ex}"
            self.status_banner.content.color = LOSS

        if self.page:
            self.page.update()

    def _sync_all_accounts(self, _) -> None:
        """Синхронизация всех подключенных счетов."""
        accounts = self.db.get_accounts()
        total_new = 0
        messages = []

        for acc in accounts:
            res = SyncService.sync_account(acc.id, self.db)
            if res.get("success"):
                total_new += res.get("new_trades", 0)
                messages.append(f"{acc.name}: +{res.get('new_trades', 0)}")

        self.status_banner.visible = True
        self.status_banner.bgcolor = ft.Colors.with_opacity(0.15, PROFIT)
        self.status_banner.border = ft.border.all(1, PROFIT)
        self.status_banner.content.value = f"Синхронизация завершена: импортировано {total_new} сделок ({', '.join(messages)})"
        self.status_banner.content.color = PROFIT

        self._refresh_accounts_list()
        if self.on_account_updated:
            self.on_account_updated()
        if self.page:
            self.page.update()

    def _on_add_account(self, _) -> None:
        """Добавление нового счета с шифрованием секретов."""
        name = (self.new_name_field.value or "").strip()
        if not name:
            self.status_banner.visible = True
            self.status_banner.content.value = "Укажите название торгового счета."
            self.status_banner.content.color = LOSS
            if self.page:
                self.page.update()
            return

        exchange_type = self.exchange_dropdown.value or "MANUAL"
        raw_key = (self.api_key_field.value or "").strip()
        raw_secret = (self.api_secret_field.value or "").strip()
        acc_num = (self.account_num_field.value or "").strip()
        try:
            init_bal = float((self.initial_balance_field.value or "10000").replace(",", "").strip())
        except Exception:
            init_bal = 10000.0
        currency = self.currency_dropdown.value or "USD"

        # Шифрование API ключей перед сохранением в SQLite
        enc_key = encrypt_secret(raw_key)
        enc_secret = encrypt_secret(raw_secret)

        self.db.add_account(
            name=name,
            exchange_type=exchange_type,
            api_key=enc_key,
            api_secret=enc_secret,
            account_number=acc_num or f"ACC-{exchange_type[:3]}-{len(self.db.get_accounts())+1}",
            initial_balance=init_bal,
            currency=currency,
        )

        # Очистка полей
        self.new_name_field.value = ""
        self.api_key_field.value = ""
        self.api_secret_field.value = ""
        self.account_num_field.value = ""
        self.initial_balance_field.value = "10000.0"

        self.status_banner.visible = True
        self.status_banner.bgcolor = ft.Colors.with_opacity(0.15, PROFIT)
        self.status_banner.border = ft.border.all(1, PROFIT)
        self.status_banner.content.value = f"Счет '{name}' успешно добавлен и зашифрован!"
        self.status_banner.content.color = PROFIT

        self._refresh_accounts_list()
        if self.on_account_updated:
            self.on_account_updated()
        if self.page:
            self.page.update()

