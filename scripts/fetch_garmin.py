"""
fetch_garmin.py — Import running activities from Garmin Connect.

Fetches all runs since STREAK_START, writes Markdown files to src/content/runs/,
saves route coordinates to public/routes/, and updates data/activities.json.
User-written notes in existing files are never overwritten.
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path

import frontmatter
from dotenv import load_dotenv
from garminconnect import Garmin

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STREAK_START = date(2024, 6, 9)
RUNS_DIR = Path("src/content/runs")
ROUTES_DIR = Path("public/routes")
ACTIVITIES_FILE = Path("data/activities.json")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def pace_str(duration_seconds: int, distance_km: float) -> str:
    """Return pace as M:SS per km."""
    if distance_km <= 0:
        return "0:00"
    secs_per_km = duration_seconds / distance_km
    m = int(secs_per_km // 60)
    s = int(secs_per_km % 60)
    return f"{m}:{s:02d}"


def slugify(text: str) -> str:
    """Lowercase, hyphenate, strip non-alphanumeric characters."""
    text = text.lower().strip()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9-]", "", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def unique_slug(base: str, existing: set[str]) -> str:
    """Append -2, -3 etc. until the slug is unique in the existing set."""
    slug = base
    n = 2
    while slug in existing:
        slug = f"{base}-{n}"
        n += 1
    return slug


def parse_date(iso: str) -> date:
    """Parse Garmin's startTimeLocal (may or may not have timezone)."""
    iso = iso.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(iso, fmt).date()
        except ValueError:
            continue
    # fallback: just take the date portion
    return date.fromisoformat(iso[:10])


def gpx_to_coords(gpx_xml: str) -> list[list[float]]:
    """Extract [[lat, lon], ...] from a GPX XML string."""
    root = ET.fromstring(gpx_xml)
    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
    coords = []
    for trkpt in root.findall(".//gpx:trkpt", ns):
        lat = trkpt.get("lat")
        lon = trkpt.get("lon")
        if lat is not None and lon is not None:
            coords.append([float(lat), float(lon)])
    return coords


def yaml_value(v) -> str:
    """Render a frontmatter value as YAML-safe inline text."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def write_new_md(path: Path, fields: dict) -> None:
    """Write a brand-new Markdown file with frontmatter and default body."""
    avg_hr_line = f"avg_hr: {fields['avg_hr']}" if fields["avg_hr"] is not None else "avg_hr: null"
    city_line = f'city: "{fields["city"]}"' if fields["city"] else "city: null"

    content = (
        f'---\n'
        f'title: "{fields["title"]}"\n'
        f'date: "{fields["date"]}"\n'
        f'garmin_id: "{fields["garmin_id"]}"\n'
        f'distance_km: {fields["distance_km"]}\n'
        f'duration_seconds: {fields["duration_seconds"]}\n'
        f'pace_per_km: "{fields["pace_per_km"]}"\n'
        f'{avg_hr_line}\n'
        f'{city_line}\n'
        f'country: null\n'
        f'has_route: {"true" if fields["has_route"] else "false"}\n'
        f'auto_generated: true\n'
        f'tags: []\n'
        f'---\n\n'
        f'## Notes\n\n'
        f'Add your notes here.\n'
    )
    path.write_text(content, encoding="utf-8")


def update_existing_md(path: Path, fields: dict) -> None:
    """Update only data fields in an existing file; leave user content alone."""
    post = frontmatter.load(str(path))
    post["distance_km"] = fields["distance_km"]
    post["duration_seconds"] = fields["duration_seconds"]
    post["pace_per_km"] = fields["pace_per_km"]
    if fields["avg_hr"] is not None:
        post["avg_hr"] = fields["avg_hr"]
    post["has_route"] = fields["has_route"]
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    load_dotenv()

    email = os.environ.get("GARMIN_EMAIL", "").strip()
    password = os.environ.get("GARMIN_PASSWORD", "").strip()
    if not email or not password:
        print("ERROR: GARMIN_EMAIL and GARMIN_PASSWORD must be set.", file=sys.stderr)
        sys.exit(1)

    # Ensure output directories exist
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ROUTES_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVITIES_FILE.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 1 — Authenticate
    # ------------------------------------------------------------------
    print("Authenticating with Garmin Connect...")
    try:
        client = Garmin(email, password)
        client.login()
        print("Logged in successfully.")
    except Exception as exc:
        print(f"ERROR: Garmin login failed — {exc}", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 2 — Fetch activities
    # ------------------------------------------------------------------
    print(f"Fetching activities since {STREAK_START} ...")
    all_activities: list[dict] = []
    batch_start = 0
    batch_size = 100

    while True:
        try:
            batch = client.get_activities(batch_start, batch_size)
        except Exception as exc:
            print(f"ERROR fetching activity batch at offset {batch_start}: {exc}", file=sys.stderr)
            break

        if not batch:
            break

        done = False
        for act in batch:
            raw_date_str = act.get("startTimeLocal", "")
            try:
                act_date = parse_date(raw_date_str)
            except Exception:
                continue

            if act_date < STREAK_START:
                done = True
                break

            type_key = (act.get("activityType") or {}).get("typeKey", "")
            if "running" not in type_key.lower():
                continue

            all_activities.append(act)

        if done or len(batch) < batch_size:
            break

        batch_start += batch_size

    print(f"Found {len(all_activities)} running activities.")

    # ------------------------------------------------------------------
    # Step 3-6 — Process each activity
    # ------------------------------------------------------------------
    existing_slugs: set[str] = {p.stem for p in RUNS_DIR.glob("*.md")}
    # Build a map of garmin_id -> slug for already-known files so we don't
    # generate a new slug for an activity that already has a file.
    garmin_id_to_slug: dict[str, str] = {}
    for md_path in RUNS_DIR.glob("*.md"):
        try:
            post = frontmatter.load(str(md_path))
            gid = str(post.get("garmin_id", ""))
            if gid:
                garmin_id_to_slug[gid] = md_path.stem
        except Exception:
            pass

    summary_records: list[dict] = []
    created = 0
    updated = 0
    routes_saved = 0
    errors: list[str] = []

    for act in all_activities:
        activity_id = str(act.get("activityId", ""))
        try:
            # -- Extract fields --
            raw_date_str = act.get("startTimeLocal", "")
            act_date = parse_date(raw_date_str)
            date_str = act_date.isoformat()

            raw_title = (act.get("activityName") or "Run").strip() or "Run"
            distance_km = round((act.get("distance") or 0) / 1000, 2)
            duration_seconds = int(act.get("duration") or 0)
            pace = pace_str(duration_seconds, distance_km)

            raw_hr = act.get("averageHR")
            avg_hr = int(raw_hr) if raw_hr is not None else None

            city = act.get("locationName") or None
            if city:
                city = city.strip() or None

            # has_route: Garmin indicates GPS presence via hasPolyline
            has_route = bool(act.get("hasPolyline") or act.get("hasImages"))

            fields = {
                "garmin_id": activity_id,
                "title": raw_title,
                "date": date_str,
                "distance_km": distance_km,
                "duration_seconds": duration_seconds,
                "pace_per_km": pace,
                "avg_hr": avg_hr,
                "city": city,
                "has_route": has_route,
            }

            # -- Resolve slug --
            if activity_id in garmin_id_to_slug:
                slug = garmin_id_to_slug[activity_id]
            else:
                base_slug = f"{date_str}-{slugify(raw_title)}"
                slug = unique_slug(base_slug, existing_slugs)
                existing_slugs.add(slug)
                garmin_id_to_slug[activity_id] = slug

            md_path = RUNS_DIR / f"{slug}.md"

            # -- Create or update Markdown --
            if not md_path.exists():
                write_new_md(md_path, fields)
                created += 1
            else:
                update_existing_md(md_path, fields)
                updated += 1

            # -- Fetch route --
            if has_route:
                route_path = ROUTES_DIR / f"{activity_id}.json"
                try:
                    gpx_raw = client.download_activity(
                        activity_id, Garmin.ActivityDownloadFormat.GPX
                    )
                    gpx_data = gpx_raw.decode("utf-8") if isinstance(gpx_raw, bytes) else gpx_raw
                    coords = gpx_to_coords(gpx_data)
                    if coords:
                        route_path.write_text(json.dumps(coords), encoding="utf-8")
                        routes_saved += 1
                    else:
                        print(f"  WARNING: No coordinates in GPX for activity {activity_id}")
                        # Update has_route to false so the map isn't attempted
                        post = frontmatter.load(str(md_path))
                        post["has_route"] = False
                        md_path.write_text(frontmatter.dumps(post), encoding="utf-8")
                except Exception as route_exc:
                    print(f"  WARNING: Could not fetch route for {activity_id} — {route_exc}")
                    post = frontmatter.load(str(md_path))
                    post["has_route"] = False
                    md_path.write_text(frontmatter.dumps(post), encoding="utf-8")

            # -- Accumulate summary record --
            summary_records.append({
                "date": date_str,
                "slug": slug,
                "distance_km": distance_km,
                "garmin_id": activity_id,
                "title": raw_title,
            })

        except Exception as exc:
            msg = f"Activity {activity_id}: {exc}"
            print(f"  ERROR: {msg}", file=sys.stderr)
            errors.append(msg)
            continue

    # ------------------------------------------------------------------
    # Step 7 — Write activities.json
    # ------------------------------------------------------------------
    summary_records.sort(key=lambda r: r["date"], reverse=True)
    ACTIVITIES_FILE.write_text(
        json.dumps(summary_records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # ------------------------------------------------------------------
    # Step 8 — Summary
    # ------------------------------------------------------------------
    print("\n--- Import complete ---")
    print(f"Activities fetched : {len(all_activities)}")
    print(f"Files created      : {created}")
    print(f"Files updated      : {updated}")
    print(f"Routes saved       : {routes_saved}")
    if errors:
        print(f"Errors             : {len(errors)}")
        for e in errors:
            print(f"  - {e}")
    else:
        print("Errors             : 0")


if __name__ == "__main__":
    main()
