"""Point this PC's app at the shared hosted DB (or back to local).

Copies the url/token from cloud_test/turso.json into the app's settings.json,
so the token is never typed on a command line or left in shell history.

  python cloud_test/enable_shared.py            turn the shared DB on
  python cloud_test/enable_shared.py --status   show which DB the app will use
  python cloud_test/enable_shared.py --disable  go back to the local file

Restart the app afterwards — main.js reads settings only at startup.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TURSO = HERE / "turso.json"
SETTINGS = Path(os.environ.get("APPDATA", "")) / "open-vending" / "settings.json"


def load_settings():
    if SETTINGS.exists():
        try:
            return json.loads(SETTINGS.read_text(encoding="utf-8"))
        except Exception:
            print("warning: settings.json was unreadable, starting fresh")
    return {}


def save_settings(d):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(d), encoding="utf-8")


def status():
    d = load_settings()
    u, t = d.get("remoteUrl", ""), d.get("remoteToken", "")
    print("settings: {}".format(SETTINGS))
    print("remoteUrl  : {}".format(u or "(empty)"))
    print("remoteToken: {}".format("set, length {}".format(len(t)) if t else "(empty)"))
    print("\napp will use: {}".format(
        "SHARED hosted DB" if (u and t) else "LOCAL db/vending.db"))


def main():
    if "--status" in sys.argv:
        return status()

    d = load_settings()
    if "--disable" in sys.argv:
        d["remoteUrl"] = ""
        d["remoteToken"] = ""
        save_settings(d)
        print("shared DB off — picks and buffers go back to the local file.")
    else:
        if not TURSO.exists():
            sys.exit("missing {} — the Turso url and token".format(TURSO))
        c = json.loads(TURSO.read_text(encoding="utf-8"))
        if not c.get("url") or not c.get("token"):
            sys.exit("{} needs both 'url' and 'token'".format(TURSO))
        d["remoteUrl"] = c["url"]
        d["remoteToken"] = c["token"]
        save_settings(d)
        print("shared DB on — {}".format(c["url"].split("//")[-1]))
    print("\nRestart the app for this to take effect.")
    print("Settings are per Windows user, shared by every install on this PC.")


if __name__ == "__main__":
    main()
