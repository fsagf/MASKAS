# AUTOPILOT STATE — TRADING JOURNAL PRO
*Autonomous Principal Python/Flet Architect & Quant Engineer Loop*

## Current Phase
- **Iteration:** 1
- **Current Phase:** Phase 2: Competitor & Design Research -> Phase 3: Implementation
- **Status:** Phase 1 Complete (Total QA Suite 32/32 Passing). Starting Phase 2 & 3.
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
- [x] **Monte Carlo Simulator:** 10,000 bootstrap simulations accounting for initial account balance and equity cone percentiles (5th, 50th, 95th).
- [x] **Tilt & Psychology Engine:** Detects revenge trading (<10 min cooldown after loss), over-risking (>2x avg risk), and break-even violation patterns.
- [x] **Wave AI Coach:** Rule-based quant trading coach diagnosing fee drag, MAE/MFE retention loss, and risk discipline.
- [x] **UI Polish Sprint:**
  - Trade Modal and Account Modal layout overflows fixed with responsive scrolling.
  - Monte Carlo card redesigned to a vertical stacked card layout with 3 metric chips and full-width cone chart.
  - Underwater drawdown chart negative axis collision resolved.
  - Backtest candlestick chart expanded from 400px fixed width to dynamic responsive width (`CrossAxisAlignment.STRETCH`).
- [x] **High-Performance Local Server Runner:** `run_local_server.py` with multi-adapter IP detection, VPN warning, terminal ASCII QR-code, and 1-click `ЗАПУСК_СЕРВЕРА.bat`.
- [x] **Total QA Suite (32 tests):**
  - Level 1: Static Analysis & Architecture (`tests/test_static_architecture.py`) — AST compilation, no circular imports, no deprecated Flet calls.
  - Level 2: Quant & Math Engine (`tests/test_quant_math.py`) — Zero division protection, R-multiple clamping, Monte Carlo percentiles, Tilt detection.
  - Level 3: Database & ORM Integration (`tests/test_database_integration.py`) — SQLite CRUD, `selectinload` relations, VWAP scale-in/out, CSV bulk import, Fernet encryption.
  - Level 4: Async & Resilience (`tests/test_async_resilience.py`) — Market data timeout fallback, synthetic candle generator, graceful error handling.
  - Level 5: Headless UI Render (`tests/test_headless_ui_render.py`) — Headless instantiation of AppLayout, DashboardView, JournalView, BacktestView, TradeModal, AccountModal.

---

## Competitor Backlog (R&D)
- [ ] **Edgewonk:** System Quality Number (SQN) by Van Tharp (\(SQN = \sqrt{N} \times \frac{\text{Expectancy}}{\text{StdDev}(R)}\)) to rank setup quality.
- [ ] **TradeZella / TraderWaves:** Trading Session Performance Matrix (Asia, London, New York) with volume, winrate, and expectancy breakdown.
- [ ] **TradeZella:** Interactive Day-of-Week & Hour-of-Day PnL Heatmap with tooltips.
- [ ] **TraderSync / Linear:** Linear-style keyboard shortcut command palette (Ctrl+K) for instant trade lookup and modal triggers.
- [ ] **Quant Feature:** Sharpe & Sortino Ratio calculation taking into account downside deviation.

---

## Next Step: Iteration 1 Feature Implementation
- **Quant Feature:** Van Tharp's System Quality Number (SQN) + Setup Quality Rating in `DashboardMetrics` and `analytics.py`.
- **UI/UX Refinement:** SQN Rating Badge & KPI Chip in `DashboardView` with colored grade (`Poor`, `Average`, `Good`, `Excellent`, `Holy Grail`).
