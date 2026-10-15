import {descriptorSource, renderDiscoveryMap} from './fma-discovery-map.js';
import {renderDiscoverySearch} from './fma-discovery-search.js';
import {renderPlayableNeighbors} from './fma-playable-neighbors.js';
import {requestPlay, requestGenreStarters} from './fma-playback.js';
const $ = selector => document.querySelector(selector);
const node = (tag, text) => { const value = document.createElement(tag); if (text !== undefined) value.textContent = text; return value; };
const link = (text, href) => { const value = node('a', text); value.href = href; return value; };
const heading = $('h1'), status = $('#discovery-status'), rows = $('#discovery-rows'), query = $('#discovery-query');
$('.skip').addEventListener('click', event => {
  event.preventDefault();
  $('#content').focus();
});

let index, genres, artists, generation = 0, routeCleanup = null;
const cache = new Map();
async function json(path) {
  if (!cache.has(path)) cache.set(path, fetch(path).then(response => { if (!response.ok) throw Error('Local file unavailable.'); return response.json(); }).catch(error => { cache.delete(path); throw error; }));
  return cache.get(path);
}
function validate(value) {
  const extended = value.revision === 'fma-genre-discovery-v2';
  if ((!extended && value.revision !== 'fma-genre-discovery-v1') || !Array.isArray(value.genres) || value.genres.length > 200 || !value.tracks || Object.keys(value.tracks).length > (extended ? 133 : 128)) throw Error('Unsupported genre index.');
  if ((extended && value.collections?.coverage?.audio_revision !== 'fma-local-coverage-extension-v2') || (!extended && value.collections?.coverage?.audio_revision !== undefined)) throw Error('Coverage protocol differs from root scope.');
  const collectionKeys = Object.keys(value.collections ?? {});
  if (!collectionKeys.includes('original') || !collectionKeys.includes('expanded')
    || collectionKeys.some(key => !['original', 'expanded', 'coverage'].includes(key))) throw Error('Invalid collection scope.');
  for (const key of collectionKeys) {
    const map = value.collections?.[key]?.descriptor_map;
    if (map && map.href !== `${key}/explorer/index.html#descriptor-map`) throw Error('Invalid descriptor map location.');
  }
  const identities = value.genres.map(genre => genre.genre_id);
  if (new Set(identities).size !== identities.length || value.musical_quality_validated !== false) throw Error('Invalid source genre scope.');
  for (const key of collectionKeys) if (value.collections?.[key]?.manifest !== `${key}/audio/manifest.json`) throw Error('Invalid collection location.');
  for (const [key, track] of Object.entries(value.tracks)) {
    if (!Array.isArray(track.origins) || !track.origins.includes(track.collection)
      || new Set(track.origins).size !== track.origins.length
      || track.origins.some(origin => !collectionKeys.includes(origin))
      || (track.origins.includes('coverage') && (track.origins.length !== 1 || track.collection !== 'coverage'))) throw Error('Invalid excerpt origins.');
    if (!Number.isSafeInteger(track.track_id) || track.track_id <= 0 || key !== String(track.track_id) || !collectionKeys.includes(track.collection) || !Number.isSafeInteger(track.artist_id) || track.artist_id <= 0 || !Array.isArray(track.genre_ids) || new Set(track.genre_ids).size !== track.genre_ids.length || track.genre_ids.some(id => !identities.includes(id))) throw Error('Invalid excerpt identity.');
  }
  const coverageCount = Object.values(value.tracks).filter(track => track.origins.includes('coverage')).length;
  if (collectionKeys.includes('coverage') && (coverageCount < 1 || coverageCount > (extended ? 17 : 12))) throw Error('Coverage collection exceeds its bound.');
  for (const genre of value.genres) {
    const expectedArtists = [...new Set(Object.values(value.tracks).filter(track => track.genre_ids.includes(genre.genre_id)).map(track => track.artist_id))].sort((a,b)=>a-b);
    const expected = Object.values(value.tracks).filter(track => track.genre_ids.includes(genre.genre_id)).map(track => track.track_id).sort((a,b)=>a-b);
    if (!Number.isSafeInteger(genre.genre_id) || genre.genre_id <= 0 || !Array.isArray(genre.track_ids) || !Array.isArray(genre.starting_ids) || JSON.stringify(genre.artist_ids) !== JSON.stringify(expectedArtists) || JSON.stringify(genre.track_ids) !== JSON.stringify(expected) || new Set(genre.starting_ids).size !== genre.starting_ids.length || Boolean(genre.starting_ids.length) !== Boolean(expected.length) || genre.starting_ids.length > 3 || genre.starting_ids.some(id => !genre.track_ids.includes(id)) || genre.track_ids.some(id => !value.tracks[String(id)]?.genre_ids.includes(genre.genre_id)) || new Set(genre.starting_ids.map(id => value.tracks[String(id)]?.artist_id)).size !== genre.starting_ids.length) throw Error('Invalid genre examples.');
  }
  if (value.counts?.genres !== value.genres.length || value.counts?.clips !== Object.keys(value.tracks).length || value.counts?.playable_genres !== value.genres.filter(g => g.track_ids.length).length || value.counts?.artists !== new Set(Object.values(value.tracks).map(t => t.artist_id)).size) throw Error('Invalid coverage counts.');
  return value;
}
function play(id, collection = null, ids = null) {
  const track = index.tracks[String(id)];
  if (!track) return;
  document.body.dataset.discoveryQueue = String(Boolean(ids && ids.length > 1));
  requestPlay({config: index.collections[collection ?? track.collection], id, ids: ids ?? [id], queue: Boolean(ids), json});
}
function playButton(id, label = 'Play excerpt') {
  const button = node('button', label); button.type = 'button'; button.dataset.playId = id;
  button.setAttribute('aria-label', `${label}: ${index.tracks[String(id)].title} by ${index.tracks[String(id)].artist_name}`);
  button.addEventListener('click', () => play(id)); return button;
}
function route() {
  const p = new URLSearchParams(location.hash.slice(1));
  for (const kind of ['genre', 'artist', 'track']) if (p.has(kind)) { const id = p.get(kind); return /^[1-9][0-9]*$/.test(id) && Number.isSafeInteger(Number(id)) ? {kind, id:Number(id)} : {kind:'invalid'}; }
  if (p.has('descriptor-map')) {
    const selected = Number(p.get('selected'));
    return {kind: 'descriptor-map', entity: p.get('entity') === 'artists' ? 'artists' : 'genres',
      q: p.get('q') ?? '', selected: Number.isSafeInteger(selected) && selected > 0 ? selected : null};
  }
  if (p.has('families')) return {kind: 'families', q: p.get('q') ?? '', playable: p.get('playable') === '1'};
  return {kind:p.has('search') ? 'search' : p.has('artists') ? 'artists':'genres', q:p.get('q') ?? '', all:p.get('all') === '1'};
}
function excerpt(id, preferred = false) {
  const track = index.tracks[String(id)], article = node('article'); article.className = 'discovery-excerpt'; article.dataset.trackId = id;
  const title=node('h3');title.append(link(track.title || `Track #${id}`, `#track=${id}`));article.append(title);
  const credit = node('p'); credit.append(link(track.artist_name, `#artist=${track.artist_id}`)); article.append(credit, playButton(id));
  if (preferred) article.append(node('small', `${track.genre_ids.length} direct source tag${track.genre_ids.length === 1 ? '' : 's'}`));
  const tags = node('div'); tags.className = 'discovery-tags';
  for (const genreId of track.genre_ids) tags.append(link(genres.get(genreId)?.title ?? `Genre #${genreId}`, `#genre=${genreId}`));
  const links = node('p'); links.className = 'excerpt-links'; links.append(link('Full track record', `${track.collection}/explorer/index.html#track=${id}`));
  article.append(tags, links); return article;
}
function directory(state) {
  const isArtist = state.kind === 'artists';
  heading.textContent = isArtist ? 'Artists with excerpts' : 'Explore genres';
  const source = isArtist ? [...artists.values()].map(a => ({id:a.id,title:a.name,track_ids:a.track_ids,artist_ids:[a.id],starting_ids:[a.track_ids[0]]})) : index.genres.map(g=>({...g,id:g.genre_id}));
  const available = source.filter(row => isArtist || state.all || row.track_ids.length);
  const term = state.q.trim().toLocaleLowerCase(), matches = available.filter(row => row.title.toLocaleLowerCase().includes(term) || String(row.id) === term).sort((a,b)=>a.title.localeCompare(b.title) || a.id-b.id);
  status.textContent = isArtist ? `${matches.length} artists with local excerpts.` : `${matches.length} matching genres · ${index.counts.playable_genres} of ${index.counts.genres} have excerpts · ${index.counts.clips} distinct recordings.`;
  const list = node('ul'); list.className = 'discovery-directory search-results';
  for (const row of matches) {
    const item = node('li'); item.dataset.nativeId = row.id; item.append(link(row.title, `#${isArtist ? 'artist':'genre'}=${row.id}`));
    item.append(node('small', row.track_ids.length ? `${row.track_ids.length} excerpt${row.track_ids.length===1?'':'s'}${isArtist?'':` · ${row.artist_ids.length} artist${row.artist_ids.length===1?'':'s'}`}` : 'No local excerpt'));
    if (row.starting_ids.length) item.append(playButton(row.starting_ids[0], 'Play starting excerpt'));
    list.append(item);
  }
  if (!matches.length) rows.append(node('p','No matching names or native IDs.'));
  rows.append(list);
}
function genreChildren(id) {
  const children = index.genres
    .filter(genre => genre.parent_id === id)
    .sort((a, b) => a.title.localeCompare(b.title) || a.genre_id - b.genre_id);
  if (!children.length) return;

  const section = node('section');
  section.setAttribute('aria-label', 'Source subgenres');
  section.append(node('h2', 'Source subgenres'));
  section.append(node('p', 'Direct source children. Excerpt counts use each genre’s own tags; parent tags are not inherited.'));

  const list = node('ul');
  list.className = 'discovery-directory';
  for (const genre of children) {
    const item = node('li');
    item.dataset.genreId = genre.genre_id;
    item.append(link(genre.title, `#genre=${genre.genre_id}`));
    const count = genre.track_ids.length;
    item.append(node('small', count
      ? `${count} local excerpt${count === 1 ? '' : 's'}`
      : 'No local excerpt'));
    list.append(item);
  }
  section.append(list);
  rows.append(section);
}

function genrePage(id) {
  const genre = genres.get(id); if (!genre) throw Error('Genre is absent from this source.');
  heading.textContent = genre.title;
  status.textContent = `${genre.track_ids.length} local excerpt${genre.track_ids.length===1?'':'s'} · ${genre.artist_ids.length} source artist${genre.artist_ids.length===1?'':'s'}.`;
  rows.append(link('All genres', '#genres'));
  if (genre.parent_id && genres.has(genre.parent_id)) { const family=node('p');family.append('Source parent: ',link(genres.get(genre.parent_id).title,`#genre=${genre.parent_id}`));rows.append(family); }
  if (!genre.track_ids.length) rows.append(node('p','No retained excerpt has this direct source tag. You can still browse its source catalog; parent tags are not inherited.'));
  else {
    rows.append(node('h2',genre.starting_ids.length===1?'Starting excerpt':'Starting excerpts'));
    const note=node('p',genre.track_ids.length===1?'Only one excerpt is available here; it has not been judged representative of this genre.':'One excerpt per source artist, preferring fewer direct tags, then native track ID. These are starting points, not reviewed representatives.');note.className='selection-note';rows.append(note);
    if (genre.starting_ids.length > 1) {
      const sequence = node('button', 'Play starting excerpts');
      sequence.type = 'button';
      sequence.className = 'genre-play-starters';
      sequence.addEventListener('click', () => {
        document.body.dataset.discoveryQueue = 'true';
        const entries = genre.starting_ids.map(id => ({
          id,
          config: index.collections[index.tracks[String(id)].collection]
        }));
        requestGenreStarters({entries, json});
      });
      rows.append(sequence);
    }
    const chosen=node('section'); chosen.setAttribute('aria-label','Starting excerpts');for(const track of genre.starting_ids)chosen.append(excerpt(track,true));rows.append(chosen);
    const other=genre.track_ids.filter(track=>!genre.starting_ids.includes(track));
    if(other.length){const details=node('details');details.className='more-excerpts';details.append(node('summary',`All other available excerpts (${other.length})`));for(const track of other)details.append(excerpt(track));rows.append(details);}
  }
  genreChildren(id);
  const full=node('p');full.append(link(`Full source genre catalog · ${genre.track_count} tracks`, `expanded/explorer/index.html#genre=${id}`));rows.append(full);
  rows.append(node('p','Opening the full catalog leaves this page and stops its player.'));
}
async function trackPage(id, current) {
  const track=index.tracks[String(id)];if(!track)throw Error('This recording is absent from the retained excerpts.');
  heading.textContent=track.title || `Track #${id}`;status.textContent='Local excerpt · direct source tags and attribution.';
  rows.append(link('Explore genres','#genres'),excerpt(id));
  const collection=track.collection, config=index.collections[collection];
  const pool=Object.values(index.tracks).filter(entry=>entry.origins.includes(collection));
  const before=rows.children.length;
  await renderPlayableNeighbors({id,config:config.playable_neighbors,playback:{manifest_sha256:config.manifest_sha256,tracks:pool},json,tracksFor:async ids=>ids.map(identity=>{const entry=index.tracks[String(identity)];if(!entry)throw Error('Missing retained excerpt');return [identity,entry.title,entry.artist_id];}),artistIndex:new Map([...artists].map(([identity,artist])=>[identity,[identity,artist.name]])),rows,current,onPlay:(identity,ids)=>{if(current())play(identity,collection,ids ?? null);}});
  if(!current())return;
  if(rows.children.length>before){const note=node('p',`Suggestions use the ${collection} collection's bounded pool and exclude the query’s artist/album/duplicate component. They are not a search across all retained recordings.`);note.className='selection-note';rows.append(note);}
  else rows.append(node('p','No descriptor suggestion pack is attached to this collection. You can still follow its source genre tags.'));
  rows.append(node('p','Opening full track details leaves this page and stops its player.'));
}
function artistPage(id) {
  const artist=artists.get(id);if(!artist)throw Error('No retained excerpt has this source artist ID.');
  heading.textContent=artist.name;status.textContent=`${artist.track_ids.length} local excerpt${artist.track_ids.length===1?'':'s'}. Tags below belong to the recordings.`;
  rows.append(link('All artists with excerpts','#artists'));
  for(const track of artist.track_ids)rows.append(excerpt(track));
  const origin=index.tracks[String(artist.track_ids[0])].collection;
  rows.append(link('Full source artist record',`${origin}/explorer/index.html#artist=${id}`),node('p','Opening the full catalog leaves this page and stops its player.'));
}
async function familyPage(state, current) {
  heading.textContent = 'Genre families';
  status.textContent = 'Source parent relationships, not musical similarity.';
  const {renderGenreAtlas} = await import('./fma-genre-map.js');
  if (!current()) return;

  const map = index.collections.expanded.descriptor_map ?? index.collections.original.descriptor_map;
  if (map) {
    const navigation = node('p');
    navigation.append(link('Audio descriptor map', '#descriptor-map'));
    rows.append(navigation);
  }
  const atlas = node('div');
  rows.append(atlas);
  renderGenreAtlas(atlas, genres, {
    playbackTracks: index.tracks,
    query: state.q,
    onlyWithExcerpts: state.playable,
    listenHref: id => `#genre=${id}`,
    onFilterChange: ({query, onlyWithExcerpts}) => {
      if (!current()) return;
      const parameters = new URLSearchParams('families');
      if (query.trim()) parameters.set('q', query.trim());
      if (onlyWithExcerpts) parameters.set('playable', '1');
      history.replaceState(null, '', '#' + parameters);
    },
  });
}

async function render() {
  if (!index) return;
  const token = ++generation, state = route();
  routeCleanup?.();
  routeCleanup = null;
  rows.replaceChildren();
  $('#content').setAttribute('aria-busy', 'true');
  const directoryView = ['genres', 'artists', 'search'].includes(state.kind);
  $('#discovery-search').hidden = !directoryView;
  if (directoryView) {
    query.value = state.q;
    $('#include-unavailable').checked = Boolean(state.all);
    $('#availability-label').hidden = state.kind !== 'genres';
    $('label[for="discovery-query"]').textContent = state.kind === 'search'
      ? 'Find music' : state.kind === 'artists' ? 'Find an artist' : 'Find a genre';
    query.placeholder = state.kind === 'search'
      ? 'Genre, artist, track or native ID' : 'Name or native ID';
  }
  try {
    if (state.kind === 'descriptor-map') {
      await renderDiscoveryMap({index, genres, artists, state, json, rows, heading, status,
        current: () => token === generation,
        registerCleanup: cleanup => { if (token === generation) routeCleanup = cleanup; else cleanup(); },
      });
    } else if (state.kind === 'families') {
      await familyPage(state, () => token === generation);
    } else if (state.kind === 'search') {
      renderDiscoverySearch({index, artists, text: state.q, rows, heading, status, playButton});
    } else if (directoryView) {
      directory(state);
    } else if (state.kind === 'genre') {
      genrePage(state.id);
    } else if (state.kind === 'artist') {
      artistPage(state.id);
    } else if (state.kind === 'track') {
      await trackPage(state.id, () => token === generation);
    } else {
      throw Error('Invalid native ID.');
    }
  } catch (error) {
    if (token !== generation) return;
    heading.textContent = 'Page unavailable';
    status.textContent = error.message;
    rows.append(link('Explore genres', '#genres'));
  }
  if (token !== generation) return;
  $('#content').setAttribute('aria-busy', 'false');
  document.documentElement.dataset.discoveryReady = 'true';
}

function search(replace = false) {
  if (!index) return;
  const state = route();
  const p = new URLSearchParams(
    state.kind === 'search' ? 'search' : state.kind === 'artists' ? 'artists' : 'genres'
  );
  if (query.value.trim()) p.set('q', query.value.trim());
  if (state.kind === 'genres' && $('#include-unavailable').checked) p.set('all', '1');
  if (replace) {
    history.replaceState(null, '', '#' + p);
    render();
  } else {
    location.hash = p.toString();
  }
}

$('#discovery-search').addEventListener('submit',event=>{event.preventDefault();const first=rows.querySelector('.search-results a');if(first)first.click();else search();});query.addEventListener('input',()=>search(true));$('#include-unavailable').addEventListener('change',()=>search());query.addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();rows.querySelector('.search-results a')?.focus();}});
window.addEventListener('hashchange',async()=>{const pending=render(),token=generation;await pending;if(token===generation)heading.focus({preventScroll:true});});
document.addEventListener('keydown',event=>{if(event.key==='/'&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName)&&!$('#discovery-search').hidden){event.preventDefault();query.focus();}});
let initializing = false;

async function initialize() {
  if (initializing || index) return;
  initializing = true;
  rows.replaceChildren();
  heading.textContent = 'Loading genres…';
  status.textContent = '';
  $('#discovery-search').hidden = true;
  $('#content').setAttribute('aria-busy', 'true');
  delete document.documentElement.dataset.discoveryReady;

  try {
    const loaded = validate(await json('genre-discovery.json'));
    const loadedArtists = new Map();
    for (const track of Object.values(loaded.tracks)) {
      if (!loadedArtists.has(track.artist_id)) {
        loadedArtists.set(track.artist_id, {
          id: track.artist_id,
          name: track.artist_name,
          track_ids: [],
        });
      }
      loadedArtists.get(track.artist_id).track_ids.push(track.track_id);
    }
    for (const artist of loadedArtists.values()) {
      artist.track_ids.sort((a, b) => a - b);
    }
    genres = new Map(loaded.genres.map(genre => [genre.genre_id, genre]));
    artists = loadedArtists;
    index = loaded;
    $('[data-root-map]').hidden = !descriptorSource(index);
    await render();
  } catch (error) {
    // Validation failures must be fetched again, just like transport failures.
    cache.delete('genre-discovery.json');
    index = undefined;
    heading.textContent = 'Listening index unavailable';
    status.textContent = error.message;
    rows.replaceChildren();
    const retry = node('button', 'Retry loading genres');
    retry.type = 'button';
    retry.dataset.retryIndex = '';
    retry.addEventListener('click', initialize);
    rows.append(retry, link('Open the verified collections', 'collections.html'));
    $('#content').setAttribute('aria-busy', 'false');
  } finally {
    initializing = false;
  }
}

await initialize();
