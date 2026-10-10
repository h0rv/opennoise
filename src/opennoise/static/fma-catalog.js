import {renderPlayableNeighbors} from './fma-playable-neighbors.js';
import {renderDescriptorMap} from './fma-descriptor-map.js';
import {renderPlayback, clearRoutePlayers, requestPlay} from './fma-playback.js';
import {relatedMusic} from './fma-related-music.js';
import {renderSourceGenres} from './source-genres.js';
import {renderGenreAtlas, renderGenreMap} from './fma-genre-map.js';
/** Source-only FMA catalog. Native track annotations never imply artist memberships. */
const $ = selector => document.querySelector(selector);
const content = $('#content'), heading = $('h1'), status = $('#status'), rows = $('#rows'), pages = $('#pages'), query = $('#query'), scope = $('#scope');
$('.skip').addEventListener('click', event => { event.preventDefault(); content.focus(); });
const node = (tag, text) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; return element; };
const number = value => new Intl.NumberFormat('en').format(value);
const link = (text, hash) => { const element = node('a', text); element.href = hash; return element; };
const button = (text, action) => { const element = node('button', text); element.type = 'button'; element.addEventListener('click', action); return element; };
let catalog, genres, artists, artistIndex, trackSearchPromise, routeCleanup = null, generation = 0;
const cache = new Map();
async function json(path) {
  if (!cache.has(path)) cache.set(path, fetch(path).then(response => { if (!response.ok) throw new Error('Catalog file unavailable'); return response.json(); }).catch(error => { cache.delete(path); throw error; }));
  return cache.get(path);
}
async function loadArtists() {
  if (!artists) { const payload = await json('artist-index.json'); artists = payload.artists; artistIndex = new Map(artists.map(row => [row[0], row])); }
}
function route() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (params.has('descriptor-map')) return {kind: 'descriptor-map', entity: params.get('entity') === 'artists' ? 'artists' : 'genres', q: params.get('q') ?? '', selected: params.get('selected') ?? null};
  if (params.has('genre-map')) return {kind: 'genre-map', q: params.get('q') ?? '', playable: params.get('playable') === '1', page: 0};
  if (params.has('listen')) {
    let queue = null;
    if (params.has('queue')) {
      const parts = params.get('queue').split(',');
      if (parts.length > 64 || parts.some(value => !/^[1-9][0-9]*$/.test(value) || !Number.isSafeInteger(Number(value))) || new Set(parts).size !== parts.length || params.has('genre') || params.has('artist')) return {kind: 'invalid'};
      queue = parts.map(Number);
    }
    for (const key of ['genre', 'artist']) if (params.has(key) && (!/^[1-9][0-9]*$/.test(params.get(key)) || !Number.isSafeInteger(Number(params.get(key))))) return {kind: 'invalid'};
    return {kind: 'listen', queue, genre: params.has('genre') ? Number(params.get('genre')) : null, artist: params.has('artist') ? Number(params.get('artist')) : null, q: '', page: 0};
  }
  if (params.has('wikidata') || params.has('wdgenre') || params.has('wdartist')) {
    const kind = params.has('wdgenre') ? 'wdgenre' : params.has('wdartist') ? 'wdartist' : 'wikidata';
    return {kind, id: params.get(kind), q: params.get('q') ?? '', page: /^[0-9]+$/.test(params.get('page') ?? '') ? Number(params.get('page')) : 0};
  }
  let kind = params.has('track') ? 'track' : params.has('artist') ? 'artist' : params.has('genre') ? 'genre' : params.has('artists') ? 'artists' : params.has('unannotated') ? 'unannotated' : params.has('tracks') ? 'tracks' : 'genres';
  const id = kind === 'track' ? params.get('track') : kind === 'artist' ? params.get('artist') : kind === 'genre' ? params.get('genre') : null;
  if (id !== null && (!/^(?:[1-9][0-9]*|null)$/.test(id) || (id !== 'null' && !Number.isSafeInteger(Number(id))))) kind = 'invalid';
  const requested = params.get('page');
  return {kind, id: id === 'null' ? null : id === null ? null : Number(id), q: params.get('q') ?? '', missing: params.get('missing') === '1', playable: params.get('playable') === '1', page: requested && /^[0-9]+$/.test(requested) ? Number(requested) : 0};
}
function setPage(page) { const params = new URLSearchParams(location.hash.slice(1)); params.set('page', String(page)); location.hash = params.toString(); }
function paginate(total, page, size) {
  const last = Math.max(0, Math.ceil(total / size) - 1);
  if (page > last) { const params = new URLSearchParams(location.hash.slice(1)); params.set('page', String(last)); history.replaceState(null, '', '#' + params); render(); return false; }
  if (last) {
    for (const [label, target, disabled] of [['First', 0, page === 0], ['Previous', page - 1, page === 0], ['Next', page + 1, page === last], ['Last', last, page === last]]) { const control = button(label, () => setPage(target)); control.disabled = disabled; pages.append(control); }
    pages.append(node('span', `Page ${page + 1} of ${last + 1}`));
  }
  return true;
}
async function directory(state, token) {
  if (state.kind === 'artists') await loadArtists();
  if (token !== generation) return;
  const source = state.kind === 'artists' ? artists.filter(row => !state.missing || row[3] === 'missing_source_artist_record').map(row => ({id: row[0], name: row[1], count: row[2]})) : catalog.genres.map(row => ({id: row.genre_id, name: row.title, count: row.track_count}));
  const matches = source.filter(row => row.name.toLocaleLowerCase().includes(state.q.toLocaleLowerCase()) || String(row.id) === state.q);
  heading.textContent = state.kind === 'artists' ? state.missing ? 'Missing artist records' : 'Artists' : 'Genres';
  status.textContent = state.kind === 'artists' ? `${number(matches.length)} matching artist IDs · ${number(catalog.counts.source_artists)} source artist records · ${number(catalog.counts.missing_artist_records)} IDs missing artist records.` : `${number(matches.length)} genre definitions · ${number(catalog.counts.observed_track_genres)} have direct track annotations.`;
  if (!paginate(matches.length, state.page, 100)) return;
  const list = node('ul'); list.className = 'directory search-results';
  for (const row of matches.slice(state.page * 100, state.page * 100 + 100)) { const item = node('li'); item.append(link(`${row.name} · #${row.id}`, `#${state.kind === 'artists' ? 'artist' : 'genre'}=${row.id}`), node('small', `${number(row.count)} tracks`)); const listen = listenLink(state.kind === 'artists' ? {artist: row.id} : {genre: row.id}); if (listen) item.append(listen); list.append(item); }
  if (!matches.length) rows.append(node('p', 'No matching names or exact native IDs.'));
  rows.append(list);
}
function playableTracks({genre = null, artist = null} = {}) {
  return (catalog.playback?.tracks ?? []).filter(row => (genre === null || row.genre_ids.includes(genre)) && (artist === null || row.artist_id === artist));
}
function listenLink(state) {
  const clips = playableTracks(state);
  if (!clips.length) return null;
  const params = new URLSearchParams('listen');
  if (state.genre !== undefined) params.set('genre', state.genre);
  if (state.artist !== undefined) params.set('artist', state.artist);
  return link(`Listen · ${clips.length} local excerpt${clips.length === 1 ? '' : 's'}`, '#' + params);
}
function trackNode(track) {
  const [id, title, artistId, genreIds, licenseId, metadataUrl, albumId] = track;
  const row = node('article'); row.className = 'track'; row.dataset.trackId = id; row.dataset.evidenceRole = 'native_track_metadata';
  const titleRow = node('h2'); titleRow.append(link(`${title || 'Missing track title'} · #${id}`, `#track=${id}`)); row.append(titleRow);
  if (playableTracks().some(entry => entry.track_id === id)) row.append(button('Play excerpt', () => requestPlay({config: catalog.playback, id, ids: playableTracks().map(entry => entry.track_id), json})));
  const credit = node('p'); credit.dataset.evidenceRole = 'native_track_artist_association'; credit.append(document.createTextNode('Source artist: '), link(`${artistIndex.get(artistId)?.[1] ?? 'Missing artist record'} · #${artistId}`, `#artist=${artistId}`)); row.append(credit);
  const annotations = node('p'); annotations.className = 'annotations'; annotations.dataset.evidenceRole = 'native_track_genre_annotations'; annotations.append(node('span', 'Track genres:'));
  if (!genreIds?.length) annotations.append(node('span', 'No source genre annotations'));
  for (const genreId of genreIds ?? []) annotations.append(link(genres.get(genreId)?.title ?? `Missing genre definition #${genreId}`, `#genre=${genreId}`));
  row.append(annotations);
  const license = catalog.licenses[licenseId];
  row.append(node('small', `Album ID: ${albumId ?? 'missing'} · Audio license declared by source: ${license?.[0] || 'missing'}`));
  if (metadataUrl) { const metadata = node('p'); metadata.className = 'metadata'; const external = node('a', 'FMA metadata page'); external.href = metadataUrl; external.target = '_blank'; external.rel = 'noopener noreferrer'; metadata.append(external); row.append(metadata); }
  return row;
}
async function tracksFor(ids) {
  const paths = [...new Set(ids.map(id => `tracks/${Math.floor(id / catalog.track_id_span)}.json`))];
  const shards = await Promise.all(paths.map(json));
  const index = new Map(shards.flatMap(shard => shard.tracks).map(track => [track[0], track]));
  if (ids.some(id => !index.has(id))) throw new Error('Track shard is incomplete');
  return ids.map(id => index.get(id));
}
async function searchTracks(state, token) {
  await loadArtists();
  if (!catalog.track_search) throw new Error('Track search is unavailable in this older export.');
  if (!trackSearchPromise) {
    trackSearchPromise = (async () => {
      const chunks = [], paths = catalog.track_search.shards;
      for (let start = 0; start < paths.length; start += 4) chunks.push(...await Promise.all(paths.slice(start, start + 4).map(json)));
      const entries = chunks.flat();
      if (entries.length !== catalog.track_search.row_count) throw new Error('Track search index is incomplete');
      return entries;
    })().catch(error => { trackSearchPromise = null; throw error; });
  }
  if (token === generation) status.textContent = 'Loading track search…';
  const entries = await trackSearchPromise;
  if (token !== generation) return;
  const terms = state.q.normalize('NFKC').toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const exactId = /^#?([1-9][0-9]*)$/.exec(state.q.trim());
  const playable = new Set(playableTracks().map(row => row.track_id));
  const matches = entries.filter(([id, title, artistId]) => {
    if (state.playable && !playable.has(id)) return false;
    const text = `${id} ${title ?? ''} ${artistIndex.get(artistId)?.[1] ?? ''}`.normalize('NFKC').toLocaleLowerCase();
    return exactId ? String(id) === exactId[1] : terms.every(term => text.includes(term));
  });
  heading.textContent = 'Tracks'; status.textContent = `${number(matches.length)} matching tracks${state.playable ? ' with local excerpts' : ''} · title, artist or native track ID.`;
  if (!paginate(matches.length, state.page, catalog.page_size)) return;
  const selected = matches.slice(state.page * catalog.page_size, (state.page + 1) * catalog.page_size);
  const tracks = await tracksFor(selected.map(row => row[0]));
  if (token !== generation) return;
  if (!matches.length) rows.append(node('p', 'No matching tracks. Try a title, artist name or native track ID.'));
  for (const track of tracks) rows.append(trackNode(track));
}
async function trackDetail(state, token) {
  await loadArtists();
  const tracks = await tracksFor([state.id]);
  if (token !== generation) return;
  heading.textContent = tracks[0][1] || `Track #${state.id}`;
  status.textContent = 'Choose a track genre or artist to keep exploring.';
  rows.append(trackNode(tracks[0]));
  const sourceGenres = new Set(tracks[0][3] ?? []);
  const relatedIds = playableTracks().filter(entry => entry.track_id !== state.id && entry.artist_id !== tracks[0][2]).map(entry => ({id: entry.track_id, shared: entry.genre_ids.filter(id => sourceGenres.has(id)).length})).filter(entry => entry.shared > 0).sort((a, b) => b.shared - a.shared || a.id - b.id).slice(0, 6).map(entry => entry.id);
  await renderPlayback({config: catalog.playback, id: state.id, relatedIds, json, rows, heading, status, current: () => token === generation});
  if (token !== generation) return;
  await renderPlayableNeighbors({id: state.id, config: catalog.playable_neighbors, playback: catalog.playback, json, tracksFor, artistIndex, rows, current: () => token === generation, onPlay: (id, ids) => requestPlay({config: catalog.playback, id, ids: ids ?? null, queue: Boolean(ids), json})});
  if (token !== generation) return;
  await relatedMusic({id: state.id, manifest: catalog.related_music, json, tracksFor, artistIndex, rows, current: () => token === generation});
  if (token === generation) heading.focus({preventScroll: true});
}
function exploreGenres(title, description, entries, countKey, selectedGenre = null) {
  const section = node('section'); section.className = 'connections';
  section.dataset.evidenceRole = 'source_track_annotation_overlap';
  section.append(node('h2', title), node('p', description));
  if (selectedGenre) {
    const map = node('details'), summary = node('summary', 'Map of these connections'), canvas = node('div');
    map.append(summary, canvas); renderGenreMap(canvas, selectedGenre, genres); section.append(map);
  }
  const list = node('ul'); list.className = 'directory';
  for (const entry of entries) {
    const genre = genres.get(entry.genre_id);
    const item = node('li');
    item.append(link(genre?.title ?? `Genre #${entry.genre_id}`, `#genre=${entry.genre_id}`), node('small', `${number(entry[countKey])} ${countKey === 'shared_tracks' ? 'shared tracks' : 'tracks'}`));
    list.append(item);
  }
  section.append(list); rows.append(section);
}
async function cohort(state, token) {
  await loadArtists();
  if (token !== generation) return;
  let ids, total, name;
  if (state.kind === 'artist') {
    const shard = await json(`artists/${(state.id ?? 0) % catalog.profile_shards}.json`), artist = shard.artists[String(state.id)];
    if (!artist) throw new Error('Native artist ID is absent');
    ids = artist.track_ids.slice(state.page * catalog.page_size, (state.page + 1) * catalog.page_size); total = artist.track_ids.length; name = `${artist.name} · #${state.id}`;
    if (token !== generation) return;
    const listen = listenLink({artist: state.id}); if (listen) rows.append(listen);
    if (artist.track_genre_counts?.length) exploreGenres('Explore track genres', 'Genres annotated on this artist’s tracks; not an artist classification.', artist.track_genre_counts, 'track_count');
    status.textContent = `${number(total)} tracks with this native source artist ID.${artist.status === 'missing_source_artist_record' ? ' Artist record is missing from the source table.' : ''} Genre annotations below belong to each track.`;
  } else {
    const genre = genres.get(state.id);
    if (state.kind === 'genre' && !genre) throw new Error('Native genre ID is absent');
    total = state.kind === 'genre' ? genre.track_count : state.kind === 'unannotated' ? catalog.counts.unannotated_tracks : catalog.counts.raw_tracks;
    name = state.kind === 'genre' ? `${genre.title} · #${genre.genre_id}` : state.kind === 'unannotated' ? 'Tracks without genre annotations' : 'All raw source tracks';
    if (!paginate(total, state.page, catalog.page_size)) return;
    if (total) { const key = state.kind === 'genre' ? `genre-${state.id}` : state.kind === 'unannotated' ? 'unannotated' : 'all'; const payload = await json(`cohorts/${key}/${state.page}.json`); if (payload.cohort !== key || payload.page !== state.page || payload.total !== total) throw new Error('Track cohort identity mismatch'); ids = payload.track_ids; } else ids = [];
    if (token !== generation) return;
    if (state.kind === 'genre') { const listen = listenLink({genre: state.id}); if (listen) rows.append(listen); }
    if (state.kind === 'genre' && genre.connections?.length) exploreGenres('Connected genres', 'Explore genres that share track annotations.', genre.connections, 'shared_tracks', genre);
    status.textContent = `${number(total)} direct source tracks.${state.kind === 'genre' ? ` Native parent ID: ${genre.parent_id ?? 'not supplied'}. No parent annotations are inherited.` : ''}`;
  }
  const tracks = await tracksFor(ids);
  if (token !== generation) return;
  heading.textContent = name;
  if (state.kind === 'artist' && !paginate(total, state.page, catalog.page_size)) return;
  if (rows.querySelector('.connections') && total) rows.append(node('h2', 'Tracks'));
  for (const track of tracks) rows.append(trackNode(track));
  if (!total) rows.append(node('p', 'No track annotations are present for this source record.'));
  heading.focus({preventScroll: true});
}
async function render() {
  const token = ++generation, state = route();
  routeCleanup?.(); routeCleanup = null;
  clearRoutePlayers();
  $('#search-form').hidden = ['listen', 'genre-map', 'descriptor-map'].includes(state.kind);
  content.setAttribute('aria-busy', 'true'); rows.replaceChildren(); pages.replaceChildren(); status.textContent = 'Loading…';
  if (['artists', 'genres', 'tracks', 'wikidata'].includes(state.kind)) { scope.value = state.kind; query.value = state.q; }
  $('#playable-only').checked = Boolean(state.playable);
  $('[data-playable-filter]').hidden = !catalog.playback || scope.value !== 'tracks';
  try {
    if (state.kind === 'invalid') throw new Error('Invalid native catalog ID');
    if (state.kind === 'listen') {
      if (!catalog.playback) { heading.textContent = 'Listen'; status.textContent = 'No local excerpts are attached to this export.'; }
      else {
        const scoped = state.genre !== null || state.artist !== null;
        if (state.queue && state.queue.some(id => !playableTracks().some(row => row.track_id === id))) throw new Error('This journey includes an excerpt absent from this local export.');
        const ids = state.queue ?? (scoped ? playableTracks({genre: state.genre, artist: state.artist}).map(row => row.track_id) : null);
        await renderPlayback({config: catalog.playback, directory: true, ids, json, rows, heading, status, current: () => token === generation});
        if (token === generation && scoped) {
          if (state.genre !== null) { heading.textContent = `Listen · ${genres.get(state.genre)?.title ?? 'Unknown genre'}`; rows.prepend(link('All tracks in this genre', `#genre=${state.genre}`)); }
          else rows.prepend(link('All tracks by this source artist', `#artist=${state.artist}`));
        }
      }
    }
    else if (state.kind === 'descriptor-map') {
      if (!catalog.descriptor_map) throw new Error('Descriptor map is not attached.');
      await loadArtists(); if (token !== generation) return;
      await renderDescriptorMap({state, registerCleanup: cleanup => { if (token === generation) routeCleanup = cleanup; else cleanup(); }, playbackTracks: catalog.playback?.tracks ?? [], onPlay: (id, ids) => requestPlay({config: catalog.playback, id, ids, queue: Array.isArray(ids), json}), config: catalog.descriptor_map, json, genres, artists, rows, heading, status, current: () => token === generation, onStateChange: ({entity, q, selected}) => { const params = new URLSearchParams('descriptor-map'); if (entity === 'artists') params.set('entity', entity); if (q) params.set('q', q); if (selected !== null && selected !== undefined) params.set('selected', selected); history.replaceState(null, '', '#' + params); }});
    }
    else if (state.kind === 'genre-map') { heading.textContent = 'Genre families'; status.textContent = 'Browse all native FMA genre definitions by source parent. Positions do not represent musical distance.'; renderGenreAtlas(rows, genres, {playbackTracks: catalog.playback?.tracks ?? [], query: state.q, onlyWithExcerpts: state.playable, onFilterChange: ({query, onlyWithExcerpts}) => { const params = new URLSearchParams('genre-map'); if (query) params.set('q', query); if (onlyWithExcerpts) params.set('playable', '1'); history.replaceState(null, '', '#' + params); }}); }
    else if (['wikidata', 'wdgenre', 'wdartist'].includes(state.kind)) await renderSourceGenres({state, manifest: catalog.source_genres, json, heading, status, rows, paginate, current: () => token === generation});
    else if (['artists', 'genres'].includes(state.kind)) await directory(state, token);
    else if (state.kind === 'tracks' && (state.q.trim() || state.playable)) await searchTracks(state, token);
    else if (state.kind === 'track') await trackDetail(state, token);
    else await cohort(state, token);
    if (token === generation) { content.setAttribute('aria-busy', 'false'); document.documentElement.dataset.fmaReady = 'true'; }
  } catch (error) {
    if (token !== generation) return;
    heading.textContent = 'Catalog unavailable'; status.textContent = error.message; rows.append(button('Retry', render)); content.setAttribute('aria-busy', 'false');
  }
}
function search(replace = false) {
  const params = new URLSearchParams(); params.set(scope.value, ''); if (query.value.trim()) params.set('q', query.value.trim()); if (scope.value === 'tracks' && $('#playable-only').checked) params.set('playable', '1');
  const hash = '#' + params.toString(); if (replace) { history.replaceState(null, '', hash); render(); } else if (location.hash !== hash) location.hash = hash; else render();
}
$('#search-form').addEventListener('submit', event => { event.preventDefault(); const first = rows.querySelector('.search-results a'); if (first && route().q === query.value.trim()) first.click(); else search(); });
$('#playable-only').addEventListener('change', () => search());
query.addEventListener('input', () => search(true)); scope.addEventListener('change', () => search());
query.addEventListener('keydown', event => { if (event.key === 'ArrowDown') { event.preventDefault(); rows.querySelector('.search-results a')?.focus(); } });
document.addEventListener('keydown', event => { if (event.key === '/' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) { event.preventDefault(); (document.querySelector('#listen-query, #descriptor-query, .fma-atlas-search') ?? query).focus(); } });
window.addEventListener('hashchange', render);
try { catalog = await json('catalog.json'); if (catalog.collection) { if (catalog.collection.home !== '../../index.html' || typeof catalog.collection.label !== 'string') throw Error('Invalid collection navigation'); const label = document.querySelector('[data-collection-label]'); label.textContent = ' · ' + catalog.collection.label; label.hidden = false; document.querySelector('[data-collection-home]').hidden = false; } document.querySelectorAll('[data-descriptor-map]').forEach(element => { element.hidden = !catalog.descriptor_map; }); document.querySelectorAll('[data-playback]').forEach(element => { element.hidden = !catalog.playback; }); if (catalog.playback) { document.querySelector('[data-audio-scope]').textContent = 'Only explicitly attached local excerpts have playback controls; other tracks have no included audio.'; document.querySelector('[data-audio-license]').textContent = 'Recordings have separate artist-selected licenses. Attached excerpts retain per-track attribution and license links.'; } document.querySelectorAll('[data-related-music]').forEach(element => { element.hidden = !catalog.related_music; }); document.querySelectorAll('[data-source-genres]').forEach(element => { element.hidden = !catalog.source_genres; }); genres = new Map(catalog.genres.map(row => [row.genre_id, row])); await render(); }
catch (error) { heading.textContent = 'Catalog unavailable'; status.textContent = error.message; rows.append(button('Reload', () => location.reload())); content.setAttribute('aria-busy', 'false'); }
