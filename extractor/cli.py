"""Command-line entry point: python -m extractor {check,fetch,backfill,export}."""
import argparse
import fcntl
import logging
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from extractor import backup, client, config, export, metrics, sites, store
from extractor.client import FetchError
from extractor.session import Session, SessionError

log = logging.getLogger("extractor")


class Busy(Exception):
    """Another run holds the lock."""


@contextmanager
def run_lock(path):
    """One run at a time (README: Collecting): the session, backup and export files use fixed temporary names, and a
    cron fetch could otherwise start while a backfill is running. The lock is released when the process exits,
    even if it crashes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy(f"another run is in progress (lock held on {path}); try again when it finishes") from None
        yield


def check(args):
    """Fetch the last 24 hours and print a summary per series. Writes nothing to the database."""
    end = datetime.now(timezone.utc)
    session = Session()
    readings = client.get_trends(session, end - timedelta(hours=24), end)
    by_series = defaultdict(list)
    for site, parameter, ts, value in readings:
        by_series[(site, parameter)].append((ts, value))
    print(f"{'site':28} {'parameter':22} {'points':>6} {'values':>6}  latest value (UTC)")
    for site, parameter, _ in config.SERIES:
        points = by_series[(site, parameter)]
        values = [(ts, v) for ts, v in points if v is not None]
        latest = (f"{values[-1][1]:.4g} at {datetime.fromtimestamp(values[-1][0], timezone.utc):%Y-%m-%d %H:%M}"
                  if values else "-")
        print(f"{site:28} {parameter:22} {len(points):6} {len(values):6}  {latest}")
    new, gone = sites.check(session)
    print(f"\nsite list: {'matches' if not (new or gone) else f'CHANGED: new {new}, gone {gone}'}")
    return 0


def fetch(args):
    """Incremental run (README: Collecting): one request for the last 24 hours of all series, upserted, then the
    CSVs rewritten."""
    end = datetime.now(timezone.utc)
    session = Session()
    readings = client.get_trends(session, end - timedelta(hours=24), end)
    conn = store.connect(config.DB_PATH)
    try:
        if config.LOCAL_BACKUPS:
            backup.daily(conn, config.BACKUP_DIR)
        store.upsert(conn, readings)
        export.write_all(conn, config.OUTPUT_DIR)
        metrics.write_summary(conn, config.OUTPUT_DIR)
    finally:
        conn.close()
    warn_if_stale(readings, end)
    sites.daily_check(session, config.SITES_CHECKED_PATH)  # after storing, so it can never hold up collection
    return 0


def warn_if_stale(readings, now):
    """The server answers with empty values, not an error, when a site stops reporting (README: Collecting)."""
    newest = max((ts for *_, ts, value in readings if value is not None), default=None)
    if newest is None:
        log.warning("no values at any site in the last 24 hours; the source may have stopped updating")
    elif (age := (now.timestamp() - newest) / 3600) > config.STALE_HOURS:
        log.warning("newest value is %.1f hours old (%s UTC); the source may have stopped updating", age,
                    f"{datetime.fromtimestamp(newest, timezone.utc):%Y-%m-%d %H:%M}")


def month_chunks(start, end):
    """Split [start, end] into pieces that end on the 1st of each month (UTC). Adjacent pieces share their
    boundary reading, which the upsert counts as unchanged."""
    chunks = []
    while start < end:
        next_month = (start.replace(day=1) + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0,
                                                                         microsecond=0)
        chunks.append((start, min(next_month, end)))
        start = next_month
    return chunks


def backfill(args):
    """Collect history (README: Collecting): month by month, each month fetched and stored before the next.
    A failure keeps the months already stored and says where to resume."""
    end = min(args.end, datetime.now(timezone.utc)) if args.end else datetime.now(timezone.utc)
    chunks = month_chunks(args.start, end)
    if not chunks:
        log.error("backfill: --from must be before --to")
        return 1
    session = Session()
    conn = store.connect(config.DB_PATH)
    try:
        if config.LOCAL_BACKUPS:
            backup.before_backfill(conn, config.BACKUP_DIR)
        total = 0
        for i, (start, stop) in enumerate(chunks):
            if i:
                time.sleep(config.BACKFILL_PAUSE)
            try:
                readings = client.get_trends(session, start, stop)
            except (SessionError, FetchError):
                log.error("backfill: stopped at %s; months before it are stored. To resume: backfill --from %s",
                          f"{start:%Y-%m}", f"{start:%Y-%m-%d}")
                raise
            store.upsert(conn, readings)
            total += sum(v is not None for *_, v in readings)
        first = conn.execute("SELECT MIN(ts) FROM readings WHERE value IS NOT NULL").fetchone()[0]
        export.write_all(conn, config.OUTPUT_DIR)
        metrics.write_summary(conn, config.OUTPUT_DIR)
    finally:
        conn.close()
    earliest = f"{datetime.fromtimestamp(first, timezone.utc):%Y-%m-%d %H:%M} UTC" if first else "none"
    log.info("backfill: done, %d months, %d non-null readings received; earliest stored reading: %s",
             len(chunks), total, earliest)
    return 0


def export_csv(args):
    """Write output/<site>.csv from the database (README: CSV output). No network."""
    conn = store.connect(config.DB_PATH)
    try:
        export.write_all(conn, config.OUTPUT_DIR)
    finally:
        conn.close()
    return 0


def analyze(args):
    """Write output/metrics.json from the database (README: Metrics). No network."""
    conn = store.connect(config.DB_PATH)
    try:
        metrics.write_summary(conn, config.OUTPUT_DIR)
    finally:
        conn.close()
    return 0


def utc_date(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {text!r}") from None


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m extractor")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("check", help="fetch the last 24 hours and print a summary (writes nothing)"
                        ).set_defaults(run=check)
    commands.add_parser("fetch", help="collect the last 24 hours (run hourly by cron)").set_defaults(run=fetch)

    backfill_ = commands.add_parser("backfill", help="collect history in 1-month chunks")
    backfill_.add_argument("--from", dest="start", type=utc_date, default=utc_date("2023-01-01"),
                           help="start date, YYYY-MM-DD, from 00:00 UTC (default: 2023-01-01)")
    backfill_.add_argument("--to", dest="end", type=utc_date,
                           help="end date, YYYY-MM-DD, up to 00:00 UTC on that day (default: now)")
    backfill_.set_defaults(run=backfill)

    commands.add_parser("export", help="write output/<site>.csv from the database (fetch and backfill do this too)"
                        ).set_defaults(run=export_csv)

    commands.add_parser("analyze", help="write output/metrics.json summarizing water-quality trends "
                        "(fetch and backfill do this too)").set_defaults(run=analyze)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        with run_lock(config.LOCK_PATH):
            return args.run(args)
    except (SessionError, FetchError, Busy) as e:
        log.error("%s: %s", type(e).__name__, e)
        return 1
