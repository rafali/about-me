import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode

import requests


ROOT = Path(__file__).resolve().parent
INSTA_FILE = ROOT / "insta.json"
TOKEN_FILE = ROOT / "mapbox_token.json"

GEOCODE_URL = "https://api.mapbox.com/search/geocode/v6/forward"
DEFAULT_TYPES = "region,district,place,locality,neighborhood"


def get_token():
    token = os.environ.get("MAPBOX_TOKEN")
    if token:
        return token

    if TOKEN_FILE.exists():
        with TOKEN_FILE.open() as file:
            data = json.load(file)
        token = data.get("token") or data.get("mapbox_token")
        if token:
            return token

    raise SystemExit(
        "Missing Mapbox token. Set MAPBOX_TOKEN or create photos/mapbox_token.json "
        'with {"token": "..."}'
    )


def load_json(path, default):
    if not path.exists():
        return default
    with path.open() as file:
        return json.load(file)


def first_caption_line(item):
    caption = item.get("caption") or ""
    for line in caption.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def clean_query(query):
    return " ".join(query.strip().split())


def query_from_item(item):
    geo_name = clean_query((item.get("geo") or {}).get("name") or "")
    if geo_name:
        return geo_name, geo_name

    title = first_caption_line(item)
    if not title:
        return None, None
    return title, clean_query(title)


def looks_like_location(query, allow_loose, max_tokens):
    if allow_loose:
        return True
    if "," not in query or len(query.split()) > max_tokens:
        return False

    parts = [part.strip() for part in query.split(",", 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return False

    qualifier = parts[1]
    if len(qualifier.split()) > 3:
        return False
    return bool(re.match(r"^[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ' -]+$", qualifier))


def geocode(token, query, language, types):
    params = {
        "q": query,
        "access_token": token,
        "limit": 1,
        "language": language,
        "types": types,
        "autocomplete": "false",
    }
    try:
        response = requests.get(f"{GEOCODE_URL}?{urlencode(params)}", timeout=30)
        response.raise_for_status()
    except requests.HTTPError as exc:
        message = ""
        try:
            message = response.json().get("message", "")
        except ValueError:
            message = response.text[:200]
        raise SystemExit(
            f"Mapbox geocoding failed: HTTP {response.status_code} {message}"
        ) from exc
    except requests.RequestException as exc:
        raise SystemExit(f"Mapbox geocoding failed: {exc.__class__.__name__}") from exc

    features = response.json().get("features") or []
    return features[0] if features else None


def feature_to_geo(feature, fallback_name):
    properties = feature.get("properties") or {}
    coordinates = properties.get("coordinates") or {}
    lon = coordinates.get("longitude")
    lat = coordinates.get("latitude")

    if lat is None or lon is None:
        geometry = feature.get("geometry") or {}
        point = geometry.get("coordinates") or []
        if len(point) >= 2:
            lon, lat = point[0], point[1]

    if lat is None or lon is None:
        return None

    return {
        "name": fallback_name,
        "lat": round(float(lat), 6),
        "lon": round(float(lon), 6),
    }


def put_geo_after_permalink(item, geo):
    reordered = {}
    inserted = False

    for key, value in item.items():
        if key == "geo":
            continue
        reordered[key] = value
        if key == "permalink" and not inserted:
            reordered["geo"] = geo
            inserted = True

    if not inserted:
        reordered["geo"] = geo

    item.clear()
    item.update(reordered)


def enrich(args):
    token = get_token()
    items = load_json(args.insta_file, [])

    changed = 0
    skipped = 0
    failed = 0
    matched = 0

    for item in items:
        if args.id and item.get("id") != args.id:
            continue

        matched += 1
        if item.get("geo", {}).get("lat") and item.get("geo", {}).get("lon"):
            skipped += 1
            continue

        title, query = query_from_item(item)
        if not query:
            skipped += 1
            continue

        if not looks_like_location(query, args.loose, args.max_tokens):
            skipped += 1
            if args.verbose:
                print(f"skip: {title}")
            continue

        feature = geocode(token, query, args.language, args.types)
        if not feature:
            failed += 1
            print(f"missing: {title} -> {query}")
            continue

        relevance = feature.get("properties", {}).get("match_code", {}).get("confidence")
        if relevance is None:
            relevance = feature.get("properties", {}).get("relevance")
        if isinstance(relevance, str):
            confidence_order = {"exact": 1.0, "high": 0.9, "medium": 0.7, "low": 0.4}
            relevance = confidence_order.get(relevance, 0)
        relevance = None if relevance is None else float(relevance or 0)

        if relevance is not None and relevance < args.min_relevance:
            failed += 1
            print(f"low: {title} -> {query} ({relevance:.2f})")
            continue

        geo = feature_to_geo(feature, query)
        if not geo:
            failed += 1
            print(f"bad: {title} -> {query}")
            continue

        put_geo_after_permalink(item, geo)
        changed += 1
        print(f"geo: {title} -> {geo['name']} ({geo['lat']}, {geo['lon']})")

        if args.limit and changed >= args.limit:
            break

    print()
    if args.id and matched == 0:
        raise SystemExit(f"No post found with id: {args.id}")

    print(f"changed={changed} skipped={skipped} failed={failed}")

    if changed and not args.dry_run:
        with args.insta_file.open("w") as file:
            json.dump(items, file, indent=4)
            file.write("\n")
        print(f"updated: {args.insta_file.relative_to(ROOT)}")
    elif changed:
        print("dry-run: no file updated")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Enrich Instagram posts with geo coordinates from Mapbox."
    )
    parser.add_argument("--insta-file", type=Path, default=INSTA_FILE)
    parser.add_argument("--language", default="en,fr")
    parser.add_argument("--types", default=DEFAULT_TYPES)
    parser.add_argument("--min-relevance", type=float, default=0.8)
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=8,
        help="Default safety filter for caption titles.",
    )
    parser.add_argument(
        "--loose",
        action="store_true",
        help="Try every caption title, not only titles containing a comma.",
    )
    parser.add_argument("--limit", type=int, help="Stop after this many additions.")
    parser.add_argument("--id", help="Only enrich one Instagram media id.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    enrich(parse_args())
