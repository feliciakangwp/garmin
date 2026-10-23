"""Read data/ and write dashboard.html: one self-contained file, no server needed."""
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE / "dashboard.html"

# ---- your settings ----
RACES = [("HYROX", "2026-11-27"), ("HYROX", "2026-11-29"), ("HYROX", "2027-02-13")]
GOAL = "Stronger and faster on race day"
TAPER_DAYS = 10
SPORTS = ["Running", "HIIT", "Strength", "Other"]


def load(name):
    path = DATA / name
    return json.loads(path.read_text()) if path.exists() else {}


def sport_of(type_key):
    t = type_key or ""
    if "run" in t:
        return "Running"
    if "hiit" in t or "cardio" in t or "hyrox" in t:
        return "HIIT"
    if "strength" in t:
        return "Strength"
    return "Other"


def dig(obj, *keys):
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def monday(d):
    return d - timedelta(days=d.weekday())


def build():
    acts_raw = load("activities.json")
    daily = load("daily.json")
    sleep = load("sleep.json")
    hrv = load("hrv.json")
    extras = load("extras.json")
    today = date.today()

    acts = []
    for a in acts_raw.values():
        acts.append({
            "date": a["startTimeLocal"][:10],
            "time": a["startTimeLocal"][11:16],
            "name": a.get("activityName") or "",
            "sport": sport_of(dig(a, "activityType", "typeKey")),
            "type": (dig(a, "activityType", "typeKey") or "").replace("_", " "),
            "km": round((a.get("distance") or 0) / 1000, 2),
            "min": round((a.get("duration") or 0) / 60, 1),
            "load": round(a.get("activityTrainingLoad") or 0),
            "avgHR": a.get("averageHR"),
            "maxHR": a.get("maxHR"),
            "kcal": a.get("calories"),
            "te": a.get("aerobicTrainingEffect"),
        })
    acts.sort(key=lambda a: (a["date"], a["time"]))

    all_dates = [a["date"] for a in acts] + list(daily) + list(sleep) + list(hrv)
    if not all_dates:
        raise SystemExit("No data yet. Run pull.py first.")
    start = date.fromisoformat(min(all_dates))
    days = [(start + timedelta(days=i)).isoformat() for i in range((today - start).days + 1)]

    # ---- training load: fitness (42-day) and fatigue (7-day) ----
    load_by_day = defaultdict(float)
    for a in acts:
        load_by_day[a["date"]] += a["load"]
    seed = statistics.mean([load_by_day.get(d, 0) for d in days[:28]]) if days else 0
    ctl = atl = seed
    fitness, fatigue, form, acwr = [], [], [], []
    for d in days:
        # form and load balance describe how you start the day, before today's session
        form.append(round((ctl - atl) / ctl * 100, 1) if ctl > 1 else None)
        acwr.append(atl / ctl if ctl > 1 else None)
        ctl += (load_by_day.get(d, 0) - ctl) / 42
        atl += (load_by_day.get(d, 0) - atl) / 7
        fitness.append(round(ctl, 1))
        fatigue.append(round(atl, 1))

    # ---- body signals ----
    rhr = [dig(daily.get(d), "heartRate", "restingValue") for d in days]
    bb = [dig(daily.get(d), "bodyBattery", "maxValue") for d in days]
    steps = [dig(daily.get(d), "movement", "steps", "value") for d in days]
    stress = [dig(daily.get(d), "stress", "avgLevel") for d in days]
    hrv_v = [dig(hrv.get(d), "lastNightAvg") for d in days]
    hrv_lo = [dig(hrv.get(d), "baseline", "balancedLow") for d in days]
    hrv_hi = [dig(hrv.get(d), "baseline", "balancedUpper") for d in days]
    hrv_status = [dig(hrv.get(d), "status") for d in days]
    sl = [sleep.get(d) or {} for d in days]
    sleep_h = [round(s["sleepTimeSeconds"] / 3600, 2) if s.get("sleepTimeSeconds") else None for s in sl]
    sleep_score = [dig(s, "sleepScores", "overall", "value") for s in sl]
    sleep_stages = [[round((s.get(k) or 0) / 3600, 2) for k in
                     ("deepSleepSeconds", "remSleepSeconds", "lightSleepSeconds", "awakeSleepSeconds")]
                    if s else None for s in sl]

    # ---- readiness: my estimate from HRV, sleep, body battery, resting HR and load balance ----
    readiness, parts = [], []
    for i, d in enumerate(days):
        comp = {}
        if hrv_v[i] is not None and hrv_lo[i] and hrv_hi[i]:
            v, lo, hi = hrv_v[i], hrv_lo[i], hrv_hi[i]
            comp["HRV"] = clamp(75 + 25 * (v - lo) / max(1, hi - lo)) if v >= lo else clamp(75 - 6 * (lo - v))
        if sleep_score[i] is not None:
            comp["Sleep"] = sleep_score[i]
        if bb[i] is not None:
            comp["Body Battery"] = bb[i]
        prev = [x for x in rhr[max(0, i - 30):i] if x]
        if rhr[i] and len(prev) >= 7:
            comp["Resting HR"] = clamp(80 - 10 * (rhr[i] - statistics.mean(prev)))
        if acwr[i] is not None and i >= 21:
            r = acwr[i]
            comp["Load balance"] = clamp(90 - (r - 1.3) * 150 if r > 1.3 else 90 - (0.8 - r) * 60 if r < 0.8 else 90)
        weights = {"HRV": 30, "Sleep": 25, "Body Battery": 20, "Resting HR": 10, "Load balance": 15}
        if len(comp) >= 3:
            total = sum(weights[k] for k in comp)
            readiness.append(round(sum(comp[k] * weights[k] for k in comp) / total))
        else:
            readiness.append(None)
        parts.append({k: round(v) for k, v in comp.items()})

    # ---- weeks ----
    weeks = []
    wk = monday(start)
    while wk <= today:
        weeks.append(wk)
        wk += timedelta(days=7)
    week_idx = {w.isoformat(): i for i, w in enumerate(weeks)}
    wstats = [{s: {"n": 0, "min": 0.0, "km": 0.0} for s in SPORTS} | {"load": 0} for _ in weeks]
    for a in acts:
        w = wstats[week_idx[monday(date.fromisoformat(a["date"])).isoformat()]]
        w[a["sport"]]["n"] += 1
        w[a["sport"]]["min"] += a["min"]
        w[a["sport"]]["km"] += a["km"]
        w["load"] += a["load"]
    week_rows = []
    for w, s in zip(weeks, wstats):
        week_rows.append({
            "start": w.isoformat(),
            "sports": {k: {"n": s[k]["n"], "h": round(s[k]["min"] / 60, 2), "km": round(s[k]["km"], 1)} for k in SPORTS},
            "load": round(s["load"]),
        })

    # ---- records ----
    runs = [a for a in acts if a["sport"] == "Running" and a["km"] >= 1]
    for r in runs:
        r["pace"] = round(r["min"] / r["km"], 2)
    week_hours = [sum(w["sports"][k]["h"] for k in SPORTS) for w in week_rows]
    week_n = [sum(w["sports"][k]["n"] for k in SPORTS) for w in week_rows]

    def best(values, fn=max):
        pairs = [(v, days[i]) for i, v in enumerate(values) if v is not None]
        return fn(pairs) if pairs else None

    records = []

    def rec(label, value, when, note=""):
        records.append({"label": label, "value": value, "when": when, "note": note})

    if runs:
        r = max(runs, key=lambda r: r["km"])
        rec("Longest run", f"{r['km']:.2f} km", r["date"], r["type"])
        fast = [r for r in runs if r["km"] >= 3] or runs
        r = min(fast, key=lambda r: r["pace"])
        rec("Fastest run pace", f"{int(r['pace'])}:{round(r['pace'] % 1 * 60):02d} /km", r["date"], f"{r['km']:.1f} km")
    if acts:
        a = max(acts, key=lambda a: a["load"])
        rec("Hardest session", f"{a['load']} load", a["date"], a["name"])
        a = max(acts, key=lambda a: a["min"])
        rec("Longest session", f"{int(a['min'] // 60)}h {int(a['min'] % 60):02d}m", a["date"], a["name"])
    if week_hours:
        i = max(range(len(week_hours)), key=lambda i: week_hours[i])
        rec("Biggest week", f"{week_hours[i]:.1f} h", f"Week of {week_rows[i]['start']}", f"{week_n[i]} sessions")
    for label, values, fn, fmt in [
        ("Highest HRV night", hrv_v, max, "{} ms"),
        ("Lowest resting HR", rhr, min, "{} bpm"),
        ("Best sleep score", sleep_score, max, "{}"),
        ("Peak readiness", readiness, max, "{}"),
        ("Most steps", steps, max, "{:,}"),
    ]:
        b = best(values, fn)
        if b:
            rec(label, fmt.format(b[0]), b[1])

    # best 7-day readiness stretch = your peak condition so far
    peak = None
    for i in range(6, len(days)):
        win = [x for x in readiness[i - 6:i + 1] if x is not None]
        if len(win) >= 5:
            avg = sum(win) / len(win)
            if not peak or avg > peak["avg"]:
                peak = {"avg": round(avg), "from": days[i - 6], "to": days[i]}

    hardest = sorted(acts, key=lambda a: -a["load"])[:5]

    payload = {
        "today": today.isoformat(),
        "pulledAt": extras.get("pulledAt"),
        "races": [{"name": n, "date": d} for n, d in RACES],
        "goal": GOAL,
        "taperDays": TAPER_DAYS,
        "sports": SPORTS,
        "days": days,
        "fitness": fitness, "fatigue": fatigue, "form": form,
        "load": [round(load_by_day.get(d, 0)) for d in days],
        "rhr": rhr, "bb": bb, "stress": stress, "steps": steps,
        "hrv": hrv_v, "hrvLo": hrv_lo, "hrvHi": hrv_hi, "hrvStatus": hrv_status,
        "sleepH": sleep_h, "sleepScore": sleep_score, "sleepStages": sleep_stages,
        "readiness": readiness, "parts": parts,
        "weeks": week_rows,
        "runs": [{k: r[k] for k in ("date", "km", "pace", "avgHR", "type", "name")} for r in runs],
        "records": records,
        "hardest": hardest,
        "peak": peak,
        "fitnessAge": dig(extras, "fitnessAge", "fitnessAge"),
        "age": dig(extras, "fitnessAge", "chronologicalAge"),
        "actsByDay": {d: [a for a in acts if a["date"] == d] for d in {a["date"] for a in acts}},
    }
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    OUT.write_text(TEMPLATE.replace("__DATA__", blob), encoding="utf-8")
    print(f"Wrote {OUT}")


TEMPLATE = (HERE / "template.html").read_text(encoding="utf-8")

if __name__ == "__main__":
    build()
