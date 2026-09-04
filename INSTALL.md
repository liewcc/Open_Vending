# Installing Open Vending — step by step

A complete walkthrough for someone installing this on a new PC for the first
time. If you have done it before, the three-step version in the
[README](README.md#installation) is all you need.

---

## 0. Before you start

| You need | Notes |
|---|---|
| **Windows 10 or 11, 64-bit** | Windows only. The launcher, the setup script and the encrypted credential store all use Windows-specific features. There is no macOS or Linux build. |
| **An internet connection** | Setup downloads about 500 MB. |
| **About 2 GB free disk space** | Roughly 600 MB stays after install. |
| **Your DVends portal username and password** | The app signs in as you to download your replenishment report. |

You do **not** need to install Python, Node.js or a browser first. Setup
downloads its own private copies into the project folder. Nothing is installed
system-wide, no administrator rights are needed, and deleting the folder removes
everything.

---

## 1. Pick a folder — this one matters

Put the project somewhere plain that you own, for example:

```
C:\Apps\Open_Vending
```

**Do not put it inside OneDrive, Google Drive or Dropbox.** This includes your
Desktop and Documents folders if OneDrive Backup is switched on — check whether
their path contains `OneDrive` before you extract anything there. The app keeps
its data in a live SQLite database, and a sync client copying that file while the
app is running will corrupt it. See [DATABASE.md](DATABASE.md) for the full rule.

Also avoid network drives and USB sticks — the app runs its own Chromium and
Electron from this folder and expects local disk speed.

---

## 2. Get the files

### Option A — Git (recommended)

If you have [Git](https://git-scm.com/download/win) installed, open PowerShell
and run:

```bash
git clone https://github.com/liewcc/Open_Vending.git C:\Apps\Open_Vending
```

Updating later is then one command (see [section 6](#6-updating-later)).

### Option B — Download the ZIP

1. Open <https://github.com/liewcc/Open_Vending>.
2. Click the green **Code** button, then **Download ZIP**.
3. Right-click the downloaded zip, choose **Properties**, tick **Unblock**, OK.
   Windows marks files from the internet as blocked, which makes the scripts
   inside fail silently.
4. Right-click the zip, choose **Extract All…**, and extract to
   `C:\Apps\Open_Vending`.

**Check what you got.** The folder must contain `setup.bat`, `run.vbs`,
`package.json` and a `src\` folder *directly*. If instead it contains a single
folder called `Open_Vending-main`, use that inner folder as your project folder.

---

## 3. Run setup

Double-click **`setup.bat`**. A black console window opens and stays open.

If Windows shows *"Windows protected your PC"*, click **More info**, then
**Run anyway**. Your antivirus may also ask; the script only downloads from
python.org, nodejs.org, pypi.org and Google's font server.

It works through seven steps, printing each one:

| Step | What it downloads |
|---|---|
| 1–3 | Python 3.12 (embedded), pip, and the `playwright` + `openpyxl` packages |
| 4 | Chromium browser — about 150 MB, the slowest step |
| 5–6 | Node.js 20 and the Electron + xlsx packages — about 100 MB |
| 7 | The Material Symbols icon font |

Expect **5–10 minutes** on a normal connection. You are done when you see:

```
 ============================================
  Setup complete! Run run.bat to start.
 ============================================
```

Press any key to close the window. An **Open Vending** shortcut now sits on your
Desktop.

**If it stops with `[ERROR]`:** just run `setup.bat` again. Every step skips
whatever already downloaded successfully, so a re-run only retries what failed.
The full detail of the failure is in `setup.log` in the project folder.

---

## 4. First launch

Double-click the **Open Vending** shortcut on your Desktop (or `run.vbs` inside
the project folder — both do the same thing).

1. A **Welcome to Open Vending** box asks for your DVends username and password.
   Enter them and click **Save & Connect**.
   They are encrypted with Windows DPAPI and stored in
   `%APPDATA%\open-vending\credentials.enc`. That file is tied to this Windows
   user on this PC — copying it to another machine will not work, so every PC
   needs its login entered once.
2. The app signs in to the portal and downloads today's replenishment report.
   The first scan takes a few minutes. Watch the status line at the bottom.
3. When the scan finishes the main table fills in, and `db\vending.db` is created
   in the project folder.

---

## 5. Set up your route plan

A fresh clone ships with an **example** `db\route_plan.json` that lists someone
else's machines, so the Picking List will not match your account until you fix
this. Do it once, right after the first scan:

1. Click the **route** icon in the left side panel to open **Route Plan**.
2. Delete the rows that are not your machines.
3. Click **Add from report** (the *playlist_add* icon) — it adds every machine
   that appeared in your own report and is missing from the plan.
4. Set the team, days and mode for each machine, then press **Save**.

Open the **Picking List** afterwards; it should now list your machines.

### Install is done — a quick check

- [ ] `db\vending.db` exists in the project folder
- [ ] The main table shows rows
- [ ] The Picking List lists your machines

---

## 6. Updating later

Pick one lane and stick to it:

- **Cloned with Git** — run `git pull` in the project folder, then run
  `setup.bat` again (it takes seconds when nothing new is needed). Your `db\`,
  `python\`, `node\`, `browsers\` and `node_modules\` folders are untracked, so
  nothing local is touched.
- **Downloaded the ZIP** — use the in-app **Update** button in the side panel.
  It lights up when a newer version exists, downloads it, and restarts the app,
  preserving `node_modules\`, `python\` and `db\`.

The in-app Update button also works on a Git clone, but it overwrites tracked
files, so `git status` will show modified files afterwards.

---

## 7. When something goes wrong

| Symptom | What to do |
|---|---|
| Double-clicking `setup.bat` does nothing | The file is blocked. Right-click, Properties, **Unblock**. Or open PowerShell in the folder and run `.\setup.bat`. |
| `[ERROR] ... download failed` | Network or proxy problem. Check the last lines of `setup.log`, then run `setup.bat` again. |
| Message box: *"Setup not complete. Please run setup.bat first."* | `setup.bat` never finished (usually step 6). Run it again and read `setup.log`. |
| No Desktop shortcut | Harmless — launch `run.vbs` in the project folder instead. |
| App opens but the table stays empty, log says *no credentials* | Open **Settings**, then the **Accounts** card, edit the account and re-enter the password. |
| Scan stops at *"Exporting Excel…"* | The portal failed to build the export. Look at `log\scan.log` and the saved page in `log\export_fail.html` / `.png`, then press **Re-download**. |
| Scan fails and you cannot tell why | Turn on **Headed Browser** in Settings and re-run — you will see the portal as the app sees it, and **F9** saves the current page. |
| Everything is broken and you want a clean slate | Delete `python\`, `node\`, `browsers\` and `node_modules\`, then run `setup.bat` again. Your data in `db\` is untouched. |

Logs worth knowing: `setup.log` (install) and `log\scan.log` (every portal scan),
both in the project folder.

---

## 8. Next steps

- [README](README.md) — what every button does
- [DATABASE.md](DATABASE.md) — read this before touching the data directly, or
  before pointing an AI assistant at this folder
- Running this on more than one PC at the same time? See section 6 of
  [DATABASE.md](DATABASE.md) — the shared-database mode.
