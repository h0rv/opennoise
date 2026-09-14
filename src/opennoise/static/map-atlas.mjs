/** Pure atlas parsing and camera maths shared by the Canvas renderer and Node tests. */

const LEVEL_COUNT = 4;
const SPATIAL_COLUMNS = 48;
const SPATIAL_ROWS = 28;

export function clamp(value, lower, upper) {
  return Math.max(lower, Math.min(upper, value));
}

/** Add one independent circle subpath to a batched Canvas Path2D. */
export function appendCirclePath(path, x, y, radius) {
  path.moveTo(x + radius, y);
  path.arc(x, y, radius, 0, Math.PI * 2);
}

function finiteNumber(value, label) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TypeError(`${label} must be a finite number`);
  }
  return value;
}

/** Stable ordering independent of locale or browser ICU data. */
export function compareCodepoints(left, right) {
  const first = String(left);
  const second = String(right);
  let firstIndex = 0;
  let secondIndex = 0;
  while (firstIndex < first.length && secondIndex < second.length) {
    const firstCodepoint = first.codePointAt(firstIndex);
    const secondCodepoint = second.codePointAt(secondIndex);
    if (firstCodepoint !== secondCodepoint) return firstCodepoint - secondCodepoint;
    firstIndex += firstCodepoint > 0xffff ? 2 : 1;
    secondIndex += secondCodepoint > 0xffff ? 2 : 1;
  }
  return (first.length - firstIndex) - (second.length - secondIndex);
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

function nodeCohortKey(node) {
  return node.regionId
    ? `region:${node.regionId}`
    : (node.communityId === null
      ? (node.hierarchyRootId ?? 'unparented')
      : `community:${node.communityId}`);
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
    if (nodeIds.has(record.target)) aliases.set(record.term.trim().toLowerCase(), record.target);
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
  for (const children of childrenByParent.values()) children.sort((left, right) => compareCodepoints(byId.get(left).name, byId.get(right).name));
  const spatialIndex = buildSpatialIndex(nodes, worldBounds);
  const cohorts = new Map();
  for (const node of nodes) {
    const key = nodeCohortKey(node);
    const members = cohorts.get(key) ?? [];
    members.push(node);
    cohorts.set(key, members);
  }
  return {
    revision: typeof source.revision === 'string' ? source.revision : 'static-atlas-v1',
    nodes,
    byId,
    initialCamera,
    worldBounds,
    labels: normaliseLabelSets(source.labels ?? source.label_sets, nodeIds),
    aliases: normaliseAliases(source.aliases, nodeIds),
    childrenByParent,
    spatialIndex,
    cohorts,
    regions: (Array.isArray(source.overview_regions) ? source.overview_regions : source.regions ?? [])
      .filter((region) => region && typeof region === 'object')
      .map((region) => ({ ...region, title: region.title ?? region.label ?? region.name })),
    neighborsUrl: typeof source.neighbors_url === 'string' ? source.neighbors_url : null,
  };
}

function buildSpatialIndex(nodes, bounds) {
  const buckets = Array.from({ length: SPATIAL_COLUMNS * SPATIAL_ROWS }, () => []);
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const xSpan = bounds.x1 - bounds.x0;
  const ySpan = bounds.y1 - bounds.y0;
  const columnFor = (x) => clamp(Math.floor((x - bounds.x0) / xSpan * SPATIAL_COLUMNS), 0, SPATIAL_COLUMNS - 1);
  const rowFor = (y) => clamp(Math.floor((y - bounds.y0) / ySpan * SPATIAL_ROWS), 0, SPATIAL_ROWS - 1);
  for (const node of nodes) {
    const column = columnFor(node.x);
    const row = rowFor(node.y);
    buckets[row * SPATIAL_COLUMNS + column].push(node.id);
  }
  for (const bucket of buckets) bucket.sort((left, right) => {
    const first = byId.get(left);
    const second = byId.get(right);
    return first.lod - second.lod
      || (second.importance - first.importance)
      || compareCodepoints(left, right);
  });
  return { columns: SPATIAL_COLUMNS, rows: SPATIAL_ROWS, bounds, buckets };
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

/** Fit a focused neighborhood while keeping its bounds centered after scaling. */
export function focusCamera(
  bounds,
  viewport,
  minimumScale,
  maximumScale,
  padding = 0.72,
  anchor = null,
) {
  const area = normaliseBounds(bounds, 'focus bounds');
  const fitted = fitCamera(area, viewport, padding);
  const scale = clamp(fitted.scale, minimumScale, maximumScale);
  const center = anchor ?? { x: (area.x0 + area.x1) / 2, y: (area.y0 + area.y1) / 2 };
  return {
    scale,
    x: viewport.width / 2 - center.x * scale,
    y: viewport.height / 2 - center.y * scale,
  };
}

export function zoomAt(camera, point, factor, limits) {
  const scale = clamp(camera.scale * factor, limits.min, limits.max);
  const worldX = (point.x - camera.x) / camera.scale;
  const worldY = (point.y - camera.y) / camera.scale;
  return { scale, x: point.x - worldX * scale, y: point.y - worldY * scale };
}

/** Zoom controls use the current canvas center; wheel input supplies its own point. */
export function zoomAtCenter(camera, viewport, factor, limits) {
  return zoomAt(camera, { x: viewport.width / 2, y: viewport.height / 2 }, factor, limits);
}

/** Select the next semantic zoom tier for the map's explicit + control. */
export function nextLodScale(scale, fitScale, maximumScale) {
  const current = levelForScale(scale, fitScale);
  if (current >= LEVEL_COUNT - 1) return Math.min(scale, maximumScale);
  const target = fitScale * 2 ** (current + 0.3);
  return Math.min(target, maximumScale);
}

export function levelForScale(scale, fitScale) {
  // Reveal the next semantic neighborhood shortly after the user begins
  // zooming. This keeps the first wheel gesture informative without making the
  // initial overview noisy.
  return clamp(Math.floor(Math.log2(scale / fitScale) + 0.8), 0, LEVEL_COUNT - 1);
}

export function findAtlasTarget(atlas, term) {
  const query = term.trim().toLowerCase();
  if (!query) return null;
  const alias = atlas.aliases.get(query);
  if (alias) return alias;
  const exact = atlas.nodes.find((node) => node.name.toLowerCase() === query);
  if (exact) return exact.id;
  const prefix = atlas.nodes.find((node) => node.name.toLowerCase().startsWith(query));
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
  const preferredX = screen.x + offset + width <= viewport.width - padding
    ? screen.x + offset
    : screen.x - offset - width;
  const preferredY = screen.y < height + padding ? screen.y + height : screen.y - 6;
  const x = clamp(preferredX, padding, Math.max(padding, viewport.width - padding - width));
  const y = clamp(preferredY, height + padding, Math.max(height + padding, viewport.height - padding));
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

function alternateLabelPlacements(screen, width, viewport, options = {}, maxRing = 8) {
  const offset = options.offset ?? 6;
  const height = options.height ?? 16;
  const padding = options.padding ?? 3;
  const placements = [];
  const add = (x, y, callout = false) => {
    const clampedX = clamp(x, padding, Math.max(padding, viewport.width - padding - width));
    const clampedY = clamp(y, height + padding, Math.max(height + padding, viewport.height - padding));
    const placement = {
      x: clampedX,
      y: clampedY,
      box: {
        x0: clampedX - padding,
        y0: clampedY - height - padding,
        x1: clampedX + width + padding,
        y1: clampedY + padding,
      },
    };
    if (!placements.some((item) => item.x === placement.x && item.y === placement.y)) {
      placements.push(callout ? { ...placement, callout: true } : placement);
    }
  };
  for (let ring = 0; ring <= maxRing; ring += 1) {
    const distance = offset + ring * (height + padding * 2);
    add(screen.x + distance, screen.y - 6, ring > 0);
    add(screen.x - distance - width, screen.y - 6, ring > 0);
    add(screen.x - width / 2, screen.y - distance, ring > 0);
    add(screen.x - width / 2, screen.y + distance + height, ring > 0);
  }
  return placements;
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
  // Most labels only need the four adjacent placements. Required context and
  // edge labels may use the wider callout search, but ordinary labels should
  // not scan every occupied box for every possible placement at LOD3.
  const cellSize = options.collisionCellSize ?? 64;
  const columns = Math.max(1, Math.ceil(viewport.width / cellSize));
  const rows = Math.max(1, Math.ceil(viewport.height / cellSize));
  const occupiedCells = new Map();
  const cellRange = (box) => ({
    x0: clamp(Math.floor(box.x0 / cellSize), 0, columns - 1),
    y0: clamp(Math.floor(box.y0 / cellSize), 0, rows - 1),
    x1: clamp(Math.floor(box.x1 / cellSize), 0, columns - 1),
    y1: clamp(Math.floor(box.y1 / cellSize), 0, rows - 1),
  });
  const overlapsOccupied = (box) => {
    const range = cellRange(box);
    for (let row = range.y0; row <= range.y1; row += 1) {
      for (let column = range.x0; column <= range.x1; column += 1) {
        for (const occupiedBox of occupiedCells.get(row * columns + column) ?? []) {
          if (boxesOverlap(occupiedBox, box)) return true;
        }
      }
    }
    return false;
  };
  const recordOccupied = (box) => {
    const range = cellRange(box);
    for (let row = range.y0; row <= range.y1; row += 1) {
      for (let column = range.x0; column <= range.x1; column += 1) {
        const key = row * columns + column;
        const bucket = occupiedCells.get(key);
        if (bucket) bucket.push(box);
        else occupiedCells.set(key, [box]);
      }
    }
  };
  const ordered = [...candidates]
    .filter((candidate) => candidate && typeof candidate.id === 'string' && candidate.id)
    .sort((left, right) => (left.priority ?? 0) - (right.priority ?? 0) || compareCodepoints(left.id, right.id));
  for (const candidate of ordered) {
    if (selected.length >= maximum) break;
    const screen = candidate.screen;
    if (!screen || !Number.isFinite(screen.x) || !Number.isFinite(screen.y)) continue;
    const width = Math.max(1, Number(measureText(candidate.text)) || 1);
    const placements = alternateLabelPlacements(
      screen,
      width,
      viewport,
      options,
      candidate.required ? 8 : 0,
    );
    const attempts = placements;
    const placement = attempts.find((item) => !overlapsOccupied(item.box));
    if (!placement && !candidate.required) continue;
    // Required context and edge labels must remain addressable even when their
    // anchor points coincide. Search deterministic viewport callout slots before
    // giving up; this preserves the no-overlap invariant without hiding context.
    const fallback = placement ?? fallbackLabelPlacement(width, viewport, occupied, options);
    if (!fallback) continue;
    occupied.push(fallback.box);
    recordOccupied(fallback.box);
    selected.push({ ...candidate, width, placement: fallback });
  }
  return selected;
}

function fallbackLabelPlacement(width, viewport, occupied, options = {}) {
  const height = options.height ?? 16;
  const padding = options.padding ?? 3;
  const stepX = Math.max(width + padding * 2, 48);
  const stepY = height + padding * 2;
  for (let y = height + padding; y <= viewport.height - padding; y += stepY) {
    for (let x = padding; x <= viewport.width - padding - width; x += stepX) {
      const placement = {
        x,
        y,
        callout: true,
        box: { x0: x - padding, y0: y - height - padding, x1: x + width + padding, y1: y + padding },
      };
      if (!occupied.some((box) => boxesOverlap(box, placement.box))) return placement;
    }
  }
  return null;
}

function indexedNodeCandidates(atlas, camera, viewport, margin, limit = Number.MAX_SAFE_INTEGER) {
  if (!camera || !atlas.spatialIndex) return atlas.nodes;
  const { columns, rows, bounds, buckets } = atlas.spatialIndex;
  const worldX0 = (0 - margin - camera.x) / camera.scale;
  const worldY0 = (0 - margin - camera.y) / camera.scale;
  const worldX1 = (viewport.width + margin - camera.x) / camera.scale;
  const worldY1 = (viewport.height + margin - camera.y) / camera.scale;
  const xSpan = bounds.x1 - bounds.x0;
  const ySpan = bounds.y1 - bounds.y0;
  const x0 = clamp(Math.floor((worldX0 - bounds.x0) / xSpan * columns), 0, columns - 1);
  const y0 = clamp(Math.floor((worldY0 - bounds.y0) / ySpan * rows), 0, rows - 1);
  const x1 = clamp(Math.floor((worldX1 - bounds.x0) / xSpan * columns), 0, columns - 1);
  const y1 = clamp(Math.floor((worldY1 - bounds.y0) / ySpan * rows), 0, rows - 1);
  const bucketsInView = [];
  for (let row = Math.min(y0, y1); row <= Math.max(y0, y1); row += 1) {
    for (let column = Math.min(x0, x1); column <= Math.max(x0, x1); column += 1) {
      const bucket = buckets[row * columns + column];
      if (bucket.length) bucketsInView.push(bucket);
    }
  }
  const ids = [];
  const seen = new Set();
  for (let offset = 0; ids.length < limit; offset += 1) {
    let added = false;
    for (const bucket of bucketsInView) {
      const id = bucket[offset];
      if (!id || seen.has(id)) continue;
      seen.add(id); ids.push(id); added = true;
      if (ids.length >= limit) break;
    }
    if (!added) break;
  }
  return ids.map((id) => atlas.byId.get(id)).filter(Boolean);
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
  const contextIds = new Set();
  // Keep a bounded local candidate window for collision selection. The cap
  // preserves semantic-group round-robin coverage while avoiding a large
  // allocation when LOD3 is already showing hundreds of labels.
  const candidateLimit = options.candidateLimit
    ?? Math.min(Math.max(options.maximum ?? 420, 128), 350);
  const localNodes = indexedNodeCandidates(atlas, options.camera, viewport, margin, candidateLimit);
  const requestedCohorts = new Set(options.cohortIds ?? []);
  const futureCamera = options.nextCamera;
  const futurePoint = futureCamera
    ? (node) => ({ x: futureCamera.x + node.x * futureCamera.scale, y: futureCamera.y + node.y * futureCamera.scale })
    : null;
  const futureInRange = futurePoint
    ? (node) => {
      const screen = futurePoint(node);
      return inRange(screen);
    }
    : () => false;
  // The previous tier's cohort seeds are a small continuity budget. Pull a
  // bounded number of their members into the local candidate window so a
  // semantic neighborhood survives a camera step even when the spatial cell
  // round-robin would otherwise replace it with unrelated dots.
  if (requestedCohorts.size && atlas.cohorts) {
    const seen = new Set(localNodes.map((node) => node.id));
    const continuityLimit = Math.max(8, Math.min(candidateLimit, 24));
    for (const key of requestedCohorts) {
      for (const node of atlas.cohorts.get(key) ?? []) {
        if (seen.has(node.id) || node.lod > level) continue;
        seen.add(node.id);
        localNodes.push(node);
        if (localNodes.length >= candidateLimit + continuityLimit) break;
      }
      if (localNodes.length >= candidateLimit + continuityLimit) break;
    }
  }
  if (level <= 2 && atlas.cohorts) {
    const seen = new Set(localNodes.map((node) => node.id));
    // One visible representative per cohort prevents the spatial-cell budget
    // from hiding an entire neighborhood before semantic ranking can consider
    // it. Deeper members are added only for the retained cohorts above.
    for (const members of atlas.cohorts.values()) {
      const representative = members.find((node) => node.lod <= level && inRange(
        project(node),
      ));
      if (representative && !seen.has(representative.id)) {
        seen.add(representative.id);
        localNodes.push(representative);
      }
    }
  }
  for (const node of localNodes) {
    if (node.lod > level && !required.has(node.id)) continue;
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
      if (node.lod <= level && inRange(projected.get(node.id) ?? project(node))) {
        ids.add(node.id);
        if (node.lod < level) contextIds.add(node.id);
      }
    }
  }
  for (const id of required) {
    const node = atlas.byId.get(id);
    if (node) {
      ids.add(id);
      if (!projected.has(id)) projected.set(id, project(node));
    }
  }
  // A cohort is a semantic neighborhood. Parent suffixes used to split one
  // neighborhood into one group per parent, which made the disclosure look
  // like unrelated dots. Keep a stable cohort key so adjacent zoom tiers can
  // retain the same neighborhoods while revealing their members.
  const cohortKey = nodeCohortKey;
  const distance = (node) => {
    const screen = projected.get(node.id) ?? project(node);
    return Math.hypot(screen.x - center.x, screen.y - center.y);
  };
  const score = (node) => (
    (required.has(node.id) ? -1e9 : 0)
    + (node.id === focus ? -1e8 : 0)
    + (contextIds.has(node.id) ? -5e7 : 0)
    + (node.lod === level ? -1e5 : 0)
    + distance(node) * 0.01
    + (node.labelPriority ?? globalOrder.get(node.id) ?? 10_000) * 1e-4
    - Math.min(node.importance, 10) * 1e-5
  );
  const groups = new Map();
  for (const id of ids) {
    const node = atlas.byId.get(id);
    if (!node) continue;
    const key = cohortKey(node);
    const group = groups.get(key) ?? [];
    group.push(node);
    groups.set(key, group);
  }
  const rankedCohorts = [...groups.entries()].map(([key, group]) => [key, group.sort((left, right) => (
    score(left) - score(right) || compareCodepoints(left.id, right.id)
  ))]).sort((left, right) => {
    const [leftKey, leftGroup] = left;
    const [rightKey, rightGroup] = right;
    // Cohort mass is a useful, cheap proxy for a meaningful neighborhood.
    // Stable tie-breaking keeps screenshots and generated artifacts repeatable.
    const leftContinues = futurePoint && (atlas.cohorts?.get(leftKey) ?? []).some(
      (node) => node.lod <= level + 1 && futureInRange(node),
    );
    const rightContinues = futurePoint && (atlas.cohorts?.get(rightKey) ?? []).some(
      (node) => node.lod <= level + 1 && futureInRange(node),
    );
    const leftHasCurrent = leftGroup.some((node) => node.lod === level);
    const rightHasCurrent = rightGroup.some((node) => node.lod === level);
    return Number(rightHasCurrent) - Number(leftHasCurrent)
      || Number(rightContinues) - Number(leftContinues)
      || rightGroup.length - leftGroup.length
      || score(leftGroup[0]) - score(rightGroup[0])
      || compareCodepoints(leftKey, rightKey);
  });
  const cohortLimit = level === 1 ? 3 : (level === 2 ? 3 : Number.MAX_SAFE_INTEGER);
  const meaningfulCohorts = rankedCohorts.filter(([, group]) => (
    group.length > 1 || group.some((node) => node.lod === level)
  ));
  const requestedInView = [...requestedCohorts].filter((key) => groups.has(key));
  const rankedFallback = (meaningfulCohorts.length ? meaningfulCohorts : rankedCohorts)
    .map(([key]) => key)
    .filter((key) => !requestedCohorts.has(key));
  const preferredKeys = [...requestedInView, ...rankedFallback].slice(0, cohortLimit);
  const preferredCohorts = new Set(
    preferredKeys,
  );
  // At the first two detail tiers, prefer a few nontrivial neighborhoods over
  // a one-label-per-community sampler. Required edge endpoints and ancestors
  // remain addressable even when their cohort is outside this local shortlist.
  const disclosedCohorts = rankedCohorts.map(([key, group]) => [
    key,
    preferredCohorts.has(key)
      ? group
      : group.filter((node) => required.has(node.id)),
  ]).filter(([, group]) => group.length > 0);
  const preferredOrder = new Map([...preferredCohorts].map((key, index) => [key, index]));
  const orderedGroups = disclosedCohorts.map(([key, group]) => ({ key, group })).sort((left, right) => (
    (preferredCohorts.has(left.key) ? 0 : 1) - (preferredCohorts.has(right.key) ? 0 : 1)
      || (preferredOrder.get(left.key) ?? Number.MAX_SAFE_INTEGER)
        - (preferredOrder.get(right.key) ?? Number.MAX_SAFE_INTEGER)
      || score(left.group[0]) - score(right.group[0])
      || compareCodepoints(left.key, right.key)
  ));
  // Round-robin over local semantic groups so one dense parent cannot consume
  // the entire label budget. Collision culling still decides final readability.
  const interleaved = [];
  for (let index = 0; ; index += 1) {
    let added = false;
    for (const { key, group } of orderedGroups) {
      const node = group[index];
      if (!node) continue;
      added = true;
      const screen = projected.get(node.id) ?? project(node);
      interleaved.push({
        id: node.id,
        text: node.name,
        cohortKey: key,
        screen,
        required: required.has(node.id) || contextIds.has(node.id),
        priority: score(node) + index * 0.001,
      });
    }
    if (!added) break;
  }
  return declutterLabels(interleaved, viewport, measureText, options);
}
