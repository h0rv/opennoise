/** Source artists grouped by direct track annotations, never artist classification. */
const positive = value => /^[1-9][0-9]*$/.test(value ?? '') && Number.isSafeInteger(Number(value));
const validArtist = id => id === null || (Number.isSafeInteger(id) && id > 0);
const completed = new Map();

export function genreArtistRoute(params) {
  if (!params.has('genre-artists') && !(params.has('artist') && params.has('genre'))) return null;
  const genre = params.get(params.has('genre-artists') ? 'genre-artists' : 'genre');
  const page = params.get('page') ?? '0';
  if (!positive(genre) || !/^(0|[1-9][0-9]*)$/.test(page) || !Number.isSafeInteger(Number(page))) return {kind: 'invalid'};
  if (params.has('genre-artists')) {
    if (params.has('artist') || params.has('genre')) return {kind: 'invalid'};
    return {kind: 'genre-artists', id: Number(genre), page: Number(page)};
  }
  const artist = params.get('artist');
  if (artist !== 'null' && !positive(artist)) return {kind: 'invalid'};
  return {kind: 'artist-genre', id: Number(genre), artist: artist === 'null' ? null : Number(artist), page: Number(page)};
}

export async function artistGenreTracks({profile, artist, genre, rawTrackCount, tracksFor, current}) {
  if (profile?.artist_id !== artist || !Array.isArray(profile.track_ids) ||
      profile.track_ids.length > rawTrackCount ||
      profile.track_ids.some((id, index, all) => !Number.isSafeInteger(id) || id <= 0 || (index && id <= all[index - 1])) ||
      !Array.isArray(profile.track_genre_counts)) throw Error('Invalid native artist profile');
  const seen = new Set();
  for (const row of profile.track_genre_counts) {
    if (!Number.isSafeInteger(row.genre_id) || row.genre_id <= 0 || seen.has(row.genre_id) ||
        !Number.isSafeInteger(row.track_count) || row.track_count <= 0 || row.track_count > profile.track_ids.length) throw Error('Invalid artist track-genre counts');
    seen.add(row.genre_id);
  }
  const expected = profile.track_genre_counts.find(row => row.genre_id === genre)?.track_count ?? 0;
  const result = [];
  // Finish the complete profile scan before exposing a count or caching a result.
  // Twenty IDs per batch bounds concurrency even when recordings span many shards.
  for (let start = 0; start < profile.track_ids.length; start += 20) {
    if (!current()) return null;
    const ids = profile.track_ids.slice(start, start + 20);
    const tracks = await tracksFor(ids);
    if (!current()) return null;
    if (tracks.length !== ids.length || tracks.some((track, index) => track[0] !== ids[index] || track[2] !== artist || (track[3] !== null && !Array.isArray(track[3])))) throw Error('Artist track identity mismatch');
    for (const track of tracks) if (track[3]?.includes(genre)) result.push(track);
  }
  if (result.length !== expected) throw Error('Artist and genre intersection count mismatch');
  return result;
}

export async function renderGenreArtists({state, config, genres, artists, json, tracksFor, trackNode, rawTrackCount, profileShards, rows, heading, status, paginate, current}) {
  if (config?.revision !== 'fma-genre-track-artists-v1' || config.page_size !== 100 || !Array.isArray(config.genres)) throw Error('Artists on genre tracks are not attached to this export.');
  const genre = genres.get(state.id);
  if (!genre) throw Error('Native genre ID is absent');
  const summary = config.genres.find(row => row[0] === state.id);
  if (!summary || summary.length !== 3 || !Number.isSafeInteger(summary[1]) || summary[1] < 0 || !Number.isSafeInteger(summary[2]) || summary[2] !== genre.track_count) throw Error('Genre artist summary mismatch');
  const node = (tag, text) => {
    const item = document.createElement(tag);
    item.textContent = text;
    return item;
  };
  const link = (text, hash) => {
    const item = node('a', text);
    item.href = hash;
    return item;
  };
  if (state.kind === 'genre-artists') {
    heading.textContent = `Artists on ${genre.title} tracks`;
    status.textContent = `${summary[1]} source artist groups · most directly annotated tracks first.`;
    if (!paginate(summary[1], state.page, 100)) return;
    const payload = await json(`genre-artists/${state.id}/${state.page}.json`);
    if (!current()) return;
    const expected = Math.min(100, summary[1] - state.page * 100);
    if (payload.genre_id !== state.id || payload.page !== state.page || payload.total !== summary[1] ||
        !Array.isArray(payload.artists) || payload.artists.length !== expected) throw Error('Genre artist page mismatch');
    const seen = new Set();
    let prior = null;
    for (const row of payload.artists) {
      if (!Array.isArray(row) || row.length !== 2 || !validArtist(row[0]) || !artists.has(row[0]) || seen.has(row[0]) ||
          !Number.isSafeInteger(row[1]) || row[1] <= 0 || row[1] > summary[2] ||
          (prior && (row[1] > prior[1] || (row[1] === prior[1] && (row[0] ?? 0) <= (prior[0] ?? 0))))) throw Error('Invalid genre artist evidence');
      seen.add(row[0]);
      prior = row;
    }
    rows.append(link('All tracks in this genre', `#genre=${state.id}`));
    const list = node('ul', '');
    list.className = 'directory genre-artist-results';
    for (const [id, count] of payload.artists) {
      const artist = artists.get(id);
      const item = node('li', '');
      item.dataset.artistId = String(id);
      item.append(link(`${artist[1]} · #${id}`, `#artist=${id}&genre=${state.id}`));
      const missing = artist[3] === 'missing_source_artist_record' ? (artist[4] === 'unanimous_track_artist_name' ? ' · Track-supplied name; artist record missing' : ' · Artist record missing') : '';
      item.append(node('small', `${count} directly annotated tracks${missing}`));
      list.append(item);
    }
    rows.append(list);
    if (!summary[1]) rows.append(node('p', 'No directly annotated source tracks.'));
    return;
  }
  if (!artists.has(state.artist)) throw Error('Native artist ID is absent');
  const shard = await json(`artists/${(state.artist ?? 0) % profileShards}.json`);
  if (!current()) return;
  const profile = shard.artists?.[String(state.artist)] ?? (state.artist === null ? shard.artists?.None : null);
  const key = `${state.artist}:${state.id}`;
  let matches = completed.get(key);
  if (!matches) {
    status.textContent = 'Checking this artist’s source tracks…';
    matches = await artistGenreTracks({profile, artist: state.artist, genre: state.id, rawTrackCount, tracksFor, current});
    if (!current() || matches === null) return;
    completed.set(key, matches);
  }
  heading.textContent = `${artists.get(state.artist)[1]} · ${genre.title}`;
  status.textContent = `${matches.length} recordings with this source artist ID and direct genre annotation.`;
  if (profile.status === 'missing_source_artist_record') status.textContent += profile.name_source === 'unanimous_track_artist_name' ? ' Track-supplied name; artist record missing.' : ' Artist record missing.';
  const navigation = node('p', '');
  navigation.className = 'genre-artist-navigation';
  navigation.append(link('Artist', `#artist=${state.artist}`), document.createTextNode(' · '), link('Genre', `#genre=${state.id}`), document.createTextNode(' · '), link('Artists on these tracks', `#genre-artists=${state.id}`));
  rows.append(navigation);
  if (!paginate(matches.length, state.page, 200)) return;
  for (const track of matches.slice(state.page * 200, state.page * 200 + 200)) rows.append(trackNode(track));
  if (!matches.length) rows.append(node('p', 'No recordings have both this source artist ID and genre annotation.'));
}
