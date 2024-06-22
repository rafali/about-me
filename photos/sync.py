import json

with open('raw_insta.json', 'r') as file:
    raw_insta = json.load(file)

with open('old_insta.json', 'r') as file:
    old_insta = json.load(file)

old_insta_map = {}


for item in old_insta['data']:
    print(item['id'])
    old_insta_map[item['id']] = item

for item in raw_insta:
    print(item['id'])
    old_item = old_insta_map.get(item['id'])
    if old_item is not None:
        location_url = old_item.get('location_url')
        if location_url is not None:
            item['location_url'] = location_url
            print(item)

with open('insta.json', 'w') as file:
    json.dump(raw_insta, file, indent=4)
