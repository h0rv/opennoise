import {renderDescriptorMap} from './fma-descriptor-map.js';
import {requestDescriptorQueue, requestPlay} from './fma-playback.js';

export function descriptorSource(index) {
  return ['expanded', 'original', 'coverage'].find(key => index.collections[key]?.descriptor_map);
}

export async function renderDiscoveryMap({index, genres, artists, state, json, rows, heading, status, current, registerCleanup}) {
  const source = descriptorSource(index);
  if (!source) throw Error('This listening export has no descriptor map.');
  const prefix = `${source}/explorer/`;
  const mapJSON = path => {
    if (path !== 'descriptor-map/manifest.json' && !/^descriptor-map\/artists-[0-9]+\.json$/.test(path)) {
      throw Error('Invalid descriptor data path.');
    }
    return json(prefix + path);
  };
  const nativeArtists = await json(prefix + 'artist-index.json');
  if (!current()) return;
  if (!Array.isArray(nativeArtists.artists)) throw Error('Native artist index unavailable.');
  await renderDescriptorMap({
    state,
    config: 'descriptor-map/manifest.json',
    json: mapJSON,
    genres,
    artists: nativeArtists.artists,
    rows,
    heading,
    status,
    current,
    registerCleanup,
    playbackTracks: Object.values(index.tracks).sort((a, b) => a.track_id - b.track_id),
    detailHref: (kind, id) => kind === 'artist' && !artists.has(id)
      ? `${prefix}index.html#artist=${id}` : `#${kind}=${id}`,
    onPlay: (id, ids) => {
      if (!current()) return;
      const track = index.tracks[String(id)];
      if (!track) return;
      if (Array.isArray(ids)) {
        if (!ids.length || ids.length > 64 || new Set(ids).size !== ids.length
          || ids.some(value => !index.tracks[String(value)])) return;
        const entries = ids.map(value => {
          const selected = index.tracks[String(value)];
          return {id: value, config: index.collections[selected.collection]};
        });
        requestDescriptorQueue({entries, json});
      } else {
        requestPlay({id, config: index.collections[track.collection], json});
      }
    },
    onStateChange: ({entity, q, selected}) => {
      if (!current()) return;
      const parameters = new URLSearchParams('descriptor-map');
      if (entity === 'artists') parameters.set('entity', entity);
      if (q) parameters.set('q', q);
      if (selected !== undefined && selected !== null) parameters.set('selected', selected);
      history.replaceState(null, '', '#' + parameters);
    },
  });
}
