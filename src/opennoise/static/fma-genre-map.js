/** Native annotation overlap only; positions and edges do not imply sonic distance. */
const SVG = 'http://www.w3.org/2000/svg';
const htmlNode = (tag, text) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; return element; };

/** Complete source hierarchy; no inherited track counts or musical coordinates. */
export function renderGenreAtlas(container, sourceGenres, options = {}) {
  container.replaceChildren();
  container.classList.add('fma-genre-atlas');
  container.dataset.evidenceRole = 'native_genre_parent_relationships';
  const genres = [...(sourceGenres instanceof Map ? sourceGenres.values() : sourceGenres)]
    .sort((a, b) => a.title.localeCompare(b.title) || a.genre_id - b.genre_id);
  const index = new Map(genres.map(genre => [genre.genre_id, genre]));
  const children = new Map(), excerpts = new Map();
  for (const genre of genres) {
    if (!children.has(genre.parent_id)) children.set(genre.parent_id, []);
    children.get(genre.parent_id).push(genre);
  }
  for (const track of Object.values(options.playbackTracks ?? [])) {
    if (!Number.isSafeInteger(track.track_id) || track.track_id <= 0) continue;
    for (const id of track.genre_ids ?? []) {
      if (!index.has(id)) continue;
      if (!excerpts.has(id)) excerpts.set(id, new Set());
      excerpts.get(id).add(track.track_id);
    }
  }
  const caption = htmlNode('p', `${genres.length} FMA genres, grouped by source parent relationships. Counts are direct track annotations; child genres are not added to their parents.`);
  caption.className = 'fma-atlas-caption'; container.append(caption);
  if (!genres.length) { container.append(htmlNode('p', 'No genre definitions are available.')); return; }
  const form = htmlNode('form'); form.className = 'fma-atlas-filters';
  const searchLabel = htmlNode('label', 'Find a genre '), search = htmlNode('input');
  search.type = 'search'; search.value = String(options.query ?? ''); search.placeholder = 'Name or native ID'; search.autocomplete = 'off'; search.className = 'fma-atlas-search';
  searchLabel.append(search);
  const playableLabel = htmlNode('label'), playable = htmlNode('input');
  playable.type = 'checkbox'; playable.checked = Boolean(options.onlyWithExcerpts); playable.className = 'fma-atlas-playable';
  playableLabel.append(playable, htmlNode('span', 'Has local excerpts'));
  const clear = htmlNode('button', 'Clear filters'); clear.type = 'button';
  form.append(searchLabel, playableLabel, clear); container.append(form);
  const status = htmlNode('p'); status.className = 'fma-atlas-status'; status.setAttribute('role', 'status'); container.append(status);
  const grid = htmlNode('div'); grid.className = 'fma-atlas-grid'; container.append(grid);
  let seen, matches, visible;
  function genreLink(genre) {
    const anchor = htmlNode('a', genre.title);
    anchor.href = `#genre=${genre.genre_id}`; anchor.dataset.genreId = genre.genre_id;
    return anchor;
  }
  function counts(genre) {
    const group = htmlNode('span'); group.className = 'fma-atlas-counts';
    const count = htmlNode('small', `${new Intl.NumberFormat('en').format(genre.track_count)} tracks`);
    count.className = 'fma-atlas-count'; group.append(count);
    const available = excerpts.get(genre.genre_id)?.size ?? 0;
    if (available) {
      const listen = htmlNode('a', `Listen · ${available} excerpt${available === 1 ? '' : 's'}`);
      listen.href = `#listen&genre=${genre.genre_id}`; listen.className = 'fma-atlas-listen';
      listen.setAttribute('aria-label', `Listen to ${available} local excerpt${available === 1 ? '' : 's'} directly tagged ${genre.title}`);
      group.append(listen);
    }
    return group;
  }
  function context(genre, element) {
    if (!matches.has(genre.genre_id)) {
      element.classList.add('fma-atlas-context');
      const note = htmlNode('small', 'Parent context'); note.className = 'fma-atlas-context-note'; element.append(note);
    }
  }
  function descendants(genre) {
    const list = htmlNode('ul');
    for (const child of children.get(genre.genre_id) ?? []) {
      if (!visible.has(child.genre_id) || seen.has(child.genre_id)) continue;
      seen.add(child.genre_id);
      const item = htmlNode('li'), row = htmlNode('div'); row.className = 'fma-atlas-row';
      const name = htmlNode('span'); name.className = 'fma-atlas-name'; name.append(genreLink(child)); context(child, name);
      row.append(name, counts(child)); item.append(row);
      const nested = descendants(child);
      if (nested.children.length) item.append(nested);
      list.append(item);
    }
    return list;
  }
  function family(genre, note) {
    if (seen.has(genre.genre_id) || !visible.has(genre.genre_id)) return;
    seen.add(genre.genre_id);
    const section = htmlNode('section'); section.className = 'fma-atlas-family';
    const heading = htmlNode('h2'); heading.append(genreLink(genre)); context(genre, heading);
    section.append(heading, counts(genre));
    if (note) section.append(htmlNode('p', note));
    const list = descendants(genre);
    if (list.children.length) section.append(list);
    grid.append(section);
  }
  function draw() {
    const query = search.value.trim().toLocaleLowerCase();
    matches = new Set(genres.filter(genre => (!query || genre.title.toLocaleLowerCase().includes(query) || String(genre.genre_id) === query) && (!playable.checked || excerpts.has(genre.genre_id))).map(genre => genre.genre_id));
    visible = new Set(matches);
    for (const id of matches) {
      const chain = new Set([id]); let parent = index.get(id).parent_id;
      while (index.has(parent) && !chain.has(parent)) {
        visible.add(parent); chain.add(parent); parent = index.get(parent).parent_id;
      }
    }
    seen = new Set(); grid.replaceChildren();
    const contextCount = visible.size - matches.size;
    status.textContent = `${matches.size} of ${genres.length} genres${playable.checked ? ' with local excerpts' : ''}${contextCount ? ` · ${contextCount} parent headings for context` : ''}.`;
    clear.hidden = !query && !playable.checked;
    if (!matches.size) { grid.append(htmlNode('p', 'No genres match these filters. Clear filters to browse every genre.')); return; }
    for (const genre of genres) {
      if (genre.parent_id == null || !index.has(genre.parent_id)) family(genre, genre.parent_id == null ? null : `Parent #${genre.parent_id} is absent from this catalog.`);
    }
    // Preserve all definitions even if future source data contains a cycle.
    for (const genre of genres) if (!seen.has(genre.genre_id) && visible.has(genre.genre_id)) family(genre, 'This source parent chain contains a cycle; shown separately.');
  }
  function update() {
    draw();
    options.onFilterChange?.({query: search.value, onlyWithExcerpts: playable.checked});
  }
  search.addEventListener('input', update); playable.addEventListener('change', update);
  form.addEventListener('submit', event => { event.preventDefault(); update(); grid.querySelector('a')?.focus(); });
  clear.addEventListener('click', () => { search.value = ''; playable.checked = false; update(); search.focus(); });
  draw();
}

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
