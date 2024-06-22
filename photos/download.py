import json

import requests

with open('insta.json', 'r') as json_file:
    insta = json.load(json_file)


def enrich(item):
    for field_name in ['media_url', 'thumbnail_url']:
        media_url = item.get(field_name)
        if media_url and media_url.startswith('http'):
            response = requests.get(media_url, stream=True)
            response.raise_for_status()  # Vérifier s'il y a des erreurs

            # Ouvrir le fichier en mode binaire pour écrire le contenu téléchargé
            item_id = item["id"]
            if item['media_type'] == 'VIDEO':
                if field_name == 'media_url':
                    file_name = f'images/vid_{item_id}.mp4'
                else:
                    file_name = f'images/vid_thumb_{item_id}.jpg'
            else:
                file_name = f'images/img_{item_id}.jpg'
            with open(file_name, 'wb') as image_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        image_file.write(chunk)

            item[field_name] = file_name
            with open('insta.json', 'w') as file:
                json.dump(insta, file, indent=4)
                print(f'Downloaded: {file_name}')


for current_item in insta:
    print(current_item)
    enrich(current_item)
    children = current_item.get('children')
    if children:
        for child in children['data']:
            enrich(child)

