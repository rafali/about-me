import json
import requests

with open('insta_token.json', 'r') as file:
    insta_token = json.load(file)

with open('insta.json', 'r') as file:
    insta = json.load(file)

insta_map = {}
results = []

for item in insta:
    insta_map[item['id']] = item


def fetch():
    token = insta_token.get("token")
    fields = 'id,caption,location_id,media_type,media_url,permalink,thumbnail_url,timestamp,children{media_type,media_url,thumbnail_url}'
    after = None
    while True:
        url = f'https://graph.instagram.com/v19.0/17841400379500478/media?fields={fields}&access_token={token}&limit=25'
        if after:
            url = url + '&after={0}'.format(after)
        resp = requests.get(url)
        j = resp.json()
        print(j)
        if j['data']:
            for item in j['data']:
                if item['id'] not in insta_map:
                    print(f"appending item: {item.get('caption')}")
                    results.append(item)
                else:
                    print(f"already stored: {item.get('caption')}")
                    return
            after = j['paging']['cursors']['after']


fetch()

for old_item in insta:
    if old_item not in results:
        results.append(old_item)

with open('insta.json', 'w') as file:
    json.dump(results, file, indent=4)
