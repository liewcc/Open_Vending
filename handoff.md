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

### Q1：Picking List Sidebar — 历史查询
- 现状：Sidebar 只根据当前报告数据计算资格，无法还原历史
- 实现思路：picking_history 有 `pick_date` 字段，可查出历史上某天做过哪些机器
- 工作量：中等

### Q10：OOS 历史报告
- 数据来源：`picking_history` 数据库（已记录每次 picking 的 `out_of_stock` 状态）
- 内容：每台机器每个 lane 的 OOS 次数（30天/90天），附建议 buffer qty
- **注意：需累积至少一个月数据才有意义**
- 可导出 PDF 或 Excel

### Q8：Route Plan UI（待 cc advise）
- 现状：新增机器或修改排程需要手动编辑 `route_plan.json`，没有界面
- 待 cc 确认是否需要 UI，以及设计建议

### Q9：Buffer Stock 页面数据来源（已部分解决）
- 问题：lane 资料来自每天的报告；没有下载报告时，设定页面能否显示？
- 现状：页面要求先 load 报告文件（`lastFilePath`），无报告时显示 "Load a report first."
- 待 cc 确认是否可接受此行为，或需要独立存储 lane 清单
