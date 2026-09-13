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
  let data, state, pixels, frame = 0, drag, moved = false, focusedEdges = [], lookup, pointers = new Map(), pinchDistance = 0;

  const size = () => ({ width: canvas.clientWidth, height: canvas.clientHeight });
  const nodeMap = () => lookup;
  const transform = (node) => ({ x: state.x + node.x * data.display_transform.scale_x * state.scale, y: state.y + node.y * data.display_transform.scale_y * state.scale });
  const level = () => clamp(Math.floor(Math.log2(state.scale / state.fitScale) + 0.5), 0, 3);
  const visible = (node, margin = 8) => {
    const point = transform(node), viewport = state.viewport;
    return point.x >= -margin && point.y >= -margin && point.x <= viewport.width + margin && point.y <= viewport.height + margin;
  };
  const schedule = () => { if (!frame) frame = requestAnimationFrame(render); };
  const fit = () => {
    const viewport = size(), bounds = data.fit_bounds || data.bounds, minX = bounds.min_x, minY = bounds.min_y, maxX = bounds.max_x, maxY = bounds.max_y, stretchX = data.display_transform.scale_x, stretchY = data.display_transform.scale_y;
    const scale = Math.min(viewport.width * .84 / ((maxX - minX) * stretchX), viewport.height * .82 / ((maxY - minY) * stretchY));
    state.fitScale = Math.max(scale, .001);
    state.scale = state.fitScale;
    state.x = viewport.width / 2 - ((minX + maxX) / 2) * stretchX * state.scale;
    state.y = viewport.height / 2 - ((minY + maxY) / 2) * stretchY * state.scale;
    schedule();
  };
  const labels = () => {
    const labelSet = data.labels[Math.min(level(), data.labels.length - 1)] || { ids: [] };
    const ids = new Set(labelSet.ids);
    const lookup = nodeMap(), occupied = [], shown = [];
    for (const id of labelSet.ids) {
      const node = lookup.get(id);
      if (!node || !visible(node)) continue;
      const measure = canvas.getContext('2d'); measure.font = '12px ui-sans-serif, system-ui, sans-serif';
      const p = transform(node), width = Math.min(176, measure.measureText(node.name).width + 12);
      const box = [p.x + 5, p.y - 10, p.x + width, p.y + 8];
      if (!occupied.some((other) => box[0] < other[2] && box[2] > other[0] && box[1] < other[3] && box[3] > other[1])) {
        occupied.push(box); shown.push(node); if (shown.length >= labelCaps[level()]) break;
      }
    }
    const focus = state.focus && lookup.get(state.focus);
    if (focus && !ids.has(focus.id)) shown.push(focus);
    return shown;
  };
  const render = () => {
    frame = 0;
    const viewport = size(), dpr = window.devicePixelRatio || 1; state.viewport = viewport;
    if (canvas.width !== Math.round(viewport.width * dpr) || canvas.height !== Math.round(viewport.height * dpr)) {
      canvas.width = Math.round(viewport.width * dpr); canvas.height = Math.round(viewport.height * dpr);
    }
    const context = canvas.getContext('2d');
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, viewport.width, viewport.height);
    const map = nodeMap(), nodes = data.nodes.filter((node) => visible(node));
    context.strokeStyle = readColor('--similarity') || '#b6a989'; context.globalAlpha = .62; context.lineWidth = 1;
    for (const edge of focusedEdges) {
      const left = map.get(edge.source), right = map.get(edge.target);
      if (!left || !right) continue;
      const a = transform(left), b = transform(right); context.beginPath(); context.moveTo(a.x, a.y); context.lineTo(b.x, b.y); context.stroke();
    }
    context.globalAlpha = 1; context.fillStyle = readColor('--node') || '#687169';
    for (const node of nodes) {
      const p = transform(node); context.beginPath(); context.arc(p.x, p.y, node.id === state.focus ? 4.8 : pointRadius, 0, Math.PI * 2); context.fill();
    }
    context.font = '12px ui-sans-serif, system-ui, sans-serif'; context.textBaseline = 'middle';
    for (const node of labels()) {
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
  const setUrl = (id, push) => {
    const url = new URL(location.href); if (id) { url.searchParams.set('view', 'open'); url.searchParams.set('open_focus', id); } else url.searchParams.delete('open_focus');
    if (push) history.pushState({ focus: id }, '', url);
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
  const focus = async (id, push = false) => {
    const node = nodeMap().get(id); if (!node) return;
    state.focus = id; const viewport = size(); state.scale = Math.max(state.scale, state.fitScale * 2.1); state.x = viewport.width / 2 - node.x * data.display_transform.scale_x * state.scale; state.y = viewport.height / 2 - node.y * data.display_transform.scale_y * state.scale;
    if (push) setUrl(id, true); schedule();
    const response = canvas.dataset.neighborsUrl
      ? await fetch(`${canvas.dataset.neighborsUrl}${encodeURIComponent(id)}`).then((result) => result.ok ? result.json() : null).catch(() => null)
      : { nodes: data.nodes.filter((candidate) => candidate.id === id || (data.peers || []).some((edge) => (edge.source === id && edge.target === candidate.id) || (edge.target === id && edge.source === candidate.id))).map((candidate) => ({ node_id: candidate.id, name: candidate.name })), edges: (data.peers || []).filter((edge) => edge.source === id || edge.target === id).slice(0, 12) };
    if (!response || state.focus !== id) return;
    focusedEdges = (response.edges || []).slice(0, 12); showDetail(node, response); schedule();
  };
  const clearFocus = (push = false) => { state.focus = null; focusedEdges = []; detail.hidden = true; if (push) setUrl(null, true); fit(); };
  const zoom = (factor, x, y) => { const next = clamp(state.scale * factor, state.fitScale * .7, state.fitScale * 30); state.x = x - (x - state.x) * next / state.scale; state.y = y - (y - state.y) * next / state.scale; state.scale = next; schedule(); };
  const setTheme = () => { const root = document.documentElement; root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : root.dataset.theme === 'light' ? '' : 'dark'; schedule(); };
  canvas.addEventListener('wheel', (event) => { event.preventDefault(); const rect = canvas.getBoundingClientRect(); zoom(event.deltaY < 0 ? 1.18 : 1 / 1.18, event.clientX - rect.left, event.clientY - rect.top); }, { passive: false });
  canvas.addEventListener('pointerdown', (event) => { canvas.setPointerCapture(event.pointerId); pointers.set(event.pointerId, [event.clientX, event.clientY]); drag = [event.clientX, event.clientY]; moved = false; if (pointers.size === 2) { const pair = [...pointers.values()]; pinchDistance = Math.hypot(pair[0][0] - pair[1][0], pair[0][1] - pair[1][1]); } });
  canvas.addEventListener('pointermove', (event) => { if (!pointers.has(event.pointerId)) return; pointers.set(event.pointerId, [event.clientX, event.clientY]); if (pointers.size === 2) { const pair = [...pointers.values()], now = Math.hypot(pair[0][0] - pair[1][0], pair[0][1] - pair[1][1]); if (pinchDistance) zoom(now / pinchDistance, (pair[0][0] + pair[1][0]) / 2, (pair[0][1] + pair[1][1]) / 2); pinchDistance = now; return; } if (!drag) return; const dx = event.clientX - drag[0], dy = event.clientY - drag[1]; moved ||= Math.abs(dx) + Math.abs(dy) > 3; state.x += dx; state.y += dy; drag = [event.clientX, event.clientY]; schedule(); });
  const endPointer = (event) => { const wasSinglePointer = pointers.size === 1; pointers.delete(event.pointerId); pinchDistance = 0; if (!drag) return; const rect = canvas.getBoundingClientRect(), node = wasSinglePointer && !moved && nearby(event.clientX - rect.left, event.clientY - rect.top); drag = undefined; if (node) void focus(node.id, true); };
  canvas.addEventListener('pointerup', endPointer); canvas.addEventListener('pointercancel', endPointer);
  controls?.addEventListener('click', (event) => { const action = event.target.closest('[data-map-action]')?.dataset.mapAction; if (action === 'fit') clearFocus(true); if (action === 'back') { if (history.state?.focus) history.back(); else clearFocus(false); } if (action === 'in') { const viewport = size(); zoom(1.35, viewport.width / 2, viewport.height / 2); } if (action === 'out') { const viewport = size(); zoom(1 / 1.35, viewport.width / 2, viewport.height / 2); } if (action === 'theme') setTheme(); });
  detail?.addEventListener('click', (event) => { const id = event.target.closest('[data-open-node-id]')?.dataset.openNodeId; if (id) { event.preventDefault(); void focus(id, true); } });
  stage?.addEventListener('click', (event) => { const id = event.target.closest('[data-open-node-id]')?.dataset.openNodeId; if (id) { event.preventDefault(); void focus(id, true); } });
  document.querySelector('#results')?.addEventListener('click', (event) => { const id = event.target.closest('[data-open-node-id]')?.dataset.openNodeId; if (id) { event.preventDefault(); void focus(id, true); } });
  window.addEventListener('resize', () => { if (data) fit(); }); window.addEventListener('popstate', () => { const id = new URL(location.href).searchParams.get('open_focus'); if (id) void focus(id); else clearFocus(); });
  canvas.tabIndex = 0;
  canvas.addEventListener('keydown', (event) => { if (!data || !['ArrowLeft', 'ArrowRight', 'Enter'].includes(event.key)) return; event.preventDefault(); const choices = data.labels[0]?.ids || []; if (event.key === 'Enter' && state.focus) { void focus(state.focus, true); return; } const index = state.focus ? choices.indexOf(state.focus) : event.key === 'ArrowLeft' ? 0 : -1; const id = event.key === 'ArrowLeft' ? choices[(index + choices.length - 1) % choices.length] : choices[(index + 1) % choices.length]; if (id) void focus(id, true); });
  search?.addEventListener('keydown', (event) => { if (event.key !== 'Enter' || !data) return; const target = new Map(data.aliases.map((alias) => [alias.term, alias.target])).get(search.value.trim().toLowerCase()); if (target) { event.preventDefault(); void focus(target, true); } });
  fetch(canvas.dataset.mapUrl).then((response) => { if (!response.ok) throw new Error('map unavailable'); return response.json(); }).then((payload) => { data = payload; data.display_transform ||= { scale_x: 1, scale_y: 1 }; lookup = new Map(data.nodes.map((node) => [node.id, node])); state = { x: 0, y: 0, scale: 1, fitScale: 1, focus: null, viewport: size() }; fit(); const id = canvas.dataset.focus || new URL(location.href).searchParams.get('open_focus'); if (id) void focus(id); }).catch(() => { canvas.setAttribute('aria-label', 'Semantic map unavailable'); const message = document.createElement('p'); message.className = 'map-error'; message.textContent = 'Semantic map unavailable.'; stage?.append(message); });
})();
