"""Generate the setup code a new PC pastes on its first run.

One short string carries everything a fresh install needs beyond the portal
login: where to fetch the seed database, and the shared-DB url and token. The
user pastes it into the welcome box and the app does the rest — no files to
hand-carry, no scripts to run, nothing to edit.

  python tools/make_setup_code.py              print the code
  python tools/make_setup_code.py --out c.txt  write it to a file as well

Reads turso.json and drive_state.json from the repo root. Both are gitignored
and stay on this machine — only the generated code travels.

Prerequisite:  python tools/drive_sync.py publish   (pushes every profile's
data and records the links; re-run it whenever you want the code to hand out
fresher data).

The code contains a write token for the shared picks database. Send it the way
you would send a password, and only to your own machines.
"""
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TURSO = ROOT / "turso.json"
DRIVE_STATE = ROOT / "drive_state.json"
SEED_NAME = "seed.db.gz"          # legacy single-account seed
MANIFEST = ROOT / "db" / "profiles.json"


def main():
    if not TURSO.exists():
        sys.exit("missing {} — the Turso url and token".format(TURSO))
    turso = json.loads(TURSO.read_text(encoding="utf-8"))
    if not turso.get("url") or not turso.get("token"):
        sys.exit("{} needs both 'url' and 'token'".format(TURSO))

    # The seed is optional: without it a new PC still joins the shared picks,
    # it just starts with no sales history.
    seed_url = ""
    if DRIVE_STATE.exists():
        seed_url = json.loads(DRIVE_STATE.read_text(encoding="utf-8")) \
            .get("public", {}).get(SEED_NAME, "")

    payload = {"remoteUrl": turso["url"], "remoteToken": turso["token"]}
    if seed_url:
        payload["seedUrl"] = seed_url        # older app versions read only this

    # One entry per profile, keyed by a hash of its portal login. The new PC
    # hashes whatever login is typed and looks it up, so the code carries no
    # username and no password — only which data belongs to which login.
    public = json.loads(DRIVE_STATE.read_text(encoding="utf-8")).get("public", {})         if DRIVE_STATE.exists() else {}
    profiles = {}
    if MANIFEST.exists():
        for prof in json.loads(MANIFEST.read_text(encoding="utf-8")):
            key = prof["key"]
            # The source PC's own id travels with the entry: the hosted rows
            # are scoped to it, so a new PC that minted its own id from the
            # login would read empty buffers even with the data right there.
            entry = {"label": prof.get("label") or key, "id": prof["id"]}
            db = public.get("seed-{}.db.gz".format(key))
            rep = public.get("report-{}.xlsx".format(key))
            if db:
                entry["db"] = db
            if rep:
                entry["report"] = rep
            if db or rep:
                profiles[key] = entry
    if profiles:
        payload["profiles"] = profiles
        print("profiles in this code: " + ", ".join(
            "{} ({})".format(v["label"], "+".join(
                k2 for k2 in ("db", "report") if k2 in v)) for v in profiles.values()),
            file=sys.stderr)
    else:
        print("WARNING: no published profile data — run "
              "'python tools/drive_sync.py publish' first", file=sys.stderr)

    code = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")

    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])
        out.write_text(code, encoding="utf-8")
        print("wrote {}".format(out))

    print()
    print(code)
    print()
    print("  shared DB  {}".format(turso["url"].split("//")[-1]))
    print("  seed       {}".format(
        "yes, {} chars".format(len(seed_url)) if seed_url
        else "NONE — run: python tools/drive_sync.py share " + SEED_NAME))
    print("\nPaste this into the new PC's welcome box, in the Setup code field.")
    print("It carries a write token — treat it like a password.")


if __name__ == "__main__":
    main()
