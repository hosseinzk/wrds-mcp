"""Save WRDS credentials to the PostgreSQL password file and test the connection.

Run once per machine before using the MCP server: `wrds-mcp-setup`.
"""

import getpass
import os
import sys
from pathlib import Path

import psycopg2

HOST, PORT, DB = "wrds-pgdata.wharton.upenn.edu", 9737, "wrds"


def pgpass_path():
    if os.environ.get("PGPASSFILE"):
        return Path(os.environ["PGPASSFILE"])
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "postgresql" / "pgpass.conf"
    return Path.home() / ".pgpass"


def main():
    user = input("WRDS username: ").strip()
    password = getpass.getpass("WRDS password (not shown): ")
    print("Connecting to WRDS (approve the Duo push on your phone if one arrives)...")
    try:
        psycopg2.connect(host=HOST, port=PORT, dbname=DB, user=user, password=password,
                         sslmode="require", connect_timeout=60).close()
    except psycopg2.OperationalError as e:
        sys.exit(f"Connection failed: {e}")

    path = pgpass_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    esc = password.replace("\\", "\\\\").replace(":", "\\:")
    lines = [l for l in (path.read_text().splitlines() if path.exists() else []) if not l.startswith(f"{HOST}:")]
    lines.append(f"{HOST}:{PORT}:{DB}:{user}:{esc}")
    if path.exists():
        path.chmod(0o600)
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)
    print(f"Connected. Credentials saved to {path}")


if __name__ == "__main__":
    main()
