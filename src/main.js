const { app, BrowserWindow, ipcMain, safeStorage, Tray, Menu, globalShortcut, Notification } = require('electron')
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
    return { status: semverGt(pkg.version, LOCAL_VERSION) ? 'available' : 'up-to-date' }
  } catch {
    return { status: 'error' }
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
    fs.writeFileSync(updaterPs1, `
$pid_  = ${process.pid}
$zip   = '${zipPath.replace(/\\/g, '\\\\')}'
$tmp   = '${tmpDir.replace(/\\/g, '\\\\')}'
$app   = '${ROOT.replace(/\\/g, '\\\\')}'
$vbs   = '${path.join(ROOT, 'run.vbs').replace(/\\/g, '\\\\')}'

while (Get-Process -Id $pid_ -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 300 }

Expand-Archive -Path $zip -DestinationPath "$tmp\\extracted" -Force
$src = (Get-ChildItem "$tmp\\extracted" | Select-Object -First 1).FullName
$excl = @(${excludeList})
Get-ChildItem $src | Where-Object { $_.Name -notin $excl } | ForEach-Object {
  Copy-Item $_.FullName (Join-Path $app $_.Name) -Recurse -Force
}
Start-Process 'wscript.exe' -ArgumentList $vbs
`)

    spawn('powershell.exe',
      ['-NoProfile', '-WindowStyle', 'Hidden', '-File', updaterPs1],
      { detached: true, stdio: 'ignore' }
    ).unref()

    app.quit()
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
        win.webContents.send('diff-ready', lastDiffs.length)
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
  tray.setToolTip('Open Vending')
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
        if (lastDiffs.length) win.webContents.send('diff-ready', lastDiffs.length)
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

ipcMain.handle('get-settings', () => settings)
ipcMain.handle('get-diffs',   () => lastDiffs)

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

const QUERY_HISTORY = path.join(__dirname, 'query_history.py')
const PICKING_HISTORY = path.join(__dirname, 'picking_history.py')
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
