# Trading Journal (Дневник трейдера)

Премиальное десктопное приложение для учета торговых сделок, анализа эффективности стратегий и отслеживания динамики депозита.

## Технологический стек
- **Язык**: Python 3.11+
- **Интерфейс**: Flet 0.25.2 (десктопный UI на базе Flutter)
- **База данных**: SQLAlchemy 2.0 + SQLite
- **Аналитика и графики**: Pandas + Plotly
- **Сборка в .exe**: PyInstaller
- **Оформление**: Dark Mode (Deep Zinc), адаптивная верстка со скругленными карточками

---

## Структура проекта
```
trading_journal/
│
├── data/                       # Папка базы данных и экспорта графиков
│   ├── trades.db               # SQLite база данных (создается автоматически)
│   └── .secret.key             # Ключ шифрования API-ключей Fernet (256-bit AES)
│
├── database.py                 # Модели Trade, TradingAccount, TradeExecution и DatabaseManager (CRUD, bulk_add)
├── analytics.py                # Квантовая аналитика, Monte Carlo, спарклайны, Wave AI Coach и экспорт Plotly
├── run_share.py                # Публичный Web-туннель (localtunnel, ngrok, Flet Share)
│
├── services/                   # Внешние институциональные сервисы
│   ├── sync_service.py         # Прямая автосинхронизация с биржами (Binance, Bybit через CCXT) и MT5
│   └── chart_service.py        # Загрузка тиковых и свечных данных (TradingView / Binance / Yahoo)
│
├── ui/                         # Модульный пакет интерфейса на Flet 0.25.2
│   ├── __init__.py             # Экспорт основных сущностей UI
│   ├── theme.py                # Премиальная Dark Mode тема (#090A0F), патч тултипов и токены
│   ├── layout.py               # Корневой каркас с NavigationRail и переключением экранов
│   ├── views/
│   │   ├── dashboard.py        # Дашборд с метриками, календарем P&L, тильт-фильтром и Монте-Карло
│   │   ├── journal.py          # Журнал сделок на виртуализированном ListView + инспектор
│   │   └── backtest.py         # Симулятор рынка и ручной бэктестинг на японских свечах (Canvas)
│   └── components/
│       ├── trade_modal.py      # Модальное окно ft.AlertDialog с чек-листом сетапа
│       ├── account_modal.py    # Модальное окно управления счетами и безопасного ввода API-ключей
│       ├── command_bar.py      # Быстрая командная строка Spotlight / палитра команд (Ctrl+K)
│       └── pnl_calendar.py     # Интерактивный интерактивный календарь прибылей и убытков
│
├── main.py                     # Главная точка входа с поддержкой desktop и --web
├── requirements.txt            # Зафиксированные зависимости (flet==0.25.2, numpy>=1.26.0)
└── README.md                   # Документация проекта
```

---

## Установка и запуск

### 1. Клонирование / переход в директорию
```bash
cd trading_journal
```

### 2. Создание виртуального окружения
```bash
python -m venv venv

# Активация на Windows:
venv\Scripts\activate

# Активация на Linux/macOS:
source venv/bin/activate
```

### 3. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 4. Запуск приложения

**Десктопный режим (нативное окно):**
```bash
python main.py
```

**Веб-режим в браузере (порт 8550):**
```bash
python main.py --web
```

---

## Сборка в один исполняемый файл (.exe)

Сборка осуществляется с помощью PyInstaller без отображения системной консоли:

```bash
pyinstaller --noconfirm --onedir --windowed --add-data "data;data" --add-data "assets;assets" main.py -n "TradingJournal"
```

Или в строго один файл (`--onefile`):
```bash
pyinstaller --noconfirm --onefile --windowed --add-data "data;data" --add-data "assets;assets" main.py -n "TradingJournal"
```
Файл сборки будет расположен в директории `dist/TradingJournal.exe`.
