# Open Vending — Handoff Notes

## Completed

### ✅ Q2：Restock Qty + Forecast Qty
- `buildPickingList()` 加入 `forecastByPid` 参数，平日 forecast 开启，Sem Break 模式关闭
- 公式：`finalRestock = max(0, actualRestock + forecastQty + bufferQty)`
- sales_detail.db + sales_forecast.db 已建立，getForecastByWeekday IPC 已连接

### ✅ Q5：Fast Mover Highlight
- `oos7 >= 3` → picking list 该行高亮（CSS `.pick-fast`）
- 旧的 +1 逻辑已移除，改由 buffer stock 处理

### ✅ Q13：显示报告下载时间
- Picking list toolbar 显示 "Last updated: MM/DD/YYYY HH:MM"
- 读取报告文件的 mtime，IPC `get-report-mtime` 已实现

### ✅ Q6：Buffer Stock 功能（2026-07 本 session 完成）
- `src/buffer_stock.py` — SQLite 操作 + 建议计算
- 两张表：
  - `buffer_stock (machine, lane_no, pid, normal_qty, sembreak_qty)` — 用户手动设定
  - `buffer_suggestions (machine, pid, suggestion_normal_qty, suggestion_sembreak_qty)` — 系统计算，不被 Save 覆盖
- 建议计算公式：`sug_normal = max(0, round(max_daily − avg_daily))`，`sug_sembreak = min(0, round(min_daily − avg_daily))`
- IPC：`init-buffer-db` / `get-buffer-settings` / `set-buffer-qty` / `calc-buffer-suggestions` / `load-buffer-suggestions`
- UI：Buffer Stock 侧面板，与 Picking List 布局一致
  - 机器列表（左侧）按 team 分组，与 picking list sidebar 相同
  - 表格列：☐ Lane PID Product | Sug Normal | Sug Sem Break | Normal | Sem Break
  - `auto_fix_high` — 重新计算并写入 buffer_suggestions（不覆盖用户 Normal/Sem Break）
  - checkbox 勾选行 → Apply（`check_box` 图标）→ 同时填入 Normal + Sem Break → Save 持久化
  - 搜索栏（lane / product 名称）
- Picking list 集成：`getBufferByLane(machine)` 根据 `bufferMode`（normal/sembreak/none）返回 `{laneNo: qty}`，传入 `buildPickingList()` 第 7 参数
- 模式切换（normal / sembreak / none）在 picking list toolbar，不在 buffer stock 页面

### ✅ Universal Sort + Search（2026-07 本 session 完成）
- `makeSortable(table, {skipCols:[...]})` — 防重复初始化，支持跳过指定列
- `filterTable(table, query)` — 通用行过滤，所有列表复用
- 搜索栏统一用 `.pick-search-bar` 样式
- 覆盖范围：Main list ✅ Picking list ✅ Slow mover ✅ Buffer stock ✅

### ✅ 列表布局统一化 — 第一阶段（2026-07-02 本 session 完成）
起因：所有列表各自实现布局，冻结表头时卡片头和表头之间出现缝隙，滚动数据从缝隙中穿透显示。

**Bug 修复**（Picking List 详情表 + Buffer Stock lane 表）：
- 根因：卡片头 `.pick-hd` 和表头 `th` 是两个独立 `position:sticky` 的兄弟元素，靠 JS 一次性测量高度（`--pick-hd-h`）对齐偏移，测量值有误差就露缝
- 修复：卡片头+搜索栏移出滚动容器（静态区），只有 `<table>` 放进独立滚动子容器，`th` 用单层 `top:0` sticky —— 不再需要 JS 测量，架构上不可能露缝
- Buffer Stock 表头之前完全没冻结，现已一并修复

**共享基础设施**（`src/index.html`）：
- `.lv-shell` / `.lv-shell-hd` / `.lv-shell-scroll` — 通用 CSS class，静态卡片头+搜索栏 / 独立滚动表格体的标准结构。`#pick-detail`、`#buf-detail` 已采用
- `table.lv-tbl` — 通用表格基础样式，页面专属皮肤（`.pick-tbl` / `.buf-tbl`）在其后声明可覆盖
- `buildListTable(scrollEl, {columns, rows, rowClass, rowAttrs, emptyMessage, tableClass})` — 列定义驱动的表格渲染器，取代手写模板字符串。每列 `{key, label, render(row,i), sortable, headerStyle, cellStyle}`，自动生成 `data-col` 属性、接线 `makeSortable`
- `filterTable(table, query, {cols:[...]})` — 扩展为支持按 `data-col` 限定列的过滤（为未来分列进阶搜索打基础），不传 `cols` 时行为不变
- `renderSearchBar(inputId, placeholder, onInput, onClear)` — 统一搜索栏 markup 生成

**已迁移到新架构**：
- Buffer Stock lane 表 — 完整迁移到 `buildListTable`（含 checkbox、number input、suggestion 高亮列），过滤策略从"整表重建"改为共享的 DOM-hide `filterTable`
- Picking List 详情表 — 表头加 `data-col`，`filterPickTable` 改为调用共享 `filterTable`（未迁移到 `buildListTable`，因 contenteditable + swap 按钮的行内逻辑较复杂）
- Main table / Slow Mover — 表头加 `data-col`（为未来分列搜索铺路），未改动渲染逻辑

### ✅ Main table + Slow Mover 冻结表头 — 追加修复（2026-07-02 同 session，用户回报后发现）
第一阶段完成后误判 Main table / Slow Mover 没有冻结表头问题（只读代码没有实机验证），用户回报后在真实 app 中复现，发现两个跟 Picking List/Buffer Stock 完全不同根因的独立 bug：

- **Main table**：`thead tr { background:#c0392b }` 把背景色设在 `<tr>` 上，但 sticky 的是 `<th>`。sticky 元素被"钉住"后渲染在新位置，`tr` 的背景不会跟过去——`th` 自己是透明的，导致表头完全隐形（白字配透明底，滚动时整条红色表头直接消失，不是缝隙是完全看不见）。**修复**：背景色改设在 `thead th` 本身（[index.html:422-431](src/index.html:422)）
- **Slow Mover**：`#slow-body`（滚动容器）本身带 `padding:12px 16px`。CSS 规范里，滚动容器的 padding 区域属于可视 scrollport 的一部分——滚动内容会正常经过那 12px，但 sticky `th{top:0}` 只贴合 content 边缘，不会往上覆盖 padding 那 12px，留出一条没被表头盖住、但内容仍然可见的窄缝，滚动数据从里面露出来。**修复**：把 padding 从 `#slow-body` 移除，改成 `#slow-table-wrap` 的 `margin`（[index.html:231-232](src/index.html:231)）——滚动容器本身不再有 padding，sticky 不会有夹缝
- **额外发现**：点击排序（`makeSortable` 触发 `tbody.appendChild` 重排序）后，Chromium 有时不会重绘 sticky `<th>`（`getBoundingClientRect()` 位置正确、背景不透明，但画面上表头视觉消失，直到下次强制 repaint）。已在 `makeSortable` 排序完成后加一个 `display:none` → `offsetHeight` → `display:''` 的强制重绘（[index.html:1288-1292](src/index.html:1288)）
- 顺便把 Slow Mover 表头对比度调高（原本 `#f9fafb` 底 + `#6b7280` 字，太浅在压缩截图里几乎看不出来），改成 `#eef1f5` 底 + `#4b5563` 字 + 底部实线
- 三个表（Main / Picking List / Buffer Stock / Slow Mover）都已在真实 app 里用 DevTools 逐一验证：滚动+排序组合下表头零缝隙、不透明、不消失

### ✅ 四个列表表头风格统一 + 固定高度（2026-07-02 同 session，用户再次回报后修复）
用户回报：Main panel 表头颜色跟其他列表不一致；Slow Mover 表头在向下滚动时会稍微变短；四个列表（Main / Slow Mover / Buffer Stock / Picking List）风格必须统一。

- 之前每个列表的表头样式（背景色、字色、字号、padding）各自独立声明在 `thead th` / `table.pick-tbl th` / `.buf-tbl th` / `#slow-table-wrap th` 四处，互相不同步，改一处不会影响其他三处
- **统一方案**：只保留一份表头样式 `table.lv-tbl th`（[index.html:502-518](src/index.html:502)），删除其余三处的重复/冲突声明；四个 `<table>` 现在都带 `class="lv-tbl"`（`#data-table`、`.pick-tbl`×2、Slow Mover 表、`.buf-tbl` 经 `buildListTable` 自动带）。以后要改表头外观（颜色/字体/高度），只改这一处
- 统一后的样式：白底 `#fff` + 灰字 `#6b7280`，11px / 600 字重，不用大写变形
- **固定高度修复"滚动变短"**：改用 `height:34px; line-height:34px`（而非靠 padding 撑高度），行高不再依赖字体渲染细节，sticky 前后完全一致，不会出现肉眼可见的"变矮"
- Buffer Stock 的 "Sug Normal"/"Sug Sem Break" 两栏保留各自的绿/橙 `headerStyle` 颜色（表达"建议增/减"的语义），这是有意保留的例外，不算风格不统一

### ✅ Slow Mover 整体布局改用 Main table 样式（2026-07-02 同 session，用户要求"重做"）
之前表头颜色/高度统一了，但 Slow Mover 的**整体列表外观**仍跟 Main table 不同：`#slow-table-wrap` 带 `margin:12px 16px` + `border-radius:8px` + `box-shadow`，做成一张浮在灰色背景上的白色圆角卡片；搜索栏也是手写 inline style，不是共用的 `.pick-search-bar`。Main table（以及 Picking List、Buffer Stock）的列表都是"贴边、无卡片"的扁平风格。

- 移除 `#slow-table-wrap` 的 `margin` / `border-radius` / `box-shadow`，表格现在贴着搜索栏下方铺满，跟 `#table-wrap` 一样没有卡片感（[index.html:230-235](src/index.html:230)）
- 搜索栏改用 `class="pick-search-bar"`（跟 Main / Picking List / Buffer Stock 完全一样的 markup + 样式），删除原本手写的 inline style 版本
- 原本 `#slow-sub-toolbar` 把状态文字（"Showing all N products…"）和搜索框挤在同一行 flex 布局里，现在拆成两个独立的 flush 区块：`#slow-status`（状态行）+ `#slow-search-bar`（跟其他三个列表一模一样的搜索栏），JS 里两处 `#slow-sub-toolbar` 的 display 切换也改成分别控制这两个元素
- 已验证：滚动冻结、排序、搜索过滤在新布局下都正常

**未完成（下一步可继续）**：
- Picking List 详情表、Slow Mover 表尚未迁移到 `buildListTable`（列渲染逻辑复杂/成本较高，风险高于收益，暂缓）
- 机器侧栏（`#pick-machine-list` / `#buf-machine-list`）、Queue 弹窗列表仍是 div-based，未纳入统一
- 分列进阶搜索 UI（用户在特定列输入关键字）尚未实现，仅打好了 `data-col` + `filterTable({cols})` 的底层支持

---

## Known Issues

### KI-1：sales_forecast.db 离群值 — TEST / STANDBY 机器
- 现象：`TEST M4`（PID 368，avg_qty=247）、`STANDBY M5`（avg_qty=67）、`Flower Test` 等测试机器在 sales CSV 内有异常高销量数据
- 影响：这些机器不在 route plan，补货公式不会读取，**当前无实际影响**
- 待处理：build_sales_forecast.py 构建时过滤掉不在 route_plan.json 的机器，避免 DB 体积浪费
- 同时确认：`Hostel B M3`、`Hostel D M3` 在 route plan 但无 sales 记录，是新机器还是已停用？

---

## Pending Features（优先顺序）

### Q7：Picking List 替换产品标注
- 场景：review picking list 时，在原有产品旁边注明建议替换的产品，员工到机器时执行更换
- 在 Edit Mode 扩展：
  - 每个 lane 加 **Replacement 栏**，自由输入替代产品名称/PID
  - **Swap with Lane** 按钮：处理两个 lane 互换，系统自动在两个 lane 互相注明
  - 单向移动：自由输入 replacement 栏，两个 lane 分开手动处理
- Print out：显示原产品 + replacement，员工清楚知道哪个 lane 换什么
- **关联 Q3**：Q3 自动建议替代品 → Q7 Edit Mode 确认/修改

### ✅ Q1：Picking List Sidebar — 历史查询（2026-07-02 本 session 完成）
- 问题：Sidebar 之前无论选哪个日期都用当前报告重新计算"资格"，选历史日期看不到当天实际拣了什么
- `src/picking_history.py` 新增 `get-history-by-date <date>`（按 pick_date 分组返回每台机器的 lane/product/qty/OOS/status）、`get-history-dates`（列出有记录的日期）
- IPC：`get-history-by-date` / `get-history-dates`（main.js + preload.js）
- `renderPicks()` 判断所选日期早于今天 → 改走 `renderPickHistory()`，从 `picking_history` 表读取当天实际拣货记录，不再用当前报告重算资格；今天/未来日期仍走原实时逻辑
- `renderHistoryDetail()`：只读表格（Lane / Product / Picked Qty / Status），带"Historical view — read-only"标识，不显示 Edit/Queue 按钮
- 已用真实历史数据（2026-06-27、2026-07-01）验证 Python 层输出正确；用户已在实机测试确认正常

### Q3：Slow Movers → Picking List 替代品建议（新功能）
- 目标：picking list 补货时，若该产品属于 slow mover，自动建议同 tray 内销量更好的替代品
- 机器结构：每部机器 = Cold machine + Warm machine，各 6 层合并成 3 个 tray 组合（COLD 1/2/3、WARM 1/2/3）
- 数据来源：
  - Slow mover 排名：sales_detail.db（已建立）
  - 产品 tray 归属 + lane size：桌面 `product.csv`（PID / Product Name / TRAY / LANE SIZE）
  - 目前 lane 放什么产品：报告的 Product ID 栏
- 替代品匹配条件：同一 TRAY 组 + 相同 LANE SIZE
- Slow mover 定义：某产品月销量低于同 tray 内所有产品平均月销量的 X%（UI 上加输入框供用户调整）
- Per-machine 可行性已审查（2026-07-01）：改动点约 100–150 行，详见旧版 handoff
- **已发 cc**：`slow_movers_review.md`

### Q4：Queue List 导出功能
- 待加：Export as Excel 和 Export as PDF 两个按钮到 Queue modal（In-Transit Queue）
- Queue 数据来源：`currentPending` 对象
- 工作量：小

### Q11：单独打印单台机器
- 现状：只有 Print All
- 需求：picking list 里可单独打印某一台机器
- 工作量：小

### Q12：Print Out 版面待确认
- 目前栏位：No / Product / Replacement / Bal / Lane / Restock / Buffer Qty
- 新增 Replacement 和 Buffer Qty 后，A4 纸可能太挤
- 待 Q7 完成后打印样本，再决定是否调整栏位宽度或字体大小

### Q10：OOS 历史报告
- 数据来源：`picking_history` 数据库（已记录每次 picking 的 `out_of_stock` 状态）
- 内容：每台机器每个 lane 的 OOS 次数（30天/90天），附建议 buffer qty
- **注意：需累积至少一个月数据才有意义**
- 可导出 PDF 或 Excel

### ✅ Q8：Route Plan UI（2026-07-02 本 session 完成，cc 无意见）
- 现状：新增机器或修改排程之前需要手动编辑 `route_plan.json`，没有界面
- `route-plan-panel` 改为可编辑表格：Machine / Team / Schedule Days（7 个复选框，全不选 = 25% 规则）/ 删除
- 工具栏：➕ 新增机器、💾 保存；搜索框可按机器名/team 过滤
- IPC：`save-route-plan`（main.js 写入 `route_plan.json`）；`preload.js` 新增 `getRoutePlan()` / `saveRoutePlan()`，保存时同步更新内存中的 `routePlan.machines`，全 app 立即生效不用重启
- 重复机器名保存时自动合并（后者覆盖），状态栏提示
- 已用真实 `route_plan.json` 做写入/回滚验证（写入→校验→还原），Electron 实机启动无报错

- **✅ 路径迁移已完成**（同 session）：`route_plan.json` 从 `src/` 搬到 `db/`。`main.js` 的 `ROUTE_PLAN_PATH`、`preload.js` 的 `require()` 都已同步改路径。`db/` 目录整体被 `.gitignore` 排除，但因为这个文件搬移前已被 git 追踪，`git mv` 后仍保持追踪状态（git 的 ignore 规则只对未追踪文件生效）——已用 `git check-ignore` 验证确认。真机启动测试无报错。

### Q9：Buffer Stock 页面数据来源（已部分解决）
- 问题：lane 资料来自每天的报告；没有下载报告时，设定页面能否显示？
- 现状：页面要求先 load 报告文件（`lastFilePath`），无报告时显示 "Load a report first."
- 待 cc 确认是否可接受此行为，或需要独立存储 lane 清单

---

## Future Extensions

### FE-1：云端数据库（Google Drive 同步）
- **场景**：单写多读——写入机运行完整 app，多台读取机只查看数据
- **方案**：app 内部通过 `googleapis` npm 包直接与 Google Drive API 交互，不依赖任何外部客户端
- **写入机流程**：写入本地 SQLite → 后台静默上传 `.db` 文件到 Drive（用户无感知）
- **读取机流程**：App 启动 / 用户刷新 → 从 Drive 下载最新 `.db` → 本地正常读取
- **认证**：Service Account（JSON 密钥文件随 app 分发，无需用户登录）
- **费用**：Google Cloud Console + Drive API 对此规模完全免费，无需绑定信用卡
- **依赖**：`npm install googleapis`（仅一个包）
- **待决定**：读取机同步频率（启动时一次 vs 定时轮询）
