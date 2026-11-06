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


def get_network_info():
    """
    Определяет реальный физический Wi-Fi/LAN IP и отделяет виртуальные VPN-адаптеры
    (ProtonVPN, PlanetVPN, WireGuard), чтобы QR-код строился для правильной сети.
    """
    lan_ips = []
    vpn_ips = []
    vpn_name = None

    try:
        import subprocess, re
        out = subprocess.check_output("ipconfig", text=True, errors="replace")
        curr = "Unknown"
        for line in out.splitlines():
            if line and not line.startswith(" ") and ":" in line:
                curr = line.split(":")[0].strip()
            m = re.search(r"IPv4[^\:]*:\s*([0-9\.]+)", line)
            if m:
                ip = m.group(1).strip()
                if ip.startswith("127.") or ip.startswith("169.254."):
                    continue
                if any(v in curr.lower() for v in ["vpn", "tunnel", "tap", "wintun", "tailscale", "wireguard"]):
                    vpn_ips.append(ip)
                    vpn_name = curr
                else:
                    lan_ips.append(ip)
    except Exception:
        pass

    if not lan_ips:
        try:
            for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
                if ip not in vpn_ips and not ip.startswith("127."):
                    lan_ips.append(ip)
        except Exception:
            pass

    primary_ip = lan_ips[0] if lan_ips else (vpn_ips[0] if vpn_ips else "127.0.0.1")
    return primary_ip, lan_ips, vpn_ips, vpn_name


def print_server_banner(port: int = 8550) -> str:
    """Выводит стильный баннер в консоль и возвращает основной мобильный URL."""
    primary_ip, lan_ips, vpn_ips, vpn_name = get_network_info()
    mobile_url = f"http://{primary_ip}:{port}"
    local_url = f"http://localhost:{port}"

    print("\n" + "=" * 65)
    print(" 🚀 TRADING JOURNAL PRO — СБОРКА ЛОКАЛЬНОГО СЕРВЕРА ЗАПУЩЕНА")
    print("=" * 65)
    print(f" 💻 Доступ на этом компьютере:  {local_url}")
    print(f" 📱 Доступ для других устройств: {mobile_url}")
    if len(lan_ips) > 1:
        print(f"    Резервные IP в сети:       {', '.join([f'http://{i}:{port}' for i in lan_ips[1:]])}")
    print("=" * 65)

    if vpn_name:
        print(f" ⚠️  ВНИМАНИЕ: На компьютере включен {vpn_name}!")
        print("    Если телефон не открывает сайт: в настройках VPN включите")
        print("    'Allow LAN access' (Разрешить локальную сеть) или временно отключите VPN.")
        print("-" * 65)

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

