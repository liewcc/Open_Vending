const { app, BrowserWindow, ipcMain, safeStorage, Tray, Menu, globalShortcut, Notification, dialog } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const fs   = require('fs')
const os   = require('os')

const ROOT          = path.join(__dirname, '..')
const CRED_FILE     = path.join(app.getPath('userData'), 'credentials.enc')
const SETTINGS_FILE = path.join(app.getPath('userData'), 'settings.json')
const LAST_REPORT   = path.join(ROOT, 'db', 'last_report.xlsx')
const LAST_DIFFS    = path.join(ROOT, 'db', 'last_diffs.json')
const DEFAULT_SETTINGS = { menuBar: false, showConsole: false, closeTray: false, notifyChanges: false, autoDownload: false, autoDownloadInterval: 30, headedBrowser: false, landingUrl: 'https://vendingportal.azurewebsites.net/SuperAdmin/SPLogin.aspx' }
const F9_TRIGGER    = path.join(ROOT, 'db', '.f9_trigger')
const BROWSER_STOP  = path.join(ROOT, 'db', '.browser_stop')
const ICON_PNG = path.join(ROOT, 'asset', 'image', 'icon_nobg.png')
let win
let tray = null
let quitting = false
let cachedCreds = null
let settings = DEFAULT_SETTINGS
let isDownloading = false
let autoDownloadTimer = null
let lastDiffs = []
let loginProc = null

function loadSettings() {
  try { return { ...DEFAULT_SETTINGS, ...JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8')) } }
  catch { return { ...DEFAULT_SETTINGS } }
}

function saveSettings() {
  fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings))
}

const LOCAL_VERSION  = require('../package.json').version
const REPO_PKG_URL   = 'https://raw.githubusercontent.com/liewcc/Open_Vending/main/package.json'
const REPO_ZIP_URL   = 'https://github.com/liewcc/Open_Vending/archive/refs/heads/main.zip'
const UPDATE_EXCLUDE = ['node_modules', 'python', 'browsers', 'node', 'db', '.claude', '.git']

// ── Update helpers ────────────────────────────────────────────────────────────

function semverGt(a, b) {
  const pa = a.split('.').map(Number)
  const pb = b.split('.').map(Number)
  for (let i = 0; i < 3; i++) {
    if ((pa[i] || 0) > (pb[i] || 0)) return true
    if ((pa[i] || 0) < (pb[i] || 0)) return false
  }
  return false
}

async function checkForUpdate() {
  try {
    const res  = await fetch(REPO_PKG_URL)
    const pkg  = await res.json()
    return { status: semverGt(pkg.version, LOCAL_VERSION) ? 'available' : 'up-to-date', local: LOCAL_VERSION, remote: pkg.version }
  } catch {
    return { status: 'error', local: LOCAL_VERSION, remote: null }
  }
}

async function doUpdate() {
  try {
    win.webContents.send('update-progress', 'downloading')

    const tmpDir  = path.join(os.tmpdir(), `ov-update-${Date.now()}`)
    const zipPath = path.join(tmpDir, 'update.zip')
    fs.mkdirSync(tmpDir, { recursive: true })

    const res = await fetch(REPO_ZIP_URL)
    const buf = await res.arrayBuffer()
    fs.writeFileSync(zipPath, Buffer.from(buf))

    // Updater script: waits for this process to exit, extracts, copies, relaunches
    const updaterPs1 = path.join(tmpDir, 'updater.ps1')
    const excludeList = UPDATE_EXCLUDE.map(e => `'${e}'`).join(',')

    // Escape single quotes in paths for PowerShell single-quoted strings
    const escZip = zipPath.replace(/'/g, "''")
    const escTmp = tmpDir.replace(/'/g, "''")
    const escApp = ROOT.replace(/'/g, "''")
    const escVbs = path.join(ROOT, 'run.vbs').replace(/'/g, "''")

    fs.writeFileSync(updaterPs1, `
$pid_  = ${process.pid}
$zip   = '${escZip}'
$tmp   = '${escTmp}'
$app   = '${escApp}'
$vbs   = '${escVbs}'

while (Get-Process -Id $pid_ -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 300 }

Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp 'extracted') -Force
$src = (Get-ChildItem -Path (Join-Path $tmp 'extracted') | Select-Object -First 1).FullName

if (-not $src -or -not (Test-Path $src)) {
  exit
}

$excl = @(${excludeList})
Get-ChildItem -Path $src | Where-Object { $_.Name -notin $excl } | ForEach-Object {
  Copy-Item $_.FullName (Join-Path $app $_.Name) -Recurse -Force
}
Start-Process 'wscript.exe' -ArgumentList ('"{0}"' -f $vbs)
`)

    spawn('cmd.exe',
      ['/c', 'start', '""', '/min', 'powershell.exe',
       '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
       '-File', updaterPs1],
      { detached: true, stdio: 'ignore' }
    ).unref()
    setTimeout(() => app.quit(), 500)
  } catch (err) {
    win.webContents.send('update-progress', 'error')
  }
}

// ── Credential helpers ────────────────────────────────────────────────────────

function loadCredentials() {
  if (!fs.existsSync(CRED_FILE)) return null
  try {
    const { u, p } = JSON.parse(fs.readFileSync(CRED_FILE, 'utf8'))
    return {
      username: safeStorage.decryptString(Buffer.from(u, 'base64')),
      password: safeStorage.decryptString(Buffer.from(p, 'base64'))
    }
  } catch { return null }
}

function saveCredentials(username, password) {
  const data = {
    u: safeStorage.encryptString(username).toString('base64'),
    p: safeStorage.encryptString(password).toString('base64')
  }
  fs.writeFileSync(CRED_FILE, JSON.stringify(data))
}

// ── Window ────────────────────────────────────────────────────────────────────

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    icon: ICON_PNG,
    titleBarStyle: 'hidden',
    titleBarOverlay: {
      color: '#1e2235',
      symbolColor: '#cdd6f4',
      height: 38
    },
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    },
    backgroundColor: '#f0f2f5'
  })
  win.loadFile(path.join(__dirname, 'index.html'))

  win.on('close', e => {
    if (!quitting && settings.closeTray) {
      e.preventDefault()
      win.hide()
    }
  })
}

// ── F9 DOM capture shortcut ───────────────────────────────────────────────────

function registerF9() {
  if (globalShortcut.isRegistered('F9')) return
  globalShortcut.register('F9', () => {
    try { fs.writeFileSync(F9_TRIGGER, '') } catch { /* ignore */ }
  })
}

function unregisterF9() {
  globalShortcut.unregister('F9')
}

// ── Auto-download timer ───────────────────────────────────────────────────────

function setupAutoDownload() {
  if (autoDownloadTimer) { clearInterval(autoDownloadTimer); autoDownloadTimer = null }
  if (!settings.autoDownload || !(settings.autoDownloadInterval > 0)) return
  autoDownloadTimer = setInterval(() => {
    if (cachedCreds && !isDownloading) runDownload(cachedCreds)
  }, settings.autoDownloadInterval * 60 * 1000)
}

// ── Download ──────────────────────────────────────────────────────────────────

function runDownload(creds) {
  if (isDownloading) return
  isDownloading = true
  win.webContents.send('download-started')
  const pythonExe = path.join(ROOT, 'python', 'python.exe')
  const script    = path.join(ROOT, 'open_vending.py')

  const args = settings.headedBrowser ? [script] : [script, '--headless']
  const proc = spawn(pythonExe, args, {
    windowsHide: !settings.showConsole,
    env: {
      ...process.env,
      PLAYWRIGHT_BROWSERS_PATH: path.join(ROOT, 'browsers'),
      PYTHONNOUSERSITE: '1',
      PYTHONPATH: '',
      OV_USERNAME: creds.username,
      OV_PASSWORD: creds.password,
      OV_LANDING_URL: settings.landingUrl || ''
    }
  })

  proc.stdout.on('data', data => {
    data.toString().trim().split('\n').forEach(line => {
      line = line.trim()
      if (!line) return
      if (line.startsWith('DIFFS: ')) {
        try { lastDiffs = JSON.parse(line.slice(7)) } catch { lastDiffs = [] }
        try { fs.writeFileSync(LAST_DIFFS, JSON.stringify(lastDiffs)) } catch { }
        if (settings.notifyChanges && lastDiffs.length > 0) {
          const notif = new Notification({
            title: 'Open Vending — Restock Changes',
            body: `${lastDiffs.length} restock change${lastDiffs.length > 1 ? 's' : ''} detected`,
            icon: ICON_PNG
          })
          notif.on('click', () => { win.show(); win.focus() })
          notif.show()
        }
        return
      }
      win.webContents.send('py-out', line)
      const m = line.match(/^FILE: (.+)$/)
      if (m) win.webContents.send('file-ready', m[1].trim())
    })
  })

  proc.stderr.on('data', data => {
    win.webContents.send('py-out', 'ERROR: ' + data.toString().trim())
  })

  proc.on('error', err => {
    isDownloading = false
    win.webContents.send('py-out', 'ERROR: ' + err.message)
    win.webContents.send('py-done', false)
  })

  proc.on('close', code => {
    isDownloading = false
    win.webContents.send('py-done', code === 0)
  })
}

// ── Login-only browser ────────────────────────────────────────────────────────

function launchBrowser(creds) {
  if (loginProc) return
  const pythonExe = path.join(ROOT, 'python', 'python.exe')
  const script    = path.join(ROOT, 'open_vending.py')
  loginProc = spawn(pythonExe, [script, '--login-only'], {
    windowsHide: false,
    env: {
      ...process.env,
      PLAYWRIGHT_BROWSERS_PATH: path.join(ROOT, 'browsers'),
      PYTHONNOUSERSITE: '1',
      PYTHONPATH: '',
      OV_USERNAME: creds.username,
      OV_PASSWORD: creds.password,
      OV_LANDING_URL: settings.landingUrl || ''
    }
  })
  win.webContents.send('browser-state', 'running')
  loginProc.stdout.on('data', data => {
    data.toString().trim().split('\n').forEach(line => {
      line = line.trim(); if (line) win.webContents.send('py-out', line)
    })
  })
  loginProc.stderr.on('data', data => {
    win.webContents.send('py-out', 'ERROR: ' + data.toString().trim())
  })
  loginProc.on('close', () => {
    loginProc = null
    win.webContents.send('browser-state', 'idle')
  })
}

function closeBrowser() {
  if (!loginProc) return
  try { fs.writeFileSync(BROWSER_STOP, '') } catch { /* ignore */ }
}

// ── App lifecycle ─────────────────────────────────────────────────────────────

if (!app.requestSingleInstanceLock()) app.quit()

app.on('second-instance', () => {
  if (win) { if (win.isMinimized()) win.restore(); win.focus() }
})

app.whenReady().then(() => {
  settings = loadSettings()
  createWindow()
  spawnPy([PICKING_HISTORY, 'init'], null)

  tray = new Tray(ICON_PNG)
  tray.setToolTip(`Open Vending v${LOCAL_VERSION}`)
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Show', click: () => { win.show(); win.focus() } },
    { type: 'separator' },
    { label: 'Quit', click: () => app.quit() }
  ]))
  tray.on('click', () => { win.show(); win.focus() })

  win.setMenuBarVisibility(settings.menuBar)
  win.setAutoHideMenuBar(!settings.menuBar)
  if (settings.headedBrowser) registerF9()
  win.webContents.once('did-finish-load', () => {
    cachedCreds = loadCredentials()

    // restore last known state before new scan starts
    if (fs.existsSync(LAST_REPORT)) {
      win.webContents.send('file-ready', LAST_REPORT)
    }
    if (fs.existsSync(LAST_DIFFS)) {
      try {
        lastDiffs = JSON.parse(fs.readFileSync(LAST_DIFFS, 'utf8'))
      } catch { }
    }

    if (cachedCreds) {
      runDownload(cachedCreds)
    } else {
      win.webContents.send('needs-credentials')
    }

    checkForUpdate().then(result => win.webContents.send('update-status', result))
    setupAutoDownload()
  })
})

app.on('before-quit', () => { quitting = true })
app.on('will-quit', () => { globalShortcut.unregisterAll() })

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

function spawnPy(args, stdinData) {
  return new Promise(resolve => {
    const pythonExe = path.join(ROOT, 'python', 'python.exe')
    const proc = spawn(pythonExe, args, {
      windowsHide: true,
      env: { ...process.env, PYTHONNOUSERSITE: '1', PYTHONPATH: '' }
    })
    let out = ''
    if (stdinData !== null && stdinData !== undefined) {
      proc.stdin.write(JSON.stringify(stdinData))
      proc.stdin.end()
    }
    proc.stdout.on('data', d => out += d)
    proc.on('close', () => { try { resolve(JSON.parse(out.trim())) } catch { resolve(null) } })
    proc.on('error', () => resolve(null))
  })
}

// ── IPC ───────────────────────────────────────────────────────────────────────

ipcMain.on('save-credentials', (_, { username, password }) => {
  saveCredentials(username, password)
  cachedCreds = { username, password }
  runDownload(cachedCreds)
})

ipcMain.on('start-download', () => {
  if (cachedCreds) runDownload(cachedCreds)
})

ipcMain.on('do-update', () => doUpdate())
ipcMain.on('quit-app',  () => app.quit())

ipcMain.handle('get-settings', () => settings)

ipcMain.on('set-setting', (_, { key, val }) => {
  settings[key] = val
  saveSettings()
  if (key === 'menuBar') {
    win.setMenuBarVisibility(val)
    win.setAutoHideMenuBar(!val)
  }
  if (key === 'autoDownload' || key === 'autoDownloadInterval') {
    setupAutoDownload()
  }
  if (key === 'headedBrowser') {
    val ? registerF9() : unregisterF9()
  }
})

ipcMain.on('launch-browser', () => { if (cachedCreds) launchBrowser(cachedCreds) })
ipcMain.on('close-browser',  () => closeBrowser())

const QUERY_HISTORY   = path.join(__dirname, 'query_history.py')
const PICKING_HISTORY = path.join(__dirname, 'picking_history.py')
const SLOW_MOVERS     = path.join(__dirname, 'slow_movers.py')
ipcMain.handle('get-restock-history', (_, { machine, lane }) =>
  new Promise(resolve => {
    const pythonExe = path.join(ROOT, 'python', 'python.exe')
    const proc = spawn(pythonExe, [QUERY_HISTORY, machine, String(lane)], {
      windowsHide: true,
      env: { ...process.env, PYTHONNOUSERSITE: '1', PYTHONPATH: '' }
    })
    let out = ''
    proc.stdout.on('data', d => out += d)
    proc.on('close', () => { try { resolve(JSON.parse(out.trim())) } catch { resolve([]) } })
    proc.on('error', () => resolve([]))
  })
)

ipcMain.handle('init-picking-db',        ()         => spawnPy([PICKING_HISTORY, 'init'],         null))
ipcMain.handle('auto-clear-picks',       ()         => spawnPy([PICKING_HISTORY, 'auto-clear'],   null))
ipcMain.handle('get-pending-in-transit', ()         => spawnPy([PICKING_HISTORY, 'get-pending'],  null))
ipcMain.handle('get-oos-counts',         ()         => spawnPy([PICKING_HISTORY, 'get-oos-counts'], null))
ipcMain.handle('save-picks',             (_, picks) => spawnPy([PICKING_HISTORY, 'save-picks'],   picks))
ipcMain.handle('mark-done',              (_, machines) => spawnPy([PICKING_HISTORY, 'mark-done'], machines))

ipcMain.handle('print-all-picking-lists', async (_, data) => {
  function esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
  }
  const pages = data.map(m => {
    const rows = m.rows.map(r => {
      const hasReplacement = false // wire replacement field here later
      if (hasReplacement) {
        return `<tr class="rep"><td>${esc(r.no)}</td><td class="orig">${esc(r.product)}</td><td class="col1">${esc(r.productId)}</td><td>${esc(r.bal)}</td><td>${esc(r.lane)}</td><td>${esc(r.restock)}</td></tr>`
      }
      return `<tr><td>${esc(r.no)}</td><td>${esc(r.product)}</td><td></td><td>${esc(r.bal)}</td><td>${esc(r.lane)}</td><td>${esc(r.restock)}</td></tr>`
    }).join('')
    return `<div class="page"><div class="hdr"><span>${esc(m.date)}</span><span>${esc(m.machine)} ${esc(m.team)}</span></div><table><thead><tr><th>No.</th><th>Product Name</th><th>Column1</th><th>Bal Qty</th><th>Lane Size</th><th>Restock</th></tr></thead><tbody>${rows}</tbody></table></div>`
  }).join('')

  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:Arial,sans-serif;font-size:11px}@page{size:A4 portrait;margin:12mm}.page{page-break-after:always;break-after:page}.page:last-child{page-break-after:avoid;break-after:avoid}.hdr{display:flex;justify-content:space-between;font-size:13px;font-weight:bold;margin-bottom:8px;padding-bottom:4px;border-bottom:1.5px solid #000}table{width:100%;border-collapse:collapse;font-size:11px}th,td{border:0.5px solid #555;padding:4px 6px;text-align:left}th{background:#f0f0f0;font-weight:600}th:nth-child(1){width:5%}th:nth-child(2){width:38%}th:nth-child(3){width:22%}th:nth-child(4),th:nth-child(5),th:nth-child(6){width:10%;text-align:center}td:nth-child(4),td:nth-child(5),td:nth-child(6){text-align:center}tr.rep td.orig{text-decoration:line-through;color:#777}tr.rep td.col1{background-color:#ffffa0!important;font-weight:500}</style></head><body>${pages}</body></html>`

  const defaultPath = settings.lastPdfPath || path.join(os.homedir(), 'Desktop', 'picking-list.pdf')
  const { canceled, filePath } = await dialog.showSaveDialog({ defaultPath, filters: [{ name: 'PDF', extensions: ['pdf'] }] })
  if (canceled || !filePath) return { ok: false }

  const printWin = new BrowserWindow({ show: false, webPreferences: { contextIsolation: true } })
  printWin.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html))
  await new Promise(resolve => printWin.webContents.once('did-finish-load', resolve))
  const pdfBuffer = await printWin.webContents.printToPDF({ printBackground: true })
  printWin.destroy()

  fs.writeFileSync(filePath, pdfBuffer)
  settings.lastPdfPath = filePath
  saveSettings()
  return { ok: true, filePath }
})

ipcMain.handle('open-csv-dialog', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    filters: [{ name: 'CSV', extensions: ['csv'] }],
    properties: ['openFile']
  })
  return canceled ? null : filePaths[0]
})

ipcMain.handle('open-db-dialog', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    filters: [{ name: 'SQLite DB', extensions: ['db', '*'] }],
    properties: ['openFile']
  })
  return canceled ? null : filePaths[0]
})

ipcMain.handle('open-save-db-dialog', async () => {
  const { canceled, filePath } = await dialog.showSaveDialog({
    filters: [{ name: 'SQLite DB', extensions: ['db'] }],
    defaultPath: path.join(os.homedir(), 'Desktop', 'slow-movers.db')
  })
  return canceled ? null : filePath
})

ipcMain.handle('generate-slow-db', (_, { productCsv, salesCsv, dbPath }) =>
  spawnPy([SLOW_MOVERS, 'build', productCsv, salesCsv, dbPath], null)
)

ipcMain.handle('analyze-slow-db', (_, { dbPath, topN }) =>
  spawnPy([SLOW_MOVERS, 'analyze', dbPath, String(topN || 20)], null)
)

ipcMain.handle('analyze-slow-movers', (_, { productCsv, salesCsv, topN }) =>
  spawnPy([SLOW_MOVERS, productCsv, salesCsv, String(topN || 20)], null)
)

ipcMain.handle('print-slow-movers', async (_, { rows, dateRange }) => {
  function esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
  }
  const tableRows = rows.map((r, i) =>
    `<tr><td>${i+1}</td><td>${esc(r.name)}</td><td>${r.total}</td><td>${esc(r.last_sale) || '—'}</td><td>${r.days != null ? r.days + 'd' : 'Never'}</td></tr>`
  ).join('')
  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:Arial,sans-serif;font-size:11px}
    @page{size:A4 portrait;margin:15mm}
    h2{font-size:14px;margin-bottom:3px}
    .sub{font-size:10px;color:#555;margin-bottom:12px}
    table{width:100%;border-collapse:collapse}
    th,td{border:1px dashed #888;padding:4px 6px;text-align:left}
    th{font-weight:600;font-size:10px;text-transform:uppercase}
    th:nth-child(1),td:nth-child(1){width:5%;text-align:center}
    th:nth-child(3),td:nth-child(3),th:nth-child(4),td:nth-child(4),th:nth-child(5),td:nth-child(5){width:13%;text-align:center}
    .note{margin-top:14px;font-size:10px;color:#444;border-top:1px dashed #aaa;padding-top:8px}
  </style></head><body>
    <h2>Slow-Moving Products</h2>
    <div class="sub">${esc(dateRange)}</div>
    <table>
      <thead><tr><th>#</th><th>Product Name</th><th>Sales</th><th>Last Sale</th><th>Days Since</th></tr></thead>
      <tbody>${tableRows}</tbody>
    </table>
    <div class="note">&#9888; Products still in machine — change on next visit, do not empty lane in advance.</div>
  </body></html>`

  const defaultPath = path.join(os.homedir(), 'Desktop', 'slow-movers.pdf')
  const { canceled, filePath } = await dialog.showSaveDialog({ defaultPath, filters: [{ name: 'PDF', extensions: ['pdf'] }] })
  if (canceled || !filePath) return { ok: false }

  const printWin = new BrowserWindow({ show: false, webPreferences: { contextIsolation: true } })
  printWin.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html))
  await new Promise(resolve => printWin.webContents.once('did-finish-load', resolve))
  const pdfBuffer = await printWin.webContents.printToPDF({ printBackground: false })
  printWin.destroy()
  fs.writeFileSync(filePath, pdfBuffer)
  return { ok: true, filePath }
})

ipcMain.handle('save-pick-edit', (_, { machine, date, rows }) => {
  const safe = machine.replace(/[^a-zA-Z0-9]/g, '_')
  const fpath = path.join(ROOT, 'db', `pick_edit_${safe}_${date}.json`)
  fs.writeFileSync(fpath, JSON.stringify({ machine, date, rows }, null, 2))
})

ipcMain.handle('load-pick-edit', (_, { machine, date }) => {
  const safe = machine.replace(/[^a-zA-Z0-9]/g, '_')
  const fpath = path.join(ROOT, 'db', `pick_edit_${safe}_${date}.json`)
  if (!fs.existsSync(fpath)) return null
  try { return JSON.parse(fs.readFileSync(fpath, 'utf8')) } catch { return null }
})


