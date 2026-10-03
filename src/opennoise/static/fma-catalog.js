/** Source-only FMA catalog. Native track annotations never imply artist memberships. */
const $ = selector => document.querySelector(selector);
const content = $('#content'), heading = $('h1'), status = $('#status'), rows = $('#rows'), pages = $('#pages'), query = $('#query'), scope = $('#scope');
$('.skip').addEventListener('click', event => { event.preventDefault(); content.focus(); });
const node = (tag, text) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; return element; };
const number = value => new Intl.NumberFormat('en').format(value);
const link = (text, hash) => { const element = node('a', text); element.href = hash; return element; };
const button = (text, action) => { const element = node('button', text); element.type = 'button'; element.addEventListener('click', action); return element; };
let catalog, genres, artists, artistIndex, generation = 0;
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
  let kind = params.has('artist') ? 'artist' : params.has('genre') ? 'genre' : params.has('artists') ? 'artists' : params.has('unannotated') ? 'unannotated' : params.has('tracks') ? 'tracks' : 'genres';
  const id = kind === 'artist' ? params.get('artist') : kind === 'genre' ? params.get('genre') : null;
  if (id !== null && (!/^(?:[1-9][0-9]*|null)$/.test(id) || (id !== 'null' && !Number.isSafeInteger(Number(id))))) kind = 'invalid';
  const requested = params.get('page');
  return {kind, id: id === 'null' ? null : id === null ? null : Number(id), q: params.get('q') ?? '', missing: params.get('missing') === '1', page: requested && /^[0-9]+$/.test(requested) ? Number(requested) : 0};
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
  const list = node('ul'); list.className = 'directory';
  for (const row of matches.slice(state.page * 100, state.page * 100 + 100)) { const item = node('li'); item.append(link(`${row.name} · #${row.id}`, `#${state.kind === 'artists' ? 'artist' : 'genre'}=${row.id}`), node('small', `${number(row.count)} tracks`)); list.append(item); }
  if (!matches.length) rows.append(node('p', 'No matching names or exact native IDs.'));
  rows.append(list);
}
function trackNode(track) {
  const [id, title, artistId, genreIds, licenseId, metadataUrl, albumId] = track;
  const row = node('article'); row.className = 'track'; row.dataset.trackId = id; row.dataset.evidenceRole = 'native_track_metadata';
  row.append(node('h2', `${title || 'Missing track title'} · #${id}`));
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
async function cohort(state, token) {
  await loadArtists();
  if (token !== generation) return;
  let ids, total, name;
  if (state.kind === 'artist') {
    const shard = await json(`artists/${(state.id ?? 0) % catalog.profile_shards}.json`), artist = shard.artists[String(state.id)];
    if (!artist) throw new Error('Native artist ID is absent');
    ids = artist.track_ids.slice(state.page * catalog.page_size, (state.page + 1) * catalog.page_size); total = artist.track_ids.length; name = `${artist.name} · #${state.id}`;
    if (token !== generation) return;
    status.textContent = `${number(total)} tracks with this native source artist ID.${artist.status === 'missing_source_artist_record' ? ' Artist record is missing from the source table.' : ''} Genre annotations below belong to each track.`;
  } else {
    const genre = genres.get(state.id);
    if (state.kind === 'genre' && !genre) throw new Error('Native genre ID is absent');
    total = state.kind === 'genre' ? genre.track_count : state.kind === 'unannotated' ? catalog.counts.unannotated_tracks : catalog.counts.raw_tracks;
    name = state.kind === 'genre' ? `${genre.title} · #${genre.genre_id}` : state.kind === 'unannotated' ? 'Tracks without genre annotations' : 'All raw source tracks';
    if (!paginate(total, state.page, catalog.page_size)) return;
    if (total) { const key = state.kind === 'genre' ? `genre-${state.id}` : state.kind === 'unannotated' ? 'unannotated' : 'all'; const payload = await json(`cohorts/${key}/${state.page}.json`); if (payload.cohort !== key || payload.page !== state.page || payload.total !== total) throw new Error('Track cohort identity mismatch'); ids = payload.track_ids; } else ids = [];
    if (token !== generation) return;
    status.textContent = `${number(total)} direct source tracks.${state.kind === 'genre' ? ` Native parent ID: ${genre.parent_id ?? 'not supplied'}. No parent annotations are inherited.` : ''}`;
  }
  const tracks = await tracksFor(ids);
  if (token !== generation) return;
  heading.textContent = name;
  if (state.kind === 'artist' && !paginate(total, state.page, catalog.page_size)) return;
  for (const track of tracks) rows.append(trackNode(track));
  if (!total) rows.append(node('p', 'No track annotations are present for this source record.'));
  heading.focus({preventScroll: true});
}
async function render() {
  const token = ++generation, state = route();
  content.setAttribute('aria-busy', 'true'); rows.replaceChildren(); pages.replaceChildren(); status.textContent = 'Loading…';
  if (['artists', 'genres'].includes(state.kind)) { scope.value = state.kind; query.value = state.q; }
  try {
    if (state.kind === 'invalid') throw new Error('Invalid native catalog ID');
    if (['artists', 'genres'].includes(state.kind)) await directory(state, token); else await cohort(state, token);
    if (token === generation) { content.setAttribute('aria-busy', 'false'); document.documentElement.dataset.fmaReady = 'true'; }
  } catch (error) {
    if (token !== generation) return;
    heading.textContent = 'Catalog unavailable'; status.textContent = error.message; rows.append(button('Retry', render)); content.setAttribute('aria-busy', 'false');
  }
}
function search(replace = false) {
  const params = new URLSearchParams(); params.set(scope.value, ''); if (query.value.trim()) params.set('q', query.value.trim());
  const hash = '#' + params.toString(); if (replace) { history.replaceState(null, '', hash); render(); } else if (location.hash !== hash) location.hash = hash; else render();
}
$('#search-form').addEventListener('submit', event => { event.preventDefault(); const first = rows.querySelector('.directory a'); if (first && route().q === query.value.trim()) first.click(); else search(); });
query.addEventListener('input', () => search(true)); scope.addEventListener('change', () => search());
query.addEventListener('keydown', event => { if (event.key === 'ArrowDown') { event.preventDefault(); rows.querySelector('.directory a')?.focus(); } });
document.addEventListener('keydown', event => { if (event.key === '/' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) { event.preventDefault(); query.focus(); } });
window.addEventListener('hashchange', render);
try { catalog = await json('catalog.json'); genres = new Map(catalog.genres.map(row => [row.genre_id, row])); await render(); }
catch (error) { heading.textContent = 'Catalog unavailable'; status.textContent = error.message; rows.append(button('Reload', () => location.reload())); content.setAttribute('aria-busy', 'false'); }
