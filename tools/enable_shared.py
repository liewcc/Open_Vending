"""Point this PC's app at the shared hosted DB (or back to local).

Copies the url/token from tools/turso.json into the app's settings.json,
so the token is never typed on a command line or left in shell history.

  python tools/enable_shared.py            turn the shared DB on
  python tools/enable_shared.py --status   show which DB the app will use
  python tools/enable_shared.py --disable  go back to the local file
  python tools/enable_shared.py --code     apply a setup code (reads stdin)

--code exists because the welcome box only appears on a PC's very first run.
An install that joined the shared DB some other way has the url and token but
no profile catalogue, so adding a profile there would find no data to restore.
Pipe the code in:  Get-Clipboard | python tools/enable_shared.py --code

Restart the app afterwards — main.js reads settings only at startup.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TURSO = ROOT / "turso.json"
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


def apply_code(raw):
    """Decode a setup code into settings: shared DB credentials plus the
    catalogue that tells a restored profile which data is its own."""
    import base64
    code = "".join(raw.split())        # codes arrive wrapped by whatever carried them
    if not code:
        sys.exit("no setup code given — pipe it in, or pass it after --code")
    try:
        cfg = json.loads(base64.urlsafe_b64decode(code))
    except Exception as e:
        sys.exit("that does not decode as a setup code: {}".format(e))
    if not cfg.get("remoteUrl") or not cfg.get("remoteToken"):
        sys.exit("no shared database in that code")

    d = load_settings()
    d["remoteUrl"] = cfg["remoteUrl"]
    d["remoteToken"] = cfg["remoteToken"]
    profiles = cfg.get("profiles") or {}
    d["seedProfiles"] = profiles
    save_settings(d)

    print("shared DB on — {}".format(cfg["remoteUrl"].split("//")[-1]))
    if profiles:
        print("profiles this PC can now restore:")
        for v in profiles.values():
            print("  {:8} id={}".format(v.get("label", "?"), v.get("id", "?")))
    else:
        print("WARNING: that code carries no profile catalogue — regenerate it "
              "with setup_code.bat on the source PC")


def main():
    if "--status" in sys.argv:
        return status()

    if "--code" in sys.argv:
        i = sys.argv.index("--code")
        inline = " ".join(sys.argv[i + 1:]).strip()
        return apply_code(inline or sys.stdin.read())

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
