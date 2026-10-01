/** Source-bound named style atlas; geometry and proposals are never native genre facts. */
const $ = selector => document.querySelector(selector);
const canvas = $('#style-map'), context = canvas.getContext('2d'), detail = $('#detail');
const search = $('#atlas-search'), results = $('#search-results');
const ROLES = ['observed_artist_feature', 'credited_release_context', 'inferred_feature_proposal'];
const ROLE_LABELS = {observed_artist_feature: 'Artist observations', credited_release_context: 'Release context', inferred_feature_proposal: 'Style suggestions'};
const ROLE_SHORT = {observed_artist_feature: 'Artists', credited_release_context: 'Releases', inferred_feature_proposal: 'Suggestions'};
const TIERS = ['supported', 'all', 'dictionary_named_style', 'repeated_source_candidate', 'raw_source_candidate'];
const TIER_LABELS = {dictionary_named_style: 'Dictionary name match', repeated_source_candidate: 'Repeated source candidate', raw_source_candidate: 'Raw source candidate'};
const count = number => new Intl.NumberFormat('en').format(number ?? 0);
const validArtist = id => typeof id === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(id);
const validStyle = id => typeof id === 'string' && /^style-[a-f0-9]{24}$/.test(id);
const positioned = style => Number.isFinite(style.x) && Number.isFinite(style.y);
const canonical = value => value.trim().toLocaleLowerCase().replaceAll(/\s+/g, ' ');
let data, styles, selected, selectedArtist, artistProfile, artistEvidence, view = 'map', tier = 'supported', evidence = 'all', placement = 'all', sort = 'name';
let cohort = ROLES[0], page = 0, directoryPage = 0, searchScope = 'styles';
let generation = 0, searchGeneration = 0, searchIndex = -1, artistSearch;
let width = 1, height = 1, camera = {scale: 1, x: 0, y: 0}, fitScale = 1, drag, hovered, targets = [], frame;
const details = new Map(), pages = new Map(), artistShards = new Map();
const DIRECTORY_SIZE = 200;

function node(tag, text, className) {
  const result = document.createElement(tag); if (text !== undefined) result.textContent = text; if (className) result.className = className; return result;
}
function button(text, className, action) {
  const result = node('button', text, className); result.type = 'button'; result.addEventListener('click', action); return result;
}
async function json(path) {
  const response = await fetch(path); if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json();
}
function hash(style = selected?.id, artist = selectedArtist) {
  const state = new URLSearchParams();
  if (style) state.set('style', style); if (artist) state.set('artist', artist);
  if (view !== 'map') state.set('view', view); if (tier !== 'supported') state.set('tier', tier);
  if (evidence !== 'all') state.set('evidence', evidence); if (placement !== 'all') state.set('placement', placement);
  if (sort !== 'name') state.set('sort', sort); if (cohort !== ROLES[0]) state.set('cohort', cohort);
  if (page) state.set('page', page + 1); if (directoryPage) state.set('directoryPage', directoryPage + 1);
  if (search.value.trim()) state.set('q', search.value.trim()); if (searchScope !== 'styles') state.set('scope', searchScope);
  return `#${state}`;
}
function save(replace = false) { const next = hash(); if (next !== location.hash) history[replace ? 'replaceState' : 'pushState']({}, '', next); }
function included(style) {
  return (tier === 'all' || (tier === 'supported' ? style.default_visible !== false : style.evidence_tier === tier)) && (evidence === 'all' || style.counts[evidence] > 0) && (placement === 'all' || (placement === 'positioned' ? positioned(style) : !positioned(style)));
}
function filtered() { return data.styles.filter(included); }
function reveal(style) {
  if (!included(style)) { tier = 'all'; evidence = 'all'; placement = 'all'; }
  if (!positioned(style)) view = 'list';
  if (view === 'list') { const rows = directoryRows(); directoryPage = Math.floor(rows.findIndex(row => row.id === style.id) / DIRECTORY_SIZE); }
}
function navigateStyle(id) {
  const row = styles.get(id); if (!row) return;
  selected = row; selectedArtist = null; artistProfile = null; cohort = ROLES[0]; page = 0; generation++;
  reveal(row); results.hidden = true; render(); save(); if (positioned(row)) focusStyle(row);
}
function navigateArtist(id, style = null) {
  id = String(id).toLowerCase(); if (!validArtist(id)) return;
  selected = styles.get(style) || null; selectedArtist = id; artistProfile = null; generation++;
  results.hidden = true; render(); save(); loadArtist(generation);
}
function overview() { selected = null; selectedArtist = null; artistProfile = null; page = 0; generation++; render(); fit(); save(); }
function restore() {
  if (!data) return; const state = new URLSearchParams(location.hash.slice(1));
  view = state.get('view') === 'list' ? 'list' : 'map'; tier = TIERS.includes(state.get('tier')) ? state.get('tier') : 'supported';
  evidence = ROLES.includes(state.get('evidence')) ? state.get('evidence') : 'all'; placement = ['positioned', 'unplaced'].includes(state.get('placement')) ? state.get('placement') : 'all';
  sort = ROLES.includes(state.get('sort')) ? state.get('sort') : 'name'; cohort = ROLES.includes(state.get('cohort')) ? state.get('cohort') : ROLES[0];
  page = Math.max(0, Math.min(100000, Number.parseInt(state.get('page') || '1', 10) - 1)) || 0;
  directoryPage = Math.max(0, Number.parseInt(state.get('directoryPage') || '1', 10) - 1) || 0;
  searchScope = state.get('scope') === 'artists' ? 'artists' : 'styles'; search.value = state.get('q') || '';
  selected = styles.get(state.get('style')) || null; const artist = (state.get('artist') || '').toLowerCase(); selectedArtist = validArtist(artist) ? artist : null;
  artistProfile = null; generation++; if (selected) reveal(selected); render(); selected && positioned(selected) ? focusStyle(selected) : fit();
  if (selectedArtist) loadArtist(generation);
}
function styleLink(row, className = 'style-evidence-link') {
  const link = node('a', row.name, className); link.href = hash(row.id, null); link.dataset.styleId = row.id;
  link.addEventListener('click', event => { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigateStyle(row.id); }); return link;
}
function artistLink(row) {
  const link = node('a', undefined, 'artist-row'); link.href = hash(selected.id, row.artist_mbid); link.dataset.artistId = row.artist_mbid;
  link.append(node('span', row.name), node('small', cohort === ROLES[2] ? `Score ${row.score.toFixed(3)}` : 'Exact ID →'));
  link.addEventListener('click', event => { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigateArtist(row.artist_mbid, selected.id); }); return link;
}
function controls() {
  $('#tier-filter').value = tier; $('#evidence-filter').value = evidence; $('#placement-filter').value = placement; $('#directory-sort').value = sort; $('#search-scope').value = searchScope;
  const rows = filtered(), placed = rows.filter(positioned).length;
  if (!placed && rows.length) view = 'list';
  $('#map-view').disabled = !placed; $('#map-view').setAttribute('aria-pressed', String(view === 'map')); $('#list-view').setAttribute('aria-pressed', String(view === 'list'));
  canvas.hidden = view !== 'map'; $('.map-controls').hidden = view !== 'map'; $('#style-directory').hidden = view !== 'list'; $('#directory-pager').hidden = view !== 'list'; $('#sort-label').hidden = view !== 'list';
  canvas.parentElement.style.setProperty('--toolbar-space', `${topSpace()}px`);
  $('#atlas-status').textContent = `${count(rows.length)} candidate labels · ${count(placed)} positioned${rows.length > placed ? ` · ${count(rows.length - placed)} unplaced, available in List` : ''}. Search includes every source candidate.`;
}
function directoryRows() { return filtered().sort((a, b) => (sort === 'name' ? 0 : b.counts[sort] - a.counts[sort]) || a.name.localeCompare(b.name) || a.id.localeCompare(b.id)); }
function pager(index, total, change, className = 'pagination') {
  const result = node('div', undefined, className); result.setAttribute('aria-label', 'Pagination');
  for (const [label, target] of [['First', 0], ['Previous', index - 1], ['Next', index + 1], ['Last', total - 1]]) {
    const control = button(label, '', () => change(target)); control.disabled = target < 0 || target >= total || target === index; result.append(control);
  }
  const label = node('label', 'Page'), input = node('input'); input.type = 'number'; input.min = '1'; input.max = String(total); input.value = String(index + 1); input.setAttribute('aria-label', 'Page number');
  input.addEventListener('change', () => { const next = Number.parseInt(input.value, 10) - 1; if (Number.isFinite(next)) change(Math.max(0, Math.min(total - 1, next))); });
  label.append(input, node('span', `of ${count(total)}`)); result.append(label); return result;
}
function renderDirectory() {
  if (view !== 'list') return; const rows = directoryRows(), total = Math.max(1, Math.ceil(rows.length / DIRECTORY_SIZE)); directoryPage = Math.min(directoryPage, total - 1);
  const list = $('#style-directory'); list.replaceChildren();
  for (const row of rows.slice(directoryPage * DIRECTORY_SIZE, (directoryPage + 1) * DIRECTORY_SIZE)) {
    const link = styleLink(row, 'style-card'); link.append(node('small', `${count(row.source_artist_support)} source artists · ${TIER_LABELS[row.evidence_tier] || 'Source candidate'}${positioned(row) ? '' : ' · unplaced'}`));
    if (row.id === selected?.id) link.setAttribute('aria-current', 'true'); list.append(link);
  }
  if (!rows.length) list.append(node('p', 'No candidate labels match these filters.', 'empty-state'));
  $('#directory-pager').replaceChildren(pager(directoryPage, total, next => { directoryPage = next; renderDirectory(); list.scrollTop = 0; save(); }));
}
function renderOverview() {
  detail.replaceChildren(node('span', 'SOURCE-BASED · CANDIDATE LABELS', 'badge'), node('h1', 'Explore named musical styles.'), node('p', 'Select a label on the map, search for a style or artist, or browse every candidate in List.', 'muted'));
  detail.append(node('h3', 'Three distinct evidence roles'));
  for (const role of ROLES) detail.append(node('span', ROLE_LABELS[role], `badge ${role}`), node('p', roleDescription(role), 'section-description'));
  detail.append(node('p', 'The default view contains dictionary names and repeated source candidates. Raw source labels remain searchable and available with the Labels filter. Label support uses source artists; inferred suggestions do not improve a label’s evidence tier.', 'section-description'));
}
function roleDescription(role) {
  return role === ROLES[0] ? 'Artists whose source records include this genre or tag. Observations do not validate a style taxonomy.' : role === ROLES[1] ? 'Artists credited on releases carrying this descriptor. Release context does not establish an artist’s style.' : 'Additional model suggestions, separate from all observed values. Scores are uncalibrated association strengths, not probabilities.';
}
function renderStyle() {
  detail.replaceChildren(); detail.scrollTop = 0; detail.setAttribute('aria-busy', String(!selected.cohorts));
  detail.append(button('← all styles', 'back-button', overview), node('span', TIER_LABELS[selected.evidence_tier] || 'CANDIDATE NAMED STYLE', 'badge'), node('h2', selected.name));
  detail.append(node('p', `${count(selected.source_artist_support)} distinct source artists across source feature and release-context roles. Role counts can overlap.`, 'section-description'));
  detail.append(node('p', 'This source-derived name is a candidate label, not a validated taxonomy or a native genre membership.', 'section-description'));
  if (selected.aliases?.some(alias => alias !== selected.name)) { const aliases = node('details', undefined, 'aliases'); aliases.append(node('summary', 'Source label variants'), node('p', selected.aliases.join(' · '))); detail.append(aliases); }
  if (!positioned(selected)) detail.append(node('p', selected.layout_status === 'abstained_identical_source_support' ? 'Unplaced: its source support cannot distinguish its geometry from another label. Every artist cohort remains browsable.' : 'Unplaced: no distinct supported source neighbors for geometry. Every artist cohort remains browsable.', 'empty-state'));
  if (selected.native_genre_ids?.length) {
    const links = node('div', undefined, 'native-links');
    for (const id of selected.native_genre_ids.filter(validArtist)) { const link = node('a', 'Native dictionary entry ↗'); link.href = `https://musicbrainz.org/genre/${id}`; link.target = '_blank'; link.rel = 'noopener noreferrer'; links.append(link); }
    detail.append(links, node('p', 'Exact dictionary-name match only; it does not establish artist membership.', 'section-description'));
  }
  const tabs = node('nav', undefined, 'cohort-tabs'); tabs.setAttribute('aria-label', 'Artist evidence cohorts');
  for (const role of ROLES) {
    const control = button(ROLE_SHORT[role], '', () => { cohort = role; page = 0; generation++; renderStyle(); save(); loadStyle(generation); });
    control.dataset.cohortRole = role; control.setAttribute('aria-pressed', String(cohort === role)); control.append(node('span', count(selected.counts[role]))); tabs.append(control);
  }
  detail.append(tabs, node('h3', ROLE_LABELS[cohort]), node('p', roleDescription(cohort), 'section-description'), node('p', 'Alphabetical by source name, then exact artist ID; not a relevance ranking.', 'section-description'));
  const container = node('div', undefined, 'cohort-content'); container.dataset.evidenceRole = cohort; detail.append(container);
  if (!selected.cohorts) container.append(node('p', 'Loading complete artist cohorts…', 'muted'));
}
async function ensureStyle(id) {
  const row = styles.get(id); if (row.cohorts) return row;
  const path = `styles/${id}.json`; if (row.detail_path !== path) throw new Error('Unsupported style detail path');
  if (!details.has(id)) details.set(id, json(path).then(payload => {
    if (payload.id !== id || payload.role !== 'candidate_named_style' || payload.native_fact !== false || payload.name !== row.name || !payload.cohorts) throw new Error('Style detail identity or role mismatch');
    for (const role of ROLES) { const record = payload.cohorts[role]; if (!record || record.artist_count !== row.counts[role] || !Array.isArray(record.pages) || record.pages.length !== Math.ceil(record.artist_count / data.page_size) || record.pages.some((path, index) => path !== `cohorts/${id}/${role}/${index}.json`)) throw new Error('Cohort page binding mismatch'); }
    Object.assign(row, payload); return row;
  }).catch(error => { details.delete(id); throw error; }));
  return details.get(id);
}
async function loadStyle(requested) {
  const id = selected?.id, role = cohort; if (!id || selectedArtist) return;
  try {
    const row = await ensureStyle(id); if (requested !== generation || selected?.id !== id || selectedArtist) return;
    renderStyle(); const record = row.cohorts[role], container = $('.cohort-content');
    if (!record.artist_count) { detail.setAttribute('aria-busy', 'false'); container.replaceChildren(node('p', 'No artists in this evidence cohort.', 'empty-state')); return; }
    detail.setAttribute('aria-busy', 'true'); container.replaceChildren(node('p', 'Loading artist page…', 'muted'));
    page = Math.min(page, record.pages.length - 1); const path = record.pages[page]; save(true);
    if (!pages.has(path)) pages.set(path, json(path).catch(error => { pages.delete(path); throw error; }));
    const payload = await pages.get(path); if (requested !== generation || selected?.id !== id || cohort !== role || selectedArtist) return;
    if (payload.style_id !== id || payload.role !== role || payload.native_fact !== false || payload.page !== page || payload.artist_count !== record.artist_count || !Array.isArray(payload.artists) || payload.artists.length !== Math.min(data.page_size, record.artist_count - page * data.page_size)) throw new Error('Artist cohort identity or role mismatch');
    if (payload.artists.some(artist => !validArtist(artist.artist_mbid) || typeof artist.name !== 'string' || artist.profile_path !== `artists/${artist.artist_mbid.slice(0, 3)}.json` || (role === ROLES[2] && (!Number.isFinite(artist.score) || artist.score <= 0)))) throw new Error('Unsupported artist cohort record');
    detail.setAttribute('aria-busy', 'false');
    container.replaceChildren(node('p', `${count(page * data.page_size + 1)}–${count(page * data.page_size + payload.artists.length)} of ${count(record.artist_count)} artists`, 'section-description'));
    const list = node('div', undefined, 'artist-list'); for (const artist of payload.artists) list.append(artistLink(artist)); container.append(list);
    if (record.pages.length > 1) container.append(pager(page, record.pages.length, next => { page = next; generation++; save(); loadStyle(generation); }));
  } catch (error) {
    if (requested !== generation || selected?.id !== id || selectedArtist) return;
    detail.setAttribute('aria-busy', 'false'); const container = $('.cohort-content');
    container?.replaceChildren(node('p', `Static cohort could not load: ${error.message}`, 'error-state'), button('Retry cohort', 'retry', () => loadStyle(generation)));
  }
}
function sourceFeatureLabel(namespace) { return {artist_genre: 'Artist genre observation', artist_tag: 'Artist tag', release_genre: 'Release genre observation', release_tag: 'Release tag'}[namespace] || 'Source observation'; }
function evidenceCard(entry) {
  const card = node('article', undefined, `evidence-card ${entry.role}`); card.dataset.evidenceRole = entry.role; card.dataset.nativeFact = 'false'; card.dataset.styleId = entry.style_id;
  card.append(styleLink(styles.get(entry.style_id)));
  const disclosure = node('details'); disclosure.append(node('summary', entry.role === ROLES[2] ? 'Source cues and training support' : 'Source feature evidence'));
  const list = node('ul');
  if (entry.role === ROLES[2]) {
    card.append(node('small', `Association score ${entry.score.toFixed(3)} · uncalibrated`));
    disclosure.append(node('p', `${count(entry.training_target_artist_support)} training artists have the proposed descriptor. Showing ${entry.evidence.length} of ${count(entry.contributing_cue_count)} contributing cues.`));
    for (const cue of entry.evidence) {
      const item = node('li', `${cue.value} · ${count(cue.training_joint_artist_support)} training artists have both values; ${count(cue.training_cue_artist_support)} have the cue.`);
      item.append(node('small', `${cue.cue_role === 'proper_genre' ? 'Observed genre cue' : 'Observed music-feature cue'} · contribution ${cue.score_contribution.toFixed(3)}`));
      const refs = node('details'); refs.append(node('summary', `Source references (${cue.query_evidence_refs.length} of ${count(cue.query_evidence_ref_count ?? cue.query_evidence_refs.length)})`), node('p', cue.query_evidence_refs.join('\n'))); item.append(refs); list.append(item);
    }
  } else {
    card.append(node('small', [...new Set(entry.source_features.map(feature => sourceFeatureLabel(feature.namespace)))].join(' · ')));
    for (const feature of entry.source_features) { const item = node('li', `${sourceFeatureLabel(feature.namespace)}: ${feature.value}`); item.append(node('small', feature.evidence_refs.join('\n'))); list.append(item); }
  }
  disclosure.append(list); card.append(disclosure); return card;
}
function validatedMemberships(profile) {
  const records = Array.isArray(profile.style_memberships) ? profile.style_memberships : [], accepted = [], known = new Set();
  const integer = value => Number.isSafeInteger(value) && value > 0, positive = value => Number.isFinite(value) && value > 0, sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  for (const entry of records) {
    const style = styles.get(entry?.style_id);
    if (!style || entry.value !== style.name || entry.native_fact !== false || !ROLES.slice(0, 2).includes(entry.role) || !Array.isArray(entry.source_features) || !entry.source_features.length) continue;
    if (!entry.source_features.every(feature => feature && ['artist_genre', 'artist_tag', 'release_genre', 'release_tag'].includes(feature.namespace) && (feature.namespace.startsWith('release_') === (entry.role === ROLES[1])) && typeof feature.value === 'string' && positive(feature.weight) && Array.isArray(feature.evidence_refs) && feature.evidence_refs.length && feature.evidence_refs.every(ref => typeof ref === 'string' && ref.length))) continue;
    accepted.push(entry); known.add(canonical(entry.value));
  }
  const seen = new Set();
  for (const entry of records) {
    const style = styles.get(entry?.style_id);
    if (!style || entry.value !== style.name || entry.role !== ROLES[2] || entry.native_fact !== false || entry.score_calibrated !== false || !positive(entry.score) || entry.feature_id !== `music:${entry.value}` || known.has(canonical(entry.value)) || seen.has(entry.style_id) || !sha(entry.training_source_sha256) || entry.training_input_sha256 !== entry.training_source_sha256 || !sha(entry.source_model_sha256) || !integer(entry.training_target_artist_support) || !integer(entry.contributing_cue_count) || !integer(entry.explanation_cue_limit) || entry.explanation_cue_limit > 5 || !Array.isArray(entry.evidence) || !entry.evidence.length || entry.evidence.length > entry.explanation_cue_limit || entry.contributing_cue_count < entry.evidence.length) continue;
    if (!entry.evidence.every(cue => cue && ['music', 'proper_genre'].includes(cue.cue_role) && typeof cue.value === 'string' && known.has(canonical(cue.value)) && positive(cue.score_contribution) && integer(cue.training_joint_artist_support) && integer(cue.training_cue_artist_support) && cue.training_joint_artist_support <= cue.training_cue_artist_support && cue.training_joint_artist_support <= entry.training_target_artist_support && Array.isArray(cue.query_evidence_refs) && cue.query_evidence_refs.length && cue.query_evidence_refs.every(ref => typeof ref === 'string' && ref.length) && (cue.query_evidence_ref_count === undefined || (integer(cue.query_evidence_ref_count) && cue.query_evidence_ref_count >= cue.query_evidence_refs.length)))) continue;
    if (entry.evidence.reduce((sum, cue) => sum + cue.score_contribution, 0) > entry.score + 1e-8) continue;
    accepted.push(entry); seen.add(entry.style_id);
  }
  return {accepted, rejected: records.length - accepted.length};
}
function renderArtist() {
  detail.replaceChildren(); detail.scrollTop = 0; detail.setAttribute('aria-busy', String(!artistProfile));
  detail.append(button(selected ? `← ${selected.name}` : '← all styles', 'back-button', () => selected ? navigateStyle(selected.id) : overview()));
  if (!artistProfile) { detail.append(node('h2', 'Loading artist…'), node('p', 'Loading exact source identity and complete typed style evidence.', 'muted')); return; }
  detail.append(node('span', 'ARTIST · EXACT SOURCE IDENTITY', 'badge'), node('h2', artistProfile.name));
  const provider = node('a', 'Artist on MusicBrainz ↗', 'provider-link'); provider.href = `https://musicbrainz.org/artist/${selectedArtist}`; provider.target = '_blank'; provider.rel = 'noopener noreferrer'; detail.append(provider);
  const validated = artistEvidence || validatedMemberships(artistProfile);
  if (validated.rejected) detail.append(node('p', 'Some evidence records could not be verified for display. Valid source observations and proposals are shown separately.', 'error-state'));
  for (const role of ROLES) {
    const section = node('section', undefined, 'artist-evidence'); section.dataset.evidenceRole = role;
    section.append(node('h3', ROLE_LABELS[role]), node('span', role === ROLES[2] ? 'INFERRED · NOT A SOURCE FACT' : role === ROLES[1] ? 'SOURCE · RELEASE CREDIT CONTEXT' : 'SOURCE · ARTIST OBSERVATIONS', `badge ${role}`), node('p', roleDescription(role), 'section-description'));
    const rows = validated.accepted.filter(entry => entry.role === role).sort((a, b) => (role === ROLES[2] ? b.score - a.score : 0) || a.value.localeCompare(b.value));
    const list = node('div', undefined, 'evidence-list'); for (const entry of rows) list.append(evidenceCard(entry));
    if (!rows.length) list.append(node('p', role === ROLES[2] ? 'No additional supported style suggestions in this snapshot.' : 'No observations retained for this evidence role.', 'empty-state'));
    section.append(list); detail.append(section);
  }
  redraw();
}
async function loadArtist(requested) {
  const id = selectedArtist;
  try {
    const prefix = id.slice(0, 3); if (!artistShards.has(prefix)) artistShards.set(prefix, json(`artists/${prefix}.json`).catch(error => { artistShards.delete(prefix); throw error; }));
    const payload = await artistShards.get(prefix); if (requested !== generation || selectedArtist !== id) return;
    const profile = payload.artists?.[id]; if (!profile || profile.artist_mbid !== id || typeof profile.name !== 'string' || !Array.isArray(profile.style_memberships)) throw new Error('Artist identity or typed evidence unavailable');
    artistProfile = profile; artistEvidence = validatedMemberships(profile); renderArtist();
  } catch (error) {
    if (requested !== generation || selectedArtist !== id) return;
    detail.setAttribute('aria-busy', 'false'); detail.append(node('p', `Static artist profile could not load: ${error.message}`, 'error-state'), button('Retry artist', 'retry', () => loadArtist(generation)));
  }
}
function render() { controls(); renderDirectory(); if (selectedArtist) renderArtist(); else if (selected) { renderStyle(); loadStyle(generation); } else renderOverview(); redraw(); }
async function searchRows() {
  const query = search.value.trim().toLocaleLowerCase(), requested = ++searchGeneration, scope = searchScope; results.replaceChildren(); results.hidden = !query; searchIndex = -1; if (!query) return;
  try {
    let matches;
    if (scope === 'styles') {
      matches = data.styles.filter(row => row.name.toLocaleLowerCase().includes(query) || row.aliases?.some(alias => alias.toLocaleLowerCase().includes(query))).sort((a, b) => Number(b.name === query) - Number(a.name === query) || Number(b.default_visible) - Number(a.default_visible) || a.name.localeCompare(b.name));
      for (const row of matches.slice(0, 40)) { const item = button('', 'search-result', () => navigateStyle(row.id)); item.dataset.styleId = row.id; item.append(node('span', row.name), node('small', TIER_LABELS[row.evidence_tier] || 'Source candidate')); results.append(item); }
    } else {
      results.append(node('p', 'Searching the complete source artist index…', 'search-empty'));
      if (data.artist_search_path && data.artist_search_path !== 'artist-search.json') throw new Error('Unsupported artist search path');
      if (!artistSearch) artistSearch = json('artist-search.json').catch(error => { artistSearch = null; throw error; });
      const index = await artistSearch; if (requested !== searchGeneration || scope !== searchScope) return;
      matches = index.artists.filter(row => validArtist(row[0]) && (row[1].toLocaleLowerCase().includes(query) || row[0].includes(query)));
      results.replaceChildren();
      for (const [id, name] of matches.slice(0, 40)) { const item = button('', 'search-result', () => navigateArtist(id)); item.dataset.artistId = id; item.append(node('span', name), node('small', 'Exact artist ID')); results.append(item); }
    }
    if (!matches.length) results.append(node('p', `No matching ${scope === 'styles' ? 'source style candidates' : 'source artists'}.`, 'search-empty'));
    if (matches.length > 40) results.append(node('p', `${count(matches.length)} matches · first 40 shown. Refine your search.`, 'search-empty'));
    $('#search-status').textContent = `${count(matches.length)} matches; showing ${Math.min(40, matches.length)}.`;
  } catch (error) { if (requested !== searchGeneration) return; results.replaceChildren(node('p', `Static search unavailable: ${error.message}`, 'search-empty'), button('Retry search', 'retry', searchRows)); }
}
const redraw = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(draw); };
const screen = style => ({x: style.x * camera.scale + camera.x, y: style.y * camera.scale + camera.y});
function topSpace() { return $('.toolbar').offsetTop + $('.toolbar').offsetHeight + 35; }
function fit() {
  if (!data) { redraw(); return; }
  const rows = filtered().filter(positioned); if (!rows.length) { redraw(); return; }
  const minX = Math.min(...rows.map(row => row.x)), maxX = Math.max(...rows.map(row => row.x)), minY = Math.min(...rows.map(row => row.y)), maxY = Math.max(...rows.map(row => row.y));
  const top = topSpace(); fitScale = Math.min((width - 100) / Math.max(.12, maxX - minX), Math.max(100, height - top - 115) / Math.max(.12, maxY - minY));
  camera = {scale: fitScale, x: width / 2 - (minX + maxX) / 2 * fitScale, y: top + (height - top - 90) / 2 - (minY + maxY) / 2 * fitScale}; redraw();
}
function focusStyle(row) { if (view !== 'map') { redraw(); return; } const scale = Math.max(fitScale * 3, camera.scale); camera = {scale, x: width / 2 - row.x * scale, y: (height + topSpace() - 80) / 2 - row.y * scale}; redraw(); }
function zoom(factor, x = width / 2, y = (height + topSpace() - 80) / 2) { const scale = Math.min(fitScale * 30, Math.max(fitScale * .35, camera.scale * factor)), ratio = scale / camera.scale; camera = {scale, x: x - (x - camera.x) * ratio, y: y - (y - camera.y) * ratio}; redraw(); }
function draw() {
  context.clearRect(0, 0, width, height); targets = []; if (!data || view !== 'map') return;
  const artistStyles = new Set(artistProfile ? (artistEvidence?.accepted || []).map(entry => entry.style_id) : []), occupied = new Set();
  const rows = filtered().filter(positioned).sort((a, b) => Number(b.id === hovered?.id) - Number(a.id === hovered?.id) || Number(b.id === selected?.id) - Number(a.id === selected?.id) || Number(artistStyles.has(b.id)) - Number(artistStyles.has(a.id)) || b.source_artist_support - a.source_artist_support);
  const size = Math.min(15, 10 + Math.max(0, Math.log2(camera.scale / fitScale))), top = topSpace() - 12;
  for (const row of rows) {
    const point = screen(row); if (point.x < -220 || point.x > width + 10 || point.y < top || point.y > height - 70) continue;
    const active = row.id === selected?.id, related = artistStyles.has(row.id), highlight = active || row.id === hovered?.id || related;
    context.fillStyle = active ? '#b94725' : related ? '#97642b' : row.evidence_tier === 'dictionary_named_style' ? '#355f72' : row.evidence_tier === 'raw_source_candidate' ? '#858677' : '#4d6654';
    context.beginPath(); context.arc(point.x, point.y, highlight ? 3 : 1.5, 0, Math.PI * 2); context.fill();
    context.font = `${highlight ? '600 ' : ''}${size}px Arial`;
    const textWidth = Math.min(context.measureText(row.name).width, 230, width - 30), x = Math.max(10, Math.min(width - textWidth - 12, point.x + 4)), y = point.y + 3;
    const cells = []; for (let cx = Math.floor(x / 30); cx <= Math.floor((x + textWidth) / 30); cx++) for (let cy = Math.floor((y - size) / 13); cy <= Math.floor((y + 2) / 13); cy++) cells.push(`${cx}:${cy}`);
    if (!highlight && cells.some(cell => occupied.has(cell))) continue;
    for (const cell of cells) occupied.add(cell);
    context.fillStyle = '#fffff9e8'; context.fillRect(x - 2, y - size, textWidth + 4, size + 3);
    context.fillStyle = active ? '#b94725' : related ? '#97642b' : row.evidence_tier === 'dictionary_named_style' ? '#355f72' : row.evidence_tier === 'raw_source_candidate' ? '#77786b' : '#3e6251';
    context.fillText(row.name, x, y, textWidth); targets.push({id: row.id, x: x - 2, y: y - size, w: textWidth + 4, h: size + 4});
  }
}
function nearest(x, y) {
  if (!data) return null;
  for (const target of targets.toReversed()) if (x >= target.x && x <= target.x + target.w && y >= target.y && y <= target.y + target.h) return styles.get(target.id);
  let closest = null, distance = 14;
  for (const row of filtered().filter(positioned)) { const point = screen(row), delta = Math.hypot(x - point.x, y - point.y); if (delta < distance) { distance = delta; closest = row; } }
  return closest;
}
function resize() { const rect = canvas.parentElement.getBoundingClientRect(); width = rect.width; height = rect.height; const ratio = devicePixelRatio || 1; canvas.width = width * ratio; canvas.height = height * ratio; context.setTransform(ratio, 0, 0, ratio, 0, 0); canvas.parentElement.style.setProperty('--toolbar-space', `${topSpace()}px`); fit(); }
for (const [selector, set] of [['#tier-filter', value => tier = value], ['#evidence-filter', value => evidence = value], ['#placement-filter', value => placement = value]]) $(selector).addEventListener('change', event => { set(event.target.value); directoryPage = 0; render(); fit(); save(); });
$('#directory-sort').addEventListener('change', event => { sort = event.target.value; directoryPage = 0; renderDirectory(); save(); });
$('#map-view').addEventListener('click', () => { view = 'map'; render(); fit(); save(); }); $('#list-view').addEventListener('click', () => { view = 'list'; render(); save(); });
$('#fit-map').addEventListener('click', fit); $('#zoom-in').addEventListener('click', () => zoom(1.5)); $('#zoom-out').addEventListener('click', () => zoom(1 / 1.5));
search.addEventListener('input', () => { searchRows(); save(true); }); $('#search-scope').addEventListener('change', event => { searchScope = event.target.value; searchRows(); save(); });
search.addEventListener('keydown', event => { if (event.key === 'Escape') results.hidden = true; if (event.key === 'Enter') { const rows = results.querySelectorAll('.search-result'); if (!results.hidden && rows.length) { event.preventDefault(); rows[Math.max(0, searchIndex)].click(); } } if (event.key === 'ArrowDown') { event.preventDefault(); const rows = results.querySelectorAll('.search-result'); if (rows.length) { searchIndex = 0; rows[0].focus(); } } });
results.addEventListener('keydown', event => { const rows = [...results.querySelectorAll('.search-result')]; if (event.key === 'Escape') { results.hidden = true; search.focus(); } if (['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); searchIndex = Math.max(0, Math.min(rows.length - 1, rows.indexOf(document.activeElement) + (event.key === 'ArrowDown' ? 1 : -1))); rows[searchIndex]?.focus(); } });
document.addEventListener('pointerdown', event => { if (!event.target.closest('.search')) results.hidden = true; });
document.addEventListener('keydown', event => { if (event.key === '/' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) { event.preventDefault(); search.focus(); } });
$('#about-toggle').addEventListener('click', event => { const about = $('#about'); about.hidden = !about.hidden; event.currentTarget.setAttribute('aria-expanded', String(!about.hidden)); if (!about.hidden) about.scrollIntoView({block: 'nearest', behavior: 'smooth'}); });
canvas.addEventListener('wheel', event => { event.preventDefault(); const rect = canvas.getBoundingClientRect(); zoom(Math.exp(-event.deltaY * .002), event.clientX - rect.left, event.clientY - rect.top); }, {passive: false});
canvas.addEventListener('pointerdown', event => { drag = {x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY}; canvas.setPointerCapture(event.pointerId); });
canvas.addEventListener('pointermove', event => { if (drag) { camera.x += event.clientX - drag.x; camera.y += event.clientY - drag.y; drag.x = event.clientX; drag.y = event.clientY; } else { const rect = canvas.getBoundingClientRect(); hovered = nearest(event.clientX - rect.left, event.clientY - rect.top); canvas.title = hovered ? `${hovered.name} · ${TIER_LABELS[hovered.evidence_tier] || 'Source candidate'}` : ''; } redraw(); });
canvas.addEventListener('pointerup', event => { if (drag && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 5) { const rect = canvas.getBoundingClientRect(), row = nearest(event.clientX - rect.left, event.clientY - rect.top); if (row) navigateStyle(row.id); } drag = null; });
canvas.addEventListener('pointercancel', () => drag = null);
canvas.addEventListener('keydown', event => { const step = 45, shifts = {ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step]}; if (shifts[event.key]) { event.preventDefault(); camera.x += shifts[event.key][0]; camera.y += shifts[event.key][1]; redraw(); } else if (['+', '='].includes(event.key)) { event.preventDefault(); zoom(1.5); } else if (event.key === '-') { event.preventDefault(); zoom(1 / 1.5); } });
window.addEventListener('popstate', restore); window.addEventListener('hashchange', restore); new ResizeObserver(resize).observe(canvas.parentElement);
try {
  data = await json('data.json');
  if (data.role !== 'candidate_named_styles' || data.scope !== 'local_research_only' || data.public_export_authorized !== false || data.native_fact !== false || data.artist_shard_prefix_length !== 3 || data.page_size !== 100 || !Array.isArray(data.styles) || !data.styles.length) throw new Error('Unsupported source atlas boundary');
  styles = new Map(data.styles.map(row => [row.id, row]));
  if (styles.size !== data.styles.length || data.styles.some(row => !validStyle(row.id) || typeof row.name !== 'string' || row.role !== 'candidate_named_style' || row.native_fact !== false || !row.counts || ROLES.some(role => !Number.isSafeInteger(row.counts[role]) || row.counts[role] < 0))) throw new Error('Unsupported named style identities or evidence roles');
  $('#coverage').textContent = `${count(data.styles.length)} named candidates · ${count(data.coverage?.artists)} source artists · metadata only`;
  canvas.dataset.evidenceRole = 'candidate_named_styles'; restore(); document.documentElement.dataset.styleAtlasReady = 'true';
} catch (error) { detail.replaceChildren(node('h2', 'Atlas unavailable'), node('p', `The source-bound atlas could not load: ${error.message}`, 'error-state')); }
