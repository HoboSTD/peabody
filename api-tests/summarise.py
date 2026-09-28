#!/usr/bin/env python3
"""Print a short summary of a saved GetTrendValues / GetMappingData response.

Usage: python3 summarise.py results/T01.json
"""
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")


def fmt(ms):
    utc = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return f"{utc:%Y-%m-%d %H:%M} UTC / {utc.astimezone(SYDNEY):%Y-%m-%d %H:%M %Z}"


path = sys.argv[1]
raw = open(path, encoding="utf-8").read()
print(f"File: {path} ({len(raw)} bytes)")

try:
    data = json.loads(raw)
    # The server returns a JSON string that itself contains JSON.
    if isinstance(data, str):
        data = json.loads(data)
except json.JSONDecodeError:
    print("Not JSON. First 500 characters:")
    print(raw[:500])
    sys.exit(1)

if "trends" not in data:
    print("Not a GetTrendValues response. Top-level structure:")
    print(json.dumps(data, indent=1)[:3000])
    sys.exit(0)

print(f"Top-level errors: {data.get('errors')}")
for trend in data["trends"]:
    print(f"- trend id={trend.get('id')} errors={trend.get('errors')}")
    for tag in trend.get("tags") or []:
        values = tag.get("values") or []
        numbers = [v for _, v in values if isinstance(v, (int, float))]
        print(f"    tag: {tag.get('name')}")
        print(f"      points: {len(values)}  non-null: {len(numbers)}  null: {len(values) - len(numbers)}")
        if not values:
            continue
        print(f"      first: {fmt(values[0][0])}")
        print(f"      last:  {fmt(values[-1][0])}")
        gaps = Counter((b[0] - a[0]) // 1000 for a, b in zip(values, values[1:]))
        print(f"      intervals (seconds: count): {dict(gaps.most_common(5))}")
        if numbers:
            print(f"      min: {min(numbers)}  max: {max(numbers)}")
        other = {type(v).__name__ for _, v in values if v is not None and not isinstance(v, (int, float))}
        if other:
            print(f"      non-numeric value types: {other}")
