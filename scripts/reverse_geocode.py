"""
reverse_geocode.py — Fill in country field for runs using Nominatim.

For every run where country is null and has_route is true, reads the first
coordinate from public/routes/{garmin_id}.json and looks up the country via
OpenStreetMap Nominatim reverse geocoding.
"""

import json
import time
from pathlib import Path

import frontmatter
import requests

RUNS_DIR = Path("src/content/runs")
ROUTES_DIR = Path("public/routes")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {"User-Agent": "therunstreak.run geocoder"}
RATE_LIMIT_SECS = 1.1  # Nominatim policy: max 1 req/sec

COUNTRY_NAMES = {
    "España": "Spain",
    "Sverige": "Sweden",
    "Deutschland": "Germany",
    "Schweiz": "Switzerland",
    "Suisse": "Switzerland",
    "Schweiz/Suisse/Svizzera/Svizra": "Switzerland",
    "Norge": "Norway",
    "Danmark": "Denmark",
    "Suomi": "Finland",
    "Nederland": "Netherlands",
    "Belgique": "Belgium",
    "Österreich": "Austria",
    "Polska": "Poland",
    "Italia": "Italy",
    "França": "France",
    "Türkiye": "Turkey",
    "Россия": "Russia",
    "日本": "Japan",
}


def normalise_country(name: str) -> str:
    """Return the English name for a country, or the original if not in the map."""
    return COUNTRY_NAMES.get(name, name)


# ---------------------------------------------------------------------------
# One-off fix: normalise country names in existing .md files
# ---------------------------------------------------------------------------

def fix_existing_countries() -> None:
    print("Fixing country names in existing run files...")
    fixed = 0
    for md_path in sorted(RUNS_DIR.glob("*.md")):
        try:
            post = frontmatter.load(str(md_path))
            raw = post.get("country")
            if not raw or not isinstance(raw, str):
                continue
            normalised = normalise_country(raw)
            if normalised != raw:
                post["country"] = normalised
                md_path.write_text(frontmatter.dumps(post), encoding="utf-8")
                fixed += 1
        except Exception as exc:
            print(f"  WARNING: Could not process {md_path.name} — {exc}")
    print(f"Updated {fixed} file(s).")


# ---------------------------------------------------------------------------
# Step 1 — Find runs needing geocoding
# ---------------------------------------------------------------------------

def run_geocoder() -> None:
    print("\nScanning run files for missing countries...")

    candidates = []
    for md_path in sorted(RUNS_DIR.glob("*.md")):
        try:
            post = frontmatter.load(str(md_path))
            country = post.get("country") or None
            has_route = bool(post.get("has_route", False))
            garmin_id = str(post.get("garmin_id", "") or "").strip()

            if country is None and has_route and garmin_id:
                candidates.append((md_path, post, garmin_id))
        except Exception as exc:
            print(f"  WARNING: Could not read {md_path.name} — {exc}")

    print(f"Found {len(candidates)} runs needing geocoding.\n")

    # -------------------------------------------------------------------------
    # Step 2 & 3 — Reverse geocode and update
    # -------------------------------------------------------------------------

    updated = 0
    skipped = 0
    failures = []
    countries_found: set[str] = set()
    total = len(candidates)

    for i, (md_path, post, garmin_id) in enumerate(candidates, start=1):
        route_path = ROUTES_DIR / f"{garmin_id}.json"

        if not route_path.exists():
            skipped += 1
            continue

        try:
            coords = json.loads(route_path.read_text(encoding="utf-8"))
            if not coords:
                skipped += 1
                continue

            lat, lon = coords[0][0], coords[0][1]

            resp = requests.get(
                NOMINATIM_URL,
                params={"lat": lat, "lon": lon, "format": "json"},
                headers=HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            raw_country = (data.get("address") or {}).get("country")

            if raw_country:
                country = normalise_country(raw_country)
                post["country"] = country
                md_path.write_text(frontmatter.dumps(post), encoding="utf-8")
                countries_found.add(country)
                updated += 1
            else:
                failures.append(f"{md_path.name}: no country in response")

        except Exception as exc:
            failures.append(f"{md_path.name}: {exc}")

        if i % 10 == 0 or i == total:
            print(f"  {i}/{total} geocoded...")

        time.sleep(RATE_LIMIT_SECS)

    # -------------------------------------------------------------------------
    # Step 4 — Summary
    # -------------------------------------------------------------------------

    print()
    print("--- Reverse geocoding complete ---")
    print(f"Updated  : {updated}")
    print(f"Skipped  : {skipped} (no route file)")
    print(f"Failures : {len(failures)}")
    if countries_found:
        print(f"Countries: {', '.join(sorted(countries_found))}")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")


if __name__ == "__main__":
    fix_existing_countries()
    run_geocoder()
