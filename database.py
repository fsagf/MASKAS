"""
Модуль базы данных (database.py)
Схема данных SQLAlchemy 2.0 с автоматической миграцией колонок для SQLite,
деревом ордеров TradeExecution (Scale-In / Scale-Out), VWAP-калькуляцией,
риск-метриками (R-Multiple, MAE/MFE, Efficiency) и детектированием тильта.
"""

from datetime import date, datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)


class Base(DeclarativeBase):
    """Базовый декларативный класс."""
    pass


def calculate_gross_pnl(direction: str, entry_price: float, exit_price: float, volume: float) -> float:
    """
    Расчет валового финансового результата (Gross PnL):
    Для LONG:  (exit_price - entry_price) * volume
    Для SHORT: (entry_price - exit_price) * volume
    """
    clean_dir = (direction or "LONG").strip().upper()
    if clean_dir == "SHORT":
        return round((entry_price - exit_price) * volume, 2)
    return round((exit_price - entry_price) * volume, 2)


# Обратная совместимость для старого кода
calculate_pnl = calculate_gross_pnl


class TradingAccount(Base):
    """
    Модель торгового счета / подключения к бирже или брокеру (Binance, Bybit, MT5, Manual).
    """
    __tablename__ = "trading_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # "Binance Futures", "MT5 Prop"
    exchange_type: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")  # BYBIT, BINANCE, OKX, MT5, MANUAL
    api_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    api_secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    account_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    initial_balance: Mapped[float] = mapped_column(Float, nullable=False, default=10000.0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    trades: Mapped[List["Trade"]] = relationship("Trade", back_populates="account", cascade="all, delete-orphan")

    @property
    def broker_type(self) -> str:
        return self.exchange_type or "MANUAL"

    @broker_type.setter
    def broker_type(self, val: str) -> None:
        self.exchange_type = val

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "broker_type": self.broker_type,
            "exchange_type": self.exchange_type,
            "api_key": self.api_key,
            "api_secret": self.api_secret,
            "account_number": self.account_number,
            "initial_balance": self.initial_balance if self.initial_balance is not None else 10000.0,
            "currency": self.currency or "USD",
            "last_sync_at": self.last_sync_at,
            "created_at": self.created_at,
        }


class Trade(Base):
    """
    Головная модель завершенной или активной торговой позиции (Round-trip position).
    """
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("trading_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    external_trade_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="LONG")  # LONG / SHORT
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="CLOSED")   # CLOSED / OPEN

    # Средневзвешенные цены (VWAP) и суммарный объем
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    volume: Mapped[float] = mapped_column(Float, nullable=False)

    # Параметры риск-менеджмента
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    commission: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    swap_fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Финансовые результаты
    gross_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    r_multiple: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Экстремумы внутри позиции (MAE / MFE)
    mae_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mfe_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mae_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mfe_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    efficiency: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Стратегия, чек-лист и тильт
    strategy_tag: Mapped[str] = mapped_column(String(50), nullable=False, default="Общая", index=True)
    checklist_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_tilt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tilt_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Артефакты и заметки
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Временные метки
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False, index=True)

    # Колонки полной обратной совместимости со старыми таблицами
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Связь с аккаунтом
    account: Mapped[Optional["TradingAccount"]] = relationship("TradingAccount", back_populates="trades")

    # Связь с деревом ордеров
    executions: Mapped[List["TradeExecution"]] = relationship(
        "TradeExecution",
        back_populates="trade",
        cascade="all, delete-orphan",
        order_by="TradeExecution.executed_at.asc()",
    )

    def __init__(self, **kwargs):
        # Нормализация тикера и направления
        if "ticker" in kwargs and kwargs["ticker"]:
            kwargs["ticker"] = kwargs["ticker"].strip().upper()
        if "direction" in kwargs and kwargs["direction"]:
            kwargs["direction"] = kwargs["direction"].strip().upper()

        super().__init__(**kwargs)
        if not hasattr(self, "closed_at") or self.closed_at is None:
            self.closed_at = kwargs.get("closed_at") or kwargs.get("date") or datetime.now()
        if not hasattr(self, "opened_at") or self.opened_at is None:
            self.opened_at = kwargs.get("opened_at") or kwargs.get("date") or (datetime.now() - timedelta(hours=2))
        self.date = self.closed_at
        self.recalculate_metrics()

    def recalculate_metrics(self) -> None:
        """
        Пересчитывает все производные финансовые и риск-метрики сделки.
        """
        if hasattr(self, "closed_at") and self.closed_at:
            self.date = self.closed_at
        self.ticker = (self.ticker or "").strip().upper()
        self.direction = (self.direction or "LONG").strip().upper()
        self.volume = max(float(self.volume or 0.0), 0.0)
        self.entry_price = max(float(self.entry_price or 0.0), 0.0)
        self.exit_price = max(float(self.exit_price or 0.0), 0.0)
        self.commission = max(float(self.commission or 0.0), 0.0)
        self.swap_fee = float(self.swap_fee or 0.0)

        # 1. Расчет Gross и Net PnL
        self.gross_pnl = calculate_gross_pnl(self.direction, self.entry_price, self.exit_price, self.volume)
        self.net_pnl = round(self.gross_pnl - self.commission - self.swap_fee, 2)
        self.pnl = self.net_pnl

        # 2. Расчет риска и R-Multiple (защита от околонулевого деления и аномалий)
        if self.stop_loss and self.stop_loss > 0 and self.stop_loss != self.entry_price:
            calc_risk = abs(self.entry_price - self.stop_loss) * self.volume
            if calc_risk >= 1.0:
                self.risk_amount = round(calc_risk, 2)
            else:
                self.risk_amount = 100.0  # Дефолтный стандартный риск 1% от депозита ($100.0)
        else:
            self.risk_amount = 100.0

        if self.risk_amount > 0:
            raw_r = self.net_pnl / self.risk_amount
            # Зажимаем индивидуальный r_multiple в строгом коридоре [-10.0, +20.0]
            self.r_multiple = round(max(-10.0, min(20.0, raw_r)), 2)
        else:
            self.r_multiple = 0.0

        # 3. Расчет MAE / MFE процентов
        is_long = self.direction == "LONG"
        price_diff = (self.exit_price - self.entry_price) if is_long else (self.entry_price - self.exit_price)
        pct_exit = (price_diff / self.entry_price * 100) if self.entry_price > 0 else 0.0

        if self.mae_price and self.entry_price > 0:
            mae_diff = (self.mae_price - self.entry_price) if is_long else (self.entry_price - self.mae_price)
            self.mae_pct = round(min(mae_diff / self.entry_price * 100, 0.0), 2)
        else:
            # Оценочный реалистичный MAE при отсутствии тиковых данных
            self.mae_pct = round(-abs(pct_exit * 0.35) - 0.6, 2)
            self.mae_price = self.entry_price * (1 + self.mae_pct / 100.0 if is_long else 1 - self.mae_pct / 100.0)

        if self.mfe_price and self.entry_price > 0:
            mfe_diff = (self.mfe_price - self.entry_price) if is_long else (self.entry_price - self.mfe_price)
            self.mfe_pct = round(max(mfe_diff / self.entry_price * 100, 0.0), 2)
        else:
            self.mfe_pct = round(max(pct_exit * 1.3, abs(self.mae_pct) * 1.5, 1.8), 2)
            self.mfe_price = self.entry_price * (1 + self.mfe_pct / 100.0 if is_long else 1 - self.mfe_pct / 100.0)

        # 4. Расчет эффективности удержания (Efficiency)
        if self.mfe_price and self.mfe_price != self.entry_price:
            max_move = abs(self.mfe_price - self.entry_price)
            realized_move = (self.exit_price - self.entry_price) if is_long else (self.entry_price - self.exit_price)
            eff = realized_move / max_move if max_move > 0 else 0.0
            self.efficiency = round(max(0.0, min(1.0, eff)), 2)
        else:
            self.efficiency = 0.5

    def recalculate_from_executions(self) -> None:
        """
        Пересчитывает средневзвешенные цены (VWAP), суммарный объем и PnL
        на основе дерева ордеров Scale-In / Scale-Out.
        """
        if not self.executions:
            return

        entry_weighted_sum = 0.0
        entry_volume_sum = 0.0
        exit_weighted_sum = 0.0
        exit_volume_sum = 0.0
        total_fees = 0.0

        for ex in self.executions:
            total_fees += (ex.fee or 0.0)
            act = (ex.action or "ENTRY").upper()
            if act in ["ENTRY", "ADD"]:
                entry_weighted_sum += ex.price * ex.volume
                entry_volume_sum += ex.volume
            elif act in ["PARTIAL_TP", "EXIT"]:
                exit_weighted_sum += ex.price * ex.volume
                exit_volume_sum += ex.volume

        if entry_volume_sum > 0:
            self.entry_price = round(entry_weighted_sum / entry_volume_sum, 4)
            self.volume = entry_volume_sum

        if exit_volume_sum > 0:
            self.exit_price = round(exit_weighted_sum / exit_volume_sum, 4)

        if total_fees > 0:
            self.commission = round(total_fees, 2)

        self.recalculate_metrics()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "external_trade_id": self.external_trade_id,
            "ticker": self.ticker,
            "direction": self.direction,
            "status": self.status,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "volume": self.volume,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "commission": self.commission,
            "swap_fee": self.swap_fee,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "pnl": self.net_pnl,
            "risk_amount": self.risk_amount,
            "r_multiple": self.r_multiple,
            "mae_price": self.mae_price,
            "mfe_price": self.mfe_price,
            "mae_pct": self.mae_pct,
            "mfe_pct": self.mfe_pct,
            "efficiency": self.efficiency,
            "strategy_tag": self.strategy_tag,
            "checklist_passed": self.checklist_passed,
            "is_tilt": self.is_tilt,
            "tilt_reason": self.tilt_reason,
            "screenshot_path": self.screenshot_path,
            "notes": self.notes,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "date": self.closed_at,
        }


class TradeExecution(Base):
    """
    Модель отдельного ордера/исполнения (Scale-In, Scale-Out).
    """
    __tablename__ = "trade_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(Integer, ForeignKey("trades.id", ondelete="CASCADE"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="ENTRY")  # ENTRY, ADD, PARTIAL_TP, EXIT
    price: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    trade: Mapped["Trade"] = relationship("Trade", back_populates="executions")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "trade_id": self.trade_id,
            "action": self.action,
            "price": self.price,
            "volume": self.volume,
            "fee": self.fee,
            "executed_at": self.executed_at,
        }


class DatabaseManager:
    """
    Менеджер базы данных SQLite с автоматической миграцией схемы и поддержкой сессий.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = Path(__file__).resolve().parent
            data_dir = base_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_file = data_dir / "trades.db"
        else:
            self.db_file = Path(db_path)
            self.db_file.parent.mkdir(parents=True, exist_ok=True)

        self.database_url = f"sqlite:///{self.db_file}"
        self.engine = create_engine(
            self.database_url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
        # expire_on_commit=False позволяет читать атрибуты моделей после закрытия сессии
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
            expire_on_commit=False,
        )
        self.init_db()

    def init_db(self) -> None:
        """Создает таблицы и выполняет безопасную авто-миграцию схемы."""
        Base.metadata.create_all(bind=self.engine)
        self._ensure_schema_up_to_date()

    def _ensure_schema_up_to_date(self) -> None:
        """
        Проверяет наличие всех колонок в SQLite через PRAGMA table_info.
        Если существующих колонок не хватает, безопасно выполняет ALTER TABLE.
        """
        try:
            with sqlite3.connect(str(self.db_file)) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(trades)")
                existing_cols = {row[1] for row in cursor.fetchall()}

                cursor.execute("""
                CREATE TABLE IF NOT EXISTS trading_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    exchange_type TEXT NOT NULL DEFAULT 'MANUAL',
                    broker_type TEXT NOT NULL DEFAULT 'MANUAL',
                    api_key TEXT,
                    api_secret TEXT,
                    account_number TEXT,
                    initial_balance REAL DEFAULT 10000.0,
                    currency TEXT DEFAULT 'USD',
                    last_sync_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)

                cursor.execute("PRAGMA table_info(trading_accounts)")
                existing_acc_cols = {row[1] for row in cursor.fetchall()}
                for acc_col, acc_type in [
                    ("broker_type", "TEXT DEFAULT 'MANUAL'"),
                    ("initial_balance", "REAL DEFAULT 10000.0"),
                    ("currency", "TEXT DEFAULT 'USD'"),
                    ("last_sync_at", "TIMESTAMP"),
                ]:
                    if acc_col not in existing_acc_cols:
                        try:
                            cursor.execute(f"ALTER TABLE trading_accounts ADD COLUMN {acc_col} {acc_type}")
                        except Exception as ex:
                            print(f"[Migration] Warning adding account column {acc_col}: {ex}")

                cursor.execute("UPDATE trading_accounts SET broker_type = exchange_type WHERE broker_type IS NULL OR broker_type = 'MANUAL'")

                expected_columns = {
                    "account_id": "INTEGER",
                    "external_trade_id": "TEXT",
                    "status": "TEXT DEFAULT 'CLOSED'",
                    "stop_loss": "REAL",
                    "take_profit": "REAL",
                    "commission": "REAL DEFAULT 0.0",
                    "swap_fee": "REAL DEFAULT 0.0",
                    "gross_pnl": "REAL DEFAULT 0.0",
                    "net_pnl": "REAL DEFAULT 0.0",
                    "risk_amount": "REAL DEFAULT 0.0",
                    "r_multiple": "REAL DEFAULT 0.0",
                    "mae_price": "REAL",
                    "mfe_price": "REAL",
                    "mae_pct": "REAL DEFAULT 0.0",
                    "mfe_pct": "REAL DEFAULT 0.0",
                    "efficiency": "REAL DEFAULT 0.0",
                    "checklist_passed": "INTEGER DEFAULT 1",
                    "is_tilt": "INTEGER DEFAULT 0",
                    "tilt_reason": "TEXT",
                    "screenshot_path": "TEXT",
                    "notes": "TEXT DEFAULT ''",
                    "opened_at": "TIMESTAMP",
                    "closed_at": "TIMESTAMP",
                }

                for col_name, col_def in expected_columns.items():
                    if col_name not in existing_cols:
                        try:
                            cursor.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_def}")
                        except Exception as ex:
                            print(f"[Migration] Warning adding {col_name}: {ex}")

                # Синхронизация net_pnl с pnl для старых записей
                if "pnl" in existing_cols:
                    cursor.execute("UPDATE trades SET net_pnl = pnl WHERE net_pnl = 0.0 AND pnl != 0.0")
                    cursor.execute("UPDATE trades SET gross_pnl = pnl WHERE gross_pnl = 0.0 AND pnl != 0.0")
                if "date" in existing_cols:
                    cursor.execute("UPDATE trades SET closed_at = date WHERE closed_at IS NULL OR closed_at = ''")
                    cursor.execute("UPDATE trades SET opened_at = date WHERE opened_at IS NULL OR opened_at = ''")
                cursor.execute("UPDATE trades SET opened_at = datetime('now') WHERE opened_at IS NULL")
                cursor.execute("UPDATE trades SET closed_at = datetime('now') WHERE closed_at IS NULL")

                # Создание дефолтных счетов если таблица accounts пуста
                try:
                    cursor.execute("SELECT COUNT(*) FROM trading_accounts")
                    count = cursor.fetchone()[0]
                    if count == 0:
                        cursor.execute("""
                            INSERT INTO trading_accounts (id, name, exchange_type, broker_type, api_key, api_secret, account_number, initial_balance, currency, created_at)
                            VALUES 
                            (1, '🟡 Binance Futures', 'BINANCE', 'BINANCE', '', '', 'BIN-98421', 10000.0, 'USDT', datetime('now')),
                            (2, '🔵 MetaTrader 5 Prop', 'MT5', 'MT5', '', '', '5029184', 50000.0, 'USD', datetime('now')),
                            (3, '⚫ Bybit USDT Perp', 'BYBIT', 'BYBIT', '', '', 'BYB-71203', 15000.0, 'USDT', datetime('now'))
                        """)
                    else:
                        cursor.execute("UPDATE trading_accounts SET name = '🟡 Binance Futures', broker_type='BINANCE' WHERE id = 1 AND name LIKE '%Binance%'")
                        cursor.execute("UPDATE trading_accounts SET name = '🔵 MetaTrader 5 Prop', broker_type='MT5' WHERE id = 2 AND name LIKE '%MT5%'")
                        cursor.execute("UPDATE trading_accounts SET name = '⚫ Bybit USDT Perp', broker_type='BYBIT' WHERE id = 3 AND name LIKE '%Bybit%'")
                    # Распределение сделок без аккаунта
                    cursor.execute("UPDATE trades SET account_id = 1 WHERE account_id IS NULL AND (ticker LIKE '%USDT%' OR ticker LIKE '%BTC%' OR ticker LIKE '%ETH%')")
                    cursor.execute("UPDATE trades SET account_id = 2 WHERE account_id IS NULL")

                    # Санитизация аномальных R-Multiple и нулевого риска (коридор [-10.0, +20.0])
                    cursor.execute("""
                        UPDATE trades 
                        SET risk_amount = 100.0,
                            r_multiple = CASE 
                                WHEN net_pnl >= 0 THEN MIN(20.0, ROUND(net_pnl / 100.0, 2))
                                ELSE MAX(-10.0, ROUND(net_pnl / 100.0, 2))
                            END
                        WHERE risk_amount < 1.0 OR r_multiple < -10.0 OR r_multiple > 20.0
                    """)
                    cursor.execute("""
                        UPDATE trades 
                        SET r_multiple = CASE 
                            WHEN r_multiple > 20.0 THEN 20.0
                            WHEN r_multiple < -10.0 THEN -10.0
                            ELSE r_multiple
                        END
                    """)
                except Exception as ex:
                    print(f"[Migration] Accounts seed warning: {ex}")

                conn.commit()
        except Exception:
            pass

    def add_trade(
        self,
        ticker: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        volume: float,
        strategy_tag: str = "Общая",
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        commission: float = 0.0,
        swap_fee: float = 0.0,
        opened_at: Optional[datetime] = None,
        closed_at: Optional[datetime] = None,
        checklist_passed: bool = True,
        is_tilt: bool = False,
        tilt_reason: Optional[str] = None,
        notes: str = "",
        screenshot_path: Optional[str] = None,
        mae_price: Optional[float] = None,
        mfe_price: Optional[float] = None,
        account_id: Optional[int] = None,
        external_trade_id: Optional[str] = None,
        # Обратная совместимость с параметром date:
        date: Optional[datetime] = None,
    ) -> Trade:
        """
        Создает сделку и автоматически формирует начальные записи ордеров ENTRY и EXIT.
        """
        t_open = opened_at or date or (datetime.now() - timedelta(hours=2))
        t_close = closed_at or date or datetime.now()

        trade = Trade(
            account_id=account_id,
            external_trade_id=external_trade_id,
            ticker=ticker,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            volume=volume,
            strategy_tag=strategy_tag,
            stop_loss=stop_loss,
            take_profit=take_profit,
            commission=commission,
            swap_fee=swap_fee,
            opened_at=t_open,
            closed_at=t_close,
            checklist_passed=checklist_passed,
            is_tilt=is_tilt,
            tilt_reason=tilt_reason,
            notes=notes,
            screenshot_path=screenshot_path,
            mae_price=mae_price,
            mfe_price=mfe_price,
        )

        with self.SessionLocal() as session:
            session.add(trade)
            session.flush()

            # Автоматическая генерация дерева ордеров (1 вход и 1 выход)
            entry_order = TradeExecution(
                trade_id=trade.id,
                action="ENTRY",
                price=trade.entry_price,
                volume=trade.volume,
                fee=round(trade.commission / 2.0, 2),
                executed_at=trade.opened_at,
            )
            exit_order = TradeExecution(
                trade_id=trade.id,
                action="EXIT",
                price=trade.exit_price,
                volume=trade.volume,
                fee=round(trade.commission / 2.0, 2),
                executed_at=trade.closed_at,
            )
            session.add_all([entry_order, exit_order])
            session.commit()
            session.refresh(trade)
            return trade

    def update_trade(self, trade_id: int, **kwargs) -> Optional[Trade]:
        """
        Обновляет параметры сделки и пересчитывает производные метрики.
        """
        with self.SessionLocal() as session:
            trade = session.get(Trade, trade_id)
            if not trade:
                return None

            for key, value in kwargs.items():
                if hasattr(trade, key):
                    setattr(trade, key, value)

            trade.recalculate_metrics()
            session.commit()
            session.refresh(trade)
            return trade

    def delete_trade(self, trade_id: int) -> bool:
        """Удаляет сделку и каскадно связанные с ней ордера."""
        with self.SessionLocal() as session:
            trade = session.get(Trade, trade_id)
            if trade:
                session.delete(trade)
                session.commit()
                return True
            return False

    def get_trade_by_id(self, trade_id: int) -> Optional[Trade]:
        """Получает сделку по ID с загруженным деревом ордеров."""
        with self.SessionLocal() as session:
            stmt = select(Trade).where(Trade.id == trade_id)
            trade = session.scalars(stmt).first()
            if trade:
                # Чтение ордеров пока открыта сессия
                _ = len(trade.executions)
            return trade

    def get_trades(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        order_by_date_desc: bool = True,
        **kwargs,
    ) -> List[Trade]:
        """
        Универсальный запрос сделок с фильтрацией по дате, тикеру, стратегии, тильту и статусу.
        Поддерживает как словарь filters, так и именованные аргументы (**kwargs).
        """
        merged_filters = {**(filters or {}), **kwargs}
        if "ticker" in merged_filters:
            t_val = merged_filters.pop("ticker")
            if "query" not in merged_filters:
                merged_filters["query"] = t_val

        with self.SessionLocal() as session:
            stmt = select(Trade)

            if merged_filters:
                if merged_filters.get("query"):
                    q = f"%{merged_filters['query'].strip().lower()}%"
                    stmt = stmt.where(
                        Trade.ticker.ilike(q)
                        | Trade.strategy_tag.ilike(q)
                        | Trade.direction.ilike(q)
                        | Trade.notes.ilike(q)
                    )
                if merged_filters.get("direction"):
                    stmt = stmt.where(Trade.direction == merged_filters["direction"].strip().upper())
                if merged_filters.get("strategy_tag") and merged_filters["strategy_tag"] != "Все":
                    stmt = stmt.where(Trade.strategy_tag == merged_filters["strategy_tag"])
                if merged_filters.get("is_tilt") is not None:
                    stmt = stmt.where(Trade.is_tilt == merged_filters["is_tilt"])
                if merged_filters.get("exclude_tilt"):
                    stmt = stmt.where(Trade.is_tilt.is_(False))
                if merged_filters.get("result"):
                    res = merged_filters["result"].lower()
                    if res == "win":
                        stmt = stmt.where(Trade.net_pnl > 0)
                    elif res == "loss":
                        stmt = stmt.where(Trade.net_pnl < 0)
                    elif res == "tilt":
                        stmt = stmt.where(Trade.is_tilt.is_(True))
                if merged_filters.get("account_id") is not None:
                    raw_acc = str(merged_filters["account_id"]).strip().lower()
                    if raw_acc not in ["-1", "0", "all", "none", "", "все", "все счета", "все торговые счета (портфель)"]:
                        try:
                            acc_id_int = int(merged_filters["account_id"])
                            if acc_id_int > 0:
                                stmt = stmt.where(Trade.account_id == acc_id_int)
                        except ValueError:
                            pass
                if merged_filters.get("date_from"):
                    d_from = merged_filters["date_from"]
                    if isinstance(d_from, date) and not isinstance(d_from, datetime):
                        d_from = datetime.combine(d_from, datetime.min.time())
                    stmt = stmt.where(Trade.closed_at >= d_from)
                if merged_filters.get("date_to"):
                    d_to = merged_filters["date_to"]
                    if isinstance(d_to, date) and not isinstance(d_to, datetime):
                        d_to = datetime.combine(d_to, datetime.max.time())
                    stmt = stmt.where(Trade.closed_at <= d_to)

            if order_by_date_desc:
                stmt = stmt.order_by(Trade.closed_at.desc(), Trade.id.desc())
            else:
                stmt = stmt.order_by(Trade.closed_at.asc(), Trade.id.asc())

            if offset:
                stmt = stmt.offset(offset)
            if limit:
                stmt = stmt.limit(limit)

            trades = list(session.scalars(stmt).all())
            # Подгрузка ордеров в память
            for t in trades:
                _ = len(t.executions)
            return trades

    def get_all_trades(self, order_by_date_desc: bool = True) -> List[Trade]:
        """Получение всех сделок (алиас для совместимости)."""
        return self.get_trades(order_by_date_desc=order_by_date_desc)

    def get_distinct_strategies(self) -> List[str]:
        """Возвращает список всех уникальных стратегий из базы данных."""
        with self.SessionLocal() as session:
            stmt = select(Trade.strategy_tag).distinct().order_by(Trade.strategy_tag)
            res = session.scalars(stmt).all()
            return [s for s in res if s] or ["Общая", "Breakout", "Trend Following", "Scalping", "Swing"]

    def get_accounts(self) -> List[TradingAccount]:
        """Возвращает список всех подключенных торговых счетов."""
        with self.SessionLocal() as session:
            stmt = select(TradingAccount).order_by(TradingAccount.id.asc())
            return list(session.scalars(stmt).all())

    def get_account_by_id(self, account_id: int) -> Optional[TradingAccount]:
        """Получает аккаунт по ID."""
        with self.SessionLocal() as session:
            return session.get(TradingAccount, account_id)

    def add_account(
        self,
        name: str,
        exchange_type: str = "MANUAL",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        account_number: Optional[str] = None,
        initial_balance: float = 10000.0,
        currency: str = "USD",
        broker_type: Optional[str] = None,
    ) -> TradingAccount:
        """Создает новый торговый счет / подключение биржи."""
        b_type = (broker_type or exchange_type or "MANUAL").strip().upper()
        curr = (currency or "USD").strip().upper()
        with self.SessionLocal() as session:
            account = TradingAccount(
                name=name.strip(),
                exchange_type=b_type,
                api_key=api_key.strip() if api_key else None,
                api_secret=api_secret.strip() if api_secret else None,
                account_number=account_number.strip() if account_number else None,
                initial_balance=float(initial_balance or 10000.0),
                currency=curr,
                last_sync_at=None,
                created_at=datetime.now(),
            )
            session.add(account)
            session.commit()
            session.refresh(account)
            return account

    def update_account_sync_time(self, account_id: int, sync_dt: Optional[datetime] = None) -> bool:
        """Обновляет время последней синхронизации счета."""
        if sync_dt is None:
            sync_dt = datetime.now()
        with self.SessionLocal() as session:
            acc = session.get(TradingAccount, account_id)
            if acc:
                acc.last_sync_at = sync_dt
                session.commit()
                return True
        return False

    def delete_account(self, account_id: int) -> bool:
        """Удаляет счет и каскадно отвязывает сделки."""
        with self.SessionLocal() as session:
            acc = session.get(TradingAccount, account_id)
            if not acc:
                return False
            session.delete(acc)
            session.commit()
            return True

    def get_trade_by_external_id(self, external_id: str) -> Optional[Trade]:
        """Ищет сделку по уникальному биржевому ID для исключения дубликатов."""
        if not external_id:
            return None
        with self.SessionLocal() as session:
            stmt = select(Trade).where(Trade.external_trade_id == str(external_id))
            return session.scalars(stmt).first()

    def add_execution(
        self,
        trade_id: int,
        action: str,
        price: float,
        volume: float,
        fee: float = 0.0,
        executed_at: Optional[datetime] = None,
    ) -> Optional[TradeExecution]:
        """
        Добавляет частичный ордер в сделку и пересчитывает средневзвешенный VWAP.
        """
        with self.SessionLocal() as session:
            trade = session.get(Trade, trade_id)
            if not trade:
                return None

            ex = TradeExecution(
                trade_id=trade_id,
                action=action.strip().upper(),
                price=price,
                volume=volume,
                fee=fee,
                executed_at=executed_at or datetime.now(),
            )
            session.add(ex)
            session.flush()

            # Обновление параметров родительской сделки
            trade.recalculate_from_executions()
            session.commit()
            session.refresh(ex)
            return ex

    def delete_execution(self, execution_id: int) -> bool:
        """Удаляет ордер и пересчитывает родительскую сделку."""
        with self.SessionLocal() as session:
            ex = session.get(TradeExecution, execution_id)
            if not ex:
                return False
            trade_id = ex.trade_id
            session.delete(ex)
            session.flush()

            trade = session.get(Trade, trade_id)
            if trade:
                trade.recalculate_from_executions()
            session.commit()
            return True

    def clear_all_trades(self) -> None:
        """Очистка всех сделок."""
        with self.SessionLocal() as session:
            trades = session.scalars(select(Trade)).all()
            for t in trades:
                session.delete(t)
            session.commit()

    def seed_demo_data_if_empty(self) -> None:
        """
        Заполняет базу данных 9 разнообразными реалистичными сделками:
        акции и криптовалюты, стоп-лоссы, комиссии, ордера Scale-In/Out,
        а также 2 сделки с тильтом для тестирования behavioral-детектора.
        """
        if self.get_all_trades():
            return

        now = datetime.now()

        demos = [
            # 1. Системный прибыльный тренд по BTC
            {
                "ticker": "BTC/USDT", "direction": "LONG", "entry_price": 63200.0, "exit_price": 66800.0,
                "volume": 0.45, "strategy_tag": "Trend Following", "stop_loss": 62100.0, "take_profit": 67000.0,
                "commission": 18.5, "swap_fee": 4.2, "opened_at": now - timedelta(days=9, hours=4),
                "closed_at": now - timedelta(days=8, hours=2), "checklist_passed": True, "is_tilt": False,
                "notes": "Чистый пробой дневного диапазона с подтверждением объема на 4H.",
                "account_id": 1,
            },
            # 2. Быстрый скальп по ETH с частичным добором (Scale-In)
            {
                "ticker": "ETH/USDT", "direction": "SHORT", "entry_price": 2680.0, "exit_price": 2540.0,
                "volume": 2.5, "strategy_tag": "Scalping", "stop_loss": 2730.0, "take_profit": 2520.0,
                "commission": 12.0, "swap_fee": 1.5, "opened_at": now - timedelta(days=7, hours=6),
                "closed_at": now - timedelta(days=7, hours=2), "checklist_passed": True, "is_tilt": False,
                "notes": "Ложный пробой уровня сопротивления $2,700.",
                "account_id": 1,
                "executions": [
                    ("ENTRY", 2700.0, 1.0, 4.8, now - timedelta(days=7, hours=6)),
                    ("ADD", 2666.6, 1.5, 7.2, now - timedelta(days=7, hours=5)),
                    ("EXIT", 2540.0, 2.5, 0.0, now - timedelta(days=7, hours=2)),
                ],
            },
            # 3. Свинг по NVDA
            {
                "ticker": "NVDA", "direction": "LONG", "entry_price": 136.5, "exit_price": 144.2,
                "volume": 25.0, "strategy_tag": "Breakout", "stop_loss": 133.0, "take_profit": 145.0,
                "commission": 4.5, "swap_fee": 0.0, "opened_at": now - timedelta(days=6, hours=5),
                "closed_at": now - timedelta(days=5, hours=1), "checklist_passed": True, "is_tilt": False,
                "notes": "Выход из треугольника перед отчетом.",
                "account_id": 2,
            },
            # 4. Неудачный вход по SOL (системный стоп-лосс)
            {
                "ticker": "SOL/USDT", "direction": "LONG", "entry_price": 172.0, "exit_price": 165.5,
                "volume": 12.0, "strategy_tag": "Breakout", "stop_loss": 166.0, "take_profit": 185.0,
                "commission": 6.8, "swap_fee": 1.2, "opened_at": now - timedelta(days=4, hours=8),
                "closed_at": now - timedelta(days=4, hours=4), "checklist_passed": True, "is_tilt": False,
                "notes": "Защитный стоп сработал четко по плану, потеря < 1% депо.",
                "account_id": 1,
            },
            # 5. ТИЛЬТ-СДЕЛКА 1: Revenge Trade (открыта через 2 мин после стопа SOL с удвоенным риском)
            {
                "ticker": "SOL/USDT", "direction": "SHORT", "entry_price": 165.0, "exit_price": 171.2,
                "volume": 25.0, "strategy_tag": "Scalping", "stop_loss": 167.0, "take_profit": 155.0,
                "commission": 14.5, "swap_fee": 0.0, "opened_at": now - timedelta(days=4, hours=3, minutes=58),
                "closed_at": now - timedelta(days=4, hours=2), "checklist_passed": False, "is_tilt": True,
                "tilt_reason": "Revenge Trade (< 3 мин после лосса) + Превышение риска x2",
                "notes": "Эмоциональный реверс позиции сразу после получения стопа. Грубое нарушение правил.",
                "account_id": 1,
            },
            # 6. Отскок по AAPL
            {
                "ticker": "AAPL", "direction": "LONG", "entry_price": 224.5, "exit_price": 231.8,
                "volume": 15.0, "strategy_tag": "Swing", "stop_loss": 221.0, "take_profit": 232.0,
                "commission": 3.2, "swap_fee": 0.0, "opened_at": now - timedelta(days=3, hours=5),
                "closed_at": now - timedelta(days=2, hours=3), "checklist_passed": True, "is_tilt": False,
                "notes": "Тест 50 EMA на дневном графике.",
                "account_id": 2,
            },
            # 7. ТИЛЬТ-СДЕЛКА 2: Вход без подтверждения и чек-листа по TSLA
            {
                "ticker": "TSLA", "direction": "SHORT", "entry_price": 248.0, "exit_price": 256.5,
                "volume": 18.0, "strategy_tag": "Breakout", "stop_loss": 252.0, "take_profit": 235.0,
                "commission": 5.0, "swap_fee": 0.0, "opened_at": now - timedelta(days=2, hours=1),
                "closed_at": now - timedelta(days=1, hours=6), "checklist_passed": False, "is_tilt": True,
                "tilt_reason": "Нарушение чек-листа: вход против локального моментума",
                "notes": "Попытка поймать вершину на сильном объеме покупателя.",
                "account_id": 2,
            },
            # 8. Фиксация прибыли по ETH (Trend)
            {
                "ticker": "ETH/USDT", "direction": "LONG", "entry_price": 2510.0, "exit_price": 2695.0,
                "volume": 1.8, "strategy_tag": "Trend Following", "stop_loss": 2440.0, "take_profit": 2700.0,
                "commission": 13.5, "swap_fee": 3.8, "opened_at": now - timedelta(days=1, hours=5),
                "closed_at": now - timedelta(hours=8), "checklist_passed": True, "is_tilt": False,
                "notes": "Классический ретест уровня $2,500 с удержанием 4H свечи.",
                "account_id": 1,
            },
            # 9. Интрадей пробой BTC
            {
                "ticker": "BTC/USDT", "direction": "LONG", "entry_price": 67100.0, "exit_price": 68450.0,
                "volume": 0.3, "strategy_tag": "Breakout", "stop_loss": 66400.0, "take_profit": 68500.0,
                "commission": 15.0, "swap_fee": 1.0, "opened_at": now - timedelta(hours=6),
                "closed_at": now - timedelta(hours=1), "checklist_passed": True, "is_tilt": False,
                "notes": "Импульсный пробой ATH консолидации.",
                "account_id": 1,
            },
        ]

        for item in demos:
            execs = item.pop("executions", None)
            t = self.add_trade(**item)
            if execs:
                # Если были кастомные ордера Scale-in/out, пересоздаем их
                with self.SessionLocal() as session:
                    # Удаляем дефолтные 2 ордера
                    for ex in session.get(Trade, t.id).executions:
                        session.delete(ex)
                    session.flush()

                    for act, pr, vol, fee, dt in execs:
                        session.add(TradeExecution(
                            trade_id=t.id, action=act, price=pr, volume=vol, fee=fee, executed_at=dt
                        ))
                    session.commit()
                    tr_obj = session.get(Trade, t.id)
                    tr_obj.recalculate_from_executions()
                    session.commit()

    # Совместимость
    seed_demo_data = seed_demo_data_if_empty
