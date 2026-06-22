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
| <img src="asset/button img/shopping_basket.png" width="24"> | **Picking List** | Daily restock plan by machine — see [Picking List](#picking-list) below |
| <img src="asset/button img/settings.png" width="24"> | **Settings** | Configure app preferences |
| <img src="asset/button img/update.png" width="24"> | **Update** | Grayed out while up to date — lights up when a newer version is available. Click to update (see [Auto-update](#auto-update) below) |

### Settings

| Option | Description |
|--------|-------------|
| Show Menu Bar | Display the Electron application menu bar |
| Show Console Window | Show the DOS console during data download |
| Close to System Tray | Clicking × minimizes to tray instead of quitting |
| Notify on Restock Changes | System tray notification when restock values change after a scan |
| Headed Browser | Run a visible browser during scan (press **F9** to capture the current page) |

---

## Picking List

Open the Picking List from the side panel (<img src="asset/button img/shopping_basket.png" width="16"> **Picking List**).

### Machine list (left panel)

The left panel lists every machine that needs restocking today. Each machine shows a badge with the fill percentage — the proportion of items that need to be refilled relative to the machine's total lane capacity. Click a machine to load its item breakdown in the main panel.

### Item detail (main panel)

The main panel shows every lane in the selected machine along with product name, current balance, lane size, and restock quantity. Rows highlighted in red indicate out-of-stock lanes. Click any row to open a **Restock History** chart for that product.

The toolbar above the detail panel has two buttons:

| Icon | Function |
|------|----------|
| <img src="asset/button img/pending_actions.png" width="20"> | Open the **In-Transit Queue** modal |
| <img src="asset/button img/picture_as_pdf.png" width="20"> | Export all queued picking lists as PDF |

### Adding to the queue

Click <img src="asset/button img/check_box.png" width="16"> in the top-right corner of the detail panel to add the machine to the queue. The icon turns **green** once the machine is queued. Click <img src="asset/button img/home.png" width="16"> on the left to go back to the machine list without selecting a machine.

### In-Transit Queue modal

Click <img src="asset/button img/pending_actions.png" width="16"> in the toolbar to open the queue modal. Each queued machine shows the total units and lane count. From here you can:

| Icon | Function |
|------|----------|
| <img src="asset/button img/edit.png" width="16"> | Open that machine in **Edit mode** |
| <img src="asset/button img/delete.png" width="16"> | Remove that machine from the queue |
| <img src="asset/button img/refresh.png" width="16"> | Reload all queued entries from the latest report data |
| <img src="asset/button img/delete_forever.png" width="16"> | Clear the entire queue |

### Edit mode

Click <img src="asset/button img/edit.png" width="16"> on any queued machine to open it in Edit mode. An **"Edit mode"** banner appears at the top of the detail panel and all table cells become editable. Changes are auto-saved as you type and stored in the `db/` folder — edits do not affect the original report. Click <img src="asset/button img/save.png" width="16"> in the top-right corner to exit Edit mode.

---

## Auto-update

On every launch, the app checks the remote `package.json` for a newer version. The <img src="asset/button img/update.png" width="16"> icon in the side panel is grayed out while the app is up to date. When a newer version is detected, the icon lights up.

Click the icon to start the update:

1. The app downloads the latest release as a zip file.
2. A background PowerShell script is launched, then the app exits.
3. The script waits for the app to fully close, extracts the zip, and copies the updated files (preserving `node_modules/`, `python/`, `db/`, and other local data).
4. The app relaunches automatically via `run.vbs`.
