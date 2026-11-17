import type { PanzoomObject } from '@panzoom/panzoom';
import { Catalog } from './data';
import { GenreTree } from './genre-tree';
import { createNavigation, type Navigation } from './navigation';
import type { Genre, GenreDetail, ArtistDetail, SearchEntry } from './catalog';
import {
  artistLabel,
  cameraAt,
  contains,
  genreLabel,
  project,
  type Box,
  type Point,
} from './map-geometry';
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
const worldPoint = (point: Point) => ({ x: 90 + point.x * 820, y: 65 + point.y * 440 });
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
  const searchIndex = catalog.search.map((entry) => ({
    entry,
    terms: [entry.name, ...entry.aliases].map((name) => name.toLocaleLowerCase()),
  }));
  let view: View = catalog.manifest.layouts.axes
    ? 'axes'
    : catalog.manifest.layouts.islands
      ? 'islands'
      : 'tree';
  let selected: Selection | null = null;
  let detail: GenreDetail | ArtistDetail | null = null;
  let controller = new AbortController();
  let panzoom: PanzoomObject | undefined;
  let navigation: Navigation | undefined;
  let labelFrame = 0;
  let islandFamily: string | null = null;
  let cameraView: 'axes' | 'islands' = 'islands';
  let homeCamera = { scale: 1, x: 0, y: 0 };
  const cameras = new Map<View, { scale: number; x: number; y: number }>();
  let mapNodes: {
    node: SVGGElement;
    label: SVGTextElement;
    point: Point;
    width: number;
    id: string;
    active: boolean;
  }[] = [];
  const textWidths = new Map<string, number>();
  const textMeasure = document.createElement('canvas').getContext('2d')!;
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
            lookup.has(`${entry.kind}:${entry.id}`),
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

  function root(genre: Genre): Genre {
    const seen = new Set<string>();
    while (genre.parent_id && genres.has(genre.parent_id) && !seen.has(genre.id)) {
      seen.add(genre.id);
      genre = genres.get(genre.parent_id)!;
    }
    return genre;
  }

  function measureLabel(name: string, size: number, bold = false) {
    const key = `${size}:${bold}:${name}`;
    let width = textWidths.get(key);
    if (width === undefined) {
      textMeasure.font = `${bold ? '700' : '400'} ${size}px Helvetica, Arial, sans-serif`;
      width = textMeasure.measureText(name).width + 2;
      textWidths.set(key, width);
    }
    return width;
  }

  function artistMarkup(layout: 'axes' | 'islands') {
    if (!detail || !('artist' in detail) || !detail.artist.positions[layout]) return '';
    const point = worldPoint(detail.artist.positions[layout]!);
    return `<g transform="translate(${point.x},${point.y})"><path id="artist-leader" stroke="#666666" fill="none"/><path d="M0 -10L9 0L0 10L-9 0Z" fill="#111111"/><text id="artist-label" font-size="14">${escape(detail.artist.name)}</text></g>`;
  }

  function updateMapSelection() {
    for (const item of mapNodes) {
      const active = selected?.kind === 'genre' && selected.id === item.id;
      if (active === item.active) continue;
      item.active = active;
      item.node.setAttribute('aria-pressed', String(active));
      item.node.querySelector('circle')!.setAttribute('r', active ? '8' : '5');
    }
    canvas.querySelector('#artist-layer')!.innerHTML = artistMarkup(cameraView);
    canvas.querySelector('#placement-status')!.textContent =
      selected?.kind === 'artist' &&
      detail &&
      'artist' in detail &&
      !detail.artist.positions[cameraView]
        ? 'Selected artist is not placed'
        : '';
    scheduleLabels();
  }

  function revealSelection() {
    if (!panzoom || view === 'tree') return;
    const position =
      selected?.kind === 'genre'
        ? genres.get(selected.id)?.positions[view]
        : detail && 'artist' in detail
          ? detail.artist.positions[view]
          : null;
    if (!position) return;
    const viewport = canvas.querySelector<HTMLElement>('#map-viewport')!;
    const point = worldPoint(position);
    const camera = { scale: panzoom.getScale(), ...panzoom.getPan() };
    if (
      contains(
        project(point, camera),
        { left: 0, top: 0, right: viewport.clientWidth, bottom: viewport.clientHeight },
        48,
      )
    )
      return;
    const target = cameraAt(point, camera.scale, viewport.clientWidth, viewport.clientHeight);
    panzoom.setOptions({ startX: target.x, startY: target.y });
    panzoom.pan(target.x, target.y);
  }

  function renderCanvas(reveal = false) {
    document
      .querySelectorAll<HTMLButtonElement>('[data-view]')
      .forEach((button) =>
        setAttribute(button, 'aria-pressed', String(button.dataset.view === view)),
      );
    if (view === 'tree') {
      if (panzoom) cameras.set(cameraView, { scale: panzoom.getScale(), ...panzoom.getPan() });
      navigation?.destroy();
      navigation = undefined;
      panzoom = undefined;
      mapNodes = [];
      hierarchy.show(canvas, selected, detail);
      return;
    }
    hierarchy.hide();
    if (panzoom && canvas.querySelector<HTMLElement>('#map-content')?.dataset.layout === view) {
      updateMapSelection();
      if (reveal) revealSelection();
      return;
    }
    if (panzoom) cameras.set(cameraView, { scale: panzoom.getScale(), ...panzoom.getPan() });
    navigation?.destroy();
    navigation = undefined;
    panzoom = undefined;
    mapNodes = [];
    const layout = view;
    const hadCamera = cameras.has(layout);
    const placed = catalog.genres.filter((genre) => genre.positions[layout] !== null);
    const xy = (genre: Genre) => {
      return worldPoint(genre.positions[layout]!);
    };
    const families = new Map<string, Genre[]>();
    for (const genre of placed) {
      const family = root(genre).id;
      families.set(family, [...(families.get(family) || []), genre]);
    }
    const islands =
      view === 'islands'
        ? [...families.values()]
            .map((group) => {
              const points = group.map(xy);
              const left = Math.min(...points.map((point) => point.x)),
                right = Math.max(...points.map((point) => point.x));
              const top = Math.min(...points.map((point) => point.y)),
                bottom = Math.max(...points.map((point) => point.y));
              return `<ellipse cx="${(left + right) / 2}" cy="${(top + bottom) / 2}" rx="${(right - left) / 2 + 65}" ry="${(bottom - top) / 2 + 52}" fill="none" stroke="#aaa" stroke-width="1" vector-effect="non-scaling-stroke"/>`;
            })
            .join('')
        : '<path d="M50 285H950 M500 25V545" stroke="#cccccc" stroke-dasharray="3 7"/>';
    const nodes = placed
      .map((genre) => {
        const { x, y } = xy(genre);
        const active = selected?.kind === 'genre' && selected.id === genre.id;
        return `<g class="genre" role="button" tabindex="0" aria-label="Explore ${escape(genre.name)}" aria-pressed="${active}" data-kind="genre" data-id="${escape(genre.id)}" transform="translate(${x},${y})"><rect x="-30" y="-30" width="60" height="60" fill="transparent"/><circle r="${active ? 8 : 5}" fill="${escape(genre.color || '#111111')}"/><text>${escape(genre.name)}</text></g>`;
      })
      .join('');
    const artist = artistMarkup(layout);
    const axes = catalog.manifest.layouts.axes;
    if (view === 'islands' && !hadCamera && selected?.kind === 'genre')
      islandFamily = root(genres.get(selected.id)!).id;
    const familyNav =
      view === 'islands'
        ? `<nav class="families" aria-label="Focus an island family"><button data-family="" aria-pressed="${islandFamily === null}">All</button>${[...families.keys()].map((id) => `<button data-family="${escape(id)}" aria-pressed="${islandFamily === id}">${escape(genres.get(id)!.name)}</button>`).join('')}</nav>`
        : '';
    canvas.innerHTML = `${familyNav}<div class="map-viewport" id="map-viewport" tabindex="0" role="group" aria-label="${modes[view].label}" aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown + - 0"><div id="map-content" class="map-stage" data-layout="${layout}"><svg viewBox="0 0 1000 570" role="group" aria-label="Genre labels are interactive">${islands}${nodes}<g id="artist-layer">${artist}</g></svg></div></div><div class="map-bottom"><span id="placement-status">${selected?.kind === 'artist' && detail && 'artist' in detail && !detail.artist.positions[layout] ? 'Selected artist is not placed' : ''}</span><div class="zoom" aria-label="Map controls"><button data-zoom="out" aria-label="Zoom out">−</button><button data-zoom="in" aria-label="Zoom in">+</button><button data-zoom="reset">Reset</button></div></div>`;
    mapNodes = [...canvas.querySelectorAll<SVGGElement>('.genre')].map((node, index) => ({
      node,
      label: node.querySelector('text')!,
      point: xy(placed[index]),
      width: measureLabel(placed[index].name, 16, true),
      id: placed[index].id,
      active: selected?.kind === 'genre' && selected.id === placed[index].id,
    }));
    if (view === 'axes' && axes) {
      const legend = document.createElement('div');
      legend.className = 'axis-legend';
      legend.innerHTML = `<span><strong>Left → right:</strong> ${escape(axes.x_min)} → ${escape(axes.x_max)}</span><span><strong>Up → down:</strong> ${escape(axes.y_min)} → ${escape(axes.y_max)}</span>`;
      canvas.querySelector('.map-bottom')!.before(legend);
    }
    cameraView = layout;
    const viewport = canvas.querySelector<HTMLElement>('#map-viewport')!;
    const scale = Math.max(
      0.76,
      Math.min(viewport.clientWidth / 1000, viewport.clientHeight / 570),
    );
    homeCamera = cameraAt({ x: 500, y: 285 }, scale, viewport.clientWidth, viewport.clientHeight);
    const camera =
      cameras.get(layout) ||
      (view === 'islands' && islandFamily ? islandCamera(islandFamily) : homeCamera);
    const content = canvas.querySelector<HTMLDivElement>('#map-content')!;
    navigation = createNavigation(content, viewport, {
      camera,
      maxScale: Math.max(6, scale * 2),
      minScale: 0.25,
      excludeClass: 'genre',
      onChange: scheduleLabels,
      onReset: resetMap,
    });
    panzoom = navigation.panzoom;
    if (reveal) revealSelection();
    scheduleLabels();
  }

  function zoomMap(factor: number, point?: { clientX: number; clientY: number }) {
    navigation?.zoomBy(factor, point);
  }

  function resetMap() {
    if (view === 'islands') focusIslandFamily(null);
    else {
      panzoom?.zoom(homeCamera.scale);
      panzoom?.pan(homeCamera.x, homeCamera.y);
    }
  }

  function focusIslandFamily(id: string | null) {
    if (!panzoom || view !== 'islands') return;
    islandFamily = id;
    canvas.querySelectorAll<HTMLButtonElement>('[data-family]').forEach((button) => {
      button.setAttribute('aria-pressed', String((button.dataset.family || null) === id));
    });
    const camera = id ? islandCamera(id) : homeCamera;
    panzoom.zoom(camera.scale);
    panzoom.pan(camera.x, camera.y);
  }

  function islandCamera(id: string) {
    const points = catalog.genres
      .filter((genre) => root(genre).id === id && genre.positions.islands)
      .map((genre) => genre.positions.islands!);
    if (!points.length) return homeCamera;
    const left = 90 + Math.min(...points.map((point) => point.x)) * 820;
    const right = 90 + Math.max(...points.map((point) => point.x)) * 820;
    const top = 65 + Math.min(...points.map((point) => point.y)) * 440;
    const bottom = 65 + Math.max(...points.map((point) => point.y)) * 440;
    const viewport = canvas.querySelector<HTMLElement>('#map-viewport')!;
    const scale = Math.max(
      0.7,
      Math.min(
        5,
        (viewport.clientWidth - 160) / Math.max(80, right - left),
        (viewport.clientHeight - 90) / Math.max(80, bottom - top),
      ),
    );
    return cameraAt(
      { x: (left + right) / 2, y: (top + bottom) / 2 },
      scale,
      viewport.clientWidth,
      viewport.clientHeight,
    );
  }

  function scheduleLabels() {
    cancelAnimationFrame(labelFrame);
    labelFrame = requestAnimationFrame(positionLabels);
  }

  function positionLabels() {
    if (view === 'tree') return;
    const viewport = canvas.querySelector('#map-viewport')?.getBoundingClientRect();
    const matrix = canvas.querySelector('svg')?.getScreenCTM();
    if (!viewport || !matrix) return;
    const obstacles: Box[] = [];
    for (const { node, label, point, width } of mapNodes) {
      const placement = genreLabel(
        { x: point.x * matrix.a + matrix.e, y: point.y * matrix.d + matrix.f },
        width,
        matrix.a,
        viewport,
      );
      setAttribute(node, 'visibility', placement ? 'visible' : 'hidden');
      setAttribute(node, 'tabindex', placement ? '0' : '-1');
      if (!placement) continue;
      setAttribute(
        label,
        'transform',
        `translate(${placement.x},${placement.y}) scale(${placement.scale})`,
      );
      obstacles.push(placement.box);
    }
    positionArtistLabel(obstacles, viewport, matrix);
  }

  function setAttribute(node: Element, name: string, value: string) {
    if (node.getAttribute(name) !== value) node.setAttribute(name, value);
  }

  function positionArtistLabel(obstacles: Box[], viewport: Box, matrix: DOMMatrix) {
    const label = canvas.querySelector<SVGTextElement>('#artist-label');
    if (!label || !detail || !('artist' in detail) || !detail.artist.positions[cameraView]) return;
    const point = worldPoint(detail.artist.positions[cameraView]!);
    const width = measureLabel(detail.artist.name, 14);
    const placement = artistLabel(
      { x: point.x * matrix.a + matrix.e, y: point.y * matrix.d + matrix.f },
      width,
      matrix.a,
      viewport,
      obstacles,
    );
    const group = label.closest<SVGGElement>('g')!;
    setAttribute(group, 'visibility', placement ? 'visible' : 'hidden');
    if (!placement) return;
    setAttribute(
      label,
      'transform',
      `translate(${placement.x},${placement.y}) scale(${placement.scale})`,
    );
    const moved = placement.x !== 14 || placement.y !== 5;
    const endX = placement.x < 0 ? placement.x + width * placement.scale : placement.x;
    setAttribute(
      canvas.querySelector('#artist-leader')!,
      'd',
      moved ? `M0 0L${endX} ${placement.y - 5}` : '',
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
    return `<div class="breadcrumbs">Genres ${chain.map((parent) => ` / <button data-kind="genre" data-id="${escape(parent.id)}">${escape(parent.name)}</button>`).join('')}</div>`;
  }

  function renderDetail() {
    if (!selected) {
      drawer.innerHTML = `<h2>Genres</h2>${catalog.genres
        .filter((genre) => !genre.parent_id)
        .map((genre) => entityButton('genre', genre.id, genre.name, undefined, genre.color))
        .join('')}`;
      return;
    }
    if (!detail) return;
    const entity = 'genre' in detail ? detail.genre : detail.artist;
    const saved = trail.some((entry) => entry.kind === selected!.kind && entry.id === selected!.id);
    drawer.innerHTML = `${'genre' in detail ? breadcrumbs(detail.genre) : '<p class="muted">Artist</p>'}<h2>${escape(entity.name)}</h2><p class="detail-lede">${'genre' in detail ? count(detail.genre.member_count) : detail.artist.listeners === null ? 'Listener count unavailable' : count(detail.artist.listeners, 'listener')}</p><button id="save" ${saved || trail.length >= 50 ? 'disabled' : ''}>${saved ? 'Saved' : trail.length >= 50 ? 'Saved items full (50)' : 'Save to trail'}</button>${'genre' in detail ? renderGenre(detail) : renderArtist(detail)}`;
  }

  function renderGenre(data: GenreDetail) {
    return `<section><h3>Member artists</h3>${
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
    return `<section><h3>Genres</h3>${
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
    }</section><section><h3>Similar artists</h3>${
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
    if ((kind === 'genre' || kind === 'artist') && id && lookup.has(`${kind}:${id}`))
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

  search.addEventListener('input', () => {
    const query = search.value.trim().toLocaleLowerCase();
    if (!query) {
      results.innerHTML = '';
      return;
    }
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
      '[data-kind], [data-view], [data-family], [data-zoom], [data-remove], button[id]',
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
    if (target.dataset.family !== undefined) {
      focusIslandFamily(target.dataset.family || null);
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
      if (!trailPanel.hidden) trailPanel.scrollIntoView({ block: 'nearest' });
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
    navigation?.destroy();
    navigation = undefined;
    panzoom = undefined;
    cameras.clear();
    if (view === 'tree') hierarchy.resize();
    else renderCanvas();
  });
  renderTrail();
  restoreURL();
}

start().catch((error) => {
  app.removeAttribute('aria-busy');
  app.innerHTML = `<h1 class="loading">The atlas could not be opened.</h1><p class="error">${escape(error instanceof Error ? error.message : 'Unknown catalog error')}</p><p class="muted">Check the catalog URL and schema version, then reload. No fallback dataset has been substituted.</p><button onclick="location.reload()">Reload atlas</button>`;
});
