# Open Vending

DVends replenishment report automation tool.

## Installation

### Step 1 — Download

Download or clone this repository to your computer.

### Step 2 — Run setup

Double-click **`setup.bat`**.

This will automatically download and install all dependencies (Python, Chromium, Node.js, Electron). An internet connection is required. Allow 5–10 minutes on first run.

When you see **"Setup complete! Run run.bat to start."**, setup is done.

### Step 3 — Launch

Double-click **`run.vbs`** to start the app with no console window.

On first launch, the app will prompt for your DVends username and password. Credentials are stored encrypted on your machine.

> `run.bat` is also available but briefly flashes a black window — this is a Windows limitation of `.bat` files.

---

## Usage

The app opens automatically, downloads the latest replenishment report, and displays it in the main panel.

Click **Re-download** in the side panel to refresh the data.

## Folder structure

```
Open_Vending/
├── src/              UI source files (Electron)
├── open_vending.py   Download automation script
├── setup.bat         First-time setup
├── run.bat           Launch the app
└── requirements.txt  Python dependencies
```
