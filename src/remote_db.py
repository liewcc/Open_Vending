"""Shared-table access over libSQL/Turso's HTTP API — stdlib only.

picking_history and buffer_stock live in one hosted DB so the office PC and the
transit laptop write the same rows instead of fighting over a synced file.
Everything else stays in the local vending.db.

Enabled by two env vars, injected by main.js alongside OV_DATA_DIR:
  OV_REMOTE_URL    https://<db>-<org>.turso.io   (libsql:// is accepted too)
  OV_REMOTE_TOKEN  auth token

With neither set, connect() hands back a plain sqlite3 connection to the local
file, so single-PC installs behave exactly as before and this module is inert.

The adapter mimics just enough of sqlite3: execute/executemany/commit/close,
cursors with .fetchall()/.rowcount, and rows that support both r['col'] and
tuple unpacking — so existing SQL and control flow are unchanged at call sites.
Writes are queued and flushed as one transaction on commit(); reads round-trip
immediately.
"""
import json
import os
import sqlite3
import ssl
import subprocess
import urllib.error
import urllib.request


class RemoteError(RuntimeError):
    """Remote is unreachable or rejected the statement. Never swallow this —
    under the no-offline-writes design the user must be told the save failed."""


def enabled():
    return bool(os.environ.get("OV_REMOTE_URL") and os.environ.get("OV_REMOTE_TOKEN"))


def _endpoint():
    url = os.environ["OV_REMOTE_URL"].strip().rstrip("/")
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    return url + "/v2/pipeline"


def _encode(v):
    if v is None:
        return {"type": "null", "value": None}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        import base64
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    return {"type": "text", "value": str(v)}


def _decode(cell):
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return float(cell["value"])
    if t == "blob":
        import base64
        return base64.b64decode(cell.get("base64", ""))
    return cell.get("value")


def _stmt(sql, params):
    s = {"sql": sql}
    if params:
        if isinstance(params, dict):
            s["named_args"] = [{"name": k, "value": _encode(v)} for k, v in params.items()]
        else:
            s["args"] = [_encode(v) for v in params]
    return s


def _warm_cert_store():
    """Python trusts only the roots Windows has already cached, and Windows
    fetches missing ones on demand. A native request (curl.exe uses Schannel)
    makes Windows cache the root so Python's next verify succeeds — otherwise a
    fresh PC fails with an opaque CERTIFICATE_VERIFY_FAILED. Best effort."""
    if os.name != "nt":
        return False
    try:
        subprocess.run(
            ["curl.exe", "-s", "-o", os.devnull, "--max-time", "15",
             _endpoint().split("/v2/")[0]],
            capture_output=True, timeout=20, creationflags=0x08000000)
        return True
    except Exception:
        return False


def _send(body):
    req = urllib.request.Request(_endpoint(), data=body, headers={
        "Authorization": "Bearer " + os.environ["OV_REMOTE_TOKEN"],
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _pipeline(stmts):
    """Send statements in order on one server-side connection."""
    body = json.dumps({
        "requests": [{"type": "execute", "stmt": s} for s in stmts] + [{"type": "close"}]
    }).encode()
    try:
        payload = _send(body)
    except urllib.error.HTTPError as e:
        raise RemoteError("remote rejected the request ({}): {}".format(
            e.code, e.read().decode()[:200]))
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError) \
                and _warm_cert_store():
            try:
                payload = _send(body)
            except Exception as e2:
                raise RemoteError("cannot reach the shared database: {}".format(e2))
        else:
            raise RemoteError("cannot reach the shared database: {}".format(e))
    except Exception as e:
        raise RemoteError("cannot reach the shared database: {}".format(e))

    out = []
    for r in payload.get("results", []):
        if r.get("type") == "error":
            raise RemoteError(r.get("error", {}).get("message", "unknown remote error"))
        resp_obj = r.get("response") or {}
        if resp_obj.get("type") == "execute":
            out.append(resp_obj["result"])
    return out


class Row:
    """Supports r['col'], r[0] and tuple unpacking — the three access styles
    the existing call sites use."""
    __slots__ = ("_cols", "_vals")

    def __init__(self, cols, vals):
        self._cols, self._vals = cols, vals

    def __getitem__(self, k):
        return self._vals[k if isinstance(k, int) else self._cols.index(k)]

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def keys(self):
        return list(self._cols)


class _Cursor:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.rowcount = -1

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


def _is_read(sql):
    head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
    return head in ("SELECT", "PRAGMA", "WITH")


class RemoteConn:
    def __init__(self):
        self._pending = []      # (stmt, cursor) queued until commit()

    def execute(self, sql, params=None):
        if _is_read(sql):
            self._flush()       # reads must see this session's own writes
            result = _pipeline([_stmt(sql, params)])[0]
            cols = [c["name"] for c in result.get("cols", [])]
            return _Cursor([Row(cols, [_decode(c) for c in row])
                            for row in result.get("rows", [])])
        cur = _Cursor()
        self._pending.append((_stmt(sql, params), cur))
        return cur

    def executemany(self, sql, seq):
        cur = _Cursor()
        for params in seq:
            self._pending.append((_stmt(sql, params), _Cursor()))
        return cur

    def executescript(self, script):
        for part in script.split(";"):
            if part.strip():
                self.execute(part)
        return _Cursor()

    def _flush(self):
        if not self._pending:
            return
        stmts = [s for s, _ in self._pending]
        cursors = [c for _, c in self._pending]
        self._pending = []
        results = _pipeline(
            [{"sql": "BEGIN"}] + stmts + [{"sql": "COMMIT"}])
        for cur, result in zip(cursors, results[1:]):
            cur.rowcount = result.get("affected_row_count", -1)

    def commit(self):
        self._flush()

    def close(self):
        self._flush()

    # sqlite3 API parity — call sites assign to it, nothing reads it
    row_factory = None


def connect(local_path):
    """Remote when configured, otherwise the local file (unchanged behaviour)."""
    if not enabled():
        conn = sqlite3.connect(str(local_path))
        conn.row_factory = sqlite3.Row
        return conn
    return RemoteConn()
