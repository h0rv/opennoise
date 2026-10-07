/** Direct Wikidata claims. Source identities are never joined to FMA by name. */
const node = (tag, text) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; return element; };
const link = (text, href) => { const element = node('a', text); element.href = href; if (href.startsWith('https://')) { element.rel = 'noopener noreferrer'; element.target = '_blank'; } return element; };
const qid = value => /^Q[1-9][0-9]*$/.test(value ?? '');
const mbid = value => /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value ?? '');
const genreLink = (id, names) => link(names.get(id)?.[1] || id, `#wdgenre=${id}`);
function relationList(rows, title, entries, names) {
  const section = node('section'); section.className = 'connections'; section.dataset.evidenceRole = 'wikidata_direct_subclass_claim';
  section.append(node('h2', title)); const list = node('ul'); list.className = 'directory';
  for (const [id, name, selected] of entries) {
    const item = node('li'); item.append(selected ? genreLink(id, names) : link(name || id, `https://www.wikidata.org/wiki/${id}`));
    item.append(node('small', selected ? id : 'Outside this selection')); list.append(item);
  }
  section.append(list); if (!entries.length) section.append(node('p', 'No direct claims in this capture.')); rows.append(section);
}
export async function renderSourceGenres({state, manifest, json, heading, status, rows, paginate, current}) {
  if (!manifest) throw new Error('Wikidata genres are unavailable in this export.');
  const index = await json(manifest.index), names = new Map(index.genres.map(row => [row[0], row]));
  if (!current()) return;
  if (state.kind === 'wikidata') {
    const term = state.q.normalize('NFKC').toLocaleLowerCase();
    const matches = index.genres.filter(([id, name]) => `${name} ${id}`.normalize('NFKC').toLocaleLowerCase().includes(term));
    heading.textContent = 'Wikidata genres'; status.textContent = `${matches.length.toLocaleString('en')} matching genres · separate source selection.`;
    if (!paginate(matches.length, state.page, 100)) return;
    const list = node('ul'); list.className = 'directory search-results';
    for (const [id, , missing] of matches.slice(state.page * 100, (state.page + 1) * 100)) { const item = node('li'); item.append(genreLink(id, names), node('small', missing ? `${id} · English name missing` : id)); list.append(item); }
    rows.append(list); if (!matches.length) rows.append(node('p', 'No matching genres. Try a name or Wikidata ID.')); return;
  }
  if (state.kind === 'wdartist') {
    if (!mbid(state.id)) throw new Error('Invalid source artist ID');
    const payload = await json('source-genres/artists.json'), artist = payload.artists[state.id];
    if (!current()) return;
    if (!artist) throw new Error('Source artist is absent from this selection');
    heading.textContent = artist.name; status.textContent = 'Direct artist genre claims · Wikidata · separate from FMA artist records.';
    rows.append(link('MusicBrainz artist', `https://musicbrainz.org/artist/${state.id}`));
    if (qid(artist.wikidata_id)) { rows.append(node('span', ' · '), link('Wikidata artist', `https://www.wikidata.org/wiki/${artist.wikidata_id}`)); }
    const section = node('section'); section.className = 'connections'; section.dataset.evidenceRole = 'wikidata_direct_artist_genre_claim'; section.append(node('h2', 'Genres in this selection'));
    const list = node('ul'); list.className = 'directory';
    for (const id of artist.direct_genres) { const item = node('li'); item.append(genreLink(id, names)); list.append(item); }
    section.append(list); rows.append(section);
    if (artist.other_genres?.length) {
      const more = node('details'); more.append(node('summary', 'Other source genres')); const other = node('ul'); other.className = 'directory';
      for (const [id, name] of artist.other_genres) { const item = node('li'); item.append(link(name || id, `https://www.wikidata.org/wiki/${id}`), node('small', 'Outside this selection')); other.append(item); }
      more.append(other); rows.append(more);
    }
    heading.focus({preventScroll: true}); return;
  }
  if (!qid(state.id)) throw new Error('Invalid Wikidata genre ID');
  const entry = names.get(state.id); if (!entry) throw new Error('Wikidata genre is absent from this selection');
  const shard = await json(`source-genres/${Number(state.id.slice(1)) % index.detail_shards}.json`), detail = shard.genres[state.id];
  if (!current()) return;
  if (!detail) throw new Error('Source genre detail is missing');
  heading.textContent = entry[1] || entry[0]; status.textContent = `${entry[0]} · Wikidata direct subclass claims${entry[2] ? ' · English name missing' : ''}.`;
  rows.append(link('Wikidata genre', `https://www.wikidata.org/wiki/${state.id}`));
  relationList(rows, 'Subclass of', detail.parents, names);
  relationList(rows, 'Has subclass', detail.children.map(id => [id, names.get(id)?.[1], true]), names);
  if (detail.artists?.length) {
    const payload = await json('source-genres/artists.json'); if (!current()) return;
    const section = node('section'); section.className = 'connections source-artists'; section.dataset.evidenceRole = 'wikidata_direct_artist_genre_claim';
    section.append(node('h2', 'Artist examples'), node('p', 'Direct source claims from a selected artist cohort.'));
    const list = node('ul'); list.className = 'directory';
    for (const id of detail.artists) { const item = node('li'); item.append(link(payload.artists[id].name, `#wdartist=${id}`)); list.append(item); }
    section.append(list); rows.append(section);
  } else rows.append(node('p', 'No direct artist examples in the selected cohort.'));
  heading.focus({preventScroll: true});
}
