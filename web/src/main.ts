import Panzoom, { type PanzoomObject } from '@panzoom/panzoom';
import { Catalog } from './data';
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
const count = (value: number | null) =>
  value === null ? 'Count unavailable' : `${value.toLocaleString()} artists`;
const modes: Record<View, { label: string; title: string; description: string }> = {
  islands: {
    label: 'Islands',
    title: 'Follow a different current.',
    description:
      'Explore neighborhoods of related genres. Region envelopes illustrate families, not measured density.',
  },
  axes: {
    label: 'Sonic map',
    title: 'Let your ears be the compass.',
    description:
      'Positions follow the published sonic axes. Nearby does not always mean similar—use the ranked neighbors to explore.',
  },
  tree: {
    label: 'Genre tree',
    title: 'Every branch, another beginning.',
    description:
      'Follow the published broad-to-specific hierarchy. One primary parent is a navigation aid, not a complete history of a genre.',
  },
};

async function start() {
  const catalog = await new Catalog().load();
  const genres = new Map(catalog.genres.map((genre) => [genre.id, genre]));
  const lookup = new Map(catalog.search.map((entry) => [`${entry.kind}:${entry.id}`, entry]));
  const releaseStatus = `${catalog.manifest.release_id} · ${catalog.manifest.data_kind === 'synthetic' ? 'Design fixture, not a quality benchmark.' : 'Explore the published model.'}`;
  let view: View = catalog.manifest.layouts.islands
    ? 'islands'
    : catalog.manifest.layouts.axes
      ? 'axes'
      : 'tree';
  let selected: Selection | null = null;
  let detail: GenreDetail | ArtistDetail | null = null;
  let controller = new AbortController();
  let panzoom: PanzoomObject | undefined;
  let cameraView: 'axes' | 'islands' = 'islands';
  const cameras = new Map<View, { scale: number; x: number; y: number }>();
  const collapsed = new Set<string>();
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
    <section class="intro"><div><p class="eyebrow">Less algorithm. More adventure.</p><h1>A world of sound.<br>No <em>wrong</em> turns.</h1></div>
      <div class="intro-copy"><p>Find a familiar name. Follow an unfamiliar one.<br>Discover the music in between.</p><span class="data-note">${catalog.manifest.data_kind === 'synthetic' ? 'Illustrative data · not model results' : 'Model-derived catalog'} · ${catalog.genres.length} genres</span></div></section>
    <div class="toolbar" id="explore"><div class="search-wrap"><label class="search-box"><span aria-hidden="true">⌕</span><input id="search" type="search" aria-label="Search genres and artists" placeholder="A genre, an artist, a place to begin…" aria-controls="results" autocomplete="off"><kbd aria-hidden="true">/</kbd></label><div id="results" class="search-results" aria-label="Search results"></div></div>
      <nav class="modes" aria-label="Atlas view">${Object.entries(modes)
        .map(
          ([key, mode]) =>
            `<button data-view="${key}" ${key !== 'tree' && !catalog.manifest.layouts[key as 'axes' | 'islands'] ? 'disabled title="This layout has not been published"' : ''}>${mode.label}</button>`,
        )
        .join('')}</nav>
      <button class="quiet" id="trail-toggle" aria-expanded="false" aria-controls="trail">My trail <span id="trail-count">${trail.length}</span></button></div>
    <section class="workspace" aria-label="Genre atlas"><div class="canvas" id="canvas"></div><aside class="detail" id="detail" tabindex="-1" aria-label="Selected genre or artist" aria-live="polite"></aside></section>
    <section class="trail" id="trail" aria-label="Saved discovery trail" hidden></section>
    <div class="under-map"><p><strong>Three lenses. One musical world.</strong> Your selection stays with you when you switch views.</p><p id="status" role="status">${escape(releaseStatus)}</p></div>`;
  app.removeAttribute('aria-busy');
  const canvas = document.querySelector<HTMLElement>('#canvas')!;
  const drawer = document.querySelector<HTMLElement>('#detail')!;
  const search = document.querySelector<HTMLInputElement>('#search')!;
  const results = document.querySelector<HTMLElement>('#results')!;
  const trailPanel = document.querySelector<HTMLElement>('#trail')!;
  const status = document.querySelector<HTMLElement>('#status')!;

  function entityButton(
    kind: Selection['kind'],
    id: string,
    name: string,
    rank?: number,
    color?: string | null,
  ) {
    return `<button class="entity-row" data-kind="${kind}" data-id="${escape(id)}" aria-pressed="${selected?.kind === kind && selected.id === id}">${rank === undefined ? '' : `<span class="number">${String(rank).padStart(2, '0')}</span>`}<span class="dot" style="background:${escape(color || '#285e48')}"></span><span>${escape(name)}</span><span class="arrow" aria-hidden="true">↗</span></button>`;
  }

  function root(genre: Genre): Genre {
    const seen = new Set<string>();
    while (genre.parent_id && genres.has(genre.parent_id) && !seen.has(genre.id)) {
      seen.add(genre.id);
      genre = genres.get(genre.parent_id)!;
    }
    return genre;
  }

  function tree(parent: string | null, seen = new Set<string>()): string {
    return `<ul>${catalog.genres
      .filter((genre) => genre.parent_id === parent && !seen.has(genre.id))
      .map((genre) => {
        const hasChildren = catalog.genres.some((child) => child.parent_id === genre.id);
        const node = `${entityButton('genre', genre.id, genre.name, undefined, genre.color)}<span class="muted">${count(genre.member_count)}</span>`;
        return `<li>${hasChildren ? `<details data-tree="${escape(genre.id)}" ${collapsed.has(genre.id) ? '' : 'open'}><summary>${node}</summary>${tree(genre.id, new Set([...seen, genre.id]))}</details>` : node}</li>`;
      })
      .join('')}</ul>`;
  }

  function renderCanvas() {
    if (panzoom) cameras.set(cameraView, { scale: panzoom.getScale(), ...panzoom.getPan() });
    panzoom?.destroy();
    panzoom = undefined;
    document
      .querySelectorAll<HTMLButtonElement>('[data-view]')
      .forEach((button) =>
        button.setAttribute('aria-pressed', String(button.dataset.view === view)),
      );
    const header = `<div class="canvas-header"><p class="eyebrow">${view === 'tree' ? 'The family resemblance' : 'The open atlas'} / ${modes[view].label}</p><h2>${modes[view].title}</h2><p>${modes[view].description}</p></div>`;
    if (view === 'tree') {
      canvas.innerHTML = `${header}<div class="tree" aria-label="Genre hierarchy">${tree(null)}</div><div class="map-bottom"><span>Expand a family. Select any genre.</span></div>`;
      return;
    }
    const layout = view;
    const placed = catalog.genres.filter((genre) => genre.positions[layout] !== null);
    const xy = (genre: Genre) => {
      const point = genre.positions[layout]!;
      return { x: 90 + point.x * 820, y: 65 + point.y * 440 };
    };
    const families = new Map<string, Genre[]>();
    for (const genre of placed) {
      const family = root(genre).id;
      families.set(family, [...(families.get(family) || []), genre]);
    }
    const islands =
      view === 'islands'
        ? [...families.entries()]
            .map(([id, group]) => {
              const points = group.map(xy);
              const left = Math.min(...points.map((point) => point.x)),
                right = Math.max(...points.map((point) => point.x));
              const top = Math.min(...points.map((point) => point.y)),
                bottom = Math.max(...points.map((point) => point.y));
              const color = escape(genres.get(id)?.color || '#628d69');
              return `<ellipse cx="${(left + right) / 2}" cy="${(top + bottom) / 2}" rx="${(right - left) / 2 + 65}" ry="${(bottom - top) / 2 + 52}" fill="${color}" fill-opacity=".07" stroke="${color}" stroke-opacity=".18" stroke-width="1.5"/><ellipse cx="${(left + right) / 2}" cy="${(top + bottom) / 2}" rx="${(right - left) / 2 + 48}" ry="${(bottom - top) / 2 + 37}" fill="${color}" fill-opacity=".04" stroke="${color}" stroke-opacity=".12"/>`;
            })
            .join('')
        : '<path d="M50 285H950 M500 25V545" stroke="#aab9a4" stroke-dasharray="3 7" opacity=".5"/>';
    const nodes = placed
      .map((genre) => {
        const { x, y } = xy(genre);
        const active = selected?.kind === 'genre' && selected.id === genre.id;
        return `<g class="genre" role="button" tabindex="0" aria-label="Explore ${escape(genre.name)}" aria-pressed="${active}" data-kind="genre" data-id="${escape(genre.id)}" transform="translate(${x},${y})"><circle r="${active ? 8 : 5}" fill="${escape(genre.color || '#285e48')}"/><text x="${x > 790 ? -13 : 13}" y="5" text-anchor="${x > 790 ? 'end' : 'start'}">${escape(genre.name)}</text></g>`;
      })
      .join('');
    let artist = '';
    if (detail && 'artist' in detail && detail.artist.positions[layout]) {
      const point = detail.artist.positions[layout]!;
      artist = `<g transform="translate(${90 + point.x * 820},${65 + point.y * 440})"><path id="artist-leader" stroke="#627368" fill="none"/><path d="M0 -10L9 0L0 10L-9 0Z" fill="#22352f"/><text id="artist-label" x="14" y="5" font-size="14">${escape(detail.artist.name)}</text></g>`;
    }
    const axes = catalog.manifest.layouts.axes;
    canvas.innerHTML = `${header}<div class="map-viewport" id="map-viewport"><svg viewBox="0 0 1000 570" role="group" aria-label="${modes[view].label}; genre labels are interactive"><g id="map-content">${islands}${nodes}${artist}</g></svg>${view === 'axes' && axes ? `<span class="axis top">${escape(axes.y_min)}</span><span class="axis bottom">${escape(axes.y_max)}</span><span class="axis left">${escape(axes.x_min)}</span><span class="axis right">${escape(axes.x_max)}</span>` : ''}</div><div class="map-bottom"><span>${placed.length} genres placed${placed.length < catalog.genres.length ? ` · ${catalog.genres.length - placed.length} without coordinates` : ''}${selected?.kind === 'artist' && detail && 'artist' in detail && !detail.artist.positions[layout] ? ' · Selected artist is not placed' : ''}<br>Pan to wander. Zoom to get closer.</span><div class="zoom" aria-label="Map controls"><button data-zoom="out" aria-label="Zoom out">−</button><button data-zoom="in" aria-label="Zoom in">+</button><button data-zoom="reset">Reset</button></div></div>`;
    positionArtistLabel();
    cameraView = layout;
    const camera = cameras.get(layout);
    panzoom = Panzoom(document.querySelector<SVGGElement>('#map-content')!, {
      maxScale: 5,
      minScale: 0.7,
      canvas: true,
      excludeClass: 'genre',
      ...(camera ? { startScale: camera.scale, startX: camera.x, startY: camera.y } : {}),
    });
  }

  function positionArtistLabel() {
    const label = canvas.querySelector<SVGTextElement>('#artist-label');
    if (!label) return;
    const obstacles = [...canvas.querySelectorAll<SVGGElement>('.genre')].map((node) =>
      node.getBoundingClientRect(),
    );
    const viewport = canvas.querySelector('svg')!.getBoundingClientRect();
    const padding = (viewport.width / 1000) * 5;
    const width = label.getBBox().width;
    const candidates = [
      [0, 0],
      [0, -26],
      [0, 26],
      [-width - 28, -26],
      [-width - 28, 26],
      [0, -52],
      [0, 52],
    ];
    let best = candidates[0];
    let bestScore = Infinity;
    for (const offset of candidates) {
      label.setAttribute('transform', `translate(${offset[0]},${offset[1]})`);
      const box = label.getBoundingClientRect();
      const score = obstacles.reduce(
        (area, other) =>
          area +
          Math.max(
            0,
            Math.min(box.right, other.right + padding) - Math.max(box.left, other.left - padding),
          ) *
            Math.max(
              0,
              Math.min(box.bottom, other.bottom + padding) - Math.max(box.top, other.top - padding),
            ),
        box.width * box.height -
          Math.max(0, Math.min(box.right, viewport.right) - Math.max(box.left, viewport.left)) *
            Math.max(0, Math.min(box.bottom, viewport.bottom) - Math.max(box.top, viewport.top)),
      );
      if (score < bestScore) {
        best = offset;
        bestScore = score;
      }
      if (score === 0) break;
    }
    label.setAttribute('transform', `translate(${best[0]},${best[1]})`);
    if (best[0] || best[1])
      canvas
        .querySelector('#artist-leader')!
        .setAttribute('d', `M0 0L${best[0] < 0 ? -14 : 14} ${best[1]}`);
  }

  function breadcrumbs(genre: Genre) {
    const chain: Genre[] = [];
    const seen = new Set([genre.id]);
    while (genre.parent_id && genres.has(genre.parent_id) && !seen.has(genre.parent_id)) {
      genre = genres.get(genre.parent_id)!;
      seen.add(genre.id);
      chain.unshift(genre);
    }
    return `<div class="breadcrumbs">All sound ${chain.map((parent) => ` / <button data-kind="genre" data-id="${escape(parent.id)}">${escape(parent.name)}</button>`).join('')}</div>`;
  }

  function renderDetail() {
    if (!selected) {
      drawer.innerHTML = `<p class="eyebrow">Where will you begin?</p><h2>A little curiosity<br>goes a long way.</h2><p class="detail-lede">Select a genre on the atlas, or search for an artist you love. The map is just the beginning.</p><section><div class="section-label"><h3>Pick a starting point</h3><span>Genre families</span></div>${catalog.genres
        .filter((genre) => !genre.parent_id)
        .map((genre) => entityButton('genre', genre.id, genre.name, undefined, genre.color))
        .join(
          '',
        )}</section><section><p class="muted">No account. No listening history required. Your saved trail stays in this browser.</p></section>`;
      return;
    }
    if (!detail) return;
    const entity = 'genre' in detail ? detail.genre : detail.artist;
    const saved = trail.some((entry) => entry.kind === selected!.kind && entry.id === selected!.id);
    drawer.innerHTML = `${'genre' in detail ? breadcrumbs(detail.genre) : '<p class="eyebrow">Artist field notes</p>'}<h2>${escape(entity.name)}</h2><p class="detail-lede">${'genre' in detail ? `${count(detail.genre.member_count)} · ${catalog.manifest.membership ? 'Published membership' : 'Membership not computed'}` : `${detail.artist.listeners === null ? 'Listener count unavailable' : `${detail.artist.listeners.toLocaleString()} listeners`}<br>${detail.signals.map((signal) => `<span class="pill">${escape(signal)}</span>`).join('')}`}</p><button class="solid" id="save" ${saved || trail.length >= 50 ? 'disabled' : ''}>${saved ? 'Saved to your trail' : trail.length >= 50 ? 'Trail full (50 stops)' : '+ Add to my trail'}</button>${'genre' in detail ? renderGenre(detail) : renderArtist(detail)}`;
  }

  function renderGenre(data: GenreDetail) {
    return `<section><div class="section-label"><h3>A few names to know</h3><span>Ranked artists</span></div>${
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
    }</section><section><div class="section-label"><h3>Follow the thread</h3><span>Related genres</span></div>${
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
    }<p class="muted">${escape(catalog.manifest.genre_similarity || 'No published similarity method')}. Rank is not a probability.</p></section>`;
  }

  function renderArtist(data: ArtistDetail) {
    const links = data.links.filter((link) => /^https?:\/\//i.test(link.url));
    return `<section><div class="section-label"><h3>At home in</h3><span>Genre membership</span></div>${
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
    }</section><section><div class="section-label"><h3>Go a little further</h3><span>Similar artists</span></div>${
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
    }<p class="muted">${escape(catalog.manifest.similarity || 'No published similarity method')}. Rank is not a probability.</p></section><section><h3 class="eyebrow">Listen elsewhere</h3>${links.length ? `<div class="links">${links.map((link) => `<a href="${escape(link.url)}" target="_blank" rel="noopener noreferrer">${escape(link.label)} ↗</a>`).join('')}</div>` : '<p class="empty">No listening links in this release.</p>'}<p class="muted">${data.preview ? 'A preview locator is available. Provider playback is not connected in this study.' : 'No preview available. Nothing plays automatically.'}</p></section>`;
  }

  function renderTrail() {
    document.querySelector('#trail-count')!.textContent = String(trail.length);
    trailPanel.innerHTML = `<div class="trail-header"><div><h2>Your curiosity, collected.</h2><p>${storageAvailable ? 'Saved in this browser only.' : 'Browser storage unavailable; this trail lasts for this tab only.'} Maximum 50 stops.</p></div><button class="quiet" id="trail-close">Close trail</button></div><div class="trail-items">${trail.length ? trail.map((entry, index) => `<div class="trail-item"><button data-kind="${entry.kind}" data-id="${escape(entry.id)}">${String(index + 1).padStart(2, '0')} · ${escape(lookup.get(`${entry.kind}:${entry.id}`)?.name || entry.id)}</button><button data-remove="${index}" aria-label="Remove ${escape(lookup.get(`${entry.kind}:${entry.id}`)?.name || entry.id)} from trail">×</button></div>`).join('') : '<p class="empty">Find something interesting? Add it from its field notes.</p>'}</div>`;
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
    status.textContent = releaseStatus;
    const params = new URLSearchParams({ view });
    if (selected) {
      params.set('kind', selected.kind);
      params.set('id', selected.id);
    }
    history.pushState(null, '', `#${params}`);
  }

  async function select(selection: Selection, push = true) {
    controller.abort();
    controller = new AbortController();
    selected = selection;
    detail = null;
    if (push) writeURL();
    drawer.innerHTML = '<p class="empty" role="status">Opening field notes…</p>';
    renderCanvas();
    results.innerHTML = '';
    try {
      const loaded =
        selection.kind === 'genre'
          ? await catalog.genre(selection.id, controller.signal)
          : await catalog.artist(selection.id, controller.signal);
      if (selected !== selection) return;
      detail = loaded;
      renderDetail();
      renderCanvas();
      drawer.focus({ preventScroll: true });
    } catch (error) {
      if (selected !== selection || (error instanceof DOMException && error.name === 'AbortError'))
        return;
      drawer.innerHTML = `<h2>Not quite there.</h2><p class="error">${escape(error instanceof Error ? error.message : 'Unable to open these field notes.')}</p><button class="quiet" id="retry">Try again</button>`;
    }
  }

  function restoreURL() {
    status.textContent = releaseStatus;
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
          'This selection is not in the current release. Search for a new starting point.';
    }
  }

  search.addEventListener('input', () => {
    const query = search.value.trim().toLocaleLowerCase();
    if (!query) {
      results.innerHTML = '';
      return;
    }
    const matches = catalog.search
      .filter((entry) =>
        [entry.name, ...entry.aliases].some((name) => name.toLocaleLowerCase().includes(query)),
      )
      .slice(0, 12);
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
    if (target.dataset.zoom === 'in') panzoom?.zoomIn();
    if (target.dataset.zoom === 'out') panzoom?.zoomOut();
    if (target.dataset.zoom === 'reset') {
      panzoom?.zoom(1);
      panzoom?.pan(0, 0);
    }
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
  canvas.addEventListener(
    'toggle',
    (event) => {
      const target = event.target;
      if (target instanceof HTMLDetailsElement && target.dataset.tree) {
        if (target.open) collapsed.delete(target.dataset.tree);
        else collapsed.add(target.dataset.tree);
      }
    },
    true,
  );
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
  app.innerHTML = `<h1 class="loading">The atlas could not be opened.</h1><p class="error">${escape(error instanceof Error ? error.message : 'Unknown catalog error')}</p><p class="muted">Check the catalog URL and schema version, then reload. No fallback dataset has been substituted.</p><button class="quiet" onclick="location.reload()">Reload atlas</button>`;
});
