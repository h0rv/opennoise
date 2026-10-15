/** Search retained names and exact native identities without downloading another index. */
export function normalizeQuery(value) {
  return String(value ?? '')
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .trim()
    .replace(/\s+/g, ' ');
}

function matches(rows, query) {
  const terms = query.split(' ');
  return rows.filter(row => String(row.id) === query
    || terms.every(term => normalizeQuery(`${row.name} ${row.context ?? ''}`).includes(term))
  ).sort((a, b) => {
    const priority = row => {
      const name = normalizeQuery(row.name);
      if (String(row.id) === query || name === query) return 0;
      return name.startsWith(query) ? 1 : 2;
    };
    return priority(a) - priority(b)
      || normalizeQuery(a.name).localeCompare(normalizeQuery(b.name))
      || a.id - b.id;
  });
}

export function searchDiscovery(index, artists, text) {
  const query = normalizeQuery(text);
  if (!query) return { genres: [], artists: [], tracks: [] };
  return {
    genres: matches(index.genres.map(genre => ({
      id: genre.genre_id,
      name: genre.title,
      count: genre.track_ids.length,
      playId: genre.starting_ids[0]
    })), query),
    artists: matches([...artists.values()].map(artist => ({
      id: artist.id,
      name: artist.name,
      count: artist.track_ids.length,
      playId: artist.track_ids[0]
    })), query),
    tracks: matches(Object.values(index.tracks).map(track => ({
      id: track.track_id,
      name: track.title || `Track #${track.track_id}`,
      context: track.artist_name,
      artistId: track.artist_id,
      playId: track.track_id
    })), query)
  };
}

export function catalogSearchLinks(text) {
  const query = new URLSearchParams({q: text}).toString();
  return ['tracks', 'artists'].map(kind => ({
    kind,
    href: `expanded/explorer/index.html#${kind}&${query}`
  }));
}

function catalogHandoff(text) {
  const section = document.createElement('section');
  section.className = 'catalog-search-handoff';
  const heading = document.createElement('h2');
  heading.textContent = 'Search the full source catalog';
  const explanation = document.createElement('p');
  explanation.textContent = 'Explore metadata beyond the attached recordings. Most catalog tracks have no local audio. Leaving this page stops the current player.';
  const list = document.createElement('ul');
  for (const {kind, href} of catalogSearchLinks(text)) {
    const item = document.createElement('li');
    const link = document.createElement('a');
    link.href = href;
    link.dataset.catalogSearch = kind;
    link.textContent = `Search source ${kind}`;
    item.append(link);
    list.append(item);
  }
  section.append(heading, explanation, list);
  return section;
}

export function renderDiscoverySearch({ index, artists, text, rows, heading, status, playButton }) {
  heading.textContent = 'Search';
  if (!normalizeQuery(text)) {
    status.textContent = 'Find genres, artists or attached tracks by name or native ID.';
    return;
  }
  const results = searchDiscovery(index, artists, text);
  const total = Object.values(results).reduce((sum, group) => sum + group.length, 0);
  const count = (rows, name) => `${rows.length} ${name}${rows.length === 1 ? '' : 's'}`;
  status.textContent = total
    ? `${count(results.genres, 'genre')} · ${count(results.artists, 'artist')} · ${count(results.tracks, 'track')}. Track results include artist names. Searches cover this local listening selection.`
    : 'No matching genres, artists or attached tracks. Try another name or native ID.';
  for (const [kind, title, route] of [
    ['genres', 'Genres', 'genre'],
    ['artists', 'Artists', 'artist'],
    ['tracks', 'Tracks', 'track']
  ]) {
    if (!results[kind].length) continue;
    const section = document.createElement('section');
    section.dataset.searchKind = kind;
    const label = document.createElement('h2');
    label.textContent = `${title} (${results[kind].length})`;
    const list = document.createElement('ul');
    list.className = 'discovery-directory search-results';
    for (const result of results[kind]) {
      const item = document.createElement('li');
      item.dataset.nativeId = result.id;
      const link = document.createElement('a');
      link.href = `#${route}=${result.id}`;
      link.textContent = result.name;
      const detail = document.createElement(kind === 'tracks' ? 'a' : 'small');
      if (kind === 'tracks') {
        detail.href = `#artist=${result.artistId}`;
        detail.textContent = result.context;
      } else {
        detail.textContent = result.count
          ? `${result.count} excerpt${result.count === 1 ? '' : 's'}`
          : 'No local excerpt';
      }
      item.append(link, detail);
      if (result.playId !== undefined) item.append(playButton(result.playId, 'Play excerpt'));
      list.append(item);
    }
    section.append(label, list);
    rows.append(section);
  }
  rows.append(catalogHandoff(text));
}
