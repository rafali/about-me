import json
import requests
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INSTA_TOKEN_FILE = ROOT / "insta_token.json"
INSTA_FILE = ROOT / "insta.json"
IMAGES_DIR = ROOT / "images"

IMAGES_DIR.mkdir(exist_ok=True)


def download_media(item):
    """Download media_url and thumbnail_url for an item and update the item with local paths"""
    for field_name in ['media_url', 'thumbnail_url']:
        media_url = item.get(field_name)
        if not media_url or not media_url.startswith('http'):
            continue

        try:
            response = requests.get(media_url, stream=True, timeout=15)
            response.raise_for_status()

            item_id = item.get("id")
            if item.get('media_type') == 'VIDEO':
                if field_name == 'media_url':
                    file_name = f'images/vid_{item_id}.mp4'
                else:
                    file_name = f'images/vid_thumb_{item_id}.jpg'
            else:
                file_name = f'images/img_{item_id}.jpg'

            file_path = ROOT / file_name
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            item[field_name] = file_name
            print(f"Downloaded: {file_name}")
        except Exception as exc:
            print(f"Failed to download {field_name} for {item.get('id')}: {exc}")


def sync_instagram():
    """Sync Instagram posts and save to insta.json"""
    with open(INSTA_TOKEN_FILE, 'r') as file:
        insta_token = json.load(file)

    with open(INSTA_FILE, 'r') as file:
        insta = json.load(file)

    insta_map = {}
    results = []

    for item in insta:
        insta_map[item['id']] = item

    token = insta_token.get("token")
    fields = 'id,caption,location_id,media_type,media_url,permalink,thumbnail_url,timestamp,children{media_type,media_url,thumbnail_url}'
    after = None
    new_count = 0

    while True:
        url = f'https://graph.instagram.com/v19.0/17841400379500478/media?fields={fields}&access_token={token}&limit=25'
        if after:
            url = url + '&after={0}'.format(after)
        resp = requests.get(url)
        j = resp.json()

        if 'error' in j:
            error = j.get('error', {})
            raise ValueError(f"Instagram API error: {error.get('message', str(error))}")

        if j.get('data'):
            for item in j['data']:
                if item['id'] not in insta_map:
                    print(f"appending item: {item.get('caption')}")
                    # Download media for new post
                    download_media(item)
                    # Download media for carousel children
                    children = item.get('children')
                    if children:
                        for child in children.get('data', []):
                            download_media(child)
                    results.append(item)
                    new_count += 1
                else:
                    print(f"already stored: {item.get('caption')}")
                    # Save and return when we hit a known post
                    for old_item in insta:
                        if old_item not in results:
                            results.append(old_item)
                    with open(INSTA_FILE, 'w') as file:
                        json.dump(results, file, indent=4)
                    return new_count

            paging = j.get('paging', {})
            if 'cursors' in paging and 'after' in paging['cursors']:
                after = paging['cursors']['after']
            else:
                break
        else:
            break

    for old_item in insta:
        if old_item not in results:
            results.append(old_item)

    with open(INSTA_FILE, 'w') as file:
        json.dump(results, file, indent=4)
        file.write("\n")

    return new_count


if __name__ == "__main__":
    count = sync_instagram()
    print(f"Synced {count} new posts")
