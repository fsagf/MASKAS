"""
run_local_server.py
Скрипт запуска высокопроизводительного локального сервера Trading Journal Pro.
Автоматически определяет IP-адреса сети, генерирует QR-код для моментального
подключения с телефонов и планшетов без ручного ввода и запускает веб-сервер на 0.0.0.0:8550.
"""

import os
import socket
import sys
from typing import List

import flet as ft
from main import main


def get_local_ip_addresses() -> List[str]:
    """Возвращает список всех активных локальных IPv4-адресов компьютера."""
    ips = []
    try:
        # Быстрый способ через UDP-сокет
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip and not primary_ip.startswith("127."):
            ips.append(primary_ip)
    except Exception:
        pass

    try:
        # Дополнительный поиск через getaddrinfo
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass

    return ips or ["127.0.0.1"]


def print_server_banner(port: int = 8550) -> str:
    """Выводит стильный баннер в консоль и возвращает основной мобильный URL."""
    ips = get_local_ip_addresses()
    primary_ip = ips[0]
    mobile_url = f"http://{primary_ip}:{port}"
    local_url = f"http://localhost:{port}"

    print("\n" + "=" * 65)
    print(" 🚀 TRADING JOURNAL PRO — СБОРКА ЛОКАЛЬНОГО СЕРВЕРА ЗАПУЩЕНА")
    print("=" * 65)
    print(f" 💻 Доступ на этом компьютере:  {local_url}")
    print(f" 📱 Доступ для других устройств: {mobile_url}")
    if len(ips) > 1:
        print(f"    Резервные IP в сети:       {', '.join([f'http://{i}:{port}' for i in ips[1:]])}")
    print("=" * 65)

    # Генерация QR-кода для мгновенного входа с камеры смартфона
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(mobile_url)
        print("\n 📷 НАВЕДИТЕ КАМЕРУ ТЕЛЕФОНА НА QR-КОД ДЛЯ ВХОДА:")
        qr.print_ascii(invert=True)
    except Exception:
        pass

    print("-" * 65)
    print(" 💡 Устройства должны быть подключены к одному Wi-Fi / точке доступа.")
    print(" 🛑 Для остановки сервера нажмите Ctrl + C в этом окне.")
    print("=" * 65 + "\n")

    return mobile_url


def run() -> None:
    port = 8550
    print_server_banner(port)

    # Запуск Flet Web с автоматическим легковесным рендерером для мобильных браузеров
    ft.app(
        target=main,
        view=ft.AppView.WEB_BROWSER,
        host="0.0.0.0",
        port=port,
        assets_dir="assets",
        web_renderer=ft.WebRenderer.AUTO,
    )


if __name__ == "__main__":
    run()
