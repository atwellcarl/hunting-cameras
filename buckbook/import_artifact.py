"""One-time import of labels and bucks exported from the claude.ai Buck Book.

Reads data/buckbook/{labels,bucks}/*.json (ArtifactData export) and attributes
them to a single named user, since artifact user ids don't carry over.

Usage: .venv/bin/python -m buckbook.import_artifact "Owner"
"""
import json
import sys
import uuid
from datetime import datetime, timezone

from buckbook.db import DATA_DIR, bump_version, connect


def load(kind):
    out = {}
    for f in sorted((DATA_DIR / kind).glob("*.json")):
        doc = json.loads(f.read_text())
        out[f.stem] = doc.get("data", doc)
    return out


def main():
    name = sys.argv[1]
    conn = connect()
    row = conn.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()
    user_id = row["id"] if row else uuid.uuid4().hex
    if not row:
        conn.execute("INSERT INTO users VALUES (?, ?, ?)", (user_id, name, datetime.now(timezone.utc).isoformat()))

    bucks, labels = load("bucks"), load("labels")
    for bid, b in bucks.items():
        conn.execute(
            "INSERT OR REPLACE INTO bucks (id, name, cover, by_user, at) VALUES (?, ?, ?, ?, ?)",
            (bid, b["name"], b.get("cover"), user_id, b["at"]),
        )
    skipped = 0
    for cid, l in labels.items():
        if not conn.execute("SELECT 1 FROM cards WHERE id = ?", (cid,)).fetchone():
            skipped += 1
            continue
        conn.execute(
            """INSERT OR REPLACE INTO labels (card_id, verdict, buck_id, points, confidence, by_user, at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cid, l["verdict"], l.get("buckId"), l.get("points"), l.get("confidence"), user_id, l["at"]),
        )
    bump_version(conn)
    conn.commit()
    print(f"Imported {len(bucks)} bucks and {len(labels) - skipped} labels as {name!r}"
          + (f" ({skipped} labels had no matching card)" if skipped else ""))


if __name__ == "__main__":
    main()
