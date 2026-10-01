/** Static exploration of inferred broad, sub, and micro music communities. */
const $ = selector => document.querySelector(selector);
const canvas = $('#community-map'), context = canvas.getContext('2d');
const detail = $('#detail'), search = $('#model-search'), results = $('#search-results');
const LEVELS = ['broad', 'sub', 'micro'];
const count = value => new Intl.NumberFormat('en').format(value ?? 0);
const validArtist = id => typeof id === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
const positioned = row => Number.isFinite(row.x) && Number.isFinite(row.y);
let model, source, communities, selected, selectedArtist, artistProfile, artistAssignments;
let level = 'broad', view = 'map', searchScope = 'communities', directorySort = 'name';
let width = 1, height = 1, camera = {scale: 1, x: 0, y: 0}, fitScale = 1, drag, hovered, frame;
let generation = 0, searchGeneration = 0, searchIndex = -1, labelTargets = [], artistIndexPromise;
const profiles = new Map(), assignments = new Map(), artistNames = new Map();

function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text !== undefined) result.textContent = text;
  if (className) result.className = className;
  return result;
}
function button(text, className, action) {
  const result = node('button', text, className); result.type = 'button'; result.addEventListener('click', action); return result;
}
async function staticJson(path, absent = null) {
  const response = await fetch(path);
  if (response.status === 404 && absent !== null) return absent;
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
function hash(id = selected?.id, artist = selectedArtist) {
  const state = new URLSearchParams();
  if (id) state.set('community', id);
  if (artist) state.set('artist', artist);
  if (view !== 'map') state.set('view', view);
  if (search.value.trim()) state.set('q', search.value.trim());
  if (searchScope !== 'communities') state.set('scope', searchScope);
  if (directorySort !== 'name') state.set('sort', directorySort);
  return `#${state}`;
}
function saveState(replace = false) {
  const next = hash(); if (next !== location.hash) history[replace ? 'replaceState' : 'pushState']({}, '', next);
}
function navigate(id, artist = null, focus = true) {
  if (!communities.has(id)) return;
  selected = communities.get(id); level = selected.level; selectedArtist = validArtist(artist) ? artist : null;
  artistProfile = null; artistAssignments = null; generation++;
  results.hidden = true; render(); saveState();
  if (focus && view === 'map') fit();
  if (selectedArtist) loadArtist(selectedArtist, generation);
}
function restoreState() {
  if (!model) return;
  const state = new URLSearchParams(location.hash.slice(1));
  view = state.get('view') === 'list' ? 'list' : 'map';
  searchScope = state.get('scope') === 'artists' ? 'artists' : 'communities';
  directorySort = state.get('sort') === 'artists' ? 'artists' : 'name';
  search.value = state.get('q') ?? '';
  document.querySelector(`[name=search-scope][value=${searchScope}]`).checked = true;
  $('#directory-sort').value = directorySort;
  selected = communities.get(state.get('community')) || model.communities.find(row => row.level === 'broad') || model.communities[0];
  level = selected.level; selectedArtist = validArtist(state.get('artist')) ? state.get('artist') : null;
  artistProfile = null; artistAssignments = null; generation++;
  render(); fit();
  if (selectedArtist) loadArtist(selectedArtist, generation);
}
function selectionLink(label, className, id, artist = null) {
  const result = node('a', label, className); result.href = hash(id, artist);
  result.addEventListener('click', event => {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); navigate(id, artist);
  });
  return result;
}
function ancestry(row = selected) {
  const path = [], seen = new Set();
  while (row && !seen.has(row.id)) { path.unshift(row); seen.add(row.id); row = communities.get(row.parent_id); }
  return path;
}
function children(row = selected) { return (row.child_ids ?? []).map(id => communities.get(id)).filter(Boolean); }
function branchNodes() {
  if (!selected) return [];
  return model.communities.filter(row => row.level === level && row.parent_id === selected.parent_id);
}
function targetForLevel(nextLevel) {
  const path = ancestry();
  const existing = path.find(row => row.level === nextLevel);
  if (existing) return existing;
  const wanted = LEVELS.indexOf(nextLevel), pending = [selected], seen = new Set();
  while (pending.length) {
    const current = pending.shift(); if (!current || seen.has(current.id)) continue; seen.add(current.id);
    for (const child of children(current)) {
      if (child.level === nextLevel) return child;
      if (LEVELS.indexOf(child.level) < wanted) pending.push(child);
    }
  }
  return null;
}
function communityLink(row, className = 'branch-button') {
  const link = selectionLink('', className, row.id); link.dataset.communityId = row.id;
  link.append(node('span', row.label), node('small', `${count(row.artist_count)} assigned members`));
  if (row.level === 'broad' && row.coarse_evidence_supported === false) link.lastChild.textContent += ' · unsupported broad coherence';
  return link;
}
function artistLink(id, label = artistNames.get(id) || source.artists[id]?.name || 'Source artist') {
  const link = selectionLink('', 'artist-button', selected.id, id); link.dataset.artistId = id;
  link.append(node('span', label), node('small', 'Explore →')); return link;
}
function renderNavigation() {
  const breadcrumbs = $('#breadcrumbs'); breadcrumbs.replaceChildren();
  for (const [index, row] of ancestry().entries()) {
    if (index) breadcrumbs.append(node('span', '›'));
    const link = selectionLink(row.label, '', row.id); link.dataset.communityId = row.id;
    if (row.id === selected.id) link.setAttribute('aria-current', 'true');
    breadcrumbs.append(link);
  }
  for (const control of document.querySelectorAll('.level-nav [data-level]')) {
    control.setAttribute('aria-pressed', String(control.dataset.level === level)); control.disabled = !targetForLevel(control.dataset.level);
  }
  const rows = branchNodes(), unplaced = rows.filter(row => !positioned(row)).length;
  if (rows.length && unplaced === rows.length) view = 'list';
  $('#view-map').disabled = !rows.some(positioned);
  $('#view-map').setAttribute('aria-pressed', String(view === 'map'));
  $('#view-list').setAttribute('aria-pressed', String(view === 'list'));
  canvas.hidden = view !== 'map'; $('#community-directory').hidden = view !== 'list'; $('.map-controls').hidden = view !== 'map';
  $('#map-status').textContent = `${count(rows.length)} ${level} communities in this ${selected.parent_id ? 'branch' : 'model'}${unplaced ? ` · ${unplaced} unplaced, available in the list` : ''}. Derived labels · unreviewed model output.`;
  canvas.dataset.evidenceRole = 'inferred_emergent_music_communities';
}
function renderDirectory() {
  const rows = branchNodes().sort((a, b) => (directorySort === 'artists' ? b.artist_count - a.artist_count : 0) || a.label.localeCompare(b.label) || a.id.localeCompare(b.id));
  $('#directory-status').textContent = `${count(rows.length)} ${level} communities`;
  const list = $('#directory-results'); list.replaceChildren();
  for (const row of rows) {
    const link = communityLink(row, 'community-card');
    link.lastChild.textContent += ` · ${positioned(row) ? 'modeled position' : 'unplaced'}`;
    if (row.id === selected.id) link.setAttribute('aria-current', 'true');
    list.append(link);
  }
  if (!rows.length) list.append(node('p', 'No supported communities at this resolution in this branch.', 'empty-state'));
}
function namespaceLabel(value) {
  const labels = {artist_genre: 'Artist genre observation', artist_tag: 'Artist tag', release_genre: 'Release genre observation', release_tag: 'Release tag', musicbrainz_genre: 'MusicBrainz genre', musicbrainz_native_genre: 'MusicBrainz native genre', musicbrainz_tag: 'MusicBrainz tag', genre: 'Source genre', tag: 'Source tag', release_group_type: 'Release group metadata', wikidata: 'Wikidata statement'};
  return labels[value] || String(value || 'Source feature').replaceAll('_', ' ');
}
function featureSuggestions(record, profile) {
  if (record.feature_proposals === undefined) return null;
  if (!Array.isArray(record.feature_proposals)) return {proposals: [], rejected: 1};
  const canonical = value => value.trim().toLocaleLowerCase().replaceAll(/\s+/g, ' ');
  const observed = new Set((Array.isArray(record.observed_music_values) ? record.observed_music_values : []).filter(value => typeof value === 'string').map(canonical));
  for (const genre of source.genres) if ((profile.genre_ids ?? []).includes(genre.id)) observed.add(canonical(genre.name));
  const integer = value => Number.isSafeInteger(value) && value > 0;
  const positive = value => Number.isFinite(value) && value > 0;
  const sha256 = value => typeof value === 'string' && /^[0-9a-f]{64}$/i.test(value);
  const seen = new Set(), proposals = [];
  for (const proposal of record.feature_proposals) {
    if (!proposal || typeof proposal !== 'object' || typeof proposal.value !== 'string' || !proposal.value.trim()) continue;
    const value = canonical(proposal.value);
    if (proposal.role !== 'inferred_feature_proposal' || proposal.native_fact !== false || proposal.score_calibrated !== false || !positive(proposal.score) || proposal.feature_id !== `music:${proposal.value}` || !sha256(proposal.training_source_sha256) || !sha256(proposal.training_input_sha256) || proposal.training_input_sha256 !== proposal.training_source_sha256 || !sha256(proposal.source_model_sha256) || !integer(proposal.training_target_artist_support) || observed.has(value) || seen.has(value)) continue;
    if (!Array.isArray(proposal.evidence) || !proposal.evidence.length || !integer(proposal.contributing_cue_count) || !integer(proposal.explanation_cue_limit) || proposal.explanation_cue_limit > 5 || proposal.evidence.length > proposal.explanation_cue_limit || proposal.contributing_cue_count < proposal.evidence.length) continue;
    const cuesValid = proposal.evidence.every(cue => cue && ['music', 'proper_genre'].includes(cue.cue_role) && typeof cue.value === 'string' && observed.has(canonical(cue.value)) && integer(cue.training_joint_artist_support) && integer(cue.training_cue_artist_support) && cue.training_joint_artist_support <= cue.training_cue_artist_support && cue.training_joint_artist_support <= proposal.training_target_artist_support && positive(cue.score_contribution) && Array.isArray(cue.query_evidence_refs) && cue.query_evidence_refs.length > 0 && cue.query_evidence_refs.every(ref => typeof ref === 'string' && ref.length > 0) && (cue.query_evidence_ref_count === undefined || (integer(cue.query_evidence_ref_count) && cue.query_evidence_ref_count >= cue.query_evidence_refs.length)));
    if (!cuesValid || proposal.evidence.reduce((sum, cue) => sum + cue.score_contribution, 0) > proposal.score + 1e-8) continue;
    proposals.push(proposal); seen.add(value);
  }
  return {proposals, rejected: record.feature_proposals.length - proposals.length};
}
function searchFeature(value) {
  searchScope = 'communities'; search.value = value;
  document.querySelector('[name=search-scope][value=communities]').checked = true;
  searchRows(); saveState(); search.focus();
}
function renderFeatureSuggestions() {
  const validated = featureSuggestions(artistAssignments, artistProfile);
  if (!validated) return;
  const section = node('section', undefined, 'style-suggestions'); section.dataset.evidenceRole = 'inferred_feature_proposal';
  section.append(node('h3', 'Inferred style suggestions'), node('span', 'INFERRED · STYLE SUGGESTIONS', 'role-badge'), node('p', 'The model proposes additional musical descriptors from observed source cues and training co-occurrences. Scores are uncalibrated association strengths, not probabilities. These suggestions add no source genre facts or community memberships.', 'section-description'));
  if (validated.rejected) section.append(node('p', 'Some suggestion records could not be verified for display; source observations and community memberships are shown independently.', 'suggestion-notice'));
  if (!validated.proposals.length) section.append(node('p', 'No additional supported style suggestions are available in this snapshot.', 'empty-state'));
  for (const proposal of validated.proposals) {
    const card = node('article', undefined, 'suggestion-card'); card.dataset.featureValue = proposal.value; card.dataset.evidenceRole = 'inferred_feature_proposal'; card.dataset.nativeFact = 'false';
    card.append(node('h4', proposal.value), node('p', `Association score ${proposal.score.toFixed(3)} · uncalibrated`, 'suggestion-score'));
    const evidence = node('details', undefined, 'suggestion-evidence'); evidence.append(node('summary', 'Why this suggestion'));
    evidence.append(node('p', `${count(proposal.training_target_artist_support)} training artists have this descriptor. Showing ${proposal.evidence.length} of ${count(proposal.contributing_cue_count)} contributing source cues.`, 'section-description'));
    const cues = node('ul');
    for (const cue of proposal.evidence) {
      const item = node('li'); item.append(node('strong', cue.value), node('small', `${cue.cue_role === 'proper_genre' ? 'Observed proper-genre cue' : 'Observed music-feature cue'} · ${count(cue.training_joint_artist_support)} training artists have both this cue and the proposed descriptor; ${count(cue.training_cue_artist_support)} have this cue. Contribution ${cue.score_contribution.toFixed(3)}.`));
      const refs = node('details', undefined, 'suggestion-references'), total = cue.query_evidence_ref_count ?? cue.query_evidence_refs.length;
      refs.append(node('summary', `Source evidence references (${cue.query_evidence_refs.length}${total > cue.query_evidence_refs.length ? ` of ${count(total)}` : ''})`));
      const list = node('ul'); for (const ref of cue.query_evidence_refs) list.append(node('li', ref)); refs.append(list); item.append(refs); cues.append(item);
    }
    evidence.append(cues); card.append(evidence, button(`Explore communities with “${proposal.value}”`, 'suggestion-explore', () => searchFeature(proposal.value))); section.append(card);
  }
  detail.append(section);
}
function renderCommunity() {
  detail.replaceChildren(); detail.setAttribute('aria-busy', 'false'); detail.scrollTop = 0;
  detail.append(node('span', `INFERRED · ${level.toUpperCase()} ${selected.coarse_evidence_supported === false ? 'CANDIDATE' : 'COMMUNITY'}`, 'role-badge'), node('h2', `Community descriptors: ${selected.label}`));
  detail.append(node('div', `${count(selected.artist_count)} assigned members · ${count(selected.distinct_profile_count)} distinct feature profiles`, 'count'));
  detail.append(node('p', 'Artists can belong to several communities, so member counts overlap. This descriptor label is derived from source features; the community and memberships are model proposals, not reviewed taxonomy names.', 'section-description'));
  if (level === 'broad' && typeof selected.coarse_evidence_supported === 'boolean') {
    const messages = {
      supported_by_source_and_representation_coherence: 'The fitted core meets source and representation coherence thresholds; musical meaning remains unreviewed.',
      abstained_no_supported_coarse_split: 'The fitted core did not meet source-coherence thresholds, and no supported coarse split was found. It remains an inferred candidate.',
      abstained_insufficient_source_split_gain: 'Source evidence did not improve enough to support another coarse split. Broad coherence remains unestablished.',
      abstained_coarse_budget_exhausted: 'The configured coarse cut limit stopped refinement. Broad coherence remains unestablished.',
    };
    const support = node('p', `${selected.coarse_evidence_supported ? 'Broad evidence support' : 'Unsupported broad candidate'}: ${messages[selected.coarse_support_state] || 'The provenance snapshot does not establish broad coherence for this candidate.'}`, 'coarse-support-state');
    support.textContent += ` Evidence checks use ${Number.isSafeInteger(selected.core_artist_count) ? count(selected.core_artist_count) + ' fitted core artists' : 'fitted core profiles'}, not every overlapping assigned member.`;
    support.dataset.evidenceRole = 'inferred_community_support'; support.dataset.supportState = selected.coarse_support_state || 'unspecified'; detail.append(support);
  }
  const next = children();
  if (next.length) {
    detail.append(node('h3', 'Explore finer communities'));
    const list = node('div', undefined, 'branch-list'); list.dataset.evidenceRole = 'inferred_emergent_music_communities';
    for (const row of next) list.append(communityLink(row)); detail.append(list);
  } else detail.append(node('p', 'No finer supported split is included for this community.', 'empty-state'));
  detail.append(node('h3', 'Features describing this community'), node('p', 'Feature support counts artists across the full retained feature catalog, not just this community. It can exceed the assigned member count.', 'section-description'));
  const features = node('ul', undefined, 'feature-list'); features.dataset.evidenceRole = 'derived_feature_descriptors';
  for (const feature of selected.descriptors ?? []) {
    const item = node('li', feature.value || feature.feature_id);
    item.append(node('small', `${namespaceLabel(feature.namespace)} · ${count(feature.support_count)} catalog artists with this feature`));
    features.append(item);
  }
  if (!features.children.length) features.append(node('li', 'No feature descriptors retained for this community.'));
  detail.append(features, node('h3', 'Model artist examples'), node('p', 'Bounded examples in descending model cosine score, then exact artist ID. Scores are not importance rankings.', 'section-description'));
  const examples = node('div', undefined, 'artist-list'); examples.dataset.evidenceRole = 'inferred_community_membership';
  for (const id of selected.artist_ids ?? []) examples.append(artistLink(id));
  if (!examples.children.length) examples.append(node('p', 'No bounded artist examples included.', 'empty-state'));
  detail.append(examples);
  loadExampleNames(selected, examples, generation);
  const supported = model.quality_evaluated === true ? 'See the provenance receipt for the evaluation scope.' : 'Community quality has not been evaluated.';
  detail.append(node('p', `${supported} Source coverage limits what this model can discover; source-isolated artists remain available through search.`, 'coverage-note'));
}
// Optional metadata examples are fetched only after opening an artist.
let artistExamplesRequest;
function showArtistExamples(artistId) {
  const path = document.body.dataset.artistExamples;
  if (!path) return;
  const section = node('section', undefined, 'artist-work-examples');
  section.dataset.evidenceRole = 'exact_artist_credited_music_examples';
  detail.append(section);
  artistExamplesRequest ||= fetch(path).then(response => {
    if (!response.ok) throw new Error('Examples unavailable');
    return response.json();
  });
  artistExamplesRequest.then(payload => {
    if (!section.isConnected) return;
    const artist = payload.artists?.find(row => row.artist_mbid === artistId);
    if (!artist) { section.remove(); return; }
    section.append(node('p', 'A few credited metadata examples from a bounded source sample.', 'section-description'));
    for (const [key, label, kind] of [['recordings', 'Recordings', 'recording'], ['release_groups', 'Release context', 'release-group']]) {
      const rows = Array.isArray(artist[key]) ? artist[key] : [];
      const list = node('div', undefined, 'artist-list');
      for (const row of rows) {
        if (!row.credited_artist_mbids?.includes(artistId) || !row.evidence_refs?.length || typeof row.entity_id !== 'string' || typeof row.title !== 'string') continue;
        const id = row.entity_id.replace(`musicbrainz:${kind}:`, '');
        if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(id) || row.url !== `https://musicbrainz.org/${kind}/${id}`) continue;
        const link = node('a', row.title, 'artist-row');
        link.href = row.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        link.dataset.entityId = row.entity_id; list.append(link);
      }
      if (list.childElementCount) section.append(node('h3', label), list);
    }
    if (!section.querySelector('a')) section.remove();
  }).catch(() => {
    if (section.isConnected) section.replaceChildren(node('p', 'Music examples unavailable. Try reloading.', 'muted'));
  });
}

function renderArtist() {
  detail.replaceChildren(); detail.scrollTop = 0; detail.setAttribute('aria-busy', String(!artistProfile || !artistAssignments));
  detail.append(button(`← ${selected.label}`, 'back-button', () => navigate(selected.id)));
  if (!artistProfile || !artistAssignments) {
    detail.append(node('h2', artistNames.get(selectedArtist) || 'Loading artist…'), node('p', 'Loading exact source identity and inferred community memberships.', 'muted')); return;
  }
  detail.append(node('span', 'ARTIST · EXACT SOURCE IDENTITY', 'role-badge source'), node('h2', artistProfile.name));
  const sourceLink = node('a', 'View artist on MusicBrainz', 'source-link'); sourceLink.href = `https://musicbrainz.org/artist/${selectedArtist}`;
  sourceLink.target = '_blank'; sourceLink.rel = 'noopener noreferrer'; detail.append(sourceLink); showArtistExamples(selectedArtist);
  detail.append(node('h3', 'Overlapping model memberships'), node('p', 'Uncalibrated cosine scores describe model similarity. They are not probabilities, source genre claims, or importance rankings.', 'section-description'));
  const memberships = node('div', undefined, 'membership-list'); memberships.dataset.evidenceRole = 'inferred_community_membership';
  for (const resolution of LEVELS) {
    const rows = (artistAssignments.memberships ?? []).filter(row => communities.get(row.community_id)?.level === resolution);
    memberships.append(node('h3', `${resolution[0].toUpperCase()}${resolution.slice(1)} communities`));
    if (!rows.length) {
      const skipsSub = resolution === 'sub' && (artistAssignments.memberships ?? []).some(row => {
        const community = communities.get(row.community_id); return community?.level === 'micro' && communities.get(community.parent_id)?.level === 'broad';
      });
      const absence = node('p', skipsSub ? 'This model branch goes directly from broad to micro; no sub assignment is included.' : `No supported ${resolution} assignment for this artist in this model snapshot.`, 'empty-state');
      absence.dataset.evidenceRole = skipsSub ? 'model_resolution_omission' : 'model_abstention'; absence.dataset.level = resolution; memberships.append(absence); continue;
    }
    for (const membership of rows) {
      const community = communities.get(membership.community_id), link = communityLink(community, 'membership-button');
      link.dataset.level = community.level;
      link.lastChild.textContent = Number.isFinite(membership.score) ? `Model score ${membership.score.toFixed(3)}` : 'Model assignment';
      memberships.append(link);
    }
  }
  if (!(artistAssignments.memberships ?? []).length) memberships.append(node('p', 'No supported community assignments for this artist in this model snapshot.', 'empty-state'));
  detail.append(memberships);
  if (artistAssignments.state && artistAssignments.state !== 'assigned') detail.append(node('p', `Model support: ${String(artistAssignments.state).replaceAll('_', ' ')}.`, 'section-description'));
  detail.append(node('h3', 'Separate source observations'), node('span', 'DIRECT · SOURCE RECORD', 'role-badge source'));
  const tags = node('div', undefined, 'source-list'); tags.dataset.evidenceRole = 'direct_source_observation';
  const genres = new Map(source.genres.map(row => [row.id, row]));
  for (const id of artistProfile.genre_ids ?? []) {
    const genre = genres.get(id); if (!genre) continue;
    const link = node('a', genre.name, 'source-button'); link.href = `source-explorer.html#${new URLSearchParams({genre: id, artist: selectedArtist})}`; tags.append(link);
  }
  if (!tags.children.length) tags.append(node('p', 'No direct proper-genre observations retained in this source slice.', 'empty-state'));
  detail.append(tags, node('p', 'The source observations above remain independent of inferred broad, sub, and micro memberships.', 'section-description'));
  renderFeatureSuggestions();
}
function render() {
  renderNavigation(); renderDirectory(); selectedArtist ? renderArtist() : renderCommunity(); redraw();
}
async function ensureProfile(id) {
  if (!validArtist(id)) throw new Error('Unsupported artist identity');
  if (Object.hasOwn(source.artists, id)) return source.artists[id];
  const prefix = id.slice(0, 3), path = `artists/${prefix}.json`;
  if (source.artist_catalog?.profile_path_template.replace('{prefix}', prefix) !== path) throw new Error('Source artist shard path mismatch');
  if (!profiles.has(prefix)) profiles.set(prefix, staticJson(path).then(payload => {
    if (!payload.artists || typeof payload.artists !== 'object') throw new Error('Source artist shard unavailable');
    Object.assign(source.artists, payload.artists); return payload;
  }).catch(error => { profiles.delete(prefix); throw error; }));
  await profiles.get(prefix);
  if (!Object.hasOwn(source.artists, id)) throw new Error('Artist absent from this retained source catalog');
  return source.artists[id];
}
async function ensureAssignments(id) {
  if (Array.isArray(model.artists)) {
    const record = model.artists.find(row => row.artist_mbid === id); if (record) return record;
  }
  const prefix = id.slice(0, 3);
  if (!assignments.has(prefix)) assignments.set(prefix, staticJson(`community-artists/${prefix}.json`, {artists: {}}).catch(error => { assignments.delete(prefix); throw error; }));
  const payload = await assignments.get(prefix);
  const result = payload.artists?.[id] || {memberships: [], state: 'no_retained_model_assignment'};
  if (!Array.isArray(result.memberships) || result.memberships.some(row => row.role !== 'inferred_community_membership' || !communities.has(row.community_id))) throw new Error('Unsupported community membership record');
  return result;
}
async function loadArtist(id, requestedGeneration) {
  try {
    const [profile, membership] = await Promise.all([ensureProfile(id), ensureAssignments(id)]);
    if (requestedGeneration !== generation || selectedArtist !== id) return;
    artistProfile = profile; artistAssignments = membership; artistNames.set(id, profile.name);
    if (membership.memberships.length && !membership.memberships.some(row => row.community_id === selected.id)) {
      const best = [...membership.memberships].sort((a, b) => LEVELS.indexOf(communities.get(b.community_id).level) - LEVELS.indexOf(communities.get(a.community_id).level) || b.score - a.score || a.community_id.localeCompare(b.community_id))[0];
      selected = communities.get(best.community_id); level = selected.level; renderNavigation(); renderDirectory(); saveState(true); fit();
    }
    renderArtist(); redraw();
  } catch (error) {
    if (requestedGeneration !== generation || selectedArtist !== id) return;
    detail.setAttribute('aria-busy', 'false'); detail.replaceChildren(button(`← ${selected.label}`, 'back-button', () => navigate(selected.id)), node('h2', 'Artist model details unavailable'), node('p', `The static source or model record could not load: ${error.message}`, 'profile-error'), button('Retry artist details', 'more-button', () => loadArtist(id, generation)));
  }
}
async function loadExampleNames(community, container, requestedGeneration) {
  const ids = community.artist_ids ?? [];
  await Promise.allSettled(ids.map(async id => {
    try {
      const profile = await ensureProfile(id); artistNames.set(id, profile.name);
      if (requestedGeneration !== generation || !container.isConnected) return;
      const link = [...container.querySelectorAll('[data-artist-id]')].find(candidate => candidate.dataset.artistId === id);
      if (link) link.firstChild.textContent = profile.name;
    } catch {
      if (!container.isConnected) return;
      const link = [...container.querySelectorAll('[data-artist-id]')].find(candidate => candidate.dataset.artistId === id);
      if (link) link.firstChild.textContent = 'Source artist name unavailable';
    }
  }));
}
async function searchRows() {
  const query = search.value.trim().toLocaleLowerCase(), requested = ++searchGeneration;
  results.replaceChildren(); searchIndex = -1; results.hidden = !query;
  if (!query) return;
  try {
    let matches;
    if (searchScope === 'artists') {
      results.append(node('p', 'Searching source artists…', 'search-empty'));
      if (!artistIndexPromise) artistIndexPromise = staticJson('artist-search.json');
      const index = await artistIndexPromise;
      matches = index.artists.filter(row => row[1].toLocaleLowerCase().includes(query) || row[0].toLocaleLowerCase().includes(query));
      if (requested !== searchGeneration || searchScope !== 'artists') return;
      results.replaceChildren();
      for (const [id, name] of matches.slice(0, 50)) {
        artistNames.set(id, name); const item = button('', 'search-result', () => navigate(selected.id, id)); item.dataset.artistId = id;
        item.append(node('span', name), node('small', 'Artist model →')); results.append(item);
      }
    } else {
      matches = model.communities.filter(row => row.label.toLocaleLowerCase().includes(query) || (row.descriptors ?? []).some(feature => typeof feature.value === 'string' && feature.value.toLocaleLowerCase().includes(query)));
      for (const row of matches.slice(0, 50)) {
        const item = button('', 'search-result', () => navigate(row.id)); item.dataset.communityId = row.id;
        item.append(node('span', row.label), node('small', row.level)); results.append(item);
      }
    }
    if (!matches.length) results.append(node('p', `No matching ${searchScope === 'artists' ? 'source artists' : 'model communities'}.`, 'search-empty'));
    if (matches.length > 50) results.append(node('p', `${count(matches.length)} matches · first 50 shown. Refine your search.`, 'search-empty'));
    $('#search-status').textContent = `${count(matches.length)} matches, showing ${Math.min(50, matches.length)}.`;
  } catch (error) {
    if (requested !== searchGeneration) return;
    artistIndexPromise = null; results.replaceChildren(node('p', `Static search unavailable: ${error.message}`, 'search-empty'), button('Retry search', 'search-more', searchRows));
  }
}
const redraw = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(draw); };
const screen = row => ({x: row.x * camera.scale + camera.x, y: row.y * camera.scale + camera.y});
function fit() {
  const rows = branchNodes().filter(positioned);
  if (!rows.length) { redraw(); return; }
  const minX = Math.min(...rows.map(row => row.x)), maxX = Math.max(...rows.map(row => row.x));
  const minY = Math.min(...rows.map(row => row.y)), maxY = Math.max(...rows.map(row => row.y));
  const top = innerWidth <= 1050 ? innerWidth <= 700 ? 355 : 330 : 280;
  fitScale = Math.min((width - 115) / Math.max(.15, maxX - minX), Math.max(100, height - top - 125) / Math.max(.15, maxY - minY));
  camera = {scale: fitScale, x: width / 2 - (minX + maxX) / 2 * fitScale, y: top + (height - top - 115) / 2 - (minY + maxY) / 2 * fitScale}; redraw();
}
function zoom(factor, x = width / 2, y = (height + 250) / 2) {
  const next = Math.min(fitScale * 20, Math.max(fitScale * .4, camera.scale * factor)), ratio = next / camera.scale;
  camera.x = x - (x - camera.x) * ratio; camera.y = y - (y - camera.y) * ratio; camera.scale = next; redraw();
}
function draw() {
  context.clearRect(0, 0, width, height); labelTargets = [];
  if (!model || view !== 'map') return;
  const rows = branchNodes().filter(positioned).sort((a, b) => Number(b.id === hovered?.id) - Number(a.id === hovered?.id) || Number(b.id === selected.id) - Number(a.id === selected.id) || b.artist_count - a.artist_count);
  const membershipIds = new Set(artistAssignments?.memberships?.map(row => row.community_id) ?? []), boxes = [];
  for (const row of rows) {
    const point = screen(row); if (point.x < -10 || point.x > width + 10 || point.y < 280 || point.y > height - 100) continue;
    const active = row.id === selected.id, hoveredRow = row.id === hovered?.id, related = membershipIds.has(row.id);
    context.beginPath(); context.arc(point.x, point.y, active ? 6 : related ? 5 : 3.5, 0, Math.PI * 2);
    context.fillStyle = active ? '#cc552f' : related ? '#986b38' : '#599b84'; context.fill();
    context.font = `${active ? '650' : '450'} ${active ? 15 : 12}px system-ui`;
    const textWidth = Math.min(context.measureText(row.label).width, width - 40), x = Math.max(14, Math.min(width - textWidth - 14, point.x + 9)), y = point.y + 4;
    const box = {x: x - 3, y: y - 13, w: textWidth + 7, h: 19, id: row.id};
    if (!active && !hoveredRow && boxes.some(other => box.x < other.x + other.w && box.x + box.w > other.x && box.y < other.y + other.h && box.y + box.h > other.y)) continue;
    boxes.push(box); labelTargets.push(box); context.fillStyle = '#f6f8f0ee'; context.fillRect(box.x, box.y, box.w, box.h);
    context.fillStyle = active ? '#ab4324' : related ? '#936134' : '#305f4c'; context.fillText(row.label, x, y, textWidth);
  }
}
function nearest(x, y) {
  for (const target of labelTargets.toReversed()) if (x >= target.x && x <= target.x + target.w && y >= target.y && y <= target.y + target.h) return communities.get(target.id);
  let best, distance = 18;
  for (const row of branchNodes().filter(positioned)) {
    const point = screen(row), delta = Math.hypot(point.x - x, point.y - y); if (delta < distance) { best = row; distance = delta; }
  }
  return best;
}

for (const control of document.querySelectorAll('.level-nav [data-level]')) control.addEventListener('click', () => { const target = targetForLevel(control.dataset.level); if (target) navigate(target.id); });
for (const input of document.querySelectorAll('[name=search-scope]')) input.addEventListener('change', () => { searchScope = input.value; searchRows(); saveState(); });
search.addEventListener('input', () => { searchRows(); saveState(true); });
search.addEventListener('keydown', event => {
  const controls = [...results.querySelectorAll('button')];
  if (event.key === 'Escape') results.hidden = true;
  if (event.key === 'ArrowDown') { event.preventDefault(); searchIndex = 0; controls[0]?.focus(); }
  if (event.key === 'Enter' && !results.hidden) { event.preventDefault(); controls[Math.max(0, searchIndex)]?.click(); }
});
results.addEventListener('keydown', event => {
  const controls = [...results.querySelectorAll('button')], index = controls.indexOf(document.activeElement);
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); searchIndex = Math.max(0, Math.min(controls.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1))); controls[searchIndex]?.focus(); }
  if (event.key === 'Escape') { results.hidden = true; search.focus(); }
});
$('#view-map').addEventListener('click', () => { view = 'map'; render(); fit(); saveState(); });
$('#view-list').addEventListener('click', () => { view = 'list'; render(); saveState(); });
$('#directory-sort').addEventListener('change', event => { directorySort = event.target.value; renderDirectory(); saveState(); });
$('#fit-map').addEventListener('click', fit); $('#zoom-out').addEventListener('click', () => zoom(1 / 1.4)); $('#zoom-in').addEventListener('click', () => zoom(1.4));
$('#about-toggle').addEventListener('click', event => { const about = $('#about'); about.hidden = !about.hidden; event.currentTarget.setAttribute('aria-expanded', String(!about.hidden)); if (!about.hidden) about.scrollIntoView({block: 'nearest', behavior: 'smooth'}); });
document.addEventListener('keydown', event => { if (event.key === '/' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) { event.preventDefault(); search.focus(); } });
document.addEventListener('pointerdown', event => { if (!event.target.closest('.search-box')) results.hidden = true; });
canvas.addEventListener('wheel', event => { event.preventDefault(); const rect = canvas.getBoundingClientRect(); zoom(Math.exp(-event.deltaY * .002), event.clientX - rect.left, event.clientY - rect.top); }, {passive: false});
canvas.addEventListener('pointerdown', event => { drag = {x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY}; canvas.setPointerCapture(event.pointerId); });
canvas.addEventListener('pointermove', event => {
  if (drag) { camera.x += event.clientX - drag.x; camera.y += event.clientY - drag.y; drag.x = event.clientX; drag.y = event.clientY; }
  else { const rect = canvas.getBoundingClientRect(); hovered = nearest(event.clientX - rect.left, event.clientY - rect.top); canvas.title = hovered?.label || ''; }
  redraw();
});
canvas.addEventListener('pointerup', event => { if (drag && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 5) { const rect = canvas.getBoundingClientRect(), row = nearest(event.clientX - rect.left, event.clientY - rect.top); if (row) navigate(row.id); } drag = null; });
canvas.addEventListener('pointercancel', () => { drag = null; });
canvas.addEventListener('keydown', event => {
  const actions = {'+': () => zoom(1.3), '=': () => zoom(1.3), '-': () => zoom(1 / 1.3), Home: fit, ArrowLeft: () => { camera.x += 40; }, ArrowRight: () => { camera.x -= 40; }, ArrowUp: () => { camera.y += 40; }, ArrowDown: () => { camera.y -= 40; }};
  if (actions[event.key]) { event.preventDefault(); actions[event.key](); redraw(); }
});
window.addEventListener('popstate', restoreState); window.addEventListener('hashchange', restoreState);
new ResizeObserver(() => { const rect = canvas.getBoundingClientRect(); if (!rect.width || !rect.height) return; width = rect.width; height = rect.height; const ratio = devicePixelRatio || 1; canvas.width = width * ratio; canvas.height = height * ratio; context.setTransform(ratio, 0, 0, ratio, 0, 0); fit(); }).observe(canvas);

try {
  [model, source] = await Promise.all([staticJson('community-data.json'), staticJson('data.json')]);
  if (model.role !== 'inferred_emergent_music_communities' || model.public_export_authorized === true || source.scope !== 'local_research_only' || source.public_export_authorized !== false) throw new Error('Unsupported local model boundary');
  if (!Array.isArray(model.communities) || !model.communities.length) throw new Error('No retained emerging communities');
  communities = new Map(model.communities.map(row => [row.id, row]));
  if (communities.size !== model.communities.length || model.communities.some(row => !LEVELS.includes(row.level) || row.label_origin !== 'derived_feature_descriptors' || (row.parent_id && !communities.has(row.parent_id)) || (row.child_ids ?? []).some(id => !communities.has(id)))) throw new Error('Unsupported model community identity or hierarchy');
  Object.assign(source.artists, model.artist_profiles ?? {});
  for (const [id, profile] of Object.entries(model.artist_profiles ?? {})) artistNames.set(id, profile.name);
  const totals = LEVELS.map(resolution => `${count(model.communities.filter(row => row.level === resolution).length)} ${resolution}`).join(' · ');
  $('#model-corpus-status').textContent = `${totals} · inferred from open metadata`;
  restoreState(); document.documentElement.dataset.communityPreviewReady = 'true';
} catch (error) {
  detail.replaceChildren(node('h2', 'Emerging music model unavailable'), node('p', `The static model could not load: ${error.message}`, 'profile-error'));
  $('#model-corpus-status').textContent = 'Local model data unavailable';
}
