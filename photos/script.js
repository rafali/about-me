// script.js

document.addEventListener('DOMContentLoaded', loadInstaPhotos);

async function loadInstaPhotos() {
    const response = await fetch('insta.json');
    const data = await response.json();
    displayPhotos(data);
}

function displayPhotos(mediaItems) {
    const photosContainer = document.getElementById('container');

    mediaItems.forEach(media => {
        const photosDiv = document.createElement('div');
        photosDiv.className = 'photos';
        if (media.caption) {
            media.caption.split('\n').forEach(function (caption, i) {
                const h = i === 0 ? document.createElement('h3') : document.createElement('p');
                h.textContent = caption;
                photosContainer.appendChild(h);
            })
        }
        if (media.timestamp) {
            const p = document.createElement('p');
            p.textContent = formatDate(media.timestamp);
            photosContainer.appendChild(p);
        }
        if (media.media_type === 'IMAGE' || media.media_type === 'VIDEO') {
            const photoDiv = createPhotoDiv(media);
            photosDiv.appendChild(photoDiv);
        } else if (media.media_type === 'CAROUSEL_ALBUM' && media.children) {
            media.children.data.forEach(media_child => {
                const photoDiv = createPhotoDiv(media_child);
                photosDiv.appendChild(photoDiv);
            });
        }
        if (media.location_url) {
            const img = document.createElement('img');
            img.src = media.location_url[0];
            const photoDiv = document.createElement('div');
            photoDiv.className = 'photo';
            photoDiv.appendChild(img);
            photosDiv.appendChild(photoDiv);

            if (media.location_url.length > 1) {
                img.addEventListener('mouseover', () => {
                    img.src = media.location_url[1]
                });
                img.addEventListener('mouseout', () => {
                    img.src = media.location_url[0]
                });
            }
        }
        photosContainer.appendChild(photosDiv);
    });
}

function createPhotoDiv(media) {
    const photoDiv = document.createElement('div');
    photoDiv.className = 'photo';

    const img = document.createElement('img');
    if (media.media_type === 'VIDEO') {
        img.src = media.thumbnail_url;
        photoDiv.classList.add('video');
        const video = document.createElement('video');
        photoDiv.addEventListener('mouseover', () => {
            if (!photoDiv.contains(video)) {
                photoDiv.innerHTML = ''
                video.src = media.media_url;
                video.controls = true;
                photoDiv.appendChild(video)
                photoDiv.classList.add('video');
                photoDiv.classList.remove('video');
            }
        });


    } else {
        img.src = media.media_url;
    }

    img.loading = "lazy"

    img.alt = media.caption || 'Instagram Photo';
    photoDiv.appendChild(img);

    return photoDiv;
}

function formatDate(dateString) {
    // Create a new Date object from the date string
    const date = new Date(dateString);

    // Extract the year
    const year = date.getFullYear();

    // Extract the month using Intl.DateTimeFormat
    const month = new Intl.DateTimeFormat('en-US', {month: 'long'}).format(date);

    // Return the formatted string
    return `${year}, ${month}`;
}

