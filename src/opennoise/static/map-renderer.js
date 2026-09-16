/* Static atlas viewport: supplied coordinates only, no graph simulation. */
import {
  boundsForNodes,
  clamp,
  fitCamera,
  focusCamera,
  structuralNeighborhood,
  isNodeRevealed,
  labelBudgetForScale,
  levelForScale,
  normaliseAtlasPayload,
  appendCirclePath,
  visibleNodeLabels,
  zoomAtCenter,
  zoomAt,
} from './map-atlas.mjs';

const canvas = document.querySelector('#semantic-map');

if (canvas instanceof HTMLCanvasElement) {
  const controls = document.querySelector('#map-controls');
  const back = controls?.querySelector('[data-map-action="back"]');
  const detail = document.querySelector('#map-detail');
  const query = document.querySelector('#query');
  const endpoint = canvas.dataset.mapUrl;
  const discoveryEndpoint = canvas.dataset.discoveryUrl;
  const state = { atlas: null, discovery: null, discoveryPromise: null, artist: null, camera: null, worldCenter: null, fitScale: 1, viewport: { width: 0, height: 0 }, focus: null, edges: [], neighborhoodIds: null, displayedIds: new Set(), frame: 0, drag: null, pointers: new Map(), pinch: null, moved: false, labelWidths: new Map() };
  const overviewPadding = () => {
    const bounds = state.atlas.worldBounds;
    const density = state.atlas.nodes.length / ((bounds.x1 - bounds.x0) * (bounds.y1 - bounds.y0));
    return density >= 1000 ? .95 : (density >= 250 ? .9 : .94);
  };
  const palette = () => { const css = getComputedStyle(document.documentElement); return Object.fromEntries(['canvas', 'node', 'ink', 'edge', 'focus', 'parent', 'similarity'].map((key) => [key, css.getPropertyValue(`--${key}`).trim()])); };
  const syncWorldCenter = () => {
    state.worldCenter = {
      x: (state.viewport.width / 2 - state.camera.x) / state.camera.scale,
      y: (state.viewport.height / 2 - state.camera.y) / state.camera.scale,
    };
  };
  const worldAt = (screen) => ({
    x: state.worldCenter.x + (screen.x - state.viewport.width / 2) / state.camera.scale,
    y: state.worldCenter.y + (screen.y - state.viewport.height / 2) / state.camera.scale,
  });
  const point = (node) => ({
    x: state.viewport.width / 2 + (node.x - state.worldCenter.x) * state.camera.scale,
    y: state.viewport.height / 2 + (node.y - state.worldCenter.y) * state.camera.scale,
  });
  const publicId = (id) => typeof id === 'string' ? id.slice(id.lastIndexOf(':') + 1) : id;
  const canonicalizeFocusUrl = () => {
    const url = new URL(window.location.href);
    const raw = url.searchParams.get('open_focus'); const clean = publicId(raw);
    if (raw && clean !== raw) { url.searchParams.set('open_focus', clean); history.replaceState({ opennoiseFocus: clean }, '', url); }
    return clean;
  };
  const level = () => levelForScale(state.camera.scale, state.fitScale);
  const visible = (node) => { const screen = point(node); return screen.x >= -8 && screen.y >= -8 && screen.x <= state.viewport.width + 8 && screen.y <= state.viewport.height + 8; };
  const schedule = () => { if (!state.frame) state.frame = requestAnimationFrame(draw); };
  const fit = () => {
    if (!state.atlas || !state.viewport.width || !state.viewport.height) return;
    // Scale dense atlases down slightly so labels and edge communities have
    // breathing room without changing their persisted geometry.
    state.camera = fitCamera(state.atlas.initialCamera, state.viewport, overviewPadding());
    syncWorldCenter();
    state.fitScale = state.camera.scale;
    state.focus = null; state.artist = null; state.edges = []; state.neighborhoodIds = null;
    state.displayedIds.clear();
    if (back) back.hidden = true;
    if (detail) detail.hidden = true;
    schedule();
  };
  const headings = () => {
    const roots = state.atlas.browseLandmarks;
    const regions = state.atlas.regions.length
      ? state.atlas.regions.filter((region) => (region.overview_visible ?? true) === true && typeof region.title === 'string' && Number.isFinite(region.x) && Number.isFinite(region.y))
      : state.atlas.labels[0].map((id) => state.atlas.byId.get(id)).filter(Boolean).map((node) => ({ title: node.name, x: node.x, y: node.y }));
    const seen = new Set();
    return [...roots, ...regions].filter((region) => {
      const key = String(region.title).toLocaleLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };
  const drawLabel = (context, name, placement, colors) => {
    const width = placement.width ?? context.measureText(name).width;
    const x = placement.x;
    context.fillStyle = colors.ink; context.strokeStyle = colors.canvas; context.lineWidth = 4;
    context.strokeText(name, x, placement.y); context.fillText(name, x, placement.y);
  };
  const boxOverlapsRect = (box, rect) => box.x0 < rect.right && box.x1 > rect.left
    && box.y0 < rect.bottom && box.y1 > rect.top;
  const staticLabelLayers = (lod) => {
    const overlays = [document.querySelector('#search'), detail, controls]
      .filter((element) => element && !element.hidden)
      .map((element) => element.getBoundingClientRect());
    return state.atlas.staticLabels.map((label) => {
      const node = state.atlas.byId.get(label.id);
      if (!node || node.lod > lod || label.revealScale > state.camera.scale) return null;
      const screen = point(node);
      const x = screen.x + label.offsetX;
      const y = screen.y + label.offsetY;
      const box = { x0: x, y0: y - label.height, x1: x + label.width, y1: y };
      if (screen.x < 0 || screen.y < 0 || screen.x > state.viewport.width || screen.y > state.viewport.height
        || box.x0 < 0 || box.y0 < 0 || box.x1 > state.viewport.width || box.y1 > state.viewport.height
        || overlays.some((rect) => boxOverlapsRect(box, rect))) return null;
      return { item: {
        ...label,
        text: node.name,
        cohortKey: state.atlas.cohortKeys.get(node.id),
        screen,
        placement: { x, y, box, anchorSide: label.side, width: label.width },
      }, alpha: 1 };
    }).filter(Boolean);
  };
  const draw = () => {
    state.frame = 0;
    if (!state.atlas || !state.camera) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const context = canvas.getContext('2d'); if (!context) return;
    if (canvas.width !== Math.round(state.viewport.width * ratio) || canvas.height !== Math.round(state.viewport.height * ratio)) { canvas.width = Math.round(state.viewport.width * ratio); canvas.height = Math.round(state.viewport.height * ratio); }
    context.setTransform(ratio, 0, 0, ratio, 0, 0); context.clearRect(0, 0, state.viewport.width, state.viewport.height);
    const colors = palette(); const lod = level(); canvas.dataset.mapLod = String(lod); canvas.dataset.mapScale = String(state.camera.scale); canvas.dataset.mapCohorts = ''; context.font = '14px ui-sans-serif, system-ui, sans-serif';
    state.displayedIds.clear();
    const measureLabel = (name) => {
      const key = `${context.font}\u0000${name}`;
      const cached = state.labelWidths.get(key);
      if (cached !== undefined) return cached;
      const width = context.measureText(name).width;
      state.labelWidths.set(key, width);
      return width;
    };
    if (lod === 0) {
      const labelLayers = staticLabelLayers(lod);
      canvas.dataset.mapLabelCount = String(labelLayers.length);
      for (const { item } of labelLayers) {
        state.displayedIds.add(item.id);
        context.fillStyle = colors.node; context.beginPath(); context.arc(item.screen.x, item.screen.y, 3.5, 0, Math.PI * 2); context.fill();
        drawLabel(context, item.text, item.placement, colors);
      }
      return;
    }
    for (const edge of state.edges) { const left = state.atlas.byId.get(edge.source); const right = state.atlas.byId.get(edge.target); if (!left || !right) continue; const start = point(left); const end = point(right); context.strokeStyle = colors.similarity; context.globalAlpha = .7; context.lineWidth = 1.5; context.setLineDash([4, 3]); context.beginPath(); context.moveTo(start.x, start.y); context.lineTo(end.x, end.y); context.stroke(); context.setLineDash([]); }
    const requiredIds = state.edges.flatMap((edge) => [edge.source, edge.target]);
    const selectedLabels = state.focus
      ? visibleNodeLabels(
        state.atlas,
        lod,
        state.viewport,
        point,
        measureLabel,
        {
          maximum: labelBudgetForScale(state.camera.scale, state.fitScale),
          focusId: state.focus,
          requiredIds,
          mandatoryIds: [],
          allowedIds: state.neighborhoodIds,
          camera: state.camera,
          height: 16,
          padding: 3,
          margin: 160,
        },
      ).map((item) => ({ item, alpha: 1 }))
      : staticLabelLayers(lod);
    const labelItems = selectedLabels.map(({ item }) => item);
    const shown = new Set(labelItems.map((item) => item.id));
    canvas.dataset.mapLabelCount = String(labelItems.length);
    canvas.dataset.mapCohorts = [...new Set(labelItems.map((item) => item.cohortKey).filter(Boolean))].join('|');
    const required = new Set(requiredIds);
    // Keep the map's hot path to three Canvas fill calls. The old per-node
    // beginPath/fill pair made dense LOD3 frames needlessly expensive while
    // producing the same circles and alpha ordering.
    const faintPath = new Path2D();
    const labelPath = new Path2D();
    const focusPath = new Path2D();
    for (const node of state.atlas.nodes) {
      if (state.neighborhoodIds && !state.neighborhoodIds.has(node.id)) continue;
      if (!visible(node) || (node.lod > lod && node.id !== state.focus && !required.has(node.id))) continue;
      if (!shown.has(node.id) && node.id !== state.focus && !required.has(node.id)
        && !isNodeRevealed(node, state.camera.scale, state.fitScale)) continue;
      state.displayedIds.add(node.id);
      const screen = point(node);
      if (node.id === state.focus) appendCirclePath(focusPath, screen.x, screen.y, 3.2);
      else if (shown.has(node.id)) appendCirclePath(labelPath, screen.x, screen.y, 3.2);
      else appendCirclePath(faintPath, screen.x, screen.y, 1.35);
    }
    context.globalAlpha = .4; context.fillStyle = colors.node; context.fill(faintPath);
    context.globalAlpha = 1; context.fillStyle = colors.node; context.fill(labelPath);
    context.fillStyle = colors.focus; context.fill(focusPath);
    context.globalAlpha = 1;
    for (const { item } of selectedLabels) if (visible(state.atlas.byId.get(item.id))) {
      if (item.placement.callout) {
        context.strokeStyle = colors.edge; context.globalAlpha = .35; context.lineWidth = 1;
        context.beginPath(); context.moveTo(item.screen.x, item.screen.y); context.lineTo(item.placement.x, item.placement.y - 4); context.stroke();
        context.globalAlpha = 1;
      }
      drawLabel(context, item.text, { ...item.placement, width: item.width }, colors);
    }
  };
  const setUrl = (id) => { const url = new URL(window.location.href); if (id) url.searchParams.set('open_focus', id); else url.searchParams.delete('open_focus'); history.pushState({ opennoiseFocus: id }, '', url); };
  const zoomHere = () => {
    const node = state.focus ? state.atlas?.byId.get(state.focus) : null;
    if (!node || !state.camera) return;
    const staticLabel = state.atlas.staticLabels.find((label) => label.id === node.id);
    const scale = clamp(
      Math.max(state.camera.scale * 1.5, (staticLabel?.revealScale ?? state.camera.scale) * 1.05),
      state.fitScale,
      state.atlas.maximumScale,
    );
    state.camera = {
      scale,
      x: state.viewport.width / 2 - node.x * scale,
      y: state.viewport.height / 2 - node.y * scale,
    };
    // Enter normal static browse at an exact selected world center. Browser
    // Back restores the focused connection detail that led here.
    state.worldCenter = { x: node.x, y: node.y };
    state.focus = null; state.edges = []; state.neighborhoodIds = null;
    state.displayedIds.clear();
    if (detail) detail.hidden = true;
    setUrl(null);
    schedule();
  };
  const normaliseDiscovery = (payload) => ({
    availability: payload?.availability === 'ready' ? 'ready' : 'unavailable',
    genres: new Map((Array.isArray(payload?.genres) ? payload.genres : []).filter((item) => typeof item?.node_id === 'string').map((item) => [item.node_id, item])),
    artists: new Map((Array.isArray(payload?.artists) ? payload.artists : []).filter((item) => typeof item?.artist_id === 'string').map((item) => [item.artist_id, item])),
  });
  const loadDiscovery = () => {
    if (state.discoveryPromise || !discoveryEndpoint) return state.discoveryPromise;
    state.discoveryPromise = fetch(discoveryEndpoint).then((response) => response.json()).then((payload) => {
      state.discovery = normaliseDiscovery(payload); if (state.artist) showArtist(state.artist); else if (state.focus) showDetail(state.focus, state.edges);
    }).catch(() => { state.discovery = normaliseDiscovery(null); if (state.focus) showDetail(state.focus, state.edges); });
    return state.discoveryPromise;
  };
  const detailHeading = (text) => { const heading = document.createElement('h3'); heading.textContent = text; detail.append(heading); };
  const detailList = () => { const list = document.createElement('ul'); detail.append(list); return list; };
  const detailEmpty = (text) => { const empty = document.createElement('p'); empty.className = 'detail-empty'; empty.textContent = text; detail.append(empty); };
  const artistButton = (artist) => {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'detail-action'; button.dataset.openArtistId = artist.artist_id; button.textContent = artist.name; return button;
  };
  const showDetail = (id, edges) => {
    if (!detail) return;
    detail.replaceChildren();
    const heading = document.createElement('h2'); heading.textContent = state.atlas.byId.get(id).name; detail.append(heading);
    const zoom = document.createElement('button'); zoom.type = 'button'; zoom.className = 'zoom-here'; zoom.textContent = 'Zoom here'; zoom.addEventListener('click', zoomHere); detail.append(zoom);
    if (edges.length) { const label = document.createElement('h3'); label.textContent = 'Structural connections'; detail.append(label); const list = document.createElement('ul'); for (const edge of edges) { const nodeId = edge.source === id ? edge.target : edge.source; const peer = state.atlas.byId.get(nodeId); if (!peer) continue; const item = document.createElement('li'); const link = document.createElement('a'); link.href = `?open_focus=${encodeURIComponent(peer.id)}`; link.dataset.openNodeId = peer.id; link.textContent = peer.name; item.append(link); list.append(item); } detail.append(list); }
    if (state.discovery?.availability === 'ready') {
      detailHeading('Artists');
      const discoveryGenre = state.discovery.genres.get(id);
      if (!discoveryGenre) detailEmpty('No direct catalog observations for this map label.');
      else {
        const list = detailList();
        for (const artistId of discoveryGenre.artist_ids) {
          const artist = state.discovery.artists.get(artistId); if (!artist) continue;
          const item = document.createElement('li'); item.append(artistButton(artist)); list.append(item);
        }
      }
    }
    detail.hidden = false;
  };
  const showArtist = (artistId) => {
    if (!detail || !state.discovery || !state.focus) return;
    const artist = state.discovery.artists.get(artistId); if (!artist) return;
    state.artist = artistId; detail.replaceChildren();
    const backToGenre = document.createElement('button'); backToGenre.type = 'button'; backToGenre.className = 'detail-back'; backToGenre.dataset.mapAction = 'genre-detail'; backToGenre.textContent = state.atlas.byId.get(state.focus).name; detail.append(backToGenre);
    const heading = document.createElement('h2'); heading.textContent = artist.name; detail.append(heading);
    detailHeading('Direct genres');
    const genres = detailList();
    for (const membership of artist.memberships) {
      const item = document.createElement('li'); const link = document.createElement('a'); link.href = `?open_focus=${encodeURIComponent(membership.node_id)}`; link.dataset.openNodeId = membership.node_id; link.textContent = membership.catalog_genre_name; item.append(link); genres.append(item);
    }
    detailHeading('Shared genres');
    if (!artist.shared_genre_artists.length) detailEmpty('No other artist shares a direct mapped genre.');
    else {
      const shared = detailList();
      for (const relation of artist.shared_genre_artists) {
        const peer = state.discovery.artists.get(relation.artist_id); if (!peer) continue;
        const item = document.createElement('li'); const button = artistButton(peer); const genreNames = relation.shared_genre_ids.map((id) => state.atlas.byId.get(id)?.name).filter(Boolean); button.title = genreNames.join(', '); item.append(button); shared.append(item);
      }
    }
    detail.hidden = false;
  };
  const focus = (id, push = true) => {
    if (!state.atlas?.byId.has(id)) return;
    state.focus = id; state.artist = null; state.edges = []; state.neighborhoodIds = new Set([id]); if (back) back.hidden = false; if (push) setUrl(id); void loadDiscovery();
    const neighborhood = structuralNeighborhood(state.atlas, id);
    const cameraFor = (edges) => {
      const ids = new Set([id]); for (const edge of edges) { ids.add(edge.source); ids.add(edge.target); }
      const nodes = [...ids].map((key) => state.atlas.byId.get(key)).filter(Boolean);
      const focusBounds = boundsForNodes(nodes, state.atlas.initialCamera);
      return focusCamera(
        focusBounds,
        state.viewport,
        state.fitScale * 1.5,
        state.atlas.maximumScale,
        .72,
        { x: state.atlas.byId.get(id).x, y: state.atlas.byId.get(id).y },
      );
    };
    // Focused connection sets need a detail LOD. A broad set can otherwise fit
    // at the overview scale.
    state.edges = neighborhood.edges;
    state.camera = cameraFor(state.edges);
    syncWorldCenter();
    state.neighborhoodIds = new Set(neighborhood.nodeIds);
    showDetail(id, state.edges);
    schedule();
  };
  const nearest = (cursor) => { let hit = null; let distance = 15; for (const id of state.displayedIds) { const node = state.atlas.byId.get(id); if (!node) continue; const screen = point(node); const next = Math.hypot(screen.x - cursor.x, screen.y - cursor.y); if (next < distance) { hit = node; distance = next; } } return hit; };
  new ResizeObserver(() => { const viewport = { width: canvas.clientWidth, height: canvas.clientHeight }; if (!viewport.width || !viewport.height) return; const center = state.worldCenter; state.viewport = viewport; if (!state.camera) fit(); else { state.camera.x = viewport.width / 2 - center.x * state.camera.scale; state.camera.y = viewport.height / 2 - center.y * state.camera.scale; state.worldCenter = center; schedule(); } }).observe(canvas);
  canvas.addEventListener('wheel', (event) => { event.preventDefault(); if (!state.camera) return; const cursor = { x: event.offsetX, y: event.offsetY }; const anchor = worldAt(cursor); state.camera = zoomAt(state.camera, cursor, event.deltaY < 0 ? 1.25 : .8, { min: state.fitScale, max: state.atlas.maximumScale }); state.worldCenter = { x: anchor.x - (cursor.x - state.viewport.width / 2) / state.camera.scale, y: anchor.y - (cursor.y - state.viewport.height / 2) / state.camera.scale }; schedule(); }, { passive: false });
  const pointerPair = () => [...state.pointers.values()].slice(0, 2);
  const midpoint = ([first, second]) => ({ x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 });
  const separation = ([first, second]) => Math.hypot(first.x - second.x, first.y - second.y);
  const beginPinch = () => {
    const pair = pointerPair();
    if (pair.length !== 2 || !state.camera) return;
    state.drag = null; state.moved = true;
    const center = midpoint(pair);
    state.pinch = { camera: { ...state.camera }, center, world: worldAt(center), distance: Math.max(1, separation(pair)) };
  };
  canvas.addEventListener('pointerdown', (event) => {
    canvas.setPointerCapture(event.pointerId);
    state.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (state.pointers.size === 1) { state.drag = { x: event.clientX, y: event.clientY }; state.moved = false; }
    else beginPinch();
  });
  canvas.addEventListener('pointermove', (event) => {
    if (!state.pointers.has(event.pointerId) || !state.camera) return;
    state.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (state.pointers.size >= 2) {
      if (!state.pinch) beginPinch();
      const pair = pointerPair(); const current = state.pinch;
      if (!current || pair.length !== 2) return;
      const center = midpoint(pair);
      const scale = clamp(current.camera.scale * separation(pair) / current.distance, state.fitScale, state.atlas.maximumScale);
      const worldX = (current.center.x - current.camera.x) / current.camera.scale;
      const worldY = (current.center.y - current.camera.y) / current.camera.scale;
      state.camera = { scale, x: center.x - worldX * scale, y: center.y - worldY * scale };
      state.worldCenter = { x: current.world.x - (center.x - state.viewport.width / 2) / scale, y: current.world.y - (center.y - state.viewport.height / 2) / scale };
      schedule(); return;
    }
    if (!state.drag) return;
    const dx = event.clientX - state.drag.x; const dy = event.clientY - state.drag.y;
    state.drag = { x: event.clientX, y: event.clientY };
    if (Math.hypot(dx, dy) > 2) state.moved = true;
    state.camera.x += dx; state.camera.y += dy; state.worldCenter.x -= dx / state.camera.scale; state.worldCenter.y -= dy / state.camera.scale; schedule();
  });
  const clearPointer = (pointerId) => {
    state.pointers.delete(pointerId);
    state.pinch = null;
    if (state.pointers.size === 1) {
      const [remaining] = pointerPair();
      state.drag = { ...remaining };
    } else {
      state.drag = null;
      if (state.pointers.size === 0) state.moved = false;
    }
  };
  const finishPointer = (event, cancelled = false) => {
    const hit = !cancelled && !state.moved && state.atlas ? nearest({ x: event.offsetX, y: event.offsetY }) : null;
    clearPointer(event.pointerId);
    if (canvas.hasPointerCapture?.(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (hit) void focus(hit.id);
  };
  canvas.addEventListener('pointerup', (event) => { finishPointer(event); });
  canvas.addEventListener('pointercancel', (event) => { finishPointer(event, true); });
  canvas.addEventListener('lostpointercapture', (event) => { clearPointer(event.pointerId); });
  controls?.addEventListener('click', (event) => { const action = event.target.closest('button')?.dataset.mapAction; if (action === 'fit') { setUrl(null); fit(); } else if (action === 'back') { if (state.artist) { state.artist = null; showDetail(state.focus, state.edges); schedule(); } else history.back(); } else if (action === 'in') { const target = nextLodScale(state.camera.scale, state.fitScale, state.atlas.maximumScale); if (target > state.camera.scale) state.camera = zoomAtCenter(state.camera, { width: canvas.clientWidth, height: canvas.clientHeight }, target / state.camera.scale, { min: state.fitScale, max: state.atlas.maximumScale }); schedule(); } else if (action === 'out') { state.camera = zoomAtCenter(state.camera, { width: canvas.clientWidth, height: canvas.clientHeight }, 1 / 1.5, { min: state.fitScale, max: state.atlas.maximumScale }); schedule(); } else if (action === 'theme') { const root = document.documentElement; root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark'; schedule(); } });
  document.addEventListener('click', (event) => { const target = event.target.closest('[data-open-node-id]'); if (target) { event.preventDefault(); void focus(target.dataset.openNodeId); return; } const artist = event.target.closest('[data-open-artist-id]'); if (artist) { event.preventDefault(); showArtist(artist.dataset.openArtistId); return; } if (event.target.closest('[data-map-action="genre-detail"]') && state.focus) { event.preventDefault(); state.artist = null; showDetail(state.focus, state.edges); schedule(); } });
  query?.addEventListener('keydown', (event) => { if (event.key !== 'Enter' || !state.atlas) return; const id = state.atlas.aliases.get(query.value.trim().toLowerCase()); if (!id) return; event.preventDefault(); void focus(id); });
  window.addEventListener('popstate', () => { const id = canonicalizeFocusUrl(); if (id) void focus(id, false); else fit(); });
  const initialFocus = publicId(canvas.dataset.focus) || canonicalizeFocusUrl();
  fetch(endpoint).then((response) => response.json()).then((payload) => {
    state.atlas = normaliseAtlasPayload(payload);
    state.viewport = { width: canvas.clientWidth, height: canvas.clientHeight }; fit(); if (initialFocus) void focus(initialFocus, false);
  }).catch(() => { const error = document.createElement('p'); error.className = 'map-error'; error.textContent = 'Map data is unavailable.'; canvas.after(error); });
}
