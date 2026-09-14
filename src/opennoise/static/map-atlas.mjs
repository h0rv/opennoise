/** Pure atlas parsing and camera maths shared by the Canvas renderer and Node tests. */

const LEVEL_COUNT = 4;

export function clamp(value, lower, upper) {
  return Math.max(lower, Math.min(upper, value));
}

function finiteNumber(value, label) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TypeError(`${label} must be a finite number`);
  }
  return value;
}

export function normaliseBounds(value, label = 'bounds') {
  if (!value || typeof value !== 'object') throw new TypeError(`${label} is required`);
  const x0 = finiteNumber(value.x0, `${label}.x0`);
  const y0 = finiteNumber(value.y0, `${label}.y0`);
  const x1 = finiteNumber(value.x1, `${label}.x1`);
  const y1 = finiteNumber(value.y1, `${label}.y1`);
  if (!(x1 > x0 && y1 > y0)) throw new RangeError(`${label} must have positive area`);
  return { x0, y0, x1, y1 };
}

function normaliseNode(value) {
  if (!value || typeof value !== 'object' || typeof value.id !== 'string' || !value.id) {
    throw new TypeError('atlas node must have an id');
  }
  if (typeof value.name !== 'string' || !value.name) throw new TypeError('atlas node must have a name');
  const lod = Number.isInteger(value.lod) ? clamp(value.lod, 0, LEVEL_COUNT - 1) : 0;
  return {
    id: value.id,
    name: value.name,
    x: finiteNumber(value.x, `node ${value.id}.x`),
    y: finiteNumber(value.y, `node ${value.id}.y`),
    lod,
    importance: typeof value.importance === 'number' && Number.isFinite(value.importance)
      ? value.importance
      : 0,
    labelPriority: Number.isInteger(value.label_priority) ? value.label_priority : null,
    parentId: typeof value.parent_id === 'string'
      ? value.parent_id
      : (typeof value.display_parent_id === 'string' ? value.display_parent_id : null),
    regionId: typeof value.region_id === 'string' ? value.region_id : null,
    communityId: Number.isInteger(value.community_id) ? value.community_id : null,
    hierarchyDepth: Number.isInteger(value.hierarchy_depth) ? Math.max(0, value.hierarchy_depth) : 0,
    hierarchyRootId: typeof value.hierarchy_root_id === 'string' ? value.hierarchy_root_id : null,
    artists: Array.isArray(value.artists) ? value.artists : [],
  };
}

function normaliseLabelSets(value, nodeIds) {
  const raw = Array.isArray(value) ? value : [];
  const byLevel = new Map(raw.map((record) => [record?.level, record?.ids]));
  const prior = new Set();
  return Array.from({ length: LEVEL_COUNT }, (_, level) => {
    const ids = Array.isArray(byLevel.get(level)) ? byLevel.get(level) : [];
    for (const id of ids) if (typeof id === 'string' && nodeIds.has(id)) prior.add(id);
    return [...prior];
  });
}

function normaliseAliases(value, nodeIds) {
  const aliases = new Map();
  for (const record of Array.isArray(value) ? value : []) {
    if (!record || typeof record.term !== 'string' || typeof record.target !== 'string') continue;
    if (nodeIds.has(record.target)) aliases.set(record.term.trim().toLocaleLowerCase(), record.target);
  }
  return aliases;
}

/**
 * Accept the current semantic-scatter payload and the forward-compatible static atlas shape.
 * Regions are metadata over a single continuous coordinate plane; they never replace geometry.
 */
export function normaliseAtlasPayload(payload) {
  if (!payload || typeof payload !== 'object') throw new TypeError('atlas payload is required');
  const source = payload.atlas && typeof payload.atlas === 'object' ? payload.atlas : payload;
  const nodes = (Array.isArray(source.nodes) ? source.nodes : []).map(normaliseNode);
  if (nodes.length === 0) throw new TypeError('atlas needs at least one node');
  const byId = new Map();
  for (const node of nodes) {
    if (byId.has(node.id)) throw new TypeError(`atlas node id is duplicated: ${node.id}`);
    byId.set(node.id, node);
  }
  const nodeIds = new Set(byId.keys());
  const initialCamera = normaliseBounds(source.initial_camera ?? source.initialCamera, 'initial_camera');
  const worldBounds = normaliseBounds(source.world_bounds ?? source.worldBounds ?? initialCamera, 'world_bounds');
  const childrenByParent = new Map();
  for (const node of nodes) {
    if (!node.parentId || !nodeIds.has(node.parentId)) continue;
    const children = childrenByParent.get(node.parentId) ?? [];
    children.push(node.id);
    childrenByParent.set(node.parentId, children);
  }
  for (const children of childrenByParent.values()) children.sort((left, right) => byId.get(left).name.localeCompare(byId.get(right).name));
  return {
    revision: typeof source.revision === 'string' ? source.revision : 'static-atlas-v1',
    nodes,
    byId,
    initialCamera,
    worldBounds,
    labels: normaliseLabelSets(source.labels ?? source.label_sets, nodeIds),
    aliases: normaliseAliases(source.aliases, nodeIds),
    childrenByParent,
    regions: (Array.isArray(source.overview_regions) ? source.overview_regions : source.regions ?? [])
      .filter((region) => region && typeof region === 'object')
      .map((region) => ({ ...region, title: region.title ?? region.label ?? region.name })),
    neighborsUrl: typeof source.neighbors_url === 'string' ? source.neighbors_url : null,
  };
}

export function fitCamera(bounds, viewport, padding = 0.94) {
  const width = finiteNumber(viewport.width, 'viewport.width');
  const height = finiteNumber(viewport.height, 'viewport.height');
  if (!(width > 0 && height > 0)) throw new RangeError('viewport must have positive area');
  const area = normaliseBounds(bounds);
  const scale = Math.min((width * padding) / (area.x1 - area.x0), (height * padding) / (area.y1 - area.y0));
  return {
    scale,
    x: width / 2 - ((area.x0 + area.x1) / 2) * scale,
    y: height / 2 - ((area.y0 + area.y1) / 2) * scale,
  };
}

export function zoomAt(camera, point, factor, limits) {
  const scale = clamp(camera.scale * factor, limits.min, limits.max);
  const worldX = (point.x - camera.x) / camera.scale;
  const worldY = (point.y - camera.y) / camera.scale;
  return { scale, x: point.x - worldX * scale, y: point.y - worldY * scale };
}

export function levelForScale(scale, fitScale) {
  // Reveal the next semantic neighborhood shortly after the user begins
  // zooming. This keeps the first wheel gesture informative without making the
  // initial overview noisy.
  return clamp(Math.floor(Math.log2(scale / fitScale) + 0.8), 0, LEVEL_COUNT - 1);
}

export function findAtlasTarget(atlas, term) {
  const query = term.trim().toLocaleLowerCase();
  if (!query) return null;
  const alias = atlas.aliases.get(query);
  if (alias) return alias;
  const exact = atlas.nodes.find((node) => node.name.toLocaleLowerCase() === query);
  if (exact) return exact.id;
  const prefix = atlas.nodes.find((node) => node.name.toLocaleLowerCase().startsWith(query));
  return prefix?.id ?? null;
}

export function boundsForNodes(nodes, fallback) {
  if (nodes.length === 0) return fallback;
  const xs = nodes.map((node) => node.x);
  const ys = nodes.map((node) => node.y);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const y0 = Math.min(...ys);
  const y1 = Math.max(...ys);
  const span = Math.max(x1 - x0, y1 - y0, 0.04);
  return { x0: x0 - span * 0.8, y0: y0 - span * 0.8, x1: x1 + span * 0.8, y1: y1 + span * 0.8 };
}

/**
 * Return the screen-space placement used by the Canvas label renderer.
 * Keeping this small bit of geometry pure makes collision decisions deterministic
 * and lets the renderer avoid measuring or laying out labels more than once.
 */
export function placeLabel(screen, width, viewport, options = {}) {
  const offset = options.offset ?? 6;
  const height = options.height ?? 16;
  const padding = options.padding ?? 3;
  const x = screen.x + offset + width <= viewport.width - padding
    ? screen.x + offset
    : screen.x - offset - width;
  const y = screen.y < height + padding ? screen.y + height : screen.y - 6;
  return {
    x,
    y,
    box: {
      x0: x - padding,
      y0: y - height - padding,
      x1: x + width + padding,
      y1: y + padding,
    },
  };
}

function boxesOverlap(left, right) {
  return left.x0 < right.x1 && left.x1 > right.x0 && left.y0 < right.y1 && left.y1 > right.y0;
}

/**
 * Select a stable, readable subset of labels from already-ranked candidates.
 * Candidates with lower priority win; ties are resolved by id. The caller owns
 * screen projection and text measurement, so this remains independent of Canvas.
 */
export function declutterLabels(candidates, viewport, measureText, options = {}) {
  const maximum = options.maximum ?? candidates.length;
  const selected = [];
  const occupied = [];
  const ordered = [...candidates]
    .filter((candidate) => candidate && typeof candidate.id === 'string' && candidate.id)
    .sort((left, right) => (left.priority ?? 0) - (right.priority ?? 0) || left.id.localeCompare(right.id));
  for (const candidate of ordered) {
    if (selected.length >= maximum) break;
    const screen = candidate.screen;
    if (!screen || !Number.isFinite(screen.x) || !Number.isFinite(screen.y)) continue;
    const width = Math.max(1, Number(measureText(candidate.text)) || 1);
    const placement = placeLabel(screen, width, viewport, options);
    if (occupied.some((box) => boxesOverlap(box, placement.box))) continue;
    occupied.push(placement.box);
    selected.push({ ...candidate, width, placement });
  }
  return selected;
}

/**
 * Pick labels for a zoom tier from the local viewport, not a globally ranked
 * label slice. Zoom therefore reveals nearby names automatically; focus is only
 * an optional priority boost and never the sole way a name can become visible.
 */
export function visibleNodeLabels(atlas, level, viewport, project, measureText, options = {}) {
  const ids = new Set();
  const focus = options.focusId;
  const required = new Set(options.requiredIds ?? []);
  if (focus && atlas.byId.has(focus)) required.add(focus);
  const globalOrder = new Map((atlas.labels[level] ?? []).map((id, index) => [id, index]));
  const margin = options.margin ?? 120;
  const center = { x: viewport.width / 2, y: viewport.height / 2 };
  const projected = new Map();
  const inRange = (screen) => (
    screen.x >= -margin && screen.y >= -margin
    && screen.x <= viewport.width + margin && screen.y <= viewport.height + margin
  );
  for (const node of atlas.nodes) {
    if (node.lod > level) continue;
    const screen = project(node);
    projected.set(node.id, screen);
    if (inRange(screen)) ids.add(node.id);
  }
  // Preserve the semantic context around each local window. Parent chains are
  // cheap to follow because the atlas already contains the immutable hierarchy.
  for (const id of [...ids]) {
    let node = atlas.byId.get(id);
    while (node?.parentId && atlas.byId.has(node.parentId)) {
      node = atlas.byId.get(node.parentId);
      if (node.lod <= level && inRange(projected.get(node.id) ?? project(node))) ids.add(node.id);
    }
  }
  for (const id of required) {
    const node = atlas.byId.get(id);
    if (node) {
      ids.add(id);
      if (!projected.has(id)) projected.set(id, project(node));
    }
  }
  const groupKey = (node) => (
    node.parentId
    ?? (node.regionId ? `region:${node.regionId}` : null)
    ?? (node.communityId === null ? null : `community:${node.communityId}`)
    ?? node.hierarchyRootId
    ?? 'unparented'
  );
  const distance = (node) => {
    const screen = projected.get(node.id) ?? project(node);
    return Math.hypot(screen.x - center.x, screen.y - center.y);
  };
  const score = (node) => (
    (required.has(node.id) ? -1e9 : 0)
    + (node.id === focus ? -1e8 : 0)
    + (node.lod === level ? -1e5 : 0)
    + distance(node) * 0.01
    + (node.labelPriority ?? globalOrder.get(node.id) ?? 10_000) * 1e-4
    - Math.min(node.importance, 10) * 1e-5
  );
  const groups = new Map();
  for (const id of ids) {
    const node = atlas.byId.get(id);
    if (!node) continue;
    const group = groups.get(groupKey(node)) ?? [];
    group.push(node);
    groups.set(groupKey(node), group);
  }
  const orderedGroups = [...groups.values()].map((group) => group.sort((left, right) => (
    score(left) - score(right) || left.id.localeCompare(right.id)
  ))).sort((left, right) => (
    score(left[0]) - score(right[0]) || left[0].id.localeCompare(right[0].id)
  ));
  // Round-robin over local semantic groups so one dense parent cannot consume
  // the entire label budget. Collision culling still decides final readability.
  const interleaved = [];
  for (let index = 0; ; index += 1) {
    let added = false;
    for (const group of orderedGroups) {
      const node = group[index];
      if (!node) continue;
      added = true;
      const screen = projected.get(node.id) ?? project(node);
      interleaved.push({
        id: node.id,
        text: node.name,
        screen,
        priority: score(node) + index * 0.001,
      });
    }
    if (!added) break;
  }
  return declutterLabels(interleaved, viewport, measureText, options);
}
