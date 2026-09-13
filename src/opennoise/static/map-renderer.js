/* Static atlas viewport: supplied coordinates only, no graph simulation. */
import { boundsForNodes, clamp, fitCamera, levelForScale, normaliseAtlasPayload, zoomAt } from './map-atlas.mjs';

const canvas = document.querySelector('#semantic-map');

if (canvas instanceof HTMLCanvasElement) {
  const controls = document.querySelector('#map-controls');
  const back = controls?.querySelector('[data-map-action="back"]');
  const detail = document.querySelector('#map-detail');
  const query = document.querySelector('#query');
  const endpoint = canvas.dataset.mapUrl;
  const neighborUrl = canvas.dataset.neighborsUrl;
  const state = { atlas: null, camera: null, fitScale: 1, viewport: { width: 0, height: 0 }, focus: null, edges: [], frame: 0, drag: null, moved: false, request: 0 };
  const palette = () => { const css = getComputedStyle(document.documentElement); return Object.fromEntries(['canvas', 'node', 'ink', 'edge', 'focus'].map((key) => [key, css.getPropertyValue(`--${key}`).trim()])); };
  const point = (node) => ({ x: state.camera.x + node.x * state.camera.scale, y: state.camera.y + node.y * state.camera.scale });
  const level = () => levelForScale(state.camera.scale, state.fitScale);
  const visible = (node) => { const screen = point(node); return screen.x >= -8 && screen.y >= -8 && screen.x <= state.viewport.width + 8 && screen.y <= state.viewport.height + 8; };
  const schedule = () => { if (!state.frame) state.frame = requestAnimationFrame(draw); };
  const fit = () => {
    if (!state.atlas || !state.viewport.width || !state.viewport.height) return;
    state.camera = fitCamera(state.atlas.initialCamera, state.viewport);
    state.fitScale = state.camera.scale;
    state.focus = null; state.edges = [];
    if (back) back.hidden = true;
    if (detail) detail.hidden = true;
    schedule();
  };
  const headings = () => state.atlas.regions.length
    ? state.atlas.regions.filter((region) => typeof region.title === 'string' && Number.isFinite(region.x) && Number.isFinite(region.y))
    : state.atlas.labels[0].map((id) => state.atlas.byId.get(id)).filter(Boolean).map((node) => ({ title: node.name, x: node.x, y: node.y }));
  const label = (context, name, screen, colors) => {
    context.fillStyle = colors.ink; context.strokeStyle = colors.canvas; context.lineWidth = 4;
    context.strokeText(name, screen.x + 6, screen.y - 6); context.fillText(name, screen.x + 6, screen.y - 6);
  };
  const draw = () => {
    state.frame = 0;
    if (!state.atlas || !state.camera) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const context = canvas.getContext('2d'); if (!context) return;
    if (canvas.width !== Math.round(state.viewport.width * ratio) || canvas.height !== Math.round(state.viewport.height * ratio)) { canvas.width = Math.round(state.viewport.width * ratio); canvas.height = Math.round(state.viewport.height * ratio); }
    context.setTransform(ratio, 0, 0, ratio, 0, 0); context.clearRect(0, 0, state.viewport.width, state.viewport.height);
    const colors = palette(); const lod = level(); context.font = lod === 0 ? '600 15px ui-sans-serif, system-ui, sans-serif' : '13px ui-sans-serif, system-ui, sans-serif';
    if (lod === 0) {
      for (const region of headings()) { const screen = { x: state.camera.x + region.x * state.camera.scale, y: state.camera.y + region.y * state.camera.scale }; if (screen.x < -80 || screen.y < -20 || screen.x > state.viewport.width + 80 || screen.y > state.viewport.height + 20) continue; context.fillStyle = colors.node; context.beginPath(); context.arc(screen.x, screen.y, 3.5, 0, Math.PI * 2); context.fill(); label(context, region.title, screen, colors); }
      return;
    }
    for (const edge of state.edges) { const left = state.atlas.byId.get(edge.source); const right = state.atlas.byId.get(edge.target); if (!left || !right) continue; const start = point(left); const end = point(right); context.strokeStyle = colors.edge; context.globalAlpha = .55; context.lineWidth = 1.5; context.beginPath(); context.moveTo(start.x, start.y); context.lineTo(end.x, end.y); context.stroke(); }
    const shown = new Set(state.atlas.labels[lod]); if (state.focus) shown.add(state.focus);
    for (const node of state.atlas.nodes) { if (!visible(node) || (node.lod > lod && node.id !== state.focus)) continue; const screen = point(node); context.globalAlpha = shown.has(node.id) ? 1 : .4; context.fillStyle = node.id === state.focus ? colors.focus : colors.node; context.beginPath(); context.arc(screen.x, screen.y, shown.has(node.id) ? 3.2 : 1.35, 0, Math.PI * 2); context.fill(); }
    context.globalAlpha = 1;
    for (const id of shown) { const node = state.atlas.byId.get(id); if (node && visible(node)) label(context, node.name, point(node), colors); }
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
    const camera = fitCamera(boundsForNodes(nodes, state.atlas.initialCamera), state.viewport, .72);
    state.camera = { ...camera, scale: clamp(camera.scale, state.fitScale, state.fitScale * 32) };
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
  controls?.addEventListener('click', (event) => { const action = event.target.closest('button')?.dataset.mapAction; if (action === 'fit') { setUrl(null); fit(); } else if (action === 'back') history.back(); else if (action === 'in' || action === 'out') { state.camera = zoomAt(state.camera, { x: state.viewport.width / 2, y: state.viewport.height / 2 }, action === 'in' ? 1.5 : 1 / 1.5, { min: state.fitScale, max: state.fitScale * 64 }); schedule(); } else if (action === 'theme') { const root = document.documentElement; root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark'; schedule(); } });
  document.addEventListener('click', (event) => { const target = event.target.closest('[data-open-node-id]'); if (!target) return; event.preventDefault(); void focus(target.dataset.openNodeId); });
  query?.addEventListener('keydown', (event) => { if (event.key !== 'Enter' || !state.atlas) return; const id = state.atlas.aliases.get(query.value.trim().toLocaleLowerCase()); if (!id) return; event.preventDefault(); void focus(id); });
  window.addEventListener('popstate', () => { const id = new URL(window.location.href).searchParams.get('open_focus'); if (id) void focus(id, false); else fit(); });
  fetch(endpoint).then((response) => response.json()).then((payload) => { state.atlas = normaliseAtlasPayload(payload); state.viewport = { width: canvas.clientWidth, height: canvas.clientHeight }; fit(); const initial = canvas.dataset.focus || new URL(window.location.href).searchParams.get('open_focus'); if (initial) void focus(initial, false); }).catch(() => { const error = document.createElement('p'); error.className = 'map-error'; error.textContent = 'Map data is unavailable.'; canvas.after(error); });
}
