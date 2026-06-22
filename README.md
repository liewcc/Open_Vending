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
| <img src="asset/button img/update.png" width="24"> | **Check for Update** | Download and apply the latest version |

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

### Adding to the queue

Click the queue icon (<img src="asset/button img/update.png" width="16">) in the top-right corner of the detail panel to add the machine to the print queue. The icon turns **green** once the machine is queued. Green icons across the machine list give a quick visual of which machines have already been queued.

### Queue modal

Click the queue icon in the **toolbar** (top-left of the picking panel) to open the queue modal. From here you can:

- **Reload** — refresh all queued entries to reflect the latest report data
- **Edit** (pencil icon beside each entry) — open that machine's picking list in **Edit mode**, where you can adjust any value directly in the table. Changes are auto-saved as you type and stored in the `db/` folder. Edits do not affect the original report.
- **Delete** (trash icon beside each entry) — remove a single machine from the queue
- **Delete All** — clear the entire queue

### Edit mode

When a machine is opened in Edit mode, an **"Edit mode"** banner appears at the top of the detail panel. All table cells become editable. Click the save icon in the top-right corner to exit Edit mode and return to the normal picking view.
