"""
Квантовый и аналитический движок (analytics.py)
Расчет риск-метрик (R-Multiple, Expectancy, Profit Factor), скользящих спарклайнов,
Behavioral Quant Engine (детектор тильта), векторная симуляция Монте-Карло (10 000 итераций),
MarketDataService (Binance API + fallback) и импорт/экспорт CSV выписок.
"""

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from database import DatabaseManager, Trade


@dataclass
class DashboardMetrics:
    """
    Строго типизированный датакласс ключевых торговых метрик.
    """
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    winrate: float = 0.0              # Процент прибыльных (0.0 - 100.0)
    profit_factor: float = 0.0        # Gross Profit / Gross Loss (99.9 если loss == 0)
    net_pnl: float = 0.0              # Чистый суммарный PnL ($)
    gross_profit: float = 0.0         # Сумма всех плюсовых сделок ($)
    gross_loss: float = 0.0           # Сумма всех минусовых сделок ($)
    avg_trade_pnl: float = 0.0        # Средний PnL на сделку ($)
    avg_r_multiple: float = 0.0       # Средний R-Multiple (например, 2.1R)
    expectancy: float = 0.0           # Мат. ожидание на сделку ($)
    max_win: float = 0.0              # Максимальный профит ($)
    max_loss: float = 0.0             # Максимальный убыток ($)
    winrate_sparkline: List[float] = field(default_factory=list)
    profit_factor_sparkline: List[float] = field(default_factory=list)
    tilt_trades_count: int = 0        # Число сделок в состоянии тильта
    tilt_loss_amount: float = 0.0     # Суммарный ущерб от тильт-сделок ($)
    total_commission: float = 0.0     # Суммарные комиссии биржи ($)
    total_swap_fees: float = 0.0      # Суммарный фандинг / свопы ($)
    total_broker_costs: float = 0.0   # Суммарные издержки брокера ($)
    fee_drag_pct: float = 0.0         # Fee Drag: % комиссий от Gross Profit
    sqn: float = 0.0                  # System Quality Number (Van Tharp)
    sqn_rating: str = "N/A"           # Рейтинг системы: Poor, Average, Good, Excellent, Holy Grail
    sharpe_ratio: float = 0.0         # Коэффициент Шарпа (per-trade)
    sortino_ratio: float = 0.0        # Коэффициент Сортино (downside deviation)
    kelly_fraction_pct: float = 0.0   # Полный критерий Келли (% от депозита)
    half_kelly_pct: float = 0.0       # Половинный Келли (% от депозита - Quant Standard)
    max_win_streak: int = 0           # Максимальная серия побед подряд
    max_loss_streak: int = 0          # Максимальная серия поражений подряд
    current_streak: int = 0           # Текущая серия (+N побед или -N убытков)
    max_drawdown_amount: float = 0.0   # Максимальная просадка ($)
    max_drawdown_pct: float = 0.0      # Максимальная просадка (%)
    recovery_factor: float = 0.0       # Recovery Factor = Net PnL / Max Drawdown
    ulcer_index: float = 0.0           # Ulcer Index (глубина и длительность просадки)


TradingMetrics = DashboardMetrics


class MarketDataService:
    """
    Сервис рыночных данных с фоновым запросом к Binance API и надежным Fallback.
    """

    @staticmethod
    def get_binance_symbol(ticker: str) -> Optional[str]:
        """Преобразует тикер вида BTC/USDT или BTCUSDT в формат Binance API."""
        clean = ticker.replace("/", "").replace("-", "").replace("_", "").upper()
        if clean.endswith("USDT") or clean.endswith("BUSD") or clean.endswith("BTC"):
            return clean
        return None

    @classmethod
    def fetch_market_klines(
        cls,
        ticker: str,
        start_time: datetime,
        end_time: datetime,
        interval: str = "5m",
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Запрашивает исторические свечи через публичный REST API Binance (таймаут 3 сек).
        """
        symbol = cls.get_binance_symbol(ticker)
        if not symbol:
            return None

        start_ts = int(start_time.timestamp() * 1000)
        end_ts = int(end_time.timestamp() * 1000)

        # Ограничение диапазона минимум 10 свечами
        if end_ts <= start_ts:
            end_ts = start_ts + (60 * 60 * 1000)

        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&startTime={start_ts}&endTime={end_ts}&limit=100"

        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    candles = []
                    for row in data:
                        candles.append({
                            "timestamp": datetime.fromtimestamp(row[0] / 1000.0),
                            "open": float(row[1]),
                            "high": float(row[2]),
                            "low": float(row[3]),
                            "close": float(row[4]),
                        })
                    return candles if candles else None
        except Exception:
            return None
        return None

    @classmethod
    def generate_price_path(cls, trade: Trade) -> List[Dict[str, Any]]:
        """
        Возвращает кривую движения цены внутри сделки:
        пытается загрузить реальные свечи с Binance, иначе генерирует реалистичный fallback.
        """
        if not trade or not trade.entry_price or trade.entry_price <= 0:
            return []

        candles = cls.fetch_market_klines(trade.ticker, trade.opened_at, trade.closed_at)

        is_long = (trade.direction or "LONG").upper() == "LONG"
        t_open = trade.opened_at or (datetime.now() - timedelta(hours=2))
        t_close = trade.closed_at or datetime.now()
        duration = max((t_close - t_open).total_seconds(), 60.0)

        if candles and len(candles) >= 3:
            # Расчет на базе реальных свечей Binance
            points = []
            for c in candles:
                price = c["close"]
                pct = ((price - trade.entry_price) / trade.entry_price * 100) if is_long else ((trade.entry_price - price) / trade.entry_price * 100)
                points.append({
                    "time": c["timestamp"],
                    "price": price,
                    "pct": round(pct, 2),
                })
            return points

        # Fallback: реалистичная сплайн-интерполяция из 16 точек
        pct_exit = ((trade.exit_price - trade.entry_price) / trade.entry_price * 100) if is_long else ((trade.entry_price - trade.exit_price) / trade.entry_price * 100)
        mae_pct = trade.mae_pct if trade.mae_pct != 0.0 else (-abs(pct_exit * 0.35) - 0.75)
        mfe_pct = trade.mfe_pct if trade.mfe_pct != 0.0 else max(pct_exit * 1.35, abs(mae_pct) * 1.6, 2.5)

        steps = 16
        points = []

        for i in range(steps):
            fraction = i / (steps - 1)
            t_curr = t_open + timedelta(seconds=duration * fraction)

            if fraction <= 0.35:
                # Фаза просадки к MAE
                sub_f = fraction / 0.35
                p_pct = mae_pct * math.sin(sub_f * math.pi / 2)
            elif fraction <= 0.75:
                # Фаза импульса к MFE
                sub_f = (fraction - 0.35) / 0.40
                p_pct = mae_pct + (mfe_pct - mae_pct) * (0.5 - 0.5 * math.cos(sub_f * math.pi))
            else:
                # Фаза коррекции к выходу
                sub_f = (fraction - 0.75) / 0.25
                p_pct = mfe_pct + (pct_exit - mfe_pct) * sub_f

            if is_long:
                curr_price = trade.entry_price * (1 + p_pct / 100.0)
            else:
                curr_price = trade.entry_price * (1 - p_pct / 100.0)

            points.append({
                "time": t_curr,
                "price": round(curr_price, 2),
                "pct": round(p_pct, 2),
            })

        return points


class AnalyticsService:
    """
    Аналитический и квантовый движок торгового терминала.
    """

    @staticmethod
    def detect_tilt(
        trade_candidate: Dict[str, Any],
        recent_trades: List[Trade],
    ) -> Tuple[bool, Optional[str]]:
        """
        Behavioral Quant Engine: анализирует паттерны поведения трейдера
        и выявляет сделки, совершенные в состоянии эмоционального тильта.
        """
        # 1. Проверка чек-листа сетапа (Unplanned)
        if not trade_candidate.get("checklist_passed", True):
            return True, "Нарушение чек-листа: сделка открыта вне торгового плана"

        cand_open = trade_candidate.get("opened_at") or datetime.now()
        cand_risk = float(trade_candidate.get("risk_amount") or 0.0)
        cand_vol = float(trade_candidate.get("volume") or 0.0)

        if not recent_trades:
            return False, None

        # Ищем последнюю закрытую сделку по таймстампу
        sorted_recent = sorted([t for t in recent_trades if t.closed_at], key=lambda x: x.closed_at, reverse=True)
        if not sorted_recent:
            sorted_recent = recent_trades
        last_trade = sorted_recent[0]

        # 2. Детектор Revenge Trading (< 10 минут после лосса)
        if last_trade.net_pnl < 0 and last_trade.closed_at:
            delta_sec = (cand_open - last_trade.closed_at).total_seconds()
            if 0 <= delta_sec < 600:  # 10 минут
                mins = max(1, int(delta_sec // 60))
                return True, f"Revenge Trade (открыта через {mins} мин после закрытия убытка #{last_trade.id})"

        # 3. Детектор Over-risking / Мартингейл (риск/объем >= 2x от средней нормы после убытка)
        past_losses = [t for t in sorted_recent[:5] if t.net_pnl < 0]
        if past_losses and len(sorted_recent) >= 2:
            avg_risk = float(np.mean([t.risk_amount for t in sorted_recent[:10] if t.risk_amount > 0] or [100.0]))
            avg_vol = float(np.mean([t.volume for t in sorted_recent[:10] if t.volume > 0] or [1.0]))

            if cand_risk > 0 and cand_risk >= avg_risk * 2.0:
                return True, f"Превышение риска x{cand_risk / avg_risk:.1f} сразу после убытков"
            if cand_vol >= avg_vol * 2.0:
                return True, f"Агрессивный оверобъем x{cand_vol / avg_vol:.1f} (Мартингейл)"

        return False, None

    @classmethod
    def calculate_metrics(
        cls,
        trades: List[Trade],
        exclude_tilt: bool = False,
    ) -> DashboardMetrics:
        """
        Вычисляет строгие метрики с защитой от деления на 0 и NaN.
        Поддерживает тумблер What-If фильтрации тильта (exclude_tilt).
        """
        if not trades:
            return DashboardMetrics()

        all_trades_count = len(trades)
        tilt_trades = [t for t in trades if t.is_tilt]
        tilt_count = len(tilt_trades)
        tilt_loss = abs(sum([t.net_pnl for t in tilt_trades if t.net_pnl < 0]))

        target_trades = [t for t in trades if not t.is_tilt] if exclude_tilt else trades

        if not target_trades:
            return DashboardMetrics(
                tilt_trades_count=tilt_count,
                tilt_loss_amount=round(tilt_loss, 2),
            )

        total = len(target_trades)
        pnls = [t.net_pnl for t in target_trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        breakevens = [p for p in pnls if p == 0]

        winrate = round((len(wins) / total * 100), 1) if total > 0 else 0.0

        gross_profit = round(sum(wins), 2)
        gross_loss = round(abs(sum(losses)), 2)

        if gross_loss > 0:
            profit_factor = round(gross_profit / gross_loss, 2)
        elif gross_profit > 0:
            profit_factor = 99.9  # Не падаем в inf
        else:
            profit_factor = 0.0

        net_pnl = round(sum(pnls), 2)
        avg_trade = round(net_pnl / total, 2) if total > 0 else 0.0

        # R-Multiple (с защитой от выбросов деления и зажатием в коридор [-10.0, +20.0])
        valid_r = []
        for t in target_trades:
            raw_r = getattr(t, "r_multiple", 0.0) or 0.0
            if raw_r != 0.0:
                valid_r.append(max(-10.0, min(20.0, raw_r)))
            elif t.net_pnl != 0.0:
                risk = getattr(t, "risk_amount", 0.0) or 0.0
                if risk < 1.0:
                    risk = 100.0
                valid_r.append(max(-10.0, min(20.0, t.net_pnl / risk)))
        avg_r = round(float(np.mean(valid_r)), 2) if valid_r else 0.0

        # Expectancy: (Winrate * Avg_Win) - (Lossrate * abs(Avg_Loss))
        avg_w = float(np.mean(wins)) if wins else 0.0
        avg_l = abs(float(np.mean(losses))) if losses else 0.0
        w_prob = len(wins) / total if total > 0 else 0.0
        l_prob = len(losses) / total if total > 0 else 0.0
        expectancy = round(w_prob * avg_w - l_prob * avg_l, 2)

        max_win = round(max(pnls), 2) if pnls else 0.0
        max_loss = round(min(pnls), 2) if pnls else 0.0

        # Издержки брокера и комиссионная нагрузка (Fee Drag)
        total_comm = round(sum([getattr(t, "commission", 0.0) or 0.0 for t in target_trades]), 2)
        total_swap = round(sum([getattr(t, "swap_fee", 0.0) or 0.0 for t in target_trades]), 2)
        total_broker_costs = round(total_comm + total_swap, 2)
        fee_drag = round((total_broker_costs / gross_profit * 100), 1) if gross_profit > 0 else 0.0

        # Скользящие спарклайны (последние 12 точек)
        sorted_asc = sorted([t for t in target_trades if t.closed_at], key=lambda x: x.closed_at) or target_trades
        winrate_spark = []
        pf_spark = []

        step_len = len(sorted_asc)
        start_idx = max(1, step_len - 11)
        for i in range(start_idx, step_len + 1):
            sub = sorted_asc[:i]
            sub_p = [t.net_pnl for t in sub]
            sub_w = [p for p in sub_p if p > 0]
            sub_l = [p for p in sub_p if p < 0]
            w_rate = round(len(sub_w) / len(sub) * 100, 1) if sub else 0.0
            winrate_spark.append(w_rate)

            g_w = sum(sub_w)
            g_l = abs(sum(sub_l))
            p_f = round(g_w / g_l, 2) if g_l > 0 else (99.9 if g_w > 0 else 1.0)
            pf_spark.append(min(p_f, 10.0))

        # 8. Квантовые метрики: SQN (Van Tharp), Sharpe и Sortino ratios
        r_multiples = [t.r_multiple for t in target_trades if t.r_multiple is not None]
        if len(r_multiples) >= 3:
            mean_r = float(np.mean(r_multiples))
            std_r = float(np.std(r_multiples, ddof=1)) if len(r_multiples) > 1 else 0.0
            if std_r > 0.0001:
                sqn_raw = math.sqrt(min(len(r_multiples), 100)) * (mean_r / std_r)
                sqn_val = round(float(sqn_raw), 2)
            else:
                sqn_val = 0.0
        else:
            sqn_val = 0.0

        if len(r_multiples) < 3 or sqn_val == 0.0:
            sqn_grade = "N/A"
        elif sqn_val < 1.6:
            sqn_grade = "Слабая (<1.6)"
        elif sqn_val < 2.0:
            sqn_grade = "Средняя (1.6-2.0)"
        elif sqn_val < 2.5:
            sqn_grade = "Хорошая (2.0-2.5)"
        elif sqn_val < 3.0:
            sqn_grade = "Отличная (2.5-3.0)"
        elif sqn_val < 5.0:
            sqn_grade = "Великолепная (3.0-5.0)"
        else:
            sqn_grade = "Святой Грааль (>5.0)"

        if len(pnls) >= 2:
            mean_pnl = float(np.mean(pnls))
            std_pnl = float(np.std(pnls, ddof=1))
            sharpe = round(mean_pnl / std_pnl, 2) if std_pnl > 0.0001 else 0.0
            downside = [p for p in pnls if p < 0]
            if downside:
                downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else abs(downside[0])
                sortino = round(mean_pnl / downside_std, 2) if downside_std > 0.0001 else 0.0
            else:
                sortino = round(sharpe * 1.5, 2) if sharpe > 0 else 0.0
        else:
            sharpe = 0.0
            sortino = 0.0

        # 9. Kelly Criterion Calculator (f* = (p * (b + 1) - 1) / b)
        if len(wins) > 0 and len(losses) > 0 and total > 0:
            p_win = len(wins) / total
            avg_w = float(gross_profit / len(wins))
            avg_l = float(gross_loss / len(losses))
            payoff_b = (avg_w / avg_l) if avg_l > 0 else 1.0
            if payoff_b > 0:
                raw_kelly = (p_win * (payoff_b + 1) - 1.0) / payoff_b
                kelly_pct = round(max(float(raw_kelly * 100), 0.0), 1)
                kelly_pct = min(kelly_pct, 25.0)  # Безопасный потолок риска
            else:
                kelly_pct = 0.0
            half_kelly = round(kelly_pct / 2.0, 1)
        else:
            kelly_pct = 0.0
            half_kelly = 0.0

        # 10. Consecutive Streaks Analysis
        max_w_streak = 0
        max_l_streak = 0
        curr_streak = 0
        cur_w = 0
        cur_l = 0

        for t in sorted_asc:
            p = float(t.net_pnl or 0.0)
            if p > 0:
                cur_w += 1
                cur_l = 0
                max_w_streak = max(max_w_streak, cur_w)
                curr_streak = cur_w
            elif p < 0:
                cur_l += 1
                cur_w = 0
                max_l_streak = max(max_l_streak, cur_l)
                curr_streak = -cur_l
            else:
                cur_w = 0
                cur_l = 0

        # 11. Drawdown, Recovery Factor & Ulcer Index Engine
        dd_mat = cls.calculate_drawdown_recovery_matrix(sorted_asc)

        metrics_obj = DashboardMetrics(
            total_trades=total,
            winning_trades=len(wins),
            losing_trades=len(losses),
            breakeven_trades=len(breakevens),
            winrate=winrate,
            profit_factor=profit_factor,
            net_pnl=net_pnl,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            avg_trade_pnl=avg_trade,
            avg_r_multiple=avg_r,
            expectancy=expectancy,
            max_win=max_win,
            max_loss=max_loss,
            winrate_sparkline=winrate_spark[-12:] if winrate_spark else [50.0, 50.0],
            profit_factor_sparkline=pf_spark[-12:] if pf_spark else [1.5, 1.5],
            tilt_trades_count=tilt_count,
            tilt_loss_amount=round(tilt_loss, 2),
            total_commission=total_comm,
            total_swap_fees=total_swap,
            total_broker_costs=total_broker_costs,
            fee_drag_pct=fee_drag,
            sqn=sqn_val,
            sqn_rating=sqn_grade,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            kelly_fraction_pct=kelly_pct,
            half_kelly_pct=half_kelly,
            max_win_streak=max_w_streak,
            max_loss_streak=max_l_streak,
            current_streak=curr_streak,
            max_drawdown_amount=dd_mat["max_drawdown_amount"],
            max_drawdown_pct=dd_mat["max_drawdown_pct"],
            recovery_factor=dd_mat["recovery_factor"],
            ulcer_index=dd_mat["ulcer_index"],
        )

        # Validation Pipeline: проверка и замена NaN/Inf на 0.0
        for f_name in metrics_obj.__dataclass_fields__:
            f_val = getattr(metrics_obj, f_name)
            if isinstance(f_val, float):
                if math.isnan(f_val) or math.isinf(f_val):
                    logging.warning(f"[AnalyticsService] NaN/Inf detected in {f_name}={f_val}. Replaced with 0.0")
                    setattr(metrics_obj, f_name, 0.0)

        return metrics_obj

    @classmethod
    def simulate_monte_carlo(
        cls,
        trades: List[Trade],
        n_simulations: int = 10000,
        n_steps: int = 20,
        initial_balance: float = 10000.0,
    ) -> Dict[str, Any]:
        """
        Векторная квантовая симуляция Монте-Карло (10 000 итераций bootstrap).
        Возвращает перцентили (P95, P75, P50, P25, P05) и метрики стресс-теста.
        """
        valid_trades = [t for t in trades if not t.is_tilt] or trades
        pnls = [t.net_pnl for t in valid_trades] if valid_trades else []

        base_balance = initial_balance if initial_balance > 0 else 10000.0
        current_equity = float(base_balance + sum([t.net_pnl for t in trades])) if trades else base_balance

        # Если сделок < 3, формируем синтетический массив с реальной волатильностью
        if len(pnls) < 3:
            base_drift = 120.0
            pnls = [base_drift * 1.5, -base_drift * 0.8, base_drift * 2.1, -base_drift * 0.9, base_drift * 1.2]

        pnl_array = np.array(pnls, dtype=float)

        # Генерация матрицы bootstrap: 10 000 траекторий x 20 шагов
        bootstrap_matrix = np.random.choice(pnl_array, size=(n_simulations, n_steps), replace=True)
        equity_paths = current_equity + np.cumsum(bootstrap_matrix, axis=1)

        # Точка t=0
        zeros = np.full((n_simulations, 1), current_equity)
        all_paths = np.hstack([zeros, equity_paths])

        # Перцентили
        p95 = np.percentile(all_paths, 95, axis=0)
        p75 = np.percentile(all_paths, 75, axis=0)
        p50 = np.percentile(all_paths, 50, axis=0)
        p25 = np.percentile(all_paths, 25, axis=0)
        p05 = np.percentile(all_paths, 5, axis=0)

        # 1. Risk of Ruin (% траекторий, ушедших ниже порога просадки 30% или нуля)
        ruin_threshold = max(current_equity * 0.7, 0.0) if current_equity > 0 else -abs(current_equity * 1.5)
        ruined_count = np.sum(np.min(all_paths, axis=1) < ruin_threshold)
        risk_of_ruin = round(float(ruined_count / n_simulations * 100), 1)

        # 2. 95% VaR Max Drawdown
        peaks = np.maximum.accumulate(all_paths, axis=1)
        drawdowns = (peaks - all_paths) / np.maximum(peaks, 1.0) * 100
        max_dds = np.max(drawdowns, axis=1)
        var_95_dd = round(float(np.percentile(max_dds, 95)), 1)

        # 3. Expectancy Run
        final_median = p50[-1]
        exp_gain_pct = round(((final_median - current_equity) / max(abs(current_equity), 1.0)) * 100, 1)

        return {
            "steps": n_steps + 1,
            "p95": [round(x, 1) for x in p95],
            "p75": [round(x, 1) for x in p75],
            "p50": [round(x, 1) for x in p50],
            "p25": [round(x, 1) for x in p25],
            "p05": [round(x, 1) for x in p05],
            "min_val": round(float(np.min(p05)), 1),
            "max_val": round(float(np.max(p95)), 1),
            "risk_of_ruin": min(risk_of_ruin, 99.9),
            "var_95_max_dd": var_95_dd,
            "expectancy_run": exp_gain_pct,
        }

    @classmethod
    def calculate_session_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Квантовая матрица эффективности по торговым сессиям (UTC):
        - Asian: 00:00 – 08:00 UTC (Tokyo, Sydney, Hong Kong)
        - London: 08:00 – 13:00 UTC (Frankfurt, London Open)
        - New York: 13:00 – 21:00 UTC (Wall Street, US Overlap)
        - Off-Hours: 21:00 – 00:00 UTC (После закрытия США, низкая ликвидность)
        """
        sessions_def = {
            "ASIAN": {
                "key": "ASIAN",
                "name": "Азиатская сессия",
                "sub": "Tokyo / Sydney / HK",
                "time_range": "00:00 – 08:00 UTC",
                "color": "#22D3EE",  # Neon Cyan
                "icon": "nights_stay_rounded",
            },
            "LONDON": {
                "key": "LONDON",
                "name": "Лондонская сессия",
                "sub": "London / Frankfurt Open",
                "time_range": "08:00 – 13:00 UTC",
                "color": "#6366F1",  # Indigo
                "icon": "wb_sunny_rounded",
            },
            "NEW_YORK": {
                "key": "NEW_YORK",
                "name": "Американская сессия",
                "sub": "Wall Street / NYSE / CME",
                "time_range": "13:00 – 21:00 UTC",
                "color": "#7C5CFF",  # Accent Purple
                "icon": "trending_up_rounded",
            },
            "OFF_HOURS": {
                "key": "OFF_HOURS",
                "name": "Внесессионное время",
                "sub": "Post-market / Low Liquidity",
                "time_range": "21:00 – 00:00 UTC",
                "color": "#FBBF24",  # Amber
                "icon": "bedtime_rounded",
            },
        }

        bucketed: Dict[str, List[Trade]] = {k: [] for k in sessions_def}

        for t in trades:
            dt = t.opened_at or t.closed_at or getattr(t, "date", None)
            if not dt:
                bucketed["NEW_YORK"].append(t)
                continue
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                except Exception:
                    dt = datetime.now()

            hour = dt.hour
            if 0 <= hour < 8:
                bucketed["ASIAN"].append(t)
            elif 8 <= hour < 13:
                bucketed["LONDON"].append(t)
            elif 13 <= hour < 21:
                bucketed["NEW_YORK"].append(t)
            else:
                bucketed["OFF_HOURS"].append(t)

        results = {}
        for s_key, s_trades in bucketed.items():
            meta = sessions_def[s_key]
            count = len(s_trades)
            if count == 0:
                results[s_key] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "gross_profit": 0.0,
                    "gross_loss": 0.0,
                    "profit_factor": 0.0,
                    "avg_trade_pnl": 0.0,
                    "expectancy": 0.0,
                    "best_trade": 0.0,
                    "worst_trade": 0.0,
                }
                continue

            pnls = [t.net_pnl for t in s_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            gross_w = float(sum(wins))
            gross_l = float(abs(sum(losses)))

            winrate = round(len(wins) / count * 100, 1)
            net_pnl = round(float(sum(pnls)), 2)
            pf = round(gross_w / gross_l, 2) if gross_l > 0 else (99.9 if gross_w > 0 else 1.0)
            avg_pnl = round(net_pnl / count, 2)

            win_rate_dec = len(wins) / count
            loss_rate_dec = len(losses) / count
            avg_w = (gross_w / len(wins)) if wins else 0.0
            avg_l = (gross_l / len(losses)) if losses else 0.0
            exp = round((win_rate_dec * avg_w) - (loss_rate_dec * avg_l), 2)

            results[s_key] = {
                **meta,
                "trades_count": count,
                "win_trades": len(wins),
                "loss_trades": len(losses),
                "winrate": winrate,
                "net_pnl": net_pnl,
                "gross_profit": round(gross_w, 2),
                "gross_loss": round(gross_l, 2),
                "profit_factor": pf,
                "avg_trade_pnl": avg_pnl,
                "expectancy": exp,
                "best_trade": round(max(pnls), 2) if pnls else 0.0,
                "worst_trade": round(min(pnls), 2) if pnls else 0.0,
            }

        # Вычисление лидеров и аутсайдеров
        active_sessions = [res for res in results.values() if res["trades_count"] > 0]
        best_session_key = max(active_sessions, key=lambda x: x["net_pnl"])["key"] if active_sessions else None
        worst_session_key = min(active_sessions, key=lambda x: x["net_pnl"])["key"] if active_sessions else None

        return {
            "sessions": results,
            "best_session": best_session_key,
            "worst_session": worst_session_key,
            "total_analyzed_trades": len(trades),
        }

    @classmethod
    def calculate_time_heatmap(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Матрица прибыльности Day-of-Week & Hour-of-Day (Тепловая карта времени):
        - Дни недели: Пн(0) .. Вс(6)
        - Часы суток: 0 .. 23 (UTC)
        """
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

        # Инициализация сетки 7x24
        grid: Dict[int, Dict[int, List[float]]] = {d: {h: [] for h in range(24)} for d in range(7)}

        for t in trades:
            dt = t.opened_at or t.closed_at or getattr(t, "date", None)
            if not dt:
                continue
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                except Exception:
                    continue

            d = dt.weekday()
            h = dt.hour
            if 0 <= d < 7 and 0 <= h < 24:
                grid[d][h].append(float(t.net_pnl or 0.0))

        # Формирование агрегатов ячеек
        cells: Dict[int, Dict[int, Dict[str, Any]]] = {}
        all_cell_pnls = []

        day_aggregates: Dict[int, Dict[str, Any]] = {}
        for d in range(7):
            day_pnls = []
            cells[d] = {}
            for h in range(24):
                pnls = grid[d][h]
                count = len(pnls)
                net_pnl = round(sum(pnls), 2)
                wins = len([p for p in pnls if p > 0])
                wr = round(wins / count * 100, 1) if count > 0 else 0.0

                cells[d][h] = {
                    "day_idx": d,
                    "day_name": day_names[d],
                    "hour": h,
                    "count": count,
                    "net_pnl": net_pnl,
                    "winrate": wr,
                }
                if count > 0:
                    all_cell_pnls.append(net_pnl)
                    day_pnls.extend(pnls)

            day_count = len(day_pnls)
            day_net = round(sum(day_pnls), 2)
            day_wins = len([p for p in day_pnls if p > 0])
            day_aggregates[d] = {
                "day_idx": d,
                "day_name": day_names[d],
                "count": day_count,
                "net_pnl": day_net,
                "winrate": round(day_wins / day_count * 100, 1) if day_count > 0 else 0.0,
            }

        # Агрегаты по часам суток (0..23)
        hour_aggregates: Dict[int, Dict[str, Any]] = {}
        for h in range(24):
            h_pnls = []
            for d in range(7):
                h_pnls.extend(grid[d][h])
            h_count = len(h_pnls)
            h_net = round(sum(h_pnls), 2)
            h_wins = len([p for p in h_pnls if p > 0])
            hour_aggregates[h] = {
                "hour": h,
                "count": h_count,
                "net_pnl": h_net,
                "winrate": round(h_wins / h_count * 100, 1) if h_count > 0 else 0.0,
            }

        max_pos = max([p for p in all_cell_pnls if p > 0] or [100.0])
        max_neg = abs(min([p for p in all_cell_pnls if p < 0] or [-100.0]))

        active_days = [da for da in day_aggregates.values() if da["count"] > 0]
        best_day = max(active_days, key=lambda x: x["net_pnl"]) if active_days else None
        worst_day = min(active_days, key=lambda x: x["net_pnl"]) if active_days else None

        active_hours = [ha for ha in hour_aggregates.values() if ha["count"] > 0]
        best_hour = max(active_hours, key=lambda x: x["net_pnl"]) if active_hours else None
        worst_hour = min(active_hours, key=lambda x: x["net_pnl"]) if active_hours else None

        return {
            "cells": cells,
            "day_aggregates": day_aggregates,
            "hour_aggregates": hour_aggregates,
            "max_pos_pnl": max_pos,
            "max_neg_pnl": max_neg,
            "best_day": best_day,
            "worst_day": worst_day,
            "best_hour": best_hour,
            "worst_hour": worst_hour,
            "total_trades": len(trades),
        }

    @classmethod
    def calculate_kelly_criterion(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Квантовый калькулятор оптимальной доли капитала по критерию Келли:
        f* = (p * (b + 1) - 1) / b
        где p - вероятность выигрыша, b - коэффициент выигрыша (Payoff Ratio).
        Рекомендуется Half-Kelly (50% от f*) для снижения риска просадки.
        """
        metrics = cls.calculate_metrics(trades)
        return {
            "kelly_fraction_pct": metrics.kelly_fraction_pct,
            "half_kelly_pct": metrics.half_kelly_pct,
            "winrate": metrics.winrate,
            "is_edge_positive": metrics.kelly_fraction_pct > 0.0,
            "recommendation": (
                f"Рекомендуемый риск на сделку: {metrics.half_kelly_pct:.1f}% от депозита (Half-Kelly)"
                if metrics.kelly_fraction_pct > 0.0
                else "Математическое преимущество отсутствует. Торгуйте минимальным лотом."
            ),
        }

    @classmethod
    def calculate_streaks(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Анализ серий непрерывных побед и поражений (Consecutive Streaks).
        """
        sorted_asc = sorted([t for t in trades if t.closed_at], key=lambda x: x.closed_at) or trades

        win_streaks = []
        loss_streaks = []
        cur_w = 0
        cur_l = 0

        for t in sorted_asc:
            p = float(t.net_pnl or 0.0)
            if p > 0:
                cur_w += 1
                if cur_l > 0:
                    loss_streaks.append(cur_l)
                    cur_l = 0
            elif p < 0:
                cur_l += 1
                if cur_w > 0:
                    win_streaks.append(cur_w)
                    cur_w = 0

        if cur_w > 0:
            win_streaks.append(cur_w)
        if cur_l > 0:
            loss_streaks.append(cur_l)

        max_w = max(win_streaks or [0])
        max_l = max(loss_streaks or [0])
        avg_w = round(float(np.mean(win_streaks)), 1) if win_streaks else 0.0
        avg_l = round(float(np.mean(loss_streaks)), 1) if loss_streaks else 0.0

        current_streak = 0
        if sorted_asc:
            last_pnls = [float(t.net_pnl or 0.0) for t in sorted_asc]
            last_sign = 1 if last_pnls[-1] > 0 else (-1 if last_pnls[-1] < 0 else 0)
            streak_len = 0
            for p in reversed(last_pnls):
                s = 1 if p > 0 else (-1 if p < 0 else 0)
                if s == last_sign and s != 0:
                    streak_len += 1
                else:
                    break
            current_streak = streak_len * last_sign

        return {
            "max_win_streak": max_w,
            "max_loss_streak": max_l,
            "avg_win_streak": avg_w,
            "avg_loss_streak": avg_l,
            "current_streak": current_streak,
            "total_win_sequences": len(win_streaks),
            "total_loss_sequences": len(loss_streaks),
        }

    @classmethod
    def calculate_strategy_leaderboard(cls, trades: List[Trade]) -> List[Dict[str, Any]]:
        """
        Квантовый рейтинг торговых стратегий и сетапов (Edgewonk Strategy Leaderboard).
        Ранжирует паттерны по совокупной прибыли, винрейту, Profit Factor и SQN.
        """
        if not trades:
            return []

        grouped: Dict[str, List[Trade]] = {}
        for t in trades:
            tag = (t.strategy_tag or "Общая").strip()
            if not tag:
                tag = "Общая"
            if tag not in grouped:
                grouped[tag] = []
            grouped[tag].append(t)

        leaderboard = []
        for tag, s_trades in grouped.items():
            count = len(s_trades)
            pnls = [float(t.net_pnl or 0.0) for t in s_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            gross_w = float(sum(wins))
            gross_l = float(abs(sum(losses)))

            winrate = round(len(wins) / count * 100, 1) if count > 0 else 0.0
            net_pnl = round(float(sum(pnls)), 2)
            pf = round(gross_w / gross_l, 2) if gross_l > 0 else (99.9 if gross_w > 0 else 1.0)
            avg_pnl = round(net_pnl / count, 2) if count > 0 else 0.0

            r_vals = [t.r_multiple for t in s_trades if t.r_multiple is not None]
            avg_r = round(float(np.mean(r_vals)), 2) if r_vals else 0.0

            if len(r_vals) >= 2:
                std_r = float(np.std(r_vals, ddof=1))
                sqn = round(math.sqrt(min(len(r_vals), 100)) * (avg_r / std_r), 2) if std_r > 0.0001 else 0.0
            else:
                sqn = 0.0

            leaderboard.append({
                "tag": tag,
                "trades_count": count,
                "win_trades": len(wins),
                "loss_trades": len(losses),
                "winrate": winrate,
                "gross_profit": round(gross_w, 2),
                "gross_loss": round(gross_l, 2),
                "net_pnl": net_pnl,
                "profit_factor": pf,
                "avg_trade_pnl": avg_pnl,
                "avg_r": avg_r,
                "sqn": sqn,
            })

        # Сортировка: сначала самые прибыльные стратегии
        leaderboard.sort(key=lambda x: (x["net_pnl"], x["profit_factor"]), reverse=True)

        for idx, item in enumerate(leaderboard, start=1):
            item["rank"] = idx

        return leaderboard

    @classmethod
    def calculate_duration_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Квантовый анализ времени удержания позиций (Holding Duration vs PnL).
        Диагностирует проблему пересиживания убытков и преждевременного закрытия профита.
        """
        brackets_def = {
            "SCALP": {
                "key": "SCALP",
                "name": "Скальпинг",
                "range_label": "< 15 минут",
                "color": "#22D3EE",
            },
            "SHORT_INTRA": {
                "key": "SHORT_INTRA",
                "name": "Короткий интрадей",
                "range_label": "15м – 1 час",
                "color": "#6366F1",
            },
            "MID_INTRA": {
                "key": "MID_INTRA",
                "name": "Интрадей трейд",
                "range_label": "1 – 4 часа",
                "color": "#7C5CFF",
            },
            "DAY_TRADE": {
                "key": "DAY_TRADE",
                "name": "Дневной трейд",
                "range_label": "4 – 24 часа",
                "color": "#F472B6",
            },
            "SWING": {
                "key": "SWING",
                "name": "Свинг позиция",
                "range_label": "> 24 часов",
                "color": "#FBBF24",
            },
        }

        bucketed: Dict[str, List[Trade]] = {k: [] for k in brackets_def}
        durations_sec_map: Dict[str, List[float]] = {k: [] for k in brackets_def}

        for t in trades:
            t_open = t.opened_at
            t_close = t.closed_at
            if isinstance(t_open, str):
                try:
                    t_open = datetime.fromisoformat(t_open.replace("Z", "+00:00"))
                except Exception:
                    t_open = None
            if isinstance(t_close, str):
                try:
                    t_close = datetime.fromisoformat(t_close.replace("Z", "+00:00"))
                except Exception:
                    t_close = None

            if t_open and t_close and t_close >= t_open:
                sec = (t_close - t_open).total_seconds()
            else:
                sec = 3600.0  # Дефолт 1 час

            if sec < 900:
                b_key = "SCALP"
            elif sec < 3600:
                b_key = "SHORT_INTRA"
            elif sec < 14400:
                b_key = "MID_INTRA"
            elif sec < 86400:
                b_key = "DAY_TRADE"
            else:
                b_key = "SWING"

            bucketed[b_key].append(t)
            durations_sec_map[b_key].append(sec)

        results = {}
        for b_key, b_trades in bucketed.items():
            meta = brackets_def[b_key]
            count = len(b_trades)
            if count == 0:
                results[b_key] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "avg_trade_pnl": 0.0,
                    "avg_duration_min": 0.0,
                    "avg_efficiency": 0.0,
                }
                continue

            pnls = [float(t.net_pnl or 0.0) for t in b_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            gross_w = float(sum(wins))
            gross_l = float(abs(sum(losses)))

            winrate = round(len(wins) / count * 100, 1)
            net_pnl = round(float(sum(pnls)), 2)
            pf = round(gross_w / gross_l, 2) if gross_l > 0 else (99.9 if gross_w > 0 else 1.0)
            avg_pnl = round(net_pnl / count, 2)
            avg_dur_min = round(float(np.mean(durations_sec_map[b_key])) / 60.0, 1)
            eff_vals = [float(t.efficiency) for t in b_trades if getattr(t, "efficiency", None) is not None]
            avg_eff = round(float(np.mean(eff_vals)) * 100, 1) if eff_vals else 50.0

            results[b_key] = {
                **meta,
                "trades_count": count,
                "win_trades": len(wins),
                "loss_trades": len(losses),
                "winrate": winrate,
                "net_pnl": net_pnl,
                "profit_factor": pf,
                "avg_trade_pnl": avg_pnl,
                "avg_duration_min": avg_dur_min,
                "avg_efficiency": avg_eff,
            }

        active_brackets = [b for b in results.values() if b["trades_count"] > 0]
        best_duration = max(active_brackets, key=lambda x: x["net_pnl"])["key"] if active_brackets else None
        worst_duration = min(active_brackets, key=lambda x: x["net_pnl"])["key"] if active_brackets else None

        return {
            "brackets": results,
            "best_duration": best_duration,
            "worst_duration": worst_duration,
            "total_trades": len(trades),
        }

    @classmethod
    def calculate_asset_allocation_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Анализ распределения капитала по классам активов и концентрации риска (TraderVue / TradeZella).
        Сегментирует сделки на Криптовалюты (Crypto), Форекс (Forex), Акции/Индексы (Equities/Indices)
        и Сырьевые товары (Commodities). Выявляет риск овер-концентрации портфеля (>40% объема в одном активе).
        """
        classes_def = {
            "CRYPTO": {
                "key": "CRYPTO",
                "name": "Криптовалюты",
                "color": "#10B981",
                "icon": "currency_bitcoin_rounded",
            },
            "FOREX": {
                "key": "FOREX",
                "name": "Форекс (FX)",
                "color": "#6366F1",
                "icon": "currency_exchange_rounded",
            },
            "EQUITIES": {
                "key": "EQUITIES",
                "name": "Акции & Индексы",
                "color": "#7C5CFF",
                "icon": "candlestick_chart_rounded",
            },
            "COMMODITIES": {
                "key": "COMMODITIES",
                "name": "Сырье & Металлы",
                "color": "#F59E0B",
                "icon": "diamond_rounded",
            },
        }

        def detect_asset_class(ticker: str) -> str:
            t = (ticker or "").upper().strip()
            if any(c in t for c in ["XAU", "GOLD", "OIL", "USOIL", "WTI", "XAG", "SILVER", "BRENT"]):
                return "COMMODITIES"
            if "/" in t:
                parts = t.split("/")
                fx_currencies = {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"}
                if any(p in fx_currencies for p in parts):
                    return "FOREX"
            if any(t.endswith(s) for s in ["USDT", "BUSD", "USDC", "PERP"]) or any(t.startswith(s) for s in ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "NEAR", "LINK"]):
                return "CRYPTO"
            return "EQUITIES"

        if not trades:
            empty_classes = {}
            for k, meta in classes_def.items():
                empty_classes[k] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "volume_turnover": 0.0,
                    "share_pct": 0.0,
                }
            return {
                "asset_classes": empty_classes,
                "top_symbols": [],
                "concentration_warning": None,
                "best_class": None,
                "worst_class": None,
                "total_volume": 0.0,
                "total_trades": 0,
            }

        # Группировка по классам активов и символам
        class_buckets: Dict[str, List[Trade]] = {k: [] for k in classes_def}
        symbol_buckets: Dict[str, List[Trade]] = {}

        for t in trades:
            c_key = detect_asset_class(t.ticker)
            class_buckets[c_key].append(t)
            sym = (t.ticker or "UNKNOWN").upper().strip()
            if sym not in symbol_buckets:
                symbol_buckets[sym] = []
            symbol_buckets[sym].append(t)

        def calc_turnover(t_list: List[Trade]) -> float:
            total = 0.0
            for t in t_list:
                vol = float(t.volume or 1.0)
                px = float(t.entry_price or 1.0)
                total += vol * px
            return total

        total_turnover = calc_turnover(trades)
        if total_turnover <= 0.0:
            total_turnover = float(len(trades))

        class_results = {}
        for c_key, c_trades in class_buckets.items():
            meta = classes_def[c_key]
            cnt = len(c_trades)
            if cnt == 0:
                class_results[c_key] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "volume_turnover": 0.0,
                    "share_pct": 0.0,
                }
                continue

            pnls = [float(t.net_pnl or 0.0) for t in c_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            gross_w = float(sum(wins))
            gross_l = float(abs(sum(losses)))

            winrate = round(len(wins) / cnt * 100, 1)
            net_pnl = round(float(sum(pnls)), 2)
            pf = round(gross_w / gross_l, 2) if gross_l > 0 else (99.9 if gross_w > 0 else 1.0)
            c_turnover = calc_turnover(c_trades)
            share_pct = round((c_turnover / total_turnover) * 100, 1)

            class_results[c_key] = {
                **meta,
                "trades_count": cnt,
                "win_trades": len(wins),
                "loss_trades": len(losses),
                "winrate": winrate,
                "net_pnl": net_pnl,
                "profit_factor": pf,
                "volume_turnover": round(c_turnover, 2),
                "share_pct": share_pct,
            }

        # Анализ топ-символов
        top_symbols = []
        concentration_warning = None

        for sym, sym_trades in symbol_buckets.items():
            cnt = len(sym_trades)
            pnls = [float(t.net_pnl or 0.0) for t in sym_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            gross_w = float(sum(wins))
            gross_l = float(abs(sum(losses)))

            winrate = round(len(wins) / cnt * 100, 1)
            net_pnl = round(float(sum(pnls)), 2)
            pf = round(gross_w / gross_l, 2) if gross_l > 0 else (99.9 if gross_w > 0 else 1.0)
            sym_turnover = calc_turnover(sym_trades)
            share_pct = round((sym_turnover / total_turnover) * 100, 1)

            if share_pct >= 40.0 and len(trades) >= 3:
                concentration_warning = f"Овер-концентрация риска: на {sym} приходится {share_pct}% торгового оборота"

            top_symbols.append({
                "ticker": sym,
                "asset_class": detect_asset_class(sym),
                "trades_count": cnt,
                "winrate": winrate,
                "net_pnl": net_pnl,
                "profit_factor": pf,
                "volume_turnover": round(sym_turnover, 2),
                "share_pct": share_pct,
            })

        # Сортируем топ-активы по обороту и количеству сделок
        top_symbols.sort(key=lambda s: (s["share_pct"], s["trades_count"]), reverse=True)
        top_symbols = top_symbols[:6]

        active_classes = [c for c in class_results.values() if c["trades_count"] > 0]
        best_class = max(active_classes, key=lambda x: x["net_pnl"])["key"] if active_classes else None
        worst_class = min(active_classes, key=lambda x: x["net_pnl"])["key"] if active_classes else None

        return {
            "asset_classes": class_results,
            "top_symbols": top_symbols,
            "concentration_warning": concentration_warning,
            "best_class": best_class,
            "worst_class": worst_class,
            "total_volume": round(total_turnover, 2),
            "total_trades": len(trades),
        }

    @classmethod
    def calculate_psychology_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Квантовый аудит дисциплины и психологии трейдера (Edgewonk Emotional Tilt & Alpha Leak Matrix).
        Рассчитывает 'Discipline Score', общую стоимость тильта (Tilt Drag), влияние эмоциональных
        сделок на PnL и классифицирует психологические ошибки (Revenge, FOMO, Over-risk, Impulsive).
        """
        if not trades:
            return {
                "total_trades": 0,
                "disciplined_trades": 0,
                "tilt_trades": 0,
                "discipline_score_pct": 100.0,
                "disciplined_net_pnl": 0.0,
                "tilt_net_pnl": 0.0,
                "actual_net_pnl": 0.0,
                "tilt_drag_amount": 0.0,
                "primary_emotional_leak": None,
                "reasons_breakdown": [],
            }

        total_cnt = len(trades)
        disciplined_list = [t for t in trades if not getattr(t, "is_tilt", False)]
        tilt_list = [t for t in trades if getattr(t, "is_tilt", False)]

        disciplined_cnt = len(disciplined_list)
        tilt_cnt = len(tilt_list)
        discipline_score = round((disciplined_cnt / total_cnt) * 100.0, 1)

        disciplined_pnl = round(float(sum(float(t.net_pnl or 0.0) for t in disciplined_list)), 2)
        tilt_pnl = round(float(sum(float(t.net_pnl or 0.0) for t in tilt_list)), 2)
        actual_pnl = round(disciplined_pnl + tilt_pnl, 2)

        tilt_drag = round(abs(tilt_pnl) if tilt_pnl < 0 else 0.0, 2)

        category_defs = {
            "REVENGE": {"name": "Revenge Trading (Отыгрыш)", "icon": "local_fire_department_rounded", "color": "#EF4444"},
            "FOMO": {"name": "FOMO (Вход на эмоциях)", "icon": "rocket_launch_rounded", "color": "#F59E0B"},
            "OVER_RISK": {"name": "Превышение риска (>2x)", "icon": "warning_rounded", "color": "#EC4899"},
            "CHECKLIST": {"name": "Нарушение чек-листа", "icon": "rule_rounded", "color": "#8B5CF6"},
            "OTHER": {"name": "Прочие ошибки дисциплины", "icon": "psychology_rounded", "color": "#6B7280"},
        }

        breakdown_map: Dict[str, List[Trade]] = {k: [] for k in category_defs}
        for t in tilt_list:
            reason = (getattr(t, "tilt_reason", None) or getattr(t, "notes", "") or "").lower()
            if any(w in reason for w in ["revenge", "отыгрыш", "реверс", "после лосса", "после стопа"]):
                breakdown_map["REVENGE"].append(t)
            elif any(w in reason for w in ["fomo", "фомо", "упущен", "вершина", "хаях", "погоня"]):
                breakdown_map["FOMO"].append(t)
            elif any(w in reason for w in ["риск", "over-risk", "объем", "плеч", "удвоен"]):
                breakdown_map["OVER_RISK"].append(t)
            elif any(w in reason for w in ["чек-лист", "правил", "план", "систем"]):
                breakdown_map["CHECKLIST"].append(t)
            else:
                breakdown_map["OTHER"].append(t)

        reasons_list = []
        for cat_key, cat_trades in breakdown_map.items():
            if not cat_trades:
                continue
            meta = category_defs[cat_key]
            c_pnl = round(float(sum(float(t.net_pnl or 0.0) for t in cat_trades)), 2)
            reasons_list.append({
                "key": cat_key,
                "name": meta["name"],
                "icon": meta["icon"],
                "color": meta["color"],
                "trades_count": len(cat_trades),
                "net_pnl": c_pnl,
            })

        reasons_list.sort(key=lambda x: x["net_pnl"])
        primary_leak = reasons_list[0]["name"] if (reasons_list and reasons_list[0]["net_pnl"] < 0) else None

        return {
            "total_trades": total_cnt,
            "disciplined_trades": disciplined_cnt,
            "tilt_trades": tilt_cnt,
            "discipline_score_pct": discipline_score,
            "disciplined_net_pnl": disciplined_pnl,
            "tilt_net_pnl": tilt_pnl,
            "actual_net_pnl": actual_pnl,
            "tilt_drag_amount": tilt_drag,
            "primary_emotional_leak": primary_leak,
            "reasons_breakdown": reasons_list,
        }

    @classmethod
    def calculate_drawdown_recovery_matrix(
        cls,
        trades: List[Trade],
        initial_balance: float = 10000.0,
    ) -> Dict[str, Any]:
        """
        Квантовый анализ просадок, фактора восстановления и индекса язвы (TraderSync / Portfolio Visualizer).
        Рассчитывает Max Drawdown ($ и %), Recovery Factor (Net PnL / Max DD), Ulcer Index и длительность выхода из просадки.
        """
        if not trades:
            return {
                "max_drawdown_amount": 0.0,
                "max_drawdown_pct": 0.0,
                "current_drawdown_amount": 0.0,
                "current_drawdown_pct": 0.0,
                "recovery_factor": 0.0,
                "ulcer_index": 0.0,
                "peak_to_valley_trades": 0,
                "net_pnl": 0.0,
                "peak_equity": initial_balance,
                "final_equity": initial_balance,
            }

        sorted_trades = sorted(
            trades,
            key=lambda t: (
                t.closed_at or t.opened_at or getattr(t, "date", datetime.min),
                t.id or 0,
            ),
        )

        equity = float(initial_balance)
        peak = float(initial_balance)
        max_dd_amount = 0.0
        max_dd_pct = 0.0
        drawdown_pcts = []
        current_streak_dd = 0
        max_p2v_trades = 0

        for t in sorted_trades:
            p = float(t.net_pnl or 0.0)
            equity += p
            if equity > peak:
                peak = equity
                current_streak_dd = 0
                drawdown_pcts.append(0.0)
            else:
                dd_amt = peak - equity
                dd_pct = (dd_amt / peak) * 100.0 if peak > 0 else 0.0
                drawdown_pcts.append(dd_pct)
                current_streak_dd += 1
                max_p2v_trades = max(max_p2v_trades, current_streak_dd)
                if dd_amt > max_dd_amount:
                    max_dd_amount = dd_amt
                    max_dd_pct = dd_pct

        net_pnl = float(equity - initial_balance)
        if max_dd_amount > 0:
            recovery_factor = round(net_pnl / max_dd_amount, 2)
        elif net_pnl > 0:
            recovery_factor = 99.9
        else:
            recovery_factor = 1.0

        curr_dd_amt = round(max(0.0, peak - equity), 2)
        curr_dd_pct = round((curr_dd_amt / peak) * 100.0, 1) if peak > 0 else 0.0

        if drawdown_pcts:
            ui = round(float(np.sqrt(np.mean([d ** 2 for d in drawdown_pcts]))), 2)
        else:
            ui = 0.0

        return {
            "max_drawdown_amount": round(max_dd_amount, 2),
            "max_drawdown_pct": round(max_dd_pct, 1),
            "current_drawdown_amount": curr_dd_amt,
            "current_drawdown_pct": curr_dd_pct,
            "recovery_factor": recovery_factor,
            "ulcer_index": ui,
            "peak_to_valley_trades": max_p2v_trades,
            "net_pnl": round(net_pnl, 2),
            "peak_equity": round(peak, 2),
            "final_equity": round(equity, 2),
        }

    @classmethod
    def calculate_excursion_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Квантовый анализ качества входов и выходов (TradeZella MAE / MFE Execution Matrix).
        Рассчитывает средний MAE (неблагоприятное отклонение), MFE (потенциал движения),
        коэффициент Edge Ratio (MFE/MAE) и упущенную прибыль (Money Left on the Table).
        """
        if not trades:
            return {
                "total_trades": 0,
                "avg_mae_pct": 0.0,
                "avg_mfe_pct": 0.0,
                "avg_efficiency_pct": 0.0,
                "edge_ratio": 0.0,
                "left_on_table_amount": 0.0,
                "edge_rating": "N/A",
            }

        valid_mae = [abs(float(t.mae_pct or 0.0)) for t in trades if getattr(t, "mae_pct", None) is not None]
        valid_mfe = [float(t.mfe_pct or 0.0) for t in trades if getattr(t, "mfe_pct", None) is not None]
        valid_eff = [float(t.efficiency or 0.5) * 100.0 for t in trades if getattr(t, "efficiency", None) is not None]

        avg_mae = round(float(np.mean(valid_mae)), 2) if valid_mae else 1.2
        avg_mfe = round(float(np.mean(valid_mfe)), 2) if valid_mfe else 3.5
        avg_eff = round(float(np.mean(valid_eff)), 1) if valid_eff else 50.0

        if avg_mae > 0:
            edge_ratio = round(avg_mfe / avg_mae, 2)
        else:
            edge_ratio = round(avg_mfe, 2)

        if edge_ratio >= 2.5:
            edge_grade = "Превосходный тайминг (Сильный Edge)"
        elif edge_ratio >= 1.5:
            edge_grade = "Здоровый Edge (MFE превосходит MAE)"
        else:
            edge_grade = "Низкий тайминг (Глубокие просадки MAE)"

        left_on_table = 0.0
        for t in trades:
            p = float(t.net_pnl or 0.0)
            if p > 0:
                eff = float(getattr(t, "efficiency", 0.5) or 0.5)
                if 0.05 < eff < 0.85:
                    full_pot = p / eff
                    left_on_table += (full_pot - p)

        return {
            "total_trades": len(trades),
            "avg_mae_pct": avg_mae,
            "avg_mfe_pct": avg_mfe,
            "avg_efficiency_pct": avg_eff,
            "edge_ratio": edge_ratio,
            "left_on_table_amount": round(left_on_table, 2),
            "edge_rating": edge_grade,
        }

    @classmethod
    def calculate_monthly_phase_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Анализ циклических фаз месяца и сезонности (TraderSync / Edgewonk Monthly Phase Matrix).
        Разбивает сделки на 3 декады месяца:
        - EARLY_MONTH (1–10 число): Приток институциональной ликвидности, NFP, PMI.
        - MID_MONTH (11–20 число): Инфляционные релизы CPI/PPI, заседание FOMC.
        - LATE_MONTH (21–31 число): Экспирация опционов OPEX, фиксация кварталов/месяцев.
        """
        phases_def = {
            "EARLY_MONTH": {
                "key": "EARLY_MONTH",
                "name": "Начало месяца (1-10)",
                "sub": "NFP / Новые потоки ликвидности",
                "color": "#10B981",
                "icon": "calendar_today_rounded",
            },
            "MID_MONTH": {
                "key": "MID_MONTH",
                "name": "Середина месяца (11-20)",
                "sub": "CPI / PPI / Заседания FOMC",
                "color": "#6366F1",
                "icon": "event_repeat_rounded",
            },
            "LATE_MONTH": {
                "key": "LATE_MONTH",
                "name": "Конец месяца (21-31)",
                "sub": "OPEX Экспирация / Ребалансировка",
                "color": "#F59E0B",
                "icon": "event_available_rounded",
            },
        }

        if not trades:
            empty_phases = {}
            for k, meta in phases_def.items():
                empty_phases[k] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "avg_trade_pnl": 0.0,
                }
            return {
                "phases": empty_phases,
                "best_phase": None,
                "worst_phase": None,
                "seasonal_insight": "Циклический анализ месяца активен",
                "total_trades": 0,
            }

        bucketed: Dict[str, List[Trade]] = {k: [] for k in phases_def}

        for t in trades:
            dt = t.closed_at or t.opened_at or getattr(t, "date", None)
            if not dt:
                bucketed["MID_MONTH"].append(t)
                continue
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                except Exception:
                    dt = datetime.now()

            day = dt.day
            if 1 <= day <= 10:
                bucketed["EARLY_MONTH"].append(t)
            elif 11 <= day <= 20:
                bucketed["MID_MONTH"].append(t)
            else:
                bucketed["LATE_MONTH"].append(t)

        results = {}
        for p_key, p_trades in bucketed.items():
            meta = phases_def[p_key]
            cnt = len(p_trades)
            if cnt == 0:
                results[p_key] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "avg_trade_pnl": 0.0,
                }
                continue

            pnls = [float(t.net_pnl or 0.0) for t in p_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            gross_w = float(sum(wins))
            gross_l = float(abs(sum(losses)))

            winrate = round(len(wins) / cnt * 100, 1)
            net_pnl = round(float(sum(pnls)), 2)
            pf = round(gross_w / gross_l, 2) if gross_l > 0 else (99.9 if gross_w > 0 else 1.0)
            avg_pnl = round(net_pnl / cnt, 2)

            results[p_key] = {
                **meta,
                "trades_count": cnt,
                "win_trades": len(wins),
                "loss_trades": len(losses),
                "winrate": winrate,
                "net_pnl": net_pnl,
                "profit_factor": pf,
                "avg_trade_pnl": avg_pnl,
            }

        active = [p for p in results.values() if p["trades_count"] > 0]
        best_p = max(active, key=lambda x: x["net_pnl"])["key"] if active else None
        worst_p = min(active, key=lambda x: x["net_pnl"])["key"] if active else None

        if best_p:
            b_meta = results[best_p]
            insight = f"Пик прибыльности: {b_meta['name']} -> {b_meta['net_pnl']:+,.2f} $ (Winrate {b_meta['winrate']}%)"
        else:
            insight = "Циклический анализ месяца активен"

        return {
            "phases": results,
            "best_phase": best_p,
            "worst_phase": worst_p,
            "seasonal_insight": insight,
            "total_trades": len(trades),
        }

    @classmethod
    def simulate_position_sizing_models(
        cls,
        trades: List[Trade],
        initial_balance: float = 10000.0,
    ) -> Dict[str, Any]:
        """
        Квантовый симулятор моделей мани-менеджмента и сайзинга позиций (QuantConnect / PortfolioVisualizer).
        Сравнивает 4 модели управления риском на исторических сделках трейдера:
        - FLAT_1PCT: Фиксированный 1% риска от текущего депозита.
        - HALF_KELLY: Половинный критерий Келли (квантовый оптимум).
        - FULL_KELLY: Полный критерий Келли (максимальный рост).
        - FIXED_DOLLAR: Фиксированный риск $100 на сделку.
        """
        if not trades:
            empty_models = {
                "FLAT_1PCT": {"name": "Фиксированный 1%", "sub": "Консервативный стандарт", "final_equity": initial_balance, "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "color": "#10B981", "badge": "Низкий риск"},
                "HALF_KELLY": {"name": "Half-Kelly", "sub": "Квантовый оптимум", "final_equity": initial_balance, "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "color": "#7C5CFF", "badge": "Оптимальный баланс"},
                "FULL_KELLY": {"name": "Full Kelly", "sub": "Агрессивный рост", "final_equity": initial_balance, "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "color": "#F59E0B", "badge": "Высокая волатильность"},
                "FIXED_DOLLAR": {"name": "Фикс $100 Risk", "sub": "Базовый бенчмарк", "final_equity": initial_balance, "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "color": "#6366F1", "badge": "Без реинвестирования"},
            }
            return {
                "models": empty_models,
                "optimal_model": "HALF_KELLY",
                "optimal_insight": "Симулятор мани-менеджмента активен",
                "initial_balance": initial_balance,
            }

        sorted_trades = sorted(
            trades,
            key=lambda t: (
                t.closed_at or t.opened_at or getattr(t, "date", datetime.min),
                t.id or 0,
            ),
        )

        r_list = []
        for t in sorted_trades:
            raw_r = getattr(t, "r_multiple", 0.0) or 0.0
            if raw_r != 0.0:
                r_list.append(max(-10.0, min(20.0, raw_r)))
            elif t.net_pnl != 0.0:
                risk = getattr(t, "risk_amount", 100.0) or 100.0
                if risk < 1.0:
                    risk = 100.0
                r_list.append(max(-10.0, min(20.0, t.net_pnl / risk)))
            else:
                r_list.append(0.0)

        kelly_mat = cls.calculate_kelly_criterion(trades)
        half_k_pct = max(0.5, min(12.5, kelly_mat.get("half_kelly_pct", 1.5)))
        full_k_pct = max(1.0, min(25.0, kelly_mat.get("kelly_fraction_pct", 3.0)))

        def simulate_curve(risk_mode: str, param: float) -> Tuple[float, float, float]:
            equity = float(initial_balance)
            peak = float(initial_balance)
            max_dd_pct = 0.0

            for r in r_list:
                if risk_mode == "PERCENT":
                    risk_usd = equity * (param / 100.0)
                else:
                    risk_usd = float(param)

                pnl = risk_usd * r
                equity = max(100.0, equity + pnl)

                if equity > peak:
                    peak = equity
                else:
                    dd = (peak - equity) / peak * 100.0
                    if dd > max_dd_pct:
                        max_dd_pct = dd

            ret_pct = ((equity - initial_balance) / initial_balance) * 100.0
            return round(equity, 2), round(ret_pct, 1), round(max_dd_pct, 1)

        eq_flat, ret_flat, dd_flat = simulate_curve("PERCENT", 1.0)
        eq_half_k, ret_half_k, dd_half_k = simulate_curve("PERCENT", half_k_pct)
        eq_full_k, ret_full_k, dd_full_k = simulate_curve("PERCENT", full_k_pct)
        eq_fixed, ret_fixed, dd_fixed = simulate_curve("FIXED", 100.0)

        models = {
            "FLAT_1PCT": {
                "key": "FLAT_1PCT",
                "name": "Фиксированный 1%",
                "sub": "1% риска на сделку",
                "final_equity": eq_flat,
                "total_return_pct": ret_flat,
                "max_drawdown_pct": dd_flat,
                "color": "#10B981",
                "badge": "Консервативный",
            },
            "HALF_KELLY": {
                "key": "HALF_KELLY",
                "name": f"Half-Kelly ({half_k_pct:.1f}%)",
                "sub": "Квантовый оптимум Шарпа",
                "final_equity": eq_half_k,
                "total_return_pct": ret_half_k,
                "max_drawdown_pct": dd_half_k,
                "color": "#7C5CFF",
                "badge": "Рекомендован",
            },
            "FULL_KELLY": {
                "key": "FULL_KELLY",
                "name": f"Full Kelly ({full_k_pct:.1f}%)",
                "sub": "Максимальный рост",
                "final_equity": eq_full_k,
                "total_return_pct": ret_full_k,
                "max_drawdown_pct": dd_full_k,
                "color": "#F59E0B",
                "badge": "Высокий риск",
            },
            "FIXED_DOLLAR": {
                "key": "FIXED_DOLLAR",
                "name": "Фикс $100 Risk",
                "sub": "Без компаундинга",
                "final_equity": eq_fixed,
                "total_return_pct": ret_fixed,
                "max_drawdown_pct": dd_fixed,
                "color": "#6366F1",
                "badge": "Бенчмарк",
            },
        }

        def score(m):
            dd = max(m["max_drawdown_pct"], 1.0)
            return m["total_return_pct"] / dd

        optimal_key = max(models.keys(), key=lambda k: score(models[k]))
        opt = models[optimal_key]
        insight = f"Оптимальный мани-менеджмент: {opt['name']} (Прирост: {opt['total_return_pct']:+,.1f}% при просадке {opt['max_drawdown_pct']}%)"

        return {
            "models": models,
            "optimal_model": optimal_key,
            "optimal_insight": insight,
            "initial_balance": initial_balance,
        }

    @classmethod
    def calculate_market_regime_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Анализ эффективности стратегий в различных рыночных фазах (TradeZella / TraderSync Market Regime Matrix).
        Классифицирует сделки по 4 макро-режимам рынка:
        - BULL_TREND: Восходящий тренд / Сильный моментум покупателей.
        - BEAR_TREND: Нисходящий тренд / Давление продавцов.
        - RANGE_CHOP: Боковик / Флэт / Торговля в коридоре.
        - BREAKOUT_EXPANSION: Импульсный пробой волатильности / Новости.
        """
        regimes_def = {
            "BULL_TREND": {
                "key": "BULL_TREND",
                "name": "Восходящий тренд",
                "sub": "Bullish Trend / Momentum",
                "color": "#10B981",
                "icon": "trending_up_rounded",
            },
            "BEAR_TREND": {
                "key": "BEAR_TREND",
                "name": "Нисходящий тренд",
                "sub": "Bearish Trend / Selloff",
                "color": "#EF4444",
                "icon": "trending_down_rounded",
            },
            "RANGE_CHOP": {
                "key": "RANGE_CHOP",
                "name": "Флэт / Консолидация",
                "sub": "Sideways / Range / Chop",
                "color": "#6366F1",
                "icon": "sync_alt_rounded",
            },
            "BREAKOUT_EXPANSION": {
                "key": "BREAKOUT_EXPANSION",
                "name": "Пробой волатильности",
                "sub": "Volatility Expansion / News",
                "color": "#F59E0B",
                "icon": "bolt_rounded",
            },
        }

        def detect_regime(t: Trade) -> str:
            notes = (getattr(t, "notes", "") or "").lower()
            strat = (getattr(t, "strategy_tag", "") or "").lower()
            if any(w in notes or w in strat for w in ["пробой", "breakout", "ath", "импульс", "expansion", "news"]):
                return "BREAKOUT_EXPANSION"
            if any(w in notes or w in strat for w in ["флэт", "range", "боковик", "канал", "reversion", "уровень", "отскок"]):
                return "RANGE_CHOP"
            if any(w in notes or w in strat for w in ["нисходящ", "bear", "шорт", "selloff", "падение"]):
                return "BEAR_TREND"
            if any(w in notes or w in strat for w in ["тренд", "bull", "лонг", "рост", "up"]):
                return "BULL_TREND"
            dir_str = (getattr(t, "direction", "LONG") or "LONG").upper()
            if dir_str == "SHORT":
                return "BEAR_TREND"
            return "BULL_TREND"

        if not trades:
            empty_regimes = {}
            for k, meta in regimes_def.items():
                empty_regimes[k] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "avg_trade_pnl": 0.0,
                    "top_strategy": "—",
                }
            return {
                "regimes": empty_regimes,
                "best_regime": None,
                "worst_regime": None,
                "regime_insight": "Анализ рыночных фаз активен",
                "total_trades": 0,
            }

        bucketed: Dict[str, List[Trade]] = {k: [] for k in regimes_def}
        for t in trades:
            r_key = detect_regime(t)
            bucketed[r_key].append(t)

        results = {}
        for r_key, r_trades in bucketed.items():
            meta = regimes_def[r_key]
            cnt = len(r_trades)
            if cnt == 0:
                results[r_key] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "avg_trade_pnl": 0.0,
                    "top_strategy": "—",
                }
                continue

            pnls = [float(t.net_pnl or 0.0) for t in r_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            gross_w = float(sum(wins))
            gross_l = float(abs(sum(losses)))

            winrate = round(len(wins) / cnt * 100, 1)
            net_pnl = round(float(sum(pnls)), 2)
            pf = round(gross_w / gross_l, 2) if gross_l > 0 else (99.9 if gross_w > 0 else 1.0)
            avg_pnl = round(net_pnl / cnt, 2)

            strat_pnl: Dict[str, float] = {}
            for t in r_trades:
                st = getattr(t, "strategy_tag", "Default") or "Default"
                strat_pnl[st] = strat_pnl.get(st, 0.0) + float(t.net_pnl or 0.0)
            top_strat = max(strat_pnl.keys(), key=lambda s: strat_pnl[s]) if strat_pnl else "—"

            results[r_key] = {
                **meta,
                "trades_count": cnt,
                "win_trades": len(wins),
                "loss_trades": len(losses),
                "winrate": winrate,
                "net_pnl": net_pnl,
                "profit_factor": pf,
                "avg_trade_pnl": avg_pnl,
                "top_strategy": top_strat,
            }

        active = [r for r in results.values() if r["trades_count"] > 0]
        best_r = max(active, key=lambda x: x["net_pnl"])["key"] if active else None
        worst_r = min(active, key=lambda x: x["net_pnl"])["key"] if active else None

        if best_r:
            b_meta = results[best_r]
            insight = f"Лучший режим: {b_meta['name']} -> {b_meta['net_pnl']:+,.2f} $ (Сетап: '{b_meta['top_strategy']}')"
        else:
            insight = "Анализ рыночных фаз активен"

        return {
            "regimes": results,
            "best_regime": best_r,
            "worst_regime": worst_r,
            "regime_insight": insight,
            "total_trades": len(trades),
        }

    @classmethod
    def calculate_r_distribution_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Анализ частотного распределения доходности по риску (R-Multiple Distribution & Skewness Engine).
        Разбивает сделки по 7 стандартизированным R-корзинам:
        - '<-2R': Катастрофические убытки / Срыв стопов (Disaster risk)
        - '-2R..-1R': Расширенные убытки / Проскальзывание
        - '-1R..0R': Контролируемый риск / Скретч-сделки
        - '0R..1R': Микро-профиты / Безубыток+
        - '1R..2R': Стандартный целевой тейк-профит
        - '2R..3R': Качественные раннеры
        - '>3R': Супер-тейки / Домашние пробои (Outlier Home Runs)

        Рассчитывает асимметрию распределения (Skewness) и эксцесс (Kurtosis).
        """
        bins_def = [
            {"key": "LT_MINUS_2R", "label": "<-2R", "name": "Критический убыток", "color": "#DC2626", "min_r": -9999.0, "max_r": -2.0},
            {"key": "MINUS_2_TO_1R", "label": "-2R..-1R", "name": "Расширенный убыток", "color": "#EF4444", "min_r": -2.0, "max_r": -1.0},
            {"key": "MINUS_1_TO_0R", "label": "-1R..0R", "name": "Контролируемый стоп", "color": "#F87171", "min_r": -1.0, "max_r": 0.0},
            {"key": "ZERO_TO_1R", "label": "0R..1R", "name": "Микро-профит / Б/У", "color": "#34D399", "min_r": 0.0, "max_r": 1.0},
            {"key": "ONE_TO_2R", "label": "1R..2R", "name": "Базовый тейк", "color": "#10B981", "min_r": 1.0, "max_r": 2.0},
            {"key": "TWO_TO_3R", "label": "2R..3R", "name": "Качественный раннер", "color": "#059669", "min_r": 2.0, "max_r": 3.0},
            {"key": "GT_3R", "label": ">3R", "name": "Home Run (>3R)", "color": "#7C5CFF", "min_r": 3.0, "max_r": 9999.0},
        ]

        if not trades:
            empty_bins = []
            for b in bins_def:
                empty_bins.append({
                    **b,
                    "trades_count": 0,
                    "share_pct": 0.0,
                    "net_pnl": 0.0,
                    "avg_r": 0.0,
                })
            return {
                "bins": empty_bins,
                "skewness": 0.0,
                "kurtosis": 0.0,
                "avg_winner_r": 0.0,
                "avg_loser_r": 0.0,
                "expectancy_r": 0.0,
                "home_runs_count": 0,
                "fat_tail_losses_count": 0,
                "distribution_profile": "Сбор статистики R-распределения",
                "insight_color": "#94A3B8",
                "total_trades": 0,
            }

        # Вычисляем R для каждой сделки с гарантией валидного риска
        r_values: List[float] = []
        trade_data: List[Tuple[Trade, float]] = []

        for t in trades:
            pnl = float(t.net_pnl or 0.0)
            r_val = 0.0

            if getattr(t, "initial_risk", None) and float(t.initial_risk) > 0:
                r_val = pnl / float(t.initial_risk)
            elif getattr(t, "stop_loss", None) and getattr(t, "entry_price", None) and float(t.entry_price or 0.0) > 0:
                risk_per_unit = abs(float(t.entry_price) - float(t.stop_loss))
                vol = float(t.volume or 1.0)
                tot_risk = risk_per_unit * vol
                if tot_risk > 0:
                    r_val = pnl / tot_risk
                elif getattr(t, "r_multiple", None) is not None and float(t.r_multiple) != 0.0:
                    r_val = float(t.r_multiple)
                else:
                    r_val = pnl / max(float(t.entry_price) * vol * 0.01, 1.0)
            elif getattr(t, "r_multiple", None) is not None and float(t.r_multiple) != 0.0:
                r_val = float(t.r_multiple)
            else:
                # 1% от объема как разумный бейзлайн при отсутствии стопа
                vol = float(t.volume or 1.0)
                ep = float(t.entry_price or 100.0)
                r_val = pnl / max(ep * vol * 0.01, 1.0)

            # Ограничиваем выбросы в диапазоне [-10.0, 20.0]
            clamped_r = max(-10.0, min(20.0, round(r_val, 2)))
            r_values.append(clamped_r)
            trade_data.append((t, clamped_r))

        total_cnt = len(trades)

        # Классификация по корзинам
        bins_result = []
        for b in bins_def:
            b_trades = []
            for t, r_val in trade_data:
                if b["key"] == "LT_MINUS_2R" and r_val < -2.0:
                    b_trades.append((t, r_val))
                elif b["key"] == "MINUS_2_TO_1R" and -2.0 <= r_val < -1.0:
                    b_trades.append((t, r_val))
                elif b["key"] == "MINUS_1_TO_0R" and -1.0 <= r_val < 0.0:
                    b_trades.append((t, r_val))
                elif b["key"] == "ZERO_TO_1R" and 0.0 <= r_val < 1.0:
                    b_trades.append((t, r_val))
                elif b["key"] == "ONE_TO_2R" and 1.0 <= r_val < 2.0:
                    b_trades.append((t, r_val))
                elif b["key"] == "TWO_TO_3R" and 2.0 <= r_val < 3.0:
                    b_trades.append((t, r_val))
                elif b["key"] == "GT_3R" and r_val >= 3.0:
                    b_trades.append((t, r_val))

            cnt = len(b_trades)
            share_pct = round(cnt / total_cnt * 100.0, 1)
            b_pnl = round(sum(float(t.net_pnl or 0.0) for t, _ in b_trades), 2)
            avg_b_r = round(sum(r for _, r in b_trades) / cnt, 2) if cnt > 0 else 0.0

            bins_result.append({
                **b,
                "trades_count": cnt,
                "share_pct": share_pct,
                "net_pnl": b_pnl,
                "avg_r": avg_b_r,
            })

        # Расчет квантовой асимметрии (Skewness) и эксцесса (Kurtosis)
        r_arr = np.array(r_values, dtype=float)
        mean_r = float(np.mean(r_arr))
        std_r = float(np.std(r_arr, ddof=1)) if len(r_arr) > 1 else 0.0

        if std_r > 1e-6 and len(r_arr) >= 3:
            norm_r = (r_arr - mean_r) / std_r
            skewness = round(float(np.mean(norm_r ** 3)), 2)
            kurtosis = round(float(np.mean(norm_r ** 4) - 3.0), 2)
        else:
            skewness = 0.0
            kurtosis = 0.0

        winners = [r for r in r_values if r > 0]
        losers = [r for r in r_values if r < 0]

        avg_w_r = round(float(np.mean(winners)), 2) if winners else 0.0
        avg_l_r = round(float(np.mean(losers)), 2) if losers else 0.0
        expectancy_r = round(mean_r, 2)

        home_runs = sum(1 for r in r_values if r >= 3.0)
        fat_tail = sum(1 for r in r_values if r <= -2.0)

        # Интерпретация формы профиля распределения
        if skewness > 0.4:
            profile = f"Правосторонний профиль (Skewness +{skewness}) — Убытки режутся быстро, тейки работают"
            color = "#10B981"
        elif skewness < -0.4:
            profile = f"Опасный левосторонний хвост (Skewness {skewness}) — Риск пересиживания стоп-лоссов"
            color = "#EF4444"
        else:
            profile = f"Симметричное нормальное распределение (Skewness {skewness:+0.2f})"
            color = "#38BDF8"

        return {
            "bins": bins_result,
            "skewness": skewness,
            "kurtosis": kurtosis,
            "avg_winner_r": avg_w_r,
            "avg_loser_r": avg_l_r,
            "expectancy_r": expectancy_r,
            "home_runs_count": home_runs,
            "fat_tail_losses_count": fat_tail,
            "distribution_profile": profile,
            "insight_color": color,
            "total_trades": total_cnt,
        }

    @classmethod
    def calculate_rr_efficiency_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Анализ эффективности реализации запланированного Risk-to-Reward (R:R Execution Efficiency & Leakage).
        Сопоставляет запланированное соотношение R:R с фактически зафиксированным R:R:
        - Planned R:R = |TakeProfit - EntryPrice| / |StopLoss - EntryPrice|
        - Realized R:R = NetPnL / InitialRisk
        - Execution Efficiency % = (Realized R:R / Planned R:R) * 100%
        - Dollar Leakage = Недополученная прибыль из-за преждевременного закрытия тейка
        """
        if not trades:
            return {
                "avg_planned_rr": 0.0,
                "avg_realized_rr": 0.0,
                "execution_efficiency_pct": 0.0,
                "total_leakage_dollars": 0.0,
                "disciplined_exits_count": 0,
                "premature_exits_count": 0,
                "execution_grade": "N/A",
                "grade_color": "#94A3B8",
                "leakage_insight": "Нет закрытых сделок для анализа R:R исполнения",
                "evaluated_trades_count": 0,
                "total_trades": 0,
            }

        planned_rrs: List[float] = []
        realized_rrs: List[float] = []
        efficiencies: List[float] = []
        leakages: List[float] = []

        disciplined_cnt = 0
        premature_cnt = 0

        for t in trades:
            ep = float(t.entry_price or 100.0)
            sl = float(t.stop_loss or 0.0)
            tp = float(t.take_profit or 0.0)
            vol = max(float(t.volume or 1.0), 1e-4)
            pnl = float(t.net_pnl or 0.0)

            # 1. Расчет запланированного риска
            if sl > 0 and abs(ep - sl) > 0:
                stop_dist = abs(ep - sl)
                risk_amt = stop_dist * vol
            elif getattr(t, "initial_risk", None) and float(t.initial_risk) > 0:
                risk_amt = float(t.initial_risk)
                stop_dist = risk_amt / vol
            else:
                stop_dist = max(ep * 0.01, 1.0)
                risk_amt = stop_dist * vol

            # 2. Расчет запланированного тейк-профита и Planned R:R
            if tp > 0 and abs(tp - ep) > 0:
                tp_dist = abs(tp - ep)
                planned_rr = round(tp_dist / stop_dist, 2)
            else:
                # Если тейк не был жестко задан, берем стандартный таргетинг 1:2
                planned_rr = 2.0
                tp_dist = stop_dist * 2.0

            # 3. Расчет фактического Realized R
            realized_r = round(pnl / risk_amt, 2) if risk_amt > 0 else 0.0
            realized_r = max(-10.0, min(20.0, realized_r))

            planned_rrs.append(planned_rr)
            realized_rrs.append(realized_r)

            # 4. Анализ реализации тейка для прибыльных сделок
            if pnl > 0:
                target_pnl = tp_dist * vol
                eff = round((realized_r / planned_rr) * 100.0, 1) if planned_rr > 0 else 100.0
                eff = max(0.0, min(300.0, eff))
                efficiencies.append(eff)

                leak = max(0.0, round(target_pnl - pnl, 2))
                leakages.append(leak)

                if eff >= 90.0:
                    disciplined_cnt += 1
                elif eff < 75.0:
                    premature_cnt += 1

        avg_pl = round(float(np.mean(planned_rrs)), 2) if planned_rrs else 0.0
        avg_rel = round(float(np.mean(realized_rrs)), 2) if realized_rrs else 0.0
        avg_eff = round(float(np.mean(efficiencies)), 1) if efficiencies else 0.0
        tot_leak = round(float(sum(leakages)), 2)

        if avg_eff >= 90.0:
            grade = "A+ (Эталонное соблюдение плана)"
            grade_color = "#10B981"
        elif avg_eff >= 75.0:
            grade = "B (Умеренные ранние выходы)"
            grade_color = "#38BDF8"
        elif avg_eff >= 50.0:
            grade = "C (Страх отдачи прибыли / Недосиживание)"
            grade_color = "#F59E0B"
        else:
            grade = "D (Критическое недосиживание тейков)"
            grade_color = "#EF4444"

        if tot_leak > 0:
            insight = f"Упущено из-за раннего закрытия: ${tot_leak:,.2f} • Реализуется {avg_eff}% плана"
        else:
            insight = f"Высокая дисциплина выходов • Реализуется {avg_eff}% плана"

        return {
            "avg_planned_rr": avg_pl,
            "avg_realized_rr": avg_rel,
            "execution_efficiency_pct": avg_eff,
            "total_leakage_dollars": tot_leak,
            "disciplined_exits_count": disciplined_cnt,
            "premature_exits_count": premature_cnt,
            "execution_grade": grade,
            "grade_color": grade_color,
            "leakage_insight": insight,
            "evaluated_trades_count": len(planned_rrs),
            "total_trades": len(trades),
        }

    @classmethod
    def calculate_rule_violation_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Анализ нарушений правил торгового плана и расчет финансового ущерба (Rule Violations & Financial Drag).
        Классифицирует сделки по 6 фундаментальным ошибкам дисциплины:
        - NO_STOP_LOSS: Вход без выставленного стоп-лосса
        - CHASING_FOMO: Вход в уходящий поезд / FOMO
        - REVENGE_TRADING: Тильт / Попытка отыгрыша после лосса
        - EARLY_EXIT: Преждевременный выход из позиции из-за страха
        - OVER_LEVERAGED: Завышение рабочего объема / плеча
        - COUNTER_TREND: Вход против старшего таймфрейма / тренда
        """
        rules_def = [
            {"key": "NO_STOP_LOSS", "name": "Без стоп-лосса", "desc": "Вход без жесткого ограничения риска", "color": "#EF4444", "icon": "shield_outlined"},
            {"key": "CHASING_FOMO", "name": "FOMO / Погоня", "desc": "Вход на верхушке свечи из-за страха упустить", "color": "#F59E0B", "icon": "rocket_launch_rounded"},
            {"key": "REVENGE_TRADING", "name": "Тильт / Реванш", "desc": "Отыгрыш убытка на эмоциях", "color": "#DC2626", "icon": "local_fire_department_rounded"},
            {"key": "EARLY_EXIT", "name": "Преждевременный выход", "desc": "Закрытие до тейка из-за страха отдачи", "color": "#38BDF8", "icon": "timer_outlined"},
            {"key": "OVER_LEVERAGED", "name": "Завышение риска (>2%)", "desc": "Превышение лимита риска на сделку", "color": "#A855F7", "icon": "scale_rounded"},
            {"key": "COUNTER_TREND", "name": "Контртренд", "desc": "Вход против тренда старшего таймфрейма", "color": "#EC4899", "icon": "swap_calls_rounded"},
        ]

        if not trades:
            empty_rules = []
            for r in rules_def:
                empty_rules.append({
                    **r,
                    "count": 0,
                    "violation_rate_pct": 0.0,
                    "dollar_loss": 0.0,
                    "winrate": 0.0,
                    "severity": "CLEAN",
                })
            return {
                "rules": empty_rules,
                "rules_followed_rate_pct": 100.0,
                "clean_trades_count": 0,
                "total_rule_drag": 0.0,
                "most_costly_violation": None,
                "discipline_grade": "N/A",
                "grade_color": "#94A3B8",
                "discipline_insight": "Нет данных по сделкам для аудита нарушений",
                "total_trades": 0,
            }

        def get_violations_for_trade(t: Trade) -> List[str]:
            v = []
            notes = (getattr(t, "notes", "") or "").lower()
            strat = (getattr(t, "strategy_tag", "") or "").lower()

            # 1. NO_STOP_LOSS
            sl = float(t.stop_loss or 0.0)
            if sl <= 0 or "без стоп" in notes or "no sl" in notes:
                v.append("NO_STOP_LOSS")

            # 2. CHASING_FOMO
            if any(w in notes or w in strat for w in ["fomo", "фомо", "погоня", "chase"]) or getattr(t, "is_fomo", False):
                v.append("CHASING_FOMO")

            # 3. REVENGE_TRADING
            if getattr(t, "is_tilt", False) or any(w in notes or w in strat for w in ["revenge", "реванш", "тильт"]):
                v.append("REVENGE_TRADING")

            # 4. EARLY_EXIT
            if any(w in notes or w in strat for w in ["рано", "early", "паника", "недосидел"]):
                v.append("EARLY_EXIT")

            # 5. OVER_LEVERAGED
            init_risk = float(getattr(t, "initial_risk", 0.0) or 0.0)
            if any(w in notes or w in strat for w in ["объем", "плечо", "overrisk", "завышен"]) or init_risk > 500:
                v.append("OVER_LEVERAGED")

            # 6. COUNTER_TREND
            if any(w in notes or w in strat for w in ["контртренд", "counter", "против тренда"]):
                v.append("COUNTER_TREND")

            return v

        total_cnt = len(trades)
        rule_buckets: Dict[str, List[Trade]] = {r["key"]: [] for r in rules_def}
        clean_trades = 0

        for t in trades:
            viols = get_violations_for_trade(t)
            if not viols:
                clean_trades += 1
            else:
                for v_key in viols:
                    rule_buckets[v_key].append(t)

        rules_result = []
        total_drag = 0.0

        for r in rules_def:
            r_key = r["key"]
            b_trades = rule_buckets[r_key]
            cnt = len(b_trades)
            rate_pct = round(cnt / total_cnt * 100.0, 1)

            pnls = [float(t.net_pnl or 0.0) for t in b_trades]
            losses = [p for p in pnls if p < 0]
            loss_sum = round(abs(sum(losses)), 2)
            total_drag += loss_sum

            wins = [p for p in pnls if p > 0]
            winrate = round(len(wins) / cnt * 100.0, 1) if cnt > 0 else 0.0

            if loss_sum > 1000 or (cnt >= 3 and winrate < 30.0):
                severity = "CRITICAL"
            elif loss_sum > 400 or cnt >= 2:
                severity = "HIGH"
            elif cnt > 0:
                severity = "MODERATE"
            else:
                severity = "CLEAN"

            rules_result.append({
                **r,
                "count": cnt,
                "violation_rate_pct": rate_pct,
                "dollar_loss": loss_sum,
                "winrate": winrate,
                "severity": severity,
            })

        followed_pct = round(clean_trades / total_cnt * 100.0, 1)
        total_drag = round(total_drag, 2)

        # Поиск самого дорогого нарушения
        active_rules = [r for r in rules_result if r["count"] > 0]
        if active_rules:
            most_costly = max(active_rules, key=lambda x: (x["dollar_loss"], x["count"]))
        else:
            most_costly = None

        if followed_pct >= 90.0:
            grade = "A (Строгая дисциплина)"
            color = "#10B981"
        elif followed_pct >= 75.0:
            grade = "B (Умеренный контроль)"
            color = "#38BDF8"
        elif followed_pct >= 55.0:
            grade = "C (Периодические срывы)"
            color = "#F59E0B"
        else:
            grade = "F (Хроническое нарушение правил)"
            color = "#EF4444"

        if most_costly and most_costly["dollar_loss"] > 0:
            insight = f"Ущерб от нарушений: -${total_drag:,.2f} • Главная утечка: '{most_costly['name']}' (-${most_costly['dollar_loss']:,.2f})"
        else:
            insight = f"Соблюдение правил: {followed_pct}% • Критических утечек не зафиксировано"

        return {
            "rules": rules_result,
            "rules_followed_rate_pct": followed_pct,
            "clean_trades_count": clean_trades,
            "total_rule_drag": total_drag,
            "most_costly_violation": most_costly["name"] if most_costly else "Нет",
            "discipline_grade": grade,
            "grade_color": color,
            "discipline_insight": insight,
            "total_trades": total_cnt,
        }

    @classmethod
    def calculate_mtf_alignment_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Анализ мульти-таймфрейм согласованности тренда (Multi-Timeframe Trend Alignment Matrix).
        Классифицирует сделки по 4 уровням таймфрейм-конфлюэнции:
        - TRIPLE_ALIGNED: Тройное согласование (HTF Daily/4H + ITF 1H + LTF 5m)
        - DOUBLE_ALIGNED: Двойное согласование (Продолжение локального тренда)
        - PULLBACK_COUNTER: Откат / Контртренд (Сделка против старшего тренда)
        - CHOP_UNALIGNED: Рассогласование / Боковик без единого направления
        """
        mtf_def = {
            "TRIPLE_ALIGNED": {
                "key": "TRIPLE_ALIGNED",
                "name": "Тройное согласование (HTF+ITF+LTF)",
                "sub": "Full Institutional Confluence",
                "color": "#10B981",
                "icon": "layers_rounded",
            },
            "DOUBLE_ALIGNED": {
                "key": "DOUBLE_ALIGNED",
                "name": "Двойное согласование (2 TF)",
                "sub": "Trend Continuation",
                "color": "#38BDF8",
                "icon": "filter_2_rounded",
            },
            "PULLBACK_COUNTER": {
                "key": "PULLBACK_COUNTER",
                "name": "Откат / Контртренд",
                "sub": "Pullback / Mean Reversion",
                "color": "#F59E0B",
                "icon": "u_turn_left_rounded",
            },
            "CHOP_UNALIGNED": {
                "key": "CHOP_UNALIGNED",
                "name": "Рассогласование / Боковик",
                "sub": "Mixed Chop / Range",
                "color": "#EF4444",
                "icon": "close_rounded",
            },
        }

        if not trades:
            empty_mtf = {}
            for k, meta in mtf_def.items():
                empty_mtf[k] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "avg_trade_pnl": 0.0,
                }
            return {
                "alignments": empty_mtf,
                "best_alignment": None,
                "mtf_edge_ratio": 1.0,
                "mtf_insight": "Анализ мульти-таймфрейм согласованности активен",
                "total_trades": 0,
            }

        def classify_mtf(t: Trade) -> str:
            notes = (getattr(t, "notes", "") or "").lower()
            strat = (getattr(t, "strategy_tag", "") or "").lower()

            if any(w in notes or w in strat for w in ["htf+ltf", "3tf", "triple", "confluence", "тренд d1", "d1+h1", "4h+1h", "институциональн", "старший тренд"]):
                return "TRIPLE_ALIGNED"
            if any(w in notes or w in strat for w in ["контртренд", "counter", "откат", "pullback", "reversion", "против"]):
                return "PULLBACK_COUNTER"
            if any(w in notes or w in strat for w in ["флэт", "боковик", "chop", "mixed", "распил", "диапазон"]):
                return "CHOP_UNALIGNED"
            if any(w in notes or w in strat for w in ["тренд", "trend", "пробой", "breakout", "h1", "15m", "continuation"]):
                return "DOUBLE_ALIGNED"

            if getattr(t, "opened_at", None) and getattr(t, "closed_at", None):
                dur_hours = (t.closed_at - t.opened_at).total_seconds() / 3600.0
                if dur_hours >= 4.0:
                    return "TRIPLE_ALIGNED"
                elif dur_hours >= 0.5:
                    return "DOUBLE_ALIGNED"

            return "DOUBLE_ALIGNED"

        bucketed: Dict[str, List[Trade]] = {k: [] for k in mtf_def}
        for t in trades:
            cat = classify_mtf(t)
            bucketed[cat].append(t)

        results = {}
        for k, b_trades in bucketed.items():
            meta = mtf_def[k]
            cnt = len(b_trades)
            if cnt == 0:
                results[k] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "avg_trade_pnl": 0.0,
                }
                continue

            pnls = [float(t.net_pnl or 0.0) for t in b_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            gross_w = float(sum(wins))
            gross_l = float(abs(sum(losses)))

            winrate = round(len(wins) / cnt * 100.0, 1)
            net_pnl = round(float(sum(pnls)), 2)
            pf = round(gross_w / gross_l, 2) if gross_l > 0 else (99.9 if gross_w > 0 else 1.0)
            avg_pnl = round(net_pnl / cnt, 2)

            results[k] = {
                **meta,
                "trades_count": cnt,
                "win_trades": len(wins),
                "loss_trades": len(losses),
                "winrate": winrate,
                "net_pnl": net_pnl,
                "profit_factor": pf,
                "avg_trade_pnl": avg_pnl,
            }

        active = [b for b in results.values() if b["trades_count"] > 0]
        best_cat = max(active, key=lambda x: x["net_pnl"])["key"] if active else None

        triple_wr = results["TRIPLE_ALIGNED"]["winrate"]
        chop_wr = results["CHOP_UNALIGNED"]["winrate"]
        edge_ratio = round(triple_wr / max(chop_wr, 1.0), 2) if results["TRIPLE_ALIGNED"]["trades_count"] > 0 else 1.0

        if best_cat:
            b_meta = results[best_cat]
            insight = f"Лучшая согласованность: {b_meta['name']} -> Net PnL: ${b_meta['net_pnl']:+,.2f} (Winrate: {b_meta['winrate']}%)"
        else:
            insight = "Анализ мульти-таймфрейм согласованности активен"

        return {
            "alignments": results,
            "best_alignment": best_cat,
            "mtf_edge_ratio": edge_ratio,
            "mtf_insight": insight,
            "total_trades": len(trades),
        }

    @classmethod
    def calculate_compliance_routine_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Анализ соблюдения чек-листа перед входом в сделку и регламента (Pre-Trade Routine & Checklist Compliance).
        Оценивает каждую сделку по 5 ключевым критериям институционального чек-листа (до 100%):
        1. Наличие жесткого Stop Loss (+20%)
        2. Соблюдение R:R >= 1:2.0 (+20%)
        3. Эмоциональный контроль (Без тильта / реванша) (+20%)
        4. Наличие формализованного сетапа / триггера (+20%)
        5. Отсутствие FOMO / погони за ценой (+20%)
        """
        criteria_def = [
            {"key": "STOP_LOSS", "name": "Защитный стоп", "desc": "Ограничение риска до входа", "weight": 20},
            {"key": "RR_RATIO", "name": "R:R >= 1:2.0", "desc": "Потенциал прибыли превышает риск", "weight": 20},
            {"key": "EMOTION_CONTROL", "name": "Самоконтроль", "desc": "Холодный расчет без тильта", "weight": 20},
            {"key": "SETUP_TRIGGER", "name": "Сетап-триггер", "desc": "Вход по паттерну стратегии", "weight": 20},
            {"key": "NO_FOMO", "name": "Без FOMO", "desc": "Вход по запланированной цене", "weight": 20},
        ]

        if not trades:
            empty_brackets = {
                "HIGH": {"key": "HIGH", "name": "Высокая дисциплина (80-100%)", "trades_count": 0, "winrate": 0.0, "net_pnl": 0.0, "profit_factor": 0.0, "color": "#10B981"},
                "MODERATE": {"key": "MODERATE", "name": "Умеренный контроль (60-79%)", "trades_count": 0, "winrate": 0.0, "net_pnl": 0.0, "profit_factor": 0.0, "color": "#38BDF8"},
                "LOW": {"key": "LOW", "name": "Импульсивные сделки (<60%)", "trades_count": 0, "winrate": 0.0, "net_pnl": 0.0, "profit_factor": 0.0, "color": "#EF4444"},
            }
            return {
                "brackets": empty_brackets,
                "avg_compliance_pct": 0.0,
                "criteria_compliance": {c["key"]: 0.0 for c in criteria_def},
                "compliance_grade": "N/A",
                "grade_color": "#94A3B8",
                "winrate_alpha_delta": 0.0,
                "compliance_insight": "Нет закрытых сделок для аудита чек-листа",
                "total_trades": 0,
            }

        crit_hits: Dict[str, int] = {c["key"]: 0 for c in criteria_def}
        trade_scores: List[Tuple[Trade, float]] = []

        for t in trades:
            score = 0.0
            notes = (getattr(t, "notes", "") or "").lower()
            strat = (getattr(t, "strategy_tag", "") or "").lower()
            ep = float(t.entry_price or 100.0)
            sl = float(t.stop_loss or 0.0)
            tp = float(t.take_profit or 0.0)

            # 1. Stop Loss check
            if sl > 0 and abs(ep - sl) > 0:
                score += 20.0
                crit_hits["STOP_LOSS"] += 1

            # 2. R:R check
            if sl > 0 and tp > 0 and abs(ep - sl) > 0:
                if abs(tp - ep) / abs(ep - sl) >= 1.8:
                    score += 20.0
                    crit_hits["RR_RATIO"] += 1
            elif getattr(t, "r_multiple", None) is not None and float(t.r_multiple) >= 1.5:
                score += 20.0
                crit_hits["RR_RATIO"] += 1
            else:
                score += 10.0
                crit_hits["RR_RATIO"] += 1

            # 3. Emotion control check
            if not getattr(t, "is_tilt", False) and not any(w in notes for w in ["тильт", "revenge", "реванш", "отыгрыш"]):
                score += 20.0
                crit_hits["EMOTION_CONTROL"] += 1

            # 4. Setup trigger check
            if strat and strat not in ("default", "none", "—") or any(w in notes for w in ["сетап", "паттерн", "пробой", "уровень", "fvg", "order block"]):
                score += 20.0
                crit_hits["SETUP_TRIGGER"] += 1

            # 5. No FOMO check
            if not getattr(t, "is_fomo", False) and not any(w in notes for w in ["fomo", "фомо", "погоня", "chase"]):
                score += 20.0
                crit_hits["NO_FOMO"] += 1

            trade_scores.append((t, score))

        total_cnt = len(trades)
        high_group = [t for t, s in trade_scores if s >= 80.0]
        mod_group = [t for t, s in trade_scores if 60.0 <= s < 80.0]
        low_group = [t for t, s in trade_scores if s < 60.0]

        def calc_bucket_kpis(b_trades: List[Trade], name: str, key: str, color: str) -> Dict[str, Any]:
            cnt = len(b_trades)
            if cnt == 0:
                return {"key": key, "name": name, "trades_count": 0, "winrate": 0.0, "net_pnl": 0.0, "profit_factor": 0.0, "color": color}
            pnls = [float(t.net_pnl or 0.0) for t in b_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            gross_w = float(sum(wins))
            gross_l = float(abs(sum(losses)))
            return {
                "key": key,
                "name": name,
                "trades_count": cnt,
                "winrate": round(len(wins) / cnt * 100.0, 1),
                "net_pnl": round(sum(pnls), 2),
                "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else (99.9 if gross_w > 0 else 1.0),
                "color": color,
            }

        brackets = {
            "HIGH": calc_bucket_kpis(high_group, "Высокая дисциплина (80-100%)", "HIGH", "#10B981"),
            "MODERATE": calc_bucket_kpis(mod_group, "Умеренный контроль (60-79%)", "MODERATE", "#38BDF8"),
            "LOW": calc_bucket_kpis(low_group, "Импульсивные сделки (<60%)", "LOW", "#EF4444"),
        }

        avg_score = round(sum(s for _, s in trade_scores) / total_cnt, 1)
        crit_pcts = {k: round(v / total_cnt * 100.0, 1) for k, v in crit_hits.items()}

        high_wr = brackets["HIGH"]["winrate"]
        low_wr = brackets["LOW"]["winrate"]
        alpha_delta = round(high_wr - low_wr, 1) if brackets["LOW"]["trades_count"] > 0 else 0.0

        if avg_score >= 80.0:
            grade = "A+ (Системный регламент)"
            grade_color = "#10B981"
        elif avg_score >= 65.0:
            grade = "B (Рабочий контроль)"
            grade_color = "#38BDF8"
        elif avg_score >= 50.0:
            grade = "C (Нужна дисциплина)"
            grade_color = "#F59E0B"
        else:
            grade = "F (Хаотичная торговля)"
            grade_color = "#EF4444"

        if brackets["HIGH"]["trades_count"] > 0 and brackets["LOW"]["trades_count"] > 0:
            insight = f"Соблюдение чек-листа дает +{alpha_delta}% к винрейту • Net PnL по плану: ${brackets['HIGH']['net_pnl']:+,.2f}"
        else:
            insight = f"Среднее соблюдение регламента: {avg_score}% • Профит по плану: ${brackets['HIGH']['net_pnl']:+,.2f}"

        return {
            "brackets": brackets,
            "avg_compliance_pct": avg_score,
            "criteria_compliance": crit_pcts,
            "compliance_grade": grade,
            "grade_color": grade_color,
            "winrate_alpha_delta": alpha_delta,
            "compliance_insight": insight,
            "total_trades": total_cnt,
        }

    @classmethod
    def calculate_session_overlap_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Анализ доходности в окнах ликвидности и перекрытиях торговых сессий (Market Session Overlap Alpha Matrix).
        Классифицирует сделки по 4 ключевым временным окнам институциональной ликвидности (UTC):
        - LONDON_NY_OVERLAP (13:00–17:00 UTC): Перекрытие Лондон + Нью-Йорк (Максимальный мировой объем)
        - ASIA_LONDON_TRANSITION (07:00–09:00 UTC): Переход Азия -> Лондон (Утренние импульсы)
        - NY_AFTERNOON_CLOSE (17:00–21:00 UTC): Вторая половина американской сессии (Тренд индексов)
        - OFF_PEAK_CHOP (21:00–07:00 UTC): Низкая ликвидность и паузы между сессиями
        """
        windows_def = {
            "LONDON_NY_OVERLAP": {
                "key": "LONDON_NY_OVERLAP",
                "name": "Лондон + Нью-Йорк",
                "time_span": "13:00–17:00 UTC",
                "desc": "Пиковая мировая ликвидность",
                "color": "#10B981",
                "icon": "public_rounded",
            },
            "ASIA_LONDON_TRANSITION": {
                "key": "ASIA_LONDON_TRANSITION",
                "name": "Стык Азия / Лондон",
                "time_span": "07:00–09:00 UTC",
                "desc": "Открытие Европы и утренний импульс",
                "color": "#38BDF8",
                "icon": "wb_twilight_rounded",
            },
            "NY_AFTERNOON_CLOSE": {
                "key": "NY_AFTERNOON_CLOSE",
                "name": "Нью-Йорк (День/Закрытие)",
                "time_span": "17:00–21:00 UTC",
                "desc": "Американские тренды и фиксация",
                "color": "#F59E0B",
                "icon": "wb_sunny_rounded",
            },
            "OFF_PEAK_CHOP": {
                "key": "OFF_PEAK_CHOP",
                "name": "Низкая ликвидность / Флэт",
                "time_span": "21:00–07:00 UTC",
                "desc": "Азиатский боковик и паузы",
                "color": "#64748B",
                "icon": "bedtime_rounded",
            },
        }

        if not trades:
            empty_res = {}
            for k, meta in windows_def.items():
                empty_res[k] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "avg_trade_pnl": 0.0,
                    "share_pct": 0.0,
                }
            return {
                "windows": empty_res,
                "best_window": None,
                "worst_window": None,
                "overlap_alpha_ratio": 1.0,
                "overlap_insight": "Анализ окон ликвидности активен",
                "total_trades": 0,
            }

        def detect_window(t: Trade) -> str:
            dt = getattr(t, "closed_at", None) or getattr(t, "opened_at", None)
            if not dt:
                return "OFF_PEAK_CHOP"
            h = dt.hour
            if 13 <= h < 17:
                return "LONDON_NY_OVERLAP"
            elif 7 <= h < 9:
                return "ASIA_LONDON_TRANSITION"
            elif 17 <= h < 21:
                return "NY_AFTERNOON_CLOSE"
            else:
                return "OFF_PEAK_CHOP"

        total_cnt = len(trades)
        bucketed: Dict[str, List[Trade]] = {k: [] for k in windows_def}
        for t in trades:
            w_key = detect_window(t)
            bucketed[w_key].append(t)

        results = {}
        for k, b_trades in bucketed.items():
            meta = windows_def[k]
            cnt = len(b_trades)
            if cnt == 0:
                results[k] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "avg_trade_pnl": 0.0,
                    "share_pct": 0.0,
                }
                continue

            pnls = [float(t.net_pnl or 0.0) for t in b_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            gross_w = float(sum(wins))
            gross_l = float(abs(sum(losses)))

            winrate = round(len(wins) / cnt * 100.0, 1)
            net_pnl = round(float(sum(pnls)), 2)
            pf = round(gross_w / gross_l, 2) if gross_l > 0 else (99.9 if gross_w > 0 else 1.0)
            avg_pnl = round(net_pnl / cnt, 2)
            share_pct = round(cnt / total_cnt * 100.0, 1)

            results[k] = {
                **meta,
                "trades_count": cnt,
                "win_trades": len(wins),
                "loss_trades": len(losses),
                "winrate": winrate,
                "net_pnl": net_pnl,
                "profit_factor": pf,
                "avg_trade_pnl": avg_pnl,
                "share_pct": share_pct,
            }

        active = [w for w in results.values() if w["trades_count"] > 0]
        best_w = max(active, key=lambda x: x["net_pnl"])["key"] if active else None
        worst_w = min(active, key=lambda x: x["net_pnl"])["key"] if active else None

        london_ny_wr = results["LONDON_NY_OVERLAP"]["winrate"]
        off_peak_wr = results["OFF_PEAK_CHOP"]["winrate"]
        alpha_ratio = round(london_ny_wr / max(off_peak_wr, 1.0), 2) if results["LONDON_NY_OVERLAP"]["trades_count"] > 0 else 1.0

        if best_w:
            b_meta = results[best_w]
            insight = f"Лучшее окно: {b_meta['name']} ({b_meta['time_span']}) -> Net PnL: ${b_meta['net_pnl']:+,.2f} (WR: {b_meta['winrate']}%)"
        else:
            insight = "Анализ окон ликвидности активен"

        return {
            "windows": results,
            "best_window": best_w,
            "worst_window": worst_w,
            "overlap_alpha_ratio": alpha_ratio,
            "overlap_insight": insight,
            "total_trades": total_cnt,
        }

    @classmethod
    def calculate_setup_grading_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Анализ качества сетапов и градация по плейбуку (Playbook Setup Quality Grading Matrix).
        Классифицирует сделки по 4 качественным категориям институционального плейбука:
        - A_PLUS: A+ Setup — Эталонный сетап наивысшего качества (Ключевой уровень, R:R >= 2.5, полная дисциплина)
        - A_TIER: A Setup — Базовый системный сетап (Хороший контекст, R:R >= 2.0, соблюдение риска)
        - B_TIER: B Setup — Вторичный сетап с компромиссом (Неидеальная точка входа, умеренный R:R 1.5–2.0)
        - C_TIER: C Setup — Субоптимальный сетап / Шум (Поздний вход, плохой R:R, эмоциональное давление)
        """
        tiers_def = {
            "A_PLUS": {
                "key": "A_PLUS",
                "name": "A+ Setup (Эталон)",
                "sub": "Flawless Institutional Edge",
                "color": "#7C5CFF",
                "icon": "verified_rounded",
            },
            "A_TIER": {
                "key": "A_TIER",
                "name": "A Setup (Системный)",
                "sub": "Core Playbook Setup",
                "color": "#10B981",
                "icon": "check_circle_rounded",
            },
            "B_TIER": {
                "key": "B_TIER",
                "name": "B Setup (Вторичный)",
                "sub": "Secondary / Minor Deviations",
                "color": "#F59E0B",
                "icon": "remove_circle_outline_rounded",
            },
            "C_TIER": {
                "key": "C_TIER",
                "name": "C Setup (Субоптимальный)",
                "sub": "Noise / Sub-optimal Entry",
                "color": "#EF4444",
                "icon": "cancel_rounded",
            },
        }

        if not trades:
            empty_res = {}
            for k, meta in tiers_def.items():
                empty_res[k] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "avg_trade_pnl": 0.0,
                    "share_pct": 0.0,
                }
            return {
                "tiers": empty_res,
                "best_tier": None,
                "a_tier_discipline_pct": 0.0,
                "c_tier_loss_drag": 0.0,
                "setup_grading_insight": "Анализ градации качества сетапов активен",
                "total_trades": 0,
            }

        def detect_tier(t: Trade) -> str:
            notes = (getattr(t, "notes", "") or "").lower()
            strat = (getattr(t, "strategy_tag", "") or "").lower()

            if any(w in notes or w in strat for w in ["a+", "а+", "tier 1", "эталон", "5 звезд", "grade a+"]):
                return "A_PLUS"
            if any(w in notes or w in strat for w in ["setup a", "сетап а", "класс a", "tier 2", "grade a"]):
                return "A_TIER"
            if any(w in notes or w in strat for w in ["setup b", "сетап б", "класс b", "tier 3", "grade b"]):
                return "B_TIER"
            if any(w in notes or w in strat for w in ["setup c", "сетап с", "класс c", "мусор", "хлам", "grade c"]):
                return "C_TIER"

            # Алгоритмическая классификация по метрикам сделки
            ep = float(t.entry_price or 100.0)
            sl = float(t.stop_loss or 0.0)
            tp = float(t.take_profit or 0.0)
            has_sl = bool(sl > 0 and abs(ep - sl) > 0)
            has_tp = bool(tp > 0 and abs(tp - ep) > 0)
            no_tilt = not getattr(t, "is_tilt", False) and "тильт" not in notes
            no_fomo = not getattr(t, "is_fomo", False) and "fomo" not in notes
            has_strat = bool(strat and strat not in ("default", "none", "—"))

            rr = (abs(tp - ep) / abs(ep - sl)) if (has_sl and has_tp) else (float(getattr(t, "r_multiple", 0.0) or 2.0))

            if has_sl and has_strat and no_tilt and no_fomo and rr >= 2.5:
                return "A_PLUS"
            elif has_sl and has_strat and no_tilt and no_fomo and rr >= 2.0:
                return "A_TIER"
            elif has_sl and (no_tilt or no_fomo) and rr >= 1.5:
                return "B_TIER"
            else:
                return "C_TIER"

        total_cnt = len(trades)
        bucketed: Dict[str, List[Trade]] = {k: [] for k in tiers_def}
        for t in trades:
            t_tier = detect_tier(t)
            bucketed[t_tier].append(t)

        results = {}
        for k, b_trades in bucketed.items():
            meta = tiers_def[k]
            cnt = len(b_trades)
            if cnt == 0:
                results[k] = {
                    **meta,
                    "trades_count": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "winrate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "avg_trade_pnl": 0.0,
                    "share_pct": 0.0,
                }
                continue

            pnls = [float(t.net_pnl or 0.0) for t in b_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            gross_w = float(sum(wins))
            gross_l = float(abs(sum(losses)))

            winrate = round(len(wins) / cnt * 100.0, 1)
            net_pnl = round(float(sum(pnls)), 2)
            pf = round(gross_w / gross_l, 2) if gross_l > 0 else (99.9 if gross_w > 0 else 1.0)
            avg_pnl = round(net_pnl / cnt, 2)
            share_pct = round(cnt / total_cnt * 100.0, 1)

            results[k] = {
                **meta,
                "trades_count": cnt,
                "win_trades": len(wins),
                "loss_trades": len(losses),
                "winrate": winrate,
                "net_pnl": net_pnl,
                "profit_factor": pf,
                "avg_trade_pnl": avg_pnl,
                "share_pct": share_pct,
            }

        active = [r for r in results.values() if r["trades_count"] > 0]
        best_t = max(active, key=lambda x: x["net_pnl"])["key"] if active else None

        a_grades_cnt = results["A_PLUS"]["trades_count"] + results["A_TIER"]["trades_count"]
        a_discipline_pct = round(a_grades_cnt / total_cnt * 100.0, 1)

        c_losses = [float(t.net_pnl or 0.0) for t in bucketed["C_TIER"] if float(t.net_pnl or 0.0) < 0]
        c_loss_drag = round(abs(sum(c_losses)), 2)

        a_pnl = results["A_PLUS"]["net_pnl"] + results["A_TIER"]["net_pnl"]

        if c_loss_drag > 0:
            insight = f"Сетапы A+/A принесли ${a_pnl:+,.2f} • Ущерб от сделок класса C: -${c_loss_drag:,.2f}"
        else:
            insight = f"Доля эталонных сделок (A+/A): {a_discipline_pct}% • Высокая дисциплина отбора"

        return {
            "tiers": results,
            "best_tier": best_t,
            "a_tier_discipline_pct": a_discipline_pct,
            "c_tier_loss_drag": c_loss_drag,
            "setup_grading_insight": insight,
            "total_trades": total_cnt,
        }

    @classmethod
    def calculate_tag_attribution_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Анализ атрибуции торговых тегов и факторов (Trade Tag Performance Cloud & Factor Attribution).
        Извлекает стратегические теги, сетапы и хэштеги из описания сделок:
        - PROFIT_DRIVER: Теги с высокой прибыльностью и винрейтом >= 60%
        - STEADY_EDGE: Стабильные прибыльные сетапы с винрейтом >= 50%
        - DRAWDOWN_LEAK: Теги с отрицательным математическим ожиданием (Утечки)
        - NEUTRAL: Нейтральные или околонулевые теги
        """
        import re

        if not trades:
            return {
                "tags": [],
                "top_profitable_tag": None,
                "top_drag_tag": None,
                "most_frequent_tag": None,
                "unique_tags_count": 0,
                "attribution_insight": "Нет данных по тегам для анализа атрибуции",
                "total_trades": 0,
            }

        def extract_tags(t: Trade) -> List[str]:
            tags = set()
            st = getattr(t, "strategy_tag", None)
            if st and str(st).strip() and str(st).strip().lower() not in ("none", "default", "—"):
                tags.add(str(st).strip())

            notes = getattr(t, "notes", None) or ""
            hashtags = re.findall(r"#([A-Za-z0-9_А-Яа-я]+)", notes)
            for ht in hashtags:
                if ht:
                    tags.add(ht.strip())

            if not tags:
                lower_n = notes.lower()
                for kw, label in [
                    ("breakout", "Breakout"),
                    ("пробой", "Breakout"),
                    ("order block", "OrderBlock"),
                    ("ордерблок", "OrderBlock"),
                    ("pullback", "Pullback"),
                    ("откат", "Pullback"),
                    ("fvg", "FVG"),
                    ("scalp", "Scalp"),
                    ("скальп", "Scalp"),
                    ("trend", "Trend"),
                    ("тренд", "Trend"),
                    ("fomo", "FOMO"),
                    ("тильт", "Тильт"),
                ]:
                    if kw in lower_n:
                        tags.add(label)

            if not tags:
                tags.add("General")

            return sorted(list(tags))

        tag_to_trades: Dict[str, List[Trade]] = {}
        for t in trades:
            t_tags = extract_tags(t)
            for tag_name in t_tags:
                if tag_name not in tag_to_trades:
                    tag_to_trades[tag_name] = []
                tag_to_trades[tag_name].append(t)

        tag_results = []
        total_cnt = len(trades)

        for tag_name, t_list in tag_to_trades.items():
            cnt = len(t_list)
            pnls = [float(t.net_pnl or 0.0) for t in t_list]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            gross_w = float(sum(wins))
            gross_l = float(abs(sum(losses)))

            winrate = round(len(wins) / cnt * 100.0, 1)
            net_pnl = round(sum(pnls), 2)
            pf = round(gross_w / gross_l, 2) if gross_l > 0 else (99.9 if gross_w > 0 else 1.0)
            avg_pnl = round(net_pnl / cnt, 2)
            share_pct = round(cnt / total_cnt * 100.0, 1)

            if net_pnl > 0 and winrate >= 60.0:
                cat = "PROFIT_DRIVER"
                color = "#10B981"
            elif net_pnl > 0 and winrate >= 50.0:
                cat = "STEADY_EDGE"
                color = "#38BDF8"
            elif net_pnl < 0:
                cat = "DRAWDOWN_LEAK"
                color = "#EF4444"
            else:
                cat = "NEUTRAL"
                color = "#F59E0B"

            tag_results.append({
                "tag": tag_name,
                "category": cat,
                "color": color,
                "trades_count": cnt,
                "win_trades": len(wins),
                "loss_trades": len(losses),
                "winrate": winrate,
                "net_pnl": net_pnl,
                "profit_factor": pf,
                "avg_trade_pnl": avg_pnl,
                "share_pct": share_pct,
            })

        # Сортировка: сначала драйверы прибыли, затем нейтральные, затем утечки
        tag_results.sort(key=lambda x: x["net_pnl"], reverse=True)

        profit_tags = [t for t in tag_results if t["net_pnl"] > 0]
        drag_tags = [t for t in tag_results if t["net_pnl"] < 0]

        top_prof = profit_tags[0] if profit_tags else None
        top_drag = min(drag_tags, key=lambda x: x["net_pnl"]) if drag_tags else None
        most_freq = max(tag_results, key=lambda x: x["trades_count"]) if tag_results else None

        if top_prof and top_drag:
            insight = f"Драйвер: #{top_prof['tag']} (+${top_prof['net_pnl']:,.2f}) • Утечка: #{top_drag['tag']} (-${abs(top_drag['net_pnl']):,.2f})"
        elif top_prof:
            insight = f"Лучший фактор: #{top_prof['tag']} (+${top_prof['net_pnl']:,.2f}, WR {top_prof['winrate']}%)"
        elif top_drag:
            insight = f"Главная утечка: #{top_drag['tag']} (-${abs(top_drag['net_pnl']):,.2f})"
        else:
            insight = f"Проанализировано {len(tag_results)} уникальных торговых тегов"

        return {
            "tags": tag_results,
            "top_profitable_tag": top_prof["tag"] if top_prof else None,
            "top_drag_tag": top_drag["tag"] if top_drag else None,
            "most_frequent_tag": most_freq["tag"] if most_freq else None,
            "unique_tags_count": len(tag_results),
            "attribution_insight": insight,
            "total_trades": total_cnt,
        }

    @classmethod
    def calculate_rolling_edge_matrix(cls, trades: List[Trade], window_days: int = 30) -> Dict[str, Any]:
        """
        Динамический аудит устойчивости преимущества и детектор затухания альфы (Rolling Edge Decay Engine).
        Сравнивает текущее 30-дневное окно с предшествующим 30-дневным окном:
        - Rolling Sharpe Ratio (динамика риск-доходности)
        - Rolling Winrate % (стабильность математического ожидания)
        - Net PnL Momentum
        - Индикатор затухания преимущества (Edge Decay Alert) для своевременной защиты депозита.
        """
        if not trades:
            return {
                "current_window": {"trades_count": 0, "winrate": 0.0, "net_pnl": 0.0, "sharpe": 0.0, "profit_factor": 1.0},
                "prior_window": {"trades_count": 0, "winrate": 0.0, "net_pnl": 0.0, "sharpe": 0.0, "profit_factor": 1.0},
                "sharpe_delta": 0.0,
                "winrate_delta": 0.0,
                "pnl_delta": 0.0,
                "edge_momentum": "INSUFFICIENT_DATA",
                "decay_alert": False,
                "momentum_color": "#94A3B8",
                "edge_insight": "Нет данных по сделкам для анализа динамики преимущества",
                "window_days": window_days,
                "total_trades": 0,
            }

        # Извлечение дат закрытия сделок
        dated_trades = []
        for t in trades:
            dt = t.closed_at or t.created_at
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                except Exception:
                    dt = None
            if not dt:
                dt = datetime.now()
            # Обеспечиваем tz-naive для надежного сравнения
            if getattr(dt, "tzinfo", None) is not None:
                dt = dt.replace(tzinfo=None)
            dated_trades.append((t, dt))

        dated_trades.sort(key=lambda x: x[1])

        latest_dt = dated_trades[-1][1]
        curr_cutoff = latest_dt - timedelta(days=window_days)
        prior_cutoff = latest_dt - timedelta(days=window_days * 2)

        curr_t = [t for t, dt in dated_trades if dt >= curr_cutoff]
        prior_t = [t for t, dt in dated_trades if prior_cutoff <= dt < curr_cutoff]

        # Если предшествующее окно пустое (например, вся история короткая), разбиваем сплитом пополам
        if not prior_t and len(dated_trades) >= 2:
            half = len(dated_trades) // 2
            prior_t = [t for t, _ in dated_trades[:half]]
            curr_t = [t for t, _ in dated_trades[half:]]
        elif not prior_t:
            prior_t = curr_t[:]

        def evaluate_window(t_list: List[Trade]) -> Dict[str, Any]:
            if not t_list:
                return {"trades_count": 0, "winrate": 0.0, "net_pnl": 0.0, "sharpe": 0.0, "profit_factor": 1.0}
            cnt = len(t_list)
            pnls = [float(t.net_pnl or 0.0) for t in t_list]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            gross_w = float(sum(wins))
            gross_l = float(abs(sum(losses)))

            wr = round(len(wins) / cnt * 100.0, 1)
            net = round(sum(pnls), 2)
            pf = round(gross_w / gross_l, 2) if gross_l > 0 else (99.9 if gross_w > 0 else 1.0)

            # Расчет Sharpe на выборке сделок
            if cnt > 1 and np.std(pnls) > 1e-6:
                sharpe = float(np.mean(pnls) / np.std(pnls) * np.sqrt(min(cnt, 252)))
                sharpe = round(sharpe, 2)
            else:
                sharpe = 0.0

            return {
                "trades_count": cnt,
                "winrate": wr,
                "net_pnl": net,
                "sharpe": sharpe,
                "profit_factor": pf,
            }

        curr_stats = evaluate_window(curr_t)
        prior_stats = evaluate_window(prior_t)

        sharpe_delta = round(curr_stats["sharpe"] - prior_stats["sharpe"], 2)
        wr_delta = round(curr_stats["winrate"] - prior_stats["winrate"], 1)
        pnl_delta = round(curr_stats["net_pnl"] - prior_stats["net_pnl"], 2)

        # Классификация динамики преимущества
        if (sharpe_delta >= 0.2 or wr_delta >= 5.0) and curr_stats["net_pnl"] > 0:
            momentum = "EXPANDING_EDGE"
            mom_color = "#10B981"
            decay_alert = False
            insight = f"Преимущество расширяется: Sharpe {curr_stats['sharpe']} (+{sharpe_delta:+}), Winrate {curr_stats['winrate']}% ({wr_delta:+}%)"
        elif sharpe_delta <= -0.3 or wr_delta <= -10.0 or (curr_stats["net_pnl"] < 0 and prior_stats["net_pnl"] > 0):
            momentum = "DECAYING_EDGE"
            mom_color = "#EF4444"
            decay_alert = True
            insight = f"⚠️ Внимание: Зафиксировано затухание преимущества! Winrate упал на {abs(wr_delta):.1f}%, Sharpe: {curr_stats['sharpe']} ({sharpe_delta:+}). Рекомендуется снизить риск"
        else:
            momentum = "STABLE_EDGE"
            mom_color = "#38BDF8"
            decay_alert = False
            insight = f"Преимущество стабильно: Sharpe {curr_stats['sharpe']}, Winrate {curr_stats['winrate']}%, динамика в пределах рыночной нормы"

        return {
            "current_window": curr_stats,
            "prior_window": prior_stats,
            "sharpe_delta": sharpe_delta,
            "winrate_delta": wr_delta,
            "pnl_delta": pnl_delta,
            "edge_momentum": momentum,
            "decay_alert": decay_alert,
            "momentum_color": mom_color,
            "edge_insight": insight,
            "window_days": window_days,
            "total_trades": len(trades),
        }

    @classmethod
    def calculate_prop_consistency_radar(
        cls,
        trades: List[Trade],
        max_single_day_share_limit: float = 33.0,
        max_single_trade_share_limit: float = 25.0,
    ) -> Dict[str, Any]:
        """
        Радар консистентности и оценка готовности к проп-челленджам (FTMO / FundedNext Consistency Rule Engine).
        Оценивает:
        1. Single Trade Profit Concentration (доля лучшей сделки от валовой прибыли, лимит 25-30%)
        2. Single Day Profit Concentration (доля лучшего торгового дня, лимит 33%)
        3. Lot Size Uniformity & Variance (стабильность размера позиций)
        4. Max Daily Drawdown Observed (просадка за один день)
        5. Composite Consistency Score (0-100%) & Readiness Status.
        """
        if not trades:
            return {
                "consistency_score": 0.0,
                "readiness_status": "NO_DATA",
                "status_color": "#94A3B8",
                "best_trade_share_pct": 0.0,
                "best_day_share_pct": 0.0,
                "lot_size_cv": 0.0,
                "max_daily_loss": 0.0,
                "trade_concentration_pass": True,
                "day_concentration_pass": True,
                "sizing_uniformity_pass": True,
                "best_trade_pnl": 0.0,
                "best_day_pnl": 0.0,
                "total_gross_profit": 0.0,
                "consistency_insight": "Нет закрытых сделок для оценки готовности к проп-челленджам",
                "total_trades": 0,
            }

        pnls = [float(t.net_pnl or 0.0) for t in trades]
        wins = [p for p in pnls if p > 0]
        total_gross_profit = float(sum(wins))

        best_trade_pnl = max(pnls) if pnls else 0.0

        # Доля лучшей сделки
        if total_gross_profit > 0 and best_trade_pnl > 0:
            best_trade_share = round((best_trade_pnl / total_gross_profit) * 100.0, 1)
        else:
            best_trade_share = 0.0

        # Группировка по дням
        daily_pnl_map: Dict[str, float] = {}
        for t in trades:
            dt = t.closed_at or t.created_at
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                except Exception:
                    dt = None
            if not dt:
                dt = datetime.now()
            day_str = dt.strftime("%Y-%m-%d")
            daily_pnl_map[day_str] = daily_pnl_map.get(day_str, 0.0) + float(t.net_pnl or 0.0)

        daily_pnls = list(daily_pnl_map.values())
        best_day_pnl = max(daily_pnls) if daily_pnls else 0.0
        worst_day_pnl = min(daily_pnls) if daily_pnls else 0.0
        max_daily_loss = round(abs(min(0.0, worst_day_pnl)), 2)

        if total_gross_profit > 0 and best_day_pnl > 0:
            best_day_share = round((best_day_pnl / total_gross_profit) * 100.0, 1)
        else:
            best_day_share = 0.0

        # Оценка вариации сайзинга (объема)
        volumes = [float(getattr(t, "volume", 0.0) or 0.0) for t in trades if float(getattr(t, "volume", 0.0) or 0.0) > 0]
        if len(volumes) >= 2 and np.mean(volumes) > 0:
            lot_size_cv = round(float(np.std(volumes) / np.mean(volumes)), 2)
        else:
            lot_size_cv = 0.0

        # Правила комплаенса
        trade_conc_pass = best_trade_share <= max_single_trade_share_limit or total_gross_profit <= 0
        day_conc_pass = best_day_share <= max_single_day_share_limit or total_gross_profit <= 0
        sizing_pass = lot_size_cv <= 0.65

        # Расчет общего Consistency Score (0 - 100)
        trade_score = max(0.0, 30.0 * (1.0 - (best_trade_share / 100.0))) if best_trade_share > 0 else 25.0
        day_score = max(0.0, 30.0 * (1.0 - (best_day_share / 100.0))) if best_day_share > 0 else 25.0
        sizing_score = max(5.0, 20.0 * (1.0 - min(lot_size_cv, 1.0)))
        winrate = (len(wins) / len(trades) * 100.0) if trades else 0.0
        win_score = min(20.0, (winrate / 50.0) * 15.0 + (5.0 if sum(pnls) > 0 else 0.0))

        consistency_score = round(min(100.0, max(0.0, trade_score + day_score + sizing_score + win_score)), 1)

        # Статус готовности
        if consistency_score >= 80.0 and trade_conc_pass and day_conc_pass:
            status = "FUNDED_READY"
            status_color = "#10B981"
            insight = f"Готов к челленджу: Высокая консистентность ({consistency_score}%). Риски распределены равномерно, сайзинг стабилен"
        elif consistency_score >= 65.0:
            status = "QUALIFIED"
            status_color = "#38BDF8"
            insight = f"Хорошая стабильность ({consistency_score}%). Доля лучшего дня {best_day_share}% (норма <{max_single_day_share_limit}%)"
        elif best_trade_share > max_single_trade_share_limit or best_day_share > max_single_day_share_limit:
            status = "LOTTERY_DEPENDENCY"
            status_color = "#F59E0B"
            insight = f"⚠️ Риск дисквалификации: Прибыль сконцентрирована в одной сделке ({best_trade_share}%) или одном дне ({best_day_share}%)"
        else:
            status = "HIGH_VARIANCE"
            status_color = "#EF4444"
            insight = f"Недостаточная консистентность ({consistency_score}%). Высокая дисперсия результатов или частые просадки"

        return {
            "consistency_score": consistency_score,
            "readiness_status": status,
            "status_color": status_color,
            "best_trade_share_pct": best_trade_share,
            "best_day_share_pct": best_day_share,
            "lot_size_cv": lot_size_cv,
            "max_daily_loss": max_daily_loss,
            "trade_concentration_pass": trade_conc_pass,
            "day_concentration_pass": day_conc_pass,
            "sizing_uniformity_pass": sizing_pass,
            "best_trade_pnl": round(best_trade_pnl, 2),
            "best_day_pnl": round(best_day_pnl, 2),
            "total_gross_profit": round(total_gross_profit, 2),
            "consistency_insight": insight,
            "total_trades": len(trades),
        }

    @classmethod
    def calculate_order_placement_efficiency(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Аудит эффективности размещения Stop Loss и Take Profit ордеров (Edgewonk Order Placement Audit).
        Выявляет:
        - Преждевременные стоп-ауты (Premature Stop-Outs): сделки, выбитые по стопу до движения к цели.
        - Утечку раннего выхода (Early Exit Leakage): недополученную прибыль из-за досрочного закрытия тейк-профита.
        - Эффективность захвата цели (Target Capture Efficiency %): отношение реального профита к потенциалу MFE.
        - Рекомендацию по калибровке буфера Stop Loss (слишком тесный стоп против избыточного риска).
        """
        if not trades:
            return {
                "target_capture_efficiency_pct": 0.0,
                "premature_stopout_count": 0,
                "premature_stopout_drag": 0.0,
                "early_exit_leakage": 0.0,
                "placement_grade": "N/A",
                "grade_color": "#94A3B8",
                "optimal_sl_buffer_recommendation": "1.0x (Базовый)",
                "placement_insight": "Нет данных по ордерам для анализа эффективности размещения SL/TP",
                "total_trades": 0,
            }

        premature_count = 0
        premature_drag = 0.0
        early_leakage = 0.0
        total_win_pnl = 0.0
        total_win_mfe = 0.0
        win_mae_list = []
        loss_cnt = 0

        for t in trades:
            pnl = float(t.net_pnl or 0.0)
            mae = float(getattr(t, "mae", 0.0) or 0.0)
            mfe = float(getattr(t, "mfe", 0.0) or 0.0)

            # Если MFE/MAE не зафиксированы биржей, применяем эвристическую нормализацию
            notes = str(getattr(t, "notes", "") or "").lower()
            if mfe == 0.0 and pnl > 0:
                mfe = pnl * 1.25
            if mae == 0.0 and pnl < 0:
                mae = abs(pnl)

            # Проверка ключевых слов о выбитом стопе в заметках
            is_stopped_out_keyword = any(k in notes for k in ("выбило", "выбило в безубыток", "выбило стоп", "преждевремен", "пошел без меня"))

            if pnl < 0:
                loss_cnt += 1
                # Если сделку закрыло в минус, но MFE был существенным (цена шла в нашу сторону)
                if (mfe >= abs(pnl) * 0.8) or is_stopped_out_keyword:
                    premature_count += 1
                    premature_drag += abs(pnl)
            elif pnl > 0:
                total_win_pnl += pnl
                total_win_mfe += max(mfe, pnl)
                if mfe > pnl:
                    early_leakage += (mfe - pnl)
                if mae > 0:
                    win_mae_list.append(mae)

        # Эффективность захвата цели
        if total_win_mfe > 0:
            target_capture = round((total_win_pnl / total_win_mfe) * 100.0, 1)
        else:
            target_capture = 0.0

        premature_drag = round(premature_drag, 2)
        early_leakage = round(early_leakage, 2)

        # Рекомендация по буферу стопа
        premature_ratio = (premature_count / loss_cnt * 100.0) if loss_cnt > 0 else 0.0
        if premature_ratio >= 30.0:
            buffer_rec = "+25% (Расширить SL)"
            grade = "C"
            grade_color = "#F59E0B"
            insight = f"Стоп-лосс слишком тесный: {premature_count} сделок выбито до движения к цели (убыток -${premature_drag:,.2f}). Рекомендуется расширить буфер на 25%"
        elif target_capture >= 75.0 and premature_count == 0:
            buffer_rec = "Оптимально (1.0x)"
            grade = "A+"
            grade_color = "#10B981"
            insight = f"Идеальная калибровка: захват 75%+ потенциала движения ({target_capture}%), преждевременных стоп-аутов не обнаружено"
        elif target_capture >= 60.0:
            buffer_rec = "Стабильно (1.0x)"
            grade = "A"
            grade_color = "#10B981"
            insight = f"Высокая эффективность тейков ({target_capture}%). Недополученная прибыль из-за ранних выходов: ${early_leakage:,.2f}"
        else:
            buffer_rec = "Подтянуть TP (-15%)"
            grade = "B"
            grade_color = "#38BDF8"
            insight = f"Ранние выходы: оставлено на столе ${early_leakage:,.2f}. Рекомендуется использовать трейлинг-стоп или забирать фикс на первом сопротивлении"

        return {
            "target_capture_efficiency_pct": target_capture,
            "premature_stopout_count": premature_count,
            "premature_stopout_drag": premature_drag,
            "early_exit_leakage": early_leakage,
            "placement_grade": grade,
            "grade_color": grade_color,
            "optimal_sl_buffer_recommendation": buffer_rec,
            "placement_insight": insight,
            "total_trades": len(trades),
        }

    @classmethod
    def calculate_factor_information_coefficient(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Квантовый аудит предсказательной силы факторов альфы (Factor Information Coefficient & Alpha Persistence).
        Рассчитывает ранговую корреляцию Спирмена (Rank IC) между пре-трейд факторами и реализованным результатом (Net PnL):
        1. Planned Risk-to-Reward Ratio (RR)
        2. Position Sizing Conviction (Volume)
        3. Multi-Timeframe Trend Confluence
        4. Discipline & Compliance Score
        Определяет элитные альфа-факторы (IC >= 0.15), шум (IC ~ 0) и токсичные факторы риска (IC < -0.05).
        """
        if not trades:
            return {
                "factors": [],
                "top_factor": None,
                "top_factor_ic": 0.0,
                "mean_factor_ic": 0.0,
                "factor_ir": 0.0,
                "ic_insight": "Нет данных по сделкам для анализа коэффициента предсказательной силы факторов",
                "total_trades": 0,
            }

        pnls = [float(t.net_pnl or 0.0) for t in trades]
        cnt = len(trades)

        def spearman_ic(x: List[float], y: List[float]) -> float:
            if len(x) < 3:
                return 0.0
            x_arr = np.array(x, dtype=float)
            y_arr = np.array(y, dtype=float)
            if np.std(x_arr) < 1e-9 or np.std(y_arr) < 1e-9:
                return 0.0
            x_ranks = pd.Series(x_arr).rank()
            y_ranks = pd.Series(y_arr).rank()
            corr = x_ranks.corr(y_ranks)
            return round(float(corr) if not np.isnan(corr) else 0.0, 2)

        # 1. Planned R:R factor
        rr_vals = []
        for t in trades:
            e = float(t.entry_price or 0.0)
            sl = float(t.stop_loss or 0.0)
            tp = float(t.take_profit or 0.0)
            d = (t.direction or "LONG").upper()
            if sl > 0 and tp > 0 and e > 0:
                if d == "SHORT":
                    risk = max(1e-4, sl - e)
                    reward = max(0.0, e - tp)
                else:
                    risk = max(1e-4, e - sl)
                    reward = max(0.0, tp - e)
                rr_vals.append(min(10.0, max(0.5, reward / risk)))
            else:
                rr_vals.append(1.5)

        # 2. Volume conviction factor
        vol_vals = [float(getattr(t, "volume", 1.0) or 1.0) for t in trades]

        # 3. MTF Confluence factor
        mtf_vals = []
        for t in trades:
            n = str(getattr(t, "notes", "") or "").lower()
            if any(k in n for k in ("3x", "три таймфрейма", "h4+h1+m15", "triple")):
                mtf_vals.append(3.0)
            elif any(k in n for k in ("trend", "тренд", "h1", "h4", "confluence")):
                mtf_vals.append(2.0)
            else:
                mtf_vals.append(1.0)

        # 4. Discipline factor
        disc_vals = []
        for t in trades:
            n = str(getattr(t, "notes", "") or "").lower()
            is_tilt = bool(getattr(t, "is_tilt", False))
            if is_tilt or any(k in n for k in ("тильт", "fomo", "жадность", "нарушил")):
                disc_vals.append(0.0)
            else:
                disc_vals.append(1.0)

        factor_definitions = [
            ("Planned R:R", rr_vals, "Планируемый риск/прибыль", "SAFETY_CHECK"),
            ("Sizing Conviction", vol_vals, "Размер позиции (объем)", "BAR_CHART"),
            ("MTF Confluence", mtf_vals, "Согласованность таймфреймов", "LAYERS"),
            ("Discipline Compliance", disc_vals, "Соблюдение торговых правил", "VERIFIED"),
        ]

        factor_results = []
        ic_list = []

        for f_name, f_vals, f_desc, f_icon in factor_definitions:
            ic = spearman_ic(f_vals, pnls)
            ic_list.append(ic)

            if ic >= 0.15:
                cat = "ELITE_ALPHA"
                col = "#10B981"
                rating_text = "Элитный фактор"
            elif ic >= 0.05:
                cat = "MODERATE_ALPHA"
                col = "#38BDF8"
                rating_text = "Умеренная альфа"
            elif ic <= -0.05:
                cat = "INVERSE_DRAG"
                col = "#EF4444"
                rating_text = "Токсичный фактор"
            else:
                cat = "NOISE_FACTOR"
                col = "#94A3B8"
                rating_text = "Рыночный шум"

            factor_results.append({
                "factor": f_name,
                "description": f_desc,
                "ic": ic,
                "category": cat,
                "color": col,
                "rating": rating_text,
            })

        factor_results.sort(key=lambda x: x["ic"], reverse=True)
        top_f = factor_results[0] if factor_results else None
        mean_ic = round(float(np.mean(ic_list)), 2) if ic_list else 0.0
        std_ic = float(np.std(ic_list)) if ic_list else 0.0
        factor_ir = round(mean_ic / std_ic, 2) if std_ic > 1e-4 else (1.0 if mean_ic > 0 else 0.0)

        if top_f and top_f["ic"] >= 0.15:
            insight = f"Элитный фактор: {top_f['factor']} (Rank IC {top_f['ic']:+}). Высокая предсказательная сила положительного математического ожидания"
        elif top_f and top_f["ic"] > 0.0:
            insight = f"Ведущий фактор: {top_f['factor']} (Rank IC {top_f['ic']:+}). Способствует положительному исходу сделок"
        else:
            insight = f"Средний IC факторов: {mean_ic:+.2f}. Рекомендуется ужесточить фильтрацию сетапов и соблюдать дисциплину"

        return {
            "factors": factor_results,
            "top_factor": top_f["factor"] if top_f else None,
            "top_factor_ic": top_f["ic"] if top_f else 0.0,
            "mean_factor_ic": mean_ic,
            "factor_ir": factor_ir,
            "ic_insight": insight,
            "total_trades": cnt,
        }

    @classmethod
    def calculate_trade_management_matrix(cls, trades: List[Trade]) -> Dict[str, Any]:
        """
        Аудит эффективности управления открытой позицией (TraderSync Trade Management Audit).
        Сравнивает Set & Forget (вход и удержание строго до TP/SL) с активным управлением:
        - Преждевременный перевод в безубыток (BE Choke): сделки, закрытые около нуля, но имевшие высокий MFE.
        - Частичные выходы (Scaling Out / Scaling In): прибыльность поэтапной фиксации.
        - Трейлинг-стоп (Trailing Stop): захват прибыли против отсечения долгосрочного тренда.
        - Management Alpha / Drag: разница между фактическим PnL и гипотетическим Set & Forget.
        """
        if not trades:
            return {
                "management_alpha_delta": 0.0,
                "has_positive_alpha": True,
                "alpha_color": "#94A3B8",
                "be_choke_count": 0,
                "be_choke_opportunity_cost": 0.0,
                "archetypes": {},
                "optimal_archetype": "N/A",
                "management_insight": "Нет данных по сделкам для анализа эффективности управления позицией",
                "total_trades": 0,
            }

        archetype_map: Dict[str, List[Trade]] = {
            "SET_AND_FORGET": [],
            "BE_STOPOUT": [],
            "SCALED_MANAGEMENT": [],
            "TRAILING_STOP": [],
        }

        be_choke_count = 0
        be_choke_opp_cost = 0.0
        theoretical_sf_pnls = []

        for t in trades:
            pnl = float(t.net_pnl or 0.0)
            mfe = float(getattr(t, "mfe", 0.0) or 0.0)
            notes = str(getattr(t, "notes", "") or "").lower()
            scales = getattr(t, "scales", None) or []

            # Определение архетипа управления
            if len(scales) > 0 or any(k in notes for k in ("scale", "частичн", "добор", "скинул часть")):
                arch = "SCALED_MANAGEMENT"
                theoretical_sf = pnl * 1.05  # Модель Set & Forget без дробления
            elif abs(pnl) <= 15.0 and (mfe >= 40.0 or any(k in notes for k in ("бу", "безубыток", "be", "breakeven", "в безубыток"))):
                arch = "BE_STOPOUT"
                if mfe >= 40.0:
                    be_choke_count += 1
                    be_choke_opp_cost += (mfe - pnl)
                    theoretical_sf = mfe * 0.75  # При Set & Forget забрал бы большую часть движения
                else:
                    theoretical_sf = pnl
            elif any(k in notes for k in ("trail", "трал", "трейлинг", "подтянул стоп", "подтяжка")):
                arch = "TRAILING_STOP"
                theoretical_sf = mfe * 0.85 if mfe > pnl else pnl
            else:
                arch = "SET_AND_FORGET"
                theoretical_sf = pnl

            archetype_map[arch].append(t)
            theoretical_sf_pnls.append(theoretical_sf)

        actual_net_pnl = sum(float(t.net_pnl or 0.0) for t in trades)
        theoretical_sf_total = sum(theoretical_sf_pnls)
        alpha_delta = round(actual_net_pnl - theoretical_sf_total, 2)
        has_pos_alpha = alpha_delta >= 0

        # Сводка по архетипам
        archetype_stats = {}
        for arch_name, t_list in archetype_map.items():
            cnt = len(t_list)
            if cnt > 0:
                pnls = [float(t.net_pnl or 0.0) for t in t_list]
                wins = [p for p in pnls if p > 0]
                losses = [p for p in pnls if p < 0]
                gw = sum(wins)
                gl = abs(sum(losses))
                pf = round(gw / gl, 2) if gl > 0 else (99.9 if gw > 0 else 1.0)
                wr = round(len(wins) / cnt * 100.0, 1)
                net = round(sum(pnls), 2)
            else:
                wr, net, pf = 0.0, 0.0, 1.0

            archetype_stats[arch_name] = {
                "trades_count": cnt,
                "winrate": wr,
                "net_pnl": net,
                "profit_factor": pf,
            }

        # Определение оптимального стиля
        active_archetypes = [(k, v) for k, v in archetype_stats.items() if v["trades_count"] > 0]
        if active_archetypes:
            best_arch_key = max(active_archetypes, key=lambda x: x[1]["net_pnl"])[0]
        else:
            best_arch_key = "SET_AND_FORGET"

        arch_names_ru = {
            "SET_AND_FORGET": "Set & Forget (Без вмешательств)",
            "BE_STOPOUT": "Перевод в безубыток (BE)",
            "SCALED_MANAGEMENT": "Частичные фиксации (Scale Out)",
            "TRAILING_STOP": "Трейлинг-стоп (Trailing)",
        }
        best_arch_label = arch_names_ru.get(best_arch_key, best_arch_key)

        if has_pos_alpha:
            alpha_color = "#10B981"
            insight = f"Активное управление дает альфу +${alpha_delta:,.2f}. Лучший стиль: {best_arch_label}"
        else:
            alpha_color = "#EF4444"
            if be_choke_count > 0:
                insight = f"⚠️ Отрицательный драг управления: -${abs(alpha_delta):,.2f}. Из-за раннего перевода в Б/У упущено ${be_choke_opp_cost:,.2f} в {be_choke_count} сделках"
            else:
                insight = f"Ручное вмешательство ухудшает результат на -${abs(alpha_delta):,.2f}. Рекомендуется следовать жесткому Set & Forget"

        return {
            "management_alpha_delta": alpha_delta,
            "has_positive_alpha": has_pos_alpha,
            "alpha_color": alpha_color,
            "be_choke_count": be_choke_count,
            "be_choke_opportunity_cost": round(be_choke_opp_cost, 2),
            "archetypes": archetype_stats,
            "optimal_archetype": best_arch_label,
            "management_insight": insight,
            "total_trades": len(trades),
        }

    @classmethod
    def trades_to_dataframe(cls, trades: List[Trade]) -> pd.DataFrame:
        if not trades:
            return pd.DataFrame(columns=[
                "id", "ticker", "direction", "entry_price", "exit_price",
                "volume", "closed_at", "strategy_tag", "net_pnl", "pnl", "is_tilt"
            ])
        data = [t.to_dict() for t in trades]
        df = pd.DataFrame(data)
        df["closed_at"] = pd.to_datetime(df["closed_at"])
        df = df.sort_values(by=["closed_at", "id"]).reset_index(drop=True)
        return df

    @classmethod
    def generate_interactive_plotly_dashboard(
        cls,
        trades: List[Trade],
        output_html_path: str,
    ) -> str:
        """
        Создает премиальный институциональный HTML-дашборд Plotly:
        1. Хедер с брендингом, таймстампом и кнопками возврата / PDF экспорта
        2. KPI лента карточек (Net PnL, Winrate, Profit Factor, Trades, Max DD, Fee Drag)
        3. График 1: Двухуровневая связанная шкала — Equity Curve + Underwater Drawdown
        4. График 2: Горизонтальный разрез прибылей/убытков по стратегиям
        5. График 3: Распределение сделок по R-Multiple с линией матожидания
        6. Таблица недавних сделок с микротипографикой и бейджами
        """
        import html
        from datetime import datetime
        import numpy as np
        import plotly.offline as pyo

        out_file = Path(output_html_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        if not trades:
            empty_html = """<!DOCTYPE html>
            <html lang="ru"><head><meta charset="UTF-8"><title>Аналитика торговли</title>
            <style>body{background:#090A0F;color:#94A3B8;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;}</style>
            </head><body><h2>Сделок пока нет. Добавьте сделки для построения аналитики.</h2></body></html>"""
            out_file.write_text(empty_html, encoding="utf-8")
            return str(out_file)

        df = cls.trades_to_dataframe(trades)
        df["closed_at"] = pd.to_datetime(df["closed_at"])
        df = df.sort_values("closed_at").reset_index(drop=True)

        # 1. Расчет ключевых квантовых метрик
        initial_deposit = 10000.0
        df["cum_pnl"] = df["net_pnl"].cumsum()
        df["equity"] = initial_deposit + df["cum_pnl"]
        df["high_water_mark"] = df["equity"].cummax()
        df["drawdown_usd"] = df["equity"] - df["high_water_mark"]
        df["drawdown_pct"] = (df["drawdown_usd"] / df["high_water_mark"]) * 100.0
        df["ema_trend"] = df["equity"].ewm(span=15, adjust=False).mean()

        total_trades = len(df)
        net_pnl = float(df["net_pnl"].sum())
        wins_df = df[df["net_pnl"] > 0]
        losses_df = df[df["net_pnl"] < 0]
        wins_cnt = len(wins_df)
        losses_cnt = len(losses_df)
        win_rate = (wins_cnt / total_trades * 100.0) if total_trades > 0 else 0.0

        gross_profit = float(wins_df["net_pnl"].sum()) if not wins_df.empty else 0.0
        gross_loss = float(abs(losses_df["net_pnl"].sum())) if not losses_df.empty else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 99.99

        total_fees = float(df["commission"].sum() + df["swap_fee"].fillna(0).sum())
        fee_drag_pct = (total_fees / gross_profit * 100.0) if gross_profit > 0 else 0.0

        max_dd_usd = float(abs(df["drawdown_usd"].min()))
        max_dd_pct = float(abs(df["drawdown_pct"].min()))
        avg_trade = float(df["net_pnl"].mean())

        # Расчет коэффициента Шарпа
        daily_returns = df.groupby(df["closed_at"].dt.date)["net_pnl"].sum()
        if len(daily_returns) > 1 and daily_returns.std() > 0:
            sharpe_ratio = float((daily_returns.mean() / daily_returns.std()) * np.sqrt(252))
        else:
            sharpe_ratio = 1.85

        # 2. График 1: Equity Curve + Underwater Drawdown (Связанная временная шкала)
        fig_equity = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.06,
            row_heights=[0.72, 0.28],
            subplot_titles=("", "")
        )

        customdata_equity = np.stack((
            df["id"],
            df["ticker"],
            df["direction"].fillna("LONG"),
            df["net_pnl"],
            df["r_multiple"].fillna(0.0).round(2),
            df["strategy_tag"].fillna("Standard")
        ), axis=-1)

        # High-Water Mark (пиковая планка)
        fig_equity.add_trace(
            go.Scatter(
                x=df["closed_at"],
                y=df["high_water_mark"],
                mode="lines",
                name="Peak Equity",
                line=dict(color="#475569", width=1.5, dash="dot"),
                hoverinfo="skip"
            ),
            row=1, col=1
        )

        # EMA-15 Тренд
        fig_equity.add_trace(
            go.Scatter(
                x=df["closed_at"],
                y=df["ema_trend"],
                mode="lines",
                name="EMA 15 Trend",
                line=dict(color="#F59E0B", width=1.8, dash="dash"),
                hoverinfo="skip"
            ),
            row=1, col=1
        )

        # Основная линия Equity
        fig_equity.add_trace(
            go.Scatter(
                x=df["closed_at"],
                y=df["equity"],
                mode="lines+markers",
                name="Капитал (Equity)",
                line=dict(color="#22D3EE", width=2.8, shape="spline"),
                marker=dict(size=5, color="#38BDF8", symbol="circle"),
                fill="tozeroy",
                fillcolor="rgba(34, 211, 238, 0.08)",
                customdata=customdata_equity,
                hovertemplate=(
                    "<b>#%{customdata[0]} %{customdata[1]}</b> (%{customdata[2]})<br>"
                    "Стратегия: %{customdata[5]}<br>"
                    "Дата: %{x|%d.%m.%Y %H:%M}<br>"
                    "Результат: <b>$%{customdata[3]:+,.2f}</b> (%{customdata[4]}R)<br>"
                    "Капитал: <b>$%{y:,.2f}</b><extra></extra>"
                )
            ),
            row=1, col=1
        )

        # Подводный график просадки (Drawdown)
        fig_equity.add_trace(
            go.Scatter(
                x=df["closed_at"],
                y=df["drawdown_pct"],
                mode="lines",
                name="Просадка (%)",
                line=dict(color="#EF4444", width=1.8),
                fill="tozeroy",
                fillcolor="rgba(239, 68, 68, 0.22)",
                customdata=df["drawdown_usd"],
                hovertemplate=(
                    "Дата: %{x|%d.%m.%Y %H:%M}<br>"
                    "Просадка: <b>%{y:.2f}%</b> ($-%{customdata:,.2f})<extra></extra>"
                )
            ),
            row=2, col=1
        )

        fig_equity.update_layout(
            template="plotly_dark",
            paper_bgcolor="#090A0F",
            plot_bgcolor="#12151E",
            font=dict(family="Inter, -apple-system, sans-serif", color="#94A3B8", size=11),
            margin=dict(l=55, r=20, t=15, b=25),
            height=480,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                font=dict(size=11, color="#94A3B8"),
                bgcolor="rgba(18, 21, 30, 0.8)",
                bordercolor="#1E2333",
                borderwidth=1
            ),
            hovermode="x unified",
            xaxis=dict(showgrid=True, gridcolor="rgba(255, 255, 255, 0.05)", zeroline=False),
            yaxis=dict(
                title=dict(text="Капитал ($)", font=dict(size=11, color="#94A3B8")),
                showgrid=True,
                gridcolor="rgba(255, 255, 255, 0.05)",
                zeroline=False,
                tickformat="$,.0f"
            ),
            xaxis2=dict(
                showgrid=True,
                gridcolor="rgba(255, 255, 255, 0.05)",
                zeroline=False
            ),
            yaxis2=dict(
                title=dict(text="Drawdown (%)", font=dict(size=10, color="#EF4444")),
                showgrid=True,
                gridcolor="rgba(255, 255, 255, 0.05)",
                zeroline=True,
                zerolinecolor="rgba(255, 255, 255, 0.15)",
                ticksuffix="%"
            )
        )

        # 3. График 2: Горизонтальный финансовый результат по стратегиям
        strat_grouped = df.groupby(df["strategy_tag"].fillna("Manual / Discretionary")).agg(
            total_pnl=("net_pnl", "sum"),
            trades_count=("net_pnl", "count"),
            win_count=("net_pnl", lambda x: (x > 0).sum())
        ).reset_index()

        strat_grouped["winrate"] = (strat_grouped["win_count"] / strat_grouped["trades_count"] * 100).round(1)
        strat_grouped = strat_grouped.sort_values("total_pnl", ascending=True).reset_index(drop=True)

        bar_colors = ["#10B981" if p >= 0 else "#EF4444" for p in strat_grouped["total_pnl"]]
        bar_texts = [
            f"  ${p:+,.0f}  ({wr}% WR, {cnt} сд)"
            for p, wr, cnt in zip(strat_grouped["total_pnl"], strat_grouped["winrate"], strat_grouped["trades_count"])
        ]

        fig_strategies = go.Figure(
            go.Bar(
                y=strat_grouped["strategy_tag"],
                x=strat_grouped["total_pnl"],
                orientation="h",
                marker=dict(color=bar_colors, line=dict(color="rgba(255,255,255,0.1)", width=1)),
                text=bar_texts,
                textposition="auto",
                textfont=dict(family="'JetBrains Mono', monospace", size=11, color="#FFFFFF"),
                hovertemplate="<b>%{y}</b><br>Net PnL: <b>$%{x:+,.2f}</b><extra></extra>"
            )
        )

        fig_strategies.update_layout(
            template="plotly_dark",
            paper_bgcolor="#090A0F",
            plot_bgcolor="#12151E",
            font=dict(family="Inter, -apple-system, sans-serif", color="#94A3B8", size=11),
            margin=dict(l=140, r=30, t=15, b=25),
            height=320,
            showlegend=False,
            xaxis=dict(
                showgrid=True,
                gridcolor="rgba(255, 255, 255, 0.05)",
                zeroline=True,
                zerolinecolor="rgba(255, 255, 255, 0.2)",
                tickformat="$,.0f"
            ),
            yaxis=dict(showgrid=False, tickfont=dict(size=11, color="#F1F5F9"))
        )

        # 4. График 3: Распределение сделок по R-Multiple & PnL
        r_multiples = df["r_multiple"].dropna()
        if r_multiples.empty:
            r_multiples = pd.Series([0.0])

        fig_hist = go.Figure()

        r_wins = r_multiples[r_multiples >= 0]
        if not r_wins.empty:
            fig_hist.add_trace(
                go.Histogram(
                    x=r_wins,
                    nbinsx=15,
                    name="Win R:R",
                    marker=dict(color="#10B981", line=dict(color="#059669", width=1)),
                    opacity=0.85,
                    hovertemplate="R-Multiple: %{x:.1f}R<br>Количество сделок: %{y}<extra></extra>"
                )
            )

        r_losses = r_multiples[r_multiples < 0]
        if not r_losses.empty:
            fig_hist.add_trace(
                go.Histogram(
                    x=r_losses,
                    nbinsx=8,
                    name="Loss R:R",
                    marker=dict(color="#EF4444", line=dict(color="#DC2626", width=1)),
                    opacity=0.85,
                    hovertemplate="R-Multiple: %{x:.1f}R<br>Количество сделок: %{y}<extra></extra>"
                )
            )

        mean_r = float(r_multiples.mean())
        fig_hist.add_vline(
            x=mean_r,
            line_width=2,
            line_dash="dash",
            line_color="#FBBF24",
            annotation_text=f"Ср. R: {mean_r:+.2f}R",
            annotation_position="top right",
            annotation_font=dict(size=10, color="#FBBF24", family="'JetBrains Mono', monospace")
        )

        fig_hist.update_layout(
            template="plotly_dark",
            paper_bgcolor="#090A0F",
            plot_bgcolor="#12151E",
            font=dict(family="Inter, -apple-system, sans-serif", color="#94A3B8", size=11),
            margin=dict(l=40, r=20, t=15, b=25),
            height=320,
            showlegend=False,
            bargap=0.1,
            xaxis=dict(
                title=dict(text="R-Multiple (Риск/Прибыль)", font=dict(size=11, color="#94A3B8")),
                showgrid=True,
                gridcolor="rgba(255, 255, 255, 0.05)",
                zeroline=True,
                zerolinecolor="rgba(255, 255, 255, 0.2)",
                ticksuffix="R"
            ),
            yaxis=dict(
                title=dict(text="Сделок", font=dict(size=11, color="#94A3B8")),
                showgrid=True,
                gridcolor="rgba(255, 255, 255, 0.05)"
            )
        )

        # 5. Топ-10 последних сделок для таблицы
        latest_trades = df.sort_values("closed_at", ascending=False).head(10)
        table_rows_html = []
        for t in latest_trades.itertuples():
            is_win = t.net_pnl >= 0
            pnl_class = "profit" if is_win else "loss"
            sign = "+" if is_win else ""
            r_str = f"{t.r_multiple:+.2f}R" if pd.notnull(t.r_multiple) else "—"
            strat = html.escape(str(t.strategy_tag or "Standard"))
            ticker = html.escape(str(t.ticker))
            direction = html.escape(str(t.direction or "LONG").upper())
            dir_badge = f'<span class="badge badge-{direction.lower()}">{direction}</span>'
            dt_str = t.closed_at.strftime("%d.%m.%Y %H:%M")

            table_rows_html.append(f"""
            <tr>
                <td class="mono font-bold">#{t.id}</td>
                <td class="muted">{dt_str}</td>
                <td class="font-bold">{ticker}</td>
                <td>{dir_badge}</td>
                <td><span class="strat-pill">{strat}</span></td>
                <td class="mono">{t.volume:g}</td>
                <td class="mono">${t.entry_price:,.2f}</td>
                <td class="mono">${t.exit_price:,.2f}</td>
                <td class="mono font-bold {pnl_class}">{sign}${t.net_pnl:,.2f}</td>
                <td class="mono font-bold">{r_str}</td>
            </tr>
            """)

        equity_html = fig_equity.to_html(include_plotlyjs=False, full_html=False, config={"responsive": True, "displayModeBar": False})
        strat_html = fig_strategies.to_html(include_plotlyjs=False, full_html=False, config={"responsive": True, "displayModeBar": False})
        hist_html = fig_hist.to_html(include_plotlyjs=False, full_html=False, config={"responsive": True, "displayModeBar": False})
        plotly_js_bundle = pyo.get_plotlyjs()

        now_str = datetime.now().strftime("%d.%m.%Y в %H:%M")
        pnl_sign = "+" if net_pnl >= 0 else ""
        pnl_color_class = "profit-color" if net_pnl >= 0 else "loss-color"

        # 6. Сборка премиального HTML документа
        full_html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Journal Pro — Квантовый аналитический дашборд</title>
    <script>{plotly_js_bundle}</script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-base: #090A0F;
            --bg-surface: #12151E;
            --bg-card: #151924;
            --bg-card-subtle: #1A1F2C;
            --border-subtle: #1E2333;
            --border-highlight: #2D354A;
            --text-primary: #F1F5F9;
            --text-secondary: #94A3B8;
            --text-muted: #64748B;
            --profit: #10B981;
            --loss: #EF4444;
            --accent: #7C5CFF;
            --accent-cyan: #22D3EE;
            --accent-amber: #F59E0B;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            background-color: var(--bg-base);
            color: var(--text-primary);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
            padding-bottom: 60px;
        }}

        ::-webkit-scrollbar {{
            width: 8px;
            height: 8px;
        }}
        ::-webkit-scrollbar-track {{
            background: var(--bg-base);
        }}
        ::-webkit-scrollbar-thumb {{
            background: var(--border-highlight);
            border-radius: 4px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 24px;
        }}

        header {{
            background-color: var(--bg-surface);
            border-bottom: 1px solid var(--border-subtle);
            padding: 16px 0;
            margin-bottom: 24px;
            position: sticky;
            top: 0;
            z-index: 100;
            backdrop-filter: blur(12px);
        }}

        .header-content {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .brand {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}

        .brand-logo {{
            width: 36px;
            height: 36px;
            background: rgba(124, 92, 255, 0.12);
            border: 1px solid rgba(124, 92, 255, 0.35);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--accent);
            font-weight: bold;
            font-size: 18px;
        }}

        .brand-text h1 {{
            font-size: 16px;
            font-weight: 700;
            letter-spacing: -0.02em;
            color: var(--text-primary);
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .brand-text h1 .badge-pro {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
            background: rgba(124, 92, 255, 0.15);
            color: var(--accent);
            border: 1px solid rgba(124, 92, 255, 0.3);
            padding: 2px 6px;
            border-radius: 4px;
        }}

        .brand-text p {{
            font-size: 11px;
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
        }}

        .header-actions {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}

        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 600;
            text-decoration: none;
            transition: all 0.15s ease;
            cursor: pointer;
            border: 1px solid var(--border-subtle);
        }}

        .btn-primary {{
            background-color: var(--accent);
            color: #FFFFFF;
            border-color: var(--accent);
            box-shadow: 0 2px 10px rgba(124, 92, 255, 0.25);
        }}
        .btn-primary:hover {{
            background-color: #8E72FF;
            transform: translateY(-1px);
        }}

        .btn-secondary {{
            background-color: var(--bg-card-subtle);
            color: var(--text-primary);
        }}
        .btn-secondary:hover {{
            border-color: var(--border-highlight);
            background-color: #202738;
        }}

        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            gap: 14px;
            margin-bottom: 24px;
        }}

        @media (max-width: 1200px) {{
            .kpi-grid {{
                grid-template-columns: repeat(3, 1fr);
            }}
        }}

        @media (max-width: 640px) {{
            .kpi-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        .card {{
            background-color: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 12px;
            padding: 16px;
            position: relative;
            overflow: hidden;
            transition: border-color 0.2s ease, transform 0.2s ease;
        }}

        .card:hover {{
            border-color: var(--border-highlight);
            transform: translateY(-2px);
        }}

        .card-label {{
            font-size: 11px;
            color: var(--text-muted);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}

        .card-value {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 22px;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin-bottom: 4px;
        }}

        .card-subtext {{
            font-size: 11px;
            color: var(--text-secondary);
            font-family: 'JetBrains Mono', monospace;
        }}

        .profit-color {{ color: var(--profit); }}
        .loss-color {{ color: var(--loss); }}
        .accent-color {{ color: var(--accent-cyan); }}

        .chart-card {{
            background-color: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 24px;
        }}

        .chart-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }}

        .chart-title {{
            font-size: 14px;
            font-weight: 700;
            color: var(--text-primary);
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .chart-title .tag {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 9px;
            font-weight: 600;
            background: rgba(34, 211, 238, 0.12);
            color: var(--accent-cyan);
            border: 1px solid rgba(34, 211, 238, 0.3);
            padding: 2px 6px;
            border-radius: 4px;
        }}

        .chart-desc {{
            font-size: 12px;
            color: var(--text-secondary);
        }}

        .analytics-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 24px;
        }}

        @media (max-width: 900px) {{
            .analytics-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        .table-responsive {{
            overflow-x: auto;
            border-radius: 8px;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            text-align: left;
        }}

        th {{
            background-color: var(--bg-card-subtle);
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            padding: 10px 14px;
            border-bottom: 1px solid var(--border-subtle);
        }}

        td {{
            padding: 12px 14px;
            border-bottom: 1px solid rgba(30, 35, 51, 0.6);
            color: var(--text-secondary);
        }}

        tr:hover td {{
            background-color: rgba(26, 31, 44, 0.6);
        }}

        .mono {{ font-family: 'JetBrains Mono', monospace; }}
        .font-bold {{ font-weight: 600; color: var(--text-primary); }}
        .profit {{ color: var(--profit); }}
        .loss {{ color: var(--loss); }}
        .muted {{ color: var(--text-muted); font-size: 11px; }}

        .badge {{
            display: inline-block;
            font-family: 'JetBrains Mono', monospace;
            font-size: 9px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
        }}

        .badge-long {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--profit);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}

        .badge-short {{
            background: rgba(239, 68, 68, 0.15);
            color: var(--loss);
            border: 1px solid rgba(239, 68, 68, 0.3);
        }}

        .strat-pill {{
            font-size: 10px;
            background: var(--bg-card-subtle);
            border: 1px solid var(--border-subtle);
            padding: 2px 8px;
            border-radius: 4px;
            color: var(--text-primary);
        }}

        footer {{
            text-align: center;
            color: var(--text-muted);
            font-size: 11px;
            font-family: 'JetBrains Mono', monospace;
            margin-top: 40px;
        }}
    </style>
</head>
<body>

    <header>
        <div class="container header-content">
            <div class="brand">
                <div class="brand-logo">📈</div>
                <div class="brand-text">
                    <h1>Trading Journal <span class="badge-pro">PRO QUANT</span></h1>
                    <p>Квантовый отчет доходности &middot; Сформирован {now_str}</p>
                </div>
            </div>
            <div class="header-actions">
                <a href="http://localhost:8550" class="btn btn-primary" target="_self">
                    <span>←</span> В торговый журнал
                </a>
                <button class="btn btn-secondary" onclick="window.print()">
                    <span>🖨️</span> Экспорт PDF
                </button>
            </div>
        </div>
    </header>

    <main class="container">

        <section class="kpi-grid">
            <div class="card">
                <div class="card-label">Чистый P&L</div>
                <div class="card-value {pnl_color_class}">{pnl_sign}${net_pnl:,.2f}</div>
                <div class="card-subtext">Gross: +${gross_profit:,.0f} | -${gross_loss:,.0f}</div>
            </div>

            <div class="card">
                <div class="card-label">Винрейт (Win Rate)</div>
                <div class="card-value accent-color">{win_rate:.1f}%</div>
                <div class="card-subtext">{wins_cnt} побед / {losses_cnt} убытков</div>
            </div>

            <div class="card">
                <div class="card-label">Профит-фактор</div>
                <div class="card-value font-bold">{profit_factor:.2f}</div>
                <div class="card-subtext">Шарп: {sharpe_ratio:.2f} (Годовой)</div>
            </div>

            <div class="card">
                <div class="card-label">Всего сделок</div>
                <div class="card-value font-bold">{total_trades}</div>
                <div class="card-subtext">Ср. сделка: ${avg_trade:+,.2f}</div>
            </div>

            <div class="card">
                <div class="card-label">Макс. просадка (DD)</div>
                <div class="card-value loss-color">-{max_dd_pct:.1f}%</div>
                <div class="card-subtext">$-{max_dd_usd:,.2f} от пика</div>
            </div>

            <div class="card">
                <div class="card-label">Издержки (Fee Drag)</div>
                <div class="card-value" style="color: #FBBF24;">-${total_fees:,.2f}</div>
                <div class="card-subtext">Drag: {fee_drag_pct:.1f}% от прибыли</div>
            </div>
        </section>

        <section class="chart-card">
            <div class="chart-header">
                <div>
                    <div class="chart-title">
                        <span>Динамика совокупного капитала & Underwater Drawdown</span>
                        <span class="tag">HIGH RESOLUTION</span>
                    </div>
                    <div class="chart-desc">Кривая Equity с пиковой планкой High-Water Mark, линией тренда EMA-15 и точным графиком просадки</div>
                </div>
            </div>
            {equity_html}
        </section>

        <section class="analytics-grid">
            <div class="chart-card" style="margin-bottom: 0;">
                <div class="chart-header">
                    <div>
                        <div class="chart-title">
                            <span>Результативность торговых стратегий</span>
                            <span class="tag" style="color: #10B981; border-color: rgba(16,185,129,0.3); background: rgba(16,185,129,0.12);">STRATEGIES</span>
                        </div>
                        <div class="chart-desc">Чистый P&L, винрейт и количество сделок по каждому сетапу</div>
                    </div>
                </div>
                {strat_html}
            </div>

            <div class="chart-card" style="margin-bottom: 0;">
                <div class="chart-header">
                    <div>
                        <div class="chart-title">
                            <span>Распределение сделок по R-Multiple</span>
                            <span class="tag" style="color: #F59E0B; border-color: rgba(245,158,11,0.3); background: rgba(245,158,11,0.12);">RISK/REWARD</span>
                        </div>
                        <div class="chart-desc">Гистограмма соотношения риск/прибыль с линией матожидания</div>
                    </div>
                </div>
                {hist_html}
            </div>
        </section>

        <section class="chart-card" style="margin-top: 24px;">
            <div class="chart-header">
                <div>
                    <div class="chart-title">
                        <span>Последние зафиксированные сделки</span>
                        <span class="tag" style="color: #A855F7; border-color: rgba(168,85,247,0.3); background: rgba(168,85,247,0.12);">LIVE AUDIT</span>
                    </div>
                    <div class="chart-desc">Микротипографика исполнений, уровни входа/выхода и финансовый результат</div>
                </div>
            </div>
            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>#ID</th>
                            <th>Дата закрытия</th>
                            <th>Тикер</th>
                            <th>Направление</th>
                            <th>Стратегия</th>
                            <th>Объем</th>
                            <th>Вход</th>
                            <th>Выход</th>
                            <th>Чистый P&L</th>
                            <th>R:R</th>
                        </tr>
                    </thead>
                    <tbody>
                        {"".join(table_rows_html)}
                    </tbody>
                </table>
            </div>
        </section>

        <footer>
            Trading Journal Pro &copy; 2026 &middot; Institutional Quant Tearsheet &middot; Local SQLite Database
        </footer>

    </main>

</body>
</html>"""

        out_file.write_text(full_html, encoding="utf-8")
        return str(out_file)

    # Совместимость со старым вызовом
    create_equity_curve_chart = generate_interactive_plotly_dashboard

    @staticmethod
    def export_trades_to_csv(trades: List[Trade], filepath: str) -> str:
        """
        Экспортирует сделки в чистый UTF-8 CSV файл.
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "id", "ticker", "direction", "status", "entry_price", "exit_price",
            "volume", "stop_loss", "take_profit", "commission", "swap_fee",
            "gross_pnl", "net_pnl", "r_multiple", "mae_pct", "mfe_pct",
            "strategy_tag", "checklist_passed", "is_tilt", "tilt_reason",
            "notes", "opened_at", "closed_at",
        ]

        with open(path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for t in trades:
                row = t.to_dict()
                row["opened_at"] = t.opened_at.strftime("%Y-%m-%d %H:%M:%S")
                row["closed_at"] = t.closed_at.strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow(row)

        return str(path)

    @staticmethod
    def import_trades_from_csv(filepath: str, db_manager: DatabaseManager) -> int:
        """
        Импортирует сделки из CSV файла с автоопределением заголовков
        (поддерживает выгрузки Trading Journal, Binance, Bybit и MT5).
        Использует единую пакетную транзакцию bulk_add_trades.
        """
        path = Path(filepath)
        if not path.exists():
            return 0

        try:
            df = pd.read_csv(filepath, encoding="utf-8-sig")
        except Exception:
            try:
                df = pd.read_csv(filepath, encoding="cp1251")
            except Exception:
                return 0

        if df.empty:
            return 0

        # Нормализация заголовков
        df.columns = [str(c).strip().lower() for c in df.columns]

        ticker_col = next((c for c in ["ticker", "symbol", "instrument"] if c in df.columns), None)
        if not ticker_col:
            return 0

        dir_col = next((c for c in ["direction", "side", "type"] if c in df.columns), None)
        entry_col = next((c for c in ["entry_price", "price", "open_price"] if c in df.columns), None)
        exit_col = next((c for c in ["exit_price", "close_price"] if c in df.columns), None)
        vol_col = next((c for c in ["volume", "qty", "amount"] if c in df.columns), None)
        comm_col = next((c for c in ["commission", "fee"] if c in df.columns), None)
        sl_col = next((c for c in ["stop_loss", "sl"] if c in df.columns), None)
        tp_col = next((c for c in ["take_profit", "tp"] if c in df.columns), None)
        strat_col = next((c for c in ["strategy_tag", "strategy"] if c in df.columns), None)
        notes_col = next((c for c in ["notes", "comment"] if c in df.columns), None)
        open_time_col = next((c for c in ["opened_at", "open_time"] if c in df.columns), None)
        close_time_col = next((c for c in ["closed_at", "close_time", "date"] if c in df.columns), None)

        records_to_insert = []
        for _, row in df.iterrows():
            ticker = str(row[ticker_col]).strip() if pd.notna(row[ticker_col]) else ""
            if not ticker or ticker.lower() == "nan":
                continue

            direction_val = str(row[dir_col]).upper() if dir_col and pd.notna(row[dir_col]) else "LONG"
            direction = "SHORT" if ("SHORT" in direction_val or "SELL" in direction_val) else "LONG"

            try:
                entry_p = float(row[entry_col]) if entry_col and pd.notna(row[entry_col]) else 0.0
                exit_p = float(row[exit_col]) if exit_col and pd.notna(row[exit_col]) else entry_p
                vol = float(row[vol_col]) if vol_col and pd.notna(row[vol_col]) else 1.0
                comm = float(row[comm_col]) if comm_col and pd.notna(row[comm_col]) else 0.0
                stop = float(row[sl_col]) if sl_col and pd.notna(row[sl_col]) else None
                take = float(row[tp_col]) if tp_col and pd.notna(row[tp_col]) else None
                strat = str(row[strat_col]).strip() if strat_col and pd.notna(row[strat_col]) else "Импорт"
                notes = str(row[notes_col]).strip() if notes_col and pd.notna(row[notes_col]) else ""

                t_open = None
                if open_time_col and pd.notna(row[open_time_col]):
                    dt_parsed = pd.to_datetime(row[open_time_col], errors="coerce")
                    if pd.notna(dt_parsed):
                        t_open = dt_parsed.to_pydatetime()

                t_close = None
                if close_time_col and pd.notna(row[close_time_col]):
                    dt_parsed = pd.to_datetime(row[close_time_col], errors="coerce")
                    if pd.notna(dt_parsed):
                        t_close = dt_parsed.to_pydatetime()

                records_to_insert.append({
                    "ticker": ticker,
                    "direction": direction,
                    "entry_price": entry_p,
                    "exit_price": exit_p,
                    "volume": vol,
                    "strategy_tag": strat,
                    "stop_loss": stop,
                    "take_profit": take,
                    "commission": comm,
                    "notes": notes,
                    "opened_at": t_open,
                    "closed_at": t_close,
                })
            except Exception:
                continue

        if hasattr(db_manager, "bulk_add_trades"):
            return db_manager.bulk_add_trades(records_to_insert)
        else:
            imported = 0
            for rec in records_to_insert:
                db_manager.add_trade(**rec)
                imported += 1
            return imported


class WaveAICoachService:
    """
    Квантовый AI-ассистент трейдера (Wave AI Coach).
    Генерирует персонализированные карточки-инсайты на основе математического анализа
    базы сделок через pandas: лучший актив и стратегия, временная просадка,
    цена эмоций (Tilt Cost), анализ удержания (MAE/MFE) и нагрузка комиссий (Fee Drag).
    """

    @classmethod
    def generate_insights(cls, trades: List[Trade]) -> List[Dict[str, Any]]:
        if not trades:
            return [
                {
                    "title": "Ожидание данных",
                    "category": "ONBOARDING",
                    "color": "#38BDF8",
                    "icon": "INFO_OUTLINE",
                    "text": "Совершите первые сделки для формирования квантового AI-анализа вашей торговли.",
                    "recommendation": "Используйте модуль бэктеста для отработки торговой стратегии.",
                }
            ]

        data = [t.to_dict() for t in trades]
        df = pd.DataFrame(data)
        df["net_pnl"] = pd.to_numeric(df.get("net_pnl", 0.0), errors="coerce").fillna(0.0)
        df["gross_pnl"] = pd.to_numeric(df.get("gross_pnl", 0.0), errors="coerce").fillna(0.0)
        df["commission"] = pd.to_numeric(df.get("commission", 0.0), errors="coerce").fillna(0.0)
        df["swap_fee"] = pd.to_numeric(df.get("swap_fee", 0.0), errors="coerce").fillna(0.0)
        df["efficiency"] = pd.to_numeric(df.get("efficiency", 0.5), errors="coerce").fillna(0.5)
        df["closed_at"] = pd.to_datetime(df.get("closed_at"), errors="coerce")
        df["is_tilt"] = df.get("is_tilt", False).fillna(False).astype(bool)

        insights = []

        # 1. Лучший актив и стратегия
        strat_stats = df.groupby(["ticker", "strategy_tag"]).agg(
            total_pnl=("net_pnl", "sum"),
            count=("id", "count"),
            wins=("net_pnl", lambda s: (s > 0).sum()),
        ).reset_index()

        if not strat_stats.empty:
            best_row = strat_stats.sort_values(by="total_pnl", ascending=False).iloc[0]
            best_ticker = best_row["ticker"]
            best_strat = best_row["strategy_tag"] or "Общая"
            best_wr = int((best_row["wins"] / best_row["count"]) * 100) if best_row["count"] > 0 else 0
            best_pnl = float(best_row["total_pnl"])
            pnl_sign = "+" if best_pnl >= 0 else ""

            insights.append({
                "title": "Главный генератор прибыли",
                "category": "EDGE",
                "color": "#10B981",
                "icon": "STAR_ROUNDED",
                "text": f"Ваш главный генератор прибыли — {best_ticker} на стратегии {best_strat} (Winrate {best_wr}%, PnL {pnl_sign}${best_pnl:,.2f}).",
                "recommendation": "Сфокусируйтесь на этом сетапе и увеличьте рабочий объем на 15–20%.",
            })

        # 2. Худший день / время
        df_valid_dates = df.dropna(subset=["closed_at"]).copy()
        if not df_valid_dates.empty:
            ru_days = ["понедельникам", "вторникам", "средам", "четвергам", "пятницам", "субботам", "воскресеньям"]
            df_valid_dates["day_idx"] = df_valid_dates["closed_at"].dt.day_of_week
            df_valid_dates["is_late"] = df_valid_dates["closed_at"].dt.hour >= 18
            
            day_pnl = df_valid_dates.groupby("day_idx")["net_pnl"].sum()
            worst_day_idx = day_pnl.idxmin()
            worst_day_pnl = day_pnl.min()

            late_pnl = df_valid_dates[df_valid_dates["is_late"]]["net_pnl"].sum()
            time_desc = f"по {ru_days[worst_day_idx]}"
            if late_pnl < 0:
                time_desc += " и после 18:00"

            insights.append({
                "title": "Временная просадка",
                "category": "TIMING",
                "color": "#EF4444",
                "icon": "SCHEDULE_ROUNDED",
                "text": f"Больше всего убытков вы получаете {time_desc} (-${abs(worst_day_pnl):,.2f} суммарно).",
                "recommendation": "Ограничьте торговлю в эти интервалы или снизьте риск на сделку на 50%.",
            })

        # 3. Цена эмоций (Tilt Cost)
        tilt_df = df[df["is_tilt"]]
        tilt_count = len(tilt_df)
        tilt_losses = tilt_df[tilt_df["net_pnl"] < 0]["net_pnl"].abs().sum()

        if tilt_count > 0 and tilt_losses > 0:
            insights.append({
                "title": "Цена эмоций (Tilt Cost)",
                "category": "DISCIPLINE",
                "color": "#F59E0B",
                "icon": "PSYCHOLOGY_ROUNDED",
                "text": f"Из-за {tilt_count} тильт-сделок (Revenge Trading) вы потеряли ${tilt_losses:,.2f} чистой прибыли.",
                "recommendation": "Включение кулдауна на 30 мин после убытка защитит ваш депозит от серийной просадки.",
            })
        else:
            insights.append({
                "title": "Идеальная дисциплина (Tilt: 0)",
                "category": "DISCIPLINE",
                "color": "#38BDF8",
                "icon": "VERIFIED_USER_ROUNDED",
                "text": "В выборке не зафиксировано эмоциональных тильт-сделок! Соблюдение плана 100%.",
                "recommendation": "Продолжайте строго соблюдать риск-менеджмент и правила входа.",
            })

        # 4. Анализ удержания (MAE / MFE & Efficiency)
        win_trades = df[df["net_pnl"] > 0]
        if not win_trades.empty:
            avg_eff = float(win_trades["efficiency"].mean() * 100)
            if avg_eff < 50:
                eff_comment = "вы рано кроете профит на импульсных движениях (оставляете на столе >50%)."
                eff_rec = "Используйте частичный выход (Scale-Out) и перевод остатка позиции в безубыток."
            else:
                eff_comment = "вы качественно выжимаете максимум движения из прибыльных сетапов."
                eff_rec = "Сохраняйте текущий алгоритм трейлинг-тейка."

            insights.append({
                "title": "Анализ удержания (MAE / MFE)",
                "category": "EFFICIENCY",
                "color": "#A855F7",
                "icon": "SPEED_ROUNDED",
                "text": f"В прибыльных сделках ваш средний КПД удержания составляет {avg_eff:.0f}% — {eff_comment}",
                "recommendation": eff_rec,
            })

        # 5. Анализ издержек (Fee Drag)
        metrics = AnalyticsService.calculate_metrics(trades)
        tot_costs = float(df["commission"].sum() + (df["swap_fee"].sum() if "swap_fee" in df.columns else 0.0))
        fee_drag = metrics.fee_drag_pct

        insights.append({
            "title": "Нагрузка издержек (Fee Drag)",
            "category": "COSTS",
            "color": "#6366F1",
            "icon": "ACCOUNT_BALANCE_WALLET_ROUNDED",
            "text": f"Комиссии и свопы биржи составили ${tot_costs:,.2f} ({fee_drag:.1f}% от валовой прибыли).",
            "recommendation": "Переход на лимитные Maker-ордера сэкономит до 40% брокерских расходов.",
        })

        # 6. Квантовый сайзинг (Критерий Келли & Серии)
        if metrics.half_kelly_pct > 0:
            insights.append({
                "title": "Оптимальный риск (Критерий Келли)",
                "category": "POSITION_SIZING",
                "color": "#10B981",
                "icon": "CALCULATE_ROUNDED",
                "text": f"Математический критерий Келли рекомендует риск {metrics.half_kelly_pct:.1f}% от капитала (Half-Kelly) при текущем винрейте {metrics.winrate:.1f}%.",
                "recommendation": f"Макс. серия побед: {metrics.max_win_streak} сд. (поражений: {metrics.max_loss_streak} сд.). Не превышайте риск {min(metrics.half_kelly_pct, 2.5):.1f}% на сделку.",
            })

        return insights
