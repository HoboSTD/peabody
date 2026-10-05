# Local dashboard

A static page over `output/metrics.json` and the per-site CSVs (README: Metrics). No build step, no server-side
code, no new Python dependency — plain `fetch()` and [Chart.js](https://www.chartjs.org/) from a CDN.

**This is stage 3 of the metrics plan: local-only, not deployed anywhere.** See the README's "Metrics" section
for what's actually being computed.

## Preview it

```bash
.venv/bin/python -m extractor analyze && .venv/bin/python -m extractor export   # fresh metrics.json and CSVs
.venv/bin/python -m http.server 8000                                            # from the repo root
```

Then open <http://localhost:8000/dashboard/>. It has to be served over `http://`, not opened as a `file://` path
— browsers refuse `fetch()` of local files under `file://` entirely, which would otherwise look like a CORS error.

## What to check

- Every panel shows live numbers, not placeholders: the headline tiles, all four sites on each chart, the window
  toggle (24h/7d/30d/90d) actually changing the charted range.
- The flagged-periods table lists real entries — in particular a high-confidence period around **24 December
  2023** (the publicly documented spill) and elevated-but-lower-confidence periods around **August 2023** (a
  documented embankment collapse).
- The data-health numbers are in the right ballpark: LDP7 around 10% complete (it only reads while discharging),
  the others high-90s/high-80s.
- Dark mode: switch your OS theme and confirm the page follows (the palette has separate light/dark values, not
  an inverted filter).

## Known simplifications (this stage only)

- The four time-series charts (conductivity, turbidity, pH, flow) parse the full per-site CSV client-side and
  then slice to the chosen window — fine locally (sub-second), but not how this would work once the dashboard is
  ever served over the network. There's no "all-time" option on those charts for the same reason; the chronic
  trend panel is the all-time view, built from `metrics.json`'s small daily buckets instead.
- No table-view fallback for the time-series charts themselves (the flagged-periods and data-health panels do
  have tables). Fine for a local, single-person preview; worth adding before this goes anywhere more public.
- Hover gives a tooltip (Chart.js default) but not a full crosshair line across all four series.
