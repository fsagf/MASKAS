"""
run_share.py
Скрипт автоматического запуска десктопного приложения 'Дневник трейдера' (Flet)
в формате временного публичного онлайн-доступа (Web-туннель).

Поддерживаемые режимы:
- Режим А: Автоматический туннель через localtunnel (npx localtunnel --port 8550) или pyngrok
- Режим Б: Встроенный шеринг Flet (flet run main.py --web --port 8550 --share)
"""

import argparse
import os
import re
import socket
import subprocess
import sys
import time
from typing import Optional
import urllib.request

DEFAULT_PORT = 8550


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    """Проверяет, слушает ли какой-либо процесс указанный TCP-порт."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) == 0


def wait_for_server(port: int, timeout: int = 15) -> bool:
    """Ожидает готовности HTTP-сервера на localhost."""
    start_time = time.time()
    url = f"http://127.0.0.1:{port}/"
    while time.time() - start_time < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def get_public_ip() -> Optional[str]:
    """Получает внешний IPv4-адрес для прохождения проверки localtunnel."""
    try:
        req = urllib.request.Request("https://loca.lt/mytunnelpassword", headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        pass
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=2.0) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return None


def print_banner(public_url: str, local_port: int, mode_name: str, tunnel_pwd: Optional[str] = None) -> None:
    """Выводит стильный баннер с публичной ссылкой в терминал."""
    print("\n" + "=" * 62)
    print("🚀 ПРИЛОЖЕНИЕ УСПЕШНО ОПУБЛИКОВАНО ОНЛАЙН:")
    print(f"👉 URL: {public_url}")
    print("=" * 62)
    print(f"• Локальный адрес: http://localhost:{local_port}")
    print(f"• Режим туннеля:   {mode_name}")
    if "loca.lt" in public_url and tunnel_pwd:
        print(f"• Пароль доступа:  {tunnel_pwd} (введите при первом открытии)")
    print("• Остановка:       Нажмите Ctrl+C для завершения сессии")
    print("=" * 62 + "\n")


def run_flet_backend(port: int) -> subprocess.Popen:
    """Запускает Flet веб-сервер в фоновом субпроцессе."""
    print(f"[1/2] ⏳ Запуск Flet-сервера на порту {port} (0.0.0.0)...")
    cmd = [sys.executable, "-u", "main.py", "--web"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc


def run_localtunnel(port: int, subdomain: Optional[str] = None) -> None:
    """Создает публичный туннель через localtunnel (npx)."""
    print("[2/2] 🌐 Инициализация публичного Web-туннеля (localtunnel)...")
    cmd = ["npx", "-y", "localtunnel", "--port", str(port)]
    if subdomain:
        cmd.extend(["--subdomain", subdomain])

    lt_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=True,
    )

    url_regex = re.compile(r"https?://[a-zA-Z0-9\.\-]+")
    public_url = None
    tunnel_pwd = get_public_ip()

    # Считываем вывод localtunnel до получения URL
    for line in lt_proc.stdout:
        match = url_regex.search(line)
        if match:
            public_url = match.group(0)
            break
        if "error" in line.lower():
            print(f"Ошибка localtunnel: {line.strip()}")

    if not public_url:
        print("Не удалось перехватить URL localtunnel. Пробуем резервный метод...")
        return

    print_banner(public_url, port, "Localtunnel (Zero-Config)", tunnel_pwd)

    try:
        while True:
            time.sleep(1)
            if lt_proc.poll() is not None:
                print("Туннель завершил работу.")
                break
    except KeyboardInterrupt:
        print("\nОстановка туннеля...")
    finally:
        lt_proc.terminate()


def run_ngrok(port: int) -> None:
    """Создает публичный туннель через pyngrok."""
    try:
        from pyngrok import ngrok
    except ImportError:
        print("Библиотека pyngrok не установлена. Запустите: pip install pyngrok>=7.0.0")
        return

    authtoken = os.environ.get("NGROK_AUTHTOKEN")
    if authtoken:
        ngrok.set_auth_token(authtoken)

    print("[2/2] 🌐 Создание защищенного туннеля ngrok...")
    try:
        tunnel = ngrok.connect(port, "http")
        public_url = tunnel.public_url
        print_banner(public_url, port, "pyngrok Tunnel")

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nОстановка ngrok...")
    except Exception as e:
        print(f"Ошибка подключения ngrok: {e}")
        print("💡 Если у вас нет токена ngrok, переключитесь на режим localtunnel (без токена).")
        raise
    finally:
        try:
            ngrok.disconnect(public_url)
            ngrok.kill()
        except Exception:
            pass


def run_flet_share(port: int) -> None:
    """Запускает приложение с встроенным шерингом Flet CLI."""
    print(f"[Flet Share] Запуск через встроенный шеринг Flet CLI на порту {port}...")
    cmd = ["flet", "run", "main.py", "--web", "--port", str(port), "--share"]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=True,
        )
        url_regex = re.compile(r"https?://[a-zA-Z0-9\.\-]+\.flet\.dev[^\s]*")
        for line in proc.stdout:
            print(line, end="")
            match = url_regex.search(line)
            if match:
                print_banner(match.group(0), port, "Flet Built-in Share")
        proc.wait()
    except Exception as e:
        print(f"Ошибка запуска Flet Share: {e}. Переключение на Localtunnel...")
        run_localtunnel(port)


def main():
    parser = argparse.ArgumentParser(description="Автозапуск публичного доступа к Trading Journal Pro")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Порт веб-сервера (по умолчанию: 8550)")
    parser.add_argument(
        "--mode",
        choices=["auto", "localtunnel", "ngrok", "flet-share"],
        default="auto",
        help="Режим создания публичного туннеля",
    )
    parser.add_argument("--subdomain", type=str, default=None, help="Желаемый поддомен для localtunnel")
    args = parser.parse_args()

    port = args.port
    backend_proc = None

    # Режим Б: прямое делегирование в flet share
    if args.mode == "flet-share":
        run_flet_share(port)
        return

    # Проверяем, запущен ли уже сервер на порту 8550
    if not is_port_open(port):
        backend_proc = run_flet_backend(port)
        if not wait_for_server(port, timeout=12):
            print(f"❌ Ошибка: Сервер Flet не смог запуститься на порту {port}.")
            if backend_proc:
                backend_proc.terminate()
            return
        print(f"✓ Сервер Flet успешно запущен и отвечает на http://127.0.0.1:{port}")
    else:
        print(f"✓ Обнаружен уже работающий Flet-сервер на порту {port}.")

    # Создание туннеля
    try:
        if args.mode == "ngrok" or (args.mode == "auto" and os.environ.get("NGROK_AUTHTOKEN")):
            try:
                run_ngrok(port)
            except Exception:
                print("Переключение на надежный localtunnel без авторизации...")
                run_localtunnel(port, subdomain=args.subdomain)
        else:
            run_localtunnel(port, subdomain=args.subdomain)
    finally:
        if backend_proc:
            print("Остановка фонового сервера Flet...")
            backend_proc.terminate()
            try:
                backend_proc.wait(timeout=3)
            except Exception:
                backend_proc.kill()


if __name__ == "__main__":
    main()

