"""
test_killer_features.py
Комплексный валидационный тест 5 новых киллер-фич платформы TraderWaves:
1. Мульти-аккаунты (database.py)
2. Прямая автосинхронизация (services/sync_service.py)
3. P&L Calendar Heatmap (ui/components/pnl_calendar.py)
4. Издержки брокера & Fee Drag (analytics.py)
5. Модуль ручного бэктестинга / симулятор (ui/views/backtest.py)
"""

from datetime import date, datetime, timedelta
from database import DatabaseManager, TradingAccount, Trade
from analytics import AnalyticsService
from services.sync_service import SyncService, encrypt_secret, decrypt_secret
from ui.components.pnl_calendar import PnLCalendar
from ui.views.backtest import BacktestView


def test_all():
    print("=== ТЕСТ 1: Мульти-аккаунты и фильтрация ===")
    db = DatabaseManager()
    accounts = db.get_accounts()
    assert len(accounts) >= 2, f"Ожидалось минимум 2 счета, получено {len(accounts)}"
    print(f"✓ Найдено счетов: {len(accounts)}: {[(a.id, a.name, a.exchange_type) for a in accounts]}")

    acc1_trades = db.get_trades(account_id=1)
    acc2_trades = db.get_trades(account_id=2)
    all_trades = db.get_all_trades()
    print(f"✓ Сделок всего: {len(all_trades)}, Счет 1 (Binance): {len(acc1_trades)}, Счет 2 (MT5): {len(acc2_trades)}")
    assert len(acc1_trades) > 0 and len(acc2_trades) > 0, "Сделки должны быть привязаны к счетам"

    print("\n=== ТЕСТ 2: Прямая автосинхронизация и шифрование ===")
    secret = "TopSecretApiPass2026!#"
    enc = encrypt_secret(secret)
    dec = decrypt_secret(enc)
    assert dec == secret, f"Ошибка шифрования/дешифрования: {dec} != {secret}"
    print(f"✓ Fernet шифрование работает: '{secret}' -> '{enc[:18]}...' -> '{dec}'")

    sync_res = SyncService.sync_account(1, db)
    print(f"✓ Синхронизация крипто-счета 1: {sync_res}")
    assert sync_res["success"] is True

    sync_res2 = SyncService.sync_account(2, db)
    print(f"✓ Синхронизация MT5-счета 2: {sync_res2}")
    assert sync_res2["success"] is True

    print("\n=== ТЕСТ 3: Издержки брокера и Fee Drag ===")
    metrics = AnalyticsService.calculate_metrics(all_trades)
    print(f"✓ Суммарные комиссии: ${metrics.total_commission:,.2f}")
    print(f"✓ Суммарные свопы: ${metrics.total_swap_fees:,.2f}")
    print(f"✓ Итого издержки брокера: ${metrics.total_broker_costs:,.2f}")
    print(f"✓ Fee Drag: {metrics.fee_drag_pct}% от валового профита")
    assert metrics.total_broker_costs >= 0
    assert metrics.fee_drag_pct >= 0

    print("\n=== ТЕСТ 4: P&L Calendar Heatmap ===")
    selected_date_holder = []
    def on_date_click(dt):
        selected_date_holder.append(dt)

    calendar_widget = PnLCalendar(trades=all_trades, on_date_selected=on_date_click)
    assert calendar_widget.month_label.value is not None
    # Тест клика на дату
    test_dt = date.today()
    calendar_widget._on_cell_clicked(test_dt)
    assert len(selected_date_holder) == 1 and selected_date_holder[0] == test_dt
    print(f"✓ PnL Календарь отрисован: {calendar_widget.month_label.value}, обработчик клика {selected_date_holder[0]} проверен")

    print("\n=== ТЕСТ 5: Симулятор рынка (Бэктест) ===")
    backtest = BacktestView()
    assert len(backtest.all_candles) >= 40, "Свечи должны быть загружены"
    initial_step = backtest.replay_index
    print(f"✓ Симулятор инициализирован: свечей {len(backtest.all_candles)}, текущий шаг {initial_step}")

    # Тест BUY Market
    backtest._execute_order("LONG")
    assert backtest.active_position is not None
    assert backtest.active_position["direction"] == "LONG"
    print(f"✓ Открыта LONG позиция: {backtest.active_position['symbol']} @ ${backtest.active_position['entry_price']}")

    # Шаг вперед на 2 свечи
    backtest._step_forward(2)
    assert backtest.replay_index == initial_step + 2
    print(f"✓ Шаг плеера вперед: новая свеча #{backtest.replay_index + 1}, плавающий PnL: ${backtest.unrealized_pnl:,.2f}")

    # Закрытие позиции
    backtest._close_current_position(silent=True)
    assert backtest.active_position is None
    assert len(backtest.session_trades) == 1
    print(f"✓ Позиция закрыта: сделка в журнале #{backtest.session_trades[0]['id']}, Net PnL: ${backtest.session_trades[0]['net_pnl']:,.2f}")
    print(f"✓ Итоговый баланс симулятора: ${backtest.virtual_balance:,.2f}")

    print("\n🎉 ВСЕ 5 ТЕСТОВ УСПЕШНО ПРОЙДЕНЫ БЕЗ ОШИБОК!")


if __name__ == "__main__":
    test_all()

