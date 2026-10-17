/** Complete native track memberships for local search; never inferred artist genres. */
export function validateIds(ids, maximum) {
  if (!Array.isArray(ids) || ids.length > maximum || ids.some((id, index) =>
    !Number.isSafeInteger(id) || id <= 0 || (index > 0 && id <= ids[index - 1]))) {
    throw Error('Native track membership is incomplete or invalid.');
  }
  return ids;
}

export function trackMatcher(query, artists) {
  const exact = /^#?([1-9][0-9]*)$/.exec(query.trim());
  const terms = query.normalize('NFKC').toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return ([id, title, artistId]) => {
    if (exact) return String(id) === exact[1];
    const text = `${id} ${title ?? ''} ${artists.get(artistId)?.[1] ?? ''}`.normalize('NFKC').toLocaleLowerCase();
    return terms.every(term => text.includes(term));
  };
}

export async function scopeMembership({state, catalog, genres, json, evict, current}) {
  const maximum = catalog.counts.raw_tracks;
  if (!Number.isSafeInteger(maximum) || maximum < 0) throw Error('Invalid source track count.');
  const paths = [];
  try {
    if (state.kind === 'genre') {
      const genre = genres.get(state.id);
      if (!genre) throw Error('Native genre ID is absent');
      const total = genre.track_count, size = catalog.page_size;
      if (!Number.isSafeInteger(total) || total < 0 || total > maximum
          || !Number.isSafeInteger(size) || size <= 0 || size > 200) throw Error('Invalid genre track count.');
      const pages = Math.ceil(total / size), ids = [];
      const cohort = `genre-${state.id}`;
      for (let start = 0; start < pages; start += 4) {
        if (!current()) return null;
        const batch = Array.from({length:Math.min(4, pages - start)}, (_, offset) => start + offset);
        const entries = await Promise.all(batch.map(async page => {
          const path = `cohorts/${cohort}/${page}.json`;
          paths.push(path);
          const value = await json(path);
          if (value?.cohort !== cohort || value.page !== page || value.total !== total
              || !Array.isArray(value.track_ids) || value.track_ids.length !== Math.min(size, total - page * size)) {
            throw Error('Genre membership page is incomplete or invalid.');
          }
          return validateIds(value.track_ids, maximum);
        }));
        if (!current()) return null;
        ids.push(...entries.flat());
      }
      validateIds(ids, maximum);
      if (ids.length !== total) throw Error('Genre membership total differs.');
      return {ids, paths, name:`${genre.title} · #${genre.genre_id}`, note:'Direct source genre annotations; no parent tags are inherited.'};
    }
    const album = state.kind === 'album';
    if (album && (catalog.albums?.revision !== 'fma-native-albums-v1' || catalog.albums.shards !== 128)) {
      throw Error('Album context is unavailable in this export.');
    }
    const shard = (state.id ?? 0) % (album ? catalog.albums.shards : catalog.profile_shards);
    const path = `${album ? 'albums' : 'artists'}/${shard}.json`;
    paths.push(path);
    const payload = await json(path);
    if (!current()) return null;
    const profile = album ? payload.albums?.[String(state.id)] : payload.artists?.[String(state.id)] ?? (state.id === null ? payload.artists?.None : null);
    if (payload.shard !== shard || !profile || (album ? profile.album_id : profile.artist_id) !== state.id) {
      throw Error(`Native ${album ? 'album' : 'artist'} ID is absent or invalid.`);
    }
    const ids = validateIds(profile.track_ids, maximum);
    if (album && (!ids.length || (profile.title !== null && typeof profile.title !== 'string')
        || !Array.isArray(profile.artist_ids) || !profile.artist_ids.length
        || new Set(profile.artist_ids).size !== profile.artist_ids.length
        || profile.artist_ids.some(id => id !== null && (!Number.isSafeInteger(id) || id <= 0)))) {
      throw Error('Native album context is missing or invalid.');
    }
    return {ids, paths, artistIds:album ? profile.artist_ids : null,
      name:`${album ? profile.title || 'Missing album title' : profile.name || 'Missing artist record'} · #${state.id}`,
      note:album ? 'Source track associations, not album ownership, release sequence or genre classification.' :
        `Tracks with this native artist ID; genres belong to tracks.${profile.status === 'missing_source_artist_record' ? ' Artist record is missing from the source table.' : ''}${profile.name_source === 'unanimous_track_artist_name' ? ' Track-supplied display name.' : ''}`};
  } catch (error) {
    for (const path of paths) evict(path);
    throw error;
  }
}

export function validateScopedTracks(tracks, state, membership) {
  const ids = new Set(membership.ids);
  if (tracks.some(track => !ids.has(track[0]) ||
    (state.kind === 'genre' && (!Array.isArray(track[3]) || !track[3].includes(state.id))) ||
    (state.kind === 'artist' && track[2] !== state.id) ||
    (state.kind === 'album' && (track[6] !== state.id || !membership.artistIds.includes(track[2]))))) {
    throw Error('Search membership differs from native track metadata.');
  }
}
