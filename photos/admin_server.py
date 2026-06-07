import json
import mimetypes
import os
import subprocess
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlparse

import generate_maps
import requests
import sync


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent  # Parent directory for serving public files
INSTA_FILE = ROOT / "insta.json"
TOKEN_FILE = ROOT / "mapbox_token.json"
HOST = "0.0.0.0"
PORT = int(os.environ.get("PHOTOS_ADMIN_PORT", "8765"))
SEARCHBOX_SUGGEST_URL = "https://api.mapbox.com/search/searchbox/v1/suggest"
SEARCHBOX_RETRIEVE_URL = "https://api.mapbox.com/search/searchbox/v1/retrieve"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
GEOCODE_TYPES = "poi,address,place,district,region,neighborhood"


def load_insta():
    with INSTA_FILE.open() as file:
        return json.load(file)


def save_insta(items):
    with INSTA_FILE.open("w") as file:
        json.dump(items, file, indent=4)
        file.write("\n")


def get_git_status():
    try:
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return f"Error: {result.stderr}"
        if not result.stdout.strip():
            return "No changes"
        return result.stdout
    except Exception as e:
        return f"Error: {str(e)}"


def git_commit_and_push(message):
    try:
        subprocess.run(
            ['git', 'add', '-A'],
            cwd=PROJECT_ROOT,
            check=True,
            timeout=10,
        )
        subprocess.run(
            ['git', 'commit', '-m', message],
            cwd=PROJECT_ROOT,
            check=True,
            timeout=10,
        )
        subprocess.run(
            ['git', 'push'],
            cwd=PROJECT_ROOT,
            check=True,
            timeout=30,
        )
        return "Changes published successfully!"
    except subprocess.CalledProcessError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


def first_caption_line(item):
    caption = item.get("caption") or ""
    for line in caption.splitlines():
        line = line.strip()
        if line:
            return line
    return "Untitled"


def thumbnail_for(item):
    if item.get("media_type") == "VIDEO":
        return item.get("thumbnail_url")
    if item.get("media_type") == "IMAGE":
        return item.get("media_url")
    for child in item.get("children", {}).get("data", []):
        return child.get("thumbnail_url") or child.get("media_url")
    return item.get("media_url")


def summarize(item):
    geo = item.get("geo") or {}
    return {
        "id": item.get("id"),
        "title": first_caption_line(item),
        "timestamp": item.get("timestamp"),
        "media_type": item.get("media_type"),
        "thumbnail": thumbnail_for(item),
        "hasGeo": bool(geo),
        "hasCoordinates": geo.get("lat") is not None and geo.get("lon") is not None,
        "hasMap": bool(item.get("location_url")),
    }


def find_post(items, post_id):
    for item in items:
        if item.get("id") == post_id:
            return item
    return None


def token_value():
    token = os.environ.get("MAPBOX_TOKEN")
    if token:
        return token
    if TOKEN_FILE.exists():
        with TOKEN_FILE.open() as file:
            data = json.load(file)
        return data.get("token") or data.get("mapbox_token")
    return None


def geocode_results(query):
    results = []
    seen = set()

    for result in mapbox_results(query):
        add_unique_result(results, seen, result)
    for result in osm_results(query):
        add_unique_result(results, seen, result)

    return sorted(
        results,
        key=lambda result: result_score(result, query),
        reverse=True,
    )[:8]


def result_score(result, query):
    query_tokens = token_set(query)
    label_tokens = token_set(result["label"])
    overlap = len(query_tokens & label_tokens)
    score = overlap * 10
    if query.casefold() in result["label"].casefold():
        score += 100
    if result.get("source") == "Mapbox":
        score += 1
    return score


def token_set(value):
    return {
        token
        for token in "".join(
            char.casefold() if char.isalnum() else " " for char in value
        ).split()
        if len(token) > 1
    }


def add_unique_result(results, seen, result):
    key = (
        round(float(result["lat"]), 4),
        round(float(result["lon"]), 4),
        result["label"].casefold(),
    )
    if key in seen:
        return
    seen.add(key)
    results.append(result)


def mapbox_results(query):
    token = token_value()
    if not token:
        raise ValueError("Missing Mapbox token")

    session_token = str(uuid.uuid4())
    response = requests.get(
        SEARCHBOX_SUGGEST_URL,
        params={
            "q": query,
            "access_token": token,
            "session_token": session_token,
            "limit": 5,
            "language": "fr",
            "types": GEOCODE_TYPES,
        },
        timeout=15,
    )
    response.raise_for_status()

    results = []
    for suggestion in response.json().get("suggestions") or []:
        lat, lon = coordinates_from_searchbox(suggestion)
        if (lat is None or lon is None) and suggestion.get("mapbox_id"):
            retrieved = retrieve_searchbox_feature(
                token, session_token, suggestion["mapbox_id"]
            )
            lat, lon = coordinates_from_searchbox(retrieved)
        if lat is None or lon is None:
            continue

        label = searchbox_label(suggestion, query)
        label = compact_place_label(label)

        results.append(
            {
                "name": label,
                "label": label,
                "lat": round(float(lat), 6),
                "lon": round(float(lon), 6),
                "type": suggestion.get("feature_type") or "",
                "source": "Mapbox",
            }
        )
    return results


def osm_results(query):
    response = requests.get(
        NOMINATIM_URL,
        params={
            "q": query,
            "format": "jsonv2",
            "limit": 5,
            "accept-language": "fr,en",
        },
        headers={"User-Agent": "rafali-photos-admin/1.0"},
        timeout=15,
    )
    response.raise_for_status()

    results = []
    for item in response.json():
        lat = item.get("lat")
        lon = item.get("lon")
        if lat is None or lon is None:
            continue

        label = compact_place_label(item.get("display_name") or query)
        osm_type = item.get("type") or item.get("class") or ""
        results.append(
            {
                "name": label,
                "label": label,
                "lat": round(float(lat), 6),
                "lon": round(float(lon), 6),
                "type": osm_type,
                "source": "OpenStreetMap",
            }
        )
    return results


def retrieve_searchbox_feature(token, session_token, mapbox_id):
    response = requests.get(
        f"{SEARCHBOX_RETRIEVE_URL}/{quote(mapbox_id, safe='')}",
        params={"access_token": token, "session_token": session_token},
        timeout=15,
    )
    response.raise_for_status()
    features = response.json().get("features") or []
    return features[0] if features else {}


def coordinates_from_searchbox(item):
    properties = item.get("properties") or {}
    coordinates = item.get("coordinates") or properties.get("coordinates") or {}
    lat = coordinates.get("latitude")
    lon = coordinates.get("longitude")
    if lat is not None and lon is not None:
        return lat, lon

    geometry = item.get("geometry") or {}
    point = geometry.get("coordinates") or []
    if len(point) >= 2:
        return point[1], point[0]

    return None, None


def searchbox_label(item, fallback):
    properties = item.get("properties") or {}
    name = item.get("name") or properties.get("name") or fallback
    place = item.get("place_formatted") or properties.get("place_formatted") or ""
    full = item.get("full_address") or properties.get("full_address")
    if place and not place.lower().startswith(name.lower()):
        return f"{name}, {place}"
    if full and full != name:
        return f"{name}, {full}"
    return name


def compact_place_label(label):
    parts = [part.strip() for part in label.split(",") if part.strip()]
    if len(parts) >= 2 and parts[0].casefold() == parts[1].casefold():
        parts.pop(1)
    return ", ".join(parts) if parts else label


def map_args(force=True, region_zoom=9):
    return SimpleNamespace(
        context_zoom=4,
        region_zoom=region_zoom,
        width=500,
        height=500,
        zoom_out_percent=15,
        crop_margin=5,
        quality=85,
        format="webp",
        style="mapbox/light-v11",
        force=force,
        output_dir=ROOT / "maps",
    )


def generate_for_post(item, force=True):
    geo = item.get("geo") or {}
    if not geo.get("name") or geo.get("lat") is None or geo.get("lon") is None:
        raise ValueError("geo.name, geo.lat and geo.lon are required")

    args = map_args(force=force, region_zoom=float(geo.get("region_zoom", 9)))
    context = generate_maps.map_generation_context(args)
    location_url = generate_maps.generate_place_maps(
        args,
        context,
        name=geo["name"],
        lat=float(geo["lat"]),
        lon=float(geo["lon"]),
        region_center=geo.get("region_center"),
    )
    generate_maps.put_location_url_after_geo(item, location_url)
    return location_url


class Handler(SimpleHTTPRequestHandler):
    server_version = "PhotosAdmin/1.0"

    def translate_path(self, path):
        parsed = urlparse(path)
        requested = parsed.path

        # Route to admin interface
        if requested.startswith("/admin"):
            if requested == "/admin":
                requested = "/admin/"
            if requested.endswith("/"):
                requested += "index.html"
            safe = Path(requested.lstrip("/"))
            return str((ROOT / safe).resolve())

        # Route to public site
        if requested == "/":
            requested = "/index.html"
        elif requested.endswith("/") and not requested.startswith("/api"):
            requested += "index.html"

        safe = Path(requested.lstrip("/"))
        public_path = PROJECT_ROOT / safe
        resolved = public_path.resolve()

        # Ensure path is within PROJECT_ROOT for security
        try:
            resolved.relative_to(PROJECT_ROOT)
        except ValueError:
            # Path is outside PROJECT_ROOT, serve from ROOT
            resolved = (ROOT / safe).resolve()

        return str(resolved)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Redirect /admin to /admin/ to fix relative paths
        if path == "/admin":
            self.send_response(301)
            self.send_header("Location", "/admin/")
            self.end_headers()
            return

        if path == "/api/git-status":
            status = get_git_status()
            return self.send_json(200, {"status": status})

        if path == "/api/config":
            token = token_value()
            return self.send_json(200, {"mapboxToken": token})

        if path == "/api/posts":
            params = parse_qs(parsed.query)
            status = params.get("status", ["all"])[0]
            posts = [summarize(item) for item in load_insta()]
            if status == "missing-geo":
                posts = [post for post in posts if not post["hasCoordinates"]]
            elif status == "missing-map":
                posts = [
                    post
                    for post in posts
                    if post["hasCoordinates"] and not post["hasMap"]
                ]
            elif status == "mapped":
                posts = [post for post in posts if post["hasMap"]]
            return self.send_json(200, {"posts": posts})

        if path == "/api/geocode":
            params = parse_qs(parsed.query)
            query = " ".join((params.get("q", [""])[0] or "").split())
            if len(query) < 2:
                return self.send_json(200, {"results": []})
            try:
                return self.send_json(200, {"results": geocode_results(query)})
            except requests.HTTPError as exc:
                return self.send_json(
                    502,
                    {
                        "error": (
                            f"Mapbox geocoding failed: HTTP "
                            f"{exc.response.status_code}"
                        )
                    },
                )
            except requests.RequestException as exc:
                return self.send_json(
                    502,
                    {"error": f"Mapbox geocoding failed: {exc.__class__.__name__}"},
                )

        if path.startswith("/api/posts/"):
            post_id = path.split("/")[-1]
            item = find_post(load_insta(), post_id)
            if not item:
                return self.send_json(404, {"error": "Post not found"})
            return self.send_json(200, {"post": item})

        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/sync":
            try:
                new_count = sync.sync_instagram()
                return self.send_json(200, {"status": "success", "newPosts": new_count})
            except Exception as exc:
                return self.send_json(500, {"error": f"Sync failed: {str(exc)}"})

        if path == "/api/git-commit-push":
            try:
                payload = self.read_json()
                message = payload.get("message", "").strip()
                if not message:
                    return self.send_json(400, {"error": "Commit message is required"})
                result = git_commit_and_push(message)
                return self.send_json(200, {"message": result})
            except Exception as exc:
                return self.send_json(500, {"error": f"Publish failed: {str(exc)}"})

        if path == "/api/save-insta-token":
            try:
                payload = self.read_json()
                token = payload.get("token", "").strip()
                if not token:
                    return self.send_json(400, {"error": "Token is required"})

                insta_file = ROOT / "insta_token.json"
                with insta_file.open("w") as file:
                    json.dump({"token": token}, file, indent=2)

                return self.send_json(200, {"message": "Token saved successfully"})
            except Exception as exc:
                return self.send_json(500, {"error": f"Failed to save token: {str(exc)}"})

        if not path.startswith("/api/posts/"):
            return self.send_json(404, {"error": "Not found"})

        parts = path.strip("/").split("/")
        if len(parts) != 4:
            return self.send_json(404, {"error": "Not found"})

        _, _, post_id, action = parts
        items = load_insta()
        item = find_post(items, post_id)
        if not item:
            return self.send_json(404, {"error": "Post not found"})

        try:
            if action == "geo":
                payload = self.read_json()
                name = str(payload.get("name") or "").strip()
                if not name:
                    return self.send_json(400, {"error": "geo.name is required"})
                item["geo"] = {"name": name}
                if payload.get("lat") is not None and payload.get("lon") is not None:
                    item["geo"]["lat"] = round(float(payload["lat"]), 6)
                    item["geo"]["lon"] = round(float(payload["lon"]), 6)
                if payload.get("region_zoom") is not None:
                    item["geo"]["region_zoom"] = round(float(payload["region_zoom"]), 2)
                if payload.get("region_center") is not None:
                    center = payload["region_center"]
                    item["geo"]["region_center"] = {
                        "lat": round(float(center["lat"]), 6),
                        "lon": round(float(center["lon"]), 6),
                    }
                generate_maps.put_geo_after_permalink(item, item["geo"])
                if item.get("geo", {}).get("lat") is None:
                    item.pop("location_url", None)
                save_insta(items)
                return self.send_json(200, {"post": item})

            if action == "generate-map":
                location_url = generate_for_post(item, force=True)
                save_insta(items)
                return self.send_json(200, {"post": item, "location_url": location_url})

            if action == "save-and-generate":
                payload = self.read_json()
                name = str(payload.get("name") or "").strip()
                if not name:
                    return self.send_json(400, {"error": "geo.name is required"})
                item["geo"] = {
                    "name": name,
                    "lat": round(float(payload["lat"]), 6),
                    "lon": round(float(payload["lon"]), 6),
                    "region_zoom": round(float(payload.get("region_zoom", 9)), 2),
                }
                if payload.get("region_center") is not None:
                    center = payload["region_center"]
                    item["geo"]["region_center"] = {
                        "lat": round(float(center["lat"]), 6),
                        "lon": round(float(center["lon"]), 6),
                    }
                generate_maps.put_geo_after_permalink(item, item["geo"])
                location_url = generate_for_post(item, force=True)
                save_insta(items)
                return self.send_json(200, {"post": item, "location_url": location_url})

            if action == "caption":
                payload = self.read_json()
                caption = payload.get("caption", "")
                item["caption"] = caption
                save_insta(items)
                return self.send_json(200, {"post": item})

        except (KeyError, TypeError, ValueError) as exc:
            return self.send_json(400, {"error": str(exc)})

        return self.send_json(404, {"error": "Not found"})


def main():
    mimetypes.add_type("application/javascript", ".js")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"🌍 Server started on port {PORT}")
    print(f"📱 Preview site:     http://{HOST}:{PORT}/")
    print(f"📸 Photos:           http://{HOST}:{PORT}/photos/")
    print(f"⚙️  Admin interface:  http://{HOST}:{PORT}/admin/")
    server.serve_forever()


if __name__ == "__main__":
    main()
