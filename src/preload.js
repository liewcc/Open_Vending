const { contextBridge, ipcRenderer, shell } = require('electron')
const path = require('path')
const fs   = require('fs')
const xlsx = require(path.join(__dirname, '..', 'node_modules', 'xlsx'))
const picking = require(path.join(__dirname, 'picking.js'))

// Read (not require) the active account's route plan: require() caches JSON, so
// after an account switch reloads the window a cached require would hand back
// the previous account's plan. Reading keeps every exposed API synchronous.
const DATA_DIR = ipcRenderer.sendSync('get-data-dir')
// A missing handler is a bug, not a data condition — fail loudly rather than
// silently degrade to an empty plan (which just looks like "no machines today").
if (!DATA_DIR) throw new Error('get-data-dir returned nothing — main process handler missing')
let routePlan
try {
  routePlan = JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'route_plan.json'), 'utf8'))
} catch {
  routePlan = { machines: {} }   // new account — no plan yet
}

function parseRows(filePath) {
  const wb = xlsx.readFile(filePath)
  let allRows = null
  for (const name of wb.SheetNames) {
    const rows = xlsx.utils.sheet_to_json(wb.Sheets[name], { header: 1, defval: '' })
    if (!rows.length) continue
    if (allRows === null) {
      allRows = [['Machine', ...rows[0]], ...rows.slice(1).map(r => [name, ...r])]
    } else {
      allRows = allRows.concat(rows.slice(1).map(r => [name, ...r]))
    }
  }
  return allRows || []
}

contextBridge.exposeInMainWorld('api', {
  onLog:              cb => ipcRenderer.on('py-out',            (_, m)  => cb(m)),
  onDone:             cb => ipcRenderer.on('py-done',           (_, ok) => cb(ok)),
  onFileReady:        cb => ipcRenderer.on('file-ready',        (_, p)  => cb(p)),
  onNeedsCredentials: cb => ipcRenderer.on('needs-credentials', ()      => cb()),
  startDownload:      ()           => ipcRenderer.send('start-download'),
  saveCredentials:    (u, p)       => ipcRenderer.send('save-credentials', { username: u, password: p }),
  doUpdate:           ()           => ipcRenderer.send('do-update'),
  quitApp:            ()           => ipcRenderer.send('quit-app'),
  onUpdateStatus:     cb => ipcRenderer.on('update-status',   (_, d) => cb(d)),
  onUpdateProgress:   cb => ipcRenderer.on('update-progress', (_, s) => cb(s)),
  openExternal:       url          => shell.openExternal(url),
  getSettings:        ()           => ipcRenderer.invoke('get-settings'),
  setSetting:         (key, val)   => ipcRenderer.send('set-setting', { key, val }),
  onDownloadStarted:  cb => ipcRenderer.on('download-started',  ()         => cb()),
  onScanStatus:       cb => ipcRenderer.on('scan-status',       (_, s)     => cb(s)),
  getScanStatus:      ()                                                   => ipcRenderer.invoke('get-scan-status'),
  launchBrowser:        ()               => ipcRenderer.send('launch-browser'),
  closeBrowser:         ()               => ipcRenderer.send('close-browser'),
  onBrowserState:       cb => ipcRenderer.on('browser-state', (_, state) => cb(state)),
  getRestockHistory:    (machine, lane)  => ipcRenderer.invoke('get-restock-history', { machine, lane }),
  initPickingDb:        ()               => ipcRenderer.invoke('init-picking-db'),
  autoClearPicks:       ()               => ipcRenderer.invoke('auto-clear-picks'),
  getPendingInTransit:  ()               => ipcRenderer.invoke('get-pending-in-transit'),
  getPendingDetail:     ()               => ipcRenderer.invoke('get-pending-detail'),
  getOosCounts:         ()               => ipcRenderer.invoke('get-oos-counts'),
  savePicks:            (picks)          => ipcRenderer.invoke('save-picks', picks),
  markDone:             (machines)       => ipcRenderer.invoke('mark-done', machines),
  getHistoryDates:      ()               => ipcRenderer.invoke('get-history-dates'),
  getHistoryByDate:     (date)           => ipcRenderer.invoke('get-history-by-date', date),
  getWeekSummary:       (from, to)       => ipcRenderer.invoke('get-week-summary', { from, to }),

  parseExcel(filePath) {
    return parseRows(filePath)
  },
  getTodayPicks(filePath, dateISO, pendingByMachine, bufferByMachine) {
    const rows = parseRows(filePath)
    return picking.machinesToPickToday(rows, routePlan, new Date(dateISO), pendingByMachine || {}, bufferByMachine || {})
  },
  getPickList(filePath, machine, pendingByLane, oosByLane, forecastByPid, semBreak, bufferByLane) {
    const rows = parseRows(filePath)
    const splitForecast = picking.splitForecastAcrossLanes(rows, machine, forecastByPid || {})
    return picking.buildPickingList(rows, machine, pendingByLane || {}, oosByLane || {}, splitForecast, semBreak || false, bufferByLane || {})
  },
  teamOf(machine) {
    const key = picking.planKeyFor(routePlan.machines, machine)
    return (key && routePlan.machines[key].team) || null
  },
  modeOf(machine) {
    const key = picking.planKeyFor(routePlan.machines, machine)
    const m = key && routePlan.machines[key].mode
    return (m === 'short' || m === 'sembreak') ? m : 'normal'
  },
  getRoutePlan() {
    return routePlan
  },
  saveRoutePlan(machines) {
    routePlan.machines = machines
    return ipcRenderer.invoke('save-route-plan', routePlan)
  },
  getAllMachines(filePath, pendingByMachine, bufferByMachine) {
    const rows = parseRows(filePath)
    if (!pendingByMachine) pendingByMachine = {}
    if (!bufferByMachine) bufferByMachine = {}
    const machinesInPlan = (routePlan && routePlan.machines) ? routePlan.machines : {}

    // Group report rows by machine name
    const groups = {}
    for (let i = 1; i < rows.length; i++) {
      const row = rows[i]
      if (!row || !row[0]) continue
      if (!groups[row[0]]) groups[row[0]] = []
      groups[row[0]].push(row)
    }

    const results = []
    for (const machineName in machinesInPlan) {
      const machinePlan = machinesInPlan[machineName]
      // Excel truncates sheet names to 31 chars; fall back to the prefix so
      // long plan names still find their report rows. Report-side name is the
      // machine identity everywhere else (detail view, pending, history).
      const reportName = groups[machineName]
        ? machineName
        : (machineName.length > 31 && groups[machineName.slice(0, 31)] ? machineName.slice(0, 31) : machineName)
      const machRows = groups[reportName] || []
      // Same Step-F per-lane semantics as the sidebar pick list (buffer applied,
      // in-transit deducted) so both % views agree.
      const { laneSum, restockSum: adjustedRestockSum, pct } =
        picking.machineRestockPct(machRows, pendingByMachine[reportName], bufferByMachine[reportName])
      results.push({ machine: reportName, team: machinePlan.team || 'UNASSIGNED', pct, adjustedRestockSum, laneSum })
    }

    results.sort((a, b) => {
      const p = t => t === '5530' ? 1 : t === '1126' ? 2 : t === 'UNASSIGNED' ? 3 : 4
      const pa = p(a.team), pb = p(b.team)
      if (pa !== pb) return pa - pb
      if (pa === 4 && a.team !== b.team) return a.team.localeCompare(b.team)
      return a.machine.localeCompare(b.machine)
    })
    return results
  },
  printAll: (data, pages) => ipcRenderer.invoke('print-all-picking-lists', { data, pages }),
  openCsvDialog:     ()                            => ipcRenderer.invoke('open-csv-dialog'),
  analyzeSlowMovers: (productCsv, salesCsv, topN) => ipcRenderer.invoke('analyze-slow-movers', { productCsv, salesCsv, topN }),
  printSlowMovers:   (data)                        => ipcRenderer.invoke('print-slow-movers', data),
  openDbDialog:      ()                            => ipcRenderer.invoke('open-db-dialog'),
  openSaveDbDialog:  ()                            => ipcRenderer.invoke('open-save-db-dialog'),
  generateSlowDb:    (productCsv, salesCsv, dbPath) => ipcRenderer.invoke('generate-slow-db', { productCsv, salesCsv, dbPath }),
  analyzeSlowDb:     (dbPath, topN)                => ipcRenderer.invoke('analyze-slow-db', { dbPath, topN }),
  savePickEdit:       (machine, date, rows) => ipcRenderer.invoke('save-pick-edit', { machine, date, rows }),
  loadPickEdit:       (machine, date)       => ipcRenderer.invoke('load-pick-edit',  { machine, date }),
  getReportMtime:     ()                    => ipcRenderer.invoke('get-report-mtime'),
  openSalesCsvDialog:  ()        => ipcRenderer.invoke('open-sales-csv-dialog'),
  buildSalesDetailDb:  (csvPath) => ipcRenderer.invoke('build-sales-detail-db', { csvPath }),
  getSalesDetailMeta:  ()        => ipcRenderer.invoke('get-sales-detail-meta'),
  buildSalesForecastDb:  ()           => ipcRenderer.invoke('build-sales-forecast-db'),
  getSalesForecastMeta:  ()           => ipcRenderer.invoke('get-sales-forecast-meta'),
  getForecastByWeekday:  (weekday)    => ipcRenderer.invoke('get-forecast-by-weekday', { weekday }),
  initBufferDb:           ()     => ipcRenderer.invoke('init-buffer-db'),
  getBufferSettings:      ()     => ipcRenderer.invoke('get-buffer-settings'),
  setBufferQty:           (rows) => ipcRenderer.invoke('set-buffer-qty', rows),
  calcBufferSuggestions:  ()     => ipcRenderer.invoke('calc-buffer-suggestions'),
  loadBufferSuggestions:  ()     => ipcRenderer.invoke('load-buffer-suggestions'),
  getLaneTypes:           ()     => ipcRenderer.invoke('get-lane-types'),
  getReplacementData:     (machine) => ipcRenderer.invoke('get-replacement-data', machine),
  getMachineSales:        (machine, days) => ipcRenderer.invoke('get-machine-sales', { machine, days }),
  getMachineLanes(filePath, machine) {
    return picking.listMachineLanes(parseRows(filePath), machine)
  },
  suggestReplacements(pickRows, machineLanes, catalog, machineSales, globalSales, thresholdPct, topN) {
    return picking.suggestReplacements(pickRows, machineLanes, catalog, machineSales, globalSales, thresholdPct, topN)
  },
  exportQueueExcel: (rows) => ipcRenderer.invoke('export-queue-excel', rows),
  exportBufferStock: (rows, machine) => ipcRenderer.invoke('export-buffer-excel', { rows, machine }),
  exportQueuePdf:   (rows, pages, date) => ipcRenderer.invoke('export-queue-pdf', { rows, pages, date }),
  analyzeSlowMachine: (machine) => ipcRenderer.invoke('analyze-slow-machine', machine),
})

