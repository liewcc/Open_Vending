# Phase 3 实施步骤书（交给执行模型用）

> 写于 2026-07-12。所有代码锚点已对照当时的 working tree（HEAD = cbf98fc）核实过。
> 四个待拍板决策已由用户定案：
> 1. Duplex padding 做成 Settings 开关，**默认开**
> 2. 动向 filter 做 **A+B**（dropdown 过滤 + Sold 列）
> 3. 全局 `+ / 0 / −` 按钮**保留，当「批量设全部」**
> 4. Sidebar 本周记录用**方案 A（行内 day 徽章）**

---

## 全局规则（每个 Task 都适用，先读完再动工）

1. **一个 Task 一个 commit，严格按 Task 1 → 7 顺序执行**。Task 6 依赖 Task 5 改过的列索引，Task 7 依赖 Task 6 的 buffer cell 代码，顺序不能乱。
2. **行号会漂移**。本文档给的行号只是初始参考；定位一律用「锚点代码」（文中给出的唯一代码片段）做全文搜索。
3. **`src/picking.js` 的 `buildPickingList()` 引擎零改动**。本计划所有 Task 都不需要碰它。整个 picking.js 只读不写。
4. **每个 Task 完成后必须跑**：`node src/picking.js` —— 必须输出 `picking.js self-check OK`。
5. Python 脚本可以直接用项目自带解释器测试：`python\python.exe src\<script>.py <args>`（在项目根目录执行）。
6. app 启动验证用 `run.bat`（或 `node_modules\.bin\electron .`）。**注意**：Export PDF/Excel 的原生保存对话框无法自动化点击，这类验证做到「按钮触发、payload 正确」为止，最后落盘那一下留给用户人工确认。
7. 代码注释用英文，风格跟周围代码一致。不要顺手重构任何无关代码。
8. **每完成一个 Task**：在 `HANDOFF.md` 的 Phase 3 对应条目标 ✅ + commit hash，并同步更新文件顶部「未完成事项总览」。
9. commit message 末尾照本仓库惯例不加多余尾注，格式 `feat: ...` / `fix: ...`。

### 关键文件速览

| 文件 | 作用 |
|---|---|
| `src/index.html` | 全部前端 UI + 渲染逻辑（单文件，~2700 行） |
| `src/main.js` | Electron 主进程，IPC handler，PDF 导出，settings |
| `src/preload.js` | contextBridge API 层，route plan 内存副本 |
| `src/picking.js` | 纯逻辑引擎（**不许改**） |
| `src/picking_history.py` | picking_history 表 CLI（vending.db） |
| `src/buffer_stock.py` | buffer_stock 表 CLI |
| `db/route_plan.json` | 每台机器 team/scheduleDays 元数据 |

### 现有约定（写代码时要遵守）

- 前端调 Python 一律走 main.js 的 `spawnPy([SCRIPT, ...args], stdinData)` → 返回 parse 好的 JSON。
- 机器名有两套：报表 sheet 名（前端 identity，31 字符截断）vs route_plan 全名。转换用 `picking.planKeyFor()`（preload.js 的 `teamOf` 是现成范例）。`daily_sales`（vending.db 查询层）已处理 sheet_alias，直接 `WHERE machine=?` 用 sheet 名查即可（`replacement_suggest.py:69` 是生产验证过的同款查询）。
- 设置持久化：前端 `applySetting(key, val)` / `window.api.setSetting`；默认值加进 main.js 第 12 行的 `DEFAULT_SETTINGS`；启动加载在 index.html 的 `window.api.getSettings().then(s => {...})` 块（锚点 `if (s.uiZoom) applyUiZoom`）。
- pill toggle 按钮范例：`#btn-toggle-highbal`（class `pick-icon-btn pick-flt-btn`，选中态 toggle class `in-queue`）。

---

## Task 1（原 Phase 3-5）：未来日期 = 计划视图（详情页/单机打印扣减 in-transit）

**目标**：日期选未来时，详情页和单机打印按 lane 扣减 in-transit qty（`actual − in-transit`）；今天及过去行为不变。改动只有 `src/index.html` 两处。

**背景语义**：过去 = history（已实现只读）；今天 = 执行视图（不扣，拣货单要完整——历史上「入 queue 后单机打印全空白」就是扣了自己 queue 导致的）；未来 = 计划视图（扣）。引擎的 `pendingByLane` 扣减早已内建（picking.js `actualRestock = max(0, restock − laneInTransit)`），只是这两个入口故意传了 `{}`。

### 步骤

**1a. `renderPickDetail`** — 锚点：

```js
      const oosByLane = (currentOos[machine]) || {}
      const pl = window.api.getPickList(lastFilePath, machine, {}, oosByLane, currentForecast[machine] || {}, restockMode !== 'normal', getBufferByLane(machine))
      const team = window.api.teamOf(machine) || '—'
      const dateStr = document.getElementById('pick-date').value
```

改成（注意 `dateStr` 声明**提前**了，原来在 `pl` 之后的那行要删掉，别声明两次）：

```js
      const oosByLane = (currentOos[machine]) || {}
      const dateStr = document.getElementById('pick-date').value
      const todayStr = (() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}` })()
      // Future date = planning view: deduct in-transit qty so the office can
      // prep tomorrow's list mid-route. Today = execution view: never deduct
      // (a queued machine's own pending entry would zero every lane).
      const planPending = dateStr > todayStr ? (currentPending[machine] || {}) : {}
      const pl = window.api.getPickList(lastFilePath, machine, planPending, oosByLane, currentForecast[machine] || {}, restockMode !== 'normal', getBufferByLane(machine))
      const team = window.api.teamOf(machine) || '—'
```

**1b. `doPrintCurrentMachine`** — 锚点（函数内 else 分支）：

```js
      const oosByLane = (currentOos[machine]) || {}
      const pl = window.api.getPickList(lastFilePath, machine, {}, oosByLane, currentForecast[machine] || {}, restockMode !== 'normal', getBufferByLane(machine))
```

该函数上方已有 `const dateStr = document.getElementById('pick-date').value`。在 else 分支里同样构造 `todayStr` + `planPending`（代码同 1a），把 `{}` 换成 `planPending`。函数上方那段 `// The saved edit (if any) ...` 注释末尾补一句 `Future dates deduct in-transit (planning view).`

**注意**：`buildQueuePicks` 里的 `getPickList(..., {}, ...)` **绝对不要动**——那个 `{}` 是故意的（入队是 wholesale replace，不能被自己旧 entry 扣减，代码里有注释）。有编辑存档时两个入口走 `saved.rows`，不经过此计算——可接受（编辑存档本来就是 source of truth）。

### 验证
1. `node src/picking.js` → OK
2. 启动 app：把某台机器加入 queue → 日期不动（今天）打开该机详情 → restock 数字**不变**（完整）
3. 日期改成明天 → 同一台机器详情 → 有 queue 记录的 lane restock 减少了对应数量（全被 queue 覆盖的 lane 变灰 R=0 行）
4. 日期改回今天 → 恢复完整

**Commit**: `feat: future-date planning view — detail & single print deduct in-transit`

---

## Task 2（原 Phase 3-6）：Queue 导出支持选择机器

**目标**：Queue modal 每台机器加 checkbox（默认全勾），Export Excel / Export PDF 只导出勾选的机器。只改 `src/index.html`，后端零改动。

### 步骤

**2a. `showQueueView`** — 锚点：

```js
        html += `<div class="q-item"><div style="flex:1"><span class="q-machine"
```

在 `<div class="q-item">` 之后、`<div style="flex:1">` 之前插入 checkbox（跟 in-transit panel 的 `value="${mach}"` 同款写法）：

```js
        html += `<div class="q-item"><input type="checkbox" class="q-chk" value="${mach}" checked style="margin-right:8px;flex-shrink:0;"><div style="flex:1"><span class="q-machine" ...（其余原样不动）
```

**2b. 新增 helper**（放在 `collectQueueRows` 前面）：

```js
  function selectedQueueMachines() {
    return new Set([...document.querySelectorAll('#queue-modal-body .q-chk:checked')].map(cb => cb.value))
  }
```

**2c. `exportQueueExcel` 和 `exportQueuePdf`** — 两个函数的第一行 `const rows = await collectQueueRows()` 都改成：

```js
    const sel = selectedQueueMachines()
    const rows = (await collectQueueRows()).filter(r => sel.has(r.machine))
```

（`if (!rows.length) return` 保留——全不勾 = 静默不导出，跟 queue 为空同行为。）

### 验证
1. queue 里放 2+ 台机器 → 打开 queue modal → 每行有 checkbox 且默认全勾
2. 取消勾选一台 → 点 Export Excel → 保存对话框弹出（人工确认文件里只有勾选的机器）
3. 全不勾 → 两个 Export 按钮点了无反应（不弹对话框）
4. checkbox 不影响原有 Edit / Remove / Refresh / Delete All 按钮

**Commit**: `feat: queue export respects per-machine checkboxes (default all checked)`

---

## Task 3（原 Phase 3-7）：Sidebar 显示本周已做 list 的机器（day 徽章）

**目标**：picking sidebar 机器行内显示本周（周一至周六）做过 list 的日子（中文 day 徽章如 `一 三 五`），工具栏 pill toggle 控制显隐并持久化。判定语义（用户已拍板）：**picking_history 有记录即算**（入过 queue 就算，不要求 mark done）。

**已查证的边界（写进代码注释即可，不用处理）**：36h auto-clear 是 UPDATE 不是 DELETE，行保留、照算；wholesale replace（同机 36h 内重复入队）会删掉旧 pending 行导致更早那天的徽章消失——小概率失真，可接受；从 queue 手动删除（markDone）行保留、照算。

### 步骤

**3a. `src/picking_history.py`** — 在 `elif cmd == 'mark-done':` 之前插入：

```python
elif cmd == 'get-week-summary':
    # {machine: [pick_date, ...]} within [from, to]. Any status counts:
    # a row means "a list was made" (auto_cleared/done rows are UPDATEd,
    # never deleted; wholesale re-queue within 36h can drop an earlier
    # day's pending row — accepted, rare).
    d_from = sys.argv[2] if len(sys.argv) > 2 else ''
    d_to   = sys.argv[3] if len(sys.argv) > 3 else ''
    if not DB.exists() or not d_from or not d_to:
        print(json.dumps({})); sys.exit(0)
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT machine, pick_date FROM picking_history "
        "WHERE pick_date BETWEEN ? AND ? ORDER BY machine, pick_date",
        (d_from, d_to)
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        result.setdefault(r['machine'], []).append(r['pick_date'])
    print(json.dumps(result))
```

**3b. `src/main.js`** — 锚点 `ipcMain.handle('get-history-by-date'`，其后加一行：

```js
ipcMain.handle('get-week-summary',       (_, r)    => spawnPy([PICKING_HISTORY, 'get-week-summary', r.from, r.to], null))
```

**3c. `src/preload.js`** — 锚点 `getHistoryByDate:`，其后加一行：

```js
  getWeekSummary:       (from, to)       => ipcRenderer.invoke('get-week-summary', { from, to }),
```

**3d. `src/index.html` 状态 + toggle** — 锚点 `let showHighBal = false`，在同一区域加：

```js
  let showWeekBadges = true   // sidebar: day badges for machines with a list made this week
  function toggleWeekBadges() {
    showWeekBadges = !showWeekBadges
    document.getElementById('btn-toggle-week')?.classList.toggle('in-queue', showWeekBadges)
    window.api.setSetting('showWeekBadges', showWeekBadges)
    renderPicks()
  }
```

设置加载（锚点 `if (s.q3ThresholdPct)` 所在的 getSettings 块内）加：

```js
    if (s.showWeekBadges === false) showWeekBadges = false
    document.getElementById('btn-toggle-week')?.classList.toggle('in-queue', showWeekBadges)
```

main.js `DEFAULT_SETTINGS` 加 `showWeekBadges: true`。

**3e. 工具栏按钮** — 锚点 `id="btn-show-all"`，在它**前面**插入：

```html
    <button id="btn-toggle-week" class="pick-icon-btn pick-flt-btn in-queue" onclick="toggleWeekBadges()" title="Show / hide day badges for machines with a list made this week (Mon–Sat)">Wk</button>
```

**3f. `renderPicks` 取数 + 渲染** — 在 `const list = window.api.getTodayPicks(...)` 之前加（`dateStr` 该函数上方已有）：

```js
      // Week badges: machines with any picking_history row in the week
      // (Mon–Sat) containing the selected date. Purely derived — rolls over
      // automatically on Monday, no storage, no cleanup.
      let weekDone = {}
      if (showWeekBadges) {
        const wd = new Date(dateStr + 'T12:00:00')
        const dowW = (wd.getDay() + 6) % 7            // 0 = Mon
        const mon = new Date(wd); mon.setDate(wd.getDate() - dowW)
        const sat = new Date(mon); sat.setDate(mon.getDate() + 5)
        const fmtD = x => `${x.getFullYear()}-${String(x.getMonth()+1).padStart(2,'0')}-${String(x.getDate()).padStart(2,'0')}`
        weekDone = await window.api.getWeekSummary(fmtD(mon), fmtD(sat)) || {}
      }
```

然后在 `displayList.forEach(m => {` 循环里，锚点：

```js
        row.innerHTML = `<span>${m.machine}</span><span class="pick-badge ${badgeClass}">${badgeText}</span>`
```

改成：

```js
        const DAY_CH = ['一','二','三','四','五','六','日']
        const wkDays = (weekDone[m.machine] || []).map(dt => DAY_CH[(new Date(dt + 'T12:00:00').getDay() + 6) % 7]).join(' ')
        const wkHtml = wkDays ? `<span class="pick-week-badge">${wkDays}</span>` : ''
        row.innerHTML = `<span>${m.machine}</span>${wkHtml}<span class="pick-badge ${badgeClass}">${badgeText}</span>`
```

（`DAY_CH` 也可以提到循环外，随意。）

**3g. CSS** — 找到 `.pick-badge` 的样式定义处，在附近加：

```css
.pick-week-badge{font-size:9.5px;color:#0e7490;background:#e0f2fe;border-radius:4px;padding:1px 5px;margin-left:auto;margin-right:5px;white-space:nowrap;flex-shrink:0}
```

**注意**：先看一眼 `.pick-mach` 的现有 flex 布局（机器名 span + pct 徽章 span 怎么分布），如果 pct 徽章本身已用 `margin-left:auto` 靠右，则把 week 徽章的 `margin-left:auto` 去掉、改由原徽章保持右贴，week 徽章紧贴其左即可——目标视觉：`机器名 …… [一 三] [45%]`。

### 验证
1. CLI：`python\python.exe src\picking_history.py get-week-summary 2026-07-06 2026-07-11` → 返回 `{机器名: [日期...]}` 且非空（本周有真实记录）
2. app：sidebar 中本周入过 queue 的机器显示对应 day 徽章；`Wk` pill 点一下徽章全部消失、再点恢复
3. 重启 app → toggle 状态保持
4. 日期切到上周（history 模式）不报错（history 分支不渲染徽章，正常）
5. `node src/picking.js` → OK

**Commit**: `feat: sidebar day badges for machines with a list made this week (Mon–Sat)`

---

## Task 4（原 Phase 3-1）：双面打印补齐偶数页（Duplex padding）

**目标**：`print-all-picking-lists` 和 `export-queue-pdf` 两个 handler 里，除最后一台机器外，占奇数页的机器后面插一页真空白（无表头），使每台机器占偶数页——双面打印时下一台永远从新纸正面开始。Settings PDF Export 卡片加开关，默认开。**slow movers 是单一文档，不改。**

**已实测排除**：CSS `break-before:right` 在 Electron 32 的 printToPDF 下完全无效（2026-07-10 实测），不要再试。方案 = 复用现有分页模拟器（simScript）逐台数页 + DOM 插空白 div。

### 步骤

**4a. `src/main.js` DEFAULT_SETTINGS** 加 `pdfDuplex: true`。

**4b. Settings UI（`src/index.html`）** — PDF Export 卡片，锚点 "Pages per Machine" 那个 `toggle-row`，在其**后**加一个同款 `toggle-row`：

```html
      <div class="toggle-row">
        <div>
          <div class="toggle-label">Duplex Padding</div>
          <div class="toggle-desc">Pad each machine to an even page count so two-sided printing never puts two machines on one sheet</div>
        </div>
        <input type="checkbox" id="pdf-duplex" onchange="applySetting('pdfDuplex', this.checked)">
      </div>
```

**先看一眼**本文件其他布尔设置（如 `tog-notify`）的 checkbox 是否套了自定义开关样式（`.switch` 之类的 label 包装）——如果有，照抄那个 markup 结构，保持视觉一致。

设置加载块（锚点 `document.getElementById('pdf-m-right').value`）后加：

```js
    document.getElementById('pdf-duplex').checked = s.pdfDuplex !== false
```

**4c. `print-all-picking-lists` handler（main.js）** — 锚点：字体缩放循环结束的 `}` 之后（即 `if (pages >= 1) { ... }` 整块之后）、`const pdfBuffer = await printWin.webContents.printToPDF(L.printOpts)` 之前，插入：

```js
  // Duplex padding: after the font is final, count each machine's real page
  // usage with the same pagination simulation, then insert one true blank
  // page after every odd-paged machine (except the last — nothing follows).
  // CSS break-before:right is ignored by this Chromium's printToPDF, so the
  // blank is a real DOM element (&nbsp; keeps it from collapsing).
  if (settings.pdfDuplex !== false) {
    const countScript = `(() => {
      const pageH = ${L.pageH.toFixed(2)};
      const counts = [];
      document.querySelectorAll('.page').forEach(pg => {
        const table = pg.querySelector('table');
        const thead = pg.querySelector('thead');
        if (!table || !thead) { counts.push(1); return; }
        const headerH = table.getBoundingClientRect().top - pg.getBoundingClientRect().top;
        const theadH = thead.getBoundingClientRect().height;
        let used = headerH + theadH;
        let n = 1;
        pg.querySelectorAll('tbody tr').forEach(tr => {
          const h = tr.getBoundingClientRect().height;
          if (used + h > pageH) { n++; used = theadH + h; } else { used += h; }
        });
        counts.push(n);
      });
      return counts;
    })()`
    const counts = await printWin.webContents.executeJavaScript(countScript)
    await printWin.webContents.executeJavaScript(`(() => {
      const pages = document.querySelectorAll('.page');
      const counts = ${JSON.stringify(counts)};
      for (let i = 0; i < pages.length - 1; i++) {
        if (counts[i] % 2 === 1) {
          const blank = document.createElement('div');
          blank.className = 'page';
          blank.innerHTML = '&nbsp;';
          pages[i].after(blank);
        }
      }
    })()`)
  }
```

原理说明（不用写进代码）：空白 div 挂 `.page` class 拿到 `page-break-after:always`；前一台机器的 break-after 把空白推到新页，空白自己的 break-after 把下一台推到再下一页；空白内容只有 `&nbsp;` 恰占 1 页。`pages[i].after()` 用的是插入前抓好的静态 NodeList，插入不影响迭代。`.page:last-child{page-break-after:avoid}` 仍然命中最后一台真机器（最后一台后面不插空白）。

**4d. `export-queue-pdf` handler（main.js）** — 同一段代码，插在它的字体缩放 for 循环之后、`const pdfBuffer = await printWin.webContents.printToPDF(L.printOpts)` 之前。该 handler 的 `L` 同样在作用域内。两处代码完全相同，直接复制。

### 验证
1. `node src/picking.js` → OK
2. app：queue 放 2 台机器（第一台行数少、明显 1 页能装下）→ queue modal Export PDF → 人工保存 → 打开 PDF：**第 2 页是空白页，第二台机器从第 3 页开始**；最后一台后面没有多余空白页
3. Settings 关掉 Duplex Padding → 再导一次 → 第二台机器直接在第 2 页
4. 单机打印（详情页 PDF 图标，走 print-all-picking-lists、单台）→ 不多出空白页（单台=最后一台，不补）

**已知风险（记录在案即可）**：sim 与 Chromium 真实分页在压线行上可能差一行导致空白页偶尔插错；多次实测 sim 相当准。若用户日后回报错位，升级方案（逐台真实试印数页）已写在 HANDOFF Phase 3 第 1 条的「方案 2」。

**Commit**: `feat: duplex padding — pad each machine's PDF section to an even page count (setting, default on)`

---

## Task 5（原 Phase 3-2）：Edit mode 销售动向 — Sold 列 + 时间窗口过滤（A+B）

**目标**：Edit mode 表格 Product 和 Bal 之间加 **Sold 列**（显示该机器该 PID 在所选窗口内的销量）；edit banner 加 dropdown（off / 1d / 10d / 20d）；选中窗口时 Sold 列填数**且自动隐藏窗口内零动销的行**（找 dead lane），off 时全部显示、Sold 列显示 `—`。只影响 edit mode，view 模式表格不动。

**已知限制**（不用处理）：`daily_sales` 粒度是天，1d = 数据里最新一个销售日；同一 PID 跨多条 lane 时每行显示同一个整机总量（数据没有 lane 粒度，可接受）。

### ⚠️ 列索引大改——本 Task 最容易出错的地方

插入 Sold 列后，edit 表格 td 索引变为：

| idx | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| 列 | No | Product | **Sold(新)** | Bal | Lane | Forecast | Buffer | Restock | Replacement | 按钮 |

以下**四处**硬编码索引必须同步更新（都只在 edit mode 生效，view 模式表格无 Sold 列、也不经过这些函数）：

1. `collectEditRows()`：`bal: tds[2]` → `tds[3]`，`lane: tds[3]` → `tds[4]`，`restock: tds[6]` → `tds[7]`，`replacement: tds[7]?` → `tds[8]?`
2. `handleSwap()`：`tdsA[7].textContent` / `tdsB[7].textContent` → `tdsA[8]` / `tdsB[8]`
3. `applySuggestion()`：`tr.cells[7].textContent = name` → `tr.cells[8]`
4. edit 分支的 `makeSortable(detailEl.querySelector('table.pick-tbl'), { skipCols: [8] })` → `{ skipCols: [9] }`

### 步骤

**5a. 新文件 `src/machine_sales.py`**：

```python
"""
machine_sales.py — per-machine sales totals over the last N days of data.

Usage:
    python machine_sales.py <vending_db> <machine> <days>

Prints: {"ok": true, "window": {"from":..., "to":...}, "sales": {pid: qty}}
Window is anchored to MAX(sale_date) in daily_sales (manual rebuilds lag
behind today), same convention as replacement_suggest.py. days=1 means the
newest sale day only (daily_sales has no time-of-day granularity).
"""
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(0)


def main():
    if len(sys.argv) < 4:
        fail("usage: machine_sales.py <vending_db> <machine> <days>")
    db_path, machine = sys.argv[1], sys.argv[2]
    try:
        days = max(1, int(sys.argv[3]))
    except ValueError:
        days = 1
    if not Path(db_path).exists():
        fail("vending.db not found")
    conn = sqlite3.connect(db_path)
    max_date = conn.execute("SELECT MAX(sale_date) FROM daily_sales").fetchone()
    if not max_date or not max_date[0]:
        conn.close()
        fail("daily_sales is empty — rebuild it (import sales CSV)")
    to_date = max_date[0][:10]
    from_date = (datetime.strptime(to_date, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    sales = dict(conn.execute(
        "SELECT pid, SUM(qty) FROM daily_sales WHERE machine=? AND sale_date>=? GROUP BY pid",
        (machine, from_date),
    ).fetchall())
    conn.close()
    print(json.dumps({"ok": True, "window": {"from": from_date, "to": to_date}, "sales": sales}))


if __name__ == "__main__":
    main()
```

**5b. `src/main.js`** — 锚点 `const REPL_SUGGEST`，其后加：

```js
const MACHINE_SALES        = path.join(__dirname, 'machine_sales.py')
```

锚点 `ipcMain.handle('get-replacement-data'`，其后加：

```js
ipcMain.handle('get-machine-sales', (_, { machine, days }) => spawnPy([MACHINE_SALES, SALES_DETAIL_DB, machine, String(days)], null))
```

**5c. `src/preload.js`** — 锚点 `getReplacementData:`，其后加：

```js
  getMachineSales:        (machine, days) => ipcRenderer.invoke('get-machine-sales', { machine, days }),
```

**5d. `src/index.html` 状态** — 锚点 `let q3ThresholdPct = 50`，其后加：

```js
  let mvWindow = 0    // sales-movement window in days; 0 = off
  let mvSales = {}    // {pid: qty} for the current window (edit mode)
```

**5e. dropdown 换窗口 handler**（放在 `onQ3ThresholdChange` 附近）：

```js
  async function onMvWindowChange(v) {
    mvWindow = Number(v) || 0
    if (isEditMode && editMachine) {
      // flush the pending autosave before re-rendering wipes the DOM
      clearTimeout(editSaveTimer)
      const r = collectEditRows(); const d = document.getElementById('pick-date').value.replace(/-/g, '')
      if (r) { await window.api.savePickEdit(editMachine, d, r); await syncQueueWithEdit(editMachine) }
      renderPickDetail(editMachine)
    }
  }
```

**5f. edit 分支取数** — `renderPickDetail` edit 分支，锚点 `const q3 = await loadQ3Suggestions(machine, rows)`，其后加：

```js
        mvSales = {}
        if (mvWindow > 0) {
          const mv = await window.api.getMachineSales(machine, mvWindow)
          if (mv && mv.ok) mvSales = mv.sales || {}
        }
```

**5g. banner 加 dropdown** — 锚点 `hdHtml += `<div class="edit-banner"`，在拼进 `${q3Ctl}` 之前先构造（q3Ctl 带 `margin-left:auto`，所以 mvCtl 要放在 q3Ctl 前面才能都靠右——实际写法是把 mvCtl 拼在 q3Ctl 字符串前）：

```js
        const mvCtl = `<span style="font-weight:400;margin-left:auto;">Sold <select onchange="onMvWindowChange(this.value)" style="padding:1px 4px;border:1px solid #d1d5db;border-radius:4px;font-size:11px;"><option value="0"${mvWindow===0?' selected':''}>off</option><option value="1"${mvWindow===1?' selected':''}>1d</option><option value="10"${mvWindow===10?' selected':''}>10d</option><option value="20"${mvWindow===20?' selected':''}>20d</option></select></span>`
```

然后把 q3Ctl 两个分支里的 `margin-left:auto` **删掉**（改成 `margin-left:10px`），edit-banner 那行改成 `...auto-saved${mvCtl}${q3Ctl}</div>`。这样 dropdown 和 q3 阈值控件并排靠右。

**5h. 表头 + 行渲染** — edit 分支 thead 锚点：

```js
<th data-col="product">Product</th><th data-col="bal">Bal</th>
```

中间插 `<th data-col="sold">Sold</th>`。表格 class 改为：

```js
`<table class="lv-tbl pick-tbl${mvWindow > 0 ? ' hide-mvzero' : ''}">`
```

行循环里（锚点 `const bufCol = r.bufferQty ?`附近），加：

```js
            const soldQty = mvWindow > 0 ? (Number(mvSales[String(r.productId)]) || 0) : null
            const soldTd = mvWindow > 0 ? `<td style="color:#6b7280">${soldQty}</td>` : `<td style="color:#c3c8d0">—</td>`
```

行 class 数组（锚点 `const cls = [r.outOfStock?'pick-out':''`）追加一项：

```js
soldQty === 0 ? 'mv-zero' : ''
```

（注意 `soldQty === 0` 严格等于——off 时是 `null` 不命中。）行模板里在 product td 之后、bal td 之前插 `${soldTd}`。

**5i. 四处索引更新**（见上方表格，逐一改）。

**5j. CSS** — 锚点 `.hide-highbal`（找到现有 hide-highbal / hide-zero 规则处），加：

```css
table.pick-tbl.hide-mvzero tbody tr.mv-zero{display:none}
```

### 验证
1. CLI：`python\python.exe src\machine_sales.py db\vending.db "KK1 M3" 10` → `{"ok": true, ..., "sales": {...}}` 非空；`days=1` 时窗口 from==to
2. `node src/picking.js` → OK
3. app：进 edit mode → 默认 off，Sold 列全是 `—`，行数不变
4. dropdown 切 10d → Sold 列出数字，零动销行消失；切 off → 全部回来
5. 窗口开着时：⇅ swap 两行 → Replacement 栏（第 9 列）正确互填，不是别的列；💡 建议点选 → 填进 Replacement 栏；改一个 Restock 数字等 1 秒自动保存 → 重进 edit mode 数字还在、产品名干净（无标签文字混入）
6. 排序点 Sold 表头 → 数字排序正常；按钮列（最后一列）不可排序

**Commit**: `feat: edit-mode Sold column + sales-window filter (off/1d/10d/20d)`

---

## Task 6（原 Phase 3-3）：Edit mode 的 Buffer 栏可编辑，直接写回 buffer_stock

**前置**：Task 5 已完成（本 Task 使用 Task 5 之后的列索引：Buffer = td 6）。

**目标**：edit mode 的 Buffer 格从只读「当日施加值」改为显示并编辑**存储的原始设定值**，失焦即写回 `buffer_stock` 表（青色样式 + 保存成功瞬时反馈）。另含一个独立前置修复。

**⚠️ 硬性设计前提（这条做错整个功能就废了）**：画面现在显示的 `r.bufferQty` 是**封顶后的施加值** `min(设定, bal)`（picking.js Step F），不是存储值。若让用户基于失真数字修正，设定会被 bal 波动来回拖着走。**Buffer 格必须显示 `currentBuffer` 里的原始设定值**，当日施加值只放 title 提示。

**已拍板的设计点**：写哪个字段按 mode 分流（normal→`normal_qty`，sembreak→`sembreak_qty`，short→禁编辑显示 `—`）；写回时带上另一字段原值以免清掉；**不联动今日 Restock**（buffer 编辑只影响明天起，今天的量用户直接改 Restock 格）；青色系视觉区分（改的是持久策略，误触后果不对称）。

### 步骤

**6a. 前置修复（独立缺陷，即使 6b 不做也该修）**：存档过一次后 edit mode 的 Forecast/Buffer 两栏显示 `—`——因为 `rows = saved.rows` 而 `collectEditRows()` 不收集这两个字段。锚点（edit 分支）：

```js
        const saved = await window.api.loadPickEdit(machine, date)
        if (saved && saved.rows) rows = saved.rows
```

改成：

```js
        const saved = await window.api.loadPickEdit(machine, date)
        if (saved && saved.rows) {
          // Saved rows don't carry forecastQty/bufferQty (collectEditRows
          // doesn't store them) — merge the live values back by lane no so
          // both columns keep displaying after a save.
          const liveByNo = {}
          pl.rows.concat(pl.hiddenRows || []).forEach(x => { liveByNo[String(x.no)] = x })
          rows = saved.rows.map(x => {
            const live = liveByNo[String(x.no)]
            return { ...x, forecastQty: live ? live.forecastQty : 0, bufferQty: live ? live.bufferQty : 0 }
          })
        }
```

**6b. Buffer 格改可编辑** — edit 分支行循环，锚点：

```js
            const bufCol = r.bufferQty ? `<span style="color:#0891b2">${r.bufferQty > 0 ? '+' : ''}${r.bufferQty}</span>` : '—'
```

在 edit 分支改成（view 分支的 bufCol **不动**）：

```js
            const laneNoStr = String(r.no)
            const bufSetting = (currentBuffer[machine] || {})[laneNoStr] || {}
            const bufStored = restockMode === 'sembreak' ? (bufSetting.sembreak_qty || 0) : (bufSetting.normal_qty || 0)
            // Show the STORED setting, not the bal-capped applied value —
            // editing a capped number would drag the setting around with bal.
            const bufTd = restockMode === 'short'
              ? `<td style="color:#c3c8d0">—</td>`
              : `<td class="buf-cell" contenteditable="true" spellcheck="false" data-lane="${laneNoStr}" title="Stored buffer setting — writes back to Buffer Stock on blur (applied today: ${r.bufferQty || 0})" onblur="onBufferCellEdit(this)">${bufStored || ''}</td>`
```

行模板里的 `<td>${bufCol}</td>` 换成 `${bufTd}`。（`bufCol` 变量在 edit 分支里如无其他引用可删。）

> Task 7 完成后这里的 `restockMode` 会换成 `window.api.modeOf(machine)`——Task 7 步骤里有写，这里先用全局变量。

**6c. 写回 handler**（放在 `collectEditRows` 附近）：

```js
  async function onBufferCellEdit(td) {
    if (!editMachine) return
    const laneNo = td.dataset.lane
    const pid = td.closest('tr')?.dataset.pid || ''
    const v = parseInt(td.textContent.trim(), 10) || 0
    const cur = (currentBuffer[editMachine] || {})[laneNo] || {}
    if (v === (restockMode === 'sembreak' ? (cur.sembreak_qty || 0) : (cur.normal_qty || 0))) return  // unchanged
    const row = {
      machine: editMachine, lane_no: laneNo, pid: pid || cur.pid || '',
      normal_qty:   restockMode === 'sembreak' ? (cur.normal_qty || 0) : v,
      sembreak_qty: restockMode === 'sembreak' ? v : (cur.sembreak_qty || 0)
    }
    const r = await window.api.setBufferQty([row])
    if (r && r.ok) {
      if (!currentBuffer[editMachine]) currentBuffer[editMachine] = {}
      currentBuffer[editMachine][laneNo] = { pid: row.pid, normal_qty: row.normal_qty, sembreak_qty: row.sembreak_qty }
      td.textContent = v || ''
      td.classList.add('buf-saved'); setTimeout(() => td.classList.remove('buf-saved'), 900)
    } else {
      td.classList.add('buf-fail'); setTimeout(() => td.classList.remove('buf-fail'), 1400)
    }
  }
```

payload 形状对齐 `buffer_stock.py cmd_set` 的 executemany named params：`{machine, lane_no, pid, normal_qty, sembreak_qty}`（与 `bufSaveAll` 相同）。

**6d. CSS**（放在 pick-tbl 相关样式附近）：

```css
td.buf-cell{color:#0891b2;background:#f0fdff;font-weight:600}
td.buf-cell.buf-saved{background:#bbf7d0}
td.buf-cell.buf-fail{background:#fecaca}
td.buf-cell{transition:background .35s}
```

**说明（不用改代码）**：表格上已有的 `input` autosave 监听会因 buffer 格编辑而触发一次 `collectEditRows → savePickEdit → syncQueueWithEdit`——无害（collectEditRows 不读 Buffer 列，存的内容不变）。

### 验证
1. `node src/picking.js` → OK
2. app 进 edit mode：Buffer 格青色、显示**设定值**（与 Buffer Stock 页面该机器 Normal 列一致，不是当日 `+n` 施加值）
3. 改一个值 → 失焦 → 绿色闪一下；切到 Buffer Stock 页面选同一机器 → Normal 列已更新
4. 工具栏切到 `−`（sembreak）→ 再进 edit mode → Buffer 格显示 sembreak_qty；编辑写回后 Buffer Stock 页 Sem Break 列更新、Normal 列**没被清掉**
5. 切到 `0`（short）→ Buffer 格显示 `—` 不可编辑
6. 存档过的机器（先随便编辑保存一次再重进）→ Forecast/Buffer 两栏**不再是 `—`**（6a 生效）
7. 编辑 Buffer 后今日 Restock 数字**不变**（不联动，设计如此）

**Commit**: `feat: editable Buffer column writes back to buffer_stock; restore live forecast/buffer on saved rows`

---

## Task 7（原 Phase 3-4）：restockMode 下沉为 per-machine（route plan 存储 + 学院级批量）

**前置**：Task 1–6 已完成（本 Task 会触碰 Task 1/6 改过的行）。

**目标**：模式从全局变量下沉到 `route_plan.json` 每台机器的 `mode` 字段（`normal`/`short`/`sembreak`，缺省 = normal）。Route Plan UI 加 Mode 列 + 「按过滤结果批量设 mode」（= 学院级操作：filter 输入 `KK` → 一键设整组）。工具栏 `+ / 0 / −` 保留，语义改为**批量设全部机器**（写 route plan，带 confirm）。sidebar 给非 normal 机器加小徽章提醒（上次事故就是切了 `−` 忘切回、无任何提醒）。**引擎零改动**——`semBreak` 参数本来就是逐调用传的，改的只是取值来源。

**副作用（预期内，好事）**：全局设置键 `restockMode` 从此不再被读取——settings.json 里卡死的 `"sembreak"` 自动失效，所有机器回到各自 mode（默认 normal）。commit message 里注明。

### 步骤

**7a. `src/preload.js`** — 锚点 `teamOf(machine)`，其后加同款方法：

```js
  modeOf(machine) {
    const key = picking.planKeyFor(routePlan.machines, machine)
    const m = key && routePlan.machines[key].mode
    return (m === 'short' || m === 'sembreak') ? m : 'normal'
  },
```

（`saveRoutePlan` 已同步更新内存 `routePlan.machines`，保存后 `modeOf` 即时生效，无需重启。）

**7b. `getBufferByLane`（index.html）** — 整个函数替换为：

```js
  function getBufferByLane(machine) {
    const mode = window.api.modeOf(machine)
    if (mode === 'short') return {}
    const machineBuf = currentBuffer[machine] || {}
    const result = {}
    for (const [laneNo, v] of Object.entries(machineBuf)) {
      result[laneNo] = mode === 'sembreak' ? (v.sembreak_qty || 0) : (v.normal_qty || 0)
    }
    return result
  }
```

**7c. 四个 `getPickList` 调用点** — 把 `restockMode !== 'normal'` 全部换成按机器取：

| 位置 | 锚点函数 | 替换为 |
|---|---|---|
| 详情页 | `renderPickDetail` | `window.api.modeOf(machine) !== 'normal'` |
| 入队 | `buildQueuePicks` | `window.api.modeOf(machine) !== 'normal'` |
| 批量打印(孤儿) | `doPrintAll` | `window.api.modeOf(m.machine) !== 'normal'` |
| 单机打印 | `doPrintCurrentMachine` | `window.api.modeOf(machine) !== 'normal'` |

forecast 参数（`currentForecast[machine] || {}`）**不用动**：引擎 Step E 里 `semBreak=true` 本来就把 forecast 归零，per-machine 的 semBreak 参数已把关。

**7d. `renderPicks` 的周六 forecast fetch** — 锚点 `if (restockMode === 'normal') {`：删掉这层 mode 判断（保留 `dow === 5` 判断），周六一律 fetch——非 normal 机器由 7c 的 semBreak 参数逐机屏蔽：

```js
      currentForecast = {}
      const selDate = new Date(document.getElementById('pick-date').value + 'T12:00:00')
      const dow = (selDate.getDay() + 6) % 7  // JS 0=Sun → remap to 0=Mon…6=Sun
      if (dow === 5) {  // Saturday → use Sunday's forecast
        const forecastRaw = await window.api.getForecastByWeekday(6)
        if (forecastRaw && forecastRaw.ok) currentForecast = forecastRaw.data
      }
```

（上方原有的注释块保留，补一句 `Per-machine mode gates application via the semBreak param.`）

**7e. 全局按钮 → 批量设全部** — `setRestockMode` 整个替换：

```js
  async function setRestockMode(mode) {
    const plan = window.api.getRoutePlan()
    const names = Object.keys(plan.machines || {})
    if (!names.length) return
    const label = { normal: 'Normal days (+)', short: 'Short break (0)', sembreak: 'Sem Break (−)' }[mode]
    if (!confirm(`Set ALL ${names.length} machines to ${label}?`)) return
    const machines = {}
    names.forEach(n => { machines[n] = { ...plan.machines[n], mode } })
    await window.api.saveRoutePlan(machines)
    updateRestockModeButtons()
    await renderPicks()
    if (currentDetailMachine && !isHistoryMode) renderPickDetail(currentDetailMachine)
  }
```

`updateRestockModeButtons` 替换（全体一致才高亮，混合状态三个都不亮）：

```js
  function updateRestockModeButtons() {
    const plan = window.api.getRoutePlan()
    const modes = new Set(Object.values(plan.machines || {}).map(v => (v.mode === 'short' || v.mode === 'sembreak') ? v.mode : 'normal'))
    const uniform = modes.size === 1 ? [...modes][0] : null
    ;['normal', 'short', 'sembreak'].forEach(m => {
      const b = document.getElementById('btn-mode-' + m)
      if (b) b.classList.toggle('in-queue', m === uniform)
    })
  }
```

**7f. 清除全局变量** — 删掉 `let restockMode = 'normal'` 声明；settings 加载块删掉 `if (s.restockMode) restockMode = s.restockMode` 和 `else if (s.semBreakMode) restockMode = 'sembreak'` 两行（`updateRestockModeButtons()` 调用保留）。Task 6 的两处 `restockMode`（`bufStored`/`bufTd` 处和 `onBufferCellEdit` 里）换成局部 `const mode = window.api.modeOf(machine)` / `window.api.modeOf(editMachine)`。最后全文 grep `restockMode`：**剩余命中只应是** `btn-mode-*` 元素 id、`setRestockMode` 函数名和 onclick 引用。有别的命中就是漏改。

**7g. Route Plan UI 加 Mode 列** — `rpLoad` 的 map 里加 `mode` 字段：

```js
    rpRows = Object.entries(plan.machines || {}).map(([name, v]) => ({
      origName: name, name, team: v.team || '',
      mode: (v.mode === 'short' || v.mode === 'sembreak') ? v.mode : 'normal',
      days: RP_DAYS.map(d => (v.scheduleDays || []).includes(d))
    }))
```

`rpColumns` 在 days 列之后、del 列之前插：

```js
    { key: 'mode', label: 'Mode', render: (r, i) => `<select data-i="${i}" data-f="mode" onchange="rpEdit(this)" style="padding:2px 4px;border:1px solid #d1d5db;border-radius:4px;font-size:11px;"><option value="normal"${r.mode==='normal'?' selected':''}>+ Normal</option><option value="short"${r.mode==='short'?' selected':''}>0 Short</option><option value="sembreak"${r.mode==='sembreak'?' selected':''}>− Sem Break</option></select>` },
```

（`rpEdit` 通用，`data-f="mode"` 直接工作。注意 `rpEdit` 里有 `.trim()`，对 select value 无害。）

`rpAddMachine` 的 push 对象加 `mode: 'normal'`。`rpSaveAll` 的 machines 赋值加 `mode: r.mode || 'normal'`：

```js
      machines[name] = { team: r.team.trim() || 'UNASSIGNED', scheduleDays: RP_DAYS.filter((d, di) => r.days[di]), mode: r.mode || 'normal' }
```

**7h. 学院级批量（按过滤结果设 mode）** — Route Plan 工具栏（锚点 `id="rp-btn-add"`），在 add 按钮**前**插：

```html
        <select id="rp-bulk-mode" style="padding:2px 6px;border:1px solid #d1d5db;border-radius:6px;font-size:11px;color:#374151;background:#fff;"><option value="normal">+ Normal</option><option value="short">0 Short</option><option value="sembreak">− Sem Break</option></select>
        <button class="pick-icon-btn" onclick="rpApplyModeToVisible()" title="Set mode on all visible (filtered) rows — then press Save"><span class="icon">done_all</span></button>
```

（若 add 按钮带 `margin-left:auto`，把 `margin-left:auto` 挪到 bulk select 上，保持整组靠右。）JS（放在 `rpSaveAll` 附近）：

```js
  function rpApplyModeToVisible() {
    const mode = document.getElementById('rp-bulk-mode').value
    const table = document.querySelector('#rp-wrap table.rp-tbl')
    if (!table) return
    let n = 0
    table.querySelectorAll('tbody tr').forEach(tr => {
      if (tr.style.display === 'none') return   // hidden by the filter box
      const sel = tr.querySelector('select[data-f="mode"]')
      if (sel) { sel.value = mode; rpEdit(sel); n++ }
    })
    const st = document.getElementById('rp-status')
    st.textContent = `Mode set on ${n} machine${n !== 1 ? 's' : ''} — press Save to apply`
    st.style.color = '#b45309'
  }
```

用法（写进按钮 title 即够）：filter 框输入学院前缀（如 `KK`）→ 选 mode → done_all → Save。

**7i. Sidebar 非 normal 徽章** — `renderPicks` 的 `displayList.forEach` 里（Task 3 改过的 `row.innerHTML` 处），week 徽章之后、pct 徽章之前加：

```js
        const mmode = window.api.modeOf(m.machine)
        const modeHtml = mmode === 'normal' ? '' : `<span class="pick-mode-badge ${mmode}" title="${mmode === 'short' ? 'Short break' : 'Sem Break'} mode">${mmode === 'short' ? '0' : '−'}</span>`
```

`row.innerHTML` 变成 `<span>${m.machine}</span>${wkHtml}${modeHtml}<span class="pick-badge ...`。CSS（放 `.pick-week-badge` 旁）：

```css
.pick-mode-badge{font-size:10px;font-weight:700;border-radius:4px;padding:0 5px;margin-right:5px;flex-shrink:0}
.pick-mode-badge.short{color:#b45309;background:#fef3c7}
.pick-mode-badge.sembreak{color:#b91c1c;background:#fee2e2}
```

### 验证
1. `node src/picking.js` → OK（引擎零改动的证明）
2. Route Plan 页：每行有 Mode 下拉；filter 输入 `KK` → bulk 选 `− Sem Break` → done_all → 状态栏显示 N 台 → Save → 重开页面值保留；`db/route_plan.json` 里对应机器多了 `"mode": "sembreak"`
3. sidebar：被设成 sembreak 的机器名旁出现红色 `−` 徽章，其他机器没有
4. 该机器详情：Buffer 列变负数倒扣；**其他 normal 机器的 Buffer 不受影响**（这正是本条目要解决的事故）
5. 日期选周六：normal 机器 Forecast 列有 `+n`，sembreak 机器 Forecast 全 `—`
6. 工具栏：混合模式时三个按钮都不高亮；点 `+` → confirm 弹窗 → 确认 → 全部机器变 normal、`+` 高亮、sidebar 徽章全消失
7. 全文 grep `restockMode` 只剩 id/函数名（见 7f）
8. edit mode Buffer 格（Task 6）在 sembreak 机器上显示/写回 `sembreak_qty`

**Commit**: `feat: per-machine restock mode stored in route plan; toolbar +/0/- becomes bulk-set-all (global setting retired)`

---

## 全部完成后

1. `HANDOFF.md`：Phase 3 七条全部标 ✅ + 各自 commit hash；顶部「未完成事项总览」的 Phase 3 段落删除或改为「全部完成」。
2. 提醒用户：全局 `restockMode` 设置已退役，之前卡在 `"sembreak"` 的问题随 Task 7 自动解决；今后放假切换在 Route Plan 页按学院 filter + 批量设置。
3. Phase 2 第 7 条（printAll 按钮断线）**不在本计划内**，仍待用户拍板 UI 形式。
