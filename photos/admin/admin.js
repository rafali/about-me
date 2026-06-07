const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '::1']);

if (!LOCAL_HOSTS.has(location.hostname)) {
    document.body.textContent = 'Local admin only';
    throw new Error('Local admin only');
}

const state = {
    posts: [],
    selectedId: null,
    selectedPost: null,
    map: null,
    marker: null,
};

const postList = document.getElementById('postList');
const statusFilter = document.getElementById('statusFilter');
const syncButton = document.getElementById('syncButton');
const emptyState = document.getElementById('emptyState');
const editor = document.getElementById('editor');
const postTitle = document.getElementById('postTitle');
const postMeta = document.getElementById('postMeta');
const postLink = document.getElementById('postLink');
const mediaMain = document.getElementById('mediaMain');
const mediaPreview = document.getElementById('mediaPreview');
const mapPreview = document.getElementById('mapPreview');
const geoName = document.getElementById('geoName');
const geoLat = document.getElementById('geoLat');
const geoLon = document.getElementById('geoLon');
const geoZoom = document.getElementById('geoZoom');
const geoResults = document.getElementById('geoResults');
const coordPaste = document.getElementById('coordPaste');
const useCoordPaste = document.getElementById('useCoordPaste');
const saveGeo = document.getElementById('saveGeo');
const generateMap = document.getElementById('generateMap');
const saveAndGenerate = document.getElementById('saveAndGenerate');
const message = document.getElementById('message');
let geoSearchTimer = null;
let geoSearchController = null;

async function api(path, options = {}) {
    const response = await fetch(path, {
        headers: {'Content-Type': 'application/json'},
        ...options,
    });
    const payload = await response.json();
    if (!response.ok) {
        throw new Error(payload.error || 'Request failed');
    }
    return payload;
}

function assetUrl(path) {
    if (!path) return '';
    return `/${path.replace(/^\/+/, '')}`;
}

function setMessage(text) {
    message.textContent = text;
}

function firstCaptionLine(post) {
    return (post.caption || '').split('\n').map(line => line.trim()).find(Boolean) || 'Untitled';
}

function mediaSource(post) {
    if (post.media_type === 'VIDEO') {
        return {type: 'image', src: post.thumbnail_url};
    }
    if (post.media_type === 'IMAGE') {
        return {type: 'image', src: post.media_url};
    }
    const first = post.children?.data?.[0];
    if (!first) {
        return {type: 'image', src: post.media_url};
    }
    return {type: first.media_type === 'VIDEO' ? 'image' : 'image', src: first.thumbnail_url || first.media_url};
}

function mediaSources(post) {
    if (post.media_type === 'IMAGE') {
        return [post.media_url].filter(Boolean);
    }
    if (post.media_type === 'VIDEO') {
        return [post.thumbnail_url || post.media_url].filter(Boolean);
    }
    const children = post.children?.data || [];
    const sources = children.map(item => item.thumbnail_url || item.media_url).filter(Boolean);
    return sources.length ? sources : [post.media_url].filter(Boolean);
}

function badges(post) {
    const items = [];
    if (!post.hasCoordinates) items.push(['geo', 'warn']);
    if (!post.hasMap) items.push(['map', 'warn']);
    if (!items.length) items.push(['ready', '']);
    return items.map(([label, cls]) => `<span class="badge ${cls}">${label}</span>`).join('');
}

function renderPosts() {
    postList.innerHTML = state.posts.map(post => `
        <button class="post ${post.id === state.selectedId ? 'active' : ''}" data-id="${post.id}" type="button">
            <img src="${assetUrl(post.thumbnail)}" alt="">
            <span>
                <span class="post-title">${post.title}</span>
                <span class="badges">${badges(post)}</span>
            </span>
        </button>
    `).join('');
}

async function loadPosts() {
    const status = statusFilter.value;
    const payload = await api(`/api/posts?status=${encodeURIComponent(status)}`);
    state.posts = payload.posts;
    renderPosts();
}

function updateMarkerFromInputs({centerMap = false} = {}) {
    const lat = parseNumber(geoLat.value);
    const lon = parseNumber(geoLon.value);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

    const lngLat = [lon, lat];
    if (!state.marker) {
        state.marker = new mapboxgl.Marker({draggable: true})
            .setLngLat(lngLat)
            .addTo(state.map);
        state.marker.on('dragend', () => {
            const point = state.marker.getLngLat();
            geoLat.value = point.lat.toFixed(6);
            geoLon.value = point.lng.toFixed(6);
        });
    } else {
        state.marker.setLngLat(lngLat);
    }
    if (centerMap) {
        state.map.flyTo({center: lngLat, zoom: Math.max(state.map.getZoom(), 9), essential: true});
    }
}

function syncMapFromInputs() {
    const lat = parseNumber(geoLat.value);
    const lon = parseNumber(geoLon.value);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

    const regionCenter = state.selectedPost?.geo?.region_center || {};
    const centerLat = parseNumber(regionCenter.lat);
    const centerLon = parseNumber(regionCenter.lon);
    const zoom = parseNumber(geoZoom.value);
    state.map.jumpTo({
        center: [
            Number.isFinite(centerLon) ? centerLon : lon,
            Number.isFinite(centerLat) ? centerLat : lat,
        ],
        zoom: Number.isFinite(zoom) ? zoom : 9,
    });
    updateMarkerFromInputs();
}

function renderMapPreviews(post) {
    mapPreview.innerHTML = (post.location_url || []).map(url => (
        `<img src="${assetUrl(url)}?t=${Date.now()}" alt="">`
    )).join('');
}

function renderMedia(post) {
    const sources = mediaSources(post);
    if (sources.length === 0) {
        mediaMain.hidden = true;
        mediaPreview.innerHTML = '';
        return;
    }

    // Show main preview
    mediaMain.hidden = false;
    mediaMain.src = assetUrl(sources[0]);

    // Show gallery
    mediaPreview.innerHTML = sources.map((src, index) => (
        `<img src="${assetUrl(src)}" alt="" class="${index === 0 ? 'active' : ''}" data-index="${index}">`
    )).join('');

    // Add click handlers to gallery
    mediaPreview.querySelectorAll('img').forEach(img => {
        img.addEventListener('click', () => {
            const index = parseInt(img.dataset.index);
            mediaMain.src = assetUrl(sources[index]);
            mediaPreview.querySelectorAll('img').forEach(i => i.classList.remove('active'));
            img.classList.add('active');
        });
    });
}

function clearGeoResults() {
    geoResults.hidden = true;
    geoResults.innerHTML = '';
}

function renderGeoResults(results) {
    if (!results.length) {
        geoResults.hidden = false;
        geoResults.innerHTML = '<div class="geo-result empty">No result</div>';
        return;
    }

    geoResults.hidden = false;
    geoResults.innerHTML = results.map(result => `
        <button
            class="geo-result"
            data-name="${escapeAttribute(result.name)}"
            data-lat="${result.lat}"
            data-lon="${result.lon}"
            type="button"
        >
            <strong>${escapeHtml(result.label)}</strong>
            <span>${escapeHtml(result.source || 'Mapbox')} - ${escapeHtml(result.type || 'place')} - ${result.lat}, ${result.lon}</span>
        </button>
    `).join('');
}

function escapeHtml(value) {
    return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function escapeAttribute(value) {
    return escapeHtml(value);
}

function fillGeo(post) {
    const geo = post.geo || {};
    geoName.value = geo.name || firstCaptionLine(post);
    geoLat.value = geo.lat ?? '';
    geoLon.value = geo.lon ?? '';
    geoZoom.value = geo.region_zoom ?? 9;
}

function parseNumber(value) {
    if (value === null || value === undefined || value === '') return NaN;
    return Number(String(value).replace(',', '.'));
}

function parseCoordinates(value) {
    const text = String(value || '').trim();
    const atMatch = text.match(/@(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/);
    if (atMatch) {
        return {
            lat: Number(atMatch[1]),
            lon: Number(atMatch[2]),
        };
    }

    const bangMatch = text.match(/!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/);
    if (bangMatch) {
        return {
            lat: Number(bangMatch[1]),
            lon: Number(bangMatch[2]),
        };
    }

    const decimalNumbers = text.match(/-?\d+(?:[\.,]\d+)?/g) || [];
    for (let index = 0; index < decimalNumbers.length - 1; index += 1) {
        const lat = parseNumber(decimalNumbers[index]);
        const lon = parseNumber(decimalNumbers[index + 1]);
        if (isLatLon(lat, lon)) {
            return {lat, lon};
        }
    }
    return null;
}

function isLatLon(lat, lon) {
    return Number.isFinite(lat)
        && Number.isFinite(lon)
        && lat >= -90
        && lat <= 90
        && lon >= -180
        && lon <= 180;
}

function applyCoordinatesFromPaste() {
    const coordinates = parseCoordinates(coordPaste.value);
    if (!coordinates || !isLatLon(coordinates.lat, coordinates.lon)) {
        setMessage('No coordinates found');
        return;
    }

    geoLat.value = coordinates.lat.toFixed(6);
    geoLon.value = coordinates.lon.toFixed(6);
    clearGeoResults();
    updateMarkerFromInputs({centerMap: true});
    setMessage('Coordinates applied');
}

function setEditorVisible(visible) {
    emptyState.hidden = visible;
    editor.hidden = !visible;
}

async function selectPost(id) {
    state.selectedId = id;
    renderPosts();
    const payload = await api(`/api/posts/${id}`);
    state.selectedPost = payload.post;

    postTitle.textContent = firstCaptionLine(payload.post);
    postMeta.textContent = payload.post.timestamp || '';
    postLink.href = payload.post.permalink || '#';
    renderMedia(payload.post);
    renderMapPreviews(payload.post);
    fillGeo(payload.post);
    clearGeoResults();
    setEditorVisible(true);

    setTimeout(() => {
        state.map.resize();
        syncMapFromInputs();
    }, 50);
}

async function searchGeoName() {
    const query = geoName.value.trim();
    if (query.length < 2) {
        clearGeoResults();
        return;
    }

    if (geoSearchController) {
        geoSearchController.abort();
    }
    geoSearchController = new AbortController();

    try {
        const payload = await api(
            `/api/geocode?q=${encodeURIComponent(query)}`,
            {signal: geoSearchController.signal},
        );
        renderGeoResults(payload.results || []);
    } catch (error) {
        if (error.name === 'AbortError') return;
        geoResults.hidden = false;
        geoResults.innerHTML = `<div class="geo-result empty">${escapeHtml(error.message)}</div>`;
    }
}

function scheduleGeoSearch() {
    window.clearTimeout(geoSearchTimer);
    geoSearchTimer = window.setTimeout(searchGeoName, 250);
}

function geoPayload() {
    const payload = {name: geoName.value.trim()};
    if (geoLat.value !== '' && geoLon.value !== '') {
        payload.lat = parseNumber(geoLat.value);
        payload.lon = parseNumber(geoLon.value);
    }
    if (geoZoom.value !== '') {
        payload.region_zoom = parseNumber(geoZoom.value);
    }
    if (state.map && geoLat.value !== '' && geoLon.value !== '') {
        const center = state.map.getCenter();
        payload.region_center = {
            lat: Number(center.lat.toFixed(6)),
            lon: Number(center.lng.toFixed(6)),
        };
    }
    return payload;
}

async function action(label, fn) {
    try {
        setMessage(label);
        [saveGeo, generateMap, saveAndGenerate].forEach(button => button.disabled = true);
        const payload = await fn();
        state.selectedPost = payload.post;
        fillGeo(payload.post);
        renderMapPreviews(payload.post);
        await loadPosts();
        setMessage('Done');
    } catch (error) {
        setMessage(error.message);
    } finally {
        [saveGeo, generateMap, saveAndGenerate].forEach(button => button.disabled = false);
    }
}

async function initMap() {
    const config = await api('/api/config');
    if (!config.mapboxToken) {
        throw new Error('Missing Mapbox token');
    }
    mapboxgl.accessToken = config.mapboxToken;
    state.map = new mapboxgl.Map({
        container: 'map',
        style: 'mapbox://styles/mapbox/light-v11',
        center: [2.348392, 48.853495],
        zoom: 4,
    });
    state.map.addControl(new mapboxgl.NavigationControl(), 'top-right');
    state.map.on('click', event => {
        geoLat.value = event.lngLat.lat.toFixed(6);
        geoLon.value = event.lngLat.lng.toFixed(6);
        updateMarkerFromInputs();
    });
    state.map.on('zoomend', () => {
        geoZoom.value = state.map.getZoom().toFixed(1);
    });
}

postList.addEventListener('click', event => {
    const post = event.target.closest('.post');
    if (post) selectPost(post.dataset.id);
});

statusFilter.addEventListener('change', loadPosts);

syncButton.addEventListener('click', () => {
    action('Syncing Instagram', async () => {
        const result = await api('/api/sync', {method: 'POST', body: '{}'});
        await loadPosts();
        return result;
    }).then(result => {
        setMessage(`Synced ${result.newPosts} new posts`);
    });
});

useCoordPaste.addEventListener('click', applyCoordinatesFromPaste);
coordPaste.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
        event.preventDefault();
        applyCoordinatesFromPaste();
    }
});
geoName.addEventListener('input', scheduleGeoSearch);
geoName.addEventListener('focus', () => {
    if (!geoResults.innerHTML) scheduleGeoSearch();
});
geoResults.addEventListener('click', event => {
    const result = event.target.closest('.geo-result[data-lat][data-lon]');
    if (!result) return;

    geoName.value = result.dataset.name;
    geoLat.value = Number(result.dataset.lat).toFixed(6);
    geoLon.value = Number(result.dataset.lon).toFixed(6);
    clearGeoResults();
    updateMarkerFromInputs({centerMap: true});
});
geoLat.addEventListener('change', () => updateMarkerFromInputs({centerMap: true}));
geoLon.addEventListener('change', () => updateMarkerFromInputs({centerMap: true}));
geoZoom.addEventListener('change', () => {
    const zoom = parseNumber(geoZoom.value);
    if (Number.isFinite(zoom)) {
        state.map.setZoom(zoom);
    }
});

saveGeo.addEventListener('click', () => action('Saving', () => api(
    `/api/posts/${state.selectedId}/geo`,
    {method: 'POST', body: JSON.stringify(geoPayload())},
)));

generateMap.addEventListener('click', () => action('Generating', () => api(
    `/api/posts/${state.selectedId}/generate-map`,
    {method: 'POST', body: '{}'},
)));

saveAndGenerate.addEventListener('click', () => action('Saving + generating', () => api(
    `/api/posts/${state.selectedId}/save-and-generate`,
    {method: 'POST', body: JSON.stringify(geoPayload())},
)));

Promise.all([initMap(), loadPosts()]).catch(error => {
    document.body.textContent = error.message;
});
