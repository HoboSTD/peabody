"""Database backups and retention (README: Backups and restore).

Backups are gzip-compressed copies made with SQLite's online backup API, named by Sydney date:
  readings-YYYY-MM-DD.db.gz                  daily, before the first write of the day
  readings-YYYY-MM-DDTHHMM-backfill.db.gz    before each backfill
"""
import gzip
import logging
import re
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from extractor import config

log = logging.getLogger(__name__)

NAME = re.compile(r"^readings-(\d{4}-\d{2}-\d{2})(T\d{4}-backfill)?\.db\.gz$")


def local_now():
    return datetime.now(ZoneInfo(config.LOCAL_TIMEZONE))


def daily(conn, folder=config.BACKUP_DIR, now=None):
    """Back up once per local date, before the first write. Returns the new file, or None if today's
    backup already exists or there's nothing to back up yet."""
    now = now or local_now()
    path = folder / f"readings-{now:%Y-%m-%d}.db.gz"
    if path.exists() or not _has_data(conn):
        return None
    _make(conn, path)
    prune(folder, now.date())
    return path


def before_backfill(conn, folder=config.BACKUP_DIR, now=None):
    """Back up before a backfill starts. Returns the new file, or None if there's nothing to back up yet."""
    now = now or local_now()
    if not _has_data(conn):
        return None
    path = folder / f"readings-{now:%Y-%m-%dT%H%M}-backfill.db.gz"
    _make(conn, path)
    prune(folder, now.date())
    return path


def _has_data(conn):
    return conn.execute("SELECT 1 FROM readings LIMIT 1").fetchone() is not None


def _make(conn, path):
    """Copy the database consistently (even if another process has it open), then gzip it into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = path.with_name(path.name + ".tmp.db")
    tmp_gz = path.with_name(path.name + ".tmp")
    try:
        dest = sqlite3.connect(tmp_db)
        try:
            conn.backup(dest)
        finally:
            dest.close()
        with open(tmp_db, "rb") as src, gzip.open(tmp_gz, "wb") as out:
            shutil.copyfileobj(src, out)
        tmp_gz.replace(path)
    finally:
        tmp_db.unlink(missing_ok=True)
        tmp_gz.unlink(missing_ok=True)
    log.info("backup: wrote %s (%d KB)", path.name, path.stat().st_size // 1000)


def prune(folder, today, keep_days=config.BACKUP_KEEP_DAYS):
    """Keep every backup from the last keep_days days (today included); of older ones, keep only the
    earliest of each calendar month. Dates come from the file names. Other files are left alone."""
    backups = sorted((m.group(1), p.name, p) for p in folder.iterdir() if (m := NAME.match(p.name)))
    earliest_in_month = {}
    for day, _, path in backups:
        earliest_in_month.setdefault(day[:7], path)
    cutoff = today - timedelta(days=keep_days)
    for day, _, path in backups:
        if date.fromisoformat(day) > cutoff or earliest_in_month[day[:7]] == path:
            continue
        path.unlink()
        log.info("backup: removed %s", path.name)
