"""Download your Garmin history into data/ as JSON. Re-running only fetches what is new.

    python3 pull.py          last 12 months (first run), then only new data
    python3 pull.py --full   your full history
"""
import json
import sys
from datetime import date, datetime, timedelta

from garmin_api import DATA, ApiError, get

TODAY = date.today()
REFETCH_DAYS = 3  # recent days can still change (sleep syncs late, etc.)


def load(name, default):
    path = DATA / name
    return json.loads(path.read_text()) if path.exists() else default


def save(name, obj):
    (DATA / name).write_text(json.dumps(obj, separators=(",", ":")))


def progress(label, done, total):
    width = 28
    filled = int(width * done / total) if total else width
    sys.stdout.write(f"\r  {label:<16} [{'#' * filled}{'.' * (width - filled)}] {done}/{total}")
    sys.stdout.flush()


def fetch_range(fetch, start, end):
    """Call fetch(start, end); on HTTP 500 (response too big) split the range in half."""
    try:
        return fetch(start, end) or []
    except ApiError as e:
        if e.status != 500 or start == end:
            if e.status in (400, 404, 500):
                return []  # no data for this stretch: skip it
            raise
        mid = start + (end - start) // 2
        return fetch_range(fetch, start, mid) + fetch_range(fetch, mid + timedelta(days=1), end)


def chunks(start, end, days):
    out, cur = [], start
    while cur <= end:
        stop = min(cur + timedelta(days=days - 1), end)
        out.append((cur, stop))
        cur = stop + timedelta(days=1)
    return out


# ---------- activities ----------

def get_activity_page(start, limit):
    try:
        return get(f"/activitylist-service/activities/search/activities?start={start}&limit={limit}") or []
    except ApiError as e:
        if e.status == 500 and limit > 1:
            half = limit // 2
            first = get_activity_page(start, half)
            return first + (get_activity_page(start + half, limit - half) if len(first) == half else [])
        raise


def pull_activities(since):
    acts = load("activities.json", {})
    known = set(acts)
    start, new = 0, 0
    print("Activities")
    while True:
        page = get_activity_page(start, 20)
        for a in page:
            aid = str(a["activityId"])
            new += aid not in acts
            acts[aid] = a
        start += len(page)
        sys.stdout.write(f"\r  fetched {start} activities ({new} new)")
        sys.stdout.flush()
        oldest = page[-1]["startTimeLocal"][:10] if page else ""
        if len(page) < 20:
            break
        if since and oldest < since.isoformat():
            break
        if known and any(str(a["activityId"]) in known for a in page):
            break  # caught up with what we already have
    print()
    if since:
        acts = {k: v for k, v in acts.items() if v["startTimeLocal"][:10] >= since.isoformat()}
    save("activities.json", acts)
    return acts


# ---------- daily datasets ----------

def daily_fetch(s, e):
    r = get(f"/usersummary-service/v2/dailysummaries?startDate={s}&endDate={e}")
    return (r or {}).get("data", [])


def sleep_fetch(s, e):
    return get(f"/sleep-service/sleep/dailySleepSummariesByDate?startDate={s}&endDate={e}")


def hrv_fetch(s, e):
    return (get(f"/hrv-service/hrv/daily/{s}/{e}") or {}).get("hrvSummaries", [])


def weight_fetch(s, e):
    return (get(f"/weight-service/weight/range/{s}/{e}") or {}).get("dailyWeightSummaries", [])


def has_daily(d):
    return bool((d.get("movement", {}).get("steps") or {}).get("value") or d.get("heartRate", {}).get("restingValue"))


DATASETS = [
    # file, label, fetcher, chunk days, date key, keep-this-item test
    ("daily.json", "Daily summaries", daily_fetch, 60, "calendarDate", has_daily),
    ("sleep.json", "Sleep", sleep_fetch, 31, "calendarDate", lambda d: bool(d.get("sleepTimeSeconds"))),
    ("hrv.json", "HRV", hrv_fetch, 180, "calendarDate", lambda d: d.get("lastNightAvg") is not None),
    ("weight.json", "Weight", weight_fetch, 60, "summaryDate", lambda d: bool((d.get("latestWeight") or {}).get("weight"))),
]


def pull_dataset(file, label, fetch, size, key, keep, start, state):
    store = load(file, {})
    last = state.get("last", {}).get(file)
    if last and state.get("start") == start.isoformat():
        start = max(start, date.fromisoformat(last) - timedelta(days=REFETCH_DAYS))
    parts = chunks(start, TODAY, size)
    for i, (s, e) in enumerate(parts, 1):
        for item in fetch_range(fetch, s, e):
            if isinstance(item, dict) and item.get(key) and keep(item):
                store[item[key]] = item
        progress(label, i, len(parts))
    print(f"  ({len(store)} days)")
    save(file, store)
    state.setdefault("last", {})[file] = TODAY.isoformat()


def main():
    DATA.mkdir(exist_ok=True)
    state = load("state.json", {})
    full = "--full" in sys.argv or state.get("mode") == "full"

    print(f"Pulling {'your full history' if full else 'the last 12 months'} from Garmin...\n")
    since = None if full else TODAY - timedelta(days=365)
    acts = pull_activities(since)

    if full:
        first = min((a["startTimeLocal"][:10] for a in acts.values()), default=None)
        start = date.fromisoformat(first) if first else TODAY - timedelta(days=365)
    else:
        start = since
    if state.get("start") and state.get("mode") == ("full" if full else "year"):
        start = min(start, date.fromisoformat(state["start"]))

    for ds in DATASETS:
        pull_dataset(*ds, start, state)

    print("Fitness age & heart rate zones")
    extras = load("extras.json", {})
    for name, path in [("fitnessAge", f"/fitnessage-service/fitnessage/v2/{TODAY}"),
                       ("hrZones", "/biometric-service/heartRateZones/v2")]:
        try:
            extras[name] = get(path)
        except ApiError:
            pass
    extras["pulledAt"] = datetime.now().isoformat(timespec="minutes")
    save("extras.json", extras)

    state.update(mode="full" if full else "year", start=start.isoformat())
    save("state.json", state)

    counts = {f: len(load(f, {})) for f, *_ in DATASETS}
    dates = sorted(a["startTimeLocal"][:10] for a in acts.values())
    print("\nDone! Here's what came back:")
    print(f"  {len(acts)} activities" + (f"  ({dates[0]} to {dates[-1]})" if dates else ""))
    print(f"  {counts['daily.json']} days of daily summaries")
    print(f"  {counts['sleep.json']} nights of sleep")
    print(f"  {counts['hrv.json']} nights of HRV")
    print(f"  {counts['weight.json']} weigh-ins")
    print(f"  Date range: {start} to {TODAY}")


if __name__ == "__main__":
    main()
