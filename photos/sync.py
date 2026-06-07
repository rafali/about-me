import json
import requests
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INSTA_TOKEN_FILE = ROOT / "insta_token.json"
INSTA_FILE = ROOT / "insta.json"


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

    return new_count


if __name__ == "__main__":
    count = sync_instagram()
    print(f"Synced {count} new posts")
