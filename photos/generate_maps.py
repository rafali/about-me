import argparse
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode

import requests

try:
    from PIL import Image
except ImportError:
    Image = None


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "maps"
DEFAULT_INSTA_FILE = ROOT / "insta.json"
TOKEN_FILE = ROOT / "mapbox_token.json"


def slugify(value):
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return slug or "map"


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


def static_map_url(
    token,
    style,
    marker_lon,
    marker_lat,
    center_lon,
    center_lat,
    zoom,
    width,
    height,
):
    marker = f"pin-l+e63946({marker_lon:.6f},{marker_lat:.6f})"
    center = f"{center_lon:.6f},{center_lat:.6f},{zoom},0"
    query = urlencode({"access_token": token})
    return (
        f"https://api.mapbox.com/styles/v1/{style}/static/"
        f"{marker}/{center}/{width}x{height}@2x?{query}"
    )


def save_with_pillow(content, output_path, quality, final_width, final_height):
    if Image is None:
        raise SystemExit(
            "Generating WebP or cropped maps without macOS sips requires Pillow. "
            "Install it with `python3 -m pip install Pillow`, or use `--format png`."
        )

    image = Image.open(BytesIO(content)).convert("RGB")
    if image.size != (final_width, final_height):
        left = max((image.width - final_width) // 2, 0)
        top = max((image.height - final_height) // 2, 0)
        image = image.crop((left, top, left + final_width, top + final_height))
    image.save(output_path, "WEBP", quality=quality, method=6)


def crop_with_sips(input_path, output_path, final_width, final_height):
    subprocess.run(
        [
            "sips",
            "--cropToHeightWidth",
            str(final_height),
            str(final_width),
            str(input_path),
            "--out",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def save_png(content, output_path, final_width, final_height):
    if content_needs_crop(final_width, final_height, content):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "mapbox.png"
            input_path.write_bytes(content)
            crop_with_sips(input_path, output_path, final_width, final_height)
    else:
        output_path.write_bytes(content)


def save_webp_with_cwebp(content, output_path, quality, final_width, final_height):
    with tempfile.TemporaryDirectory() as tmp_dir:
        input_path = Path(tmp_dir) / "mapbox.png"
        cropped_path = Path(tmp_dir) / "cropped.png"
        input_path.write_bytes(content)

        cwebp_input = input_path
        if content_needs_crop(final_width, final_height, content):
            crop_with_sips(input_path, cropped_path, final_width, final_height)
            cwebp_input = cropped_path

        subprocess.run(
            [
                "cwebp",
                "-quiet",
                "-q",
                str(quality),
                str(cwebp_input),
                "-o",
                str(output_path),
            ],
            check=True,
        )


def download_map(url, output_path, quality, final_width, final_height):
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit(f"Mapbox download failed: {exc.__class__.__name__}") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".webp":
        if shutil.which("cwebp"):
            save_webp_with_cwebp(
                response.content, output_path, quality, final_width, final_height
            )
        else:
            save_with_pillow(
                response.content, output_path, quality, final_width, final_height
            )
    else:
        save_png(response.content, output_path, final_width, final_height)


def content_needs_crop(final_width, final_height, content):
    # Static Images uses @2x, so Mapbox returns double the requested CSS size.
    # PNG dimensions are at bytes 16..24 in the IHDR chunk.
    if content[:8] != b"\x89PNG\r\n\x1a\n":
        return True
    width = int.from_bytes(content[16:20], "big")
    height = int.from_bytes(content[20:24], "big")
    return (width, height) != (final_width, final_height)


def zoom_out(zoom, percent):
    return zoom - math.log2(1 + percent / 100)


def request_size(final_size, crop_margin):
    if crop_margin <= 0:
        return final_size
    return math.ceil(final_size / (1 - 2 * crop_margin / 100))


def map_generation_context(args):
    return {
        "token": get_token(),
        "views": [
            ("context", args.context_zoom),
            ("region", args.region_zoom),
        ],
        "request_width": request_size(args.width, args.crop_margin),
        "request_height": request_size(args.height, args.crop_margin),
        "final_width": args.width * 2,
        "final_height": args.height * 2,
    }


def generate_place_maps(args, context, name, lat, lon, slug=None, region_center=None):
    token = context["token"]
    slug = slug or slugify(name)

    generated = []
    for suffix, zoom in context["views"]:
        center = region_center if suffix == "region" and region_center else None
        center_lat = float(center["lat"]) if center else lat
        center_lon = float(center["lon"]) if center else lon
        output_path = args.output_dir / f"{slug}-{suffix}.{args.format}"
        if output_path.exists() and not args.force:
            generated.append(output_path)
            print(f"Skipped existing: {output_path.relative_to(ROOT)}")
            continue

        url = static_map_url(
            token=token,
            style=args.style,
            marker_lon=lon,
            marker_lat=lat,
            center_lon=center_lon,
            center_lat=center_lat,
            zoom=zoom_out(zoom, args.zoom_out_percent),
            width=context["request_width"],
            height=context["request_height"],
        )
        download_map(
            url,
            output_path,
            args.quality,
            context["final_width"],
            context["final_height"],
        )
        generated.append(output_path)
        print(f"Generated: {output_path.relative_to(ROOT)}")

    return [str(path.relative_to(ROOT)) for path in generated]


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


def put_location_url_after_geo(item, location_url):
    reordered = {}
    inserted = False
    pending_location_url = None

    for key, value in item.items():
        if key == "location_url":
            pending_location_url = location_url
            continue
        reordered[key] = value
        if key == "geo":
            reordered["location_url"] = location_url
            inserted = True

    if not inserted and pending_location_url is not None:
        reordered["location_url"] = location_url

    item.clear()
    item.update(reordered)


def complete_geo(item):
    geo = item.get("geo") or {}
    return (
        geo.get("name")
        and geo.get("lat") is not None
        and geo.get("lon") is not None
    )


def update_insta(args):
    context = map_generation_context(args)
    with args.insta_file.open() as file:
        media_items = json.load(file)

    generated = 0
    removed = 0
    matched = 0
    for item in media_items:
        if args.id and item.get("id") != args.id:
            continue

        matched += 1
        if complete_geo(item):
            geo = item["geo"]
            location_url = generate_place_maps(
                args,
                context,
                name=geo["name"],
                lat=float(geo["lat"]),
                lon=float(geo["lon"]),
                region_center=geo.get("region_center"),
            )
            put_location_url_after_geo(item, location_url)
            generated += 1
        elif "location_url" in item:
            del item["location_url"]
            removed += 1

    if not args.dry_run:
        with args.insta_file.open("w") as file:
            json.dump(media_items, file, indent=4)
            file.write("\n")

    action = "would update" if args.dry_run else "updated"
    print()
    if args.id and matched == 0:
        raise SystemExit(f"No post found with id: {args.id}")

    print(
        f"{action}: {args.insta_file.relative_to(ROOT)} "
        f"(maps={generated}, removed_location_url={removed})"
    )


def generate_maps(args):
    if args.update_insta:
        update_insta(args)
        return

    missing = [
        name for name in ("name", "lat", "lon") if getattr(args, name) is None
    ]
    if missing:
        raise SystemExit(
            "Missing required arguments for single map generation: "
            + ", ".join(f"--{name}" for name in missing)
        )

    context = map_generation_context(args)
    generated = generate_place_maps(
        args,
        context,
        name=args.name,
        lat=args.lat,
        lon=args.lon,
        slug=args.slug,
        region_center=(
            {"lat": args.region_center_lat, "lon": args.region_center_lon}
            if args.region_center_lat is not None
            and args.region_center_lon is not None
            else None
        ),
    )

    print()
    print("location_url:")
    print(json.dumps(generated, indent=4))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate local Mapbox static maps with a pin."
    )
    parser.add_argument("--name", help="Place name, used for the slug.")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--region-center-lat", type=float)
    parser.add_argument("--region-center-lon", type=float)
    parser.add_argument("--slug", help="Override the generated file slug.")
    parser.add_argument("--context-zoom", type=float, default=4)
    parser.add_argument("--region-zoom", type=float, default=9)
    parser.add_argument("--width", type=int, default=500)
    parser.add_argument("--height", type=int, default=500)
    parser.add_argument(
        "--zoom-out-percent",
        type=float,
        default=15,
        help="Show this much more area than the configured zoom level.",
    )
    parser.add_argument(
        "--crop-margin",
        type=float,
        default=5,
        help="Fetch extra image around the final crop, then crop from the center.",
    )
    parser.add_argument("--quality", type=int, default=85)
    parser.add_argument(
        "--format",
        choices=["png", "webp"],
        default="webp",
        help="Output format. WebP uses cwebp when available, then Pillow as fallback.",
    )
    parser.add_argument("--style", default="mapbox/light-v11")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--update-insta",
        action="store_true",
        help="Generate maps for complete geo entries and update insta.json.",
    )
    parser.add_argument("--insta-file", type=Path, default=DEFAULT_INSTA_FILE)
    parser.add_argument("--id", help="Only update one Instagram media id.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where generated maps are written.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    generate_maps(parse_args())
