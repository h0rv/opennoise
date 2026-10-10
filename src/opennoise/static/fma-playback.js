/** Local licensed excerpts only. Synthetic fixture manifests are visibly marked. */
const node = (tag, text) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; return element; };
const link = (text, href) => { const element = node('a', text); element.href = href; if (href.startsWith('http')) { element.target = '_blank'; element.rel = 'noopener noreferrer'; } return element; };
function safeExternal(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch { return null; }
}
async function loadPlayback(config, json) {
  const manifestURL = new URL(config.manifest, location.href);
  if (manifestURL.origin !== location.origin) throw new Error('Local audio manifest must use this server.');
  const manifest = await json(config.manifest);
  if (!['fma-local-playback-v1', 'fma-local-playback-collection-v1'].includes(manifest.revision) || typeof manifest.test_only !== 'boolean' || !manifest.tracks || Object.keys(manifest.tracks).length > 64) throw new Error('Unsupported local audio manifest.');
  for (const [key, entry] of Object.entries(manifest.tracks)) {
    if (!Number.isSafeInteger(entry.track_id) || entry.track_id <= 0 || key !== String(entry.track_id) || entry.audio_path !== `${entry.track_id}.mp3`) throw new Error('Local audio track identity differs.');
  }
  return {manifest, manifestURL};
}
let persistent = null, requestVersion = 0, queueEntries = [], queueIndex = -1, queueArmed = false, repeatQueue = false, loaded = null;
const routeUpdates = new Set();
const notify = () => { persistent?.update(); for (const update of routeUpdates) update(); };
export function clearRoutePlayers() { routeUpdates.clear(); }
export function stopPlayback() {
  requestVersion++; queueArmed = false; repeatQueue = false; queueEntries = []; queueIndex = -1; loaded = null;
  if (persistent) { persistent.audio.pause(); persistent.audio.removeAttribute('src'); persistent.audio.load(); persistent.section.hidden = true; }
  notify();
}
function credits(entry, manifest, target) {
  if (manifest.test_only) target.append(node('p', 'Test-only audio fixture · Synthetic test fixture; not FMA audio or catalog playback coverage.'));
  target.append(node('p', entry.attribution));
  const sources = node('p'), license = safeExternal(entry.license_url), source = safeExternal(entry.source_url);
  if (license) sources.append(link(entry.license_title || 'Audio license', license));
  if (source) sources.append(node('span', ' · '), link('Source track page', source));
  target.append(sources);
  const rights = [entry.copyright_c, entry.copyright_p, entry.composer && `Composer: ${entry.composer}`].filter(Boolean);
  if (rights.length) { const detail = node('details'); detail.append(node('summary', 'Additional source credits'), node('p', rights.join(' · '))); target.append(detail); }
}
function control(text, className, action) {
  const button = node('button', text); button.type = 'button'; button.className = className; button.addEventListener('click', action); return button;
}
function ensurePlayer() {
  if (persistent) return persistent;
  const section = node('section'); section.id = 'persistent-player'; section.className = 'playback'; section.hidden = true; section.setAttribute('aria-label', 'Current excerpt and listening queue');
  const title = node('h2'), attribution = node('div');
  const audio = node('audio'); audio.controls = true; audio.preload = 'none';
  const status = node('p'); status.className = 'playback-status'; status.setAttribute('role', 'status');
  const toggle = control('Play excerpt', 'playback-toggle', () => { if (!audio.paused) { queueArmed = false; audio.pause(); notify(); } else startCurrent(queueEntries.length > 1); });
  const previous = control('Previous', 'playback-previous', () => advance(-1));
  const next = control('Next', 'playback-next', () => advance(1));
  const stop = control('Stop', 'playback-stop', stopPlayback);
  const shuffle = control('Shuffle remaining', 'playback-shuffle', () => {
    for (let i = queueEntries.length - 1; i > queueIndex + 1; i--) {
      const j = queueIndex + 1 + Math.floor(Math.random() * (i - queueIndex));
      [queueEntries[i], queueEntries[j]] = [queueEntries[j], queueEntries[i]];
    }
    notify();
  });
  const repeat = control('Repeat: off', 'playback-repeat', () => { repeatQueue = !repeatQueue; if (repeatQueue && !audio.paused) queueArmed = true; notify(); });
  const order = node('p'); order.className = 'playback-order';
  const orderPanel = node('details'); orderPanel.append(node('summary', 'Queue order'), order);
  const retry = control('Retry playback', 'playback-retry', () => { audio.load(); startCurrent(queueEntries.length > 1); }); retry.hidden = true;
  const update = () => { toggle.textContent = audio.paused ? 'Play excerpt' : 'Pause excerpt'; previous.disabled = queueIndex <= 0; next.disabled = queueIndex < 0 || queueIndex >= queueEntries.length - 1; toggle.disabled = queueIndex < 0; shuffle.disabled = queueEntries.length - queueIndex - 1 < 2; repeat.textContent = repeatQueue ? 'Repeat: on' : 'Repeat: off'; repeat.setAttribute('aria-pressed', String(repeatQueue)); order.textContent = queueIndex < 0 ? '' : `${queueIndex + 1} of ${queueEntries.length} · ${queueEntries.map(entry => entry.title || `Track #${entry.track_id}`).join(' → ')}`; };
  persistent = {section, title, attribution, audio, status, retry, update};
  audio.addEventListener('play', () => { if (!loaded || section.hidden) { audio.pause(); return; } status.textContent = 'Playing local excerpt.'; notify(); });
  audio.addEventListener('pause', () => { if (!audio.ended) { queueArmed = false; if (!retry.hidden) return; status.textContent = 'Paused.'; } notify(); });
  audio.addEventListener('ended', () => { if (!audio.ended) return; status.textContent = 'Excerpt ended.'; if (queueArmed && queueIndex + 1 < queueEntries.length) advance(1); else if (queueArmed && repeatQueue && queueEntries.length) { queueIndex = 0; startCurrent(true); } else { queueArmed = false; notify(); } });
  audio.addEventListener('error', () => { if (loaded && !section.hidden) failPlayback(); });
  section.append(title, previous, toggle, next, stop, shuffle, repeat, audio, status, orderPanel, retry, attribution);
  document.body.append(section); return persistent;
}
function failPlayback() {
  queueArmed = false;
  const player = ensurePlayer(); player.status.textContent = 'Audio unavailable. Retry playback or check the local audio folder.'; player.retry.hidden = false; notify();
}
async function startCurrent(armed) {
  const entry = queueEntries[queueIndex]; if (!loaded || !entry) return false;
  const version = ++requestVersion, player = ensurePlayer(), url = new URL(entry.audio_path, loaded.manifestURL).href;
  if (player.audio.src !== url) {
    player.audio.pause(); player.audio.src = url;
    player.title.replaceChildren(link(entry.title || `Track #${entry.track_id}`, `#track=${entry.track_id}`), node('span', ' · '), link(entry.artist_name || `Artist #${entry.artist_id}`, `#artist=${entry.artist_id}`));
    player.attribution.replaceChildren(); credits(entry, loaded.manifest, player.attribution);
  }
  player.section.hidden = false; player.section.dataset.trackId = entry.track_id;
  player.section.dataset.evidenceRole = loaded.manifest.test_only ? 'test_only_audio_fixture' : 'native_licensed_excerpt';
  player.audio.setAttribute('aria-label', `${entry.title} — ${entry.artist_name}`);
  if (player.audio.ended) player.audio.currentTime = 0;
  player.retry.hidden = true; player.status.textContent = 'Loading local excerpt…'; queueArmed = armed || repeatQueue;
  try { await player.audio.play(); if (version !== requestVersion) return false; queueArmed = armed || repeatQueue; notify(); return true; }
  catch { if (version === requestVersion) failPlayback(); return false; }
}
function advance(direction) {
  const index = queueIndex + direction; if (index < 0 || index >= queueEntries.length) return;
  queueIndex = index; startCurrent(true);
}
/** Call only from an explicit user Play action; route rendering never calls this API. */
export async function requestPlay({config, id, ids = null, json, queue = false}) {
  const version = ++requestVersion;
  queueArmed = false;
  const pending = ensurePlayer(); pending.section.hidden = false; pending.status.textContent = 'Loading local excerpt…'; notify();
  try {
    const pack = await loadPlayback(config, json); if (version !== requestVersion) return false;
    const entry = pack.manifest.tracks[String(id)]; if (!entry) throw new Error('Excerpt absent');
    const wanted = ids === null ? Object.keys(pack.manifest.tracks).map(Number) : journeyIds(ids, pack.manifest);
    if (!wanted || !Number.isSafeInteger(id) || id <= 0) throw new Error('Invalid native queue IDs');
    const entries = queue ? [...new Set(wanted)].map(value => pack.manifest.tracks[String(value)]).filter(Boolean) : [entry];
    if (!entries.some(row => row.track_id === entry.track_id)) throw new Error('Excerpt outside queue');
    loaded = pack; repeatQueue = false; queueEntries = entries; queueIndex = entries.findIndex(row => row.track_id === entry.track_id);
    return await startCurrent(queue);
  } catch { if (version === requestVersion) { ensurePlayer().section.hidden = false; failPlayback(); } return false; }
}
function player(entry, manifest, config, json) {
  const section = node('section'); section.className = 'playback'; section.dataset.trackId = entry.track_id;
  section.dataset.evidenceRole = manifest.test_only ? 'test_only_audio_fixture' : 'native_licensed_excerpt';
  section.append(node('h2', manifest.test_only ? 'Test-only audio fixture' : 'Local excerpt'));
  const toggle = control('Play excerpt', 'playback-toggle', () => {
    if (persistent?.section.dataset.trackId === String(entry.track_id) && !persistent.audio.paused) { queueArmed = false; persistent.audio.pause(); notify(); }
    else requestPlay({config, id: entry.track_id, json});
  });
  const update = () => { toggle.textContent = persistent?.section.dataset.trackId === String(entry.track_id) && !persistent.audio.paused ? 'Pause excerpt' : 'Play excerpt'; };
  routeUpdates.add(update); update(); section.append(toggle); credits(entry, manifest, section); return section;
}
const JOURNEY_KEY = 'opennoise.fma-listening-journey.v1';
function journeyIds(value, manifest) {
  if (!Array.isArray(value) || value.length > 64 || value.some(id => !Number.isSafeInteger(id) || id <= 0 || !Object.hasOwn(manifest.tracks, String(id)))) return null;
  return [...new Set(value)];
}
function savedJourney(manifest) {
  try {
    const raw = localStorage.getItem(JOURNEY_KEY); if (!raw || raw.length > 8192) return null;
    const value = JSON.parse(raw); if (value.revision !== 'fma-native-listening-journey-v1') return null;
    const ids = journeyIds(value.track_ids, manifest); return ids?.length ? ids : null;
  } catch { return null; }
}
function journeyURL(ids) { const url = new URL(location.href); url.hash = 'listen&queue=' + ids.join(','); return url.href; }
function listeningDirectory(entries, manifest, config, json, rows) {
  const controls = node('form'); controls.className = 'listening-controls'; controls.setAttribute('aria-label', 'Listening queue'); controls.addEventListener('submit', event => event.preventDefault());
  const label = node('label', 'Search excerpts'), search = node('input'); search.type = 'search'; search.id = 'listen-query'; search.placeholder = 'Title or artist'; label.htmlFor = search.id;
  const summary = node('p'); summary.className = 'listening-status'; summary.setAttribute('role', 'status');
  const items = [], selected = new Set(entries.map(entry => entry.track_id)), matches = () => items.filter(item => !item.wrapper.hidden);
  const selectedVisible = () => { const visible = new Set(matches().map(item => item.entry.track_id)); return [...selected].filter(id => visible.has(id)); };
  const queue = control('Play queue', 'playback-queue', () => {
    if (queueArmed && persistent && !persistent.audio.paused) { queueArmed = false; persistent.audio.pause(); notify(); }
    else { const ids = selectedVisible(); if (ids.length) requestPlay({config, id: ids[0], ids, json, queue: true}); }
  });
  const selectionNotice = node('p'); selectionNotice.className = 'journey-status'; selectionNotice.setAttribute('role', 'status');
  const shareURL = node('input'); shareURL.type = 'url'; shareURL.readOnly = true; shareURL.hidden = true; shareURL.className = 'journey-url'; shareURL.setAttribute('aria-label', 'Shareable listening queue URL');
  const selectVisible = control('Select visible', 'queue-select-visible', () => { for (const item of matches()) selected.add(item.entry.track_id); update(); });
  const clear = control('Clear queue', 'queue-clear', () => { selected.clear(); update(); });
  const share = control('Share queue', 'queue-share', () => { shareURL.value = journeyURL(selectedVisible()); shareURL.hidden = false; shareURL.focus(); shareURL.select(); });
  const save = control('Save queue', 'queue-save', () => {
    try { localStorage.setItem(JOURNEY_KEY, JSON.stringify({revision:'fma-native-listening-journey-v1', track_ids:selectedVisible()})); selectionNotice.textContent = 'Queue saved in this browser.'; update(); }
    catch { selectionNotice.textContent = 'This browser could not save the queue. Use Share queue instead.'; }
  });
  const restore = control('Restore saved queue', 'queue-restore', () => {
    const ids = savedJourney(manifest); if (!ids) { selectionNotice.textContent = 'No valid saved queue.'; return; }
    const hash = new URL(journeyURL(ids)).hash;
    if (location.hash === hash) { selected.clear(); for (const id of ids) selected.add(id); update(); } else location.hash = hash;
    selectionNotice.textContent = 'Saved queue restored. Press Play queue to listen.';
  });
  const update = () => {
    const visible = matches(), ids = selectedVisible();
    queue.disabled = !ids.length && !queueArmed; queue.textContent = queueArmed ? 'Pause queue' : 'Play queue'; share.disabled = save.disabled = !ids.length; restore.disabled = !savedJourney(manifest);
    for (const item of items) item.checkbox.checked = selected.has(item.entry.track_id);
    summary.textContent = visible.length ? `${visible.length} matching excerpts · ${ids.length} selected. Re-select an excerpt to move it to the end.` : 'No matching excerpts.';
  };
  const options = node('details'); options.className = 'queue-options'; options.append(node('summary', 'Queue options'), selectVisible, clear, share, save, restore, shareURL, selectionNotice);
  controls.append(label, search, queue, summary, options); rows.append(controls);
  for (const entry of entries) {
    const wrapper = node('div'); wrapper.className = 'listening-entry'; const title = node('h2'); title.append(link(entry.title || `Track #${entry.track_id}`, `#track=${entry.track_id}`));
    const choice = node('label'), checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.className = 'queue-include'; checkbox.value = entry.track_id; checkbox.checked = true;
    choice.append(checkbox, document.createTextNode(`Include ${entry.title || `Track #${entry.track_id}`} in queue`));
    checkbox.addEventListener('change', () => { if (checkbox.checked) selected.add(entry.track_id); else selected.delete(entry.track_id); update(); });
    wrapper.append(choice, title, link(entry.artist_name || `Artist #${entry.artist_id}`, `#artist=${entry.artist_id}`), player(entry, manifest, config, json)); items.push({entry, wrapper, checkbox}); rows.append(wrapper);
  }
  search.addEventListener('input', () => { const term = search.value.normalize('NFKC').toLocaleLowerCase().trim(); for (const item of items) item.wrapper.hidden = !`${item.entry.title ?? ''} ${item.entry.artist_name ?? ''}`.normalize('NFKC').toLocaleLowerCase().includes(term); update(); });
  routeUpdates.add(update); update();
}
export async function renderPlayback({config, id, ids = null, relatedIds = [], directory = false, json, rows, heading, status, current}) {
  if (!config) return;
  try {
    const {manifest, manifestURL} = await loadPlayback(config, json);
    if (!current()) return;
    const allowed = ids === null ? null : journeyIds(ids, manifest);
    if (ids !== null && allowed === null) throw new Error('Invalid listening queue');
    const entries = directory ? (allowed === null ? Object.values(manifest.tracks) : allowed.map(value => manifest.tracks[String(value)])) : [manifest.tracks[String(id)]].filter(Boolean);
    if (directory) {
      heading.textContent = 'Listen';
      status.textContent = manifest.test_only ? 'Test-only audio fixtures; zero verified catalog clips.' : `${entries.length} local source excerpts · selected by source license and availability.`;
    }
    if (!entries.length) { const empty = node('section'); empty.className = 'playback'; empty.append(node('p', 'No local excerpt is attached for this track.')); rows.append(empty); }
    if (directory) listeningDirectory(entries, manifest, config, json, rows);
    else {
      for (const entry of entries) rows.append(player(entry, manifest, config, json));
      const related = [...new Set(relatedIds)].filter(value => Number.isSafeInteger(value) && value !== Number(id)).map(value => manifest.tracks[String(value)]).filter(Boolean).slice(0, 6);
      if (related.length) {
        const section = node('section'); section.className = 'connections playback-related'; section.dataset.evidenceRole = 'shared_source_track_annotations';
        section.append(node('h2', 'More local excerpts with shared track genres'), node('p', 'Shared source annotations; not a musical-similarity ranking.'));
        const list = node('ul'); list.className = 'directory';
        for (const entry of related) {
          const item = node('li');
          item.append(link(entry.title || `Track #${entry.track_id}`, `#track=${entry.track_id}`), link(entry.artist_name || `Artist #${entry.artist_id}`, `#artist=${entry.artist_id}`));
          list.append(item);
        }
        section.append(list); rows.append(section);
      }
    }
  } catch {
    if (!current()) return;
    const section = node('section'); section.className = 'playback'; const message = node('p', 'Local audio is unavailable. Check the adjacent audio folder and reload.'); message.className = 'playback-status'; message.setAttribute('role', 'status'); section.append(message); rows.append(section);
    if (directory) { heading.textContent = 'Listen'; status.textContent = 'Audio manifest unavailable.'; }
  }
}
