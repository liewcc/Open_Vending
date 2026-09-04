const { app, BrowserWindow, ipcMain, safeStorage, Tray, Menu, globalShortcut, Notification, dialog, shell } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const fs   = require('fs')
const os   = require('os')

const ROOT          = path.join(__dirname, '..')
const CRED_FILE     = path.join(app.getPath('userData'), 'credentials.enc')
const SETTINGS_FILE = path.join(app.getPath('userData'), 'settings.json')
const ACCOUNTS_FILE = path.join(app.getPath('userData'), 'accounts.json')
const DEFAULT_SETTINGS = { menuBar: false, showConsole: false, closeTray: false, notifyChanges: false, autoDownload: false, autoDownloadInterval: 30, headedBrowser: false, landingUrl: 'https://vendingportal.azurewebsites.net/SuperAdmin/SPLogin.aspx', q3ThresholdPct: 50, uiZoom: 100, pdfPaperSize: 'A4', pdfFontPct: 100, pdfMarginTop: 12, pdfMarginBottom: 12, pdfMarginLeft: 12, pdfMarginRight: 12, pdfPages: 1, showWeekBadges: true, pdfDuplex: true, remoteUrl: '', remoteToken: '' }
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

// ── Accounts ──────────────────────────────────────────────────────────────────
// One account is active at a time; every data path resolves through dataDir().
// The primary account keeps the original db/ folder (dir: null) so existing
// installs are untouched — added accounts get db/accounts/<id>/.

const PRIMARY_ID = 'dvends'
let accounts = null

function defaultAccounts() {
  return {
    active: PRIMARY_ID,
    accounts: [{
      id: PRIMARY_ID, label: 'Dvends', dir: null, scan: true,
      landingUrl: DEFAULT_SETTINGS.landingUrl
    }]
  }
}

function loadAccounts() {
  try {
    const a = JSON.parse(fs.readFileSync(ACCOUNTS_FILE, 'utf8'))
    if (a && Array.isArray(a.accounts) && a.accounts.length) return a
  } catch { /* missing or corrupt — fall back to the primary-only default */ }
  return defaultAccounts()
}

function saveAccounts() {
  fs.writeFileSync(ACCOUNTS_FILE, JSON.stringify(accounts, null, 2))
}

// Lazy so it is safe to call before app.whenReady()
function activeAccount() {
  if (!accounts) accounts = loadAccounts()
  return accounts.accounts.find(a => a.id === accounts.active) || accounts.accounts[0]
}

function dataDir(acct) {
  const a = acct || activeAccount()
  if (!a.dir) return path.join(ROOT, 'db')
  const d = path.join(ROOT, 'db', a.dir)
  fs.mkdirSync(d, { recursive: true })
  return d
}

const lastReport      = a => path.join(dataDir(a), 'last_report.xlsx')
const lastDiffsFile   = a => path.join(dataDir(a), 'last_diffs.json')
const routePlanPath   = a => path.join(dataDir(a), 'route_plan.json')
// One physical file; the three aliases keep each handler saying which layer it uses.
const vendingDb       = a => path.join(dataDir(a), 'vending.db')
const dataDb          = vendingDb
const salesDetailDb   = vendingDb
const salesForecastDb = vendingDb

// Create the tables an account's DB needs. Runs at startup for the active
// account, and again whenever the active account changes — a window reload
// does not re-run app.whenReady().
function initAccount(acct) {
  spawnPy([PICKING_HISTORY, 'init'], null, { OV_DATA_DIR: dataDir(acct) })
  spawnPy([BUFFER_STOCK, 'init', vendingDb(acct)], null, { OV_DATA_DIR: dataDir(acct) })
}

const LOCAL_VERSION  = require('../package.json').version
const xlsx = require(path.join(__dirname, '..', 'node_modules', 'xlsx'))
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

// credentials.enc holds one record per account id. A pre-multi-account file is a
// bare { u, p } and belongs to the primary — it is read in place and only
// rewritten in the keyed shape when a credential is actually saved.
function loadCredentials(id) {
  if (!fs.existsSync(CRED_FILE)) return null
  const acctId = id || activeAccount().id
  try {
    const raw = JSON.parse(fs.readFileSync(CRED_FILE, 'utf8'))
    const rec = (raw.u && raw.p) ? (acctId === PRIMARY_ID ? raw : null) : raw[acctId]
    if (!rec) return null
    return {
      username: safeStorage.decryptString(Buffer.from(rec.u, 'base64')),
      password: safeStorage.decryptString(Buffer.from(rec.p, 'base64'))
    }
  } catch { return null }
}

function saveCredentials(username, password, id) {
  const acctId = id || activeAccount().id
  let raw = {}
  try {
    const cur = JSON.parse(fs.readFileSync(CRED_FILE, 'utf8'))
    raw = (cur.u && cur.p) ? { [PRIMARY_ID]: cur } : cur
  } catch { /* first save — start empty */ }
  raw[acctId] = {
    u: safeStorage.encryptString(username).toString('base64'),
    p: safeStorage.encryptString(password).toString('base64')
  }
  fs.writeFileSync(CRED_FILE, JSON.stringify(raw))
}

// ── Window ────────────────────────────────────────────────────────────────────

const overlayOpts = { color: '#1e2235', symbolColor: '#cdd6f4', height: 38 }

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    icon: ICON_PNG,
    titleBarStyle: 'hidden',
    titleBarOverlay: overlayOpts,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    },
    backgroundColor: '#f0f2f5'
  })
  win.loadFile(path.join(__dirname, 'index.html'))

  // Chromium sometimes blanks the native window-controls overlay without repainting
  // (after restore/show/focus/maximize). Re-apply it to force a redraw.
  const repaintOverlay = () => { if (win && !win.isDestroyed()) win.setTitleBarOverlay(overlayOpts) }
  ;['show', 'restore', 'focus', 'maximize', 'unmaximize'].forEach(ev => win.on(ev, repaintOverlay))

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
    if (!isDownloading) runScanQueue(accountsToScan())
  }, settings.autoDownloadInterval * 60 * 1000)
}

// ── Download ──────────────────────────────────────────────────────────────────
// One Python process per account, run sequentially. Separate processes mean
// separate browsers and therefore separate cookie jars, so a live session from
// the previous account cannot leak into the next one's login. It also binds the
// output folder to the process at spawn time, so a scan that finishes after the
// user switches accounts still writes where it started.

// acctId -> { state: 'running' | 'ok' | 'err', at: ISO, reason? }
let scanStatus = {}

function pushScanStatus() {
  if (win && !win.isDestroyed()) win.webContents.send('scan-status', scanStatus)
}

function scanAccount(acct) {
  return new Promise(resolve => {
    const creds = loadCredentials(acct.id)
    if (!creds) {
      scanStatus[acct.id] = { state: 'err', at: new Date().toISOString(), reason: 'no credentials' }
      win.webContents.send('py-out', `ERROR: [${acct.label || acct.id}] no credentials saved`)
      pushScanStatus()
      return resolve(false)
    }

    const isActive = acct.id === activeAccount().id
    const label    = acct.label || acct.id
    const tag      = isActive ? '' : `[${label}] `
    const outDir   = dataDir(acct)

    scanStatus[acct.id] = { state: 'running', at: new Date().toISOString() }
    pushScanStatus()

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
        OV_LANDING_URL: acct.landingUrl || settings.landingUrl || '',
        OV_DATA_DIR: outDir
      }
    })

    proc.stdout.on('data', data => {
      data.toString().trim().split('\n').forEach(line => {
        line = line.trim()
        if (!line) return
        if (line.startsWith('DIFFS: ')) {
          let diffs = []
          try { diffs = JSON.parse(line.slice(7)) } catch { diffs = [] }
          try { fs.writeFileSync(lastDiffsFile(acct), JSON.stringify(diffs)) } catch { }
          // Only the active account drives the Changing List in the UI
          if (isActive) lastDiffs = diffs
          if (settings.notifyChanges && diffs.length > 0) {
            const notif = new Notification({
              title: 'Open Vending — Restock Changes',
              body: `${label}: ${diffs.length} restock change${diffs.length > 1 ? 's' : ''} detected`,
              icon: ICON_PNG
            })
            notif.on('click', () => { win.show(); win.focus() })
            notif.show()
          }
          return
        }
        win.webContents.send('py-out', tag + line)
        // Never swap the visible report to a background account's file
        const m = line.match(/^FILE: (.+)$/)
        if (m && isActive) win.webContents.send('file-ready', m[1].trim())
      })
    })

    proc.stderr.on('data', data => {
      win.webContents.send('py-out', `ERROR: ${tag}` + data.toString().trim())
    })

    // 'error' and 'close' can both fire for one process — settle only once, or
    // a spawn failure would be overwritten by the close status.
    let settled = false
    const finish = (ok, reason) => {
      if (settled) return
      settled = true
      scanStatus[acct.id] = { state: ok ? 'ok' : 'err', at: new Date().toISOString(), ...(reason ? { reason } : {}) }
      pushScanStatus()
      resolve(ok)
    }

    proc.on('error', err => {
      win.webContents.send('py-out', `ERROR: ${tag}` + err.message)
      finish(false, err.message)
    })
    proc.on('close', code => finish(code === 0))
  })
}

// Accounts kept fresh on startup and on the interval timer, active one first so
// the visible account is usable soonest. An unchecked account is not scanned —
// it keeps its last-scanned data until you switch to it or re-download.
function accountsToScan() {
  const act = activeAccount()
  const due = accounts.accounts.filter(a => a.scan)
  return due.some(a => a.id === act.id) ? [act, ...due.filter(a => a.id !== act.id)] : due
}

async function runScanQueue(accts) {
  if (isDownloading || !accts.length) return
  isDownloading = true
  win.webContents.send('download-started')
  let allOk = true
  for (const acct of accts) {
    const ok = await scanAccount(acct)
    if (!ok) allOk = false
  }
  isDownloading = false
  win.webContents.send('py-done', allOk)
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
      OV_LANDING_URL: activeAccount().landingUrl || settings.landingUrl || '',
      OV_DATA_DIR: dataDir()
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
  accounts = loadAccounts()
  createWindow()
  initAccount(activeAccount())
  // Daily rotating backup per account (each skips if already done today)
  for (const a of accounts.accounts) spawnPy([DB_BACKUP], null, { OV_DATA_DIR: dataDir(a) })

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
  // Runs on every load, not just the first: switching account reloads the
  // window, and the new account's report and diffs have to be restored again.
  let firstLoad = true
  win.webContents.on('did-finish-load', () => {
    cachedCreds = loadCredentials()

    // Make the resolved account and folder visible every launch, so a wrong
    // path is obvious in the Log card instead of silently producing odd data.
    win.webContents.send('py-out', `Account: ${activeAccount().label} — data: ${dataDir()}`)

    // restore last known state before new scan starts
    if (fs.existsSync(lastReport())) {
      win.webContents.send('file-ready', lastReport())
    }
    lastDiffs = []
    if (fs.existsSync(lastDiffsFile())) {
      try {
        lastDiffs = JSON.parse(fs.readFileSync(lastDiffsFile(), 'utf8'))
      } catch { }
    }
    pushScanStatus()

    if (!firstLoad) return
    firstLoad = false

    prunePdfExports()

    if (cachedCreds) {
      runScanQueue(accountsToScan())
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

// extraEnv targets a specific account (see initAccount / the backup loop);
// without it the call runs against the active account.
function spawnPy(args, stdinData, extraEnv) {
  return new Promise(resolve => {
    const pythonExe = path.join(ROOT, 'python', 'python.exe')
    const proc = spawn(pythonExe, args, {
      windowsHide: true,
      // UTF-8 stdio: Node writes UTF-8, but Python on Windows defaults to
      // the locale codepage (cp1252) and mangles non-ASCII (e.g. the "→"
      // in replacement product names) on the way into the DB
      // OV_REMOTE_* point picking_history and buffer_stock at the shared hosted
      // DB. Blank (the default) leaves every script on the local file as before.
      env: { ...process.env, PYTHONNOUSERSITE: '1', PYTHONPATH: '', PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', OV_DATA_DIR: dataDir(), OV_REMOTE_URL: settings.remoteUrl || process.env.OV_REMOTE_URL || '', OV_REMOTE_TOKEN: settings.remoteToken || process.env.OV_REMOTE_TOKEN || '', ...extraEnv }
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
  runScanQueue([activeAccount()])
})

// Manual re-download always refreshes the account you are looking at, whether
// or not it is checked for periodic scanning.
ipcMain.on('start-download', () => {
  runScanQueue([activeAccount()])
})

ipcMain.on('do-update', () => doUpdate())
ipcMain.on('quit-app',  () => app.quit())

ipcMain.handle('get-settings', () => settings)

// Synchronous: preload needs the active account's folder at load time, before
// it reads route_plan.json (see src/preload.js).
ipcMain.on('get-data-dir', e => { e.returnValue = dataDir() })

ipcMain.handle('get-scan-status', () => scanStatus)

// The renderer pulls its report once it is ready, rather than relying only on
// the push at did-finish-load. On first launch a missed push is masked by the
// scan re-sending file-ready moments later; after an account switch no scan
// runs, so that single push was the only chance the table had to populate.
ipcMain.handle('get-current-report', () => {
  const p = lastReport()
  return fs.existsSync(p) ? p : null
})

// ── Account management ────────────────────────────────────────────────────────

function slugify(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 24)
}

// Never includes passwords — those only leave main via reveal-credential, one
// account at a time, when the user asks for them.
function publicAccounts() {
  return {
    active: activeAccount().id,
    primary: PRIMARY_ID,
    accounts: accounts.accounts.map(a => {
      const c = loadCredentials(a.id)
      return {
        id: a.id,
        label: a.label || a.id,
        scan: !!a.scan,
        landingUrl: a.landingUrl || '',
        folder: dataDir(a),
        username: c ? c.username : '',
        hasPassword: !!c,
        status: scanStatus[a.id] || null
      }
    })
  }
}

ipcMain.handle('get-accounts', () => publicAccounts())

ipcMain.handle('add-account', (_, { label, username, password, landingUrl }) => {
  label    = String(label || '').trim()
  username = String(username || '').trim()
  if (!label || !username || !password) return { ok: false, error: 'Name, login ID and password are all required' }

  let id = slugify(label) || 'account'
  if (accounts.accounts.some(a => a.id === id)) {
    let n = 2
    while (accounts.accounts.some(a => a.id === `${id}-${n}`)) n++
    id = `${id}-${n}`
  }
  const acct = {
    id, label, dir: `accounts/${id}`, scan: true,
    landingUrl: String(landingUrl || '').trim() || DEFAULT_SETTINGS.landingUrl
  }
  accounts.accounts.push(acct)
  saveCredentials(username, password, id)   // also migrates a legacy cred file
  saveAccounts()
  initAccount(acct)                          // creates the folder + its tables
  // Fetch its first report now, so the account is usable without a restart and
  // any credential mistake surfaces immediately rather than at the next launch.
  runScanQueue([acct])
  return { ok: true, id, accounts: publicAccounts() }
})

ipcMain.handle('update-account', (_, { id, label, username, password, landingUrl, scan }) => {
  const a = accounts.accounts.find(x => x.id === id)
  if (!a) return { ok: false, error: 'account not found' }

  if (label !== undefined && String(label).trim()) a.label = String(label).trim()
  if (landingUrl !== undefined) a.landingUrl = String(landingUrl).trim()
  if (scan !== undefined) a.scan = !!scan
  saveAccounts()

  // Credentials are only rewritten when something was actually supplied — a
  // blank password field means "leave it alone", not "clear it".
  if ((username !== undefined && String(username).trim()) || password) {
    const cur = loadCredentials(id) || { username: '', password: '' }
    const u = (username !== undefined && String(username).trim()) ? String(username).trim() : cur.username
    const p = password || cur.password
    if (u && p) saveCredentials(u, p, id)
  }
  if (scan !== undefined) setupAutoDownload()
  return { ok: true, accounts: publicAccounts() }
})

// Removes the account from the list but deliberately leaves its data folder on
// disk — it holds picking history, buffer stock and the route plan. Deleting
// that is a separate, explicit action.
ipcMain.handle('remove-account', (_, id) => {
  if (id === PRIMARY_ID) return { ok: false, error: 'The primary account cannot be removed' }
  const i = accounts.accounts.findIndex(a => a.id === id)
  if (i < 0) return { ok: false, error: 'account not found' }

  const folder = dataDir(accounts.accounts[i])
  accounts.accounts.splice(i, 1)
  if (accounts.active === id) accounts.active = PRIMARY_ID
  saveAccounts()
  try {
    const raw = JSON.parse(fs.readFileSync(CRED_FILE, 'utf8'))
    if (!(raw.u && raw.p)) { delete raw[id]; fs.writeFileSync(CRED_FILE, JSON.stringify(raw)) }
  } catch { }
  return { ok: true, folder, accounts: publicAccounts() }
})

ipcMain.handle('delete-account-data', async (_, id) => {
  if (id === PRIMARY_ID) return { ok: false, error: 'Refusing to delete the primary account folder' }
  if (accounts.accounts.some(a => a.id === id)) {
    return { ok: false, error: 'Remove the account from the list first' }
  }
  const folder = path.join(ROOT, 'db', 'accounts', id)
  if (!fs.existsSync(folder)) return { ok: false, error: 'No data folder for that account' }
  try { await shell.trashItem(folder); return { ok: true, folder } }
  catch (e) { return { ok: false, error: e.message } }
})

ipcMain.handle('reveal-credential', (_, id) => {
  const c = loadCredentials(id)
  return c ? { ok: true, username: c.username, password: c.password } : { ok: false }
})

ipcMain.handle('set-active-account', (_, id) => {
  const a = accounts.accounts.find(x => x.id === id)
  if (!a) return { ok: false, error: 'account not found' }
  if (accounts.active === id) return { ok: true, unchanged: true }
  if (isDownloading) return { ok: false, error: 'A scan is running — try again once it finishes' }

  accounts.active = id
  saveAccounts()
  initAccount(a)
  // Reload after replying, so the renderer gets this result before it is torn
  // down. did-finish-load then restores the new account's report and diffs.
  setTimeout(() => { if (win && !win.isDestroyed()) win.reload() }, 50)
  return { ok: true }
})

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

const QUERY_HISTORY      = path.join(__dirname, 'query_history.py')
const PICKING_HISTORY    = path.join(__dirname, 'picking_history.py')
const SLOW_MOVERS        = path.join(__dirname, 'slow_movers.py')
const BUILD_SALES_DETAIL   = path.join(__dirname, 'build_sales_detail.py')
const BUILD_SALES_FORECAST = path.join(__dirname, 'build_sales_forecast.py')
const BUFFER_STOCK         = path.join(__dirname, 'buffer_stock.py')
const REPL_SUGGEST         = path.join(__dirname, 'replacement_suggest.py')
const MACHINE_SALES        = path.join(__dirname, 'machine_sales.py')
// All data lives in the unified vending.db (see src/migrate_to_vending.py),
// now resolved per active account — see dataDb() / salesDetailDb() above.
const DB_BACKUP            = path.join(__dirname, 'db_backup.py')
ipcMain.handle('save-route-plan', (_, data) => {
  try {
    fs.writeFileSync(routePlanPath(), JSON.stringify(data, null, 2))
    return { ok: true }
  } catch (e) {
    return { ok: false, error: e.message }
  }
})
ipcMain.handle('get-restock-history', (_, { machine, lane }) =>
  new Promise(resolve => {
    const pythonExe = path.join(ROOT, 'python', 'python.exe')
    const proc = spawn(pythonExe, [QUERY_HISTORY, machine, String(lane)], {
      windowsHide: true,
      // UTF-8 stdio: Node writes UTF-8, but Python on Windows defaults to
      // the locale codepage (cp1252) and mangles non-ASCII (e.g. the "→"
      // in replacement product names) on the way into the DB
      env: { ...process.env, PYTHONNOUSERSITE: '1', PYTHONPATH: '', PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', OV_DATA_DIR: dataDir() }
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
ipcMain.handle('get-pending-detail',     ()         => spawnPy([PICKING_HISTORY, 'get-pending-detail'], null))
ipcMain.handle('get-oos-counts',         ()         => spawnPy([PICKING_HISTORY, 'get-oos-counts'], null))
ipcMain.handle('save-picks',             (_, picks) => spawnPy([PICKING_HISTORY, 'save-picks'],   picks))
ipcMain.handle('mark-done',              (_, machines) => spawnPy([PICKING_HISTORY, 'mark-done'], machines))
ipcMain.handle('get-history-dates',      ()         => spawnPy([PICKING_HISTORY, 'get-history-dates'], null))
ipcMain.handle('get-history-by-date',    (_, date)  => spawnPy([PICKING_HISTORY, 'get-history-by-date', date], null))
ipcMain.handle('get-week-summary',       (_, r)    => spawnPy([PICKING_HISTORY, 'get-week-summary', r.from, r.to], null))

// ── Exported PDF cleanup ──────────────────────────────────────────────────────
// Exports go wherever the save dialog is pointed (usually the Desktop), so the
// app cannot safely scan a folder for old PDFs — it would find the user's own
// files. Instead every export this app writes is recorded here, and cleanup only
// ever considers those exact paths. Removal goes to the Recycle Bin, so even a
// wrong call is recoverable. The ledger is shared across accounts, so a PDF
// exported under one account is still pruned while another is active.

const PDF_LEDGER  = path.join(ROOT, 'db', 'pdf_exports.json')
const PDF_KEEP_MS = 7 * 24 * 60 * 60 * 1000

function readPdfLedger() {
  try {
    const l = JSON.parse(fs.readFileSync(PDF_LEDGER, 'utf8'))
    return Array.isArray(l) ? l : []
  } catch { return [] }
}

function recordPdfExport(filePath) {
  try {
    const led = readPdfLedger().filter(e => e && e.path !== filePath)
    led.push({ path: filePath, at: Date.now() })
    fs.writeFileSync(PDF_LEDGER, JSON.stringify(led))
  } catch { /* the ledger is a convenience — never fail an export over it */ }
}

async function prunePdfExports() {
  const led = readPdfLedger()
  if (!led.length) return
  const cutoff = Date.now() - PDF_KEEP_MS
  const keep = []
  let trashed = 0
  for (const e of led) {
    if (!e || !e.path) continue
    if (!(e.at > 0) || e.at > cutoff) { keep.push(e); continue }
    try {
      // Already gone (moved or deleted by hand) — just drop the entry
      if (!fs.existsSync(e.path)) continue
      // Something newer now sits at that path — not the file we exported
      if (fs.statSync(e.path).mtimeMs > e.at + 60000) { keep.push(e); continue }
      await shell.trashItem(e.path)
      trashed++
    } catch { keep.push(e) }   // locked, permission denied, etc — try again later
  }
  try { fs.writeFileSync(PDF_LEDGER, JSON.stringify(keep)) } catch { }
  if (trashed && win && !win.isDestroyed()) {
    win.webContents.send('py-out',
      `Cleaned up ${trashed} exported PDF${trashed > 1 ? 's' : ''} older than 7 days (moved to Recycle Bin)`)
  }
}

// Layout derived from the PDF Export settings — shared by every printToPDF export.
const PAPER_MM = { A4: [210, 297], A5: [148, 210], Letter: [215.9, 279.4], Legal: [215.9, 355.6] }
function pdfLayout() {
  const paper = PAPER_MM[settings.pdfPaperSize] ? settings.pdfPaperSize : 'A4'
  const [w, h] = PAPER_MM[paper]
  const mm = k => Math.min(50, Math.max(0, Number(settings[k]) || 0))
  const m = { top: mm('pdfMarginTop'), bottom: mm('pdfMarginBottom'), left: mm('pdfMarginLeft'), right: mm('pdfMarginRight') }
  return {
    baseFs: 12 * Math.max(100, Number(settings.pdfFontPct) || 100) / 100,
    bodyW: w - m.left - m.right,                 // printable width in mm
    pageH: (h - m.top - m.bottom) / 25.4 * 96,   // printable height in CSS px
    pageCss: `@page{size:${paper} portrait;margin:${m.top}mm ${m.right}mm ${m.bottom}mm ${m.left}mm}`,
    printOpts: { printBackground: false, pageSize: paper, margins: { top: m.top / 25.4, bottom: m.bottom / 25.4, left: m.left / 25.4, right: m.right / 25.4 } }
  }
}

ipcMain.handle('print-all-picking-lists', async (_, { data, pages }) => {
  function esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
  }
  const pageHtml = data.map(m => {
    const rows = m.rows.map(r => {
      const repl = r.replacement && r.replacement.trim()
      if (repl) {
        return `<tr class="rep"><td>${esc(r.no)}</td><td class="orig">${esc(r.product)}</td><td class="col1">${esc(repl)}</td><td>${esc(r.bal)}</td><td>${esc(r.lane)}</td><td>${esc(r.restock)}</td></tr>`
      }
      return `<tr><td>${esc(r.no)}</td><td>${esc(r.product)}</td><td></td><td>${esc(r.bal)}</td><td>${esc(r.lane)}</td><td>${esc(r.restock)}</td></tr>`
    }).join('')
    return `<div class="page"><table><thead><tr class="mhd"><th colspan="6"><div class="hdr"><span>${esc(m.date)}</span><span>${esc(m.machine)} ${esc(m.team)}</span></div></th></tr><tr><th>No.</th><th>Product Name</th><th>Replacement</th><th>Bal Qty</th><th>Lane Size</th><th>Restock</th></tr></thead><tbody>${rows}</tbody></table></div>`
  }).join('')

  const L = pdfLayout()
  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>*{box-sizing:border-box;margin:0;padding:0}:root{--fs:${L.baseFs}px}body{font-family:'Calibri Light',Calibri,Arial,sans-serif;font-size:var(--fs);line-height:1.15;width:${L.bodyW}mm}${L.pageCss}.page{page-break-after:always;break-after:page}.page:last-child{page-break-after:avoid;break-after:avoid}tr.mhd th{border:none;padding:0 0 0.36em}.hdr{display:flex;justify-content:space-between;font-size:13px;font-weight:bold;padding-bottom:0.36em;border-bottom:1.5px solid #000}table{width:100%;border-collapse:collapse;font-size:1em}th,td{border:1px dashed #aaa;padding:0.22em 0.55em;text-align:left}th{font-weight:600}th:nth-child(1){width:5%}th:nth-child(2){width:38%}th:nth-child(3){width:22%}th:nth-child(4),th:nth-child(5),th:nth-child(6){width:10%;text-align:center}td:nth-child(4),td:nth-child(5),td:nth-child(6){text-align:center}tr{page-break-inside:avoid}tr.rep td.orig{text-decoration:line-through;color:#777}tr.rep td.col1{background-color:#ffffa0!important;font-weight:500}</style></head><body>${pageHtml}</body></html>`

  const defaultPath = settings.lastPdfPath || path.join(os.homedir(), 'Desktop', 'picking-list.pdf')
  const { canceled, filePath } = await dialog.showSaveDialog({ defaultPath, filters: [{ name: 'PDF', extensions: ['pdf'] }] })
  if (canceled || !filePath) return { ok: false }

  const printWin = new BrowserWindow({ show: false, webPreferences: { contextIsolation: true } })
  printWin.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html))
  await new Promise(resolve => printWin.webContents.once('did-finish-load', resolve))

  // Shrink font until every machine's section fits its page budget (min 5px).
  // pages = max pages per machine (each .page starts on a fresh sheet).
  // scrollHeight underestimates print pages: Chromium repeats <thead> on every
  // page and pushes unbreakable rows down, so simulate that pagination instead.
  if (pages >= 1) {
    const PAGE_H = L.pageH
    const simScript = `(() => {
      const pageH = ${PAGE_H.toFixed(2)};
      let maxPages = 0;
      document.querySelectorAll('.page').forEach(pg => {
        const table = pg.querySelector('table');
        const thead = pg.querySelector('thead');
        if (!table || !thead) return;
        const headerH = table.getBoundingClientRect().top - pg.getBoundingClientRect().top;
        const theadH = thead.getBoundingClientRect().height;
        let used = headerH + theadH;
        let n = 1;
        pg.querySelectorAll('tbody tr').forEach(tr => {
          const h = tr.getBoundingClientRect().height;
          if (used + h > pageH) { n++; used = theadH + h; } else { used += h; }
        });
        maxPages = Math.max(maxPages, n);
      });
      return maxPages;
    })()`
    let fs2 = L.baseFs
    for (let i = 0; i < 10; i++) {
      const maxP = await printWin.webContents.executeJavaScript(simScript)
      if (maxP <= pages || fs2 <= 5) break
      // First overflow: jump by the page ratio; then converge in small steps.
      const factor = i === 0 ? Math.max(0.5, pages / maxP) : 0.95
      fs2 = Math.max(5, fs2 * factor)
      await printWin.webContents.executeJavaScript(`document.documentElement.style.setProperty('--fs','${fs2.toFixed(2)}px')`)
    }
  }

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

  const pdfBuffer = await printWin.webContents.printToPDF(L.printOpts)
  printWin.destroy()

  fs.writeFileSync(filePath, pdfBuffer)
  recordPdfExport(filePath)
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

ipcMain.handle('analyze-slow-machine', (_, machine) =>
  spawnPy([SLOW_MOVERS, 'machine', salesDetailDb(), machine], null)
)

ipcMain.handle('print-slow-movers', async (_, { rows, dateRange }) => {
  function esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
  }
  const tableRows = rows.map((r, i) =>
    `<tr><td>${i+1}</td><td>${esc(r.name)}</td><td>${r.total}</td><td>${esc(r.last_sale) || '—'}</td><td>${r.days != null ? r.days + 'd' : 'Never'}</td></tr>`
  ).join('')
  const L = pdfLayout()
  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Calibri Light',Calibri,Arial,sans-serif;font-size:${L.baseFs}px}
    ${L.pageCss}
    h2{font-size:1.27em;margin-bottom:3px}
    .sub{font-size:0.91em;color:#555;margin-bottom:12px}
    table{width:100%;border-collapse:collapse}
    th,td{border:1px dashed #aaa;padding:4px 6px;text-align:left}
    th{font-weight:600;font-size:0.91em;text-transform:uppercase}
    th:nth-child(1),td:nth-child(1){width:5%;text-align:center}
    th:nth-child(3),td:nth-child(3),th:nth-child(4),td:nth-child(4),th:nth-child(5),td:nth-child(5){width:13%;text-align:center}
    .note{margin-top:14px;font-size:0.91em;color:#444;border-top:1px dashed #aaa;padding-top:8px}
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
  const pdfBuffer = await printWin.webContents.printToPDF(L.printOpts)
  printWin.destroy()
  fs.writeFileSync(filePath, pdfBuffer)
  recordPdfExport(filePath)
  return { ok: true, filePath }
})

ipcMain.handle('export-queue-excel', async (_, rows) => {
  const defaultPath = path.join(os.homedir(), 'Desktop', 'in-transit-queue.xlsx')
  const { canceled, filePath } = await dialog.showSaveDialog({ defaultPath, filters: [{ name: 'Excel', extensions: ['xlsx'] }] })
  if (canceled || !filePath) return { ok: false }

  const aoa = [['Machine', 'Lane', 'Product Name', 'Qty'], ...rows.map(r => [r.machine, r.lane, r.product || '', r.qty])]
  const ws = xlsx.utils.aoa_to_sheet(aoa)
  const wb = xlsx.utils.book_new()
  xlsx.utils.book_append_sheet(wb, ws, 'Queue')
  xlsx.writeFile(wb, filePath)
  return { ok: true, filePath }
})

// Buffer Stock page export — columns mirror bufColumns in index.html.
// If a column is added/removed there, update this header + the renderer's .map().
ipcMain.handle('export-buffer-excel', async (_, { rows, machine }) => {
  const safe = String(machine || 'buffer').replace(/[\\/:*?"<>|]/g, '_')
  const defaultPath = path.join(os.homedir(), 'Desktop', `buffer-stock-${safe}.xlsx`)
  const { canceled, filePath } = await dialog.showSaveDialog({ defaultPath, filters: [{ name: 'Excel', extensions: ['xlsx'] }] })
  if (canceled || !filePath) return { ok: false }

  const aoa = [['Lane', 'Lane Size', 'PID', 'Product', 'Sug Normal', 'Sug Sem Break', 'Normal', 'Sem Break'], ...rows]
  const ws = xlsx.utils.aoa_to_sheet(aoa)
  const wb = xlsx.utils.book_new()
  xlsx.utils.book_append_sheet(wb, ws, safe.slice(0, 31))
  xlsx.writeFile(wb, filePath)
  return { ok: true, filePath }
})

ipcMain.handle('export-queue-pdf', async (_, { rows, pages, date }) => {
  function esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
  }
  // Group rows by machine, preserving first-seen order — each machine gets
  // its own table with the machine name as a heading row in <thead> (repeats
  // on every printed page that table spans) instead of a per-row column.
  const machines = []
  const byMachine = {}
  rows.forEach(r => {
    if (!byMachine[r.machine]) { byMachine[r.machine] = []; machines.push(r.machine) }
    byMachine[r.machine].push(r)
  })
  // Each machine gets its own .page section so it starts on a fresh sheet;
  // the pages limit is a per-machine budget, not a whole-document one.
  // Replacement rows arrive as "orig → repl" (assembled at queue time from
  // the edit file): print the original struck through, then the arrow and
  // the replacement — same convention as the per-machine picking-list PDF.
  function prodCell(s) {
    const str = String(s ?? '')
    const i = str.indexOf(' → ')
    if (i < 0) return esc(str)
    return `<span class="orig">${esc(str.slice(0, i))}</span> → <span class="repl">${esc(str.slice(i + 3))}</span>`
  }
  const tables = machines.map(mach => {
    const tableRows = byMachine[mach].map(r => `<tr><td>${esc(r.lane)}</td><td>${prodCell(r.product)}</td><td>${esc(r.qty)}</td></tr>`).join('')
    return `<div class="page"><table><thead><tr class="mhd"><th colspan="3"><div class="mh"><span>${esc(mach)}</span><span>${esc(date)}</span></div></th></tr><tr><th>Lane</th><th>Product Name</th><th>Qty</th></tr></thead><tbody>${tableRows}</tbody></table></div>`
  }).join('')
  // Font sizes/padding in em relative to --fs so the fit loop below can scale
  // the whole document by changing one variable. body width = A4 printable
  // width (210mm - 2x15mm margins) so on-screen wrap matches print wrap.
  const L = pdfLayout()
  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
    *{box-sizing:border-box;margin:0;padding:0}
    :root{--fs:${L.baseFs}px}
    body{font-family:'Calibri Light',Calibri,Arial,sans-serif;font-size:var(--fs);line-height:1.15;width:${L.bodyW}mm}
    ${L.pageCss}
    .page{page-break-after:always;break-after:page}
    .page:last-child{page-break-after:avoid;break-after:avoid}
    table{width:100%;border-collapse:collapse}
    th,td{border:1px dashed #aaa;padding:0.22em 0.55em;text-align:left}
    th{font-weight:600;font-size:0.9em;text-transform:uppercase}
    tr.mhd th{border:none;font-size:1.1em;text-transform:none;padding:0.3em 0.1em}
    .mh{display:flex;justify-content:space-between}
    th:nth-child(3),td:nth-child(3){width:15%;text-align:center}
    tr{page-break-inside:avoid}
    .orig{text-decoration:line-through;color:#777}
    .repl{font-weight:600}
  </style></head><body>
    ${tables}
  </body></html>`

  const defaultPath = path.join(os.homedir(), 'Desktop', 'in-transit-queue.pdf')
  const { canceled, filePath } = await dialog.showSaveDialog({ defaultPath, filters: [{ name: 'PDF', extensions: ['pdf'] }] })
  if (canceled || !filePath) return { ok: false }

  const printWin = new BrowserWindow({ show: false, webPreferences: { contextIsolation: true } })
  printWin.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html))
  await new Promise(resolve => printWin.webContents.once('did-finish-load', resolve))

  // Shrink font until every machine's section fits its page budget (min 5px).
  // pages = max pages per machine (each .page starts on a fresh sheet).
  // Simulate real print pagination: <thead> repeats on every page and rows
  // never split across pages, so continuous scrollHeight underestimates.
  const targetPages = Math.max(1, Number(pages) || 1)
  const PAGE_H = L.pageH
  const simScript = `(() => {
    const pageH = ${PAGE_H.toFixed(2)};
    let maxPages = 1;
    document.querySelectorAll('.page').forEach(pg => {
      const table = pg.querySelector('table');
      const thead = pg.querySelector('thead');
      if (!table || !thead) return;
      const headerH = table.getBoundingClientRect().top - pg.getBoundingClientRect().top;
      const theadH = thead.getBoundingClientRect().height;
      let used = headerH + theadH;
      let n = 1;
      pg.querySelectorAll('tbody tr').forEach(tr => {
        const h = tr.getBoundingClientRect().height;
        if (used + h > pageH) { n++; used = theadH + h; } else { used += h; }
      });
      maxPages = Math.max(maxPages, n);
    });
    return maxPages;
  })()`
  let fs2 = L.baseFs
  for (let i = 0; i < 10; i++) {
    const maxP = await printWin.webContents.executeJavaScript(simScript)
    if (maxP <= targetPages || fs2 <= 5) break
    const factor = i === 0 ? Math.max(0.5, targetPages / maxP) : 0.95
    fs2 = Math.max(5, fs2 * factor)
    await printWin.webContents.executeJavaScript(`document.documentElement.style.setProperty('--fs','${fs2.toFixed(2)}px')`)
  }

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

  const pdfBuffer = await printWin.webContents.printToPDF(L.printOpts)
  printWin.destroy()
  fs.writeFileSync(filePath, pdfBuffer)
  recordPdfExport(filePath)
  return { ok: true, filePath }
})

ipcMain.handle('open-sales-csv-dialog', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    filters: [{ name: 'CSV', extensions: ['csv'] }],
    properties: ['openFile']
  })
  return canceled ? null : filePaths[0]
})

ipcMain.handle('build-sales-detail-db', (_, { csvPath }) =>
  spawnPy([BUILD_SALES_DETAIL, csvPath, salesDetailDb()], null)
)

ipcMain.handle('get-sales-detail-meta', () =>
  spawnPy([BUILD_SALES_DETAIL, 'meta', salesDetailDb()], null)
)

ipcMain.handle('build-sales-forecast-db', () =>
  spawnPy([BUILD_SALES_FORECAST, salesDetailDb(), salesForecastDb()], null)
)

ipcMain.handle('get-sales-forecast-meta', () =>
  spawnPy([BUILD_SALES_FORECAST, 'meta', salesForecastDb()], null)
)

ipcMain.handle('get-forecast-by-weekday', (_, { weekday }) =>
  spawnPy([BUILD_SALES_FORECAST, 'query', salesForecastDb(), String(weekday)], null)
)

ipcMain.handle('init-buffer-db',        ()       => spawnPy([BUFFER_STOCK, 'init',    dataDb()], null))
ipcMain.handle('get-buffer-settings',   ()       => spawnPy([BUFFER_STOCK, 'get',     dataDb()], null))
ipcMain.handle('set-buffer-qty',        (_, rows) => spawnPy([BUFFER_STOCK, 'set',    dataDb()], rows))
ipcMain.handle('calc-buffer-suggestions',()      => spawnPy([BUFFER_STOCK, 'suggest',     dataDb(), salesDetailDb(), String(settings.bufLeadDays || 1), String(settings.bufSembreakFactor || 0.5), String(settings.bufMinOos ?? 2)], null))
ipcMain.handle('load-buffer-suggestions',()      => spawnPy([BUFFER_STOCK, 'get_suggest',    dataDb()], null))
ipcMain.handle('get-lane-types',         ()      => spawnPy([BUFFER_STOCK, 'get_lane_types', dataDb()], null))
ipcMain.handle('get-replacement-data',   (_, machine) => spawnPy([REPL_SUGGEST, salesDetailDb(), settings.smProductPath || '', machine], null))
ipcMain.handle('get-machine-sales', (_, { machine, days }) => spawnPy([MACHINE_SALES, salesDetailDb(), machine, String(days)], null))

ipcMain.handle('get-report-mtime', () => {
  try { return fs.statSync(lastReport()).mtime.toISOString() } catch { return null }
})

ipcMain.handle('save-pick-edit', (_, { machine, date, rows }) => {
  const safe = machine.replace(/[^a-zA-Z0-9]/g, '_')
  const fpath = path.join(dataDir(), `pick_edit_${safe}_${date}.json`)
  fs.writeFileSync(fpath, JSON.stringify({ machine, date, rows }, null, 2))
})

ipcMain.handle('load-pick-edit', (_, { machine, date }) => {
  const safe = machine.replace(/[^a-zA-Z0-9]/g, '_')
  const fpath = path.join(dataDir(), `pick_edit_${safe}_${date}.json`)
  if (!fs.existsSync(fpath)) return null
  try { return { ...JSON.parse(fs.readFileSync(fpath, 'utf8')), _mtime: fs.statSync(fpath).mtime.toISOString() } } catch { return null }
})


