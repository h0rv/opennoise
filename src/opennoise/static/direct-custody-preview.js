/** Local, static source explorer. All coordinates and model scores are precomputed. */
const $ = (selector) => document.querySelector(selector);
const canvas = $('#genre-map');
const context = canvas.getContext('2d');
const detail = $('#detail');
const search = $('#genre-search');
const results = $('#search-results');
let data, genres, selected, selectedArtist, hovered, width = 1, height = 1;
let camera = { scale: 1, x: 0, y: 0 }, fitScale = 1, drag = null, frame;
let labelTargets = [];
let view = 'map', sort = 'name', placement = 'all', page = 1, searchIndex = -1;
const PAGE_SIZE = 75;
let artistQuery = '', artistSort = 'id', artistExpanded = false, sourcePage = 1, searchScope = 'genres';
let artistSearchIndex, artistSearchPromise;
const sourcePages = new Map(), profiles = new Map(), genreDetails = new Map();
const hydratedGenres = new Set();
let selectionGeneration = 0;
let artistMap, artistMapQuery = '';
const artistMaps = new Map(), releaseContexts = new Map();
const safeArtistId = id => typeof id === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
const count = (value) => new Intl.NumberFormat('en').format(value);
const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};
const button = (text, className, action) => {
  const node = element('button', text, className);
  node.type = 'button'; node.addEventListener('click', action); return node;
};
const positioned = (genre) => Number.isFinite(genre.x) && Number.isFinite(genre.y);
const screen = (genre) => ({ x: genre.x * camera.scale + camera.x, y: genre.y * camera.scale + camera.y });
const redraw = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(draw); };

function currentHash(id = selected?.id, artist = selectedArtist) {
  const state = new URLSearchParams();
  if (id) state.set('genre', id);
  if (artist) state.set('artist', artist);
  if (view !== 'map') state.set('view', view);
  if (search.value.trim()) state.set('q', search.value.trim());
  if (sort !== 'name') state.set('sort', sort);
  if (placement !== 'all') state.set('placement', placement);
  if (page > 1) state.set('page', page);
  if (sourcePage > 1 && id === selected?.id) state.set('ap', sourcePage);
  if (searchScope !== 'genres') state.set('scope', searchScope);
  return `#${state}`;
}
function saveState(replace = false) {
  const hash = currentHash();
  if (hash !== location.hash) history[replace ? 'replaceState' : 'pushState']({}, '', hash);
}
function navigate(id, artist = null, focus = false) {
  if (!genres.has(id)) return;
  select(id, artist, focus);
  saveState();
}
function restoreState() {
  if (!data) return;
  const state = new URLSearchParams(location.hash.slice(1));
  view = ['list', 'artists'].includes(state.get('view')) ? state.get('view') : 'map';
  sort = ['name', 'artists', 'neighbors'].includes(state.get('sort')) ? state.get('sort') : 'name';
  placement = ['all', 'placed', 'unplaced'].includes(state.get('placement')) ? state.get('placement') : 'all';
  page = Math.max(1, Number.parseInt(state.get('page'), 10) || 1);
  search.value = state.get('q') ?? '';
  searchScope = state.get('scope') === 'artists' && data.artist_catalog ? 'artists' : 'genres';
  $(`#scope-${searchScope}`).checked = true;
  $('#genre-sort').value = sort; $('#genre-placement').value = placement;
  select(genres.has(state.get('genre')) ? state.get('genre') : data.default_genre, state.get('artist'), false);
  sourcePage = Math.max(1, Number.parseInt(state.get('ap'), 10) || 1);
  sourcePage = Math.min(sourcePage, selected.direct_artist_page_count || data.artist_catalog?.genre_page_counts?.[selected.id] || Number.MAX_SAFE_INTEGER);
  renderDetail(); renderView();
}
function select(id, artist, focus) {
  selectionGeneration++;
  const next = genres.get(id);
  if (selected?.id !== id) { artistQuery = ''; artistSort = 'id'; artistExpanded = false; sourcePage = 1; artistMap = null; artistMapQuery = ''; }
  selected = next; selectedArtist = Object.hasOwn(data.artists, artist) || (data.artist_catalog && safeArtistId(artist)) ? artist : null;
  if (focus && positioned(selected)) {
    camera.scale = Math.max(camera.scale, fitScale * 1.5);
    camera.x = width / 2 - selected.x * camera.scale;
    camera.y = (height + 155) / 2 - selected.y * camera.scale;
  }
  renderDetail(); redraw(); results.hidden = true;
  if (view === 'list') renderDirectory();
  if (view === 'artists' && artistMap?.genre_id !== selected.id) loadArtistMap(selected, selectionGeneration);
}
function selectionLink(text, className, id, artist = null, focus = false) {
  const node = element('a', text, className);
  node.href = currentHash(id, artist);
  node.addEventListener('click', event => {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); navigate(id, artist, focus);
  });
  return node;
}
function genreButton(id, className = 'genre-button') {
  const genre = genres.get(id);
  const node = selectionLink('', className, id, null, true);
  node.dataset.genreId = id;
  node.append(element('span', genre.name), element('small', `${count(genre.observed_artist_count)} artists`));
  return node;
}
function artistButton(id, proposal = false) {
  const artist = data.artists[id];
  const node = selectionLink('', 'artist-button', selected.id, id);
  node.dataset.artistId = id;
  node.dataset.evidenceRole = proposal ? 'inferred_artist_candidate' : 'direct_source_observation';
  node.append(element('span', artist.name), element('small', '>'));
  return node;
}
function renderDetail() {
  detail.replaceChildren();
  detail.scrollTop = 0;
  if (data.genre_details_revision && (!hydratedGenres.has(selected.id) || (!selectedArtist && selected.proposals.some(row => !Object.hasOwn(data.artists, row.artist_mbid))))) {
    detail.setAttribute('aria-busy', 'true');
    detail.append(element('h2', selected.name), element('p', 'Loading source observations and modeled neighbors…', 'muted'));
    loadSelectionDetail(selected, selectionGeneration); return;
  }
  detail.setAttribute('aria-busy', 'false');
  if (selectedArtist && !data.artists[selectedArtist]) {
    detail.append(element('h2', 'Loading artist…'), element('p', 'Loading this artist’s exact source profile.', 'muted'));
    loadArtistProfile(selectedArtist, selected.id); return;
  }
  if (selectedArtist) {
    const artist = data.artists[selectedArtist];
    detail.append(button(`← ${selected.name}`, 'back-button', () => navigate(selected.id)));
    detail.append(element('div', 'ARTIST · EXACT MUSICBRAINZ ID', 'eyebrow'), element('h2', artist.name));
    if (selected.proposals.some(row => row.artist_mbid === selectedArtist)) {
      detail.append(element('p', `Inferred proposal for ${selected.name}. Direct source observations are listed below.`, 'muted'));
    }
    const link = element('a', 'View artist on MusicBrainz', 'source-link');
    link.href = `https://musicbrainz.org/artist/${selectedArtist}`;
    link.target = '_blank'; link.rel = 'noopener noreferrer'; detail.append(link);
    detail.append(element('h3', 'Directly observed genres'), element('p', 'Exact proper-genre claims on this artist’s source record.', 'section-description'));
    const list = element('div', undefined, 'genre-list'); list.dataset.evidenceRole = 'direct_source_observation';
    for (const id of artist.genre_ids) if (genres.has(id)) list.append(genreButton(id));
    detail.append(list);
    detail.append(element('p', 'Open a genre to explore its source artists and modeled neighborhood.', 'muted'));
    appendReleaseContext(selected.id, selectedArtist);
    return;
  }
  detail.append(element('span', positioned(selected) ? 'GENRE · SOURCE OBSERVATIONS' : 'GENRE · UNPLACED', `role-badge${positioned(selected) ? '' : ' unplaced'}`));
  detail.append(element('h2', selected.name), element('div', `${count(selected.observed_artist_count)} directly observed artists`, 'count'));
  if (selected.native_genre_ids.length === 1) {
    const link = element('a', 'MusicBrainz genre record', 'source-link');
    link.href = `https://musicbrainz.org/genre/${selected.native_genre_ids[0]}`;
    link.target = '_blank'; link.rel = 'noopener noreferrer'; detail.append(link);
  }
  if (selected.label_status !== 'exact_native_uuid') detail.append(element('p', 'Native genre label unresolved. The exact source seed ID is retained.', 'muted'));
  if (!positioned(selected)) detail.append(element('p', 'This genre has source observations but insufficient shared-artist support for a model neighborhood. It remains unplaced.', 'empty-state'));
  if (selected.artist_map_path) detail.append(button('Explore artist map →', 'more-button', () => changeView('artists')));
  detail.append(element('h3', 'Artists in the source'), element('p', data.artist_catalog ? `${count(selected.observed_artist_count)} direct source artists. Browse the complete A–Z list.` : `${count(selected.direct_artist_ids.length)} bounded examples of ${count(selected.observed_artist_count)} source artists. Source ID order is not relevance.`, 'section-description'));
  if (data.artist_catalog && selected.direct_artist_page_count) {
    renderCompleteSourceArtists();
  } else {
  const artistTools = element('div', undefined, 'artist-tools');
  const artistFilter = element('input'); artistFilter.type = 'search'; artistFilter.placeholder = 'Filter source examples…';
  artistFilter.setAttribute('aria-label', 'Filter source artist examples'); artistFilter.value = artistQuery;
  const ordering = element('select'); ordering.setAttribute('aria-label', 'Sort source artist examples');
  for (const [value, label] of [['id', 'Source ID order'], ['name', 'Artist A–Z']]) {
    const option = element('option', label); option.value = value; ordering.append(option);
  }
  ordering.value = artistSort; artistTools.append(artistFilter, ordering); detail.append(artistTools);
  const direct = element('div', undefined, 'artist-list'); direct.dataset.evidenceRole = 'direct_source_observation';
  const artistStatus = element('p', '', 'section-description'); artistStatus.setAttribute('aria-live', 'polite');
  const showMore = button('Show all source examples', 'more-button', () => { artistExpanded = true; renderArtists(); });
  function renderArtists() {
    const ids = selected.direct_artist_ids.filter(id => data.artists[id].name.toLocaleLowerCase().includes(artistQuery.toLocaleLowerCase()));
    if (artistSort === 'name') ids.sort((a, b) => data.artists[a].name.localeCompare(data.artists[b].name) || a.localeCompare(b));
    direct.replaceChildren();
    for (const [index, id] of ids.entries()) { const node = artistButton(id); node.hidden = !artistExpanded && !artistQuery && index >= 8; direct.append(node); }
    if (!ids.length) direct.append(element('p', 'No matching source examples.', 'empty-state'));
    artistStatus.textContent = `${count(ids.length)} matching examples${artistQuery ? ` for “${artistQuery}”` : ''}.`;
    showMore.hidden = artistExpanded || Boolean(artistQuery) || ids.length <= 8;
  }
  artistFilter.addEventListener('input', () => { artistQuery = artistFilter.value; renderArtists(); });
  ordering.addEventListener('change', () => { artistSort = ordering.value; renderArtists(); });
  detail.append(direct, artistStatus, showMore); renderArtists();
  }
  detail.append(element('h3', 'Modeled neighbors'), element('span', 'INFERRED · SHARED ARTIST OVERLAP', 'role-badge inferred'));
  const peers = element('div', undefined, 'peer-list'); peers.dataset.evidenceRole = 'inferred_genre_overlap_neighbor';
  for (const peer of selected.peers) {
    const node = genreButton(peer.seed_id, 'peer-button');
    node.lastChild.textContent = `${count(peer.shared_artist_count)} shared`;
    peers.append(node);
  }
  if (!selected.peers.length) peers.append(element('p', 'No supported model neighbors.', 'muted'));
  detail.append(peers);
  detail.append(element('h3', 'Artist proposals'), element('span', 'INFERRED · FOR EXPLORATION', 'role-badge inferred'));
  detail.append(element('p', 'Suggested through neighboring genres. This artist ranking has not been evaluated.', 'section-description'));
  const proposals = element('div', undefined, 'proposal'); proposals.dataset.evidenceRole = 'inferred_artist_candidate';
  for (const proposal of selected.proposals) {
    proposals.append(artistButton(proposal.artist_mbid, true));
    const via = proposal.via_seed_ids.map(id => genres.get(id)?.name).filter(Boolean).join(', ');
    proposals.append(element('p', `Via ${via}`, 'section-description'));
    if (proposal.opposing_seed_ids?.length) {
      const opposing = proposal.opposing_seed_ids.map(id => genres.get(id)?.name).filter(Boolean).join(', ');
      proposals.append(element('p', `Opposing source genres in the model: ${opposing}`, 'section-description'));
    }
  }
  if (!selected.proposals.length) proposals.append(element('p', 'No artist proposals.', 'muted'));
  detail.append(proposals);
  appendReleaseContext(selected.id);
}
async function staticJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
async function ensureGenre(genre) {
  if (!data.genre_details_revision || hydratedGenres.has(genre.id)) return genre;
  if (!/^[a-zA-Z0-9_-]+$/.test(genre.id)) throw new Error('Unsupported genre source ID');
  const path = `genre-details/${genre.id}.json`;
  if (genre.detail_path !== path) throw new Error('Genre detail path mismatch');
  if (!genreDetails.has(genre.id)) genreDetails.set(genre.id, staticJson(path).then(payload => {
    if (payload.id !== genre.id || !Array.isArray(payload.native_genre_ids) || !Array.isArray(payload.peers) || !Array.isArray(payload.proposals) || !Array.isArray(payload.direct_artist_ids)) throw new Error('Genre detail identity or shape mismatch');
    if (payload.artist_profiles) {
      for (const [id, profile] of Object.entries(payload.artist_profiles)) {
        if (!safeArtistId(id) || typeof profile.name !== 'string' || !Array.isArray(profile.genre_ids)) throw new Error('Genre artist profile identity or shape mismatch');
        data.artists[id] = profile;
      }
    }
    Object.assign(genre, payload); hydratedGenres.add(genre.id); return genre;
  }).catch(error => { genreDetails.delete(genre.id); throw error; }));
  return genreDetails.get(genre.id);
}
async function ensureProfiles(ids) {
  const missing = ids.filter(id => !Object.hasOwn(data.artists, id));
  if (!missing.length) return;
  if (!data.artist_catalog || missing.some(id => !safeArtistId(id))) throw new Error('Unsupported source artist profile ID');
  const catalog = data.artist_catalog;
  const prefixes = [...new Set(missing.map(id => id.slice(0, catalog.prefix_length)))];
  await Promise.all(prefixes.map(async prefix => {
    const path = `artists/${prefix}.json`;
    if (catalog.profile_path_template.replace('{prefix}', prefix) !== path) throw new Error('Artist profile path mismatch');
    if (!profiles.has(prefix)) profiles.set(prefix, staticJson(path).then(shard => {
      if (!shard.artists || typeof shard.artists !== 'object') throw new Error('Artist profile shard shape mismatch');
      Object.assign(data.artists, shard.artists); return shard;
    }).catch(error => { profiles.delete(prefix); throw error; }));
    await profiles.get(prefix);
  }));
  if (missing.some(id => !Object.hasOwn(data.artists, id))) throw new Error('Artist profile absent from source shard');
}
async function loadSelectionDetail(genre, generation) {
  try {
    await ensureGenre(genre);
    if (generation !== selectionGeneration || selected.id !== genre.id) return;
    if (!selectedArtist) await ensureProfiles(genre.proposals.map(row => row.artist_mbid));
    if (generation !== selectionGeneration || selected.id !== genre.id) return;
    sourcePage = Math.min(sourcePage, genre.direct_artist_page_count || 1);
    renderDetail(); redraw();
    if (view === 'list') renderDirectory();
  } catch (error) {
    if (generation !== selectionGeneration || selected.id !== genre.id) return;
    detail.setAttribute('aria-busy', 'false');
    detail.replaceChildren(element('h2', genre.name), element('p', `The static genre details could not load: ${error.message}`, 'profile-error'), button('Retry genre details', 'more-button', renderDetail));
  }
}
async function loadArtistProfile(id, genreId, generation = selectionGeneration) {
  try {
    await ensureProfiles([id]);
    if (generation === selectionGeneration && selectedArtist === id && selected.id === genreId) renderDetail();
  } catch (error) {
    if (generation !== selectionGeneration || selectedArtist !== id || selected.id !== genreId) return;
    detail.replaceChildren(button(`← ${selected.name}`, 'back-button', () => navigate(selected.id)), element('h2', 'Artist profile unavailable'), element('p', `The static source profile could not load: ${error.message}`, 'profile-error'), button('Retry source profile', 'more-button', () => loadArtistProfile(id, genreId)));
  }
}
function renderCompleteSourceArtists() {
  const genre = selected, requestedPage = Math.min(sourcePage, genre.direct_artist_page_count);
  const direct = element('div', undefined, 'artist-list'); direct.dataset.evidenceRole = 'direct_source_observation'; direct.setAttribute('aria-busy', 'true');
  const tools = element('div', undefined, 'artist-tools');
  const filter = element('input'); filter.type = 'search'; filter.placeholder = 'Filter artists on this page…'; filter.setAttribute('aria-label', 'Filter source artists on this page'); filter.value = artistQuery;
  tools.append(filter); detail.append(tools, direct);
  const status = element('p', `Loading source page ${requestedPage}…`, 'section-description'); status.setAttribute('aria-live', 'polite'); detail.append(status);
  const more = button('Show all artists on this page', 'more-button', () => { artistExpanded = true; filter.dispatchEvent(new Event('input')); }); more.hidden = true; detail.append(more);
  const controls = element('nav', undefined, 'artist-page-controls'); controls.setAttribute('aria-label', 'Source artist pages');
  const changePage = value => { sourcePage = value; artistQuery = ''; artistExpanded = false; renderDetail(); saveState(); };
  const previous = button('← Previous', 'page-button', () => changePage(requestedPage - 1)); previous.disabled = requestedPage <= 1;
  const next = button('Next →', 'page-button', () => changePage(requestedPage + 1)); next.disabled = requestedPage >= genre.direct_artist_page_count;
  controls.append(previous, element('span', `${requestedPage} / ${genre.direct_artist_page_count}`), next); detail.append(controls);
  const path = data.artist_catalog.genre_pages_path_template.replace('{genre_id}', genre.id).replace('{page}', requestedPage - 1);
  const key = `${genre.id}/${requestedPage}`;
  if (!sourcePages.has(key)) sourcePages.set(key, staticJson(path));
  sourcePages.get(key).then(payload => {
    if (selected.id !== genre.id || sourcePage !== requestedPage || selectedArtist || !direct.isConnected) return;
    if (payload.genre_id !== genre.id || payload.page !== requestedPage - 1) throw new Error('Source page identity mismatch');
    for (const artist of payload.artists) data.artists[artist.id] = artist;
    const render = () => {
      const matches = payload.artists.filter(artist => artist.name.toLocaleLowerCase().includes(filter.value.toLocaleLowerCase()));
      artistQuery = filter.value; direct.replaceChildren();
      for (const [index, artist] of matches.entries()) { const node = artistButton(artist.id); node.hidden = !artistExpanded && !filter.value && index >= 8; direct.append(node); }
      more.hidden = artistExpanded || Boolean(filter.value) || matches.length <= 8;
      if (!matches.length) direct.append(element('p', 'No matching artists on this page.', 'empty-state'));
      status.textContent = `${count(!artistExpanded && !filter.value ? Math.min(8, matches.length) : matches.length)} of ${payload.artists.length} artists shown on page ${requestedPage} · ${count(payload.total_count)} total source artists.`;
    };
    direct.setAttribute('aria-busy', 'false'); filter.addEventListener('input', render); render();
  }).catch(error => {
    sourcePages.delete(key); if (!direct.isConnected) return;
    direct.setAttribute('aria-busy', 'false'); status.textContent = `Source page unavailable: ${error.message}`;
    direct.append(button('Retry source page', 'more-button', renderDetail));
  });
}
async function searchArtists() {
  const query = search.value.trim().toLocaleLowerCase(); results.replaceChildren(); results.hidden = !query;
  if (!query) return;
  results.append(element('p', 'Searching source artists…', 'search-empty'));
  try {
    if (!artistSearchPromise) artistSearchPromise = staticJson(data.artist_catalog.search_path);
    if (!artistSearchIndex) artistSearchIndex = (await artistSearchPromise).artists;
    if (searchScope !== 'artists' || search.value.trim().toLocaleLowerCase() !== query) return;
    const matches = artistSearchIndex.filter(row => row[1].toLocaleLowerCase().includes(query) || row[0].toLocaleLowerCase().includes(query));
    results.replaceChildren();
    for (const [id, name] of matches.slice(0, 50)) {
      const node = button('', 'search-result', () => navigate(selected.id, id)); node.dataset.artistId = id;
      node.append(element('span', name), element('small', 'Source artist')); results.append(node);
    }
    if (!matches.length) results.append(element('p', 'No matching source artists.', 'search-empty'));
    if (matches.length > 50) results.append(element('p', `${count(matches.length)} matches · first 50 shown. Refine your search.`, 'search-empty'));
    $('#search-status').textContent = `${count(matches.length)} matching source artists. Showing ${Math.min(50, matches.length)}.`;
  } catch (error) {
    artistSearchPromise = null; results.replaceChildren(element('p', `Artist search unavailable: ${error.message}`, 'search-empty'));
    results.append(button('Retry artist search', 'search-more', searchArtists));
  }
}
async function loadArtistMap(genre, generation = selectionGeneration) {
  artistMap = null; $('#artist-map-status').textContent = 'Loading the source artist map…';
  $('#artist-map-results').replaceChildren(); redraw();
  try {
    await ensureGenre(genre);
    const path = `genre-artist-maps/${genre.id}.json`;
    if (!/^[a-zA-Z0-9_-]+$/.test(genre.id) || genre.artist_map_path !== path) throw new Error('Artist map unavailable for this genre');
    if (!artistMaps.has(genre.id)) artistMaps.set(genre.id, staticJson(path).then(payload => {
      if (payload.genre_id !== genre.id || payload.role !== 'inferred_artist_overlap_map' || !Array.isArray(payload.artists)) throw new Error('Artist map identity or role mismatch');
      for (const artist of payload.artists) {
        if (!safeArtistId(artist.id) || typeof artist.name !== 'string' || !Array.isArray(artist.genre_ids)) throw new Error('Artist map source profile mismatch');
        data.artists[artist.id] = {name: artist.name, name_status: artist.name_status, genre_ids: artist.genre_ids};
      }
      return payload;
    }).catch(error => { artistMaps.delete(genre.id); throw error; }));
    const payload = await artistMaps.get(genre.id);
    if (generation !== selectionGeneration || selected.id !== genre.id || view !== 'artists') return;
    artistMap = payload; renderArtistMapTools(); fit();
  } catch (error) {
    if (generation !== selectionGeneration || selected.id !== genre.id || view !== 'artists') return;
    $('#artist-map-status').textContent = `Artist map unavailable: ${error.message}`;
    $('#artist-map-results').replaceChildren(button('Retry artist map', 'more-button', () => loadArtistMap(selected)));
  }
}
function renderArtistMapTools() {
  if (!artistMap) return;
  $('.map-intro h1').textContent = `${selected.name} artists`;
  const selectionCaption = artistMap.candidate_selection?.includes('affinity') ? 'Sample selection uses source genre affinity, then exact ID; it is not an importance ranking.' : 'Sample selection uses source genre count, then exact ID; it is not an importance ranking.';
  $('#artist-map-status').textContent = `${count(artistMap.positioned_count)} placed · ${count(artistMap.abstained_count)} unplaced · ${count(artistMap.selected_count)} of ${count(artistMap.total_count)} source artists${artistMap.truncated ? ' (bounded sample)' : ''}. Inferred source profile overlap; map quality not evaluated. ${selectionCaption}`;
  const list = $('#artist-map-results'); list.replaceChildren(); list.dataset.evidenceRole = 'inferred_artist_overlap_map';
  for (const artist of artistMap.artists.filter(row => row.name.toLocaleLowerCase().includes(artistMapQuery.toLocaleLowerCase()))) {
    const node = artistButton(artist.id); node.lastChild.textContent = positioned(artist) ? 'On map' : 'Unplaced'; list.append(node);
  }
  if (!list.children.length) list.append(element('p', 'No matching artists in this map sample.', 'empty-state'));
  redraw();
}
function musicBrainzLink(kind, id, label, className = 'source-link') {
  if (!safeArtistId(id)) return element('span', label);
  const node = element('a', label, className); node.href = `https://musicbrainz.org/${kind}/${id}`;
  node.target = '_blank'; node.rel = 'noopener noreferrer'; return node;
}
function creditText(credit) {
  return (credit?.members ?? []).map(member => `${member.credited_name || member.artist_name || 'Unnamed artist'}${member.join_phrase || ''}`).join('');
}
function creditRoleText(roles) {
  return (roles ?? []).map(role => ({release_artist_credit: 'release artist credit', recording_artist_credit: 'recording artist credit'})[role] ?? role.replaceAll('_', ' ')).join(', ');
}
function appendReleaseContext(genreId, artistId = null) {
  if (!data.release_contexts) return;
  const registry = artistId ? data.release_contexts.artist_paths : data.release_contexts.genre_paths;
  const path = registry?.[artistId || genreId] || (!artistId ? selected.release_context_path : null);
  if (!path) {
    detail.append(element('h3', 'Release metadata'), element('p', `No release-credit metadata is included for this ${artistId ? 'artist' : 'genre’s source artists'} in the local snapshot.`, 'section-description'));
    return;
  }
  const contextSection = element('details', undefined, 'release-context'); contextSection.dataset.evidenceRole = 'source_release_credit_context';
  contextSection.append(element('summary', 'Releases credited to source artists'));
  const content = element('div', undefined, 'release-context-content'); contextSection.append(content); detail.append(contextSection);
  const generation = selectionGeneration;
  let loaded = false, loading = false;
  const load = async () => {
    if (loaded || loading) return;
    loading = true; content.replaceChildren(element('p', 'Loading release credits…', 'section-description')); content.setAttribute('aria-busy', 'true');
    try {
      const expectedPath = artistId ? `artist-releases/${artistId}.json` : `genre-release-examples/${genreId}.json`;
      if (path !== expectedPath) throw new Error('Release context path mismatch');
      if (!releaseContexts.has(path)) releaseContexts.set(path, staticJson(path).catch(error => { releaseContexts.delete(path); throw error; }));
      const payload = await releaseContexts.get(path);
      if ((artistId ? payload.artist_mbid !== artistId : payload.seed_id !== genreId) || !Array.isArray(payload.releases) || payload.native_release_genres_available !== false) throw new Error('Release credit identity or source boundary mismatch');
      if (generation !== selectionGeneration || !contextSection.isConnected) return;
      content.replaceChildren(element('p', 'Release credits identify source artists; they do not establish genre membership for releases or tracks.', 'section-description'));
      content.append(element('p', `${count(payload.releases.length)} of ${count(payload.total_release_count)} retained releases${payload.remaining_release_count ? ` · ${count(payload.remaining_release_count)} additional releases outside this bounded context` : ''}. Concrete release dates and exact source ID order.`, 'section-description'));
      for (const release of payload.releases) {
        const card = element('article', undefined, 'release-card');
        const title = element('h4'); title.append(musicBrainzLink('release', release.release_mbid, release.title || release.release_group_title || 'Untitled release', 'release-title')); card.append(title);
        card.append(element('p', [release.date || release.year, release.country, release.status].filter(Boolean).join(' · '), 'section-description'));
        const credit = creditText(release.release_artist_credit); if (credit) card.append(element('p', `Release artist credit: ${credit}`, 'release-credit'));
        if (release.queried_artist_credit_roles?.length) card.append(element('p', `This source artist appears in the ${creditRoleText(release.queried_artist_credit_roles)}.`, 'section-description'));
        if (release.matched_source_artists?.length) {
          const credits = element('p', undefined, 'release-credit'); credits.append(document.createTextNode('Source artist credits: '));
          for (const [index, artist] of release.matched_source_artists.entries()) {
            if (index) credits.append(document.createTextNode('; '));
            credits.append(musicBrainzLink('artist', artist.artist_mbid, artist.artist_name || data.artists[artist.artist_mbid]?.name || 'View credited source artist', 'release-credit-link'), document.createTextNode(` (${creditRoleText(artist.credit_roles)})`));
          }
          card.append(credits);
        }
        const tracks = element('details', undefined, 'release-tracks'); tracks.append(element('summary', `${(release.tracks ?? []).length} tracks`));
        const trackList = element('ol');
        for (const track of release.tracks ?? []) {
          const row = element('li'); row.append(element('span', `${track.medium_position ? `Disc ${track.medium_position} · ` : ''}${track.number || track.position || ''} `, 'track-position')); row.append(musicBrainzLink('recording', track.recording_mbid, track.title || track.recording_title || 'Untitled track', 'track-title'));
          if (Number.isFinite(track.duration_ms) && track.duration_ms > 0) row.append(element('small', `${Math.floor(track.duration_ms / 60000)}:${String(Math.floor(track.duration_ms / 1000) % 60).padStart(2, '0')}`));
          const recordingCredit = creditText(track.recording_artist_credit); if (recordingCredit) row.append(element('div', recordingCredit, 'track-credit')); trackList.append(row);
        }
        tracks.append(trackList); card.append(tracks, musicBrainzLink('release-group', release.release_group_mbid, 'MusicBrainz release group')); content.append(card);
      }
      if (!payload.releases.length) content.append(element('p', 'No release credits in this local context.', 'section-description'));
      loaded = true;
    } catch (error) {
      if (generation !== selectionGeneration || !contextSection.isConnected) return;
      content.replaceChildren(element('p', `Release metadata unavailable: ${error.message}`, 'section-description'), button('Retry release metadata', 'more-button', load));
    } finally { loading = false; content.setAttribute('aria-busy', 'false'); }
  };
  contextSection.addEventListener('toggle', () => { if (contextSection.open) load(); });
}
function matchedGenres() {
  const query = searchScope === 'genres' ? search.value.trim().toLocaleLowerCase() : '';
  return data.genres.filter(genre => (!query || genre.name.toLocaleLowerCase().includes(query)) &&
    (placement === 'all' || (placement === 'placed') === positioned(genre)));
}
function sortedGenres(matches) {
  return matches.sort((a, b) => (sort === 'artists' ? (b.observed_artist_count ?? b.genre_ids?.length ?? 0) - (a.observed_artist_count ?? a.genre_ids?.length ?? 0) :
    sort === 'neighbors' ? (b.modeled_neighbor_count ?? b.peers.length) - (a.modeled_neighbor_count ?? a.peers.length) : 0) || a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
}
function searchGenres(unplaced = false) {
  if (!data) return;
  if (searchScope === 'artists' && !unplaced) { searchArtists(); return; }
  const query = search.value.trim().toLocaleLowerCase();
  const matches = data.genres.filter(genre => (!unplaced || !positioned(genre)) && (!query || genre.name.toLocaleLowerCase().includes(query)));
  matches.sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
  results.replaceChildren(); searchIndex = -1; results.hidden = view === 'list' || (!query && !unplaced);
  for (const genre of matches.slice(0, 30)) {
    const node = button('', 'search-result', () => navigate(genre.id, null, true));
    node.dataset.genreId = genre.id;
    node.append(element('span', genre.name), element('small', positioned(genre) ? `${count(genre.observed_artist_count)} artists` : 'Unplaced'));
    results.append(node);
  }
  if (!matches.length) results.append(element('p', 'No matching source genres.', 'search-empty'));
  if (matches.length > 30) results.append(button(`Browse all ${count(matches.length)} matches →`, 'search-more', () => changeView('list')));
  $('#search-status').textContent = `${matches.length} matching genres. Showing ${Math.min(30, matches.length)}.`;
}
function renderDirectory() {
  if (!data) return;
  const matches = sortedGenres(matchedGenres());
  const pages = Math.max(1, Math.ceil(matches.length / PAGE_SIZE)); page = Math.min(page, pages);
  const start = (page - 1) * PAGE_SIZE;
  const directory = $('#directory-results'); directory.replaceChildren();
  for (const genre of matches.slice(start, start + PAGE_SIZE)) {
    const node = genreButton(genre.id, 'directory-genre');
    node.classList.toggle('selected', genre.id === selected.id);
    if (genre.id === selected.id) node.setAttribute('aria-current', 'true');
    node.lastChild.textContent = `${count(genre.observed_artist_count)} artists · ${positioned(genre) ? `${genre.modeled_neighbor_count ?? genre.peers.length} modeled neighbors` : 'unplaced'}`;
    directory.append(node);
  }
  if (!matches.length) directory.append(element('p', 'No matching source genres. Try another search or placement filter.', 'empty-state'));
  $('#directory-status').textContent = `${count(matches.length)} genres${matches.length ? ` · ${start + 1}–${Math.min(start + PAGE_SIZE, matches.length)} shown` : ''}`;
  const pagination = $('#directory-pages'); pagination.replaceChildren();
  const previous = button('← Previous', 'page-button', () => { page--; renderDirectory(); saveState(); $('#genre-directory').scrollTop = 0; }); previous.disabled = page === 1;
  const next = button('Next →', 'page-button', () => { page++; renderDirectory(); saveState(); $('#genre-directory').scrollTop = 0; }); next.disabled = page === pages;
  pagination.append(previous, element('span', `Page ${page} of ${pages}`), next);
}
function renderView() {
  $('#genre-directory').hidden = view !== 'list'; canvas.hidden = view === 'list';
  $('.map-controls').hidden = view === 'list'; $('.map-caption').hidden = view === 'list';
  $('#artist-map-tools').hidden = view !== 'artists';
  canvas.dataset.evidenceRole = view === 'artists' ? 'inferred_artist_overlap_map' : 'inferred_genre_overlap_neighbor';
  canvas.setAttribute('aria-label', `${view === 'artists' ? 'Bounded source artist map, inferred from source genre overlap' : 'Genre neighborhood map'}. Drag to pan, scroll to zoom. Arrow keys pan, plus and minus zoom, Home resets. Search and lists provide access to unplaced items.`);
  $('.map-intro h1').textContent = view === 'artists' ? `${selected.name} artists` : 'Follow the connections.';
  $('.map-intro > p:last-child').textContent = view === 'artists' ? 'Direct source artists · inferred profile overlap.' : 'Explore genres through the artists they share.';
  $('.map-caption > span').textContent = view === 'artists' ? 'Inferred artist profile overlap · no acoustic axes' : 'Source overlap neighborhoods';
  $('.map-caption > div').hidden = view === 'artists';
  $('#view-map').setAttribute('aria-pressed', String(view === 'map'));
  $('#view-list').setAttribute('aria-pressed', String(view === 'list'));
  results.hidden = true;
  if (view === 'list') renderDirectory();
  else if (view === 'artists') {
    if (artistMap?.genre_id !== selected.id) loadArtistMap(selected); else { renderArtistMapTools(); fit(); }
  } else fit();
}
function changeView(next) {
  view = next; renderView(); saveState();
}
function fit() {
  fitScale = Math.min((width - 75) / (16 / 9), Math.max(100, height - 285));
  camera = { scale: fitScale, x: (width - (16 / 9) * fitScale) / 2, y: 195 + (height - 275 - fitScale) / 2 };
  redraw();
}
function zoom(factor, x = width / 2, y = (height + 155) / 2) {
  const next = Math.min(fitScale * 24, Math.max(fitScale * .55, camera.scale * factor));
  const ratio = next / camera.scale;
  camera.x = x - (x - camera.x) * ratio; camera.y = y - (y - camera.y) * ratio; camera.scale = next; redraw();
}
function nearest(x, y) {
  for (const box of labelTargets.toReversed()) if (x >= box.x && x <= box.x + box.w && y >= box.y && y <= box.y + box.h) return view === 'artists' ? artistMap?.artists.find(row => row.id === box.id) : genres.get(box.id);
  let best = null, distance = 18;
  for (const genre of (view === 'artists' ? artistMap?.artists ?? [] : data?.genres ?? [])) {
    if (!positioned(genre)) continue;
    const point = screen(genre), delta = Math.hypot(point.x - x, point.y - y);
    if (delta < distance) { distance = delta; best = genre; }
  }
  return best;
}
function draw() {
  context.clearRect(0, 0, width, height);
  labelTargets = [];
  if (!data) return;
  const mapArtist = view === 'artists' ? artistMap?.artists.find(row => row.id === selectedArtist) : null;
  const peerIds = new Set(view === 'artists' ? mapArtist?.neighbors?.map(row => row.id) ?? [] : selected?.peers.map(row => row.seed_id) ?? []);
  if (mapArtist && positioned(mapArtist)) {
    const origin = screen(mapArtist);
    for (const neighbor of mapArtist.neighbors ?? []) {
      const targetArtist = artistMap.artists.find(row => row.id === neighbor.id); if (!targetArtist || !positioned(targetArtist)) continue;
      const target = screen(targetArtist);
      context.beginPath(); context.moveTo(origin.x, origin.y); context.lineTo(target.x, target.y);
      context.strokeStyle = '#7599874a'; context.lineWidth = 1; context.stroke();
    }
  }
  if (view !== 'artists' && selected && positioned(selected)) {
    const origin = screen(selected);
    for (const peer of selected.peers) {
      const genre = genres.get(peer.seed_id); if (!positioned(genre)) continue;
      const target = screen(genre);
      context.beginPath(); context.moveTo(origin.x, origin.y); context.lineTo(target.x, target.y);
      context.strokeStyle = '#7599874a'; context.lineWidth = 1; context.stroke();
    }
  }
  const nodes = view === 'artists' ? (artistMap?.artists ?? []).filter(row => row.name.toLocaleLowerCase().includes(artistMapQuery.toLocaleLowerCase())) : data.genres;
  const activeId = view === 'artists' ? selectedArtist : selected?.id;
  const ordered = nodes.filter(positioned).sort((a, b) => {
    const priority = (genre) => genre.id === hovered?.id ? 4 : genre.id === activeId ? 3 : peerIds.has(genre.id) ? 2 : 1;
    return priority(b) - priority(a) || (b.observed_artist_count ?? b.genre_ids?.length ?? 0) - (a.observed_artist_count ?? a.genre_ids?.length ?? 0) || a.id.localeCompare(b.id);
  });
  const boxes = []; let labelCount = 0;
  for (const genre of ordered) {
    const point = screen(genre); if (point.x < -10 || point.x > width + 10 || point.y < -10 || point.y > height + 10) continue;
    const active = genre.id === activeId, related = peerIds.has(genre.id), over = genre.id === hovered?.id;
    const radius = active ? 6 : Math.min(4.2, 1.4 + Math.log1p(genre.observed_artist_count ?? genre.genre_ids?.length ?? 0) * .24);
    context.beginPath(); context.arc(point.x, point.y, radius, 0, Math.PI * 2);
    context.fillStyle = active ? '#cc552f' : related || over ? '#377d6b' : `hsl(${135 + genre.x * 105} 32% 48% / .62)`; context.fill();
    if (active) { context.beginPath(); context.arc(point.x, point.y, 10, 0, Math.PI * 2); context.strokeStyle = '#cc552f66'; context.stroke(); }
    if (point.y < 205 || point.y > height - 38 || labelCount >= 280) continue;
    context.font = `${active || over ? '650' : '450'} ${active ? 16 : related ? 13 : 10 + Math.min(3, Math.log1p(genre.observed_artist_count ?? genre.genre_ids?.length ?? 0) * .32)}px system-ui`;
    const textWidth = context.measureText(genre.name).width, x = Math.min(width - textWidth - 12, Math.max(12, point.x + 8)), y = point.y + 4;
    const box = { x: x - 3, y: y - 13, w: textWidth + 8, h: 18 };
    if (!active && !over && boxes.some(other => box.x < other.x + other.w && box.x + box.w > other.x && box.y < other.y + other.h && box.y + box.h > other.y)) continue;
    boxes.push(box); labelCount++;
    labelTargets.push({ ...box, id: genre.id });
    context.fillStyle = '#f6f8f0db'; context.fillRect(box.x, box.y, box.w, box.h);
    context.fillStyle = active ? '#ab4324' : related || over ? '#254f40' : `hsl(${135 + genre.x * 105} 30% 32%)`; context.fillText(genre.name, x, y);
  }
}

search.addEventListener('input', () => { page = 1; searchGenres(); if (view === 'list') renderDirectory(); saveState(true); redraw(); });
search.addEventListener('keydown', event => {
  const buttons = [...results.querySelectorAll('button')];
  if (event.key === 'Escape') results.hidden = true;
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault(); if (results.hidden) searchGenres();
    searchIndex = Math.max(0, Math.min(buttons.length - 1, searchIndex + (event.key === 'ArrowDown' ? 1 : -1)));
    buttons[searchIndex]?.focus();
  }
  if (event.key === 'Enter' && !results.hidden) { event.preventDefault(); buttons[Math.max(0, searchIndex)]?.click(); }
});
results.addEventListener('keydown', event => {
  const buttons = [...results.querySelectorAll('button')], index = buttons.indexOf(document.activeElement);
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); searchIndex = Math.max(0, Math.min(buttons.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1))); buttons[searchIndex]?.focus(); }
  if (event.key === 'Escape') { results.hidden = true; search.focus(); }
});
$('#show-unplaced').addEventListener('click', () => { search.value = ''; searchScope = 'genres'; $('#scope-genres').checked = true; searchGenres(true); search.focus(); });
$('#browse-all').addEventListener('click', () => { search.value = ''; searchScope = 'genres'; $('#scope-genres').checked = true; placement = 'all'; page = 1; $('#genre-placement').value = placement; changeView('list'); });
$('#artist-map-close').addEventListener('click', () => changeView('map'));
$('#artist-map-query').addEventListener('input', event => { artistMapQuery = event.target.value; renderArtistMapTools(); });
$('#artist-map-list-toggle').addEventListener('click', event => { const list = $('#artist-map-results'); list.hidden = !list.hidden; event.currentTarget.setAttribute('aria-expanded', String(!list.hidden)); });
$('#view-map').addEventListener('click', () => changeView('map'));
$('#view-list').addEventListener('click', () => changeView('list'));
$('#genre-sort').addEventListener('change', event => { sort = event.target.value; page = 1; renderDirectory(); saveState(); });
$('#genre-placement').addEventListener('change', event => { placement = event.target.value; page = 1; renderDirectory(); saveState(); });
for (const input of document.querySelectorAll('[name=search-scope]')) input.addEventListener('change', () => { searchScope = input.value; page = 1; searchGenres(); if (view === 'list') renderDirectory(); saveState(); });
document.addEventListener('keydown', event => { if (event.key === '/' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) { event.preventDefault(); search.focus(); } });
document.addEventListener('pointerdown', event => { if (!event.target.closest('.search-box')) results.hidden = true; });
$('#fit-map').addEventListener('click', fit);
$('#zoom-in').addEventListener('click', () => zoom(1.4));
$('#zoom-out').addEventListener('click', () => zoom(1 / 1.4));
$('#about-toggle').addEventListener('click', (event) => { const about = $('#about'); about.hidden = !about.hidden; event.currentTarget.setAttribute('aria-expanded', String(!about.hidden)); if (!about.hidden) about.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); });
canvas.addEventListener('wheel', (event) => { event.preventDefault(); const rect = canvas.getBoundingClientRect(); zoom(Math.exp(-event.deltaY * .002), event.clientX - rect.left, event.clientY - rect.top); }, { passive: false });
canvas.addEventListener('pointerdown', (event) => { drag = { x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY }; canvas.setPointerCapture(event.pointerId); results.hidden = true; });
canvas.addEventListener('pointermove', (event) => {
  if (drag) { camera.x += event.clientX - drag.x; camera.y += event.clientY - drag.y; drag.x = event.clientX; drag.y = event.clientY; }
  else { const rect = canvas.getBoundingClientRect(); hovered = nearest(event.clientX - rect.left, event.clientY - rect.top); canvas.title = hovered?.name ?? ''; }
  redraw();
});
canvas.addEventListener('pointerup', (event) => {
  if (drag && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 5) { const rect = canvas.getBoundingClientRect(), genre = nearest(event.clientX - rect.left, event.clientY - rect.top); if (genre) view === 'artists' ? navigate(selected.id, genre.id) : navigate(genre.id); }
  drag = null;
});
canvas.addEventListener('pointercancel', () => { drag = null; });
canvas.addEventListener('keydown', (event) => {
  const actions = { '+': () => zoom(1.3), '=': () => zoom(1.3), '-': () => zoom(1 / 1.3), Home: fit, ArrowLeft: () => { camera.x += 40; }, ArrowRight: () => { camera.x -= 40; }, ArrowUp: () => { camera.y += 40; }, ArrowDown: () => { camera.y -= 40; } };
  if (actions[event.key]) { event.preventDefault(); actions[event.key](); redraw(); }
});
window.addEventListener('popstate', restoreState);
window.addEventListener('hashchange', restoreState);
new ResizeObserver(() => { const rect = canvas.getBoundingClientRect(); if (!rect.width || !rect.height) return; width = rect.width; height = rect.height; const ratio = devicePixelRatio || 1; canvas.width = width * ratio; canvas.height = height * ratio; context.setTransform(ratio, 0, 0, ratio, 0, 0); fit(); }).observe(canvas);

try {
  const response = await fetch('data.json'); if (!response.ok) throw new Error(`HTTP ${response.status}`);
  data = await response.json(); genres = new Map(data.genres.map(genre => [genre.id, genre]));
  if (data.scope !== 'local_research_only' || data.public_export_authorized !== false) throw new Error('Unsupported preview boundary');
  $('#corpus-status').textContent = `${count(data.genres.length)} genres · ${count(data.artist_count)} source artists · ${count(data.unplaced_count)} unplaced`;
  $('#show-unplaced').textContent = `${data.unplaced_count} unplaced genres`;
  $('#evaluation-note').textContent = data.evaluation_note;
  $('.search-scope').hidden = !data.artist_catalog;
  restoreState();
  document.documentElement.dataset.previewReady = 'true';
} catch (error) {
  detail.replaceChildren(element('h2', 'Source graph unavailable'), element('p', `The local preview could not load: ${error.message}`, 'muted'));
  $('#corpus-status').textContent = 'Local data unavailable';
}
