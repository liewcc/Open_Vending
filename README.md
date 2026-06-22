# Open Vending

**English** | [简体中文](README.zh-CN.md)

<p align="center"><img src="asset/image/1.png" width="50%"></p>

## Installation

### Step 1 — Download

Download or clone this repository to your computer.

### Step 2 — Run setup

Double-click **`setup.bat`**.

This will automatically download and install all dependencies (Python, Chromium, Node.js, Electron). An internet connection is required. Allow 5–10 minutes on first run.

When you see **"Setup complete! Run run.bat to start."**, setup is done.

### Step 3 — Launch

Double-click the **Open Vending** shortcut on your Desktop (created by setup).

On first launch, the app will prompt for your DVends username and password. Credentials are stored encrypted on your machine.

> You can also launch via **`run.vbs`** in the project folder. `run.bat` works too but briefly flashes a black window — a Windows limitation of `.bat` files.

---

## Usage

On launch, the app automatically downloads the latest replenishment report from DVends and displays it in the main table.

### Side panel buttons

| Icon | Button | Description |
|------|--------|-------------|
| <img src="asset/button img/table_view.png" width="24"> | **Home** | Return to the main replenishment table |
| <img src="asset/button img/cloud_sync.png" width="24"> | **Re-download** | Fetch the latest report from DVends |
| <img src="asset/button img/track_changes.png" width="24"> | **Changing List** | Items whose restock values changed since the last scan |
| <img src="asset/button img/shopping_basket.png" width="24"> | **Picking List** | Items that need restocking — click any row to view its restock history chart |
| <img src="asset/button img/settings.png" width="24"> | **Settings** | Configure app preferences |
| <img src="asset/button img/update.png" width="24"> | **Check for Update** | Download and apply the latest version |

### Settings

| Option | Description |
|--------|-------------|
| Show Menu Bar | Display the Electron application menu bar |
| Show Console Window | Show the DOS console during data download |
| Close to System Tray | Clicking × minimizes to tray instead of quitting |
| Notify on Restock Changes | System tray notification when restock values change after a scan |
| Headed Browser | Run a visible browser during scan (press **F9** to capture the current page) |
