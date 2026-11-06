# AUTOPILOT STATE — TRADING JOURNAL PRO
*Autonomous Principal Python/Flet Architect & Quant Engineer Loop*

## Current Phase
- **Iteration:** 1 (Completed) -> Starting Iteration 2
- **Current Phase:** Phase 4: Full Regression & Close Loop
- **Status:** All 33 Tests Green (100% Passing). Feature Deployed.
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
- [x] **Monte Carlo Simulator:** 10,000 bootstrap simulations accounting for initial account balance and equity cone percentiles (5th, 50th, 95th).
- [x] **Tilt & Psychology Engine:** Detects revenge trading (<10 min cooldown after loss), over-risking (>2x avg risk), and break-even violation patterns.
- [x] **Wave AI Coach:** Rule-based quant trading coach diagnosing fee drag, MAE/MFE retention loss, and risk discipline.
- [x] **UI Polish Sprint:**
  - Trade Modal and Account Modal layout overflows fixed with responsive scrolling.
  - Monte Carlo card redesigned to a vertical stacked card layout with 4 metric chips and full-width cone chart.
  - Underwater drawdown chart negative axis collision resolved.
  - Backtest candlestick chart expanded from 400px fixed width to dynamic responsive width (`CrossAxisAlignment.STRETCH`).
- [x] **High-Performance Local Server Runner:** `run_local_server.py` with multi-adapter IP detection, VPN warning, terminal ASCII QR-code, and 1-click `ЗАПУСК_СЕРВЕРА.bat`.
- [x] **Total QA Suite (33 tests):**
  - Level 1: Static Analysis & Architecture (`tests/test_static_architecture.py`) — 3 tests.
  - Level 2: Quant & Math Engine (`tests/test_quant_math.py`) — 6 tests (including SQN, Sharpe & Sortino).
  - Level 3: Database & ORM Integration (`tests/test_database_integration.py`) — 4 tests.
  - Level 4: Async & Resilience (`tests/test_async_resilience.py`) — 4 tests.
  - Level 5: Headless UI Render (`tests/test_headless_ui_render.py`) — 4 tests.
  - Legacy regression suite — 12 tests.

---

## Competitor Backlog (R&D for Iteration 2+)
- [ ] **TradeZella / TraderWaves:** Trading Session Performance Matrix (Asia, London, New York) with volume, winrate, and expectancy breakdown per session.
- [ ] **TradeZella:** Interactive Day-of-Week & Hour-of-Day PnL Heatmap with tooltips.
- [ ] **TraderSync / Linear:** Linear-style keyboard shortcut command palette (Ctrl+K) for instant trade lookup and modal triggers.
- [ ] **Edgewonk:** Setup / Strategy Efficiency Matrix (ranking strategy tags by profit factor & SQN).
