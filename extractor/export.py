"""CSV exports, one file per site in the wide layout (README: CSV output).

Rows and values are exactly as stored: one row per stored timestamp (no rounding to 15-minute marks), values
written in full (Python's shortest round-trip form), and an empty cell for a null or a missing reading.
"""
import csv
import logging
import os
from datetime import datetime, timezone
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo

from extractor import config

log = logging.getLogger(__name__)


def file_name(site):
    """'LDP7 Water Treatment Plant' -> 'ldp7-water-treatment-plant.csv'"""
    return site.lower().replace(" ", "-") + ".csv"


def write_site(conn, site, folder=config.OUTPUT_DIR):
    """Write <folder>/<site>.csv from the database. Returns (path, rows). The file is replaced in one step,
    so a reader never sees a half-written file."""
    parameters = list(config.SITES[site])
    local = ZoneInfo(config.LOCAL_TIMEZONE)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / file_name(site)
    tmp = path.with_suffix(".csv.tmp")
    rows = 0
    cursor = conn.execute("SELECT ts, parameter, value FROM readings WHERE site = ? ORDER BY ts", (site,))
    try:
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            out = csv.writer(f)
            out.writerow(["timestamp_utc", "timestamp_local", *parameters])
            for ts, readings in groupby(cursor, key=lambda r: r[0]):
                values = {parameter: value for _, parameter, value in readings}
                when = datetime.fromtimestamp(ts, timezone.utc)
                out.writerow([when.strftime("%Y-%m-%dT%H:%M:%SZ"), when.astimezone(local).isoformat(),
                              *("" if values.get(p) is None else repr(values[p]) for p in parameters)])
                rows += 1
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path, rows


def write_all(conn, folder=config.OUTPUT_DIR):
    for site in config.SITES:
        path, rows = write_site(conn, site, folder)
        log.info("export: wrote %s (%d rows)", path.name, rows)
