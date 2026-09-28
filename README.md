# Metropolitan Coal Mine water monitoring extractor

Collects water monitoring readings from Peabody's public monitoring page (<https://peabody.ghost.site/>) for four
sites around the Metropolitan Coal Mine. It stores them in a local SQLite database and writes one CSV per site.

This is an independent project. It isn't affiliated with or endorsed by Peabody, and it uses the same requests
the public page makes in a browser (see [API reference](#api-reference)).

**Status:** complete and working. It runs every 3 hours on GitHub Actions and publishes the full history (from
2023-08-08) to the [`data` release](https://github.com/HoboSTD/peabody/releases/tag/data). The CSVs have been
checked against the source.

## Download the data

The latest files, updated every 3 hours:

| Site | CSV |
|---|---|
| Upstream | <https://github.com/HoboSTD/peabody/releases/download/data/upstream.csv> |
| LDP7 Water Treatment Plant | <https://github.com/HoboSTD/peabody/releases/download/data/ldp7-water-treatment-plant.csv> |
| LDP8 Turkeys Nest | <https://github.com/HoboSTD/peabody/releases/download/data/ldp8-turkeys-nest.csv> |
| Downstream | <https://github.com/HoboSTD/peabody/releases/download/data/downstream.csv> |
| All four, as the SQLite database (gzip) | <https://github.com/HoboSTD/peabody/releases/download/data/readings.db.gz> |

The links don't change. See [CSV output](#csv-output) for the columns and [About the data](#about-the-data) for
quirks worth knowing. The asset dates on the release page show when each file was last updated.

Python 3.10+ with `requests` and the standard library. No other dependencies.

## Quick start

```bash
./setup.sh                                    # create .venv and the working folders
.venv/bin/python -m extractor check           # try the live site: prints the last 24 hours, stores nothing
.venv/bin/python -m extractor backfill        # load the full history (about 5 minutes)
.venv/bin/python -m extractor fetch           # collect the last 24 hours (what cron runs every hour)
```

The CSVs are then in `output/`. This builds a copy on your own machine, separate from the one on GitHub. To
collect automatically, see [Running on GitHub](#running-on-github) or
[Running it on your own machine](#running-it-on-your-own-machine).

## Commands

Run as `.venv/bin/python -m extractor <command>` from the repo folder.

| Command | What it does |
|---|---|
| `check` | Fetches the last 24 hours and prints, for each of the 18 series, how many readings came back and the latest value. Also checks the site list. Doesn't touch the database or CSVs |
| `fetch` | Fetches the last 24 hours, stores new readings and rewrites the CSVs. Makes the day's backup before its first write each day. Meant to run on a schedule: every 3 hours on GitHub, or hourly by cron |
| `backfill [--from YYYY-MM-DD] [--to YYYY-MM-DD]` | Fetches history month by month and stores it, then rewrites the CSVs. Makes a backup first. `--from` defaults to 2023-01-01 and `--to` to now; both dates mean 00:00 UTC |
| `export` | Rewrites the CSVs from the database. No network |

Exit codes: `0` success; `1` the run failed, or was skipped because another run was in progress; `2` bad arguments.
Messages go to standard error; see [Log messages](#log-messages).

## What's collected

Four sites, 18 series in all, one reading every 15 minutes:

| Site | pH | Specific conductivity | Temperature | Turbidity | Flow volume | Latitude, longitude |
|---|:-:|:-:|:-:|:-:|:-:|---|
| Upstream | ✓ | ✓ | ✓ | ✓ | | -34.188793, 150.992384 |
| LDP7 Water Treatment Plant | ✓ | ✓ | ✓ | ✓ | ✓ | -34.187534, 150.993715 |
| LDP8 Turkeys Nest | ✓ | ✓ | ✓ | ✓ | ✓ | -34.186904, 150.998721 |
| Downstream | ✓ | ✓ | ✓ | ✓ | | -34.187603, 151.002612 |

| Parameter | Unit | Column name |
|---|---|---|
| pH | pH | `ph` |
| Specific conductivity | µS/cm at 25 °C | `specific_conductivity` |
| Temperature | °C | `temperature` |
| Turbidity | NTU | `turbidity` |
| Flow volume | litres discharged in the 15-minute interval (confirmed). A period's total is the sum of its readings | `flow_volume` |

Units come from the page's labels. Values are stored and exported exactly as the server sends them: nothing is
rounded, aligned or cleaned. See [About the data](#about-the-data) for quirks worth knowing.

## CSV output

`fetch`, `backfill` and `export` write one file per site to `output/`:

| File | Columns |
|---|---|
| `upstream.csv`, `downstream.csv` | `timestamp_utc, timestamp_local, ph, specific_conductivity, temperature, turbidity` |
| `ldp7-water-treatment-plant.csv`, `ldp8-turkeys-nest.csv` | the same, plus `flow_volume` |

- **One row per stored timestamp** for that site, oldest first. Timestamps are never rounded, so readings before
  2024-02-14, which weren't on the 15-minute marks, keep their own times, seconds included. In the few weeks where
  flow and water quality had different timestamps, they're on separate rows.
- **Times:** `timestamp_utc` is ISO 8601 with `Z` (`2023-08-08T06:26:09Z`). `timestamp_local` is Sydney time with its
  UTC offset (`2023-08-08T16:26:09+10:00`), so the repeated hour when daylight saving ends is unambiguous.
- **Values** are written in full, in Python's shortest exact form (`8.770000457763672`, `587.0`).
- **Empty cell:** the server sent `null`, or there's no record for that series at that time. The CSV doesn't
  distinguish the two; the database does.
- Each file is written in full and then swapped in, so a reader never sees a half-written file, and a failed export
  leaves the previous one in place.
- With the full history, each file has about 109,000 rows (6–10 MB). Rewriting all four takes about 3 seconds.

## Running on GitHub

[.github/workflows/collect.yml](.github/workflows/collect.yml) runs `fetch` every 3 hours, at 00:17, 03:17, 06:17
UTC and so on. The newest data published is then at most about 6 hours old (3 hours between runs, plus the source's
usual 3-hour delay). GitHub sometimes starts scheduled runs late, or occasionally skips one; that's harmless,
because each `fetch` covers the last 24 hours, so up to seven runs in a row can be missed without a gap. Each run:

1. Downloads `readings.db.gz` from the `data` release. If it isn't there, the run fails rather than starting again
   from empty (see [Restoring the database on GitHub](#restoring-the-database-on-github)).
2. On the first run of each month (Sydney time), copies the database, unchanged, to the
   [`backups` release](https://github.com/HoboSTD/peabody/releases/tag/backups) as `readings-YYYY-MM.db.gz`.
3. Runs the command, then checks the database: SQLite's integrity check must pass, and the number of rows and of
   values must not have gone down. If the check fails, nothing is uploaded and the run fails.
4. Uploads `readings.db.gz` and the four CSVs to the `data` release, replacing the old ones. A `fetch` that stored
   nothing new uploads nothing.

Things to know:
- **Running a command by hand:** Actions > collect > Run workflow, then choose `fetch`, `backfill` (with optional
  `--from` and `--to` dates) or `export`. Use `backfill` after an outage of more than 24 hours.
- **If scheduled runs stop, nothing is emailed.** GitHub only emails when a run starts and fails, not when runs
  don't start at all (during a GitHub outage, or if the schedule is turned off or stops being picked up). Check
  now and then that the asset dates on the [`data` release](https://github.com/HoboSTD/peabody/releases/tag/data)
  are less than a day old. If the schedule seems stuck, turn the workflow off and on again under Actions > collect.
- **Failures are emailed** to you by GitHub. The log of every run is under Actions > collect, kept for 90 days.
  Warnings, such as stale data, only appear in those logs.
- **One run at a time:** a run that starts while another is going waits for it to finish.
- **The 60-day rule:** GitHub turns off scheduled workflows in a public repo after 60 days with no activity. The
  last step of each run re-enables the workflow through the API, which counts as activity. If it's turned off
  anyway, GitHub emails you; turn it back on under Actions > collect, and `backfill` the gap.
- **Local daily backups are off** on GitHub (`EXTRACTOR_LOCAL_BACKUPS=off`), because the runner's files are thrown
  away after each run.
- **The site-list check runs with every run** on GitHub instead of once a day, because `state/` isn't kept between runs.
  It's one extra request of about 2 KB.
- **Cost:** nothing. Actions minutes are free for public repos, and so are release downloads. A run takes about a
  minute.

### Restoring the database on GitHub

If `readings.db.gz` is missing from the `data` release, or holds bad data, upload a good copy from the `backups`
release, then fill the gap:

```bash
gh release download backups --pattern readings-2026-09.db.gz     # the latest good month
mv readings-2026-09.db.gz readings.db.gz
gh release upload data readings.db.gz --clobber
```

Then run `backfill` from Actions with `--from` set to the backup's month, e.g. `2026-09-01`.

### Working on a local copy

The copy on GitHub is the main one. To get it on your own machine (with no local runs in progress):

```bash
gh release download data --pattern readings.db.gz --dir data --clobber && gunzip -f data/readings.db.gz
.venv/bin/python -m extractor export
```

Changes made locally aren't uploaded. Don't upload a local database to the `data` release unless you mean to
replace GitHub's copy, as in [Restoring the database on GitHub](#restoring-the-database-on-github).

## Running it on your own machine

Instead of GitHub, cron can run `fetch` on your own machine every hour. Don't run both: they'd keep two separate
copies of the database.

1. **Install and start cron.** It isn't installed by default on some systems:
   ```bash
   sudo apt install cron                # Debian / Ubuntu
   sudo systemctl enable --now cron     # start it now and at boot
   systemctl is-active cron             # should print "active"
   ```
   macOS has cron built in. If the repo is under Documents, Desktop or Downloads, give `/usr/sbin/cron` Full Disk
   Access (System Settings > Privacy & Security), or cron can't read it.
2. **Fill the gap since the last run**, if it's more than 24 hours, with `backfill --from <last day collected>`
   (e.g. `--from 2026-09-27`). See [Filling a gap](#filling-a-gap-of-more-than-24-hours).
3. **Add the entry:** `./setup.sh --cron`. `crontab -l` should then show this line, once:
   `0 * * * * cd '<repo>' && .venv/bin/python -m extractor fetch >> logs/fetch.log 2>&1`
4. **Confirm it ran** after the next full hour. `tail logs/fetch.log` should show a `GetTrendValues` line, an
   `upsert:` line and four `export: wrote` lines. The first run of each day also shows `site list matches (4 sites)`,
   and a `backup: wrote` line.

Things to know:
- **The machine has to be on.** cron only runs while the computer is running. Each `fetch` covers
  the last 24 hours, so a gap shorter than that fills itself on the next run.
- **Nothing is emailed.** Output goes to `logs/fetch.log`, so check it now and then:
  `grep -E "WARNING|ERROR" logs/fetch.log | tail`.
- **Log size:** about 1 KB per run, or 9 MB a year. Delete or truncate the file whenever you like.
- **Running commands by hand** while cron is active is fine. Only one run happens at a time: if two overlap, the
  second stops straight away with `Busy: another run is in progress`. A skipped hourly `fetch` loses nothing.
- **To stop it:** `crontab -e` and delete the line, or put `#` in front of it.

## Log messages

| Message | Level | Meaning and what to do |
|---|---|---|
| `upsert: inserted=… filled=… unchanged=… kept=…` | INFO | What a run stored: new readings, stored nulls now filled, readings already stored, and readings where the server sent something different from what's stored |
| `site list matches (4 sites)` | INFO | The daily site-list check passed |
| `site list changed: new on the server: … no longer on the server: …` | WARNING | See [When a site is added or renamed](#when-a-site-is-added-renamed-or-removed) |
| `site-list check failed; will try again next run` | WARNING | Usually a network hiccup. Only a concern if it repeats for days |
| `newest value is N hours old` or `no values at any site in the last 24 hours` | WARNING | The source may have stopped updating (normally the newest reading is about 3 hours old). Check the web page |
| `server sent a different value for N stored readings; stored values kept` | WARNING | Peabody changed past data. Ours is unchanged; see [Accepting a correction](#accepting-a-correction-from-peabody) |
| `GetTrendValues failed, refreshing session and retrying` | WARNING | Normal when the token expires. Only a concern if an error follows |
| `FetchError: … failed twice` or `SessionError: …` | ERROR | The run failed (exit code 1); nothing from the failed request was stored. If it keeps happening, the site may have changed or be blocking requests; see [Session and failures](#session-and-failures) |
| `Busy: another run is in progress` | ERROR | Another run held the lock, so this one was skipped |
| `backfill: stopped at YYYY-MM; …To resume: backfill --from …` | ERROR | Months before that one are stored. Run the command it gives |

## Backups and restore

On GitHub, the `backups` release keeps one copy per month instead (see [Running on GitHub](#running-on-github)). The
rest of this section is about runs on your own machine.

- **When:**
  - Before the first write of each day (Sydney date), the database is copied to
    `backups/readings-YYYY-MM-DD.db.gz`.
  - `backfill` always makes its own copy first: `readings-YYYY-MM-DDTHHMM-backfill.db.gz`.
  - Nothing is backed up while the database is empty.
- **How:** SQLite's online backup makes a consistent copy, which is gzip-compressed and then moved into place. A
  failed backup leaves no partial file and stops the run. A full copy is about 13 MB (the database is about 100 MB).
- **Retention**, applied after each backup, using the dates in the file names:
  - keep everything from the last 7 days, today included
  - older than that, keep the earliest backup of each calendar month, indefinitely
  - delete the rest. Other files in `backups/` are never touched

  That's about 90 MB for the dailies, plus 13 MB for each month that passes: roughly 250 MB after a year.
- **To restore:** stop cron (see [Running it on your own machine](#running-it-on-your-own-machine)), then
  `gunzip -c backups/<file>.db.gz > data/readings.db`, then run `backfill --from <the backup's date>` to catch up.

The CSVs aren't a backup: they're rewritten from the database on every run, so they'd carry any bad data too.

## Maintenance

### Filling a gap of more than 24 hours

```bash
.venv/bin/python -m extractor backfill --from 2026-09-27    # the last day collected, or earlier
```

Going back further than needed is harmless: readings already stored are left as they are.

### Accepting a correction from Peabody

Stored values are never changed (see [Storage](#storage)). If Peabody corrects past data and you want the corrected
values, delete that period and fetch it again:

```bash
cp data/readings.db data/readings-before-correction.db     # a copy to go back to (with cron stopped)
.venv/bin/python -c "
import sqlite3; c = sqlite3.connect('data/readings.db')
c.execute(\"DELETE FROM readings WHERE ts >= strftime('%s','2025-07-01') AND ts < strftime('%s','2025-07-03')\")
c.commit()"
.venv/bin/python -m extractor backfill --from 2025-07-01 --to 2025-07-03
```

The times in the `DELETE` are UTC. Delete the copy once you're happy with the result.

### When a site is added, renamed or removed

The first `fetch` each day compares the server's site list with `SITES` in
[extractor/config.py](extractor/config.py) and logs a warning if they differ. Collection carries on with the
configured sites, although a renamed or removed site will also make `fetch` fail, because every requested series
has to come back.

Update `SITES` (and `WATER_QUALITY` or `FLOW` if the parameters differ), run `check`, then backfill a new site's
history with `backfill`.

### Moving to another machine

Clone the repo, run `./setup.sh` (and `--cron` if wanted), then copy over `data/readings.db` (or restore a backup,
or download GitHub's copy as in [Working on a local copy](#working-on-a-local-copy)) and run
`backfill --from <last day collected>`. Or just run `backfill` to start again from scratch.

## How it works

### Collecting

The program calls the same JSON endpoint the page uses, `GetTrendValues`, directly: the page's HTML contains no
readings. One request covers all 18 series.

- **`fetch`** asks for the last 24 hours. The overlap between runs picks up readings that arrive late
  (normally about 3 hours after the fact). A run downloads about 40 KB.
- **`backfill`** walks from `--from` to `--to` a calendar month (UTC) at a time, about 1 MB per request, with 5
  seconds between requests. Each month is stored before the next is requested. If one fails, the months already
  done stay stored, and the log gives the command to resume. Months before the data starts come back empty, which
  is normal. At the end it logs the earliest stored reading. The CSVs are only rewritten when it finishes.
- **Afterwards,** `fetch` warns if the newest value is more than 12 hours old, and once a day checks the site list
  (`GetMappingData`). Both only log. The site check runs last, so it can never hold up collection.
- **One run at a time:** every command takes a lock on `state/run.lock`, which is released when the process exits,
  even if it crashes.

### Session and failures

Each request needs an anti-forgery token and cookie from the home page. They're cached in `state/session.json`
(readable only by you) and reused until a request fails. Tokens have lasted at least 48 hours.

A request has failed if there's a network error or 60-second timeout, the status isn't 200, or the body isn't what's
expected: every requested series exactly once, well-formed `[time, number or null]` pairs, and empty `errors`. The
status alone isn't enough, because server exceptions come back with HTTP 200.

On the first failure, the program fetches a new token and retries once. If the retry fails too, or a new token
can't be had (e.g. a Cloudflare challenge or a site redesign), the run stops with exit code 1 and logs the start of
the response. Empty values and nulls aren't failures.

### Storage

SQLite at `data/readings.db`, one row per reading:

| Column | Notes |
|---|---|
| `site` | `Upstream`, `LDP7 Water Treatment Plant`, `LDP8 Turkeys Nest` or `Downstream` |
| `parameter` | `ph`, `specific_conductivity`, `temperature`, `turbidity` or `flow_volume` |
| `ts` | Unix seconds, UTC. The server sends milliseconds, but every time checked was a whole second, so nothing is lost |
| `value` | REAL, or NULL where the server sent `null` |
| `fetched_at` | Unix seconds when this row was last written |

The primary key is (`site`, `parameter`, `ts`). After the backfill: about 1.92 million rows (1.29 million with
values), about 100 MB.

**The write-once rule: once a reading has a value, it's never changed.** New readings are added, and a stored null is
filled when a value arrives. Anything else the server sends for a stored reading is ignored, and the run logs a
warning with up to 10 examples (`stored 7.0, sent 0.0`). This protects the data from a glitch, such as a response
that suddenly reads 0.0 everywhere. The trade-off is that genuine corrections by Peabody are ignored too, unless you
[accept them deliberately](#accepting-a-correction-from-peabody). Rows are never deleted by the program.

Each `fetch` writes in one transaction, and so does each month of a `backfill`, so a run that fails part-way leaves
no partial write.

### Being polite to the server

- One request per `fetch`, plus one small site-list request (about 2 KB). On GitHub that's 8 of each a day (every
  3 hours); on your own machine, 24 fetches (hourly by cron) and one site-list request a day.
- `backfill`: one request every 5 seconds.
- User-Agent: a current desktop Chrome string (`USER_AGENT` in `config.py`).
- This is Peabody's public disclosure page.

## About the data

Observed while building this (September 2026):

- **Start of the data:** water quality from **2023-08-08 06:26 UTC** (16:26 in Sydney). Upstream's first readings
  are null. Flow starts later: LDP7 from 1 Jan 2024 (Sydney time), LDP8 from 12 Jan 2024.
- **Timestamps:** every 15 minutes, on the :00/:15/:30/:45 marks (UTC) since 2024-02-13 21:45 UTC. Before that,
  the water-quality readings were offset from the marks, for example at :10/:25/:40/:55, a few seconds past the
  mark, or 06:26:09 for the very first reading. They're stored as sent.
  - The 16 water-quality series always share timestamps, so they line up across all four sites.
  - Flow was on the marks from the start, so in January and early February 2024 flow and water quality at LDP7
    (and LDP8 on two days) have different timestamps.
- **History kept by the server:** at least 3 years so far. The page's date picker stops at 3 years, but the API
  returned everything from 2023-08-08 onwards.
- **Gaps and nulls:** normal. For example, Downstream pH over a year was about 9% null, with 9 gaps of 4–16 hours
  with no records at all.
- **LDP7 Water Treatment Plant:** everything, flow included, is null except while it discharges (the page says so
  too). In the year to September 2026 there were 4 discharge events (January, late February to early March, and late
  May 2026), with flow of 10–35,660 L per interval (up to about 40 L/s). The largest day on record is 2 July 2025,
  at about 2.28 ML.
- **LDP8 Turkeys Nest:** its water-quality readings run continuously. Flow records are sparse until 2024-03-18.
  Flow is 0.0 almost everywhere: 180 non-zero readings in the whole history, in February, May–June and December
  2024 and early January 2025.
- **Values that look wrong, kept as sent:**
  - LDP8 flow of exactly 2,059,407.625 L in a single interval (about 2,300 L/s), several times between 30 December
    2024 and 5 January 2025. Most likely a meter glitch.
  - Downstream conductivity sometimes reads 0.0.

## Known limitations

- **Alerts only for failures:** on GitHub, a failed run is emailed, but warnings (such as stale data) only appear in
  the run logs, and runs that stop happening aren't reported at all. On your own machine, everything is only in `logs/fetch.log`.
- **Gaps over 24 hours need a manual `backfill`:** after a GitHub outage, a disabled schedule, or, on your own
  machine, time spent switched off or asleep.
- **Corrections by Peabody are ignored** by design, unless accepted by hand.
- **Null and missing look the same in the CSVs** (both empty cells).
- **Unknown token lifetime and possible bot protection:** handled by refreshing on failure. A Cloudflare challenge
  or a site redesign would stop collection with a `SessionError` or `FetchError`. The fallback would be a headless
  browser capturing the same responses.

## API reference

The page is a gHost dashboard over an AVEVA PI server (data server `PEABODYAF`). The findings below come from the
tests in [api-tests/README.md](api-tests/README.md) (T01–T18).

### Getting a session

`GET https://peabody.ghost.site/` sets a cookie (`__orchantiforgery_<id>`), and the HTML contains
`<input name="__RequestVerificationToken" type="hidden" value="CfDJ8...">` (use the first match). Both are needed on
every data request, from the same page load; without them the server returns HTTP 400 with the home page as the
body. No browser headers are needed.

### GetTrendValues

`POST https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues`, as form fields:

| Field | Value |
|---|---|
| `__RequestVerificationToken` | the token |
| `dataserver` | `PEABODYAF` |
| `overrideTimezoneID` | `Etc/UTC` |
| `trendsinput` | JSON, as below |

```json
{"trends": [
  {"starttimestamp": "2026-09-24T08:00:00", "endtimestamp": "2026-09-25T08:00:00",
   "tagName": "Metropolitan Water Monitoring\\Downstream|pH", "id": "Downstream|pH"},
  ...
]}
```

- **Tag names:** `Metropolitan Water Monitoring\<site>|<attribute>`, with attributes `pH`,
  `Specific Electrical Conductivity|Display`, `Temperature`, `Turbidity|Display` and
  `Instantaneous Volume Discharged` (flow).
- **`id`:** any string, echoed back. We use `<site>|<attribute>`.
- **Times:** `YYYY-MM-DDTHH:MM:SS`, read in the `overrideTimezoneID` zone (Sydney if it's left out). A `Z` or an
  offset makes the server throw an exception. We send UTC, which avoids the repeated hour when daylight saving ends.
  Both ends of the range are included.
- **Size:** all 18 tags work in one request. One request can cover at least a year of one tag (about 1.2 MB).
- **Optional fields to leave out:** `PerformRounding` and `DecimalPlaces` round the values; `BoundaryMode` and
  `SamplingInterval` return calculated values instead of real readings.

The response body is a JSON **string** containing JSON, so it's decoded twice:

```json
"{\"trends\":[{\"id\":\"Downstream|pH\",\"tags\":[{\"name\":\"Metropolitan Water Monitoring\\\\Downstream|pH\",
  \"values\":[[1790236800000,7.7627],[1790237700000,null],...]}],\"errors\":[]}],\"errors\":[]}"
```

`values` holds `[epoch milliseconds (UTC), number or null]` pairs. Times with no record are left out, and an empty
list just means no data in that range. `errors` (top level and per trend) was always `[]` in testing.

| Failure | HTTP status | Body |
|---|---|---|
| Missing or invalid token or cookie | 400 | The HTML home page (about 18 KB) |
| Server exception, e.g. a bad time format | **200** | `{"Message":"An error has occurred.","ExceptionMessage":…,"StackTrace":…}` |

### Other endpoints

- **`POST /gHostModules/Mapping/GetMappingData`** (fields: token, `input` = the map's config JSON, `start`, `end`):
  the sites with display name, coordinates and asset path (`GroupSelectionResult`). The body is plain JSON, not
  double-encoded. Display names differ from asset names ("Water Treatment Plant" vs "LDP7 Water Treatment Plant"),
  so the site check compares the last part of the asset path.
- **`GetSingleValues`:** declared in the page but never called, request format unknown. Not needed.
- **`…|pH|Low Limit` and `|High Limit` tags:** return no data.

## Development

### Layout

| Path | Contents |
|---|---|
| [extractor/config.py](extractor/config.py) | Sites, tags, paths and settings |
| [extractor/session.py](extractor/session.py) | Token and cookie |
| [extractor/client.py](extractor/client.py) | Requests, response checks and the retry |
| [extractor/store.py](extractor/store.py) | The database and the write-once upsert |
| [extractor/backup.py](extractor/backup.py) | Backups and retention |
| [extractor/export.py](extractor/export.py) | The CSVs |
| [extractor/sites.py](extractor/sites.py) | The daily site-list check |
| [extractor/cli.py](extractor/cli.py) | The commands, the run lock and the stale-data warning |
| [setup.sh](setup.sh), [requirements.txt](requirements.txt) | Setup. `requests` and `tzdata` are pinned |
| [tests/](tests/) | Unit tests, with saved API responses in `tests/fixtures/` |
| [api-tests/](api-tests/) | The original API tests: plan, request bodies, findings and `summarise.py`. The saved responses in `results/` are kept locally and git-ignored |
| [.github/workflows/collect.yml](.github/workflows/collect.yml) | Collects every 3 hours and publishes the data (see [Running on GitHub](#running-on-github)) |
| [.github/workflows/tests.yml](.github/workflows/tests.yml) | Runs the tests on GitHub |
| [.github/workflows/live-check.yml](.github/workflows/live-check.yml) | Runs `check` against the live site from GitHub, started by hand. Stores nothing |
| [.github/dependabot.yml](.github/dependabot.yml) | Monthly update PRs for the pinned requirements and the workflow actions |

Everything the program creates stays inside the repo folder and is git-ignored:

| Folder | Contents |
|---|---|
| `data/` | `readings.db` |
| `backups/` | `readings-*.db.gz` |
| `output/` | the CSVs |
| `state/` | `session.json` (token and cookie), `run.lock`, `sites-checked` (date of the last site check) |
| `logs/` | `fetch.log` (from cron) and any logs you keep from manual runs |

### Settings

In [extractor/config.py](extractor/config.py):

| Setting | Default | Meaning |
|---|---|---|
| `SITES`, `WATER_QUALITY`, `FLOW` | the 4 sites and 5 parameters | What's collected |
| `LOCAL_BACKUPS` | on | Local backups (see [Backups and restore](#backups-and-restore)). Off when the environment variable `EXTRACTOR_LOCAL_BACKUPS` is `off`, as on GitHub |
| `LOCAL_TIMEZONE` | `Australia/Sydney` | For backup dates, the daily site check and `timestamp_local` |
| `BACKUP_KEEP_DAYS` | 7 | Days of daily backups kept in full |
| `BACKFILL_PAUSE` | 5 | Seconds between backfill requests |
| `STALE_HOURS` | 12 | Age of the newest value that triggers a warning |
| `TIMEOUT` | 60 | Seconds per HTTP request |

`setup.sh` checks for Python 3.10+ (set `PYTHON=/path/to/python3` to choose one), creates `.venv`, installs the
requirements and creates the working folders. With `--cron` it adds the cron line only if it isn't there, and stops
without writing if the existing crontab can't be read. It's safe to run again.

### Tests

```bash
.venv/bin/python -m unittest
```

68 tests, standard library only, no network. GitHub Actions runs them on every push and pull request, on Python
3.10 and 3.13 ([.github/workflows/tests.yml](.github/workflows/tests.yml)). The fixtures are real responses: `all-series-1-day.json` (T05),
`empty-values.json` (T09), `http-400-error-page.html` (T02), `server-exception.json` (T13) and `site-list.json`
(a `GetMappingData` response from 2026-09-27).

| File | Covers |
|---|---|
| `test_store.py` | The write-once rule, and rollback on failure |
| `test_backup.py` | Backups, restoring one, and retention |
| `test_export.py` | CSV layout, rows exactly as stored, Sydney offsets across daylight saving, a failed write |
| `test_sites.py` | The site-list check |
| `test_client.py` | Response checks, token refresh and retry, all four commands, the run lock, the stale-data warning and turning local backups off |

### How it was checked

- Unit tests as above.
- **Live runs (27 September 2026):**
  - The token refreshed after being corrupted on purpose.
  - A backup restored identical to the database it was made from.
  - The full backfill (45 requests) completed without errors.
  - A `fetch` was turned away while a `backfill` held the lock.
- **CSVs against the source:** three 24-hour windows were fetched fresh from the API and compared cell by cell with
  the CSVs; all matched. They were 25 May 2026, 2 July 2025 and a day in October 2023 with offset timestamps. On
  28 September 2026, 2 July 2025 at LDP7 was also checked by eye against the web page, and matched.

## Sensitive files

`state/session.json` holds the current session token and cookie. Re-running the API tests in `api-tests/` creates
`cookies.txt`, `token.txt` and `page.html` there, which hold them too. All are in `.gitignore`, so they stay out of
version control. Don't share them. The GitHub repo also has secret scanning and push protection turned on. On
GitHub, the session is fetched fresh in each run and thrown away with the runner: it's never uploaded.

The browser captures used to work out the API (`website.mhtml`, `har`, `GetTrendValues`) were deleted on 2026-09-28,
once everything learned from them was in this README.
