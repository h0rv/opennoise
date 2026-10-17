/** Complete same-recording source annotation evidence; no inherited tags. */
const positive = value => /^[1-9][0-9]*$/.test(value ?? '') && Number.isSafeInteger(Number(value));

export function cotagRoute(params) {
  if (!params.has('connections') && !params.has('pair')) return null;
  const page = params.get('page') ?? '0';
  if (!/^(0|[1-9][0-9]*)$/.test(page) || !Number.isSafeInteger(Number(page))) return {kind: 'invalid'};
  if (params.has('connections')) {
    if (params.has('pair') || !positive(params.get('connections'))) return {kind: 'invalid'};
    return {kind: 'connections', id: Number(params.get('connections')), page: Number(page)};
  }
  const parts = params.get('pair').split(',');
  if (parts.length !== 2 || !parts.every(positive) || parts[0] === parts[1]) return {kind: 'invalid'};
  const ids = parts.map(Number).sort((a, b) => a - b);
  return {kind: 'pair', ids, page: Number(page)};
}

export function validateConnections(payload, id, genres) {
  if (payload.genre_id !== id || !Array.isArray(payload.connections)) throw Error('Connection identity mismatch');
  const seen = new Set();
  let previous = null;
  for (const row of payload.connections) {
    if (!Number.isSafeInteger(row.genre_id) || row.genre_id === id || !genres.has(row.genre_id) || seen.has(row.genre_id)) throw Error('Invalid connected genre');
    for (const key of ['shared_tracks', 'known_artist_count', 'unresolved_artist_tracks']) {
      if (!Number.isSafeInteger(row[key]) || row[key] < 0) throw Error('Invalid connection count');
    }
    if (!row.shared_tracks || row.known_artist_count + row.unresolved_artist_tracks > row.shared_tracks || (!row.known_artist_count && row.unresolved_artist_tracks !== row.shared_tracks)) throw Error('Inconsistent artist support');
    if (previous && (previous.shared_tracks < row.shared_tracks || (previous.shared_tracks === row.shared_tracks && previous.genre_id >= row.genre_id))) throw Error('Connection ordering mismatch');
    seen.add(row.genre_id);
    previous = row;
  }
  return payload.connections;
}

export async function renderCotags({state, config, genres, json, rows, heading, status, paginate, tracksFor, trackNode, current}) {
  if (config?.revision !== 'fma-direct-cotags-v1') throw Error('Complete connection evidence is not attached to this export.');
  const ids = state.kind === 'pair' ? state.ids : [state.id];
  if (ids.some(id => !genres.has(id))) throw Error('Native genre ID is absent');
  const element = (tag, text) => {
    const item = document.createElement(tag);
    item.textContent = text;
    return item;
  };
  const link = (text, href) => {
    const item = element('a', text);
    item.href = href;
    return item;
  };
  const connections = validateConnections(await json(`connections/${ids[0]}.json`), ids[0], genres);
  if (!current()) return;
  const explanation = 'Recordings with both source genre tags.';
  rows.append(element('p', explanation));
  const navigation = element('p', '');
  for (const [index, id] of ids.entries()) {
    if (index) navigation.append(document.createTextNode(' · '));
    navigation.append(link(`${genres.get(id).title} · #${id}`, `#genre=${id}`));
  }
  rows.append(navigation);
  if (state.kind === 'connections') {
    heading.textContent = `All connections · ${genres.get(state.id).title}`;
    status.textContent = `${connections.length} directly connected genres. Most shared recordings first.`;
    if (!paginate(connections.length, state.page, 100)) return;
    const list = element('ul', '');
    list.className = 'directory cotag-connections';
    list.dataset.evidenceRole = 'same_track_source_annotations';
    for (const row of connections.slice(state.page * 100, state.page * 100 + 100)) {
      const item = element('li', '');
      item.dataset.genreId = row.genre_id;
      const pair = [state.id, row.genre_id].sort((a, b) => a - b);
      item.append(link(`${genres.get(row.genre_id).title} · #${row.genre_id}`, `#pair=${pair.join(',')}`));
      item.append(element('small', `${row.shared_tracks} shared recordings · ${row.known_artist_count} known artist IDs · ${row.unresolved_artist_tracks} recordings with unresolved artists`));
      list.append(item);
    }
    rows.append(list);
    if (!connections.length) rows.append(element('p', 'No same-recording connections are present.'));
    return;
  }
  const canonical = `#pair=${ids.join(',')}${state.page ? `&page=${state.page}` : ''}`;
  if (location.hash !== canonical) history.replaceState(null, '', canonical);
  const support = connections.find(row => row.genre_id === ids[1]);
  heading.textContent = `${genres.get(ids[0]).title} + ${genres.get(ids[1]).title}`;
  if (!support) {
    status.textContent = 'No recordings carry both direct source annotations.';
    return;
  }
  status.textContent = `${support.shared_tracks} shared recordings · ${support.known_artist_count} known artist IDs · ${support.unresolved_artist_tracks} recordings with unresolved artists.`;
  if (!paginate(support.shared_tracks, state.page, 200)) return;
  const key = `pair-${ids.join('-')}`;
  const payload = await json(`cohorts/${key}/${state.page}.json`);
  if (!current()) return;
  const expected = Math.min(200, support.shared_tracks - state.page * 200);
  if (payload.cohort !== key || payload.page !== state.page || payload.total !== support.shared_tracks || !Array.isArray(payload.track_ids) || payload.track_ids.length !== expected || payload.track_ids.some((id, index, all) => !Number.isSafeInteger(id) || id <= 0 || (index && id <= all[index - 1]))) throw Error('Pair cohort identity mismatch');
  const tracks = await tracksFor(payload.track_ids);
  if (!current()) return;
  if (tracks.length !== expected || tracks.some((track, index) => track[0] !== payload.track_ids[index] || ids.some(id => !track[3].includes(id)))) throw Error('Pair track annotations mismatch');
  for (const track of tracks) rows.append(trackNode(track));
}
