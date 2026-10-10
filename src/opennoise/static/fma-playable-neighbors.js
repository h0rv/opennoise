/** Optional suggestions within the attached local excerpt pool; never source annotations. */
const node = (tag, text) => { const value = document.createElement(tag); if (text !== undefined) value.textContent = text; return value; };
const link = (text, href) => { const value = node('a', text); value.href = href; return value; };
const nativeId = value => Number.isSafeInteger(value) && value > 0;
const reasons = new Set([null, 'unresolved_artist', 'missing_feature_row', 'outside_training_support', 'no_cross_component_candidates']);
function validate(manifest, playback) {
  const attached = playback.tracks;
  if (!Array.isArray(attached) || attached.length > 64 || attached.some(row => !nativeId(row.track_id))) throw Error('Invalid excerpt pool');
  const ids = new Set(attached.map(row => row.track_id));
  if (ids.size !== attached.length || !/^[a-f0-9]{64}$/.test(playback.manifest_sha256) || manifest.audio_manifest_sha256 !== playback.manifest_sha256 || manifest.revision !== 'fma-playable-descriptor-neighbors-v1' || manifest.labels_used !== false || manifest.fitted !== false || manifest.musical_relevance_established !== false || !Array.isArray(manifest.rows) || manifest.rows.length !== ids.size || !manifest.components || Object.keys(manifest.components).length !== ids.size) throw Error('Excerpt suggestion binding differs');
  for (const id of ids) if (!Object.hasOwn(manifest.components, id) || (manifest.components[id] !== null && !nativeId(manifest.components[id]))) throw Error('Invalid native component');
  const seen = new Set();
  for (const row of manifest.rows) {
    if (!ids.has(row.track_id) || seen.has(row.track_id) || !Array.isArray(row.neighbor_ids) || row.neighbor_ids.length > 6 || new Set(row.neighbor_ids).size !== row.neighbor_ids.length || !reasons.has(row.reason) || (row.reason === null ? !row.neighbor_ids.length : row.neighbor_ids.length)) throw Error('Invalid excerpt suggestions');
    seen.add(row.track_id);
    for (const id of row.neighbor_ids) if (!ids.has(id) || id === row.track_id || !nativeId(manifest.components[id]) || !nativeId(manifest.components[row.track_id]) || manifest.components[id] === manifest.components[row.track_id]) throw Error('Excerpt candidate differs');
  }
  const indexed = new Map(manifest.rows.map(row => [row.track_id, row]));
  for (const row of manifest.rows) if (row.neighbor_ids.some(id => indexed.get(id).reason !== null)) throw Error('Unsupported excerpt candidate');
}
export async function renderPlayableNeighbors({id, config, playback, json, tracksFor, artistIndex, rows, current, onPlay}) {
  if (!config || !playback || !playback.tracks?.some(row => row.track_id === id)) return;
  const section = node('section'); section.className = 'connections playable-neighbors'; section.dataset.evidenceRole = 'attached_excerpt_descriptor_neighbors';
  section.append(node('h2', 'Suggested excerpts'), node('p', 'Similar numeric descriptors among the attached excerpts. Musical similarity has not been validated.'));
  try {
    if (typeof config.manifest_path !== 'string' || !/^(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_.-]+\.json$/.test(config.manifest_path)) throw Error('Invalid local suggestion path');
    const manifest = await json(config.manifest_path); if (!current()) return;
    validate(manifest, playback);
    const selected = manifest.rows.find(row => row.track_id === id);
    if (selected.reason !== null) {
      section.append(node('p', 'No suggested excerpts: this track has no supported comparison in the attached pool.'));
    } else {
      const neighbors = [...selected.neighbor_ids], tracks = await tracksFor(neighbors); if (!current()) return;
      const native = new Map(tracks.map(row => [row[0], row]));
      if (native.size !== neighbors.length || neighbors.some(value => !native.has(value))) throw Error('Excerpt metadata missing');
      const invoke = (track, queue) => { if (current()) onPlay(track, queue); };
      const queue = node('button', 'Play these excerpts'); queue.type = 'button'; queue.className = 'playable-neighbors-queue'; queue.addEventListener('click', () => invoke(neighbors[0], [...neighbors])); section.append(queue);
      const list = node('ul'); list.className = 'directory';
      for (const value of neighbors) {
        const track = native.get(value), entry = playback.tracks.find(row => row.track_id === value);
        if (track[2] !== entry.artist_id) throw Error('Excerpt artist differs');
        const item = node('li'), title = link(track[1] || `Track #${value}`, `#track=${value}`); title.className = 'playable-neighbor-track';
        const artist = link(artistIndex.get(track[2])?.[1] || `Artist #${track[2]}`, `#artist=${track[2]}`);
        const play = node('button', 'Play excerpt'); play.type = 'button'; play.className = 'playable-neighbor-play'; play.setAttribute('aria-label', `Play ${track[1] || `track ${value}`}`); play.addEventListener('click', () => invoke(value));
        item.append(title, artist, play); list.append(item);
      }
      section.append(list);
    }
  } catch {
    if (!current()) return;
    section.replaceChildren(node('h2', 'Suggested excerpts'), node('p', 'Suggested excerpts are unavailable for this local export.'));
  }
  if (current()) rows.append(section);
}
