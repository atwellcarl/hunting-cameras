"""SQLite store for Buck Book. One file: data/buckbook/buckbook.db."""
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "buckbook"
DB_PATH = Path(os.environ.get("BUCKBOOK_DB", DATA_DIR / "buckbook.db"))
IMG_DIR = DATA_DIR / "img"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
  id TEXT PRIMARY KEY,
  camera TEXT NOT NULL,
  property TEXT,
  taken_at TEXT NOT NULL,          -- local camera time, ISO
  daylight INTEGER,
  temp_f REAL,
  wind TEXT,
  moon TEXT,
  pressure REAL,
  burst INTEGER,
  photo_id TEXT,
  bbox TEXT,                       -- JSON [x, y, w, h], normalized
  ai TEXT                          -- JSON from the tagging pipeline
);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bucks (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  cover TEXT REFERENCES cards(id),
  by_user TEXT REFERENCES users(id),
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS labels (
  card_id TEXT PRIMARY KEY REFERENCES cards(id),
  verdict TEXT NOT NULL CHECK (verdict IN ('buck', 'not', 'unsure')),
  buck_id TEXT REFERENCES bucks(id),
  points INTEGER,
  confidence INTEGER CHECK (confidence BETWEEN 1 AND 5),
  by_user TEXT REFERENCES users(id),
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
INSERT OR IGNORE INTO meta VALUES ('version', '0');
"""


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def bump_version(conn):
    """Increment the change counter clients poll on."""
    conn.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'version'")


def version(conn):
    return int(conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()[0])
