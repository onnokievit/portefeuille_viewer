# Portfolio Viewer v0.5 - Development Notes
**Date:** October 14, 2025  
**Session Summary:** Comprehensive development session covering CRUD operations, snapshot architecture, IBKR integration, and architectural decisions.

---

## 📋 Table of Contents
1. [Session Overview](#session-overview)
2. [Implemented Features](#implemented-features)
3. [Architecture & Design Decisions](#architecture--design-decisions)
4. [Technical Stack](#technical-stack)
5. [IBKR Integration](#ibkr-integration)
6. [Known Limitations](#known-limitations)
7. [Future Enhancements](#future-enhancements)
8. [Code Statistics](#code-statistics)
9. [Troubleshooting & Lessons Learned](#troubleshooting--lessons-learned)

---

## 📝 Session Overview

### Major Achievements
- ✅ Implemented complete CRUD operations for Orders tab
- ✅ Fixed snapshot synchronization issues
- ✅ Enhanced error logging with symbol identification
- ✅ Improved date formatting (removed timestamps)
- ✅ Documented IBKR subscription strategies
- ✅ Analyzed option price retrieval complexities

### Key Discussions
- Snapshot architecture and synchronization patterns
- IBKR API subscription limits and rotation strategies
- European options and conId requirements
- Git workflow for multiple experiment versions
- Code size analysis and industry benchmarking

---

## 🚀 Implemented Features

### 1. DELETE Functionality (Orders Tab)

**Implementation Date:** October 14, 2025

**Problem:**
- Initial implementation used `order_id` for deletion
- `order_id` is a grouping field (same for paired orders)
- Deleting by `order_id` would remove ALL records with that order_id

**Solution:**
- Changed to **Id-based deletion** (Id = Primary Key)
- Collect `EDIT_ID` and `EDIT_ID2` from selected row
- Delete specific records by their unique Ids
- Supports single orders (only EDIT_ID) and paired orders (EDIT_ID + EDIT_ID2)

**Key Code:**
```python
# orders_tab.py, line ~1168
def delete_order(self):
    """Delete selected order(s) by their unique Id(s)"""
    edit_id = row_data.get("EDIT_ID")
    edit_id2 = row_data.get("EDIT_ID2")
    
    ids_to_delete = [edit_id]
    if edit_id2 and edit_id2 != edit_id:
        ids_to_delete.append(edit_id2)
    
    # Delete from database
    deleted_count = repository.delete_transactions_by_ids(ids_to_delete)
    
    # Update snapshots
    self._delete_transactions_from_snapshot_by_ids(ids_to_delete)
    self._refresh_derived_snapshots()
```

**Database:**
```python
# repository.py, line ~311
def delete_transactions_by_ids(ids_to_delete: list[int]) -> int:
    """Delete transactions WHERE Id IN (?)"""
    placeholders = ','.join(['?'] * len(ids_to_delete))
    sql = f"DELETE FROM transacties_bron_data_org WHERE Id IN ({placeholders})"
```

---

### 2. Snapshot Synchronization Fix

**Problem:**
- GUI not updating after INSERT/UPDATE operations
- Only DELETE triggered snapshot refresh
- `snapshot_aandelen` remained stale after database changes

**Root Cause:**
- Missing `_refresh_derived_snapshots()` calls after INSERT/UPDATE
- Derived snapshots (`snapshot_aandelen`, `snapshot_load_open_opties_from_tx`, etc.) not regenerated

**Solution:**
Added `_refresh_derived_snapshots()` calls in `opslaan_orders()`:
```python
# orders_tab.py
def opslaan_orders(self):
    if is_new_transaction:
        # INSERT logic
        self._add_transaction_to_snapshot(new_id)
        self._refresh_derived_snapshots()  # ← ADDED (line 811)
    else:
        # UPDATE logic
        self._update_transaction_in_snapshot(trans_id)
        self._refresh_derived_snapshots()  # ← ADDED (line 772)
```


### Snapshot Architecture

This section gives a complete, implementation-oriented snapshot architecture for the app. It explains the snapshot keys, lifecycle, concurrency model, signals, optional persistence, recommended schema names, and verification steps.

High-level goals:
- Single source of truth for DB-derived data (base snapshot)
- Deterministic derived snapshots for UI consumption
- Lightweight live snapshots for frequent price updates
- Explicit lifecycle and signal-based synchronization for UI refresh

1) Snapshot keys (recommended canonical names)
- `repository_snapshot_alle_transacties` (base snapshot loaded from DB)
- `repository_snapshot_aandelen` (derived static aggregation)
- `repository_snapshot_load_open_opties` (derived static open options)
- `repository_snapshot_open_sprinters` (derived static open sprinters)
- `repository_snapshot_gesloten_opties` (derived closed options)
- `repository_snapshot_gesloten_sprinters` (derived closed sprinters)
- `snapshot_asset_rollup_data` (reference table: asset metadata)
- `repository_snapshot_sprinter_referentie_data` (sprinter ref data)

- Live snapshots (updated by aggregators / PortfolioEngine):
    - `aggregator_snapshot_aandelen_live` (live aggregated aandelen)
    - `aggregator_snapshot_load_open_opties_from_tx_live` (live opties)
    - `aggregator_snapshot_open_sprinters_live` (live sprinters with prices)
    - `snapshot_aggregated_portfolio` (portfolio-level aggregation)

- Metadata stored on the snapshot store:
    - `active_database_name: str|None` — current DB name
    - `snapshot_timestamps: dict[str, datetime]` — optional timestamps for each key
    - `snapshot_source: dict[str,str]` — optional source/version info for derived snapshots

2) Snapshot lifecycle (recommended operations)
- Initialize app: `SNAPSHOT_STORE.clear()` (empty) and then `repository.load_alle_transacties()` to populate base snapshot.
- After base load: always call `_refresh_derived_snapshots()` which will regenerate all derived repository snapshots from the base snapshot.
- On INSERT/UPDATE/DELETE (orders tab):
    1. Apply change to DB (INSERT/UPDATE/DELETE)
    2. Update `repository_snapshot_alle_transacties` accordingly (either reload fully or apply delta)
    3. Call `_refresh_derived_snapshots()` to recompute derived repository snapshots
    4. Notify interested listeners via a DB-change signal (see Signals below)
- On Price Feed updates:
    1. Live aggregators collect price updates into an in-memory map
    2. After a debounce interval (e.g., 300-500ms) `PortfolioEngine` calls each aggregator.process_live_update()
    3. Aggregator writes a new DataFrame into its `aggregator_snapshot_*_live` slot (overwrite semantics)
    4. Aggregator emits a specific Qt signal (e.g., `aandelenUpdated`, `optiesUpdated`, `sprintersUpdated`) so UI tabs reload.

3) Atomicity & Concurrency
- Treat each snapshot assignment as atomic: build the full Polars DataFrame off-thread if needed, then assign the attribute on the main snapshot store in one statement.
- Add an optional lock on the snapshot store for safety if multiple threads may write simultaneously. Example pattern (Python):

```py
import threading
SNAPSHOT_STORE._lock = threading.RLock()

def safe_write(key, df):
        with SNAPSHOT_STORE._lock:
                setattr(SNAPSHOT_STORE, key, df)
```

- UI readers should not mutate snapshots. If a UI needs a copy, it should call `.clone()` or convert to a new Polars DataFrame.

4) Signals and event wiring (recommended)
- Central signals module (create `portefeuille_viewer/signals.py`) with a QObject carrying these signals:
    - `databaseChanged = Signal(str)` — emitted when active DB changes; passes the new DB name
    - `snapshotUpdated = Signal(str)` — emitted when a snapshot key is updated (passes key name)

- Existing signals to use/standardize:
    - OrdersTab currently emits `dbChanged` — ensure MainWindow connects it to the central `databaseChanged` or directly to tab reloads.
    - Aggregators already emit granular signals (`sprintersUpdated`, `optiesUpdated`, etc.). Continue using these.

- Recommended wiring in `MainWindow.__init__`:
    - Connect `orders_tab.dbChanged` → central `signals.databaseChanged.emit(name)` or call `SNAPSHOT_STORE.active_database_name = name` and then `signals.databaseChanged.emit(name)`
    - Connect `signals.databaseChanged` → all tabs' reload methods (if available)
    - Connect aggregator signals → corresponding tab `reload_data()` for immediate live updates

5) Storage & persistence (optional but recommended for faster startup)
- Persist snapshots to disk on clean shutdown or periodically (Parquet or Polars IPC):
    - Path layout: `.snapshots/<db_name>/<snapshot_key>.parquet`
    - On startup, if snapshots exist for the active DB, load `repository_snapshot_alle_transacties` from disk before hitting the DB to improve cold-start.
- Keep a small manifest file with snapshot timestamps and file sizes to validate consistency.

6) Snapshot naming conventions and schema expectations
- Snapshot keys should follow the `repository_snapshot_*` (DB-derived) and `aggregator_snapshot_*_live` (live) pattern.
- For UI tables we expect consistent column names; examples:
    - Sprinters live snapshot: ["broker","asset_rollup","asset_detail","last","sprinter_funding","sprinter_ratio","SomVantransactie_aantal","SomVantransactie_euro_totaal","winst"] — note: prefer `last` or `price` as canonical numeric column; UI can alias `Koers`.
    - Opties live snapshot: include `uniek_id, broker, asset_rollup, optie_exp_date, optie_strike, optie_call_put, SomVantransactie_aantal, SomVantransactie_euro_totaal, last, iv`.
    - Aandelen live snapshot: include `asset_rollup, ib_symbol, koers, aantal_bezit, eq_total_fee, total_result`.

7) Validation & tests (must add)
- Unit tests:
    - test_switch_database_sets_active_name: call `repository.switch_database(name)` and assert `SNAPSHOT_STORE.active_database_name == name`.
    - test_live_aggregator_writes_empty_snapshot: ensure aggregator writes an empty DataFrame into `aggregator_snapshot_open_sprinters_live` when no data.
    - test_orders_insert_triggers_derived_refresh: simulate an insert, call the OrdersTab save routine, assert derived snapshots were regenerated.

- Integration tests:
    - Simulate DB switch: call `orders_tab.apply_database_by_name(name)`, assert `signals.databaseChanged` emitted and tabs' `reload_data()` invoked (use a test double for tabs).

8) Debugging & observability
- Add `snapshot_store.snapshot_store_summary()` (already present) to log a quick summary on DB switch and after major operations.
- Log snapshot writes with DEBUG level (include key name, row count, timestamp).

9) Backward compatibility notes and migration
- Existing code currently inspects `repository.db_path` and `DB_MAP` to determine the active DB — replace these lookups with `SNAPSHOT_STORE.active_database_name` gradually.
- Ensure `repository.switch_database()` sets `SNAPSHOT_STORE.active_database_name` immediately after a successful test connection.

10) Quick checklist to implement in code (small incremental PRs)
- [ ] Add `active_database_name`, `snapshot_timestamps`, and optional `_lock` to `SnapshotStore`.
- [ ] Ensure `repository.switch_database()` sets `SNAPSHOT_STORE.active_database_name` and optionally writes a small manifest file in `.snapshots/<db>/manifest.json`.
- [ ] Create `portefeuille_viewer/signals.py` with `databaseChanged` and `snapshotUpdated` and use it in `MainWindow` to wire tabs.
- [ ] Update all tabs to prefer `SNAPSHOT_STORE.active_database_name` for display and rely on `signals.databaseChanged` to refresh.
- [ ] Add unit tests and integration tests for the items in section 7.

---

## 🔧 Recent changes (experiment_0.8)

These entries reflect edits made in the `experiment_0.8` working copy to centralize signals and wire DB-switch behavior. The changes were applied to the local 0.8 working tree for testing (not yet committed by the developer during the session unless noted).

- Added central signals package:
    - `portefeuille_viewer/signals/__init__.py` defines a small `Signals(QObject)` class and exports module-level `signals` instance.
    - Signals provided: `databaseChanged(str)`, `snapshotUpdated(str)`, and `debugSignal(str)` plus queued emit helpers (`queued_emit_databaseChanged`, `queued_emit_snapshotUpdated`).

- Wired repository to emit central signal on DB switch:
    - `portefeuille_viewer/data/repository.py` now sets `SNAPSHOT_STORE.active_database_name = name` (existing behavior) and calls `signals.queued_emit_databaseChanged(name)` after successful switch.
    - The import and emit are guarded with try/except to avoid hard dependency during progressive rollout.

- Wired MainWindow to listen for central DB-change events:
    - `portefeuille_viewer/ui/main_window.py` imports `signals` and connects `signals.databaseChanged` to a new handler `_on_central_database_changed(self, db_name)` which defensively iterates tabs and calls `reload_data()` on tabs that expose it.

- Notes about this change:
    - The signals package is intentionally minimal and only imports PySide6 to avoid circular imports.
    - Emission uses `QTimer.singleShot(0, ...)` helper to ensure the signal is delivered on the Qt main thread, which avoids threading issues if DB-switch is invoked from a worker thread.
    - The wiring provides immediate end-to-end behavior: calling `repository.switch_database(name)` will now cause tabs that have `reload_data()` to refresh automatically (via MainWindow handler).

Test instructions (local, before committing):
1. Start the app from the `experiment_0.8` folder (same startup script you normally use).
2. Trigger a DB switch via Orders tab or Settings → apply. Observe the UI tabs (Sprinters, Open Opties, Aandelen Tab) reload.
3. Optional debug check: in Python REPL inside the same virtualenv run:
     - `from portefeuille_viewer.signals import signals; print(signals)` should show the signals instance.

Next recommended steps:
- If tests look good, commit the changes in `experiment_0.8` and open a small PR describing the signals centralization.
- Replace ad-hoc per-tab `dbChanged` emits over time with the central `signals.databaseChanged` to avoid duplication.
- Add unit tests: `switch_database` emits the central signal and sets `SNAPSHOT_STORE.active_database_name`.

    val = self._df[index.row(), index.column()]
    
    if role == Qt.DisplayRole:
        if val is None:
            return ""
        if isinstance(val, float):
            return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        # ← Added date formatting
        if isinstance(val, datetime.date):
            return val.strftime("%d/%m/%Y")
        return str(val)
    
    # ← Added center alignment for dates
    if role == Qt.TextAlignmentRole:
        if isinstance(val, datetime.date):
            return Qt.AlignCenter | Qt.AlignVCenter
```

**Import Added:**
```python
import datetime  # Added to top of models.py
```

---

### 5. Enhanced Error Logging

**Problem:**
- IB ERROR 200 messages didn't show which symbol failed
- Hard to debug subscription issues

**Solution:**
```python
# price_feed.py, line ~69
def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
    if errorCode not in (2103,2104,2106,2158):
        # Lookup symbol from reqId
        with feed._lock:
            key = feed._tid_by_key.get(reqId)
        
        if key:
            sym, cur = key
            feed.log.emit(f"IB ERROR {errorCode} for {sym} ({cur}): {errorString}")
        else:
            feed.log.emit(f"IB ERROR {errorCode}: {errorString}")
```

**Before:**
```
[17:36:18] IB-Feed: IB ERROR 200: No security definition has been found
```

**After:**
```
[17:36:18] IB-Feed: IB ERROR 200 for AAPL (USD): No security definition has been found
```


## 🔔 Recent repository changes (added Oct 17, 2025)

This section documents changes that were implemented after the main session above. They are important to keep the development notes aligned with the current codebase and to identify follow-ups that still need work.

### Summary of key changes
- Sprinters tab (UI) was refactored to match the Options tab behaviour: uses a Polars-backed table model, QSortFilterProxyModel, preserves user sort state on refresh and exposes a `reload_data()` method that reads from the live snapshot.
- Live aggregator for sprinters (`LiveAggregatorSprinters`) now always writes a DataFrame into the snapshot store even when there are no sprinter transactions. This prevents the UI from failing to refresh when a database has zero sprinter records.
- The sprinters UI now shows an explicit message and an empty table with sensible columns when the active database has no sprinter transactions. The message includes the active database name (resolved dynamically from `repository.DB_MAP` / `db_path`).
- `LiveAggregatorSprinters` received a `verbose` flag to control console logging (suppress or enable debug prints). Default is `verbose=False` so the console stays quiet in normal runs.
- Several fixes were applied to ensure snapshot refresh after DB switch / order changes propagate to tabs: orders tab triggers derived snapshot reload and now live aggregators react to the live base snapshot.

### Files changed (high level)
- `portefeuille_viewer/ui/sprinters_tab.py` — new reload logic, proxy-model, sort-state preservation, DB-name-aware empty-table message.
- `portefeuille_viewer/data/live_aggregator_sprinters.py` — always save empty DataFrame to snapshot, added `verbose` parameter and conditional logging, process_live_update emits `sprintersUpdated`.
- `portefeuille-viewer-experiment_0.7.py` — dataset loading and debug prints adjusted (some debug prints commented out to avoid syntax issues).
- `portefeuille_viewer/data/snapshot_store.py` — snapshot keys for sprinters are used; consider adding an explicit `active_database_name` or exposing current DB selection for UI components (see follow-ups).
- `portefeuille_viewer/ui/orders_tab.py` — ensured `_refresh_derived_snapshots()` is called after changes and DB switches.

### Why these changes were made
- Previously, when a database had no sprinter transactions the live aggregator printed "Geen data om op te slaan" and did not write a snapshot. The UI relied on a snapshot existing to refresh, so the Sprinters tab looked empty and unrefreshed, causing confusion.
- Writing an explicit empty DataFrame into the snapshot makes the UI deterministic: it will always render a table (possibly empty) and show a clear message about the active DB status.
- The DB name shown in the UI is now derived from the repository's current `db_path` → `DB_MAP` mapping, avoiding stale display of the default DB name.

### Things missing / follow-ups (recommended)
1. Centralize the "active database name" in `SNAPSHOT_STORE` or `PortfolioEngine` and emit a signal on DB change. Right now the UI resolves the active DB by inspecting `repository.db_path` and `DB_MAP` — this is fragile. Proposed change:
    - Add `SNAPSHOT_STORE.active_database_name` (string) and update it in `repository.switch_database()`.
    - Emit a Qt signal `databaseChanged(name)` from the Orders tab / MainWindow when switching databases; tabs subscribe and call their `reload_data()` on change.

2. Add unit/integration tests for the sprinters refresh flow:
    - Test that `LiveAggregatorSprinters._save_to_snapshot_store()` writes an empty DataFrame when `self.df` is empty or None.
    - Test that `SprintersTab.reload_data()` populates an empty table with correct columns and that the label shows the correct DB name.

3. Persist `verbose` configuration in settings, or wire the aggregator to the central logger instead of printing. Right now `verbose` defaults to False but is passed in code construction; consider a global logging config.

4. Add a small visible UI hint (e.g. secondary label or colored bar) when a tab is intentionally empty because the active DB has no relevant data. The current single-line label is good, but a persistent subtle UI affordance would reduce confusion further.

5. Consider moving the default column list for empty sprinters table out of UI code and into a single schema/metadata source so all tabs share consistent headers.

### Proposed immediate tasks (prioritized)
1. (P0) Add `SNAPSHOT_STORE.active_database_name` and update `repository.switch_database()` to set it and trigger a signal. Have `SprintersTab` listen to that signal and refresh (and likewise the other tabs). Estimated: 2–4 hours.
2. (P1) Add automated tests for sprinter snapshot write and UI reload behaviour (mock snapshot store). Estimated: 3–6 hours.
3. (P1) Persist `verbose` setting in app settings/config (or use Python logging with log levels). Estimated: 1–2 hours.
4. (P2) Create a small UI affordance (colored banner or icon) that indicates "no data for active DB" across tabs. Estimated: 2–3 hours.

### Quick verification steps
1. Start app with database A (with sprinters) and confirm Sprinters tab shows rows.
2. Switch active DB to B (no sprinters) via Orders tab → DB dropdown. Confirm:
    - Label updates to `DATABASE <name> heeft geen sprinter transacties.`
    - Table displays empty rows but header columns are visible.
3. Switch back to A, confirm table repopulates.
4. Run unit tests for snapshot write and tab reload (as implemented above).

---

## 🛡️ SnapshotStore.safe_write contract (added Oct 17, 2025)

Summary:
- Use `SNAPSHOT_STORE.safe_write(key, value)` for any code that assigns snapshot attributes (both repository-derived and aggregator live snapshots).
- `safe_write` performs three responsibilities:
    1. Atomically sets `setattr(SNAPSHOT_STORE, key, value)`
    2. Records a best-effort timestamp in `SNAPSHOT_STORE._last_update_ts[key] = time.time()`
    3. Emits `signals.queued_emit_snapshotUpdated(key)` (queued helper) so subscribers on the Qt event loop receive the notification safely

Why:
- Ensures consistent observability (timestamps + central notification) across all snapshot writes.
- Guarantees the notify happens on the Qt main thread via queued emit (avoids threading issues when writers run in worker threads).

Usage examples:

- From an aggregator (recommended):
```py
# inside LiveAggregator.process_live_update()
aggregated = self.get_aggregated()
SNAPSHOT_STORE.safe_write("aggregator_snapshot_aandelen_live", aggregated)
```

- From repository after building a derived snapshot:
```py
per_uniek_filtered = ...  # polars DataFrame
SNAPSHOT_STORE.safe_write("repository_snapshot_open_sprinters", per_uniek_filtered)
```

Testing notes:
- Unit test (`tests/test_snapshot_store.py`) monkeypatches `signals.signals.queued_emit_snapshotUpdated` to assert the helper is called synchronously.
- Integration test (`tests/test_snapshot_integration.py`) connects a real Qt slot to `signals.snapshotUpdated` and uses the Qt event loop (pytest-qt) to ensure queued emits are delivered. This verifies end-to-end behavior including the `QTimer.singleShot(0, ...)` queued delivery.

How to run the tests locally:
1. Install test dependencies:
```powershell
& C:/Python311/python.exe -m pip install --user pytest pytest-qt
```
2. Run only the new tests (keeps output tight):
```powershell
cd c:\python_coding\portefeuille_viewer\portefeuille_viewer_experiment_0.8
& C:/Python311/python.exe -m pytest -q tests/test_snapshot_store.py tests/test_snapshot_integration.py
```

Expected output on success: `..` or `2 passed`.

Notes on CI:
- If adding to CI, ensure the test runner has access to a Qt platform plugin (headless). On GitHub Actions use the `xvfb` service or the `pytest-qt` recommended setup for headless runs.


## 🏗️ Architecture & Design Decisions

### Snapshot Architecture

**Design Pattern:** In-Memory Snapshot with Lazy Loading

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              DATABASE                                    │
│                        transacties_bron_data_org                         │
└──────────────────────────────┬─────────────────────────────────────────────┘
                                         │
                                         │ load_alle_transacties()  (reads DB once)
                                         ↓
                        ┌──────────────────────────────────────────┐
                        │  repository_snapshot_alle_transacties    │  ← BASE SNAPSHOT
                        │        (Polars DataFrame - persistent)   │
                        └───────────────┬──────────────────────────┘
                                             │
            ┌────────────────────────┼────────────────────────┬────────────────────────┐
            │                        │                        │                        │
            │                        │                        │                        │
 load_aandelen_from_tx()   load_open_opties_from_tx()  load_gesloten_opties_from_tx()  load_gesloten_opties_no_broker()
     ↓                        ↓                         ↓                            ↓
 snapshot_repository_aandelen  snapshot_load_open_opties   snapshot_gesloten_opties   snapshot_gesloten_opties_no_broker

     (derived, recomputed from base snapshot by `_refresh_derived_snapshots()`)

                                             │
                                             ↓
                        ┌──────────────────────────────────────────┐
                        │           LIVE UPDATES (PortfolioEngine) │
                        │  - batch price updates (debounce 300-500ms)│
                        └───────────────┬──────────────────────────┘
                                             │
              ┌──────────────────────┴──────────────────────────┐
              │                                                 │
              │                                                 │
aggregator_snapshot_aandelen_live                      aggregator_snapshot_load_open_opties_from_tx_live
     (aandelen live)                                          (opties live)
              │                                                 │
              └───────────────┬─────────────────────────────────┘
                                    │
                                    ↓
                    (Aggregators emit signals: aandelenUpdated, optiesUpdated, sprintersUpdated)

Metadata & persistence:
- SNAPSHOT_STORE.active_database_name  ← set on DB switch (repository.switch_database)
- SNAPSHOT_STORE.snapshot_timestamps[name]  ← updated after each write
- Optional disk cache: .snapshots/<db_name>/<snapshot_key>.parquet (load on startup)

Notes:
- Write snapshots atomically (build off-thread, then assign under lock)
- UI tabs subscribe to aggregator signals and to a central databaseChanged signal for DB switches
```

**Key Principles:**
1. **Single Source of Truth:** `snapshot_alle_transacties` is the base
2. **Derived Snapshots:** Aggregated/filtered views of base snapshot
3. **Live Updates:** Separate "live" snapshots updated by PortfolioEngine
4. **Synchronization:** All CRUD operations must call `_refresh_derived_snapshots()`

**Rationale:**
- ✅ Fast queries (in-memory Polars)
- ✅ No repeated database hits
- ✅ Consistent data across tabs
- ⚠️ Must manually sync after changes

---

### IBKR Live Price Integration

**Architecture:** Batch Processing with Debounce Timer

```
IBKR API Stream
      ↓
   Price Update (AMD = 219.82)
      ↓
LiveAggregatorAandelen.update_live_price()
      ↓
   Store in live_prices dict
      ↓
   Set _pending_updates = True
      ↓
   Start/Restart 500ms timer
      ↓
   [Wait for quiet period]
      ↓
PortfolioEngine._process_batched_updates()
      ↓
      
    Sprinters batching flow (confirmed)
    ----------------------------------
    - `PortfolioEngine` creates and owns a `LiveAggregatorSprinters` instance (`self.live_aggregator_sprinters`).
    - On each incoming price update the engine calls `live_aggregator_sprinters.update_live_price(symbol, price)` to stash the latest price in the aggregator's `live_prices` map.
    - After the debounce interval `PortfolioEngine._process_batched_updates()` calls `live_aggregator_sprinters.process_live_update()`. The aggregator rebuilds its DataFrame from `repository_snapshot_open_sprinters`, applies the latest `live_prices`, writes the result to `SNAPSHOT_STORE.aggregator_snapshot_open_sprinters_live`, and emits the Qt signal `sprintersUpdated`.
    - `SprintersTab` connects to `sprintersUpdated` and reacts by calling `reload_data()`; `reload_data()` reads the snapshot and repopulates the table (showing an empty table + DB-specific message when no rows are present).

    Implementation locations:
    - `portefeuille_viewer/domain/portfolio_engine.py` — initializes `LiveAggregatorSprinters`, `_on_live_price()` calls `update_live_price()`, `_process_batched_updates()` calls `process_live_update()`.
    - `portefeuille_viewer/data/live_aggregator_sprinters.py` — implements `update_live_price()`, `process_live_update()`, snapshot write and `sprintersUpdated` emission.
    - `portefeuille_viewer/ui/sprinters_tab.py` — subscribes to `sprintersUpdated` and implements `reload_data()`.

    Recommended quick tests:
    - Call `_on_live_price(symbol, currency, price)` and assert `live_aggregator_sprinters.live_prices` contains the value.
    - Trigger `_process_batched_updates()` and assert `SNAPSHOT_STORE.aggregator_snapshot_open_sprinters_live` is updated (rows or empty DataFrame) and that `sprintersUpdated` was emitted.

   ├→ LiveAggregatorAandelen.process_live_update()
   │     ├→ Update snapshot_aandelen_live
   │     └→ Emit aandelenUpdated signal
   │
   └→ LiveAggregatorOpties.process_live_update()
         ├→ Update snapshot_load_open_opties_from_tx_live
         └→ Emit optiesUpdated signal
              ↓
         GUI Updates (QTableView)
```

**Key Design Decisions:**

1. **Batch Processing (500ms debounce):**
   - **Problem:** IBKR sends 100+ price updates/second → GUI freezes
   - **Solution:** Accumulate updates, process in batch every 500ms
   - **Result:** Max 2 GUI updates/second, smooth performance

2. **Two-Stage Updates:**
   - Stage 1: `update_live_price()` - Store price (fast, no processing)
   - Stage 2: `process_live_update()` - Apply to DataFrame (batched)

3. **Separate Live Snapshots:**
   - `snapshot_aandelen` - Static (from database)
   - `snapshot_aandelen_live` - Dynamic (updated by PortfolioEngine)
   - Prevents database snapshot pollution

**Code Locations:**
- `portfolio_engine.py` (line ~76): Batch processing
- `live_aggregator_aandelen.py` (line ~68): Update live price
- `live_aggregator_opties.py` (line ~138): Update live price

---

### IBKR Subscription Strategy

**Current Implementation:** Subscribe All (Simplified)

```python
# portfolio_engine.py
def start_subscriptions(self):
    """Subscribe to all symbols from asset_rollup_data"""
    df = repository.load_asset_rollup_data()
    symbols = df['ib_symbol'].unique()
    
    for symbol in symbols:
        currency = df[df['ib_symbol'] == symbol]['ib_currency'].iloc[0]
        self.feed_service.subscribe(symbol, currency)
    
    print(f"Subscribed to {len(symbols)} symbols")
```

**Current Status:**
- 89 symbols subscribed
- Well within 100 subscription limit
- No rotation needed yet

**Discussed Alternatives:**

#### **Option A: Priority-Based Filtering**
```python
def start_subscriptions(self):
    # Filter: Only positions with holdings > 0
    active_df = df[df['aantal_bezit'] > 0]
    
    # Sort by position value
    sorted_df = active_df.sort_values('eq_bezit', ascending=False)
    
    # Subscribe top 100
    for symbol in sorted_df.head(100)['ib_symbol']:
        self.subscribe(symbol)
```

**Pros:** Simple, focuses on active positions  
**Cons:** Misses closed positions that might reopen

#### **Option B: Rotation Strategy (Ping-Pong)**
```python
# Two groups of 100 symbols
group_a = symbols[0:100]
group_b = symbols[100:200]

# Switch every 5 seconds
def _switch_group(self):
    self._unsubscribe_group(current_group)
    self._subscribe_group(other_group)
```

**Timeline:**
```
00s-05s: Group A active (100 symbols get 5s of updates)
05s-10s: Group B active (100 symbols get 5s of updates)
10s-15s: Group A active (repeat)
```

**Pros:** Covers 200+ symbols within limit  
**Cons:** Each symbol only updated every 10 seconds

#### **Option C: Continuous Fast Rotation**
```python
# 10 groups of 20 symbols each
rotation_interval = 500ms  # 0.5 seconds

# Cycle time: 10 groups × 0.5s = 5 seconds
# Each symbol updated every 5 seconds
```

**Pros:** Fast updates for all symbols  
**Cons:** More complex, higher CPU usage

**Decision:** Keep current simple approach until >100 symbols needed

**Subscription Limits:**
```
Paper Trading Account:  ~100 simultaneous
Live Standard Account:  ~100 simultaneous
Live Pro Account:       ~200-300 simultaneous

Rate Limits:
- Max 60 requests/sec for market data
- Max 50 simultaneous historical data requests
```

**Timing Analysis:**
```
Operation               Time        Impact
──────────────────────────────────────────
Subscribe 1 symbol      ~300ms      Network + IBKR processing
Unsubscribe 1 symbol    ~50ms       Faster (no data setup)
Batch 20 subscribes     ~500ms      Parallel processing
Batch 100 subscribes    ~1-2 sec    Initial setup
```

**Rotation Trade-offs:**
```
Rotation Speed    CPU Impact    Update Freq    Complexity
──────────────────────────────────────────────────────────
None (all static)  Low          Real-time      Low
1 min rotation     Low          1x/2min        Low
5 sec rotation     Medium       1x/10sec       Medium
500ms rotation     Medium-High  1x/1sec        High
```

---

### Git Workflow & Version Management

**Branch Strategy:** Feature Branches per Experiment Version

```
Repository: portefeuille_viewer
Owner: onnokievit

Branch Structure:
├── develop (main development)
├── experiment_0.2
├── experiment_0.3
├── experiment_0.4
└── experiment_0.5 (current active branch)

Folder Structure:
C:\python_coding\portefeuille_viewer\
├── portefeuille_viewer_experiment_0.1\
│   └── .git\ (separate repository, branch: experiment_0.1)
├── portefeuille_viewer_experiment_0.2\
│   └── .git\ (separate repository, branch: experiment_0.2)
├── ...
└── portefeuille_viewer_experiment_0.5\
    └── .git\ (separate repository, branch: experiment_0.5)
```

**Important:** Each experiment folder is a **separate git repository** (not subfolders of one repo)

**Workflow:**
```bash
# On desktop - make changes
cd C:\python_coding\portefeuille_viewer\portefeuille_viewer_experiment_0.5
git add .
git commit -m "feat: description"
git push origin experiment_0.5

# On laptop - get changes
cd C:\python_coding\portefeuille_viewer
git clone -b experiment_0.5 https://github.com/onnokievit/portefeuille_viewer.git portefeuille_viewer_experiment_0.5
```

**Commit Message Format:**
```
feat: Add new feature
fix: Fix bug
docs: Update documentation
refactor: Code restructuring
perf: Performance improvement
test: Add tests
```

**Example Commits from Session:**
```bash
git commit -m "feat(orders): Implement complete snapshot sync for INSERT/UPDATE/DELETE operations

- Add _refresh_derived_snapshots() after INSERT (line 811)
- Add _refresh_derived_snapshots() after UPDATE (line 772)
- Add _refresh_derived_snapshots() after DELETE
- Ensure all derived snapshots stay in sync with base snapshot

Fixes GUI not updating after database modifications."
```

---

## 💻 Technical Stack

### Core Technologies
```yaml
Language: Python 3.11
GUI Framework: PySide6 (Qt 6.x)
Data Processing: Polars (primary), Pandas (legacy)
Database: SQL Server / Microsoft Access (ODBC)
API: Interactive Brokers API (ibapi)
Version Control: Git + GitHub
```

### Key Libraries
```python
# GUI
PySide6                # Qt bindings for Python
PySide6.QtCore         # Core Qt functionality
PySide6.QtWidgets      # UI widgets
PySide6.QtGui          # GUI utilities

# Data Processing
polars                 # Fast DataFrame library (Rust-based)
pandas                 # Legacy DataFrame operations
numpy                  # Numerical computations

# Database
pyodbc                 # ODBC database connectivity

# IBKR
ibapi                  # Interactive Brokers API client

# Utilities
openpyxl               # Excel file handling
python-dateutil        # Date parsing
```

### Project Structure
```
portefeuille_viewer_experiment_0.5/
├── portefeuille-viewer-experiment_0.5.py  # Main entry point
├── portefeuille_viewer/                   # Application package
│   ├── __init__.py
│   ├── data/                              # Data layer
│   │   ├── repository.py                  # Database operations
│   │   ├── snapshot_store.py              # In-memory snapshots
│   │   ├── live_aggregator_aandelen.py    # Live stock updates
│   │   └── live_aggregator_opties.py      # Live option updates
│   ├── domain/                            # Business logic
│   │   └── portfolio_engine.py            # Orchestrator
│   ├── services/                          # External services
│   │   └── price_feed.py                  # IBKR price feed
│   └── ui/                                # User interface
│       ├── main_window.py                 # Main window
│       ├── orders_tab.py                  # Orders CRUD
│       ├── aandelen_tab2.py               # Stocks tab
│       ├── open_options_tab.py            # Options tab
│       └── models.py                      # Qt table models
├── logs/                                  # Application logs
└── DEVELOPMENT_NOTES.md                   # This file
```

### Database Schema (Key Tables)
```sql
-- Main transaction table
transacties_bron_data_org
├── Id (INT, PK)                    -- Unique record identifier
├── order_id (INT)                  -- Grouping field for paired orders
├── datum (DATE)                    -- Transaction date
├── transactie_oorsprong (VARCHAR)  -- Source (IBKR, DeGiro, etc.)
├── broker (VARCHAR)                -- Broker name
├── asset_rollup (VARCHAR)          -- Ticker symbol
├── asset_type (VARCHAR)            -- Type: aandeel, optie, sprinter
├── transactie_type (VARCHAR)       -- buy, sell, dividend, etc.
├── asset_detail (VARCHAR)          -- Additional details
├── optie_exp_date (DATE)           -- Option expiry date
├── optie_strike (FLOAT)            -- Option strike price
├── optie_call_put (VARCHAR)        -- call or put
├── aantal (INT)                    -- Quantity
├── transactie_prijs (FLOAT)        -- Transaction price
├── transactie_fee (FLOAT)          -- Transaction fee
├── uniek_id (VARCHAR)              -- Unique transaction ID
└── transactie_oorsprong_detail     -- Additional transaction details

-- Supporting tables
asset_rollup_data                   -- Symbol metadata
├── asset_rollup
├── ib_symbol                       -- IBKR symbol
├── ib_currency                     -- Currency (USD, EUR, etc.)
├── prim_exchange                   -- Primary exchange
└── aantal_bezit                    -- Current holdings
```

---

## 🔌 IBKR Integration

### Option Price Retrieval - Complexities

**Discussed Challenge:** European Options & Multiple Series

**Problem:**
Simple contract specification doesn't work for all options:
```python
# ❌ This fails for European stocks with multiple series
contract = Contract()
contract.symbol = "BN"              # Danone
contract.secType = "OPT"
contract.strike = 50.0
contract.lastTradeDateOrContractMonth = "20251017"
contract.right = "C"

# IBKR Error: Multiple matches found!
# - BN (current series)
# - DA1 (old series after corporate action)
# - DA2 (even older series)
```

**Root Cause:**
- Corporate actions (splits, mergers, dividends) create multiple option series
- Same strike + expiry can exist across multiple series
- Symbol + Strike + Expiry is **not unique**

**Solution: Use Contract ID (conId)**

```python
# Step 1: Request contract details
search_contract = Contract()
search_contract.symbol = "BN"
search_contract.secType = "OPT"
search_contract.exchange = "EURONEXT"
search_contract.currency = "EUR"
search_contract.strike = 50.0
search_contract.lastTradeDateOrContractMonth = "20251017"
search_contract.right = "C"

ib.reqContractDetails(reqId=1, contract=search_contract)

# Step 2: Receive multiple matches
def contractDetails(self, reqId, contractDetails):
    contract = contractDetails.contract
    print(f"ConId: {contract.conId}")
    print(f"Symbol: {contract.symbol}")
    print(f"TradingClass: {contract.tradingClass}")
    print(f"Multiplier: {contract.multiplier}")
    
    # Filter: main series only
    if (contract.tradingClass == "BN" and 
        contract.multiplier == "100"):
        self.main_series_conid = contract.conId

# Step 3: Subscribe using conId
final_contract = Contract()
final_contract.conId = self.main_series_conid
final_contract.exchange = "SMART"

ib.reqMktData(reqId=2, contract=final_contract, ...)
```

**Trading Class Explained:**
```
Trading Class = Option series identifier

Examples:
- BN     → Current Danone series
- DA1    → Adjusted series 1 (after corporate action)
- AAPL   → Normal Apple options
- AAPL1  → Adjusted Apple (after stock split)
```

**Filtering Strategy:**
```python
def is_main_series(contract):
    """Check if this is the main (non-adjusted) option series"""
    # Rule 1: Trading class matches symbol
    if contract.tradingClass != contract.symbol:
        return False
    
    # Rule 2: Standard multiplier
    if contract.multiplier != "100":
        return False
    
    # Rule 3: Check open interest (optional)
    # Higher open interest = more liquid = likely main series
    
    return True
```

**Implementation Recommendation:**
```
For MVP (Current):
- Use simple contract specification (symbol + strike + expiry)
- Works for 90% of US options
- Log errors for European options

For Production (Future):
- Implement conId lookup via reqContractDetails
- Store conId in database (new column: ib_option_conid)
- Use conId for all option subscriptions
```

### Required Option Contract Fields

**Minimum Required:**
```python
contract = Contract()
contract.symbol = "AAPL"                              # Ticker symbol
contract.secType = "OPT"                              # Security type: OPTion
contract.exchange = "SMART"                           # Exchange routing
contract.currency = "USD"                             # Currency
contract.lastTradeDateOrContractMonth = "20251017"    # Expiry (YYYYMMDD)
contract.strike = 250.0                               # Strike price
contract.right = "C"                                  # "C" = Call, "P" = Put
contract.multiplier = "100"                           # Contract size
```

**Data Sources (From Database):**
```sql
SELECT 
    asset_rollup,                    -- → contract.symbol
    optie_exp_date,                  -- → contract.lastTradeDateOrContractMonth (convert)
    optie_strike,                    -- → contract.strike
    optie_call_put                   -- → contract.right (convert)
FROM transacties_bron_data_org
WHERE asset_type = 'optie'
  AND aantal != 0  -- Only open positions
```

**Conversions Needed:**
```python
# Date: "2025-10-17" → "20251017"
expiry_str = pd.to_datetime(row['optie_exp_date']).strftime('%Y%m%d')

# Right: "call"/"put" → "C"/"P"
right_str = "C" if row['optie_call_put'].lower() == "call" else "P"

# Strike: Already float
strike = float(row['optie_strike'])
```

### Available Option Data from IBKR

**Live Market Data:**
```python
genericTickList options:
- ""     → Standard (bid, ask, last, volume)
- "100"  → Option volume
- "101"  → Option open interest
- "104"  → Historical volatility
- "106"  → Option implied volatility
```

**Greeks & Model Prices:**
```
Delta:    Price sensitivity (€ per €1 underlying move)
Gamma:    Delta change rate
Vega:     IV sensitivity (€ per 1% IV change)
Theta:    Time decay (€ loss per day)
Rho:      Interest rate sensitivity

Model prices:
- Black-Scholes theoretical price
- IBKR proprietary model price
- Mark price (for margining)
```

**Historical Data:**
Available resolutions:
- Tick: 1sec, 5sec, 15sec, 30sec
- Bars: 1min, 2min, 5min, 15min, 30min
- Daily: 1hour, 2hours, 3hours, 1day, 1week

Lookback: Up to 60 days (intraday), years (daily)

**Not Implemented Yet:**
- Option chain scanning
- Greeks tracking
- Historical option data
- Volatility surface plotting

---

## ⚠️ Known Limitations

### 1. Subscription Management
**Issue:** No rotation implemented  
**Impact:** Limited to ~100 simultaneous subscriptions  
**Current Status:** 89 symbols (OK)  
**Trigger:** Will become issue if portfolio grows >100 symbols  
**Mitigation:** Discussed rotation strategies (see Architecture section)

### 2. European Option Support
**Issue:** conId lookup not implemented  
**Impact:** European options with multiple series may fail to subscribe  
**Current Status:** Affects Danone and similar stocks  
**Workaround:** Manual symbol verification  
**Solution:** Implement reqContractDetails flow (documented above)

### 3. Option Live Prices
**Issue:** Options not subscribed for live prices  
**Impact:** Option positions show static prices only  
**Current Status:** Only stocks have live updates  
**Complexity:** Medium (similar to stocks, needs contract building)

### 4. No Unit Tests
**Issue:** No automated testing  
**Impact:** Regressions hard to catch  
**Risk Level:** Medium  
**Mitigation:** Manual testing after changes

### 5. Limited Error Handling
**Issue:** Database errors not gracefully handled  
**Impact:** App may crash on DB connection loss  
**Example:** No retry logic for ODBC failures

### 6. No Logging Configuration
**Issue:** Debug logging always on  
**Impact:** Console noise, performance impact  
**Location:** Multiple print statements throughout codebase

---

## 🚀 Future Enhancements

### High Priority
- [ ] **Option Live Prices:** Subscribe to option prices (similar to stocks)
- [ ] **ConId Lookup:** Implement for European options
- [ ] **Unit Tests:** Add pytest framework with core tests
- [ ] **Error Recovery:** Add retry logic for database/IBKR disconnections

### Medium Priority
- [ ] **Subscription Rotation:** Implement ping-pong strategy for >100 symbols
- [ ] **Portfolio Greeks:** Track delta, gamma, theta in real-time
- [ ] **Configuration File:** Move hardcoded values (DB paths, etc.) to config
- [ ] **Logging Framework:** Replace print with proper logging (with levels)

### Low Priority
- [ ] **Option Chain Scanner:** Find best strikes to trade
- [ ] **Historical Analysis:** Backtest strategies with historical option data
- [ ] **Volatility Surface:** Visualize IV across strikes/expiries
- [ ] **Multi-Database:** Support multiple databases simultaneously
- [ ] **Export Reports:** PDF/Excel portfolio reports

### Nice to Have
- [ ] **Mobile App:** Companion app for portfolio viewing
- [ ] **Web Dashboard:** Browser-based portfolio view
- [ ] **Alerts System:** Price alerts, expiry warnings
- [ ] **Auto-Trading:** Execute trades based on signals

---

## 📊 Code Statistics

### Project Size (as of October 14, 2025)
```
Total Python Files: 29
Total Lines of Code: ~3,000
Average Lines per File: ~103

Largest Files:
1. orders_tab.py: ~1,400 lines (CRUD operations)
2. repository.py: ~650 lines (database layer)
3. portfolio_engine.py: ~200 lines (orchestration)
4. models.py: ~220 lines (Qt models)
5. price_feed.py: ~173 lines (IBKR integration)
```

### Industry Comparison
```
Size Category: Small Application (1,000 - 5,000 lines)

Similar Projects:
- Dropbox v1.0:      ~3,000 lines ✅ Similar
- Instagram (early): ~5,000 lines
- Simple trading bot: 1,000-3,000 lines ✅ Similar

Assessment: Appropriately sized for feature set
- Not too small (toy project)
- Not too large (maintainability issues)
- Good features-per-line ratio (~6 major features / 1000 lines)
```

### Code Quality Indicators
```
✅ Modular structure (data / domain / services / ui)
✅ Consistent naming conventions
✅ Reasonable file sizes (largest: 1,400 lines - still manageable)
✅ Clear separation of concerns
⚠️ Limited documentation (comments)
⚠️ No unit tests
⚠️ Some code duplication (formatting functions)
```

---

## 🐛 Troubleshooting & Lessons Learned

### Issue 1: GUI Not Updating After INSERT/UPDATE

**Symptoms:**
- Database changes saved correctly
- Other users see updated data
- Current session shows stale data
- Only visible after app restart

**Root Cause:**
```python
# Missing snapshot refresh
def opslaan_orders(self):
    if is_new:
        db.insert(...)
        # ❌ Missing: _refresh_derived_snapshots()
    else:
        db.update(...)
        # ❌ Missing: _refresh_derived_snapshots()
```

**Solution:**
Always call `_refresh_derived_snapshots()` after database modifications

**Lesson:**
In snapshot-based architecture, derived views must be manually regenerated after base changes

---

### Issue 2: DELETE Removed Too Many Records

**Symptoms:**
- Deleted one order in GUI
- Multiple related orders also deleted
- Database had fewer records than expected

**Root Cause:**
```python
# Using wrong field for deletion
order_id = row['order_id']  # ❌ Grouping field!
db.delete_where_order_id(order_id)  # Deletes ALL with this order_id
```

**Solution:**
Use Primary Key (Id) for targeted deletion:
```python
edit_id = row['EDIT_ID']  # ✅ Primary key
db.delete_where_id(edit_id)  # Deletes exactly one record
```

**Lesson:**
Always use primary keys for record-specific operations

---

### Issue 3: Database Switch Showed Old Data

**Symptoms:**
- Selected different database
- Dropdown updated
- Data tables still showed old database content

**Root Cause:**
```python
def apply_database_by_name(self, db_name):
    repository.switch_database(db_name)
    # ❌ Missing: reload base snapshot
    self.load_initial_records()  # Only reloads UI from cached snapshot
```

**Solution:**
```python
def apply_database_by_name(self, db_name):
    repository.switch_database(db_name)
    repository.load_alle_transacties()      # ✅ Reload from DB
    self._refresh_derived_snapshots()       # ✅ Regenerate derived
    self.load_initial_records()             # Update UI
```

**Lesson:**
Database switch requires full data pipeline reload

---

### Issue 4: IB ERROR 200 - Unknown Symbol

**Symptoms:**
```
[17:36:18] IB-Feed: IB ERROR 200: No security definition has been found
[17:36:18] IB-Feed: IB ERROR 200: No security definition has been found
```

**Root Cause:**
- Delisted stocks in asset_rollup_data
- Wrong ticker symbols (e.g., after merger)
- European stocks needing exchange suffix

**Solution:**
Enhanced error logging to show symbol:
```python
feed.log.emit(f"IB ERROR 200 for {symbol} ({currency}): {errorString}")
```

**Debugging Steps:**
1. Check symbol in TWS (Trader Workstation)
2. Verify currency matches
3. Check if stock delisted/merged
4. For European: add exchange suffix (e.g., ASML.AMS)

**Lesson:**
Error logging must provide context for debugging

---

### Issue 5: Chat Size Growing Large

**Symptoms:**
- Chat file 100MB+
- VS Code slower to open chat
- Concern about context loss

**Solution:**
Created comprehensive documentation (this file) to preserve:
- Technical decisions
- Architecture patterns
- Known issues
- Implementation details

**Lesson:**
Document-first approach enables:
- Context preservation across chat sessions
- Knowledge transfer to team members
- Future-self understanding
- AI assistant onboarding in new chats

---

## 🎓 Key Takeaways

### Architecture Patterns That Work
1. **Snapshot-based data loading** - Fast, but requires manual sync
2. **Batch processing** - Essential for high-frequency updates
3. **Signal/Slot pattern** - Clean separation of concerns (Qt)
4. **Separate live vs static snapshots** - Prevents data pollution

### Best Practices Adopted
1. **Git commit messages** - Descriptive with context
2. **Code organization** - Clear layer separation (data/domain/ui)
3. **Error logging** - Include contextual information
4. **Documentation** - Comprehensive markdown files

### Development Workflow
1. **Iterative development** - Small commits, frequent pushes
2. **Multi-version strategy** - Experiment folders allow parallel exploration
3. **Manual testing** - After each change, verify in GUI
4. **Documentation as you go** - Don't wait until end

---

## 📚 References & Resources

### IBKR API Documentation
- [API Reference](https://interactivebrokers.github.io/tws-api/)
- [Contract Specifications](https://interactivebrokers.github.io/tws-api/contracts.html)
- [Market Data Types](https://interactivebrokers.github.io/tws-api/tick_types.html)

### Libraries
- [Polars Documentation](https://pola-rs.github.io/polars/)
- [PySide6 Documentation](https://doc.qt.io/qtforpython/)
- [PyODBC Documentation](https://github.com/mkleehammer/pyodbc/wiki)

### Git Workflow
- Repository: `https://github.com/onnokievit/portefeuille_viewer`
- Branch: `experiment_0.5`
- Local: `C:\python_coding\portefeuille_viewer\portefeuille_viewer_experiment_0.5`

---

## 📞 Session Metadata

**Date:** October 14, 2025  
**Session Duration:** Extended development session  
**Files Modified:** 5 (orders_tab.py, repository.py, models.py, price_feed.py, portfolio_engine.py)  
**Commits Made:** 3+  
**Lines Added/Modified:** ~100+  
**Major Features:** CRUD completion, snapshot sync, enhanced logging  
**Bugs Fixed:** 4 (GUI sync, delete scope, database switch, error context)  

**Developer Notes:**
- Highly productive session
- Clear progress on core functionality
- Good balance of implementation and documentation
- Multiple architectural discussions documented
- Ready for next development phase

---

**Last Updated:** October 14, 2025  
**Document Version:** 1.0  
**Status:** Complete session summary

---

*This document serves as a comprehensive record of development decisions, implementation details, and architectural patterns for the Portfolio Viewer v0.5. It should be updated after significant changes or when new patterns emerge.*

---

## 2A. Orders Tab - Snapshot Synchronisatie Implementatie

### Overzicht
De Orders tab is succesvol gemigreerd van database-centric naar snapshot-centric architectuur. Dit document beschrijft de implementatie van Stap 1 en Stap 2.

#### Stap 1: Data Loading uit Snapshot ✅ COMPLEET
- `load_initial_records()` en `load_more_records()` lezen nu uit `SNAPSHOT_STORE.snapshot_alle_transacties` in plaats van database queries
- Filtering en sorting gebeurt via Polars expressions in-memory
- Conversie naar Pandas alleen voor display (Optie A benadering)
- Belangrijke functies: `_apply_snapshot_filters()`, `_apply_snapshot_sorting()`, lazy loading met `_current_offset`
- Voordelen: Snellere data loading, geen SQL injection risico, consistent met andere tabs

#### Stap 2: Insert/Update Sync met Snapshot ✅ COMPLEET
- Synchronisatie betekent dat wijzigingen in de database ook direct in de snapshot worden doorgevoerd
- INSERT: na `insert_transaction()` wordt `_add_transaction_to_snapshot()` aangeroepen
- UPDATE: na `update_transactions_atomic()` wordt `_update_transaction_in_snapshot()` aangeroepen
- Beide paden ondersteunen gekoppelde orders

**Voorbeeldcode INSERT:**
```python
eerste_id = insert_transaction(eerste_order)
self._add_transaction_to_snapshot(eerste_order, eerste_id)
if tweede_order:
    tweede_id = insert_transaction(tweede_order)
    self._add_transaction_to_snapshot(tweede_order, tweede_id)
```

**Voorbeeldcode UPDATE:**
```python
update_transactions_atomic(record_id1=int(self.EDIT_ID), data1=data_update_1, ...)
self._update_transaction_in_snapshot(int(self.EDIT_ID), data_update_1)
if self.EDIT_ID2 is not None:
    self._update_transaction_in_snapshot(int(self.EDIT_ID2), data_update_2)
```

#### Helper Functies
- `_add_transaction_to_snapshot(order_dict, record_id)`: voegt nieuw record toe aan snapshot na INSERT
- `_update_transaction_in_snapshot(record_id, data_dict)`: update bestaand record in snapshot na UPDATE

**Voorbeeldcode toevoegen:**
```python
new_row = {**order_dict, "Id": record_id}
new_df = pl.DataFrame([new_row])
SNAPSHOT_STORE.snapshot_alle_transacties = pl.concat([
    SNAPSHOT_STORE.snapshot_alle_transacties,
    new_df
])
```

**Voorbeeldcode updaten:**
```python
mask = SNAPSHOT_STORE.snapshot_alle_transacties["Id"] == record_id
updates = {}
for col_name, new_value in data_dict.items():
    if col_name in SNAPSHOT_STORE.snapshot_alle_transacties.columns:
        updates[col_name] = pl.when(mask).then(pl.lit(new_value)).otherwise(pl.col(col_name))
if updates:
    SNAPSHOT_STORE.snapshot_alle_transacties = SNAPSHOT_STORE.snapshot_alle_transacties.with_columns(**updates)
```

#### Voordelen van Snapshot Sync
- Real-time consistency: snapshot is altijd up-to-date zonder extra database query
- Performance: geen extra SELECT query na INSERT/UPDATE, alles in-memory
- Simpliciteit: snapshot is master voor UI, database is persistent storage
- Future-proof: makkelijk uit te breiden, consistent met aggregator pattern

#### Flow Diagrams
**INSERT:**
User klikt "Opslaan" → `opslaan_orders()` → `insert_transaction()` → `_add_transaction_to_snapshot()` → UI refresh → `ordersCommitted.emit()`

**UPDATE:**
User klikt "Opslaan" (edit mode) → `opslaan_orders()` → `update_transactions_atomic()` → `_update_transaction_in_snapshot()` → UI refresh → `ordersCommitted.emit()`

#### Testing Checklist
- [ ] Insert single/paired order → nieuwe rijen zichtbaar
- [ ] Update bestaande/paired orders → wijzigingen zichtbaar
- [ ] Geen database query na insert/update (alleen in-memory update)
- [ ] Edge cases: snapshot niet geladen, missing columns, rapid inserts

#### Bekende Beperkingen
- Geen DELETE sync (workaround: reload snapshot)
- Geen transaction rollback (snapshot reflecteert database state)
- Memory overhead (Polars is efficient, ~1000-10000 transacties is acceptabel)

#### Toekomstige Verbeteringen
- DELETE sync toevoegen
- Unit tests voor snapshot sync
- Snapshot persistence (pickle/parquet), batch sync, versioning voor undo/redo

#### Conclusie
- Stap 1 (Data Loading): COMPLEET
- Stap 2 (Insert/Update Sync): COMPLEET
- Orders tab is nu volledig snapshot-centric, met snelle UI updates en betere maintainability.

---
