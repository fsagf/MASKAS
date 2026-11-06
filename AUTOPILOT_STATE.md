# AUTOPILOT STATE — TRADING JOURNAL PRO
*Autonomous Principal Python/Flet Architect & Quant Engineer Loop*

## Current Phase
- **Iteration:** 7 (Completed) -> Starting Iteration 8
- **Current Phase:** Phase 4: Full Regression & Close Loop
- **Status:** All 38 Tests Green (100% Passing). Linear-style Command Palette with Dynamic Strategy Filters & Ticker Search Deployed.
- **Active Branch:** `redesign` (local) / `main` (mirror: `C:\Users\maksi\OneDrive\Documents\GitHub\MASKAS`)
- **Server Status:** 🟢 Active & Healthy on `http://localhost:8550` and LAN `http://192.168.100.6:8550` (Daemon task running)

---

## Known Issues & User Explanations
1. **Localtunnel Hang (`twenty-forks-enter.loca.lt`):**
   - User screenshot showed Chrome tab `twenty-forks-enter.loca.lt` hanging indefinitely on the Flet fish splash screen.
   - **Root Cause:** Localtunnel (`loca.lt`) drops or delays persistent WebSocket packets (`ws://`) required by Flutter/Flet, and rate-limits heavy WASM bundles (`canvaskit.wasm`) over slow internet connections.
   - **Resolution:** The user should switch to the local address `http://localhost:8550` (or click the tab `Trading Journal Pro` already opened in Chrome).
2. **Wi-Fi Network Change:**
   - Active Wi-Fi IPv4 changed to `192.168.100.6` (ProtonVPN active on `10.2.0.2`).
   - Old IP `172.20.10.4` is no longer reachable. Mobile devices should now use `http://192.168.100.6:8550` (with ProtonVPN "Allow LAN" enabled).

---

## Implemented Features & UI/UX History
- [x] **Theme & Design System:** Deep Dark / Zinc palette (`#090A0F`, `#12151E`, `#1E2333`, `#10B981`, `#EF4444`, `#7C5CFF`).
- [x] **Quant Metrics Engine:** Recalculates Net PnL, Winrate, Profit Factor, Expectancy, MAE/MFE Retention, R-Multiple clamped in `[-10, 20]`.
- [x] **Van Tharp System Quality Number (SQN) & Quant Ratios (Iteration 1):**
  - Added Van Tharp SQN computation: \(\text{SQN} = \sqrt{\min(N, 100)} \times \frac{\text{Mean}(R)}{\text{StdDev}(R)}\).
  - Categorization into ratings: Poor (<1.6), Average (1.6-2.0), Good (2.0-2.5), Excellent (2.5-3.0), Superb (3.0-5.0), Holy Grail (>5.0).
  - Added Sharpe Ratio & Sortino Ratio (downside deviation penalization) in `DashboardMetrics`.
  - Upgraded Dashboard R-Multiple KPI card with real-time SQN rating subtitle.
  - Upgraded Monte Carlo Quant Panel with 4 adaptive metric mini-boxes: Risk of Ruin, SQN Van Tharp, Sharpe / Sortino, and Expectancy Run.
- [x] **Session Performance Matrix (Iteration 2):**
  - Implemented `AnalyticsService.calculate_session_matrix(trades)`: categorizes trades by UTC session (Asian 00:00–08:00, London 08:00–13:00, New York 13:00–21:00, Off-Hours 21:00–00:00).
  - Calculates per session: Winrate %, Net PnL $, Profit Factor, Expectancy, Trades Count, Best & Worst trades.
  - Detects Top Session (leader) and Risk Zone (drawdown session).
  - Created interactive card `_build_session_matrix_card` with responsive progress bars, session colors, and leader highlight chips.
  - Integrated into `DashboardView` below the Monte Carlo and Calendar row.
- [x] **Interactive Day-of-Week & Hour-of-Day PnL Heatmap (Iteration 3):**
  - Implemented `AnalyticsService.calculate_time_heatmap(trades)` in `analytics.py`: 7x24 grid mapping profit/loss to days (Mon–Sun) and hours (00–23 UTC).
  - Created `TimeHeatmap` component in `ui/components/time_heatmap.py` with responsive horizontal scrolling, color-scaled cells (emerald profit / coral loss), tooltips with trade count and winrate, right-hand daily totals, and peak hour highlight chip.
  - Integrated into `DashboardView` with error-boundary updates.
- [x] **Kelly Criterion & Streaks Engine (Iteration 4):**
  - Implemented `AnalyticsService.calculate_kelly_criterion(trades)`: computes full Kelly fraction \(f^* = \frac{p(b+1)-1}{b}\) and recommended Half-Kelly risk fraction (clamped to safe ceiling 25.0%).
  - Implemented `AnalyticsService.calculate_streaks(trades)`: computes max consecutive wins, max consecutive losses, current active streak (\(+N\) or \(-N\)), and average sequence lengths.
  - Integrated into `DashboardMetrics`: `kelly_fraction_pct`, `half_kelly_pct`, `max_win_streak`, `max_loss_streak`, `current_streak`.
  - Upgraded `DashboardView` trade count KPI card with live streak indicator (`Серия: +3 • Ср: +$120.0`).
  - Added dynamic Half-Kelly risk guidance to Monte Carlo Quant footer.
  - Added AI Coach rule in `WaveAICoachService`: recommends position sizing according to Kelly Criterion.
- [x] **Strategy & Setup Leaderboard Matrix (Iteration 5):**
  - Implemented `AnalyticsService.calculate_strategy_leaderboard(trades)`: aggregates and ranks trading strategies/playbook setups by Net PnL, Profit Factor, Winrate, and SQN.
  - Created `_build_strategy_leaderboard_card` in `ui/views/dashboard.py` with medal badges (#1 Gold, #2 Silver, #3 Bronze), winrate progress bars, and profit factor indicators.
  - Integrated into `DashboardView` between Session Matrix and Time Heatmap.
- [x] **Trade Duration & Holding Time Performance Matrix (Iteration 6):**
  - Implemented `AnalyticsService.calculate_duration_matrix(trades)`: segments trades into 5 holding duration buckets (`<15m` Scalp, `15m-1h` Short Intraday, `1h-4h` Mid Intraday, `4h-24h` Day Trade, `>24h` Swing).
  - Computes Winrate %, Net PnL, Profit Factor, Avg Duration, and Total Trades for each bracket.
  - Identifies optimal holding period bracket (`optimal_bracket`).
  - Created `_build_duration_analysis_card` in `ui/views/dashboard.py` with duration bracket cards, KPI progress bars, and optimal duration badge.
  - Integrated into `DashboardView` beneath the Strategy Leaderboard.
- [x] **Linear-style Command Palette (Ctrl+K) & Dynamic Strategy Filters (Iteration 7):**
  - Re-architected `CommandBar` with category selector pills (`Все`, `⚡ Действия`, `🏷️ Стратегии`, `📜 Сделки`).
  - Dynamic discovery of active strategy tags from database trades (`Breakout`, `SMC Order Block`, `Pullback`, `Trend Following`, `Scalping`, `Range`).
  - Added `strategy_<tag>` action: instantly switches to `JournalView`, populates search query with setup name, filters trades list, and presents modern snackbar feedback.
  - Modernized `AppLayout` snackbar notifications to standard `page.overlay` pattern.
  - Added Linear-style footer shortcut chips (`↵ Select`, `ESC Close`, `Ctrl+K Shortcut`).
  - Added headless UI regression tests verifying category switching, search filtering, and Enter submission.
- [x] **Total QA Suite (38 tests):**
  - Level 1: Static Analysis & Architecture (`tests/test_static_architecture.py`) — 3 tests.
  - Level 2: Quant & Math Engine (`tests/test_quant_math.py`) — 11 tests.
  - Level 3: Database & ORM Integration (`tests/test_database_integration.py`) — 4 tests.
  - Level 4: Async & Resilience (`tests/test_async_resilience.py`) — 4 tests.
  - Level 5: Headless UI Render (`tests/test_headless_ui_render.py`) — 4 tests (including CommandBar Linear UX).
  - Legacy regression suite — 12 tests.

---

## Competitor Backlog (R&D for Iteration 8+)
- [ ] **TraderVue / TradeZella:** Asset Class & Symbol Concentration Risk Matrix (Crypto vs Forex vs Equities breakdown with volume, winrate, and drawdown exposure) (Iteration 8 Target).
- [ ] **Edgewonk:** Emotional State & Psychology Matrix (tracking Discipline, Fear, Greed, FOMO impact on PnL).
