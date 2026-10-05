# Dashboard

A static page over `output/metrics.json` and the per-site CSVs (README: Metrics). No build step, no server-side
code, no new Python dependency — plain `fetch()` and [Chart.js](https://www.chartjs.org/) from a CDN.

**Published to GitHub Pages** by [.github/workflows/pages.yml](../.github/workflows/pages.yml) — see the main
README's "[The dashboard on GitHub Pages](../README.md#the-dashboard-on-github-pages)" for the URL and how that
deploy works. This page can also be previewed locally against your own copy of the data, which is useful for
checking a change before it's pushed.

## Preview it locally

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

## Known simplifications

- The four time-series charts (conductivity, turbidity, pH, flow) parse the full per-site CSV client-side and
  then slice to the chosen window. That's sub-second locally, but on the deployed page every visitor downloads
  the complete multi-year CSV (several MB) just to show, say, the last 24 hours — fine for occasional personal
  use, but worth replacing with a server-aggregated "recent readings" file if this ever gets real traffic. There's
  no "all-time" option on those charts for the same reason; the chronic trend panel is the all-time view, built
  from `metrics.json`'s small daily buckets instead.
- No table-view fallback for the time-series charts themselves (the flagged-periods and data-health panels do
  have tables).
- Hover gives a tooltip (Chart.js default) but not a full crosshair line across all four series.
- Paths in `app.js` are relative (`../output/...`), deliberately, so the same code works unmodified whether the
  page is served from the repo root locally or from a GitHub Pages project site under a `/<repo>/` prefix — don't
  change these back to a leading-slash absolute path, which breaks under that prefix.
