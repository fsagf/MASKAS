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
│   └── equity_chart.html       # Интерактивный график Plotly
│
├── database.py                 # Модель Trade (SQLAlchemy) и DatabaseManager (CRUD)
├── analytics.py                # Расчет Winrate, Profit Factor, Net PnL и генерация Equity Curve
│
├── ui/                         # Модульный пакет интерфейса
│   ├── __init__.py             # Экспорт основных сущностей UI
│   ├── theme.py                # Премиальная Dark Mode тема и дизайн-токены
│   ├── layout.py               # Корневой каркас с NavigationRail и переключением экранов
│   ├── views/
│   │   ├── dashboard.py        # Дашборд с метриками, тильт-фильтром и превью Монте-Карло
│   │   └── journal.py          # Журнал сделок на виртуализированном ListView + инспектор
│   └── components/
│       └── trade_modal.py      # Модальное окно ft.AlertDialog с чек-листом сетапа
│
├── main.py                     # Главная точка входа с поддержкой desktop и --web
├── requirements.txt            # Зафиксированные зависимости (flet==0.25.2)
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
pyinstaller --noconfirm --onedir --windowed --add-data "data;data" main.py -n "TradingJournal"
```

Или в строго один файл (`--onefile`):
```bash
pyinstaller --noconfirm --onefile --windowed main.py -n "TradingJournal"
```
Файл сборки будет расположен в директории `dist/TradingJournal.exe`.
