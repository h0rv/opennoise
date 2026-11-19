import type { ArtistDetail } from './catalog';

export function artistNeighbors(data: ArtistDetail) {
  const seen = new Set([data.artist.id]);
  return (data.similar || []).filter(({ artist }) => {
    if (seen.has(artist.id)) return false;
    seen.add(artist.id);
    return true;
  });
}

type Node = { width: number; height: number };
type Edge = { a: number; b: number; score: number };
const strength = (score: number) => Math.max(0, Math.min(1, score));

export function layoutArtists(nodes: Node[], edges: Edge[], width: number, height: number) {
  const radius = Math.max(30, Math.min(width, height) * 0.43);
  const points = nodes.map((_, i) => ({
    x: i ? Math.cos(i * 2.399963) * radius * 0.7 : 0,
    y: i ? Math.sin(i * 2.399963) * radius * 0.7 : 0,
  }));
  for (let step = 0; step < 400; step++) {
    const forces = nodes.map(() => ({ x: 0, y: 0 }));
    for (const { a, b, score } of edges) {
      const dx = points[b].x - points[a].x,
        dy = points[b].y - points[a].y;
      const distance = Math.hypot(dx, dy) || 1;
      const target = radius * (1 - 0.76 * strength(score));
      const force = (distance - target) * (a === 0 ? 0.2 : 0.008);
      forces[a].x += (dx / distance) * force;
      forces[a].y += (dy / distance) * force;
      forces[b].x -= (dx / distance) * force;
      forces[b].y -= (dy / distance) * force;
    }
    for (let a = 0; a < nodes.length; a++) {
      for (let b = a + 1; b < nodes.length; b++) {
        const dx = points[b].x - points[a].x,
          dy = points[b].y - points[a].y;
        const distance = Math.hypot(dx, dy) || 1;
        const repulsion = 100 / distance;
        forces[a].x -= (dx / distance) * repulsion;
        forces[a].y -= (dy / distance) * repulsion;
        forces[b].x += (dx / distance) * repulsion;
        forces[b].y += (dy / distance) * repulsion;
        const overlapX = (nodes[a].width + nodes[b].width) / 2 + 10 - Math.abs(dx);
        const overlapY = (nodes[a].height + nodes[b].height) / 2 + 8 - Math.abs(dy);
        if (overlapX > 0 && overlapY > 0) {
          const axis = overlapX < overlapY ? 'x' : 'y';
          const push =
            (axis === 'x' ? overlapX : overlapY) * Math.sign((axis === 'x' ? dx : dy) || 1) * 0.4;
          forces[a][axis] -= push;
          forces[b][axis] += push;
        }
      }
    }
    points.forEach((point, i) => {
      if (!i) return;
      point.x = Math.max(
        -width / 2 + nodes[i].width / 2 + 12,
        Math.min(width / 2 - nodes[i].width / 2 - 12, point.x + forces[i].x),
      );
      point.y = Math.max(
        -height / 2 + nodes[i].height / 2 + 12,
        Math.min(height / 2 - nodes[i].height / 2 - 12, point.y + forces[i].y),
      );
    });
  }
  for (let step = 0; step < 300; step++) {
    for (let a = 0; a < nodes.length; a++) {
      for (let b = a + 1; b < nodes.length; b++) {
        const dx = points[b].x - points[a].x,
          dy = points[b].y - points[a].y;
        const overlapX = (nodes[a].width + nodes[b].width) / 2 + 8 - Math.abs(dx);
        const overlapY = (nodes[a].height + nodes[b].height) / 2 + 6 - Math.abs(dy);
        if (overlapX <= 0 || overlapY <= 0) continue;
        const axis = overlapX < overlapY && Math.abs(dx) > 1 ? 'x' : 'y';
        const push =
          (axis === 'x' ? overlapX : overlapY) * Math.sign((axis === 'x' ? dx : dy) || 1) * 0.51;
        points[a][axis] -= push;
        points[b][axis] += push;
      }
    }
    points.forEach((point, i) => {
      point.x = Math.max(
        -width / 2 + nodes[i].width / 2 + 12,
        Math.min(width / 2 - nodes[i].width / 2 - 12, point.x),
      );
      point.y = Math.max(
        -height / 2 + nodes[i].height / 2 + 12,
        Math.min(height / 2 - nodes[i].height / 2 - 12, point.y),
      );
    });
  }
  if (!points.length) return [];
  const left = Math.min(...points.map((point, i) => point.x - nodes[i].width / 2));
  const right = Math.max(...points.map((point, i) => point.x + nodes[i].width / 2));
  const top = Math.min(...points.map((point, i) => point.y - nodes[i].height / 2));
  const bottom = Math.max(...points.map((point, i) => point.y + nodes[i].height / 2));
  const scale = Math.max(
    1,
    Math.min((width - 40) / (right - left), (height - 40) / (bottom - top)),
  );
  return points.map(({ x, y }) => ({
    x: (x - (left + right) / 2) * scale + width / 2,
    y: (y - (top + bottom) / 2) * scale + height / 2,
  }));
}

export function artistGraph(
  data: ArtistDetail,
  load: (id: string, signal: AbortSignal) => Promise<ArtistDetail>,
  signal: AbortSignal,
) {
  const neighbors = artistNeighbors(data)
    .sort((a, b) => b.score - a.score)
    .slice(0, 24);
  const scores = neighbors.map(({ score }) => score);
  const low = Math.min(...scores),
    high = Math.max(...scores);
  const normalized = scores.map((score, i) =>
    high > low
      ? (0.7 * (score - low)) / (high - low) + 0.3 * (1 - i / Math.max(1, scores.length - 1))
      : 0.5,
  );
  const edges: Edge[] = normalized.map((score, i) => ({ a: 0, b: i + 1, score }));
  const graph = document.createElement('div');
  graph.className = 'artist-graph';
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('aria-hidden', 'true');
  graph.append(svg);
  const buttons = [data.artist, ...neighbors.map(({ artist }) => artist)].map((artist, i) => {
    const button = document.createElement('button');
    button.className = i ? 'artist-neighbor' : 'artist-root';
    button.dataset.kind = 'artist';
    button.dataset.id = artist.id;
    button.textContent = artist.name;
    button.setAttribute(
      'aria-label',
      i ? `Explore ${artist.name}, similar to ${data.artist.name}` : `Explore ${artist.name}`,
    );
    if (i) {
      button.style.fontSize = `${12 + normalized[i - 1] * 7}px`;
      button.style.fontWeight = `${400 + Math.round(normalized[i - 1] * 2) * 100}`;
      button.style.opacity = `${0.6 + normalized[i - 1] * 0.4}`;
    }
    graph.append(button);
    return button;
  });
  let frame = 0;
  const draw = () => {
    if (signal.aborted || !graph.isConnected) return;
    const width = graph.clientWidth,
      height = graph.clientHeight;
    const points = layoutArtists(
      buttons.map((button) => ({ width: button.offsetWidth, height: button.offsetHeight })),
      edges,
      width,
      height,
    );
    buttons.forEach((button, i) => {
      button.style.left = `${points[i].x}px`;
      button.style.top = `${points[i].y}px`;
    });
    svg.replaceChildren(
      ...edges.map(({ a, b, score }) => {
        const line = document.createElementNS(svg.namespaceURI, 'line');
        for (const [key, value] of Object.entries({
          x1: points[a].x,
          y1: points[a].y,
          x2: points[b].x,
          y2: points[b].y,
        }))
          line.setAttribute(key, String(value));
        line.setAttribute(
          'opacity',
          String(a ? 0.025 + strength(score) * 0.09 : 0.15 + strength(score) * 0.25),
        );
        return line;
      }),
    );
  };
  const schedule = () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(draw);
  };
  const observer = new ResizeObserver(schedule);
  observer.observe(graph);
  signal.addEventListener(
    'abort',
    () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    },
    { once: true },
  );
  neighbors.forEach(({ artist }, i) => {
    void load(artist.id, signal)
      .then((detail) => {
        if (signal.aborted) return;
        for (const { artist: other, score } of artistNeighbors(detail)) {
          const j = neighbors.findIndex(({ artist }) => artist.id === other.id);
          if (j < 0 || j === i) continue;
          const a = Math.min(i, j) + 1,
            b = Math.max(i, j) + 1;
          const existing = edges.find((edge) => edge.a === a && edge.b === b);
          if (existing) existing.score = Math.max(existing.score, score);
          else edges.push({ a, b, score });
        }
        schedule();
      })
      .catch(() => {});
  });
  return graph;
}
