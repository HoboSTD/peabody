# GetTrendValues API tests

These tests find out how little is needed to call
`https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues` from a script, without a browser.
Run them in order. Record each outcome in that test's **Result** block.

## How the commands are laid out

Each request sends four form fields. The awkward one, `trendsinput`, is JSON, and it's kept in a readable file under
`bodies/`. curl's `--data-urlencode "trendsinput@bodies/<file>.json"` reads that file and encodes it for you.
To change a request, edit or copy the JSON file; you don't need to touch the curl command.

In each command:
- `-o results/Txx.json` saves the response. The saved responses aren't in the git repo (they're real site data),
  so run `mkdir -p results` first in a fresh clone. The **Result** blocks record what they showed.
- `-w '%{http_code}\n'` prints the HTTP status. `200` means success.
- `python3 summarise.py results/Txx.json` prints the point count, first and last timestamps, the interval between
  points, and any errors.

Run everything from this folder: `cd ~/peabody/api-tests`

Wait a few seconds between tests. This is someone else's production server.

## Setup: get a token and cookie

Every request needs an anti-forgery **token** (sent as a form field) and a matching **cookie**. The two are issued
together.

### S1. Fetch them without a browser (preferred)

This also tests whether Cloudflare allows plain curl to load the page.

```bash
curl -sS -c cookies.txt -o page.html -w '%{http_code}\n' https://peabody.ghost.site/
grep -o 'name="__RequestVerificationToken" type="hidden" value="[^"]*"' page.html | head -1 | sed 's/.*value="//; s/"$//' > token.txt
cat token.txt
cat cookies.txt
```

It worked if the status is `200`, `token.txt` holds a long `CfDJ8...` string and `cookies.txt` has a line containing
`__orchantiforgery_`.

Then set these variables. Repeat this in every new terminal window:

```bash
TOKEN=$(cat token.txt)
COOKIE=cookies.txt
```

**Result S1:**
- HTTP status: 200
- Token found (y/n): y
- Cookie found (y/n): y
- Notes (e.g. Cloudflare challenge page in page.html): page.html appears to be the peabody site - "<title>Peabody gHost Portal - Home</title>".

### S2. Fallback: reuse the browser's token and cookie

Use this only if S1 failed. Take the values from the `GetTrendValues` cURL file you saved:

```bash
TOKEN='<value after __RequestVerificationToken= in --data-raw, up to the first &>'
COOKIE='<the whole string inside -b '"'"'...'"'"', i.e. __orchantiforgery_...=CfDJ8...>'
```

(curl's `-b` accepts either a file name or a literal `name=value` string, so the commands below work either way.)

---

## Part A: what does a request need?

### T01. Baseline: token + cookie, no browser headers

Same request as the browser sample (Downstream pH, 24–25 Sep) with none of the browser's extra headers.

```bash
curl -sS -o results/T01.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/downstream-ph-1d.json" \
  --data-urlencode "overrideTimezoneID=Australia/Sydney" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T01.json
python3 summarise.py results/sample-from-browser.json
```

Expected: the same summary as the browser sample (87 points, 18:00 → 15:30 AEST, 900 s intervals). There may be
more points if new data has arrived since.

**Result T01:**
- HTTP status: 200
- Matches browser sample (y/n): y
- Notes:

### T01b. Baseline with browser headers (only if T01 failed)

```bash
curl -sS -o results/T01b.json -w '%{http_code}\n' -b "$COOKIE" \
  -H 'x-requested-with: XMLHttpRequest' \
  -H 'origin: https://peabody.ghost.site' \
  -H 'referer: https://peabody.ghost.site/' \
  -A 'Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36' \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/downstream-ph-1d.json" \
  --data-urlencode "overrideTimezoneID=Australia/Sydney" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T01b.json
```

If this works where T01 didn't, remove the `-H`/`-A` lines one at a time to find which one is required.

**Result T01b:**
- HTTP status:
- Headers that turned out to be required:

### T02. No cookie

```bash
curl -sS -o results/T02.json -w '%{http_code}\n' \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/downstream-ph-1d.json" \
  --data-urlencode "overrideTimezoneID=Australia/Sydney" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T02.json
```

Expected: an error such as `400`. If it returns data, the cookie isn't needed.

**Result T02:**
- HTTP status: 400
- Cookie required (y/n): y?

### T03. No token

```bash
curl -sS -o results/T03.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/downstream-ph-1d.json" \
  --data-urlencode "overrideTimezoneID=Australia/Sydney" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T03.json
```

**Result T03:**
- HTTP status: 400
- Token required (y/n): y?

### T04. Minimal trend fields

`bodies/downstream-ph-1d-minimal.json` sends only `starttimestamp`, `endtimestamp`, `tagName` and `id`. It leaves out
`PerformRounding`, `DecimalPlaces`, `BoundaryMode` and `SamplingInterval`.

```bash
curl -sS -o results/T04.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/downstream-ph-1d-minimal.json" \
  --data-urlencode "overrideTimezoneID=Australia/Sydney" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T04.json
```

**Result T04:**
- HTTP status: 200
- Same data as T01 (y/n): y
- Notes:

---

## Part B: batching and time ranges

### T05. All 18 tags in one request

`bodies/all-tags-1d.json` asks for every site and parameter you need (4 + 5 + 5 + 4 tags) in one `trends` array. The
browser sends one tag per request, so this tests whether the server accepts several.

```bash
curl -sS -o results/T05.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/all-tags-1d.json" \
  --data-urlencode "overrideTimezoneID=Australia/Sydney" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T05.json
```

Expected: 18 `trend id=...` blocks. Each `id` is the tag name, so you can tell which is which.

**Result T05:**
- HTTP status: 200
- Number of trends returned: 18
- Any trends with errors or 0 points (list them): none
- Is the flow unit litres, and does the value look like a per-interval volume?: not sure, please investigate
  - *Claude:* Can't tell from this day. LDP7 flow is null for all 88 points (not discharging, as the page's note
    says) and LDP8 flow is 0.0 for all 88 points. The only evidence for the unit is the page's table label,
    "Flow Volume (L)". T17 looks for a period with non-zero flow.

### T06–T08. Longer ranges (checking for downsampling)

Same tag, with 7-day, 30-day and 1-year ranges. At 15-minute intervals, the full counts would be about 673, 2,881 and
35,041 points. Look at the point count and the `intervals` line. If the interval grows (e.g. 3600 s or more) or the
count stops at a round number, the server is downsampling or capping the results.

```bash
for T in "T06 downstream-ph-7d" "T07 downstream-ph-30d" "T08 downstream-ph-1y"; do
  set -- $T
  curl -sS -o results/$1.json -w "$1 %{http_code} %{time_total}s\n" -b "$COOKIE" \
    --data-urlencode "__RequestVerificationToken=$TOKEN" \
    --data-urlencode "dataserver=PEABODYAF" \
    --data-urlencode "trendsinput@bodies/$2.json" \
    --data-urlencode "overrideTimezoneID=Australia/Sydney" \
    https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
  python3 summarise.py results/$1.json
  sleep 3
done
```

**Result T06 (7 days):**
- HTTP status / time: 200
- Points / interval: 663 (intervals (seconds: count): {900: 662})

**Result T07 (30 days):**
- HTTP status / time: 200
- Points / interval: 2791 (intervals (seconds: count): {900: 2787, 15300: 2, 44100: 1})

**Result T08 (1 year):**
- HTTP status / time: 200
- Points / interval: 34806 (intervals (seconds: count): {900: 34796, 15300: 3, 14400: 2, 57600: 1, 4500: 1})
- Conclusion: the largest range that still returns 15-minute data: not sure, please conclude on my behalf
  - *Claude:* **At least 1 year, with no downsampling.** Nearly every interval is 900 s. The few longer intervals are
    9 real gaps in the record (4 h to 16 h, e.g. 29 Jan 2026 12:30 → 30 Jan 04:30), not a coarser sampling rate.
    The year also has 3,212 `null` points. One request for 1 year of one tag returned about 1.2 MB. No limit was
    reached, but a backfill should still use smaller chunks (e.g. 1 month × all tags) to keep responses modest.

### T09. Old data (January 2023)

The page limits its date picker to 3 years back. This checks whether the API has data from before then.

```bash
curl -sS -o results/T09.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/downstream-ph-2023.json" \
  --data-urlencode "overrideTimezoneID=Australia/Sydney" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T09.json
```

**Result T09:**
- HTTP status: 200
- Data present (y/n), points: n, 0

### T10. SamplingInterval = 1h

The browser always sends `"SamplingInterval": ""`. This tests whether a value makes the server return hourly
samples. If `1h` gives an error or no change, edit the JSON file and try `01:00:00`, then `3600`.

```bash
curl -sS -o results/T10.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/downstream-ph-7d-hourly.json" \
  --data-urlencode "overrideTimezoneID=Australia/Sydney" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T10.json
```

`1h`:
- HTTP status: 200
- Points / interval: 169 (intervals (seconds: count): {3600: 168})

`01:00:00`:
- HTTP status: 200
- Points / interval: 169 (intervals (seconds: count): {3600: 168})

`3600`:
- HTTP status: 200
- Points / interval: 2 (intervals (seconds: count): {604800: 1})

**Result T10:**
- HTTP status: 200
- Interval compared with T06: 168 compared to 662
- Value format that worked: `1h`, `01:00:00`

---

## Part C: time zones and timestamp formats

In T01, the request asked for `2026-09-24T18:00:00` in `Australia/Sydney` time, and the first point returned was
`1790236800000` (epoch milliseconds), which is 08:00 UTC or 18:00 AEST. So request times are local and response times
are UTC epoch milliseconds. These tests confirm that.

### T11. Time zone set to UTC

Same body as T01, but with `overrideTimezoneID=Etc/UTC`. If the zone is respected, the first point should shift 10
hours later, to 18:00 UTC.

```bash
curl -sS -o results/T11.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/downstream-ph-1d.json" \
  --data-urlencode "overrideTimezoneID=Etc/UTC" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T11.json
```

**Result T11:**
- HTTP status: 200
- First timestamp: `2026-09-24 18:00 UTC / 2026-09-25 04:00 AEST`

### T12. No time zone field

```bash
curl -sS -o results/T12.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/downstream-ph-1d.json" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T12.json
```

**Result T12:**
- HTTP status: 200
- First timestamp (which zone does the server default to?): `first: 2026-09-24 08:00 UTC / 2026-09-24 18:00 AEST`

### T13. UTC timestamps with a `Z` suffix

The body asks for `2026-09-24T08:00:00Z` → `2026-09-25T08:00:00Z`, which is the same period as T01 written in UTC.

```bash
curl -sS -o results/T13.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/downstream-ph-1d-utc-z.json" \
  --data-urlencode "overrideTimezoneID=Australia/Sydney" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T13.json
```

**Result T13:**
- HTTP status: 200
- First timestamp (same as T01?): None, an error occurred.

```
Not a GetTrendValues response. Top-level structure:
{
 "Message": "An error has occurred.",
 "ExceptionMessage": "The UTC Offset of the local dateTime parameter does not match the offset argument.\r\nParameter name: offset",
 "ExceptionType": "System.ArgumentException",
 "StackTrace": "   at System.DateTimeOffset..ctor(DateTime dateTime, TimeSpan offset)\r\n   at gHostDataService.Controllers.DataAccessController.<GetTrendValues>d__2.MoveNext() in C:\\Users\\Harry\\source\\repos\\gHostDataService\\gHostDataService\\Controllers\\DataAccessController.cs:line 302\r\n--- End of stack trace from previous location where exception was thrown ---\r\n   at System.Runtime.ExceptionServices.ExceptionDispatchInfo.Throw()\r\n   at System.Runtime.CompilerServices.TaskAwaiter.HandleNonSuccessAndDebuggerNotification(Task task)\r\n   at System.Threading.Tasks.TaskHelpersExtensions.<CastToObject>d__1`1.MoveNext()\r\n--- End of stack trace from previous location where exception was thrown ---\r\n   at System.Runtime.ExceptionServices.ExceptionDispatchInfo.Throw()\r\n   at System.Runtime.CompilerServices.TaskAwaiter.HandleNonSuccessAndDebuggerNotification(Task task)\r\n   at System.Web.Http.Controllers.ApiControllerActionInvoker.<InvokeActionAsyncCore>d__1.MoveNext()\r\n--- End of stack trace from previous location where exception was thrown ---\r\n   at System.Runtime.ExceptionServices.ExceptionDispatchInfo.Throw()\r\n   at System.Runtime.CompilerServices.TaskAwaiter.HandleNonSuccessAndDebuggerNotification(Task task)\r\n   at System.Web.Http.Controllers.ActionFilterResult.<ExecuteAsync>d__5.MoveNext()\r\n--- End of stack trace from previous location where exception was thrown ---\r\n   at System.Runtime.ExceptionServices.ExceptionDispatchInfo.Throw()\r\n   at System.Runtime.CompilerServices.TaskAwaiter.HandleNonSuccessAndDebuggerNotification(Task task)\r\n   at System.Web.Http.Dispatcher.HttpControllerDispatcher.<SendAsync>d__15.MoveNext()"
}
```

---

## Part D: extras

### T14. pH limits (optional)

In the HAR, the Low Limit and High Limit responses were very small (about 200 bytes), so they may hold one constant
value each.

```bash
curl -sS -o results/T14.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/ph-limits-1d.json" \
  --data-urlencode "overrideTimezoneID=Australia/Sydney" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T14.json
```

**Result T14:**
- HTTP status: 200
- Low / high limit values: no results returned

### T15. GetMappingData (site list)

The map's request. Its response probably lists the monitoring locations with coordinates, status colour and name. That
could be a way to discover sites instead of hard-coding them.

```bash
curl -sS -o results/T15.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "input@bodies/map-input.json" \
  --data-urlencode "start=2026-09-24T18:00:00" \
  --data-urlencode "end=2026-09-25T18:00:00" \
  https://peabody.ghost.site/gHostModules/Mapping/GetMappingData
python3 summarise.py results/T15.json
```

**Result T15:**
- HTTP status: 200
- What the response contains:

```
{
 "layers": [
  {
   "LayerName": "Unassigned Sites",
   "ShowOnLoad": true,
   "MarkerConfiguration": {},
   "features": [
    {
     "paths": [],
     "strokeColor": "-",
     "fillColor": "-",
     "strokeOpacity": 0.8,
     "strokeWeight": 2,
     "fillOpacity": 0.3,
     "featureValues": [],
     "featureMetadata": {},
     "Latitude": -34.187603,
     "Longitude": 151.002612,
     "Name": "Downstream",
     "ToggleOffClass": "monitoringLocation",
     "ToggleOnId": "showDownstream",
     "GroupSelectionID": "",
     "GroupSelectionResult": "Metropolitan Water Monitoring\\\\Downstream",
     "MarkerURL": "gHostDefaultMarker"
    },
    {
     "paths": [],
     "strokeColor": "-",
     "fillColor": "-",
     "strokeOpacity": 0.8,
     "strokeWeight": 2,
     "fillOpacity": 0.3,
     "featureValues": [],
     "featureMetadata": {},
     "Latitude": -34.187534129,
     "Longitude": 150.993714596,
     "Name": "Water Treatment Plant",
     "ToggleOffClass": "monitoringLocation",
     "ToggleOnId": "showLDP7",
     "GroupSelectionID": "",
     "GroupSelectionResult": "Metropolitan Water Monitoring\\\\LDP7 Water Treatment Plant",
     "MarkerURL": "gHostDefaultMarker"
    },
    {
     "paths": [],
     "strokeColor": "-",
     "fillColor": "-",
     "strokeOpacity": 0.8,
     "strokeWeight": 2,
     "fillOpacity": 0.3,
     "featureValues": [],
     "featureMetadata": {},
     "Latitude": -34.186903601,
     "Longitude": 150.998720524,
     "Name": "Turkeys Nest",
     "ToggleOffClass": "monitoringLocation",
     "ToggleOnId": "showLDP8",
     "GroupSelectionID": "",
     "GroupSelectionResult": "Metropolitan Water Monitoring\\\\LDP8 Turkeys Nest",
     "MarkerURL": "gHostDefaultMarker"
    },
    {
     "paths": [],
     "strokeColor": "-",
     "fillColor": "-",
     "strokeOpacity": 0.8,
     "strokeWeight": 2,
     "fillOpacity": 0.3,
     "featureValues": [],
     "featureMetadata": {},
     "Latitude": -34.188792826,
     "Longitude": 150.992383937,
     "Name": "Upstream",
     "ToggleOffClass": "monitoringLocation",
     "ToggleOnId": "showUpstream",
     "GroupSelectionID": "",
     "GroupSelectionResult": "Metropolitan Water Monitoring\\\\Upstream",
     "MarkerURL": "gHostDefaultMarker"
    }
   ]
  }
 ]
}
```

### T16. Token lifetime

Re-run **T01** (as `results/T16a.json` and `T16b.json`) without repeating setup:
- T16a: at least 1 hour after S1
- T16b: the next day

```bash
curl -sS -o results/T16a.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/downstream-ph-1d.json" \
  --data-urlencode "overrideTimezoneID=Australia/Sydney" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T16a.json
```

**Result T16a (+1 h):**
- HTTP status: 200

**Result T16b (+1 day):**
- HTTP status:
- Conclusion: can a token be reused, or should each run fetch a new one?

---

## Part E: follow-ups

### T17. Find non-zero flow (flow unit)

Asks for 1 year of flow at both discharge points so we can find periods of real discharge. Look at the `min`/`max`
lines. The script below lists the first few non-zero readings so you can see whether the values look like litres per
15-minute interval (they should vary and add up to plausible daily totals) or like a rate.

```bash
python3 - <<'EOF' > bodies/flow-1y.json
import json
R = 'Metropolitan Water Monitoring\\'
print(json.dumps({"trends": [
    {"starttimestamp": "2025-09-25T18:00:00", "endtimestamp": "2026-09-25T18:00:00",
     "tagName": R + s + "|Instantaneous Volume Discharged", "id": s}
    for s in ("LDP7 Water Treatment Plant", "LDP8 Turkeys Nest")]}))
EOF
curl -sS -o results/T17.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/flow-1y.json" \
  --data-urlencode "overrideTimezoneID=Australia/Sydney" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 summarise.py results/T17.json
python3 -c "
import json
d = json.loads(json.loads(open('results/T17.json').read()))
for t in d['trends']:
    nz = [v for v in t['tags'][0]['values'] if v[1]]
    print(t['id'], len(nz), 'non-zero readings; first 10:', nz[:10])
"
```

**Result T17:**
- Non-zero readings at LDP7 / LDP8: 322 / 0
- Example values: LDP7 - `[[1768627800000, 14374.2275390625], [1768628700000, 2272.11376953125], [1768629600000, 28534.794921875], [1768630500000, 30130.974609375], [1768631400000, 24543.49609375], [1768632300000, 32603.982421875], [1768633200000, 24443.8203125], [1768634100000, 28814.30859375], [1768635000000, 20104.30859375], [1768635900000, 14288.6171875]]`

### T18. Earliest available data

T09 (January 2023) returned no data. This asks for 2 years of Upstream pH at hourly sampling (to keep the response
small) and shows where the data starts.

```bash
python3 - <<'EOF' > bodies/upstream-ph-2y-hourly.json
import json
print(json.dumps({"trends": [{"starttimestamp": "2023-09-25T00:00:00", "endtimestamp": "2025-09-26T00:00:00",
    "tagName": "Metropolitan Water Monitoring\\Upstream|pH", "id": "t1", "SamplingInterval": "1h"}]}))
EOF
curl -sS -o results/T18.json -w '%{http_code}\n' -b "$COOKIE" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "dataserver=PEABODYAF" \
  --data-urlencode "trendsinput@bodies/upstream-ph-2y-hourly.json" \
  --data-urlencode "overrideTimezoneID=Australia/Sydney" \
  https://peabody.ghost.site/gHostModules/DataAccess/GetTrendValues
python3 -c "
import json
from datetime import datetime, timezone
d = json.loads(json.loads(open('results/T18.json').read()))
v = [x for x in d['trends'][0]['tags'][0]['values'] if x[1] is not None]
print('first non-null:', datetime.fromtimestamp(v[0][0] / 1000, tz=timezone.utc) if v else 'none')
"
```

**Result T18:**
- First non-null timestamp: `2023-09-24 14:00:00+00:00`
  - *Claude:* That's the first hour of the query window (2023-09-25 00:00 AEST), so data goes back at least that far.
    With T09 (nothing in early January 2023), the start is somewhere between 2023-01-08 and 2023-09-25. The backfill
    will find the exact date.

---

## Files that contain session tokens

`cookies.txt`, `token.txt` and `page.html` (created by the setup step) hold anti-forgery tokens and cookies. These
come from an anonymous public page, so the risk is low, but keep them out of version control and out of anything you
share. The browser captures `../har` and `../GetTrendValues` mentioned above were deleted on 2026-09-28 (see the main
README).
