"""
Модуль котировок и генерации интерактивного графика TradingView Lightweight Charts (services/chart_service.py)
Загрузка исторических свечей (Binance API / yfinance / Fallback сплайн-генератор),
нанесение маркеров исполнения сделки (Execution Markers) и ценовых уровней Stop-Loss / Take-Profit.
"""

from datetime import datetime, timedelta
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

import httpx

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

from database import Trade


def get_binance_symbol(ticker: str) -> Optional[str]:
    """Нормализует тикер для публичного REST API Binance."""
    clean = ticker.replace("/", "").replace("-", "").replace("_", "").strip().upper()
    if clean.endswith("USDT") or clean.endswith("BUSD") or clean.endswith("BTC"):
        return clean

    common_crypto = {
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
        "SOL": "SOLUSDT",
        "BNB": "BNBUSDT",
        "XRP": "XRPUSDT",
        "DOGE": "DOGEUSDT",
        "ADA": "ADAUSDT",
        "AVAX": "AVAXUSDT",
        "DOT": "DOTUSDT",
        "LINK": "LINKUSDT",
        "NEAR": "NEARUSDT",
        "MATIC": "MATICUSDT",
        "POL": "POLUSDT",
        "SUI": "SUIUSDT",
        "APT": "APTUSDT",
        "TON": "TONUSDT",
    }
    return common_crypto.get(clean)


def get_tradingview_url(ticker: str) -> str:
    """Генерирует прямую ссылку на инструмент в TradingView."""
    clean = ticker.strip().upper()
    binance_sym = get_binance_symbol(clean)
    if binance_sym:
        return f"https://ru.tradingview.com/chart/?symbol=BINANCE%3A{binance_sym}"

    clean_stock = clean.replace("/", "").replace("-", "")
    return f"https://ru.tradingview.com/chart/?symbol={urllib.parse.quote(clean_stock)}"


def fetch_binance_candles(
    symbol: str,
    start_time: datetime,
    end_time: datetime,
    interval: str = "15m",
) -> Optional[List[Dict[str, Any]]]:
    """Запрашивает исторические свечи через публичный REST API Binance с таймаутом 3 сек."""
    start_ts = int(start_time.timestamp() * 1000)
    end_ts = int(end_time.timestamp() * 1000)

    if end_ts <= start_ts:
        end_ts = start_ts + (24 * 3600 * 1000)

    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&startTime={start_ts}&endTime={end_ts}&limit=1000"

    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if not data or not isinstance(data, list):
                    return None
                candles = []
                for row in data:
                    candles.append({
                        "time": int(row[0] // 1000),  # Unix timestamp в секундах для Lightweight Charts
                        "open": round(float(row[1]), 4),
                        "high": round(float(row[2]), 4),
                        "low": round(float(row[3]), 4),
                        "close": round(float(row[4]), 4),
                        "volume": round(float(row[5]), 2),
                    })
                return candles if len(candles) >= 5 else None
    except Exception:
        return None
    return None


def fetch_yfinance_candles(
    ticker: str,
    start_time: datetime,
    end_time: datetime,
    interval: str = "15m",
) -> Optional[List[Dict[str, Any]]]:
    """Запрашивает исторические котировки через yfinance (акции, ETF, валюты)."""
    if not YFINANCE_AVAILABLE:
        return None

    clean_ticker = ticker.replace("/", "").strip().upper()
    try:
        df = yf.download(
            clean_ticker,
            start=start_time.strftime("%Y-%m-%d"),
            end=(end_time + timedelta(days=1)).strftime("%Y-%m-%d"),
            interval=interval,
            progress=False,
            timeout=3.0,
        )
        if df is None or len(df) < 5:
            return None

        candles = []
        for idx_ts, row in df.iterrows():
            if hasattr(idx_ts, "timestamp"):
                ts_sec = int(idx_ts.timestamp())
            else:
                ts_sec = int(datetime.fromisoformat(str(idx_ts)).timestamp())

            # Обработка MultiIndex колонок yfinance
            def get_val(col_name: str) -> float:
                val = row.get(col_name)
                if val is None:
                    # Поиск в кортежах MultiIndex
                    for k in row.keys():
                        if isinstance(k, tuple) and k[0].lower() == col_name.lower():
                            return float(row[k])
                    return 0.0
                return float(val)

            o = round(get_val("Open"), 4)
            h = round(get_val("High"), 4)
            l = round(get_val("Low"), 4)
            c = round(get_val("Close"), 4)
            v = round(get_val("Volume"), 2)

            if o > 0 and h > 0 and l > 0 and c > 0:
                candles.append({
                    "time": ts_sec,
                    "open": o,
                    "high": max(h, o, c),
                    "low": min(l, o, c),
                    "close": c,
                    "volume": v,
                })

        return candles if len(candles) >= 5 else None
    except Exception:
        return None


def generate_synthetic_candles(
    trade: Trade,
    start_time: datetime,
    end_time: datetime,
    interval_minutes: int = 15,
) -> List[Dict[str, Any]]:
    """
    Высокоточный синтетический генератор свечей (Fallback).
    Формирует непрерывную последовательность OHLCV свечей,
    проходящую через точки входа, MAE, MFE и выхода из позиции.
    """
    total_seconds = max((end_time - start_time).total_seconds(), 3600.0 * 6)
    step_seconds = interval_minutes * 60
    num_candles = max(int(total_seconds // step_seconds), 30)

    t_entry = trade.opened_at or (datetime.now() - timedelta(hours=2))
    t_exit = trade.closed_at or datetime.now()

    entry_price = float(trade.entry_price or 100.0)
    exit_price = float(trade.exit_price or entry_price * 1.02)
    mae_price = float(trade.mae_price or (entry_price * 0.98 if trade.direction == "LONG" else entry_price * 1.02))
    mfe_price = float(trade.mfe_price or (exit_price * 1.015 if trade.direction == "LONG" else exit_price * 0.985))

    is_long = (trade.direction or "LONG").upper() == "LONG"
    candles = []

    current_price = entry_price * (0.995 if is_long else 1.005)
    noise_amplitude = max(entry_price * 0.0025, 0.05)

    for i in range(num_candles):
        c_time = start_time + timedelta(seconds=i * step_seconds)
        ts_sec = int(c_time.timestamp())

        # Определение фазы жизненного цикла сделки
        if c_time < t_entry:
            # 1. Фаза до входа: консолидация перед сетапом
            progress = (c_time - start_time).total_seconds() / max((t_entry - start_time).total_seconds(), 60.0)
            target = entry_price * 0.992 + (entry_price * 0.008 * progress) if is_long else entry_price * 1.008 - (entry_price * 0.008 * progress)
        elif t_entry <= c_time <= t_exit:
            # 2. Внутри сделки: движение через MAE и MFE к Exit
            in_trade_progress = (c_time - t_entry).total_seconds() / max((t_exit - t_entry).total_seconds(), 60.0)
            if in_trade_progress <= 0.35:
                # Движение к MAE
                sub_p = in_trade_progress / 0.35
                target = entry_price + (mae_price - entry_price) * math.sin(sub_p * math.pi / 2)
            elif in_trade_progress <= 0.75:
                # Импульс от MAE к MFE
                sub_p = (in_trade_progress - 0.35) / 0.40
                target = mae_price + (mfe_price - mae_price) * (0.5 - 0.5 * math.cos(sub_p * math.pi))
            else:
                # Фиксация к цене выхода (Exit)
                sub_p = (in_trade_progress - 0.75) / 0.25
                target = mfe_price + (exit_price - mfe_price) * sub_p
        else:
            # 3. После выхода: продолжение движения / затухание
            post_progress = min((c_time - t_exit).total_seconds() / max((end_time - t_exit).total_seconds(), 60.0), 1.0)
            target = exit_price + ((exit_price - entry_price) * 0.2 * post_progress)

        # Псевдослучайный шум для реалистичности свечей
        pseudo_rand = math.sin(i * 1.35) * math.cos(i * 0.85)
        close_p = target + (pseudo_rand * noise_amplitude)
        open_p = current_price

        wick_noise = abs(pseudo_rand) * noise_amplitude * 1.5 + (entry_price * 0.001)
        high_p = max(open_p, close_p) + wick_noise
        low_p = min(open_p, close_p) - wick_noise

        candles.append({
            "time": ts_sec,
            "open": round(open_p, 4),
            "high": round(high_p, 4),
            "low": round(low_p, 4),
            "close": round(close_p, 4),
            "volume": round(max(abs(pseudo_rand * 150.0) + 20.0, 5.0), 2),
        })

        current_price = close_p

    return candles


def generate_trade_chart(trade: Trade, output_html_path: Optional[str] = None) -> str:
    """
    Генерирует автономный интерактивный HTML-чарт TradingView Lightweight Charts v4.
    Загружает котировки, наносит маркеры входа/выхода и ценовые уровни SL/TP.
    Возвращает путь к сохраненному HTML-файлу.
    """
    t_open = trade.opened_at or (datetime.now() - timedelta(hours=2))
    t_close = trade.closed_at or datetime.now()

    # Интервал: открыта - 12 часов до закрыта + 12 часов
    start_interval = t_open - timedelta(hours=12)
    end_interval = t_close + timedelta(hours=12)

    # 1. Загрузка котировок (Binance API -> yfinance -> Fallback)
    candles = None
    binance_symbol = get_binance_symbol(trade.ticker)

    if binance_symbol:
        candles = fetch_binance_candles(binance_symbol, start_interval, end_interval, interval="15m")

    if not candles and YFINANCE_AVAILABLE:
        candles = fetch_yfinance_candles(trade.ticker, start_interval, end_interval, interval="15m")

    if not candles:
        candles = generate_synthetic_candles(trade, start_interval, end_interval, interval_minutes=15)

    # Сортировка и удаление возможных дубликатов по времени (строгое требование Lightweight Charts)
    candles_dict = {}
    for c in candles:
        candles_dict[c["time"]] = c
    sorted_times = sorted(candles_dict.keys())
    clean_candles = [candles_dict[t] for t in sorted_times]

    # Поиск ближайшей свечи к точке входа и выхода для точного позиционирования маркеров
    entry_ts = int(t_open.timestamp())
    exit_ts = int(t_close.timestamp())

    closest_entry_time = min(sorted_times, key=lambda t: abs(t - entry_ts))
    closest_exit_time = min(sorted_times, key=lambda t: abs(t - exit_ts))

    is_long = (trade.direction or "LONG").upper() == "LONG"
    is_win = (trade.net_pnl or 0.0) >= 0

    pnl_prefix = "+" if is_win else ""
    pnl_str = f"{pnl_prefix}${trade.net_pnl:,.2f}"

    # 2. Настройка маркеров исполнения (Execution Markers)
    entry_marker = {
        "time": closest_entry_time,
        "position": "belowBar" if is_long else "aboveBar",
        "color": "#10B981",
        "shape": "arrowUp" if is_long else "arrowDown",
        "text": f"ВХОД ({trade.direction}) @ ${trade.entry_price:,.2f}",
    }

    exit_marker = {
        "time": closest_exit_time,
        "position": "aboveBar" if is_long else "belowBar",
        "color": "#10B981" if is_win else "#EF4444",
        "shape": "arrowDown" if is_long else "arrowUp",
        "text": f"ВЫХОД @ ${trade.exit_price:,.2f} ({pnl_str})",
    }

    markers = [entry_marker, exit_marker]

    # 3. Настройка ценовых линий (Price Lines)
    price_lines = []
    if trade.stop_loss and trade.stop_loss > 0:
        price_lines.append({
            "price": float(trade.stop_loss),
            "color": "#EF4444",
            "lineWidth": 2,
            "lineStyle": 2,  # Dashed
            "axisLabelVisible": True,
            "title": f"STOP-LOSS: ${trade.stop_loss:,.2f}",
        })

    if trade.take_profit and trade.take_profit > 0:
        price_lines.append({
            "price": float(trade.take_profit),
            "color": "#10B981",
            "lineWidth": 2,
            "lineStyle": 2,  # Dashed
            "axisLabelVisible": True,
            "title": f"TAKE-PROFIT: ${trade.take_profit:,.2f}",
        })

    price_lines.append({
        "price": float(trade.entry_price),
        "color": "#38BDF8",
        "lineWidth": 1,
        "lineStyle": 1,  # Dotted
        "axisLabelVisible": True,
        "title": f"ENTRY VWAP: ${trade.entry_price:,.2f}",
    })

    # Путь сохранения файла
    if output_html_path:
        out_file = Path(output_html_path)
    else:
        out_file = Path(__file__).resolve().parent.parent / "assets" / "cache_trade_chart.html"

    out_file.parent.mkdir(parents=True, exist_ok=True)

    tv_url = get_tradingview_url(trade.ticker)
    r_mult_str = f"{trade.r_multiple:+.2f} R" if trade.r_multiple != 0.0 else "N/A"

    # HTML-шаблон с автономной библиотекой TradingView Lightweight Charts v4
    html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{trade.ticker} • Анализ исполнения сделки</title>
    <script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            user-select: none;
        }}
        body {{
            background-color: #0F1117;
            color: #F8FAFC;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            height: 100vh;
            width: 100vw;
        }}
        #header_bar {{
            background: #181B24;
            border-bottom: 1px solid #2D3243;
            padding: 10px 18px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            height: 52px;
            flex-shrink: 0;
        }}
        .trade-info {{
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 13px;
        }}
        .ticker-pill {{
            font-size: 14px;
            font-weight: 700;
            color: #F8FAFC;
            letter-spacing: 0.5px;
        }}
        .badge {{
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 700;
            font-family: 'Roboto Mono', monospace;
            text-transform: uppercase;
        }}
        .badge-long {{
            background: rgba(16, 185, 129, 0.15);
            color: #10B981;
            border: 1px solid rgba(16, 185, 129, 0.4);
        }}
        .badge-short {{
            background: rgba(239, 68, 68, 0.15);
            color: #EF4444;
            border: 1px solid rgba(239, 68, 68, 0.4);
        }}
        .metric {{
            color: #94A3B8;
            font-family: 'Roboto Mono', monospace;
        }}
        .metric-val {{
            font-weight: 600;
            color: #F8FAFC;
        }}
        .metric-pnl-win {{
            color: #10B981;
            font-weight: 700;
        }}
        .metric-pnl-loss {{
            color: #EF4444;
            font-weight: 700;
        }}
        .actions {{
            display: flex;
            gap: 8px;
            align-items: center;
        }}
        .btn {{
            background: #2D3243;
            color: #38BDF8;
            border: 1px solid #3B82F6;
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s ease;
        }}
        .btn:hover {{
            background: #3B82F6;
            color: #FFFFFF;
        }}
        #chart_container {{
            flex: 1;
            width: 100%;
            height: calc(100vh - 52px);
            position: relative;
        }}
        #legend_bar {{
            position: absolute;
            top: 12px;
            left: 18px;
            z-index: 10;
            background: rgba(24, 27, 36, 0.85);
            backdrop-filter: blur(8px);
            padding: 6px 14px;
            border-radius: 8px;
            border: 1px solid rgba(45, 50, 67, 0.7);
            font-size: 11px;
            color: #94A3B8;
            font-family: 'Roboto Mono', monospace;
            display: flex;
            gap: 14px;
            pointer-events: none;
        }}
        .legend-item span {{
            font-weight: 600;
            color: #F8FAFC;
        }}
    </style>
</head>
<body>
    <div id="header_bar">
        <div class="trade-info">
            <span class="ticker-pill">{trade.ticker}</span>
            <span class="badge {'badge-long' if is_long else 'badge-short'}">{trade.direction}</span>
            <span class="metric">Сетап: <span class="metric-val">{trade.strategy_tag}</span></span>
            <span class="metric">VWAP: <span class="metric-val">${trade.entry_price:,.2f}</span></span>
            <span class="metric">Выход: <span class="metric-val">${trade.exit_price:,.2f}</span></span>
            <span class="metric">Net PnL: <span class="{'metric-pnl-win' if is_win else 'metric-pnl-loss'}">{pnl_str}</span></span>
            <span class="metric">R:R: <span class="metric-val">{r_mult_str}</span></span>
        </div>
        <div class="actions">
            <button class="btn" onclick="fitView()">⛶ Масштаб</button>
            <a class="btn" href="{tv_url}" target="_blank" rel="noopener noreferrer">↗ TradingView</a>
        </div>
    </div>

    <div id="chart_container">
        <div id="legend_bar">
            <div class="legend-item">O: <span id="leg_o">-</span></div>
            <div class="legend-item">H: <span id="leg_h">-</span></div>
            <div class="legend-item">L: <span id="leg_l">-</span></div>
            <div class="legend-item">C: <span id="leg_c">-</span></div>
            <div class="legend-item">Vol: <span id="leg_v">-</span></div>
        </div>
    </div>

    <script>
        const candlesData = {json.dumps(clean_candles)};
        const markersData = {json.dumps(markers)};
        const priceLinesData = {json.dumps(price_lines)};

        const container = document.getElementById('chart_container');

        // Создание инстанса TradingView Lightweight Charts v4
        const chart = LightweightCharts.createChart(container, {{
            width: container.clientWidth,
            height: container.clientHeight,
            layout: {{
                background: {{ type: 'solid', color: '#0F1117' }},
                textColor: '#94A3B8',
                fontSize: 11,
                fontFamily: "'Roboto Mono', 'SF Pro Display', -apple-system, monospace",
            }},
            grid: {{
                vertLines: {{ color: '#1E2330' }},
                horzLines: {{ color: '#1E2330' }},
            }},
            crosshair: {{
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: {{
                    color: '#64748B',
                    width: 1,
                    style: LightweightCharts.LineStyle.Dashed,
                    labelBackgroundColor: '#1E293B',
                }},
                horzLine: {{
                    color: '#64748B',
                    width: 1,
                    style: LightweightCharts.LineStyle.Dashed,
                    labelBackgroundColor: '#1E293B',
                }},
            }},
            rightPriceScale: {{
                borderColor: '#2D3243',
                scaleMargins: {{
                    top: 0.12,
                    bottom: 0.15,
                }},
            }},
            timeScale: {{
                borderColor: '#2D3243',
                timeVisible: true,
                secondsVisible: false,
            }},
        }});

        // Серия японских свечей
        const candleSeries = chart.addCandlestickSeries({{
            upColor: '#10B981',
            downColor: '#EF4444',
            borderVisible: false,
            wickUpColor: '#10B981',
            wickDownColor: '#EF4444',
        }});

        candleSeries.setData(candlesData);

        // Нанесение маркеров исполнения
        candleSeries.setMarkers(markersData);

        // Нанесение ценовых линий (Stop-Loss, Take-Profit, Entry VWAP)
        priceLinesData.forEach(line => {{
            candleSeries.createPriceLine({{
                price: line.price,
                color: line.color,
                lineWidth: line.lineWidth,
                lineStyle: line.lineStyle,
                axisLabelVisible: line.axisLabelVisible,
                title: line.title,
            }});
        }});

        // Автоподгонка отображения всех свечей и маркеров
        chart.timeScale().fitContent();

        function fitView() {{
            chart.timeScale().fitContent();
        }}

        // Обновление легенды при наведении перекрестия
        chart.subscribeCrosshairMove(param => {{
            if (!param || !param.time || !param.seriesData.get(candleSeries)) {{
                const last = candlesData[candlesData.length - 1];
                if (last) {{
                    document.getElementById('leg_o').innerText = last.open;
                    document.getElementById('leg_h').innerText = last.high;
                    document.getElementById('leg_l').innerText = last.low;
                    document.getElementById('leg_c').innerText = last.close;
                    document.getElementById('leg_v').innerText = last.volume || '-';
                }}
                return;
            }}
            const data = param.seriesData.get(candleSeries);
            document.getElementById('leg_o').innerText = data.open;
            document.getElementById('leg_h').innerText = data.high;
            document.getElementById('leg_l').innerText = data.low;
            document.getElementById('leg_c').innerText = data.close;
            document.getElementById('leg_v').innerText = data.volume || '-';
        }});

        // Отзывчивый ресайз
        window.addEventListener('resize', () => {{
            chart.resize(container.clientWidth, container.clientHeight);
        }});
    </script>
</body>
</html>
"""

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    return str(out_file)

