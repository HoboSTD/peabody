"""SQLite storage with the write-once upsert (README: Storage).

Readings go in as (site, parameter, ts, value) tuples: ts in Unix seconds (UTC), value a float or None.

The rule: a stored non-null value is never changed. Only new readings are inserted, and a stored null
can be filled with a value. Anything else the server sends for an existing reading is ignored and logged.
"""
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from extractor import config

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    site       TEXT    NOT NULL,
    parameter  TEXT    NOT NULL,
    ts         INTEGER NOT NULL,
    value      REAL,
    fetched_at INTEGER NOT NULL,
    PRIMARY KEY (site, parameter, ts)
) WITHOUT ROWID
"""

# The WHERE clause enforces the rule in SQL too: an existing row is only updated from null to a value.
UPSERT = """
INSERT INTO readings (site, parameter, ts, value, fetched_at) VALUES (?, ?, ?, ?, ?)
ON CONFLICT (site, parameter, ts) DO UPDATE
    SET value = excluded.value, fetched_at = excluded.fetched_at
    WHERE readings.value IS NULL AND excluded.value IS NOT NULL
"""

SAMPLE_SIZE = 10


@dataclass
class UpsertResult:
    inserted: int = 0    # new keys
    filled: int = 0      # stored null replaced by a value
    unchanged: int = 0   # same value as stored (or null again): not rewritten
    kept: int = 0        # server sent a different value or null for a stored value: stored value kept
    samples: list = field(default_factory=list)  # (site, parameter, ts, stored, sent) for kept values

    def summary(self):
        return f"inserted={self.inserted} filled={self.filled} unchanged={self.unchanged} kept={self.kept}"


def connect(path=config.DB_PATH):
    """Open the database (creating it and the table if needed) in autocommit mode;
    upsert() manages its own transaction."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=60)
    conn.execute(SCHEMA)
    return conn


def upsert(conn, readings, now=None):
    """Write new readings and fill stored nulls, in one transaction. Never changes a stored value
    and never deletes."""
    now = int(time.time()) if now is None else now
    by_series = {}
    for site, parameter, ts, value in readings:
        by_series.setdefault((site, parameter), {})[ts] = value

    result = UpsertResult()
    if not by_series:
        return result

    # IMMEDIATE takes the write lock now, so no other run can change rows between our read and write.
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = []
        for (site, parameter), incoming in by_series.items():
            stored = dict(conn.execute(
                "SELECT ts, value FROM readings WHERE site = ? AND parameter = ? AND ts BETWEEN ? AND ?",
                (site, parameter, min(incoming), max(incoming))))
            for ts, new in incoming.items():
                if ts not in stored:
                    result.inserted += 1
                elif new == stored[ts]:
                    result.unchanged += 1
                    continue
                elif stored[ts] is None:
                    result.filled += 1
                else:
                    result.kept += 1
                    if len(result.samples) < SAMPLE_SIZE:
                        result.samples.append((site, parameter, ts, stored[ts], new))
                    continue
                rows.append((site, parameter, ts, new, now))
        conn.executemany(UPSERT, rows)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    log.info("upsert: %s", result.summary())
    if result.kept:
        samples = "; ".join(f"{s}/{p} ts={ts}: stored {old}, sent {new}" for s, p, ts, old, new in result.samples)
        log.warning("upsert: server sent a different value for %d stored readings; stored values kept. "
                    "Sample: %s", result.kept, samples)
    return result
