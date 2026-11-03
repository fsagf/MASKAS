"""
Точка входа в приложение (main.py)
Инициализация Flet-приложения 'Дневник трейдера' (Trading Journal Pro).
Настройка темной темы (Dark Mode), параметров окна, глобальных горячих клавиш (Ctrl+K, Escape),
генерация интерактивного Plotly дашборда и поддержка веб-режима (--web на порту 8550).
"""

from pathlib import Path
import sys
import webbrowser

import flet as ft

from analytics import AnalyticsService
from database import DatabaseManager
from ui.layout import AppLayout
from ui.theme import ACCENT_PRIMARY, BG_APP, FONT_FAMILY, SURFACE_1


def main(page: ft.Page):
    """
    Главная функция конфигурации интерфейса и жизненного цикла Flet.
    """
    # 1. Настройка параметров окна и темы (актуальный синтаксис Flet 0.25.2+)
    page.title = "Trading Journal Pro — Дневник трейдера"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG_APP
    page.padding = 0

    # Подключение локальных TTF шрифтов (работает 100% офлайн без внешних запросов)
    page.fonts = {
        "Inter": "fonts/Inter.ttf",
        "JetBrainsMono": "fonts/JetBrainsMono-Regular.ttf",
        "JetBrainsMono-Bold": "fonts/JetBrainsMono-Bold.ttf",
        "RobotoMono": "fonts/RobotoMono.ttf",
    }
    page.theme = ft.Theme(
        font_family=FONT_FAMILY,
        color_scheme=ft.ColorScheme(
            background=BG_APP,
            surface=SURFACE_1,
            primary=ACCENT_PRIMARY,
        ),
    )

    # Конфигурация параметров окна для десктопа
    page.window.min_width = 1000
    page.window.min_height = 680
    page.window.width = 1260
    page.window.height = 840

    # 2. Инициализация базы данных и сидирование демо-данных
    db_manager = DatabaseManager()
    db_manager.seed_demo_data_if_empty()

    # 3. Путь и обработчик генерации интерактивного мульти-графика Plotly HTML
    assets_dir = Path(__file__).resolve().parent / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    plotly_html_path = assets_dir / "equity_chart.html"

    def open_plotly_chart():
        """Экспорт комплексного квантового дашборда в интерактивный Plotly HTML и открытие в браузере."""
        trades = db_manager.get_all_trades(order_by_date_desc=False)
        out_path = AnalyticsService.generate_interactive_plotly_dashboard(
            trades=trades,
            output_html_path=str(plotly_html_path),
        )

        # 1. Открытие в браузере клиента через Flet Web launch_url
        try:
            page.launch_url("/equity_chart.html", web_window_name="_blank")
        except Exception:
            pass

        # 2. Локальный фоллбэк для десктопного режима
        try:
            webbrowser.open(Path(out_path).resolve().as_uri())
        except Exception:
            pass

        # 3. Интерактивное всплывающее уведомление
        try:
            sb = ft.SnackBar(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.INSIGHTS_ROUNDED, color="#22D3EE", size=18),
                        ft.Text("Квантовый дашборд Plotly готов и открыт в новой вкладке", color="#FFFFFF", size=13),
                    ],
                    spacing=8,
                ),
                action="Открыть снова",
                action_color="#22D3EE",
                on_action=lambda _: page.launch_url("/equity_chart.html", web_window_name="_blank"),
                bgcolor=SURFACE_1,
                duration=5000,
            )
            page.overlay.append(sb)
            sb.open = True
            page.update()
        except Exception:
            pass

    # 4. Инициализация обновленного макета приложения
    layout = AppLayout(page=page, db_manager=db_manager, on_open_plotly=open_plotly_chart)
    page.add(layout)

    # 5. Глобальный обработчик горячих клавиш: Ctrl+K (Палитра команд), Escape (Закрытие)
    def on_keyboard_event(e: ft.KeyboardEvent):
        key_low = (e.key or "").lower()
        if key_low == "k" and (e.ctrl or e.meta):
            layout.command_bar.show(page)
        elif key_low == "escape":
            if page.dialog and page.dialog.open:
                page.dialog.open = False
                page.update()
            if hasattr(layout, "journal_view"):
                layout.journal_view.close_inspector()

    page.on_keyboard_event = on_keyboard_event
    page.update()


if __name__ == "__main__":
    # Проверка запуска с аргументом --web или --share (для браузера / шеринга)
    is_web = "--web" in sys.argv or "--share" in sys.argv
    port = 8550

    if is_web:
        print(f"[Trading Journal] Запуск в веб-режиме: http://0.0.0.0:{port} (http://localhost:{port})")
        ft.app(
            target=main,
            view=ft.AppView.WEB_BROWSER,
            host="0.0.0.0",
            port=port,
            assets_dir="assets",
        )
    else:
        ft.app(
            target=main,
            view=ft.AppView.FLET_APP,
            assets_dir="assets",
        )
