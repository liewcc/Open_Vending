const { contextBridge, ipcRenderer, shell } = require('electron')
const path = require('path')
const xlsx = require(path.join(__dirname, '..', 'node_modules', 'xlsx'))

contextBridge.exposeInMainWorld('api', {
  onLog:              cb => ipcRenderer.on('py-out',            (_, m)  => cb(m)),
  onDone:             cb => ipcRenderer.on('py-done',           (_, ok) => cb(ok)),
  onFileReady:        cb => ipcRenderer.on('file-ready',        (_, p)  => cb(p)),
  onNeedsCredentials: cb => ipcRenderer.on('needs-credentials', ()      => cb()),
  startDownload:      ()           => ipcRenderer.send('start-download'),
  saveCredentials:    (u, p)       => ipcRenderer.send('save-credentials', { username: u, password: p }),
  doUpdate:           ()           => ipcRenderer.send('do-update'),
  onUpdateStatus:     cb => ipcRenderer.on('update-status',   (_, d) => cb(d)),
  onUpdateProgress:   cb => ipcRenderer.on('update-progress', (_, s) => cb(s)),
  openExternal:       url          => shell.openExternal(url),
  getSettings:        ()           => ipcRenderer.invoke('get-settings'),
  setSetting:         (key, val)   => ipcRenderer.send('set-setting', { key, val }),
  onDiffReady:        cb => ipcRenderer.on('diff-ready',        (_, count) => cb(count)),
  onDownloadStarted:  cb => ipcRenderer.on('download-started',  ()         => cb()),
  getDiffs:           ()           => ipcRenderer.invoke('get-diffs'),
  launchBrowser:        ()               => ipcRenderer.send('launch-browser'),
  closeBrowser:         ()               => ipcRenderer.send('close-browser'),
  onBrowserState:       cb => ipcRenderer.on('browser-state', (_, state) => cb(state)),
  getRestockHistory:    (machine, lane)  => ipcRenderer.invoke('get-restock-history', { machine, lane }),

  parseExcel(filePath) {
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
})
