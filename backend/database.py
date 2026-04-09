import sqlite3
from contextlib import contextmanager

from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
CREATE TABLE IF NOT EXISTS gpu_offers (
    id             TEXT PRIMARY KEY,
    provider       TEXT NOT NULL,
    gpu_type       TEXT NOT NULL,
    normalized_gpu_type TEXT DEFAULT '',
    gpu_count      INTEGER NOT NULL,
    price_per_hour REAL NOT NULL,
    region         TEXT,
    available      INTEGER NOT NULL DEFAULT 1,
    raw_instance_type_id TEXT,
    raw_image_id   TEXT,
    raw_region_id  TEXT,
    updated_at     TIMESTAMP DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS instances (
    id                   TEXT PRIMARY KEY,
    provider_instance_id TEXT,
    provider             TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending',
    gpu_type             TEXT,
    ssh_host             TEXT,
    ssh_port             INTEGER,
    ssh_user             TEXT,
    ssh_password         TEXT,
    benchmark_result     TEXT,
    created_at           TIMESTAMP DEFAULT (datetime('now')),
    ready_at             TIMESTAMP
);

CREATE TABLE IF NOT EXISTS telemetry (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id    TEXT NOT NULL,
    timestamp      REAL NOT NULL,
    gpu_util_pct   REAL,
    gpu_mem_used_mb REAL,
    gpu_mem_total_mb REAL,
    gpu_temp_c     REAL,
    FOREIGN KEY (instance_id) REFERENCES instances(id)
);
""")
