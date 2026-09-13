/* Receipt-bound scatter-map viewport. It draws only supplied geometry. */
(() => {
  const canvas = document.querySelector('#semantic-map');
  if (!canvas) return;
  const controls = document.querySelector('#map-controls');
  const detail = document.querySelector('#map-detail');
  const search = document.querySelector('#query');
  const stage = canvas.parentElement;
  const readColor = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const pointRadius = 2.1;
  const labelCaps = [45, 96, 210, 420];
  let data, state, pixels, frame = 0, drag, moved = false, focusedEdges = [], lookup, pointers = new Map(), pinchDistance = 0, measureContext, textWidths = new Map();

  const size = () => ({ width: canvas.clientWidth, height: canvas.clientHeight });
  const nodeMap = () => lookup;
  const transform = (node) => ({ x: state.x + node.x * state.scale, y: state.y + node.y * state.scale });
  const level = () => clamp(Math.floor(Math.log2(state.scale / state.fitScale) + 0.5), 0, 3);
  const visible = (node, margin = 8) => {
    const point = transform(node), viewport = state.viewport;
    return point.x >= -margin && point.y >= -margin && point.x <= viewport.width + margin && point.y <= viewport.height + margin;
  };
  const schedule = () => { if (!frame) frame = requestAnimationFrame(render); };
  const fit = () => {
    const viewport = size(), camera = data.initial_camera, minX = camera.x0, minY = camera.y0, maxX = camera.x1, maxY = camera.y1;
    const scale = Math.min(viewport.width / (maxX - minX), viewport.height / (maxY - minY));
    state.fitScale = Math.max(scale, .001);
    state.scale = state.fitScale;
    state.x = viewport.width / 2 - ((minX + maxX) / 2) * state.scale;
    state.y = viewport.height / 2 - ((minY + maxY) / 2) * state.scale;
    schedule();
  };
  const labels = () => {
    const labelSet = data.labels[Math.min(level(), data.labels.length - 1)] || { ids: [] };
    const ids = new Set(labelSet.ids);
    const lookup = nodeMap(), occupied = new Map(), shown = [];
    const canvasRect = canvas.getBoundingClientRect();
    for (const element of [search, controls, detail]) {
      if (!element || element.hidden) continue;
      const rect = element.getBoundingClientRect(), box = [rect.left - canvasRect.left, rect.top - canvasRect.top, rect.right - canvasRect.left, rect.bottom - canvasRect.top];
      for (let x = Math.floor(box[0] / 32); x <= Math.floor(box[2] / 32); x += 1) for (let y = Math.floor(box[1] / 32); y <= Math.floor(box[3] / 32); y += 1) occupied.set(`${x}:${y}`, [box]);
    }
    measureContext ||= canvas.getContext('2d'); measureContext.font = '12px ui-sans-serif, system-ui, sans-serif';
    for (const id of labelSet.ids) {
      const node = lookup.get(id);
      if (!node || !visible(node)) continue;
      const width = textWidths.get(node.id) ?? Math.min(176, measureContext.measureText(node.name).width + 12);
      textWidths.set(node.id, width);
      const p = transform(node);
      const box = [p.x + 5, p.y - 10, p.x + width, p.y + 8], cells = [];
      for (let x = Math.floor(box[0] / 32); x <= Math.floor(box[2] / 32); x += 1) for (let y = Math.floor(box[1] / 32); y <= Math.floor(box[3] / 32); y += 1) cells.push(`${x}:${y}`);
      const overlaps = cells.some((cell) => (occupied.get(cell) || []).some((other) => box[0] < other[2] && box[2] > other[0] && box[1] < other[3] && box[3] > other[1]));
      if (!overlaps) {
        for (const cell of cells) occupied.set(cell, [...(occupied.get(cell) || []), box]);
        shown.push(node); if (shown.length >= labelCaps[level()]) break;
      }
    }
    const focus = state.focus && lookup.get(state.focus);
    if (focus && !ids.has(focus.id)) shown.push(focus);
    return shown;
  };
  const render = () => {
    frame = 0;
    const viewport = size(), dpr = Math.min(window.devicePixelRatio || 1, 2); state.viewport = viewport;
    if (canvas.width !== Math.round(viewport.width * dpr) || canvas.height !== Math.round(viewport.height * dpr)) {
      canvas.width = Math.round(viewport.width * dpr); canvas.height = Math.round(viewport.height * dpr);
    }
    const context = canvas.getContext('2d');
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, viewport.width, viewport.height);
    const map = nodeMap(), focusIDs = new Set([state.focus, ...focusedEdges.flatMap((edge) => [edge.source, edge.target])]), nodes = data.nodes.filter((node) => (node.lod <= level() || focusIDs.has(node.id)) && visible(node));
    context.strokeStyle = readColor('--similarity') || '#b6a989'; context.globalAlpha = .62; context.lineWidth = 1;
    for (const edge of focusedEdges) {
      const left = map.get(edge.source), right = map.get(edge.target);
      if (!left || !right) continue;
      const a = transform(left), b = transform(right), margin = 20;
      if (a.x < -margin || a.x > viewport.width + margin || a.y < -margin || a.y > viewport.height + margin || b.x < -margin || b.x > viewport.width + margin || b.y < -margin || b.y > viewport.height + margin) continue;
      context.beginPath(); context.moveTo(a.x, a.y); context.lineTo(b.x, b.y); context.stroke();
    }
    context.globalAlpha = 1; context.fillStyle = readColor('--node') || '#687169';
    for (const node of nodes) {
      const p = transform(node); context.beginPath(); context.arc(p.x, p.y, node.id === state.focus ? 4.8 : pointRadius, 0, Math.PI * 2); context.fill();
    }
    context.font = '12px ui-sans-serif, system-ui, sans-serif'; context.textBaseline = 'middle';
    const shownLabels = labels();
    for (const node of shownLabels) {
      const p = transform(node); context.lineWidth = 3; context.strokeStyle = readColor('--canvas') || '#f6f6f2'; context.strokeText(node.name, p.x + 6, p.y); context.fillStyle = readColor('--ink') || '#23231f'; context.fillText(node.name, p.x + 6, p.y);
    }
    const back = controls?.querySelector('[data-map-action="back"]'); if (back) back.hidden = !state.focus;
    pixels = nodes;
  };
  const nearby = (x, y) => {
    let hit, distance = 15 * 15;
    for (const node of pixels || []) { const p = transform(node), next = (p.x - x) ** 2 + (p.y - y) ** 2; if (next < distance) { hit = node; distance = next; } }
    return hit;
  };
  const camera = () => ({ x: state.x, y: state.y, scale: state.scale });
  const setUrl = (id, push, priorCamera, priorFocus) => {
    const url = new URL(location.href); if (id) { url.searchParams.set('view', 'open'); url.searchParams.set('open_focus', id); } else url.searchParams.delete('open_focus');
    if (push) { history.replaceState({ focus: priorFocus || null, camera: priorCamera || camera() }, '', location.href); history.pushState({ focus: id, camera: camera() }, '', url); }
  };
  const showDetail = (node, response) => {
    detail.hidden = false; detail.replaceChildren();
    const heading = document.createElement('h2'); heading.textContent = node.name; detail.append(heading);
    if (canvas.dataset.artistUrl) { const artist = document.createElement('a'); artist.href = `${canvas.dataset.artistUrl}${encodeURIComponent(node.id)}`; artist.textContent = 'Artist evidence'; artist.className = 'artist-link'; detail.append(artist); }
    const peers = response.nodes.filter((item) => item.node_id !== node.id);
    if (peers.length) {
      const list = document.createElement('ul');
      for (const peer of peers.slice(0, 12)) { const item = document.createElement('li'), link = document.createElement('a'); link.href = `?view=open&open_focus=${encodeURIComponent(peer.node_id)}`; link.dataset.openNodeId = peer.node_id; link.textContent = peer.name; item.append(link); list.append(item); }
      detail.append(list);
    }
  };
  const focus = async (id, push = false, restoredCamera) => {
    const node = nodeMap().get(id); if (!node) return;
    const priorCamera = camera(), priorFocus = state.focus; state.focus = id;
    if (restoredCamera) { state.x = restoredCamera.x; state.y = restoredCamera.y; state.scale = restoredCamera.scale; } else { const viewport = size(); state.scale = Math.max(state.scale, state.fitScale * 2.1); state.x = viewport.width / 2 - node.x * state.scale; state.y = viewport.height / 2 - node.y * state.scale; }
    if (push) setUrl(id, true, priorCamera, priorFocus); schedule();
    const response = canvas.dataset.neighborsUrl
      ? await fetch(`${canvas.dataset.neighborsUrl}${encodeURIComponent(id)}`).then((result) => result.ok ? result.json() : null).catch(() => null)
      : { nodes: data.nodes.filter((candidate) => candidate.id === id || (data.peers || []).some((edge) => (edge.source === id && edge.target === candidate.id) || (edge.target === id && edge.source === candidate.id))).map((candidate) => ({ node_id: candidate.id, name: candidate.name })), edges: (data.peers || []).filter((edge) => edge.source === id || edge.target === id).slice(0, 12) };
    if (!response || state.focus !== id) return;
    focusedEdges = (response.edges || []).slice(0, 12); showDetail(node, response); schedule();
  };
  const clearFocus = (push = false, restoredCamera) => { const priorCamera = camera(), priorFocus = state.focus; state.focus = null; focusedEdges = []; detail.hidden = true; if (restoredCamera) { state.x = restoredCamera.x; state.y = restoredCamera.y; state.scale = restoredCamera.scale; schedule(); } else fit(); if (push) setUrl(null, true, priorCamera, priorFocus); };
  const zoom = (factor, x, y) => { const next = clamp(state.scale * factor, state.fitScale * .7, state.fitScale * 30); state.x = x - (x - state.x) * next / state.scale; state.y = y - (y - state.y) * next / state.scale; state.scale = next; schedule(); };
  const setTheme = () => { const root = document.documentElement, dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; root.dataset.theme = dark ? 'light' : 'dark'; schedule(); };
  canvas.addEventListener('wheel', (event) => { event.preventDefault(); const rect = canvas.getBoundingClientRect(), factor = Math.pow(1.18, Math.max(1, Math.abs(event.deltaY) / 120)); zoom(event.deltaY < 0 ? factor : 1 / factor, event.clientX - rect.left, event.clientY - rect.top); }, { passive: false });
  canvas.addEventListener('pointerdown', (event) => { canvas.setPointerCapture(event.pointerId); pointers.set(event.pointerId, [event.clientX, event.clientY]); drag = [event.clientX, event.clientY]; moved = false; if (pointers.size === 2) { const pair = [...pointers.values()]; pinchDistance = Math.hypot(pair[0][0] - pair[1][0], pair[0][1] - pair[1][1]); } });
  canvas.addEventListener('pointermove', (event) => { if (!pointers.has(event.pointerId)) return; pointers.set(event.pointerId, [event.clientX, event.clientY]); if (pointers.size === 2) { const pair = [...pointers.values()], now = Math.hypot(pair[0][0] - pair[1][0], pair[0][1] - pair[1][1]); if (pinchDistance) zoom(now / pinchDistance, (pair[0][0] + pair[1][0]) / 2, (pair[0][1] + pair[1][1]) / 2); pinchDistance = now; return; } if (!drag) return; const dx = event.clientX - drag[0], dy = event.clientY - drag[1]; moved ||= Math.abs(dx) + Math.abs(dy) > 3; state.x += dx; state.y += dy; drag = [event.clientX, event.clientY]; schedule(); });
  const endPointer = (event) => { const wasSinglePointer = pointers.size === 1; pointers.delete(event.pointerId); pinchDistance = 0; if (!drag) return; const rect = canvas.getBoundingClientRect(), node = wasSinglePointer && !moved && nearby(event.clientX - rect.left, event.clientY - rect.top); drag = undefined; if (node) void focus(node.id, true); };
  canvas.addEventListener('pointerup', endPointer); canvas.addEventListener('pointercancel', endPointer);
  controls?.addEventListener('click', (event) => { const action = event.target.closest('[data-map-action]')?.dataset.mapAction; if (action === 'fit') clearFocus(true); if (action === 'back') { if (history.state?.focus) history.back(); else clearFocus(false); } if (action === 'in') { const viewport = size(); zoom(1.35, viewport.width / 2, viewport.height / 2); } if (action === 'out') { const viewport = size(); zoom(1 / 1.35, viewport.width / 2, viewport.height / 2); } if (action === 'theme') setTheme(); });
  detail?.addEventListener('click', (event) => { const id = event.target.closest('[data-open-node-id]')?.dataset.openNodeId; if (id) { event.preventDefault(); void focus(id, true); } });
  stage?.addEventListener('click', (event) => { const id = event.target.closest('[data-open-node-id]')?.dataset.openNodeId; if (id) { event.preventDefault(); void focus(id, true); } });
  document.querySelector('#results')?.addEventListener('click', (event) => { const id = event.target.closest('[data-open-node-id]')?.dataset.openNodeId; if (id) { event.preventDefault(); void focus(id, true); } });
  window.addEventListener('resize', () => { if (data) fit(); }); window.addEventListener('popstate', () => { const id = new URL(location.href).searchParams.get('open_focus'), restoredCamera = history.state?.camera; if (id) void focus(id, false, restoredCamera); else clearFocus(false, restoredCamera); });
  canvas.tabIndex = 0;
  canvas.addEventListener('keydown', (event) => { if (!data || !['ArrowLeft', 'ArrowRight', 'Enter'].includes(event.key)) return; event.preventDefault(); const choices = data.labels[0]?.ids || []; if (event.key === 'Enter' && state.focus) { void focus(state.focus, true); return; } const index = state.focus ? choices.indexOf(state.focus) : event.key === 'ArrowLeft' ? 0 : -1; const id = event.key === 'ArrowLeft' ? choices[(index + choices.length - 1) % choices.length] : choices[(index + 1) % choices.length]; if (id) void focus(id, true); });
  search?.addEventListener('keydown', (event) => { if (event.key !== 'Enter' || !data) return; const target = new Map(data.aliases.map((alias) => [alias.term, alias.target])).get(search.value.trim().toLowerCase()); if (target) { event.preventDefault(); void focus(target, true); } });
  fetch(canvas.dataset.mapUrl).then((response) => { if (!response.ok) throw new Error('map unavailable'); return response.json(); }).then((payload) => { data = payload; if (!data.initial_camera || !data.nodes.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y) && Number.isInteger(node.lod))) throw new Error('invalid map contract'); lookup = new Map(data.nodes.map((node) => [node.id, node])); textWidths = new Map(); state = { x: 0, y: 0, scale: 1, fitScale: 1, focus: null, viewport: size() }; fit(); const id = canvas.dataset.focus || new URL(location.href).searchParams.get('open_focus'); if (id) void focus(id); }).catch(() => { canvas.setAttribute('aria-label', 'Semantic map unavailable'); const message = document.createElement('p'); message.className = 'map-error'; message.textContent = 'Semantic map unavailable.'; stage?.append(message); });
})();
