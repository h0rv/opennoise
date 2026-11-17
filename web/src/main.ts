import { Catalog } from './data';
import { GenreTree } from './genre-tree';
import { MapCanvas } from './map-canvas';
import type { Genre, GenreDetail, ArtistDetail, SearchEntry } from './catalog';
import './style.css';

type View = 'axes' | 'islands' | 'tree';
type Selection = Pick<SearchEntry, 'kind' | 'id'>;
const app = document.querySelector<HTMLElement>('#app')!;
const escape = (value: unknown) =>
  String(value).replace(
    /[&<>"']/g,
    (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!,
  );
const count = (value: number | null, noun = 'artist') =>
  value === null
    ? 'Count unavailable'
    : `${value.toLocaleString()} ${noun}${value === 1 ? '' : 's'}`;
const modes: Record<View, { label: string }> = {
  axes: {
    label: 'Sonic map',
  },
  islands: {
    label: 'Islands',
  },
  tree: {
    label: 'Genre tree',
  },
};

async function start() {
  const catalog = await new Catalog().load();
  const genres = new Map(catalog.genres.map((genre) => [genre.id, genre]));
  const lookup = new Map(catalog.search.map((entry) => [`${entry.kind}:${entry.id}`, entry]));
  let searchIndex = catalog.search.map((entry) => ({
    entry,
    terms: [entry.name, ...entry.aliases].map((name) => name.toLocaleLowerCase()),
  }));
  let indexedSearch = catalog.search;
  let view: View = catalog.manifest.layouts.axes
    ? 'axes'
    : catalog.manifest.layouts.islands
      ? 'islands'
      : 'tree';
  let selected: Selection | null = null;
  let detail: GenreDetail | ArtistDetail | null = null;
  let controller = new AbortController();
  let map: MapCanvas | undefined;
  const cameras = new Map<View, { scale: number; x: number; y: number }>();
  let trail: Selection[] = [];
  let storageAvailable = true;
  const storageKey = `opennoise:trail:${catalog.manifest.release_id}`;
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(storageKey) || '[]');
    if (Array.isArray(saved))
      trail = saved
        .filter(
          (entry): entry is Selection =>
            !!entry &&
            typeof entry === 'object' &&
            'kind' in entry &&
            'id' in entry &&
            (lookup.has(`${entry.kind}:${entry.id}`) ||
              (entry.kind === 'artist' && /^[a-f0-9-]{36}$/.test(String(entry.id)))),
        )
        .slice(0, 50);
  } catch {
    storageAvailable = false;
  }

  app.innerHTML = `
    <div class="toolbar" id="explore"><div class="search-wrap"><input id="search" type="search" aria-label="Search genres and artists" placeholder="Search genres and artists" aria-controls="results" autocomplete="off"><div id="results" class="search-results" aria-label="Search results"></div></div>
      <nav class="modes" aria-label="Atlas view">${Object.entries(modes)
        .map(
          ([key, mode]) =>
            `<button data-view="${key}" ${key !== 'tree' && !catalog.manifest.layouts[key as 'axes' | 'islands'] ? 'disabled title="This layout has not been published"' : ''}>${mode.label}</button>`,
        )
        .join('')}</nav>
      <button id="trail-toggle" aria-expanded="false" aria-controls="trail">Saved (<span id="trail-count">${trail.length}</span>)</button></div>
    <section class="workspace" aria-label="Genre atlas"><div class="canvas" id="canvas"></div><aside id="detail" tabindex="-1" aria-label="Selected genre or artist" aria-live="polite"></aside></section>
    <section class="trail" id="trail" aria-label="Saved discovery trail" hidden></section>
    <p id="status" role="status"></p>`;
  app.removeAttribute('aria-busy');
  const canvas = document.querySelector<HTMLElement>('#canvas')!;
  const drawer = document.querySelector<HTMLElement>('#detail')!;
  const search = document.querySelector<HTMLInputElement>('#search')!;
  const results = document.querySelector<HTMLElement>('#results')!;
  const trailPanel = document.querySelector<HTMLElement>('#trail')!;
  const status = document.querySelector<HTMLElement>('#status')!;
  const hierarchy = new GenreTree(
    catalog.genres,
    (selection) => void select(selection, true, false),
  );

  function entityButton(
    kind: Selection['kind'],
    id: string,
    name: string,
    rank?: number,
    color?: string | null,
  ) {
    return `<button class="entity-row" data-kind="${kind}" data-id="${escape(id)}" aria-pressed="${selected?.kind === kind && selected.id === id}">${rank === undefined ? '' : `<span class="number">${String(rank).padStart(2, '0')}</span>`}<span class="dot" style="background:${escape(color || '#111111')}"></span><span>${escape(name)}</span></button>`;
  }

  function updateMapSelection(reveal = false) {
    if (!map) return;
    const artist = detail && 'artist' in detail ? detail.artist : null;
    const point = artist?.positions[map.layout];
    map.selection(
      selected?.id || '',
      artist && point ? { id: artist.id, name: artist.name, ...point } : undefined,
      reveal,
    );
  }

  function renderCanvas(reveal = false) {
    document
      .querySelectorAll<HTMLButtonElement>('[data-view]')
      .forEach((button) =>
        button.setAttribute('aria-pressed', String(button.dataset.view === view)),
      );
    if (view !== 'tree' && map?.layout === view) {
      updateMapSelection(reveal);
      return;
    }
    if (map) {
      cameras.set(map.layout, { ...map.camera });
      map.destroy();
      map = undefined;
    }
    if (view === 'tree') {
      hierarchy.show(canvas, selected, detail);
      return;
    }
    hierarchy.hide();
    const axes = catalog.manifest.layouts.axes;
    canvas.innerHTML = `<div class="map-viewport" id="map-viewport"><canvas id="map-content" data-layout="${view}" tabindex="0" role="img" aria-label="${modes[view].label}. Arrow keys pan, plus and minus zoom. Page Down and Page Up browse visible labels; Enter opens. Search or tree reaches every genre."></canvas></div>
      ${view === 'axes' && axes ? `<div class="axis-legend"><span>Left → right: ${escape(axes.x_min)} → ${escape(axes.x_max)}</span><span>Up → down: ${escape(axes.y_min)} → ${escape(axes.y_max)}</span></div>` : ''}
      <div class="map-bottom"><span>${catalog.manifest.data_kind === 'model' ? 'Suggested map. ' : ''}<span id="placement-status"></span></span><div class="zoom" aria-label="Map controls"><button data-zoom="out" aria-label="Zoom out">−</button><button data-zoom="in" aria-label="Zoom in">+</button><button data-zoom="reset">Reset</button></div></div>`;
    map = new MapCanvas(
      canvas.querySelector<HTMLCanvasElement>('canvas')!,
      catalog.genres,
      view,
      (kind, id) => void select({ kind, id }),
      canvas.querySelector('#placement-status')!,
      cameras.get(view),
    );
    updateMapSelection(reveal);
  }

  function zoomMap(factor: number) {
    map?.zoom(factor);
  }
  function resetMap() {
    map?.reset();
  }

  function breadcrumbs(genre: Genre) {
    const chain: Genre[] = [];
    const seen = new Set([genre.id]);
    while (genre.parent_id && genres.has(genre.parent_id) && !seen.has(genre.parent_id)) {
      genre = genres.get(genre.parent_id)!;
      seen.add(genre.id);
      chain.unshift(genre);
    }
    return `<div class="breadcrumbs">Genres ${chain.map((parent) => ` / <button data-kind="genre" data-id="${escape(parent.id)}">${escape(parent.name)}</button>`).join('')}</div>`;
  }

  function renderDetail() {
    if (!selected) {
      drawer.innerHTML = `<h2>Genres</h2>${catalog.genres
        .filter((genre) => !genre.parent_id)
        .sort((a, b) => (b.member_count || 0) - (a.member_count || 0))
        .slice(0, 30)
        .map((genre) => entityButton('genre', genre.id, genre.name, undefined, genre.color))
        .join(
          '',
        )}<p class="muted">Search or open the genre tree for all ${catalog.genres.length.toLocaleString()} genres.</p>`;
      return;
    }
    if (!detail) return;
    const entity = 'genre' in detail ? detail.genre : detail.artist;
    const saved = trail.some((entry) => entry.kind === selected!.kind && entry.id === selected!.id);
    drawer.innerHTML = `${'genre' in detail ? breadcrumbs(detail.genre) : '<p class="muted">Artist</p>'}<h2>${escape(entity.name)}</h2><p class="detail-lede">${'genre' in detail ? count(detail.genre.member_count) : detail.artist.listeners === null ? 'Listener count unavailable' : count(detail.artist.listeners, 'listener')}</p><button id="save" ${saved || trail.length >= 50 ? 'disabled' : ''}>${saved ? 'Saved' : trail.length >= 50 ? 'Saved items full (50)' : 'Save to trail'}</button>${'genre' in detail ? renderGenre(detail) : renderArtist(detail)}`;
  }

  function renderGenre(data: GenreDetail) {
    return `<section><h3>${catalog.manifest.data_kind === 'model' ? 'Suggested members' : 'Member artists'}</h3>${
      data.members === null
        ? '<p class="empty">Membership has not been computed yet.</p>'
        : !data.members.length
          ? '<p class="empty">No artists in this published membership.</p>'
          : data.members
              .slice(0, 8)
              .map((member, index) =>
                entityButton(
                  'artist',
                  member.artist.id,
                  member.artist.name,
                  index + 1,
                  member.artist.color,
                ),
              )
              .join('')
    }</section><section><h3>Related genres</h3>${
      data.related === null
        ? '<p class="empty">Genre similarity has not been computed yet.</p>'
        : !data.related.length
          ? '<p class="empty">No related genres in this release.</p>'
          : data.related
              .slice(0, 6)
              .map((entry, index) =>
                entityButton(
                  'genre',
                  entry.id,
                  genres.get(entry.id)?.name || entry.id,
                  index + 1,
                  genres.get(entry.id)?.color,
                ),
              )
              .join('')
    }</section>`;
  }

  function renderArtist(data: ArtistDetail) {
    const links = data.links.filter((link) => /^https?:\/\//i.test(link.url));
    return `<section><h3>${catalog.manifest.data_kind === 'model' ? 'Suggested genres' : 'Genres'}</h3>${
      data.genres === null
        ? '<p class="empty">Membership has not been computed yet.</p>'
        : !data.genres.length
          ? '<p class="empty">No genre memberships in this release.</p>'
          : data.genres
              .slice(0, 8)
              .map((entry, index) =>
                entityButton(
                  'genre',
                  entry.id,
                  genres.get(entry.id)?.name || entry.id,
                  index + 1,
                  genres.get(entry.id)?.color,
                ),
              )
              .join('')
    }</section><section><h3>${catalog.manifest.data_kind === 'model' ? 'Suggested similar artists' : 'Similar artists'}</h3>${
      data.similar === null
        ? '<p class="empty">Artist similarity has not been computed yet.</p>'
        : !data.similar.length
          ? '<p class="empty">No similar artists in this release.</p>'
          : data.similar
              .slice(0, 8)
              .map((entry, index) =>
                entityButton(
                  'artist',
                  entry.artist.id,
                  entry.artist.name,
                  index + 1,
                  entry.artist.color,
                ),
              )
              .join('')
    }</section><section><h3>Listening links</h3>${links.length ? `<div class="links">${links.map((link) => `<a href="${escape(link.url)}" target="_blank" rel="noopener noreferrer">${escape(link.label)} ↗</a>`).join('')}</div>` : '<p class="empty">No listening links available.</p>'}<p class="muted">${data.preview ? 'Preview playback is not connected.' : 'No preview available.'}</p></section>`;
  }

  function renderTrail() {
    document.querySelector('#trail-count')!.textContent = String(trail.length);
    trailPanel.innerHTML = `<div class="trail-header"><div><h2>Saved trail</h2><p>${storageAvailable ? 'Saved in this browser only.' : 'Browser storage unavailable; this trail lasts for this tab only.'} Maximum 50 items.</p></div><button id="trail-close">Close</button></div><div class="trail-items">${trail.length ? trail.map((entry, index) => `<div class="trail-item"><button data-kind="${entry.kind}" data-id="${escape(entry.id)}">${String(index + 1).padStart(2, '0')} · ${escape(lookup.get(`${entry.kind}:${entry.id}`)?.name || entry.id)}</button><button data-remove="${index}" aria-label="Remove ${escape(lookup.get(`${entry.kind}:${entry.id}`)?.name || entry.id)} from trail">×</button></div>`).join('') : '<p class="empty">No saved genres or artists.</p>'}</div>`;
  }

  function persistTrail() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(trail));
    } catch {
      storageAvailable = false;
    }
    renderTrail();
    renderDetail();
  }

  function writeURL() {
    status.textContent = '';
    const params = new URLSearchParams({ view });
    if (selected) {
      params.set('kind', selected.kind);
      params.set('id', selected.id);
    }
    const hash = `#${params}`;
    if (location.hash !== hash) history.pushState(null, '', hash);
  }

  async function select(selection: Selection, push = true, focusDetails = true) {
    controller.abort();
    controller = new AbortController();
    selected = selection;
    detail = null;
    if (push) writeURL();
    drawer.innerHTML = '<p class="empty" role="status">Loading details…</p>';
    renderCanvas(true);
    results.innerHTML = '';
    try {
      const loaded =
        selection.kind === 'genre'
          ? await catalog.genre(selection.id, controller.signal)
          : await catalog.artist(selection.id, controller.signal);
      if (selected !== selection) return;
      detail = loaded;
      if ('artist' in loaded) {
        lookup.set(`artist:${loaded.artist.id}`, {
          kind: 'artist',
          id: loaded.artist.id,
          name: loaded.artist.name,
          aliases: [],
        });
        renderTrail();
      }
      renderDetail();
      renderCanvas(true);
      if (focusDetails) drawer.focus({ preventScroll: true });
    } catch (error) {
      if (selected !== selection || (error instanceof DOMException && error.name === 'AbortError'))
        return;
      drawer.innerHTML = `<h2>Details unavailable</h2><p class="error">${escape(error instanceof Error ? error.message : 'Unable to load details.')}</p><button id="retry">Try again</button>`;
    }
  }

  function restoreURL() {
    status.textContent = '';
    const params = new URLSearchParams(location.hash.slice(1));
    const requestedView = params.get('view');
    if (
      requestedView === 'tree' ||
      ((requestedView === 'axes' || requestedView === 'islands') &&
        catalog.manifest.layouts[requestedView])
    )
      view = requestedView;
    const kind = params.get('kind'),
      id = params.get('id');
    if (
      (kind === 'genre' || kind === 'artist') &&
      id &&
      (lookup.has(`${kind}:${id}`) || (kind === 'artist' && /^[a-f0-9-]{36}$/.test(id)))
    )
      void select({ kind, id }, false);
    else {
      controller.abort();
      selected = null;
      detail = null;
      renderCanvas();
      renderDetail();
      if (id)
        status.textContent =
          'This selection is not in the current release. Search for another genre or artist.';
    }
  }

  async function loadSearchIndex() {
    const entries = await catalog.loadSearch();
    if (entries === indexedSearch) return;
    searchIndex = entries.map((entry) => ({
      entry,
      terms: [entry.name, ...entry.aliases].map((name) => name.toLocaleLowerCase()),
    }));
    for (const entry of entries) lookup.set(`${entry.kind}:${entry.id}`, entry);
    indexedSearch = entries;
    renderTrail();
  }

  search.addEventListener('input', async () => {
    const query = search.value.trim().toLocaleLowerCase();
    if (!query) {
      results.innerHTML = '';
      return;
    }
    results.innerHTML = '<p role="status">Searching…</p>';
    try {
      await loadSearchIndex();
    } catch {
      if (search.value.trim().toLocaleLowerCase() === query)
        results.innerHTML =
          '<p role="status">Search unavailable. Type again to retry; the genre tree remains available.</p>';
      return;
    }
    if (search.value.trim().toLocaleLowerCase() !== query) return;
    const matches: SearchEntry[] = [];
    for (const { entry, terms } of searchIndex) {
      if (!terms.some((term) => term.includes(query))) continue;
      matches.push(entry);
      if (matches.length === 12) break;
    }
    results.innerHTML = matches.length
      ? matches
          .map(
            (entry) =>
              `<button data-kind="${entry.kind}" data-id="${escape(entry.id)}">${escape(entry.name)}<span>${entry.kind}</span></button>`,
          )
          .join('')
      : '<p role="status">No matches in this release. Try another name.</p>';
  });
  search.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      results.querySelector<HTMLButtonElement>('button')?.focus();
    }
    if (event.key === 'Enter') results.querySelector<HTMLButtonElement>('button')?.click();
  });
  app.addEventListener('click', (event) => {
    const target = (event.target as Element).closest<HTMLElement>(
      '[data-kind], [data-view], [data-zoom], [data-remove], button[id]',
    );
    if (!target) return;
    if (target.dataset.kind && target.dataset.id) {
      void select({ kind: target.dataset.kind as Selection['kind'], id: target.dataset.id });
      return;
    }
    if (target.dataset.view) {
      view = target.dataset.view as View;
      writeURL();
      renderCanvas();
      return;
    }
    if (target.dataset.zoom === 'in') zoomMap(1.35);
    if (target.dataset.zoom === 'out') zoomMap(1 / 1.35);
    if (target.dataset.zoom === 'reset') resetMap();
    if (target.dataset.remove !== undefined) {
      trail.splice(Number(target.dataset.remove), 1);
      persistTrail();
    }
    if (target.id === 'save' && selected) {
      trail.push({ ...selected });
      persistTrail();
      status.textContent = 'Added to your trail.';
    }
    if (target.id === 'retry' && selected) void select(selected, false);
    if (target.id === 'trail-toggle' || target.id === 'trail-close') {
      trailPanel.hidden = target.id === 'trail-close' || !trailPanel.hidden;
      document
        .querySelector('#trail-toggle')!
        .setAttribute('aria-expanded', String(!trailPanel.hidden));
      if (!trailPanel.hidden) {
        trailPanel.scrollIntoView({ block: 'nearest' });
        if (trail.some((entry) => !lookup.has(`${entry.kind}:${entry.id}`)))
          void loadSearchIndex().catch(() => {
            if (!trailPanel.hidden)
              status.textContent = 'Saved names unavailable. Close and reopen Saved to retry.';
          });
      }
    }
  });
  app.addEventListener('keydown', (event) => {
    if (
      (event.target as Element).matches('.genre') &&
      (event.key === 'Enter' || event.key === ' ')
    ) {
      event.preventDefault();
      (event.target as HTMLElement).dispatchEvent(new MouseEvent('click', { bubbles: true }));
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === '/' && !(event.target instanceof HTMLInputElement)) {
      event.preventDefault();
      search.focus();
    }
    if (event.key === 'Escape') {
      results.innerHTML = '';
      search.focus();
    }
  });
  document.addEventListener('click', (event) => {
    if (!(event.target as Element).closest('.search-wrap')) results.innerHTML = '';
  });
  window.addEventListener('popstate', restoreURL);
  window.addEventListener('resize', () => {
    if (view === 'tree') hierarchy.resize();
  });
  renderTrail();
  restoreURL();
}

start().catch((error) => {
  app.removeAttribute('aria-busy');
  app.innerHTML = `<h1 class="loading">The atlas could not be opened.</h1><p class="error">${escape(error instanceof Error ? error.message : 'Unknown catalog error')}</p><p class="muted">Check the catalog URL and schema version, then reload. No fallback dataset has been substituted.</p><button onclick="location.reload()">Reload atlas</button>`;
});
