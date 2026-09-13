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
    parentId: typeof value.parent_id === 'string'
      ? value.parent_id
      : (typeof value.display_parent_id === 'string' ? value.display_parent_id : null),
    regionId: typeof value.region_id === 'string' ? value.region_id : null,
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
  return clamp(Math.floor(Math.log2(scale / fitScale) + 0.45), 0, LEVEL_COUNT - 1);
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
