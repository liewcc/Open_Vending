const { contextBridge, ipcRenderer } = require('electron')
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

  parseExcel(filePath) {
    const wb = xlsx.readFile(filePath)
    const ws = wb.Sheets[wb.SheetNames[0]]
    return xlsx.utils.sheet_to_json(ws, { header: 1, defval: '' })
  }
})
