import {normalizeName} from './full-foundation-normalization.mjs';

const main = document.querySelector('main');
const input = document.querySelector('input');
const make = (tag, text) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; };
const link = (text, href) => { const n = make('a', text); n.href = href; return n; };
const norm = value => normalizeName(value).normalize('NFKD').replace(/\p{M}/gu, '');
const route = (kind, id = '', view = '', page = 0) => `#${kind}${id ? '/' + encodeURIComponent(id) : ''}${view ? '/' + view + '/' + page : ''}`;
const offline = location.protocol === 'file:';
const networkURL = id => `artist-network/${offline ? 'OpenNoiseArtists.html' : ''}${id ? '#artist/' + id : ''}`;
let bundled, genres, byGenre, artists, byArtist, native, sequence = 0;
const detailCache = new Map();

async function load(path) {
  if (bundled) { if (!(path in bundled)) throw Error('Incomplete offline export'); return bundled[path]; }
  const response = await fetch(path);
  if (!response.ok) throw Error('Missing atlas data');
  return response.json();
}
async function artistIndex() {
  if (!artists) { artists = await load('atlas/artists.json'); byArtist = new Map(artists.map(a => [a.id, a])); }
  return artists;
}
async function nativeIndex() { if (!native) native = (await load('artist-network/catalog.json')).artists; return native; }
async function artistDetail(id) {
  const prefix = id.slice(0, 2);
  if (!detailCache.has(prefix)) detailCache.set(prefix, await load(`atlas/artists/${prefix}.json`));
  return detailCache.get(prefix)[id];
}
function names(rows, kind = 'artist') {
  const list = make('ul'); list.className = 'names';
  for (const row of rows) { const item = make('li'); item.append(link(row.name, kind === 'connection' ? networkURL(row.id) : route(kind, row.id))); list.append(item); }
  main.append(list);
}
function pages(page, count, href) {
  if (count <= 60) return;
  const nav = make('nav'); nav.className = 'pagination'; nav.setAttribute('aria-label', 'Pages');
  if (page > 0) nav.append(link('Previous', href(page - 1)));
  nav.append(make('span', `${page + 1} / ${Math.ceil(count / 60)}`));
  if ((page + 1) * 60 < count) nav.append(link('Next', href(page + 1)));
  main.append(nav);
}
function ordered(rows) { return [...rows].sort((a, b) => norm(a.name).localeCompare(norm(b.name)) || a.id.localeCompare(b.id)); }
function paged(rows, page, href, kind = 'artist') {
  if (!Number.isInteger(page) || page < 0 || page >= Math.max(1, Math.ceil(rows.length / 60))) { main.append(make('p', 'Page not found.')); return; }
  pages(page, rows.length, href); names(rows.slice(page * 60, (page + 1) * 60), kind); pages(page, rows.length, href);
}

export function placeLabels(labels, width, height) {
  const cells = new Map(), result = [];
  const keys = box => { const out = []; for (let y = Math.floor(box.y / 64); y <= Math.floor((box.y + box.h) / 64); y++) for (let x = Math.floor(box.x / 64); x <= Math.floor((box.x + box.w) / 64); x++) out.push(`${x},${y}`); return out; };
  const blocked = box => keys(box).some(key => (cells.get(key) || []).some(p => box.x < p.x + p.w && box.x + box.w > p.x && box.y < p.y + p.h && box.y + box.h > p.y));
  for (const label of labels) {
    const w = Math.max(44, label.width + 14), h = 48;
    let chosen;
    if (w > width - 16) { result.push(null); continue; }
    const clamp = (x, y) => ({x: Math.max(8, Math.min(width - w - 8, x)), y: Math.max(8, Math.min(height - h - 8, y)), w, h});
    for (let step = 0; step < 1800; step++) {
      const angle = step * 2.3999632297, radius = 13 * Math.sqrt(step);
      const candidate = clamp(label.x + Math.cos(angle) * radius, label.y + Math.sin(angle) * radius);
      if (!blocked(candidate)) { chosen = candidate; break; }
    }
    if (!chosen) for (let y = 8; y < height - h - 8 && !chosen; y += 48) for (let x = 8; x < width - w - 8; x += 30) { const candidate = {x, y, w, h}; if (!blocked(candidate)) { chosen = candidate; break; } }
    if (chosen) for (const key of keys(chosen)) { if (!cells.has(key)) cells.set(key, []); cells.get(key).push(chosen); }
    result.push(chosen || null);
  }
  return result;
}
async function map(rows, kind = 'artist', full = false) {
  const generation = sequence;
  await document.fonts.ready;
  if (generation !== sequence) return {placed: 0, unplaced: 0};
  const width = full ? 1800 : 1200, height = full ? Math.max(900, Math.ceil(rows.length * 11000 / width)) : 780;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('role', 'group');
  const title = document.createElementNS(ns, 'title'); title.textContent = kind === 'genre' ? 'Genres' : 'Artists'; svg.append(title);
  const anchors = [];
  for (const row of rows) {
    const a = document.createElementNS(ns, 'a'); a.setAttribute('href', route(kind, row.id)); a.setAttribute('aria-label', row.name);
    const rect = document.createElementNS(ns, 'rect'); rect.setAttribute('aria-hidden', 'true');
    const text = document.createElementNS(ns, 'text'); text.setAttribute('font-size', '16'); text.textContent = row.name;
    a.append(rect, text); svg.append(a); anchors.push({a, rect, text, row});
  }
  const shell = make('div'); shell.className = 'map-shell'; shell.tabIndex = 0; shell.setAttribute('role', 'region'); shell.setAttribute('aria-label', kind === 'genre' ? 'Genre map' : 'Artist map'); shell.append(svg);
  const controls = make('div'); controls.className = 'map-controls'; let zoom = 1;
  for (const [name, label, step] of [['Zoom out', '−', -.2], ['Zoom in', '+', .2], ['Reset map', 'Reset', 0]]) {
    const button = make('button', label); button.type = 'button'; button.setAttribute('aria-label', name);
    button.addEventListener('click', () => { zoom = step ? Math.max(1, Math.min(2.4, zoom + step)) : 1; svg.style.width = `${width * zoom}px`; if (!step) shell.scrollTo(0, 0); }); controls.append(button);
  }
  svg.style.width = `${width}px`; main.append(controls, shell);
  const layout = placeLabels(anchors.map(({row, text}, i) => ({width: text.getComputedTextLength(), x: (row.x ?? ((i * .61803398875) % 1)) * (width - 200), y: (row.y ?? ((i * .41421356237) % 1)) * (height - 60)})), width, height);
  const unplaced = [];
  anchors.forEach(({a, rect, text, row}, i) => {
    const p = layout[i]; if (!p) { a.remove(); unplaced.push(row); return; }
    text.setAttribute('x', p.x + 7); text.setAttribute('y', p.y + 27);
    rect.setAttribute('x', p.x); rect.setAttribute('y', p.y); rect.setAttribute('width', p.w); rect.setAttribute('height', '44');
  });
  if (unplaced.length) { main.append(make('h2', 'More')); names(unplaced, kind); }
  return {placed: anchors.length - unplaced.length, unplaced: unplaced.length};
}
function choices(kind, id, view, count) {
  const nav = make('nav'); nav.className = 'view-links';
  for (const name of ['Map', 'List']) { const key = name.toLowerCase(), a = link(name, route(kind, id, key)); if (view === key) a.setAttribute('aria-current', 'page'); nav.append(a); }
  main.append(nav); const scope = make('p', `${count.toLocaleString()} artists`); scope.className = 'scope'; main.append(scope); return scope;
}
function entitySource(uri) {
  const p = make('p'); p.dataset.entitySource = '';
  p.append(link('Source entity', uri)); document.querySelector('#sources').prepend(p);
}
async function render() {
  const current = ++sequence;
  try {
    main.setAttribute('aria-busy', 'true'); main.replaceChildren();
    document.querySelectorAll('[data-entity-source]').forEach(p => p.remove());
    const [kind = '', encoded = '', mode = '', pageValue = '0'] = location.hash.slice(1).split('/');
    const value = decodeURIComponent(encoded);
    if (kind === 'artist' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value)) { location.href = networkURL(value); return; }
    for (const a of document.querySelectorAll('[data-view]')) { if ((kind === '' || kind === 'genre' || kind === 'genres') && a.dataset.view === 'genres' || kind === 'artists' && a.dataset.view === 'artists') a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); }
    if (kind === 'q') {
      input.value = value; const terms = norm(value).split(/\s+/).filter(Boolean);
      if (!terms.length) { main.append(make('h1', 'Search'), make('p', 'Enter a genre or artist.')); }
      else {
        const [allArtists, connections] = await Promise.all([artistIndex(), nativeIndex()]); if (current !== sequence) return;
        const matches = row => terms.every(t => norm(row.name).includes(t));
        const styles = genres.filter(matches), rows = ordered(allArtists.filter(matches)), linked = ordered(connections.filter(matches));
        main.append(make('h1', value));
        if (styles.length) { main.append(make('h2', 'Genres')); names(ordered(styles), 'genre'); }
        if (rows.length) { main.append(make('h2', 'Artists')); const scope = make('p', `${rows.length.toLocaleString()} matches`); scope.className = 'scope'; main.append(scope); paged(rows, Number(mode || 0), p => `#q/${encodeURIComponent(value)}/${p}`); }
        else if (!styles.length && !linked.length) main.append(make('p', 'No matches.'));
        if (linked.length) { main.append(make('h2', 'Connections')); names(linked.slice(0, 60), 'connection'); if (linked.length > 60) main.append(link('All connections', `artist-network/${offline ? 'OpenNoiseArtists.html' : ''}#browse/${encodeURIComponent(value)}/0`)); }
      }
    } else if (kind === 'artists') {
      const rows = ordered(await artistIndex()); if (current !== sequence) return;
      main.append(make('h1', 'Artists')); const scope = make('p', `${rows.length.toLocaleString()} artists`); scope.className = 'scope'; main.append(scope);
      paged(rows, Number(value || 0), p => `#artists/${p}`);
    } else if (kind === 'genre') {
      const genre = byGenre.get(value);
      if (!genre) { location.href = `${offline ? 'OpenNoiseRetained.html' : 'retained.html'}#genre/${encodeURIComponent(value)}`; return; }
      const data = await load(`atlas/genres/${value}.json`); const all = await artistIndex(); if (current !== sequence) return;
      entitySource(genre.uri);
      const rows = ordered(data.artists.map(id => byArtist.get(id))); const view = mode || (matchMedia('(max-width:800px)').matches ? 'list' : 'map');
      main.append(make('h1', genre.name)); const scope = choices('genre', value, view, rows.length);
      if (view === 'list') paged(rows, Number(pageValue), p => route('genre', value, 'list', p));
      else { const shown = data.map.map(id => byArtist.get(id)); scope.textContent = `${shown.length} of ${rows.length.toLocaleString()} artists`; await map(shown); }
    } else if (kind === 'artist') {
      const row = await artistDetail(value); await artistIndex(); if (current !== sequence) return;
      if (!row) { main.append(make('h1', 'Artist not found')); }
      else {
        main.append(make('h1', row.name));
        entitySource(row.uri);
        if (row.genres.length) { main.append(make('h2', 'Genres')); names(ordered(row.genres.map(id => byGenre.get(id))), 'genre'); }
        const rows = ordered(row.related.map(id => byArtist.get(id)));
        if (rows.length) { main.append(make('h2', 'Related artists')); const view = mode || (matchMedia('(max-width:800px)').matches ? 'list' : 'map'); const scope = choices('artist', value, view, rows.length); if (view === 'list') paged(rows, Number(pageValue), p => route('artist', value, 'list', p)); else { scope.textContent = `${row.map.length} of ${rows.length.toLocaleString()} artists`; await map(row.map.map(id => byArtist.get(id))); } }
        if (row.suggested?.length) { main.append(make('h2', 'Suggested')); names(row.suggested.map(id => byArtist.get(id))); }
        if (row.native_id) main.append(link('Connections', networkURL(row.native_id)));
      }
    } else {
      main.append(make('h1', 'Genres')); const nav = make('nav'); nav.className = 'view-links'; const view = kind === 'genres' && value === 'list' ? 'list' : 'map';
      for (const [name, key] of [['Map', 'map'], ['List', 'list']]) { const a = link(name, key === 'map' ? '#' : '#genres/list'); if (view === key) a.setAttribute('aria-current', 'page'); nav.append(a); } main.append(nav);
      const scope = make('p', `${genres.length.toLocaleString()} genres`); scope.className = 'scope'; main.append(scope);
      if (view === 'list') names(ordered(genres), 'genre'); else await map(genres, 'genre', true);
    }
    if (current !== sequence) return;
    main.setAttribute('aria-busy', 'false'); document.title = `${main.querySelector('h1')?.textContent || 'Music'} · OpenNoise`;
  } catch (error) { if (current === sequence) { main.replaceChildren(make('h1', 'Music unavailable'), make('p', 'Reload the complete static export.')); main.setAttribute('aria-busy', 'false'); console.error(error); } }
}
document.querySelector('form').addEventListener('submit', e => { e.preventDefault(); const next = `#q/${encodeURIComponent(input.value.trim())}/0`; if (location.hash === next) render(); else location.hash = next; });
window.addEventListener('hashchange', () => { render(); main.focus({preventScroll: true}); });
document.querySelector('.skip').addEventListener('click', e => { e.preventDefault(); main.focus(); });
try {
  if (globalThis.OPENNOISE_ATLAS_GZIP) {
    const bytes = Uint8Array.from(atob(globalThis.OPENNOISE_ATLAS_GZIP), c => c.charCodeAt(0));
    const packed = JSON.parse(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text());
    const expand = value => {
      if (typeof value === 'string') return value.startsWith('~~') ? value.slice(1) : value.startsWith('~') ? packed.ids[parseInt(value.slice(1), 16)] : value;
      if (Array.isArray(value)) return value.map(expand);
      if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [expand(k), expand(v)]));
      return value;
    };
    bundled = expand(packed.files);
  }
  genres = await load('atlas/genres.json'); byGenre = new Map(genres.map(g => [g.id, g]));
  const receipt = await load('atlas/receipt.json'); const sources = document.querySelector('#sources');
  const logoLink = link('', 'https://databus.dbpedia.org/dbpedia'), logo = make('img'); logo.src = receipt.logo_data; logo.alt = 'DBpedia'; logoLink.append(logo); sources.append(logoLink);
  sources.append(make('p', `DBpedia ${receipt.source_version}, extracted from English Wikipedia. ${receipt.counts.artists.toLocaleString()} named artists have genre or relationship evidence; ${receipt.counts.genre_artists.toLocaleString()} have genre claims. Source associations and band memberships appear as Related artists. Suggested artists share graph context. Map positions have no musical axes. Recommendation relevance has not been independently judged.`));
  const credit = make('p'); credit.append(link('DBpedia', 'https://databus.dbpedia.org/dbpedia'), make('span', ' · '), link('CC BY 3.0 source', 'https://creativecommons.org/licenses/by/3.0/'), make('span', ' · '), link('CC BY-SA 3.0 derived data', 'https://creativecommons.org/licenses/by-sa/3.0/')); sources.append(credit);
  sources.append(make('p', 'The data was filtered to music records and reformatted. Genre names are checked against MusicBrainz core genre definitions (CC0); exact name aliases are grouped. Entity pages link to their sources. Connections uses the separate CC0 ListenBrainz/MusicBrainz catalog. Artist identities are kept separate across sources.'));
  const old = make('p'); old.append(link('Original catalog', offline ? 'OpenNoiseRetained.html' : 'retained.html'), make('span', ' · '), link('Build receipt', 'opennoise-release.json')); sources.append(old);
  document.querySelector('#connections').href = networkURL(); await render();
} catch (error) { main.replaceChildren(make('h1', 'Music unavailable'), make('p', 'Reload the complete static export.')); console.error(error); }
