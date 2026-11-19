import type { ArtistDetail } from './catalog';

export function artistNeighbors(data: ArtistDetail) {
  const seen = new Set([data.artist.id]);
  return (data.similar || []).filter(({ artist }) => {
    if (seen.has(artist.id)) return false;
    seen.add(artist.id);
    return true;
  });
}

export function artistGraph(data: ArtistDetail) {
  const neighbors = artistNeighbors(data);
  const graph = document.createElement('div');
  graph.className = 'artist-graph';
  graph.style.height = `${Math.max(360, neighbors.length * 72)}px`;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('aria-hidden', 'true');
  graph.append(svg);
  const root = document.createElement('div');
  root.className = 'artist-root';
  root.textContent = data.artist.name;
  graph.append(root);
  neighbors.forEach(({ artist }, index) => {
    const y = ((index + 0.5) / neighbors.length) * 100;
    const edge = document.createElementNS(svg.namespaceURI, 'line');
    edge.setAttribute('x1', '25');
    edge.setAttribute('y1', '50');
    edge.setAttribute('x2', '75');
    edge.setAttribute('y2', String(y));
    svg.append(edge);
    const button = document.createElement('button');
    button.className = 'artist-neighbor';
    button.dataset.kind = 'artist';
    button.dataset.id = artist.id;
    button.style.top = `${y}%`;
    button.textContent = artist.name;
    button.setAttribute('aria-label', `Explore ${artist.name}, similar to ${data.artist.name}`);
    graph.append(button);
  });
  return graph;
}
