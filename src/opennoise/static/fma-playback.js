/** Local licensed excerpts only. Synthetic fixture manifests are visibly marked. */
const node = (tag, text) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; return element; };
const link = (text, href) => { const element = node('a', text); element.href = href; if (href.startsWith('http')) { element.target = '_blank'; element.rel = 'noopener noreferrer'; } return element; };
const players = new Set();
let active = null;
export function stopPlayback() {
  for (const audio of players) { audio.pause(); audio.removeAttribute('src'); audio.load(); }
  players.clear(); active = null;
}
function safeExternal(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch { return null; }
}
async function loadPlayback(config, json) {
  const manifestURL = new URL(config.manifest, location.href);
  if (manifestURL.origin !== location.origin) throw new Error('Local audio manifest must use this server.');
  const manifest = await json(config.manifest);
  if (manifest.revision !== 'fma-local-playback-v1' || typeof manifest.test_only !== 'boolean' || !manifest.tracks || Object.keys(manifest.tracks).length > 64) throw new Error('Unsupported local audio manifest.');
  for (const [key, entry] of Object.entries(manifest.tracks)) {
    if (!Number.isSafeInteger(entry.track_id) || entry.track_id <= 0 || key !== String(entry.track_id) || entry.audio_path !== `${entry.track_id}.mp3`) throw new Error('Local audio track identity differs.');
  }
  return {manifest, manifestURL};
}
function player(entry, manifest, manifestURL, onPlay = () => {}, onEnded = () => {}) {
  const section = node('section'); section.className = 'playback'; section.dataset.trackId = entry.track_id;
  section.dataset.evidenceRole = manifest.test_only ? 'test_only_audio_fixture' : 'native_licensed_excerpt';
  section.append(node('h2', manifest.test_only ? 'Test-only audio fixture' : 'Local excerpt'));
  if (manifest.test_only) section.append(node('p', 'Synthetic test fixture; not FMA audio or catalog playback coverage.'));
  const audio = node('audio'); audio.controls = true; audio.preload = 'none'; audio.setAttribute('aria-label', `${entry.title} — ${entry.artist_name}`);
  audio.src = new URL(entry.audio_path, manifestURL).href;
  const toggle = node('button', 'Play excerpt'); toggle.type = 'button'; toggle.className = 'playback-toggle';
  const status = node('p', 'Ready to play local excerpt.'); status.className = 'playback-status'; status.setAttribute('role', 'status');
  const retry = node('button', 'Retry playback'); retry.type = 'button'; retry.className = 'playback-retry'; retry.hidden = true;
  let failed = false;
  const fail = () => { failed = true; status.textContent = 'Audio unavailable. Retry playback or check that the local audio folder is present.'; toggle.disabled = true; retry.hidden = false; };
  const play = async () => { if (!players.has(audio)) return; try { await audio.play(); } catch { if (players.has(audio)) fail(); } };
  toggle.addEventListener('click', () => { if (audio.paused) play(); else audio.pause(); });
  retry.addEventListener('click', () => { failed = false; retry.hidden = true; toggle.disabled = false; status.textContent = 'Loading local excerpt…'; audio.load(); play(); });
  audio.addEventListener('play', () => { if (!players.has(audio)) { audio.pause(); return; } onPlay(); if (active && active !== audio) active.pause(); active = audio; failed = false; toggle.textContent = 'Pause excerpt'; status.textContent = 'Playing local excerpt.'; });
  audio.addEventListener('pause', () => { toggle.textContent = 'Play excerpt'; if (!failed && !audio.ended) status.textContent = 'Paused.'; });
  audio.addEventListener('ended', () => { toggle.textContent = 'Play excerpt'; status.textContent = 'Excerpt ended.'; if (active === audio) active = null; if (players.has(audio)) onEnded(); });
  audio.addEventListener('waiting', () => { if (!failed && !audio.paused) status.textContent = 'Loading local excerpt…'; });
  audio.addEventListener('playing', () => { if (!failed) status.textContent = 'Playing local excerpt.'; });
  audio.addEventListener('error', () => { if (players.has(audio)) fail(); });
  players.add(audio);
  section.append(toggle, audio, status, retry, node('p', entry.attribution));
  const sources = node('p'); const license = safeExternal(entry.license_url), source = safeExternal(entry.source_url);
  if (license) sources.append(link(entry.license_title || 'Audio license', license));
  if (source) sources.append(node('span', ' · '), link('Source track page', source));
  section.append(sources);
  const rights = [entry.copyright_c, entry.copyright_p, entry.composer && `Composer: ${entry.composer}`].filter(Boolean);
  if (rights.length) { const details = node('details'); details.append(node('summary', 'Additional source credits'), node('p', rights.join(' · '))); section.append(details); }
  return section;
}
function listeningDirectory(entries, manifest, manifestURL, rows) {
  const controls = node('form'); controls.className = 'listening-controls'; controls.setAttribute('aria-label', 'Listening queue');
  controls.addEventListener('submit', event => event.preventDefault());
  const label = node('label', 'Search excerpts');
  const search = node('input'); search.type = 'search'; search.id = 'listen-query'; search.placeholder = 'Title or artist'; label.htmlFor = search.id;
  const previous = node('button', 'Previous'), queue = node('button', 'Play queue'), next = node('button', 'Next');
  for (const button of [previous, queue, next]) button.type = 'button';
  previous.className = 'playback-previous'; queue.className = 'playback-queue'; next.className = 'playback-next';
  const summary = node('p'); summary.className = 'listening-status'; summary.setAttribute('role', 'status');
  controls.append(label, search, previous, queue, next, summary); rows.append(controls);
  let selected = null, armed = false;
  const items = [], matches = () => items.filter(item => !item.wrapper.hidden);
  const update = () => {
    const visible = matches(), index = visible.indexOf(selected);
    previous.disabled = !visible.length || index <= 0;
    next.disabled = !visible.length || index >= visible.length - 1;
    queue.disabled = !visible.length;
    queue.textContent = armed ? 'Pause queue' : 'Play queue';
    summary.textContent = visible.length ? `${visible.length} matching excerpts${index >= 0 ? ` · ${index + 1} of ${visible.length}: ${selected.entry.title}` : ''}.` : 'No matching excerpts.';
  };
  const start = item => {
    if (!item || !players.has(item.audio)) return;
    selected = item; armed = true;
    if (item.audio.ended) item.audio.currentTime = 0;
    if (item.audio.paused) item.section.querySelector('.playback-toggle').click();
    update();
  };
  for (const entry of entries) {
    const wrapper = node('div'); wrapper.className = 'listening-entry';
    const title = node('h2'); title.append(link(entry.title || `Track #${entry.track_id}`, `#track=${entry.track_id}`));
    wrapper.append(title, link(entry.artist_name || `Artist #${entry.artist_id}`, `#artist=${entry.artist_id}`));
    const item = {entry, wrapper};
    item.section = player(entry, manifest, manifestURL, () => { selected = item; update(); }, () => {
      if (!armed || selected !== item) return;
      const visible = matches(), following = visible[visible.indexOf(item) + 1];
      if (following) start(following); else { armed = false; update(); }
    });
    item.audio = item.section.querySelector('audio');
    item.audio.addEventListener('pause', () => {
      if (selected === item && !item.audio.ended) { armed = false; update(); }
    });
    item.audio.addEventListener('error', () => { if (selected === item) { armed = false; update(); } });
    wrapper.append(item.section); items.push(item); rows.append(wrapper);
  }
  queue.addEventListener('click', () => {
    if (armed) { armed = false; selected?.audio.pause(); update(); }
    else start(matches().includes(selected) ? selected : matches()[0]);
  });
  previous.addEventListener('click', () => { const visible = matches(); start(visible[visible.indexOf(selected) - 1]); });
  next.addEventListener('click', () => { const visible = matches(); start(visible[visible.indexOf(selected) + 1]); });
  search.addEventListener('input', () => {
    armed = false; for (const item of items) item.audio.pause(); selected = null;
    const term = search.value.normalize('NFKC').toLocaleLowerCase().trim();
    for (const item of items) item.wrapper.hidden = !`${item.entry.title ?? ''} ${item.entry.artist_name ?? ''}`.normalize('NFKC').toLocaleLowerCase().includes(term);
    update();
  });
  update();
}
export async function renderPlayback({config, id, ids = null, relatedIds = [], directory = false, json, rows, heading, status, current}) {
  if (!config) return;
  try {
    const {manifest, manifestURL} = await loadPlayback(config, json);
    if (!current()) return;
    const allowed = ids === null ? null : new Set(ids);
    const entries = directory ? Object.values(manifest.tracks).filter(entry => allowed === null || allowed.has(entry.track_id)) : [manifest.tracks[String(id)]].filter(Boolean);
    if (directory) {
      heading.textContent = 'Listen';
      status.textContent = manifest.test_only ? 'Test-only audio fixtures; zero verified catalog clips.' : `${entries.length} local source excerpts · selected by source license and availability.`;
    }
    if (!entries.length) { const empty = node('section'); empty.className = 'playback'; empty.append(node('p', 'No local excerpt is attached for this track.')); rows.append(empty); }
    if (directory) listeningDirectory(entries, manifest, manifestURL, rows);
    else {
      for (const entry of entries) rows.append(player(entry, manifest, manifestURL));
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
