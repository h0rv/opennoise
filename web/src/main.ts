import { Catalog } from './data';
import { artistGraph, artistNeighbors } from './artist-graph';
import { MapCanvas } from './map-canvas';
import { SonicMap } from './sonic-map';
import { searchableEntry, searchMatches } from './search';
import { PreviewPlayer } from './preview';
import type { Genre, GenreDetail, ArtistDetail, SearchEntry } from './catalog';
import './style.css';

type View = 'axes' | 'islands' | 'artists';
type Selection = Pick<SearchEntry, 'kind' | 'id'>;
const app = document.querySelector<HTMLElement>('#app')!;
const escape = (value: unknown) =>
  String(value).replace(
    /[&<>"']/g,
    (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!,
  );
const modes: Record<View, { label: string }> = {
  axes: {
    label: 'Map',
  },
  islands: {
    label: 'Islands',
  },
  artists: {
    label: 'Artists',
  },
};

async function start() {
  const catalog = await new Catalog().load();
  const genres = new Map(catalog.genres.map((genre) => [genre.id, genre]));
  const lookup = new Map(catalog.search.map((entry) => [`${entry.kind}:${entry.id}`, entry]));
  let searchIndex = catalog.search.filter(searchableEntry).map((entry) => ({
    entry,
    topLevel: entry.kind === 'genre' && genres.get(entry.id)?.parent_id === null,
    terms: [entry.name, ...entry.aliases].map((name) => name.toLocaleLowerCase()),
  }));
  let indexedSearch = catalog.search;
  let view: View = catalog.manifest.layouts.axes ? 'axes' : 'islands';
  let selected: Selection | null = null;
  let detail: GenreDetail | ArtistDetail | null = null;
  let artistPath: { id: string; name: string }[] = [];
  let detailError = '';
  let controller = new AbortController();
  let graphController = new AbortController();
  let map: MapCanvas | SonicMap | undefined;
  const cameras = new Map<View, { scale: number; x: number; y: number }>();
  let mapScrollY = 0;
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
    <header class="toolbar" id="explore"><h1><a href="#" class="brand" aria-label="OpenNoise home">OpenNoise</a></h1><div class="search-wrap"><input id="search" type="search" aria-label="Search genres and artists" placeholder="Search" aria-controls="results" autocomplete="off"><div id="results" class="search-results" aria-label="Search results"></div></div>
      <div class="toolbar-actions"><nav class="modes" aria-label="Atlas view">${Object.entries(
        modes,
      )
        .map(
          ([key, mode]) =>
            `<button data-view="${key}" ${(key === 'axes' || key === 'islands') && !catalog.manifest.layouts[key] ? 'disabled title="This layout has not been published"' : ''}>${mode.label}</button>`,
        )
        .join('')}</nav>
      <button data-zoom="reset">Reset</button><button id="trail-toggle" aria-expanded="false" aria-controls="trail">Saved</button></div><a class="source" href="./about.html">About</a><a class="source repo-link" href="https://github.com/h0rv/opennoise">Source ↗</a></header>
    <section class="workspace" aria-label="Genre atlas"><div class="canvas" id="canvas"></div>
    <aside id="sidebar" hidden aria-label="Selected genre or artist"><button id="detail-close" aria-label="Close details">×</button><div id="preview" hidden></div><div id="detail" tabindex="-1" aria-live="polite"></div></aside></section>
    <section class="trail" id="trail" aria-label="Saved genres and artists" hidden></section>
    <p id="status" role="status"></p>`;
  app.removeAttribute('aria-busy');
  const canvas = document.querySelector<HTMLElement>('#canvas')!;
  const drawer = document.querySelector<HTMLElement>('#detail')!;
  const sidebar = document.querySelector<HTMLElement>('#sidebar')!;
  const search = document.querySelector<HTMLInputElement>('#search')!;
  const results = document.querySelector<HTMLElement>('#results')!;
  const trailPanel = document.querySelector<HTMLElement>('#trail')!;
  const status = document.querySelector<HTMLElement>('#status')!;
  const previewHost = document.querySelector<HTMLElement>('#preview')!;
  const preview = new PreviewPlayer(previewHost);

  function entityButton(kind: Selection['kind'], id: string, name: string, color?: string | null) {
    return `<button class="entity-row" data-kind="${kind}" data-id="${escape(id)}" aria-pressed="${selected?.kind === kind && selected.id === id}"><span class="dot" style="background:${escape(color || '#111111')}"></span><span>${escape(name)}</span></button>`;
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
    if (map instanceof SonicMap)
      map.highlight(
        detail && 'artist' in detail
          ? (detail.genres ?? []).map((genre) => catalog.genreId(genre.id))
          : [],
      );
  }

  function renderCanvas(reveal = false) {
    graphController.abort();
    document.querySelector<HTMLButtonElement>('.toolbar [data-zoom="reset"]')!.hidden =
      view !== 'islands';
    document
      .querySelectorAll<HTMLButtonElement>('[data-view]')
      .forEach((button) =>
        button.setAttribute('aria-pressed', String(button.dataset.view === view)),
      );
    if (view !== 'artists' && map?.layout === view) {
      updateMapSelection(reveal);
      return;
    }
    if (map) {
      if (map instanceof SonicMap) mapScrollY = window.scrollY;
      else cameras.set(map.layout, { ...map.camera });
      map.destroy();
      map = undefined;
    }
    document.body.classList.toggle('sonic-view', view === 'axes');
    canvas.classList.toggle('artist-view', view === 'artists');
    if (view === 'artists') {
      renderArtists();
      return;
    }
    if (view === 'axes') {
      canvas.replaceChildren();
      const content = document.createElement('div');
      canvas.append(content);
      map = new SonicMap(
        content,
        catalog.genres,
        (kind, id) => void select({ kind, id }, true, true),
        mapScrollY,
      );
      updateMapSelection(reveal);
      return;
    }
    canvas.innerHTML = `<div class="map-viewport" id="map-viewport"><canvas id="map-content" data-layout="${view}" tabindex="0" role="img" aria-label="${modes[view].label}. Arrow keys pan, plus and minus zoom. Page Down and Page Up browse visible labels; Enter opens. Search genres and artists."></canvas></div>`;
    map = new MapCanvas(
      canvas.querySelector<HTMLCanvasElement>('canvas')!,
      catalog.genres,
      view,
      (kind, id) => void select({ kind, id }, true, true),
      cameras.get(view),
    );
    updateMapSelection(reveal);
  }

  function resetMap() {
    if (map instanceof MapCanvas) map.reset();
  }

  function renderArtists() {
    graphController.abort();
    graphController = new AbortController();
    if (selected?.kind !== 'artist') {
      canvas.innerHTML =
        '<div class="artist-heading"><h2 class="visually-hidden">Artists</h2><p>Search for an artist to explore their connections.</p></div>';
      return;
    }
    if (!detail || !('artist' in detail)) {
      canvas.innerHTML = detailError
        ? `<div class="artist-heading"><h2>Artist unavailable</h2><p class="error">${escape(detailError)}</p><button id="retry">Try again</button></div>`
        : '<p class="artist-heading" role="status">Loading artist…</p>';
      return;
    }
    const data = detail;
    canvas.innerHTML = `<div class="artist-heading"><nav class="artist-path" aria-label="Artist hops">${artistPath.map((artist, index) => `${index ? '<span aria-hidden="true">→</span>' : ''}<button data-kind="artist" data-id="${escape(artist.id)}" ${artist.id === data.artist.id ? 'aria-current="page"' : ''}>${escape(artist.name)}</button>`).join('')}</nav><h2 class="visually-hidden" tabindex="-1">${escape(data.artist.name)}</h2></div>${data.similar?.length ? '' : '<p class="empty">No similar artists in this release. Search for another artist.</p>'}`;
    canvas.querySelector('.artist-heading')!.append(previewHost);
    const path = canvas.querySelector<HTMLElement>('.artist-path')!;
    path.scrollLeft = path.scrollWidth;
    canvas.append(
      artistGraph(data, (id, signal) => catalog.artist(id, signal), graphController.signal),
    );
  }

  function breadcrumbs(genre: Genre) {
    const chain: Genre[] = [];
    const seen = new Set([genre.id]);
    while (genre.parent_id && genres.has(genre.parent_id) && !seen.has(genre.parent_id)) {
      genre = genres.get(genre.parent_id)!;
      seen.add(genre.id);
      chain.unshift(genre);
    }
    return chain.length
      ? `<div class="breadcrumbs">${chain.map((parent) => `<button data-kind="genre" data-id="${escape(parent.id)}">${escape(parent.name)}</button>`).join(' / ')}</div>`
      : '';
  }

  function renderDetail() {
    sidebar.hidden = !selected;
    if (!selected) {
      drawer.innerHTML = '';
      return;
    }
    if (!detail) return;
    const entity = 'genre' in detail ? detail.genre : detail.artist;
    const saved = trail.some((entry) => entry.kind === selected!.kind && entry.id === selected!.id);
    drawer.innerHTML = `<h2>${escape(entity.name)}</h2>${'genre' in detail ? breadcrumbs(detail.genre) : detail.artist.disambiguation ? `<p class="about">${escape(detail.artist.disambiguation)}</p>` : ''}<button id="save" ${saved || trail.length >= 50 ? 'disabled' : ''}>${saved ? 'Saved' : trail.length >= 50 ? 'Saved items full' : 'Save'}</button>${'genre' in detail ? renderGenre(detail) : renderArtist(detail)}`;
    if (view === 'artists') canvas.querySelector('.artist-heading')?.append(previewHost);
    else drawer.querySelector('h2')!.after(previewHost);
  }

  function renderGenre(data: GenreDetail) {
    return `${
      data.members?.length
        ? `<section><h3>Artists</h3>${[...data.members]
            .sort((a, b) => (b.artist.listeners ?? 0) - (a.artist.listeners ?? 0))
            .slice(0, 8)
            .map((member) =>
              entityButton('artist', member.artist.id, member.artist.name, member.artist.color),
            )
            .join('')}</section>`
        : ''
    }${
      data.related?.length
        ? `<section><h3>Related genres</h3>${data.related
            .slice(0, 6)
            .map((entry) =>
              entityButton(
                'genre',
                entry.id,
                genres.get(entry.id)?.name || entry.id,
                genres.get(entry.id)?.color,
              ),
            )
            .join('')}</section>`
        : ''
    }`;
  }

  function renderArtist(data: ArtistDetail) {
    const links = data.links.filter((link) => /^https?:\/\//i.test(link.url));
    return `${
      data.genres?.length
        ? `<section><h3>Genres</h3>${data.genres
            .slice(0, 8)
            .map((entry) =>
              entityButton(
                'genre',
                entry.id,
                genres.get(entry.id)?.name || entry.id,
                genres.get(entry.id)?.color,
              ),
            )
            .join('')}</section>`
        : ''
    }${
      data.similar?.length
        ? `<section><h3>Similar artists</h3>${artistNeighbors(data)
            .slice(0, 8)
            .map((entry) =>
              entityButton('artist', entry.artist.id, entry.artist.name, entry.artist.color),
            )
            .join('')}</section>`
        : ''
    }${links.length ? `<section><div class="links">${links.map((link) => `<a href="${escape(link.url)}" target="_blank" rel="noopener noreferrer">${escape(link.label)} ↗</a>`).join('')}</div></section>` : ''}`;
  }

  function renderTrail() {
    trailPanel.innerHTML = `<div class="trail-header"><h2>Saved</h2><button id="trail-close" aria-label="Close saved">×</button></div>${storageAvailable ? '' : '<p class="error">Browser storage unavailable. Saved items will be lost when this tab closes.</p>'}<div class="trail-items">${trail.length ? trail.map((entry, index) => `<div class="trail-item"><button data-kind="${entry.kind}" data-id="${escape(entry.id)}">${escape(lookup.get(`${entry.kind}:${entry.id}`)?.name || entry.id)}</button><button data-remove="${index}" aria-label="Remove ${escape(lookup.get(`${entry.kind}:${entry.id}`)?.name || entry.id)} from saved">×</button></div>`).join('') : '<p class="empty">Nothing saved yet.</p>'}</div>`;
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

  function clearSelection() {
    preview.stop();
    controller.abort();
    selected = null;
    detail = null;
    renderCanvas();
    renderDetail();
  }

  async function select(selection: Selection, push = true, hear = false) {
    if (selection.kind === 'genre') selection = { ...selection, id: catalog.genreId(selection.id) };
    else
      selection = {
        ...selection,
        id: catalog.manifest.artist_redirects?.[selection.id] ?? selection.id,
      };
    preview.stop();
    controller.abort();
    controller = new AbortController();
    selected = selection;
    if (selection.kind === 'genre') artistPath = [];
    if (selection.kind === 'artist' && push) view = 'artists';
    else if (selection.kind === 'genre' && view === 'artists')
      view = catalog.manifest.layouts.axes ? 'axes' : 'islands';
    sidebar.hidden = false;
    sidebar.scrollTop = 0;
    detail = null;
    detailError = '';
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
      if (hear)
        void preview.play(
          'artist' in loaded
            ? [loaded.artist.name]
            : (loaded.members || []).map((member) => member.artist.name),
        );
      if ('artist' in loaded) {
        const index = artistPath.findIndex((artist) => artist.id === loaded.artist.id);
        artistPath =
          index < 0 ? [...artistPath, loaded.artist].slice(-8) : artistPath.slice(0, index + 1);
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
      if (view === 'artists')
        canvas.querySelector<HTMLElement>('h2')?.focus({ preventScroll: true });
    } catch (error) {
      if (selected !== selection || (error instanceof DOMException && error.name === 'AbortError'))
        return;
      drawer.innerHTML = `<h2>Details unavailable</h2><p class="error">${escape(error instanceof Error ? error.message : 'Unable to load details.')}</p><button id="retry">Try again</button>`;
      detailError = error instanceof Error ? error.message : 'Unable to load details.';
      if (view === 'artists') renderArtists();
    }
  }

  function restoreURL() {
    status.textContent = '';
    const params = new URLSearchParams(location.hash.slice(1));
    const requestedView = params.get('view');
    if (
      requestedView === 'artists' ||
      ((requestedView === 'axes' || requestedView === 'islands') &&
        catalog.manifest.layouts[requestedView])
    )
      view = requestedView;
    const kind = params.get('kind'),
      id = params.get('id');
    if (!requestedView && kind === 'artist') view = 'artists';
    if (
      (kind === 'genre' || kind === 'artist') &&
      id &&
      (kind === 'genre'
        ? lookup.has(`genre:${catalog.genreId(id)}`)
        : lookup.has(`artist:${id}`) || /^[a-f0-9-]{36}$/.test(id))
    )
      void select({ kind, id }, false);
    else {
      clearSelection();
      if (id)
        status.textContent =
          'This selection is not in the current release. Search for another genre or artist.';
    }
  }

  async function loadSearchIndex() {
    const entries = await catalog.loadSearch();
    if (entries === indexedSearch) return;
    searchIndex = entries.filter(searchableEntry).map((entry) => ({
      entry,
      topLevel: entry.kind === 'genre' && genres.get(entry.id)?.parent_id === null,
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
        results.innerHTML = '<p role="status">Search unavailable. Try again.</p>';
      return;
    }
    if (search.value.trim().toLocaleLowerCase() !== query) return;
    const matches = searchMatches(searchIndex, query);
    results.innerHTML = matches.length
      ? matches
          .map(
            (entry) =>
              `<button data-kind="${entry.kind}" data-id="${escape(entry.id)}"><b>${escape(entry.name)}${entry.disambiguation ? ` <small>${escape(entry.disambiguation)}</small>` : ''}</b><span>${entry.kind}</span></button>`,
          )
          .join('')
      : '<p role="status">No matches.</p>';
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
      if (target.closest('#results')) search.blur();
      if (!target.closest('.artist-graph, .artist-path') && !target.closest('#detail'))
        artistPath = [];
      void select(
        { kind: target.dataset.kind as Selection['kind'], id: target.dataset.id },
        true,
        true,
      );
      return;
    }
    if (target.dataset.view) {
      view = target.dataset.view as View;
      writeURL();
      renderCanvas();
      renderDetail();
      return;
    }
    if (target.dataset.zoom === 'reset') resetMap();
    if (target.dataset.remove !== undefined) {
      trail.splice(Number(target.dataset.remove), 1);
      persistTrail();
    }
    if (target.id === 'save' && selected) {
      trail.push({ ...selected });
      persistTrail();
    }
    if (target.id === 'retry' && selected) void select(selected, false);
    if (target.id === 'detail-close') {
      clearSelection();
      writeURL();
    }
    if (target.id === 'trail-toggle' || target.id === 'trail-close') {
      trailPanel.hidden = target.id === 'trail-close' || !trailPanel.hidden;
      document
        .querySelector('#trail-toggle')!
        .setAttribute('aria-expanded', String(!trailPanel.hidden));
      if (!trailPanel.hidden) {
        status.textContent = '';
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
  renderTrail();
  restoreURL();
}

start().catch((error) => {
  app.removeAttribute('aria-busy');
  app.innerHTML = `<h1 class="loading">The atlas could not be opened.</h1><p class="error">${escape(error instanceof Error ? error.message : 'Unknown catalog error')}</p><p class="muted">Check the catalog URL and schema version, then reload. No fallback dataset has been substituted.</p><button onclick="location.reload()">Reload atlas</button>`;
});
