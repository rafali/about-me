import requests
import json

file_path = 'raw_insta.json'

data = []

token = ''
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
        data.extend(j['data'])
        after = j['paging']['cursors']['after']
        print(f'data length: {len(data)}')

    else:
        break

with open(file_path, 'w') as file:
    json.dump(data, file, indent=4)
