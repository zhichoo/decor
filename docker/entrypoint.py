"""Initialize/validate the isolated deployment database, then serve the app."""
import os
from pathlib import Path
import subprocess
import sys
import time

import psycopg2

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.umask(0o077)
    if not os.environ.get("DATABASE_URL", "").strip():
        raise RuntimeError("DATABASE_URL is required")
    readonly = os.environ.get("PUBLIC_READ_ONLY", "false").lower() in ("1", "true", "yes")
    if not readonly and len(os.environ.get("ADMIN_PASSWORD", "")) < 16:
        raise RuntimeError("Set ADMIN_PASSWORD to at least 16 characters")
    for attempt in range(30):
        try:
            with psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=3):
                break
        except psycopg2.OperationalError:
            if attempt == 29:
                raise RuntimeError("Database unavailable; check deployment configuration") from None
            time.sleep(2)
    for script in ("migrate_transcript_jobs.py", "init_db.py"):
        subprocess.run([sys.executable, str(ROOT / "scripts" / script)], check=True)
    os.execvp("xvfb-run", ["xvfb-run", "-a", sys.executable, str(ROOT / "backend/server.py")])


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
