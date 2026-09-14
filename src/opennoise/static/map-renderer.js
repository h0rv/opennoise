/* Static atlas viewport: supplied coordinates only, no graph simulation. */
import {
  boundsForNodes,
  clamp,
  declutterLabels,
  fitCamera,
  focusCamera,
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
  const neighborUrl = canvas.dataset.neighborsUrl;
  const state = { atlas: null, camera: null, fitScale: 1, viewport: { width: 0, height: 0 }, focus: null, edges: [], frame: 0, drag: null, moved: false, request: 0, labelWidths: new Map() };
  const palette = () => { const css = getComputedStyle(document.documentElement); return Object.fromEntries(['canvas', 'node', 'ink', 'edge', 'focus'].map((key) => [key, css.getPropertyValue(`--${key}`).trim()])); };
  const point = (node) => ({ x: state.camera.x + node.x * state.camera.scale, y: state.camera.y + node.y * state.camera.scale });
  const level = () => levelForScale(state.camera.scale, state.fitScale);
  const visible = (node) => { const screen = point(node); return screen.x >= -8 && screen.y >= -8 && screen.x <= state.viewport.width + 8 && screen.y <= state.viewport.height + 8; };
  const schedule = () => { if (!state.frame) state.frame = requestAnimationFrame(draw); };
  const fit = () => {
    if (!state.atlas || !state.viewport.width || !state.viewport.height) return;
    // Use a slightly fuller initial frame so the overview remains legible in
    // the fixed desktop viewport while retaining its centered camera.
    state.camera = fitCamera(state.atlas.initialCamera, state.viewport, 1.05);
    state.fitScale = state.camera.scale;
    state.focus = null; state.edges = [];
    if (back) back.hidden = true;
    if (detail) detail.hidden = true;
    schedule();
  };
  const headings = () => state.atlas.regions.length
    ? state.atlas.regions.filter((region) => (region.overview_visible ?? true) === true && typeof region.title === 'string' && Number.isFinite(region.x) && Number.isFinite(region.y))
    : state.atlas.labels[0].map((id) => state.atlas.byId.get(id)).filter(Boolean).map((node) => ({ title: node.name, x: node.x, y: node.y }));
  const drawLabel = (context, name, placement, colors) => {
    const width = placement.width ?? context.measureText(name).width;
    const viewportWidth = canvas.clientWidth || context.canvas.width;
    const x = clamp(placement.x, 4, Math.max(4, viewportWidth - width - 4));
    context.fillStyle = colors.ink; context.strokeStyle = colors.canvas; context.lineWidth = 4;
    context.strokeText(name, x, placement.y); context.fillText(name, x, placement.y);
  };
  const draw = () => {
    state.frame = 0;
    if (!state.atlas || !state.camera) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const context = canvas.getContext('2d'); if (!context) return;
    if (canvas.width !== Math.round(state.viewport.width * ratio) || canvas.height !== Math.round(state.viewport.height * ratio)) { canvas.width = Math.round(state.viewport.width * ratio); canvas.height = Math.round(state.viewport.height * ratio); }
    context.setTransform(ratio, 0, 0, ratio, 0, 0); context.clearRect(0, 0, state.viewport.width, state.viewport.height);
    const colors = palette(); const lod = level(); context.font = lod === 0 ? '600 15px ui-sans-serif, system-ui, sans-serif' : '13px ui-sans-serif, system-ui, sans-serif';
    const measureLabel = (name) => {
      const key = `${context.font}\u0000${name}`;
      const cached = state.labelWidths.get(key);
      if (cached !== undefined) return cached;
      const width = context.measureText(name).width;
      state.labelWidths.set(key, width);
      return width;
    };
    if (lod === 0) {
      const regions = headings().map((region, index) => ({
        id: `region:${region.community_id ?? index}`,
        text: region.title,
        screen: { x: state.camera.x + region.x * state.camera.scale, y: state.camera.y + region.y * state.camera.scale },
        priority: index,
      }));
      const visibleRegions = declutterLabels(
        regions,
        state.viewport,
        measureLabel,
        { maximum: 35, height: 18, padding: 4, margin: 40 },
      );
      for (const region of visibleRegions) {
        context.fillStyle = colors.node; context.beginPath(); context.arc(region.screen.x, region.screen.y, 3.5, 0, Math.PI * 2); context.fill();
        drawLabel(context, region.text, region.placement, colors);
      }
      return;
    }
    for (const edge of state.edges) { const left = state.atlas.byId.get(edge.source); const right = state.atlas.byId.get(edge.target); if (!left || !right) continue; const start = point(left); const end = point(right); context.strokeStyle = colors.edge; context.globalAlpha = .55; context.lineWidth = 1.5; context.beginPath(); context.moveTo(start.x, start.y); context.lineTo(end.x, end.y); context.stroke(); }
    const requiredIds = state.edges.flatMap((edge) => [edge.source, edge.target]);
    const selectedLabels = visibleNodeLabels(
      state.atlas,
      lod,
      state.viewport,
      point,
      measureLabel,
      {
        maximum: [45, 96, 210, 420][lod],
        focusId: state.focus,
        requiredIds,
        camera: state.camera,
        height: 16,
        padding: 3,
        margin: 160,
      },
    );
    const shown = new Set(selectedLabels.map((item) => item.id));
    const required = new Set(requiredIds);
    // Keep the map's hot path to three Canvas fill calls. The old per-node
    // beginPath/fill pair made dense LOD3 frames needlessly expensive while
    // producing the same circles and alpha hierarchy.
    const faintPath = new Path2D();
    const labelPath = new Path2D();
    const focusPath = new Path2D();
    for (const node of state.atlas.nodes) {
      if (!visible(node) || (node.lod > lod && node.id !== state.focus && !required.has(node.id))) continue;
      const screen = point(node);
      if (node.id === state.focus) appendCirclePath(focusPath, screen.x, screen.y, 3.2);
      else if (shown.has(node.id)) appendCirclePath(labelPath, screen.x, screen.y, 3.2);
      else appendCirclePath(faintPath, screen.x, screen.y, 1.35);
    }
    context.globalAlpha = .4; context.fillStyle = colors.node; context.fill(faintPath);
    context.globalAlpha = 1; context.fillStyle = colors.node; context.fill(labelPath);
    context.fillStyle = colors.focus; context.fill(focusPath);
    context.globalAlpha = 1;
    for (const item of selectedLabels) if (visible(state.atlas.byId.get(item.id))) {
      if (item.placement.callout) {
        context.strokeStyle = colors.edge; context.globalAlpha = .35; context.lineWidth = 1;
        context.beginPath(); context.moveTo(item.screen.x, item.screen.y); context.lineTo(item.placement.x, item.placement.y - 4); context.stroke();
        context.globalAlpha = 1;
      }
      drawLabel(context, item.text, { ...item.placement, width: item.width }, colors);
    }
  };
  const setUrl = (id) => { const url = new URL(window.location.href); if (id) url.searchParams.set('open_focus', id); else url.searchParams.delete('open_focus'); history.pushState({ opennoiseFocus: id }, '', url); };
  const showDetail = (id, neighborhood) => {
    if (!detail) return;
    detail.replaceChildren();
    const heading = document.createElement('h2'); heading.textContent = state.atlas.byId.get(id).name; detail.append(heading);
    const peers = Array.isArray(neighborhood?.nodes) ? neighborhood.nodes.filter((node) => node.node_id !== id) : [];
    if (peers.length) { const list = document.createElement('ul'); for (const peer of peers) { const item = document.createElement('li'); const link = document.createElement('a'); link.href = `?open_focus=${encodeURIComponent(peer.node_id)}`; link.dataset.openNodeId = peer.node_id; link.textContent = peer.name; item.append(link); list.append(item); } detail.append(list); }
    if (canvas.dataset.artistUrl) { const artists = document.createElement('a'); artists.className = 'artist-link'; artists.href = `${canvas.dataset.artistUrl}${encodeURIComponent(id)}`; artists.textContent = 'Artist evidence'; detail.append(artists); }
    detail.hidden = false;
  };
  const focus = async (id, push = true) => {
    if (!state.atlas?.byId.has(id)) return;
    state.focus = id; state.edges = []; if (back) back.hidden = false; if (push) setUrl(id);
    const request = ++state.request;
    let neighborhood = null;
    if (neighborUrl) try { const response = await fetch(`${neighborUrl}${encodeURIComponent(id)}`); neighborhood = await response.json(); if (request === state.request) state.edges = Array.isArray(neighborhood.edges) ? neighborhood.edges : []; } catch { /* a point remains focusable when detail is unavailable */ }
    if (request !== state.request) return;
    const ids = [id, ...state.edges.flatMap((edge) => [edge.source, edge.target])];
    const nodes = [...new Set(ids)].map((key) => state.atlas.byId.get(key)).filter(Boolean);
    const focusBounds = boundsForNodes(nodes, state.atlas.initialCamera);
    // Focused neighborhoods must use a detail LOD so their verified edges are
    // visible. A broad neighborhood can otherwise fit at the overview scale.
    state.camera = focusCamera(
      focusBounds,
      state.viewport,
      state.fitScale * 1.5,
      state.fitScale * 32,
      .72,
      { x: state.atlas.byId.get(id).x, y: state.atlas.byId.get(id).y },
    );
    showDetail(id, neighborhood);
    schedule();
  };
  const nearest = (cursor) => { let hit = null; let distance = 15; for (const node of state.atlas.nodes) { const screen = point(node); const next = Math.hypot(screen.x - cursor.x, screen.y - cursor.y); if (next < distance) { hit = node; distance = next; } } return hit; };
  new ResizeObserver(() => { const viewport = { width: canvas.clientWidth, height: canvas.clientHeight }; if (!viewport.width || !viewport.height) return; const center = state.camera ? { x: (viewport.width / 2 - state.camera.x) / state.camera.scale, y: (viewport.height / 2 - state.camera.y) / state.camera.scale } : null; state.viewport = viewport; if (!state.camera) fit(); else { state.camera.x = viewport.width / 2 - center.x * state.camera.scale; state.camera.y = viewport.height / 2 - center.y * state.camera.scale; schedule(); } }).observe(canvas);
  canvas.addEventListener('wheel', (event) => { event.preventDefault(); if (!state.camera) return; state.camera = zoomAt(state.camera, { x: event.offsetX, y: event.offsetY }, event.deltaY < 0 ? 1.25 : .8, { min: state.fitScale, max: state.fitScale * 64 }); schedule(); }, { passive: false });
  canvas.addEventListener('pointerdown', (event) => { canvas.setPointerCapture(event.pointerId); state.drag = { x: event.clientX, y: event.clientY }; state.moved = false; });
  canvas.addEventListener('pointermove', (event) => { if (!state.drag || !state.camera) return; const dx = event.clientX - state.drag.x; const dy = event.clientY - state.drag.y; state.drag = { x: event.clientX, y: event.clientY }; if (Math.hypot(dx, dy) > 2) state.moved = true; state.camera.x += dx; state.camera.y += dy; schedule(); });
  canvas.addEventListener('pointerup', (event) => { const hit = !state.moved && state.atlas ? nearest({ x: event.offsetX, y: event.offsetY }) : null; state.drag = null; if (hit) void focus(hit.id); });
  canvas.addEventListener('pointercancel', () => { state.drag = null; });
  controls?.addEventListener('click', (event) => { const action = event.target.closest('button')?.dataset.mapAction; if (action === 'fit') { setUrl(null); fit(); } else if (action === 'back') history.back(); else if (action === 'in' || action === 'out') { state.camera = zoomAtCenter(state.camera, { width: canvas.clientWidth, height: canvas.clientHeight }, action === 'in' ? 1.5 : 1 / 1.5, { min: state.fitScale, max: state.fitScale * 64 }); schedule(); } else if (action === 'theme') { const root = document.documentElement; root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark'; schedule(); } });
  document.addEventListener('click', (event) => { const target = event.target.closest('[data-open-node-id]'); if (!target) return; event.preventDefault(); void focus(target.dataset.openNodeId); });
  query?.addEventListener('keydown', (event) => { if (event.key !== 'Enter' || !state.atlas) return; const id = state.atlas.aliases.get(query.value.trim().toLowerCase()); if (!id) return; event.preventDefault(); void focus(id); });
  window.addEventListener('popstate', () => { const id = new URL(window.location.href).searchParams.get('open_focus'); if (id) void focus(id, false); else fit(); });
  fetch(endpoint).then((response) => response.json()).then((payload) => { state.atlas = normaliseAtlasPayload(payload); state.viewport = { width: canvas.clientWidth, height: canvas.clientHeight }; fit(); const initial = canvas.dataset.focus || new URL(window.location.href).searchParams.get('open_focus'); if (initial) void focus(initial, false); }).catch(() => { const error = document.createElement('p'); error.className = 'map-error'; error.textContent = 'Map data is unavailable.'; canvas.after(error); });
}
