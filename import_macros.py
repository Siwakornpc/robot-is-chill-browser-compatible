"""
import_macros.py - load user-created macros into your robot.db.

    python import_macros.py                     # download from the public macro API
    python import_macros.py macros.json         # a JSON file saved from that API
    python import_macros.py other\\robot.db      # copy the table out of another robot.db

Run it from the repo root, AFTER build_db.py. Macros with the same name are
replaced. It is a snapshot: run it again to refresh. Rebuilding robot.db from
scratch empties the macros table, so run this again after a rebuild.
The web server does not need this to be re-run per render - once is enough.
"""
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

API_URL = "https://ric-api.sno.mba/macros.json"

SCHEMA = """CREATE TABLE IF NOT EXISTS macros (
    name TEXT UNIQUE PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT NOT NULL,
    creator INT NOT NULL
)"""


def load_json(source: str) -> dict:
    if source.startswith(("http://", "https://")):
        request = urllib.request.Request(source, headers={"User-Agent": "robot-is-chill-importer"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    with open(source, encoding="utf-8") as fp:
        return json.load(fp)


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else API_URL
    con = sqlite3.connect("robot.db")
    con.execute(SCHEMA)

    if source.lower().endswith((".db", ".sqlite", ".sqlite3")):
        if not Path(source).is_file():
            sys.exit(f"File not found: {source}")
        con.execute("ATTACH DATABASE ? AS src", (str(Path(source).resolve()),))
        con.execute("INSERT OR REPLACE INTO main.macros SELECT * FROM src.macros")
    else:
        try:
            data = load_json(source)
        except (OSError, ValueError) as err:       # network errors, bad JSON, missing file
            sys.exit(f"Could not read macros from {source}: {err}")
        rows = [
            (name, str(info.get("value", "")), str(info.get("description", "")), int(info.get("creator", 0)))
            for name, info in data.items() if isinstance(info, dict)
        ]
        con.executemany(
            "INSERT OR REPLACE INTO macros (name, value, description, creator) VALUES (?, ?, ?, ?)", rows)
        print(f"Read {len(rows)} macros from {source}")

    con.commit()
    print("Macros now in robot.db:", con.execute("SELECT COUNT(*) FROM macros").fetchone()[0])


if __name__ == "__main__":
    main()