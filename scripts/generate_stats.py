"""
generate_stats.py — Calculate stats from run Markdown files.

Writes:
  data/stats.json
  data/monthly-summary.json
  data/activities.json
"""

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import frontmatter

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RUNS_DIR = Path("src/content/runs")
STATS_FILE = Path("data/stats.json")
MONTHLY_FILE = Path("data/monthly-summary.json")
ACTIVITIES_FILE = Path("data/activities.json")

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def format_pace(total_seconds: float, total_km: float) -> str:
    """Return M:SS per km."""
    if total_km <= 0:
        return "0:00"
    secs = total_seconds / total_km
    m = int(secs // 60)
    s = int(secs % 60)
    return f"{m}:{s:02d}"


def format_mmss(seconds: int) -> str:
    """Format seconds as M:SS."""
    m = seconds // 60
    s = seconds % 60
    return f"{m}:{s:02d}"


def format_hmmss(seconds: int) -> str:
    """Format seconds as H:MM:SS."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}"


def format_duration(seconds: int) -> str:
    """Format seconds as Xh Ym for monthly summaries."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def compute_streaks(run_dates: list[date]) -> tuple[int, int]:
    """Return (current_streak, longest_streak) given a list of run dates."""
    if not run_dates:
        return 0, 0

    day_set = set(run_dates)
    today = date.today()

    # Current streak — walk backwards from today
    current = 0
    cursor = today
    while cursor in day_set:
        current += 1
        cursor -= timedelta(days=1)

    # Longest streak — iterate sorted unique days
    sorted_days = sorted(day_set)
    longest = 1
    run = 1
    for i in range(1, len(sorted_days)):
        if (sorted_days[i] - sorted_days[i - 1]).days == 1:
            run += 1
            longest = max(longest, run)
        else:
            run = 1

    return current, longest


# ---------------------------------------------------------------------------
# Step 1 — Load runs
# ---------------------------------------------------------------------------

print("Loading run files...")
runs: list[dict] = []

for md_path in RUNS_DIR.glob("*.md"):
    try:
        post = frontmatter.load(str(md_path))
        date_str = str(post.get("date", "")).strip()
        distance_km = float(post.get("distance_km", 0) or 0)

        if not date_str or distance_km <= 0:
            continue

        run_date = date.fromisoformat(date_str[:10])

        runs.append({
            "slug": md_path.stem,
            "date": run_date,
            "date_str": run_date.isoformat(),
            "title": str(post.get("title", "")).strip(),
            "garmin_id": str(post.get("garmin_id", "") or ""),
            "distance_km": distance_km,
            "duration_seconds": int(post.get("duration_seconds", 0) or 0),
            "avg_hr": post.get("avg_hr"),
            "city": post.get("city") or None,
            "country": post.get("country") or None,
            "has_route": bool(post.get("has_route", False)),
        })
    except Exception as exc:
        print(f"  WARNING: Could not parse {md_path.name} — {exc}")

runs.sort(key=lambda r: r["date"], reverse=True)
print(f"Loaded {len(runs)} valid runs.")

# ---------------------------------------------------------------------------
# Step 2 — stats.json
# ---------------------------------------------------------------------------

total_runs = len(runs)
total_km = round(sum(r["distance_km"] for r in runs), 1)
total_seconds = sum(r["duration_seconds"] for r in runs)
longest_run_km = round(max((r["distance_km"] for r in runs), default=0), 2)
avg_pace = format_pace(total_seconds, sum(r["distance_km"] for r in runs))

# PBs — find lowest duration in distance band
def find_pb(min_km: float, max_km: float) -> list[dict]:
    return [r for r in runs if min_km <= r["distance_km"] <= max_km and r["duration_seconds"] > 0]

pb_5k_candidates = find_pb(4.8, 5.5)
pb_10k_candidates = find_pb(9.5, 10.5)
pb_half_candidates = find_pb(20.5, 22.0)

pb_5k = format_mmss(min(pb_5k_candidates, key=lambda r: r["duration_seconds"])["duration_seconds"]) if pb_5k_candidates else None
pb_10k = format_mmss(min(pb_10k_candidates, key=lambda r: r["duration_seconds"])["duration_seconds"]) if pb_10k_candidates else None
pb_half = format_hmmss(min(pb_half_candidates, key=lambda r: r["duration_seconds"])["duration_seconds"]) if pb_half_candidates else None

countries = sorted({r["country"] for r in runs if r["country"]})
cities = sorted({r["city"] for r in runs if r["city"]})

run_dates = [r["date"] for r in runs]
current_streak, longest_streak = compute_streaks(run_dates)

earliest = min(r["date"] for r in runs) if runs else None
latest = max(r["date"] for r in runs) if runs else None

stats = {
    "total_runs": total_runs,
    "total_km": total_km,
    "longest_run_km": longest_run_km,
    "avg_pace": avg_pace,
    "pb_5k": pb_5k,
    "pb_10k": pb_10k,
    "pb_half": pb_half,
    "countries": countries,
    "cities": cities,
    "current_streak": current_streak,
    "longest_streak": longest_streak,
    "last_updated": date.today().isoformat(),
}

STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
STATS_FILE.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")

# ---------------------------------------------------------------------------
# Step 3 — monthly-summary.json
# ---------------------------------------------------------------------------

monthly: dict[tuple[int, int], dict] = defaultdict(lambda: {"runs": 0, "distance_km": 0.0, "duration_seconds": 0})

for r in runs:
    key = (r["date"].year, r["date"].month)
    monthly[key]["runs"] += 1
    monthly[key]["distance_km"] += r["distance_km"]
    monthly[key]["duration_seconds"] += r["duration_seconds"]

monthly_list = []
for (year, month), data in sorted(monthly.items(), reverse=True):
    monthly_list.append({
        "year": year,
        "month": month,
        "month_label": f"{MONTH_NAMES[month - 1]} {year}",
        "runs": data["runs"],
        "distance_km": round(data["distance_km"], 1),
        "duration_seconds": data["duration_seconds"],
        "duration_formatted": format_duration(data["duration_seconds"]),
    })

MONTHLY_FILE.write_text(json.dumps(monthly_list, indent=2, ensure_ascii=False), encoding="utf-8")

# ---------------------------------------------------------------------------
# Step 4 — activities.json
# ---------------------------------------------------------------------------

activities = [
    {
        "date": r["date_str"],
        "slug": r["slug"],
        "distance_km": r["distance_km"],
        "garmin_id": r["garmin_id"],
        "title": r["title"],
    }
    for r in runs
]

ACTIVITIES_FILE.write_text(json.dumps(activities, indent=2, ensure_ascii=False), encoding="utf-8")

# ---------------------------------------------------------------------------
# Step 5 — Summary
# ---------------------------------------------------------------------------

print()
print("--- Stats generated ---")
print(f"Total runs processed : {total_runs}")
print(f"Date range           : {earliest} to {latest}")
print(f"Total distance       : {total_km} km")
print(f"Avg pace             : {avg_pace}/km")
print(f"Longest run          : {longest_run_km} km")
print(f"Current streak       : {current_streak} days")
print(f"Longest streak       : {longest_streak} days")
print(f"PB 5K                : {pb_5k or '—'}")
print(f"PB 10K               : {pb_10k or '—'}")
print(f"PB half marathon     : {pb_half or '—'}")
print(f"Countries            : {', '.join(countries) or '—'}")
print(f"Cities               : {len(cities)} unique")
print()
print(f"Written: {STATS_FILE}, {MONTHLY_FILE}, {ACTIVITIES_FILE}")
