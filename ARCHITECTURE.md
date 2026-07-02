# Open Vending — Architecture Reference

> Purpose: map every UI panel to its data sources, IPC calls, and logic layer so future work can start at the right file without a full codebase scan.

---

## 1. Process & File Overview

```
Electron main process   src/main.js          Node.js, IPC handlers, PDF generation
Preload bridge          src/preload.js        contextBridge → window.api (renderer ↔ main)
Renderer UI             src/index.html        All panels in a single-page app
Picking logic           src/picking.js        Pure JS, no side effects, unit-testable
Route plan              db/route_plan.json    44 machines, team assignments, scheduleDays
Python scripts          src/*.py              Spawned as child processes via spawnPy()
```

Entry point: `package.json` → `"main": "src/main.js"` → loads `src/index.html`.

---

## 2. Data Files

| File | Location | Written by | Read by |
|---|---|---|---|
| `last_report.xlsx` | `db/` | `open_vending.py` (Playwright scrape) | `preload.js` (xlsx.js parse) |
| `last_diffs.json` | `db/` | `main.js` (DIFFS: stdout line) | `main.js` (tray notification) |
| `data.db` | `db/` | `picking_history.py`, `buffer_stock.py` | same scripts via IPC |
| `sales_detail.db` | `db/` | `build_sales_detail.py` | `build_sales_forecast.py` |
| `sales_forecast.db` | `db/` | `build_sales_forecast.py` | `build_sales_forecast.py` (get-forecast-by-weekday) |
| `pick_edit_<machine>_<date>.json` | `db/` | `main.js` (save-pick-edit) | `main.js` (load-pick-edit) |
| `credentials.enc` | `app.getPath('userData')` | `main.js` (safeStorage) | `main.js` on startup |
| `settings.json` | `app.getPath('userData')` | `main.js` | `main.js` on startup |

### data.db tables

| Table | Owner script | Purpose |
|---|---|---|
| `picking_history` | `picking_history.py` | Per-lane pick records; drives in-transit & OOS counts |
| `buffer_stock` | `buffer_stock.py` | Normal/SemBreak buffer qty per machine+lane |
| `buffer_suggestions` | `buffer_stock.py` | DB-persisted suggestion cache |

### last_report.xlsx structure (per sheet = per machine)

Columns after preload inserts machine name as col 0:

| col 0 | col 1 | col 2 | col 3 | col 4 | col 5 | col 6 |
|---|---|---|---|---|---|---|
| Machine | No. (lane#) | Product ID | Product Name | Bal Qty | Lane Size | Restock |

---

## 3. UI Panels

The renderer is a single HTML page. Navigation is `showPanel(id)` toggling display of `<section id="...">` elements. Sidebar icons map to panel IDs:

| Icon | Panel ID | Feature |
|---|---|---|
| dashboard | `home` | Download report + status log |
| people | `history` | Restock history query |
| shopping_basket | `pick` | Picking list (main workflow) |
| inventory_2 | `buffer` | Buffer stock settings |
| assessment | `slow` | Slow movers analysis |
| settings | `settings` | App settings |

---

## 4. Panel → Data Flow

### 4a. Picking List (`#pick`)

**Entry data:**
- `last_report.xlsx` — parsed in preload via `xlsx.js`, passed to `picking.js` as `reportRows[][]`
- `db/data.db` → `picking_history` — via `picking_history.py get-pending` and `get-oos-counts`
- `db/sales_forecast.db` — via `build_sales_forecast.py get-forecast-by-weekday`
- `db/data.db` → `buffer_stock` — via `buffer_stock.py`
- `db/pick_edit_<machine>_<date>.json` — per-machine edit annotations

**Render pipeline:**

```
renderPicks()
  ├─ api.autoClearPicks()          picking_history.py auto-clear   (36h cleanup)
  ├─ api.getPendingInTransit()     picking_history.py get-pending  → currentPending{}
  ├─ api.getOosCounts()            picking_history.py get-oos-counts → currentOos{}
  └─ api.getTodayPicks(xlsx, date, pending)
       └─ picking.machinesToPickToday()  [pure JS]
            Qualify: scheduleDays match OR restock/laneSize ≥ 25%
            Sort: team 5530 → 1126 → others A-Z → machine A-Z

renderPickDetail(machine)
  ├─ api.loadPickEdit(machine, date)    db/pick_edit_*.json
  ├─ api.getForecastByWeekday(weekday)  build_sales_forecast.py
  ├─ api.getBufferSettings()            buffer_stock.py
  └─ api.getPickList(xlsx, machine, pending, oos, forecast, semBreak, buffer)
       └─ picking.buildPickingList()  [pure JS]
            Filter: restock=0 hidden, bal>10 hidden
            Flags: outOfStock (bal=0), fastMover (oos7≥3)
            Restock = rawRestock − inTransit + forecastQty + bufferQty
```

**Row fields from `buildPickingList()`:**

```js
{ no, productId, product, bal, lane, restock, forecastQty, bufferQty,
  outOfStock, fastMover, laneNo }
```

**Edit Mode:**
- Triggered by ✏️ button in detail header (`enterEditMode(machine)`)
- Loads `pick_edit_*.json`; table adds Replacement col + ⇅ swap button
- Auto-saves via `api.savePickEdit()` on 1 s debounce after any input
- `collectEditRows()` collects: `{ no, product, bal, lane, restock, replacement, outOfStock, fastMover }`
- Replacement annotations shown in view mode as `→ name` sub-text under product

**Queue / Print workflow** (separate from Edit Mode):
- ☑ button → `confirmAndQueuePrintCurrent()` → `api.savePicks()` → `picking_history` table
- Queue modal shows `currentPending` machines; delete = `api.markDone()`
- PDF export: `printAll()` → merges replacement from `pick_edit_*.json` → IPC `print-all-picking-lists` → `main.js` generates HTML → `printToPDF()`

**Buffer mode toggle (`semBreakMode`):**
- Lives in picking list toolbar (global for current session)
- `false` = Normal buffer, `true` = SemBreak buffer column used

---

### 4b. History (`#history`)

- UI: machine + lane input → query button
- IPC: `get-restock-history` → spawns `query_history.py machine lane`
- Data: `data.db` → `picking_history` table
- Returns: `[{ pick_date, picked_qty, out_of_stock }]`

---

### 4c. Buffer Stock (`#buffer`)

- IPC: `init-buffer-db`, `get-buffer-settings`, `set-buffer-qty`, `calc-buffer-suggestions`, `load-buffer-suggestions`
- Script: `buffer_stock.py` — reads `data.db` (buffer_stock + buffer_suggestions tables)
- UI: two columns Normal/SemBreak; Apply checkbox pattern; sort+search

---

### 4d. Slow Movers (`#slow`)

Two modes:
1. **CSV mode**: `analyzeSlowMovers(productCsv, salesCsv)` → `slow_movers.py` (no persistent DB)
2. **DB mode**: build once with `generateSlowDb()` → `slow_movers.py build` → user-chosen `.db`; then `analyzeSlowDb(dbPath)` → `slow_movers.py analyze`

PDF: `printSlowMovers()` → IPC `print-slow-movers` → `main.js`

---

### 4e. Settings (`#settings`)

- Read/write: `settings.json` via `get-settings` / `set-setting`
- Credentials: `credentials.enc` via `safeStorage` (OS keychain encryption)
- Auto-download timer managed in `main.js` (`setupAutoDownload()`)

---

## 5. IPC API Map

All renderer→main calls go through `window.api` (defined in `preload.js`).

### Download / Browser

| `window.api` method | IPC channel | Handler location |
|---|---|---|
| `startDownload()` | `start-download` | `main.js` → `runDownload()` → `open_vending.py` |
| `launchBrowser()` | `launch-browser` | `main.js` → `launchBrowser()` → `open_vending.py --login-only` |
| `closeBrowser()` | `close-browser` | writes `.browser_stop` sentinel file |

### Picking History (`picking_history.py`)

| `window.api` method | IPC channel | `picking_history.py` arg |
|---|---|---|
| `autoClearPicks()` | `auto-clear-picks` | `auto-clear` |
| `getPendingInTransit()` | `get-pending-in-transit` | `get-pending` |
| `getOosCounts()` | `get-oos-counts` | `get-oos-counts` |
| `savePicks(picks)` | `save-picks` | `save-picks` (stdin JSON) |
| `markDone(machines)` | `mark-done` | `mark-done` (stdin JSON) |
| `getRestockHistory(m, lane)` | `get-restock-history` | `query_history.py m lane` |

### Pick Edit (JSON files, no Python)

| `window.api` method | IPC channel | File |
|---|---|---|
| `savePickEdit(machine, date, rows)` | `save-pick-edit` | `db/pick_edit_<safe>_<date>.json` |
| `loadPickEdit(machine, date)` | `load-pick-edit` | same |

### Forecast (`build_sales_detail.py`, `build_sales_forecast.py`)

| `window.api` method | Script | Purpose |
|---|---|---|
| `buildSalesDetailDb(csvPath)` | `build_sales_detail.py` | CSV → `sales_detail.db` |
| `getSalesDetailMeta()` | `build_sales_detail.py meta` | row count + date range |
| `buildSalesForecastDb()` | `build_sales_forecast.py` | `sales_detail.db` → `sales_forecast.db` |
| `getSalesForecastMeta()` | `build_sales_forecast.py meta` | record count |
| `getForecastByWeekday(wd)` | `build_sales_forecast.py` | `{machine: {pid: avg_qty}}` |

### Buffer Stock (`buffer_stock.py`)

| `window.api` method | `buffer_stock.py` arg |
|---|---|
| `initBufferDb()` | `init db/data.db` |
| `getBufferSettings()` | `get db/data.db` |
| `setBufferQty(rows)` | `set db/data.db` (stdin JSON) |
| `calcBufferSuggestions()` | `suggest db/data.db` |
| `loadBufferSuggestions()` | `load-suggestions db/data.db` |

### Pure JS (no IPC, runs in renderer)

| `window.api` method | Logic | Input |
|---|---|---|
| `getTodayPicks(xlsx, dateISO, pending)` | `picking.machinesToPickToday()` | reportRows, routePlan, Date |
| `getPickList(xlsx, machine, ...)` | `picking.buildPickingList()` | reportRows + 6 modifiers |
| `parseExcel(filePath)` | `xlsx.js` parse | `.xlsx` file |
| `teamOf(machine)` | `route_plan.json` lookup | machine name string |
| `getAllMachines(xlsx, pending)` | `picking.js` helpers | reportRows, routePlan |

---

## 6. `picking.js` Logic Summary

**`machinesToPickToday(reportRows, routePlan, date, pendingByMachine)`**
- Qualifies machine if: `scheduleDays` includes today's weekday **OR** `restock/laneSize ≥ 0.25`
- In-transit deduction: subtracts pending qty before computing pct
- Returns sorted array: `{ machine, team, reason, pct, restockSum, laneSum }`

**`buildPickingList(reportRows, machine, pendingByLane, oosByLane, forecastByPid, semBreak, bufferByLane)`**
- Hides rows: `actualRestock = 0` or `bal > 10`
- `finalRestock = max(0, rawRestock − inTransit + forecastQty + bufferQty)`
- `forecastQty = 0` when `semBreak = true`
- `fastMover = true` when `oos7 ≥ 3`

---

## 7. Python Scripts

| Script | Invoked via | Purpose |
|---|---|---|
| `open_vending.py` | `spawn()` directly | Playwright browser scrape → writes `last_report.xlsx` |
| `picking_history.py` | `spawnPy()` | CRUD on `data.db` picking_history table |
| `query_history.py` | `spawn()` directly | Query picking_history for chart data |
| `buffer_stock.py` | `spawnPy()` | CRUD on `data.db` buffer tables |
| `build_sales_detail.py` | `spawnPy()` | CSV → `sales_detail.db` (raw transactions) |
| `build_sales_forecast.py` | `spawnPy()` | `sales_detail.db` → `sales_forecast.db` (avg_qty/weekday) |
| `slow_movers.py` | `spawnPy()` | Analyse slow-moving products from CSV or `.db` |

All Python scripts communicate via **stdout JSON** (return value) and **stdin JSON** (for scripts that take input data). Never write to files directly from renderer.

---

## 8. Key Design Constraints

- **No nodeIntegration in renderer** — all Node/file access must go through IPC.
- **`picking.js` is pure** — no IPC, no fs, no DB. Safe to call synchronously in renderer.
- **`db/route_plan.json`** is the authoritative source for team assignments and schedule rules. Machines absent from it are ignored by `machinesToPickToday` and `getAllMachines`. Editable via the Route Plan panel (Q8), which writes back through `save-route-plan` IPC. Lives under `db/` (gitignored directory) but stays tracked in git since it was already committed before the move — git only skips *untracked* files matching an ignore rule.
- **`semBreakMode`** is a session-only global in the renderer (not persisted in settings). Managed in the picking panel toolbar.
- **Pick edits** (`pick_edit_*.json`) are per-machine per-date flat JSON files — no DB table. They store replacement annotations and any manual row overrides from Edit Mode.
- **`src/src/`** is a stale duplicate directory — the app loads from `src/` only. Do not edit files under `src/src/`.
