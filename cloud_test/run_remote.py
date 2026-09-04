"""Run an app script against the hosted DB, credentials loaded from turso.json.

Keeps the token off the command line and out of shell history.

  python cloud_test/run_remote.py picking_history.py get-pending
  python cloud_test/run_remote.py buffer_stock.py get <db>
"""
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import turso_env  # noqa: E402

turso_env.load()

if len(sys.argv) < 2:
    sys.exit(__doc__)

script = HERE.parent / "src" / sys.argv[1]
if not script.exists():
    sys.exit("no such script: {}".format(script))

sys.argv = [str(script)] + sys.argv[2:]
runpy.run_path(str(script), run_name="__main__")
