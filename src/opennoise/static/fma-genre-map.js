/** Native annotation overlap only; positions and edges do not imply sonic distance. */
const SVG = 'http://www.w3.org/2000/svg';
function svgNode(tag, attributes = {}, text) {
  const element = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  if (text !== undefined) element.textContent = text;
  return element;
}

export function renderGenreMap(container, genre, genresMap) {
  container.replaceChildren();
  container.classList.add('fma-genre-map');
  container.dataset.evidenceRole = 'source_track_annotation_overlap';
  const heading = document.createElement('h2');
  heading.textContent = 'Shared track annotations';
  container.append(heading);
  const connections = (genre.connections ?? []).filter(row => genresMap.has(row.genre_id) && row.genre_id !== genre.genre_id && row.shared_tracks > 0)
    .slice().sort((a, b) => b.shared_tracks - a.shared_tracks || a.genre_id - b.genre_id);
  const neighbors = connections.slice(0, 6);
  const caption = document.createElement('p');
  caption.textContent = neighbors.length
    ? `${neighbors.length} connections shown. Lines count tracks annotated with both genres; positions have no musical meaning. Names are also listed below.`
    : 'No tracks in this catalog share this genre annotation with another genre.';
  container.append(caption);
  if (!neighbors.length) return;

  const height = Math.max(160, neighbors.length * 76);
  const centerY = height / 2;
  const svg = svgNode('svg', {viewBox: `0 0 360 ${height}`, role: 'group', 'aria-label': `Genres sharing track annotations with ${genre.title}`});
  for (let index = 0; index < neighbors.length; index++) {
    const y = (index + .5) * height / neighbors.length;
    svg.append(svgNode('path', {d: `M 158 ${centerY} C 181 ${centerY}, 179 ${y}, 202 ${y}`, class: 'fma-genre-map-edge', 'aria-hidden': 'true'}));
  }

  function label(parent, title, x, y) {
    // Keep native names available in full through the accessible link and tooltip.
    const short = title.length > 19 ? title.slice(0, 18) + '…' : title;
    parent.append(svgNode('text', {x, y, 'text-anchor': 'middle', class: 'fma-genre-map-name'}, short));
    parent.append(svgNode('title', {}, title));
  }
  const selected = svgNode('g', {'aria-label': `${genre.title}, selected genre`});
  selected.append(svgNode('rect', {x: 2, y: centerY - 28, width: 156, height: 56, class: 'fma-genre-map-selected'}));
  label(selected, genre.title, 80, centerY - 2);
  selected.append(svgNode('text', {x: 80, y: centerY + 17, 'text-anchor': 'middle', class: 'fma-genre-map-count'}, 'Selected genre'));
  svg.append(selected);
  for (let index = 0; index < neighbors.length; index++) {
    const connection = neighbors[index];
    const neighbor = genresMap.get(connection.genre_id);
    const y = (index + .5) * height / neighbors.length;
    const count = new Intl.NumberFormat('en').format(connection.shared_tracks);
    const anchor = svgNode('a', {href: `#genre=${connection.genre_id}`, 'aria-label': `${neighbor.title}: ${count} tracks shared with ${genre.title}`});
    anchor.append(svgNode('rect', {x: 202, y: y - 28, width: 156, height: 56, class: 'fma-genre-map-target'}));
    label(anchor, neighbor.title, 280, y - 2);
    anchor.append(svgNode('text', {x: 280, y: y + 17, 'text-anchor': 'middle', class: 'fma-genre-map-count'}, `${count} shared tracks`));
    svg.append(anchor);
  }
  container.append(svg);
}
