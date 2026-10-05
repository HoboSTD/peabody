"""Pollution-indicator metrics computed from stored readings (README: Metrics).

Everything here reads the database; nothing is fetched from the network. write_summary() is the only thing that
writes a file, following export.py's atomic-write pattern.
"""
import json
import logging
import os
import statistics
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from extractor import config

log = logging.getLogger(__name__)


@dataclass
class FlaggedPeriod:
    start: int              # Unix seconds, UTC; first elevated reading in the window
    end: int                # Unix seconds, UTC; last elevated reading in the window
    peak_ratio: float       # the highest Downstream:Upstream conductivity ratio seen in the window
    confidence: str         # "high", "medium" or "low" (see flagged_periods())
    corroborated_by: list = field(default_factory=list)  # "turbidity", "flow", both, or neither


def series(conn, site, parameter, start=None, end=None):
    """(ts, value) pairs for one site/parameter, oldest first. Includes stored nulls."""
    sql = "SELECT ts, value FROM readings WHERE site = ? AND parameter = ?"
    params = [site, parameter]
    if start is not None:
        sql += " AND ts >= ?"
        params.append(start)
    if end is not None:
        sql += " AND ts < ?"
        params.append(end)
    return conn.execute(sql + " ORDER BY ts", params).fetchall()


def sanitize(parameter, value):
    """True if value is physically plausible for parameter (README: Metrics). A null reading is never
    sane here: it means no reading, which is a data-health question, not a bad-value one. Parameters with
    no entry in SANE_BOUNDS (flow_volume) aren't bounds-checked."""
    if value is None:
        return False
    bounds = config.SANE_BOUNDS.get(parameter)
    return bounds is None or bounds[0] <= value <= bounds[1]


def sanitized_series(conn, site, parameter, start=None, end=None):
    """Like series(), but with nulls and out-of-bounds values dropped (README: Metrics)."""
    return [(ts, value) for ts, value in series(conn, site, parameter, start, end) if sanitize(parameter, value)]


def latest_reading_at(conn, site, parameter):
    """The timestamp of the newest non-null reading for site/parameter, or None (README: Metrics). Matches
    cli.warn_if_stale's idea of "newest value": a null reading still means the source answered, so staleness
    is about the newest non-null value, not raw sanity."""
    row = conn.execute(
        "SELECT MAX(ts) FROM readings WHERE site = ? AND parameter = ? AND value IS NOT NULL",
        (site, parameter)).fetchone()
    return row[0]


def ratio_series(conn, start=None, end=None):
    """Downstream:Upstream specific_conductivity ratio at shared timestamps, sanitized values only
    (README: Metrics). (ts, ratio) pairs, oldest first."""
    upstream = dict(sanitized_series(conn, "Upstream", "specific_conductivity", start, end))
    downstream = dict(sanitized_series(conn, "Downstream", "specific_conductivity", start, end))
    return sorted((ts, downstream[ts] / upstream[ts]) for ts in upstream.keys() & downstream.keys())


def ph_excursions(conn, site, start=None, end=None):
    """Sanitized pH readings outside the licence band (README: Metrics). (ts, value) pairs."""
    lo, hi = config.PH_LICENCE_BAND
    return [(ts, value) for ts, value in sanitized_series(conn, site, "ph", start, end) if not lo <= value <= hi]


def turbidity_spikes(conn, site, start=None, end=None):
    """Sanitized turbidity readings that are robust outliers against the site's own full-history baseline:
    a modified z-score (median + MAD) at or above TURBIDITY_SPIKE_MODIFIED_Z, the standard Iglewicz & Hoaglin
    outlier threshold (README: Metrics). (ts, value, modified_z) tuples, oldest first. The baseline always
    uses the whole history, regardless of start/end, so the same reading gets the same baseline wherever
    it's queried from."""
    baseline = [value for _, value in sanitized_series(conn, site, "turbidity")]
    if len(baseline) < 2:
        return []
    median = statistics.median(baseline)
    mad = statistics.median(abs(value - median) for value in baseline)
    if mad == 0:
        return []
    spikes = []
    for ts, value in sanitized_series(conn, site, "turbidity", start, end):
        z = 0.6745 * (value - median) / mad
        if z >= config.TURBIDITY_SPIKE_MODIFIED_Z:
            spikes.append((ts, value, z))
    return spikes


def flagged_periods(conn, start=None, end=None):
    """Contiguous windows where the conductivity ratio reached CONDUCTIVITY_RATIO_ELEVATED, merged across
    gaps of up to FLAGGED_PERIOD_MERGE_GAP_MINUTES (README: Metrics). Confidence is "high" when the peak
    reaches CONDUCTIVITY_RATIO_ALERT and is corroborated by a Downstream turbidity spike or LDP7/LDP8 flow in
    the same window, "medium" for either alone, "low" for an elevated ratio with neither. Oldest first."""
    elevated = [(ts, r) for ts, r in ratio_series(conn, start, end) if r >= config.CONDUCTIVITY_RATIO_ELEVATED]
    if not elevated:
        return []

    merge_gap = config.FLAGGED_PERIOD_MERGE_GAP_MINUTES * 60
    groups = [[elevated[0]]]
    for ts, r in elevated[1:]:
        if ts - groups[-1][-1][0] <= merge_gap:
            groups[-1].append((ts, r))
        else:
            groups.append([(ts, r)])

    turbid_ts = {ts for ts, _, _ in turbidity_spikes(conn, "Downstream", start, end)}
    flow_ts = set()
    for site in ("LDP7 Water Treatment Plant", "LDP8 Turkeys Nest"):
        flow_ts.update(ts for ts, value in sanitized_series(conn, site, "flow_volume", start, end) if value)

    periods = []
    for group in groups:
        group_ts = {ts for ts, _ in group}
        peak_ratio = max(r for _, r in group)
        corroborated_by = [name for name, hits in (("turbidity", turbid_ts), ("flow", flow_ts)) if group_ts & hits]
        if peak_ratio >= config.CONDUCTIVITY_RATIO_ALERT and corroborated_by:
            confidence = "high"
        elif peak_ratio >= config.CONDUCTIVITY_RATIO_ALERT or corroborated_by:
            confidence = "medium"
        else:
            confidence = "low"
        periods.append(FlaggedPeriod(start=group[0][0], end=group[-1][0], peak_ratio=peak_ratio,
                                      confidence=confidence, corroborated_by=corroborated_by))
    return periods


def chronic_trend(conn):
    """Daily median Downstream:Upstream ratio across the full history, and its rolling
    90-day median, to separate a long-run baseline shift from acute spikes (README: Metrics).
    (date, daily_median, rolling_90d_median) tuples, oldest first."""
    by_day = {}
    for ts, r in ratio_series(conn):
        by_day.setdefault(datetime.fromtimestamp(ts, timezone.utc).date(), []).append(r)

    window = deque(maxlen=90)
    trend = []
    for day in sorted(by_day):
        daily_median = statistics.median(by_day[day])
        window.append(daily_median)
        trend.append((day, daily_median, statistics.median(window)))
    return trend


def data_health(conn, parameter="ph"):
    """Per site, using `parameter` as the clock: how many stored timestamps have a sanitized value, and any
    gaps of GAP_HOURS or more with no record at all (README: Metrics). A gap is about missing records, not
    nulls: a null still means the source answered."""
    gap_seconds = config.GAP_HOURS * 3600
    report = {}
    for site, parameters in config.SITES.items():
        if parameter not in parameters:
            continue
        rows = series(conn, site, parameter)
        valid = sum(1 for _, value in rows if sanitize(parameter, value))
        gaps = [(ts1, ts2) for (ts1, _), (ts2, _) in zip(rows, rows[1:]) if ts2 - ts1 >= gap_seconds]
        report[site] = {
            "total": len(rows),
            "valid": valid,
            "completeness": valid / len(rows) if rows else 0.0,
            "gaps": gaps,
        }
    return report


def summary(conn, now=None):
    """Everything write_summary() serializes to metrics.json (README: Metrics)."""
    now = int(time.time()) if now is None else now
    ratios = ratio_series(conn)
    current_ratio = ratios[-1][1] if ratios else None
    if current_ratio is None:
        ratio_tier = "unknown"
    elif current_ratio >= config.CONDUCTIVITY_RATIO_ALERT:
        ratio_tier = "alert"
    elif current_ratio >= config.CONDUCTIVITY_RATIO_ELEVATED:
        ratio_tier = "elevated"
    else:
        ratio_tier = "normal"

    sites = {}
    for site in config.SITES:
        latest_ph = sanitized_series(conn, site, "ph")[-1:] if "ph" in config.SITES[site] else []
        sites[site] = {
            "latest_reading_at": latest_reading_at(conn, site, "ph" if "ph" in config.SITES[site] else "flow_volume"),
            "latest_ph": latest_ph[0][1] if latest_ph else None,
            "ph_in_band": (config.PH_LICENCE_BAND[0] <= latest_ph[0][1] <= config.PH_LICENCE_BAND[1]
                           if latest_ph else None),
        }

    trend = chronic_trend(conn)
    return {
        "generated_at": now,
        "conductivity_ratio": {"current": current_ratio, "tier": ratio_tier,
                                "elevated_threshold": config.CONDUCTIVITY_RATIO_ELEVATED,
                                "alert_threshold": config.CONDUCTIVITY_RATIO_ALERT},
        "sites": sites,
        "chronic_trend": [{"date": day.isoformat(), "daily_median_ratio": daily, "rolling_90d_median_ratio": rolling}
                           for day, daily, rolling in trend],
        "flagged_periods": [asdict(p) for p in flagged_periods(conn)],
        "data_health": data_health(conn),
    }


def write_summary(conn, folder=config.OUTPUT_DIR, now=None):
    """Write <folder>/metrics.json from the database. Returns the path. The file is replaced in one step,
    so a reader never sees a half-written file (README: Metrics; same pattern as export.write_site)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "metrics.json"
    tmp = path.with_suffix(".json.tmp")
    data = summary(conn, now)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    log.info("metrics: wrote %s (%d flagged periods)", path.name, len(data["flagged_periods"]))
    return path
