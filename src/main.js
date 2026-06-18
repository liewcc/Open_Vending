const { app, BrowserWindow, ipcMain, safeStorage } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const fs   = require('fs')

const ROOT      = path.join(__dirname, '..')
const CRED_FILE = path.join(app.getPath('userData'), 'credentials.enc')
let win
let cachedCreds = null

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
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    },
    backgroundColor: '#f0f2f5'
  })
  win.loadFile(path.join(__dirname, 'index.html'))
}

// ── Download ──────────────────────────────────────────────────────────────────

function runDownload(creds) {
  const pythonExe = path.join(ROOT, 'python', 'python.exe')
  const script    = path.join(ROOT, 'open_vending.py')

  const proc = spawn(pythonExe, [script, '--headless'], {
    env: {
      ...process.env,
      PLAYWRIGHT_BROWSERS_PATH: path.join(ROOT, 'browsers'),
      PYTHONNOUSERSITE: '1',
      PYTHONPATH: '',
      OV_USERNAME: creds.username,
      OV_PASSWORD: creds.password
    }
  })

  proc.stdout.on('data', data => {
    data.toString().trim().split('\n').forEach(line => {
      line = line.trim()
      if (!line) return
      win.webContents.send('py-out', line)
      const m = line.match(/^FILE: (.+)$/)
      if (m) win.webContents.send('file-ready', m[1].trim())
    })
  })

  proc.stderr.on('data', data => {
    win.webContents.send('py-out', 'ERROR: ' + data.toString().trim())
  })

  proc.on('error', err => {
    win.webContents.send('py-out', 'ERROR: ' + err.message)
    win.webContents.send('py-done', false)
  })

  proc.on('close', code => {
    win.webContents.send('py-done', code === 0)
  })
}

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(() => {
  createWindow()
  win.webContents.once('did-finish-load', () => {
    cachedCreds = loadCredentials()
    if (cachedCreds) {
      runDownload(cachedCreds)
    } else {
      win.webContents.send('needs-credentials')
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

// ── IPC ───────────────────────────────────────────────────────────────────────

ipcMain.on('save-credentials', (_, { username, password }) => {
  saveCredentials(username, password)
  cachedCreds = { username, password }
  runDownload(cachedCreds)
})

ipcMain.on('start-download', () => {
  if (cachedCreds) runDownload(cachedCreds)
})
