# AUTOPILOT STATE — TRADING JOURNAL PRO
*Autonomous Principal Python/Flet Architect & Quant Engineer Loop*

## Current Phase
- **Iteration:** 4 (Completed) -> Starting Iteration 5
- **Current Phase:** Phase 4: Full Regression & Close Loop
- **Status:** All 36 Tests Green (100% Passing). Kelly Criterion & Streaks Engine Deployed.
- **Active Branch:** `redesign` (local) / `main` (mirror: `C:\Users\maksi\OneDrive\Documents\GitHub\MASKAS`)
- **Server Status:** 🟢 Active & Healthy on `http://localhost:8550` and LAN `http://172.20.10.4:8550` (Daemon task running)

---

## Known Issues & User Explanations
1. **Localtunnel Hang (`twenty-forks-enter.loca.lt`):**
   - User screenshot showed Chrome tab `twenty-forks-enter.loca.lt` hanging indefinitely on the Flet fish splash screen.
   - **Root Cause:** Localtunnel (`loca.lt`) drops or delays persistent WebSocket packets (`ws://`) required by Flutter/Flet, and rate-limits heavy WASM bundles (`canvaskit.wasm`) over slow internet connections.
   - **Resolution:** The next browser tab on the user's screen — `Trading Journal Pro` — is already open and running. Direct Wi-Fi LAN address `http://172.20.10.4:8550` loads instantaneously with zero tunnel latency.
2. **Offline / Low-Bandwidth Optimizations:**
   - WebRenderer is configured to `ft.WebRenderer.AUTO` for minimal bandwidth usage on mobile devices.

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
- [x] **Monte Carlo Simulator:** 10,000 bootstrap simulations accounting for initial account balance and equity cone percentiles (5th, 50th, 95th).
- [x] **Tilt & Psychology Engine:** Detects revenge trading (<10 min cooldown after loss), over-risking (>2x avg risk), and break-even violation patterns.
- [x] **Wave AI Coach:** Rule-based quant trading coach diagnosing fee drag, MAE/MFE retention loss, risk discipline, and Kelly sizing.
- [x] **High-Performance Local Server Runner:** `run_local_server.py` with multi-adapter IP detection, VPN warning, terminal ASCII QR-code, and 1-click `ЗАПУСК_СЕРВЕРА.bat`.
- [x] **Total QA Suite (36 tests):**
  - Level 1: Static Analysis & Architecture (`tests/test_static_architecture.py`) — 3 tests.
  - Level 2: Quant & Math Engine (`tests/test_quant_math.py`) — 9 tests (including SQN, Sharpe/Sortino, Session Matrix, Time Heatmap, Kelly & Streaks).
  - Level 3: Database & ORM Integration (`tests/test_database_integration.py`) — 4 tests.
  - Level 4: Async & Resilience (`tests/test_async_resilience.py`) — 4 tests.
  - Level 5: Headless UI Render (`tests/test_headless_ui_render.py`) — 4 tests (including Time Heatmap and Session Matrix renders).
  - Legacy regression suite — 12 tests.

---

## Competitor Backlog (R&D for Iteration 5+)
- [ ] **Edgewonk:** Strategy / Setup Leaderboard with 1-click filter in Journal (Iteration 5 Target).
- [ ] **TraderSync / Linear:** Linear-style keyboard shortcut command palette (Ctrl+K) for instant trade lookup and modal triggers.
- [ ] **TradeZella:** Trade Duration vs PnL distribution scatter analysis.
