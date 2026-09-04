"""Load Turso credentials from tools/turso.json into the environment.

Keeps the token out of command lines, shell history and terminal output — the
scripts read the file themselves. turso.json is gitignored.

  {"url": "https://<db>-<org>.turso.io", "token": "<auth token>"}
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CREDS = ROOT / "turso.json"


def load(required=True):
    if not CREDS.exists():
        if required:
            sys.exit(
                "missing {}\n"
                'Create it with:  {{"url": "https://<db>-<org>.turso.io", '
                '"token": "<auth token>"}}'.format(CREDS))
        return False
    try:
        d = json.loads(CREDS.read_text(encoding="utf-8"))
    except Exception as e:
        sys.exit("{} is not valid JSON: {}".format(CREDS, e))
    url, token = (d.get("url") or "").strip(), (d.get("token") or "").strip()
    if not url or not token:
        sys.exit("{} needs both 'url' and 'token'".format(CREDS))
    os.environ["OV_REMOTE_URL"] = url
    os.environ["OV_REMOTE_TOKEN"] = token
    # src/ holds remote_db and the app scripts
    sys.path.insert(0, str(ROOT / "src"))
    return True


def describe():
    """Safe to print — host only, never the token."""
    url = os.environ.get("OV_REMOTE_URL", "")
    return url.split("//")[-1] if url else "(not configured)"
