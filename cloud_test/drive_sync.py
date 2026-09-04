"""Google Drive access for seed distribution — stdlib only, no pip installs.

The Drive API is plain HTTPS + JSON, so this needs nothing added to the app's
bundled python. Scope is drive.file: this app can only ever see files it
created itself, never the rest of the user's Drive.

  python cloud_test/drive_sync.py auth            one-time consent, saves token.json
  python cloud_test/drive_sync.py init            create the "open vending db" folder
  python cloud_test/drive_sync.py push <file>     upload (resumable, replaces by name)
  python cloud_test/drive_sync.py list            what's in the folder
  python cloud_test/drive_sync.py pull <name> <dest>

Needs client_secret.json (OAuth client ID, type "Desktop app") beside this file.
token.json and client_secret.json are gitignored — never commit them.
"""
import http.server
import json
import mimetypes
import os
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

HERE     = Path(__file__).resolve().parent
SECRET   = HERE / "client_secret.json"
TOKEN    = HERE / "token.json"
STATE    = HERE / "drive_state.json"
FOLDER   = "open vending db"
SCOPE    = "https://www.googleapis.com/auth/drive.file"
PORT     = 8765
REDIRECT = "http://localhost:{}".format(PORT)
API      = "https://www.googleapis.com/drive/v3"
UPLOAD   = "https://www.googleapis.com/upload/drive/v3"
CHUNK    = 8 * 1024 * 1024


def _req(url, data=None, headers=None, method=None):
    r = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _form(url, fields):
    body = urllib.parse.urlencode(fields).encode()
    status, _, raw = _req(url, body,
                          {"Content-Type": "application/x-www-form-urlencoded"})
    if status != 200:
        sys.exit("token endpoint {}: {}".format(status, raw.decode()[:400]))
    return json.loads(raw)


def _client():
    if not SECRET.exists():
        sys.exit("missing {}\nCreate an OAuth client ID (Desktop app) in Google "
                 "Cloud Console, enable the Drive API, download the JSON here."
                 .format(SECRET))
    blob = json.loads(SECRET.read_text())
    cfg = blob.get("installed") or blob.get("web") or blob
    return cfg["client_id"], cfg["client_secret"]


# ── auth ──────────────────────────────────────────────────────────────────────

def auth():
    cid, csec = _client()
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            ok = "code" in got
            self.wfile.write(
                b"<h3>Done - close this tab and return to the terminal.</h3>"
                if ok else b"<h3>No code returned. Check the console output.</h3>")

        def log_message(self, *a):
            pass

    try:
        srv = http.server.HTTPServer(("localhost", PORT), Handler)
    except socket.error as e:
        sys.exit("port {} busy: {}".format(PORT, e))

    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": REDIRECT, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent"})
    print("Opening the consent screen. Approve access, then come back.\n" + url)
    threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    srv.handle_request()
    srv.server_close()

    if "code" not in got:
        sys.exit("no authorization code: {}".format(got))
    tok = _form("https://oauth2.googleapis.com/token", {
        "code": got["code"], "client_id": cid, "client_secret": csec,
        "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
    if "refresh_token" not in tok:
        sys.exit("no refresh_token returned — revoke the app at "
                 "myaccount.google.com/permissions and run auth again")
    TOKEN.write_text(json.dumps(tok, indent=2))
    os.chmod(TOKEN, 0o600)
    print("saved {}".format(TOKEN))


def access_token():
    if not TOKEN.exists():
        sys.exit("not authorised yet — run: python cloud_test/drive_sync.py auth")
    cid, csec = _client()
    tok = json.loads(TOKEN.read_text())
    fresh = _form("https://oauth2.googleapis.com/token", {
        "client_id": cid, "client_secret": csec,
        "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    return fresh["access_token"]


def _auth_headers(extra=None):
    h = {"Authorization": "Bearer " + access_token()}
    h.update(extra or {})
    return h


# ── folder ────────────────────────────────────────────────────────────────────

def _saved_folder():
    if STATE.exists():
        return json.loads(STATE.read_text()).get("folder_id")
    return None


def init():
    """Create the folder. drive.file scope cannot see folders made in the web UI,
    so the app must own the one it uses."""
    existing = _saved_folder()
    if existing:
        print("already initialised: {}".format(existing))
        return existing
    body = json.dumps({"name": FOLDER,
                       "mimeType": "application/vnd.google-apps.folder"}).encode()
    status, _, raw = _req(API + "/files",
                          body, _auth_headers({"Content-Type": "application/json"}))
    if status not in (200, 201):
        sys.exit("create folder {}: {}".format(status, raw.decode()[:400]))
    fid = json.loads(raw)["id"]
    STATE.write_text(json.dumps({"folder_id": fid, "name": FOLDER}, indent=2))
    print("created folder {} -> {}".format(FOLDER, fid))
    print("https://drive.google.com/drive/folders/" + fid)
    return fid


def _folder_id():
    return _saved_folder() or sys.exit(
        "no folder yet — run: python cloud_test/drive_sync.py init")


def _find(name):
    q = "name='{}' and '{}' in parents and trashed=false".format(name, _folder_id())
    url = API + "/files?" + urllib.parse.urlencode(
        {"q": q, "fields": "files(id,name,size,modifiedTime)"})
    status, _, raw = _req(url, headers=_auth_headers())
    if status != 200:
        sys.exit("list {}: {}".format(status, raw.decode()[:400]))
    return json.loads(raw).get("files", [])


# ── push / pull / list ────────────────────────────────────────────────────────

def push(path):
    src = Path(path).resolve()
    if not src.exists():
        sys.exit("no such file: {}".format(src))
    size = src.stat().st_size
    hits = _find(src.name)
    mime = mimetypes.guess_type(src.name)[0] or "application/octet-stream"

    if hits:
        fid = hits[0]["id"]
        start = _req("{}/files/{}?uploadType=resumable".format(UPLOAD, fid),
                     json.dumps({}).encode(),
                     _auth_headers({"Content-Type": "application/json",
                                    "X-Upload-Content-Type": mime,
                                    "X-Upload-Content-Length": str(size)}),
                     method="PATCH")
        print("replacing existing {} ({})".format(src.name, fid))
    else:
        meta = json.dumps({"name": src.name, "parents": [_folder_id()]}).encode()
        start = _req(UPLOAD + "/files?uploadType=resumable", meta,
                     _auth_headers({"Content-Type": "application/json",
                                    "X-Upload-Content-Type": mime,
                                    "X-Upload-Content-Length": str(size)}))
        print("uploading new {}".format(src.name))

    status, headers, raw = start
    if status != 200:
        sys.exit("resumable start {}: {}".format(status, raw.decode()[:400]))
    session = headers.get("Location") or headers.get("location")

    sent = 0
    with open(src, "rb") as f:
        while sent < size:
            chunk = f.read(CHUNK)
            end = sent + len(chunk) - 1
            st, _, body = _req(session, chunk, {
                "Content-Length": str(len(chunk)),
                "Content-Range": "bytes {}-{}/{}".format(sent, end, size)},
                method="PUT")
            if st not in (200, 201, 308):
                sys.exit("chunk {}-{} failed {}: {}".format(
                    sent, end, st, body.decode()[:400]))
            sent += len(chunk)
            print("  {:>6.1f} MB / {:.1f} MB".format(sent / 1048576, size / 1048576))
            if st in (200, 201):
                print("uploaded: " + json.loads(body)["id"])
                return


def pull(name, dest):
    hits = _find(name)
    if not hits:
        sys.exit("not in the folder: {}".format(name))
    fid = hits[0]["id"]
    req = urllib.request.Request(
        "{}/files/{}?alt=media".format(API, fid), headers=_auth_headers())
    out = Path(dest).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req) as resp, open(out, "wb") as f:
        got = 0
        while True:
            block = resp.read(CHUNK)
            if not block:
                break
            f.write(block)
            got += len(block)
            print("  {:>6.1f} MB".format(got / 1048576))
    print("saved {} ({:.1f} MB)".format(out, out.stat().st_size / 1048576))


def share(name):
    """Make one file readable by anyone with the link, and print the direct
    download URL. Used for the seed so a new PC needs no Google auth at all."""
    hits = _find(name)
    if not hits:
        sys.exit("not in the folder: {}".format(name))
    fid = hits[0]["id"]
    body = json.dumps({"role": "reader", "type": "anyone"}).encode()
    status, _, raw = _req(
        "{}/files/{}/permissions".format(API, fid), body,
        _auth_headers({"Content-Type": "application/json"}))
    if status not in (200, 201):
        sys.exit("share {}: {}".format(status, raw.decode()[:400]))
    # The uc?export endpoint interstitials on files >25MB; this one streams.
    url = ("https://drive.usercontent.google.com/download"
           "?id={}&export=download&confirm=t".format(fid))
    # Cached so the installer generator needs no Google auth at all.
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state.setdefault("public", {})[name] = url
    STATE.write_text(json.dumps(state, indent=2))
    print("shared: anyone with the link can read {}".format(name))
    print(url)
    return url


def unshare(name):
    """Revoke the public link (leaves the file in place)."""
    hits = _find(name)
    if not hits:
        sys.exit("not in the folder: {}".format(name))
    fid = hits[0]["id"]
    status, _, raw = _req("{}/files/{}/permissions".format(API, fid),
                          headers=_auth_headers())
    if status != 200:
        sys.exit("list permissions {}: {}".format(status, raw.decode()[:200]))
    removed = 0
    for p in json.loads(raw).get("permissions", []):
        if p.get("type") == "anyone":
            _req("{}/files/{}/permissions/{}".format(API, fid, p["id"]),
                 headers=_auth_headers(), method="DELETE")
            removed += 1
    print("revoked {} public link(s) on {}".format(removed, name))


def ls():
    url = API + "/files?" + urllib.parse.urlencode({
        "q": "'{}' in parents and trashed=false".format(_folder_id()),
        "fields": "files(id,name,size,modifiedTime)"})
    status, _, raw = _req(url, headers=_auth_headers())
    if status != 200:
        sys.exit("list {}: {}".format(status, raw.decode()[:400]))
    files = json.loads(raw).get("files", [])
    if not files:
        print("(folder is empty)")
    for f in files:
        mbs = int(f.get("size", 0)) / 1048576
        print("{:32} {:>8.1f} MB  {}  {}".format(
            f["name"], mbs, f["modifiedTime"], f["id"]))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "auth":
        auth()
    elif cmd == "init":
        init()
    elif cmd == "push":
        push(a[1])
    elif cmd == "pull":
        pull(a[1], a[2])
    elif cmd == "list":
        ls()
    elif cmd == "share":
        share(a[1] if len(a) > 1 else "seed.db.gz")
    elif cmd == "unshare":
        unshare(a[1] if len(a) > 1 else "seed.db.gz")
    else:
        sys.exit("unknown: {}".format(cmd))
