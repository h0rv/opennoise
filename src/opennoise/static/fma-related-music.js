/** Suggestions from frozen numeric descriptors, never source genre assertions. */
const node = (tag, text) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; return element; };
const link = (text, href) => { const element = node('a', text); element.href = href; return element; };
const reasons = {
  missing_feature_row: 'Audio descriptors are missing.',
  unresolved_artist: 'The source artist could not be resolved.',
  missing_descriptors: 'Audio descriptors are incomplete.',
  outside_training_support: 'Audio descriptors fall outside the fitted model’s supported range.',
  no_cross_component_candidates: 'No eligible comparison tracks remain.',
};
export async function relatedMusic({id, manifest, json, tracksFor, artistIndex, rows, current}) {
  if (!manifest) return;
  const shard = await json(`related-tracks/${Math.floor(id / manifest.track_id_span)}.json`);
  if (!current()) return;
  const entry = shard.rows.find(row => row[0] === id);
  if (!entry) throw new Error('Related music entry is missing');
  const section = node('section'); section.className = 'connections related-music'; section.dataset.evidenceRole = 'frozen_descriptor_neighbors';
  section.append(node('h2', 'Suggested tracks'));
  if (entry[2] || !entry[1].length) {
    section.append(node('p', `No suggestions. ${reasons[entry[2]] ?? 'No supported descriptor comparison is available.'}`)); rows.append(section); return;
  }
  const tracks = await tracksFor(entry[1]); if (!current()) return;
  section.append(node('p', 'Similar audio descriptors from a bounded training pool. Musical similarity has not been validated.'));
  const list = node('ul'); list.className = 'directory';
  for (const [trackId, title, artistId] of tracks) {
    const item = node('li'), track = link(title || `Track #${trackId}`, `#track=${trackId}`); track.className = 'related-track';
    item.append(track, link(artistIndex.get(artistId)?.[1] || `Artist #${artistId}`, `#artist=${artistId}`)); list.append(item);
  }
  section.append(list); rows.append(section);
}
