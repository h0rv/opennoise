/** Browser acceptance and screenshots for the local-only source explorer. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const [url, destination] = process.argv.slice(2);
if (!url || !destination) throw new Error('usage: capture_direct_custody_preview.mjs LOCAL_URL NEW_CACHE_DIRECTORY');
if (!['127.0.0.1', 'localhost', '[::1]'].includes(new URL(url).hostname)) throw new Error('Preview browser checks require a local URL');
const root = fileURLToPath(new URL('../', import.meta.url));
const output = resolve(destination);
if (!output.startsWith(resolve(root, '.cache') + sep)) throw new Error('Browser evidence must remain under .cache');
await mkdir(output);
const profile = await mkdtemp(join(tmpdir(), 'opennoise-direct-preview-'));
const browser = spawn(process.env.CHROMIUM_PATH || '/usr/bin/chromium', [
  '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
  '--disable-background-networking', '--disable-default-apps', '--no-first-run',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
]);
let socket;
const errors = [];
const requests = [];
try {
  const endpoint = await new Promise((resolve_, reject) => {
    let stderr = '';
    const timeout = setTimeout(() => reject(new Error('Chromium startup timed out')), 15000);
    browser.on('error', reject);
    browser.stderr.on('data', bytes => {
      stderr += bytes;
      const match = stderr.match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\//);
      if (match) { clearTimeout(timeout); resolve_(`http://127.0.0.1:${match[1]}`); }
    });
  });
  const page = await fetch(`${endpoint}/json/new?about:blank`, { method: 'PUT' }).then(response => response.json());
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve_, reject) => { socket.addEventListener('open', resolve_, { once: true }); socket.addEventListener('error', reject, { once: true }); });
  let sequence = 0;
  const pending = new Map();
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data);
    if (message.method === 'Network.requestWillBeSent') requests.push({url: message.params.request.url, type: message.params.type});
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.exception?.description ?? message.params.exceptionDetails.text);
    pending.get(message.id)?.(message);
  });
  const command = (method, params = {}) => new Promise((resolve_, reject) => {
    const id = ++sequence;
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`${method} timed out`)); }, 15000);
    pending.set(id, message => { clearTimeout(timeout); pending.delete(id); message.error ? reject(new Error(JSON.stringify(message.error))) : resolve_(message.result); });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const result = await command('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description ?? result.exceptionDetails.text);
    return result.result.value;
  };
  const wait = async expression => {
    for (let attempt = 0; attempt < 300; attempt++) {
      if (await evaluate(expression)) return;
      await new Promise(resolve_ => setTimeout(resolve_, 50));
    }
    throw new Error(`Browser condition failed: ${expression}`);
  };
  const screenshot = async name => {
    const result = await command('Page.captureScreenshot', { format: 'png' });
    await writeFile(join(output, name), Buffer.from(result.data, 'base64'));
  };
  await command('Network.enable');
  await command('Runtime.enable');
  await command('Page.enable');
  await command('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await command('Page.navigate', { url });
  await wait("document.documentElement?.dataset.previewReady === 'true'");
  const overviewReadyMs = await evaluate('Math.round(performance.now())');
  await wait("Boolean(document.querySelector('.artist-list a'))");
  const summary = await evaluate(`({title: document.querySelector('#detail h2').textContent,
    corpus: document.querySelector('#corpus-status').textContent,
    directRole: document.querySelector('.artist-list').dataset.evidenceRole,
    proposalRole: document.querySelector('.proposal').dataset.evidenceRole,
    visibleExamples: [...document.querySelectorAll('.artist-list a')].filter(node => !node.hidden).length,
    overflow: document.documentElement.scrollWidth > innerWidth, overview_ready_ms: ${overviewReadyMs}})`);
  assert.equal(summary.directRole, 'direct_source_observation');
  assert.equal(summary.proposalRole, 'inferred_artist_candidate');
  assert.ok(summary.visibleExamples <= 100);
  assert.equal(summary.overflow, false);
  await screenshot('desktop.png');
  await evaluate("document.querySelector('.artist-list a').click()");
  assert.equal(await evaluate("document.querySelector('.genre-list').dataset.evidenceRole"), 'direct_source_observation');
  const artist = await evaluate("document.querySelector('#detail h2').textContent");
  await screenshot('artist.png');
  await evaluate("document.querySelector('.genre-list a').click()");
  await wait("Boolean(document.querySelector('.artist-list a'))");
  assert.ok(await evaluate("Boolean(document.querySelector('.artist-list'))"));
  await evaluate("document.querySelector('.proposal a').click()");
  assert.ok(await evaluate("document.querySelector('#detail').textContent.includes('Inferred proposal for')"));
  await evaluate("document.querySelector('.back-button').click()");
  await evaluate("document.querySelector('#show-unplaced').click()");
  const unplacedResults = await evaluate("document.querySelectorAll('#search-results button').length");
  assert.ok(unplacedResults > 0);
  await evaluate("document.querySelector('#search-results button').click()");
  await wait("document.querySelector('#detail').textContent.includes('It remains unplaced')");
  assert.ok(await evaluate("document.querySelector('#detail').textContent.includes('It remains unplaced')"));
  await screenshot('unplaced.png');
  await evaluate("document.querySelector('#genre-search').value = 'no-such-genre-928'; document.querySelector('#genre-search').dispatchEvent(new Event('input'))");
  assert.ok(await evaluate("document.querySelector('#search-results').textContent.includes('No matching')"));
  await evaluate(`document.querySelector('#genre-search').value = ${JSON.stringify(summary.title)}; document.querySelector('#genre-search').dispatchEvent(new Event('input')); document.querySelector('#search-results button').click(); document.querySelector('#fit-map').click();`);
  const painted = async () => evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve(document.querySelector('canvas').toDataURL()))))");
  const beforeZoom = await painted();
  await evaluate("document.querySelector('#zoom-in').click()");
  assert.notEqual(await painted(), beforeZoom, 'zoom must change rendered graph');
  await evaluate("document.querySelector('#fit-map').click()");
  const beforePan = await painted();
  await command('Input.dispatchMouseEvent', { type: 'mousePressed', x: 750, y: 620, button: 'left', clickCount: 1 });
  await command('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 810, y: 680, button: 'left', buttons: 1 });
  await command('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 810, y: 680, button: 'left', clickCount: 1 });
  assert.notEqual(await painted(), beforePan, 'drag must pan the rendered graph');
  await evaluate("document.querySelector('#fit-map').click()");
  await command('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
  assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'), false);
  await screenshot('mobile.png');
  await command('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await evaluate("document.querySelector('#browse-all').click()");
  await wait("!document.querySelector('#genre-directory').hidden");
  const directory = await evaluate(`({count: document.querySelectorAll('.directory-genre').length, status: document.querySelector('#directory-status').textContent, hash: location.hash})`);
  assert.ok(directory.count > 0 && directory.count <= 75);
  assert.ok(directory.hash.includes('view=list'));
  await screenshot('directory.png');
  const pageOne = await evaluate("document.querySelector('.directory-genre').dataset.genreId");
  await evaluate("document.querySelector('#directory-pages button:last-child').click()");
  assert.notEqual(await evaluate("document.querySelector('.directory-genre').dataset.genreId"), pageOne);
  assert.ok(await evaluate("location.hash.includes('page=2')"));
  await evaluate('history.back()');
  await wait("!location.hash.includes('page=2')");
  assert.equal(await evaluate("document.querySelector('.directory-genre').dataset.genreId"), pageOne);
  await evaluate("document.querySelector('#genre-placement').value = 'unplaced'; document.querySelector('#genre-placement').dispatchEvent(new Event('change'))");
  assert.ok(await evaluate("[...document.querySelectorAll('.directory-genre small')].every(node => node.textContent.includes('unplaced'))"));
  await evaluate("document.querySelector('#genre-placement').value = 'all'; document.querySelector('#genre-placement').dispatchEvent(new Event('change')); document.querySelector('#genre-sort').value = 'artists'; document.querySelector('#genre-sort').dispatchEvent(new Event('change'))");
  const sortedCounts = await evaluate("[...document.querySelectorAll('.directory-genre small')].map(node => Number(node.textContent.split(' artists')[0].replaceAll(',', '')))");
  assert.ok(sortedCounts.every((value, index) => index === 0 || value <= sortedCounts[index - 1]));
  await command('Page.reload');
  await wait("document.documentElement?.dataset.previewReady === 'true' && !document.querySelector('#genre-directory').hidden");
  assert.equal(await evaluate("document.querySelector('#genre-sort').value"), 'artists');
  await evaluate("document.querySelector('#view-map').click()");
  await wait("!document.querySelector('#genre-map').hidden");
  let lazyGenreChecks = null;
  const metadata = await evaluate("fetch('data.json').then(response => response.arrayBuffer()).then(bytes => { const payload = JSON.parse(new TextDecoder().decode(bytes)); return {bytes: bytes.byteLength, lazy: Boolean(payload.genre_details_revision), artistMaps: Boolean(payload.artist_maps_revision), defaultGenre: payload.default_genre, releaseContexts: payload.release_contexts || null, embeddedArtistCount: Object.keys(payload.artists).length, genres: payload.genres.map(row => ({id: row.id, name: row.name, detail_path: row.detail_path, observed_artist_count: row.observed_artist_count}))}; })");
  if (metadata.lazy) {
    assert.ok(metadata.bytes < 256 * 1024, 'overview JSON must remain under 256KiB');
    assert.equal(metadata.embeddedArtistCount, 0, 'overview must not eagerly include all source artists');
    const requestedGenres = new Set(requests.map(request => new URL(request.url).pathname));
    const fresh = metadata.genres.filter(row => !requestedGenres.has('/' + row.detail_path)).slice(-3);
    assert.equal(fresh.length, 3);
    await evaluate(`(() => { const original = window.fetch; window.__parityOriginalFetch = original; window.fetch = (input, init) => { if (String(input) === ${JSON.stringify(fresh[0].detail_path)}) { window.__parityDelayedStarted = true; return original(input, init).then(response => new Promise(resolve => setTimeout(() => { window.__parityDelayedFinished = true; resolve(response); }, 700))); } return original(input, init); }; location.hash = new URLSearchParams({genre: ${JSON.stringify(fresh[0].id)}}); })()`);
    await wait('window.__parityDelayedStarted === true');
    await evaluate(`location.hash = new URLSearchParams({genre: ${JSON.stringify(fresh[1].id)}})`);
    await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify(fresh[1].name) + " && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
    await wait('window.__parityDelayedFinished === true');
    assert.equal(await evaluate("document.querySelector('#detail h2').textContent"), fresh[1].name, 'late genre responses must not replace the newer selection');
    await evaluate(`(() => { window.fetch = (input, init) => String(input) === ${JSON.stringify(fresh[2].detail_path)} ? Promise.reject(new Error('Acceptance: simulated missing static detail')) : window.__parityOriginalFetch(input, init); location.hash = new URLSearchParams({genre: ${JSON.stringify(fresh[2].id)}}); })()`);
    await wait("document.querySelector('#detail').textContent.includes('Retry genre details')");
    await evaluate("window.fetch = window.__parityOriginalFetch; document.querySelector('#detail .more-button').click()");
    await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify(fresh[2].name) + " && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
    lazyGenreChecks = {overview_payload_bytes: metadata.bytes, overview_under_256_kib: true, overview_embedded_artists: 0, lazy_genre_details: true, stale_genre_response_ignored: true, failed_genre_detail_retry: true};
  }
  let artistMapChecks = null;
  if (metadata.artistMaps) {
    await evaluate(`location.hash = new URLSearchParams({genre: ${JSON.stringify(metadata.defaultGenre)}})`);
    await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify(summary.title) + " && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
    await evaluate("[...document.querySelectorAll('#detail button')].find(node => node.textContent.includes('Explore artist map')).click()");
    await wait("location.hash.includes('view=artists') && document.querySelectorAll('#artist-map-results a').length > 0");
    const map = await evaluate(`fetch(${JSON.stringify('genre-artist-maps/' + metadata.defaultGenre + '.json')}).then(response => response.json())`);
    assert.equal(map.role, 'inferred_artist_overlap_map');
    assert.ok(map.selected_count <= 200);
    assert.equal(await evaluate("document.querySelector('#genre-map').dataset.evidenceRole"), 'inferred_artist_overlap_map');
    assert.equal(await evaluate("document.querySelectorAll('#artist-map-results a').length"), map.selected_count);
    assert.ok(await evaluate("document.querySelector('#artist-map-status').textContent.includes('map quality not evaluated')"));
    await screenshot('genre-artist-map.png');
    const point = map.artists.filter(row => Number.isFinite(row.x) && Number.isFinite(row.y)).map(row => ({...row, distance: Math.min(...map.artists.filter(other => other.id !== row.id && Number.isFinite(other.x)).map(other => Math.hypot(row.x - other.x, row.y - other.y)))})).sort((a, b) => b.distance - a.distance)[0];
    assert.ok(point, 'reference genre must include a supported artist map point');
    const targetPoint = await evaluate(`(() => { const rect = document.querySelector('#genre-map').getBoundingClientRect(); const scale = Math.min((rect.width - 75) / (16 / 9), Math.max(100, rect.height - 285)); return {x: rect.x + (rect.width - (16 / 9) * scale) / 2 + ${point.x} * scale, y: rect.y + 195 + (rect.height - 275 - scale) / 2 + ${point.y} * scale}; })()`);
    await command('Input.dispatchMouseEvent', {type: 'mousePressed', ...targetPoint, button: 'left', clickCount: 1});
    await command('Input.dispatchMouseEvent', {type: 'mouseReleased', ...targetPoint, button: 'left', clickCount: 1});
    await wait("Boolean(new URLSearchParams(location.hash.slice(1)).get('artist')) && Boolean(document.querySelector('.genre-list'))");
    const selectedMapArtist = await evaluate("new URLSearchParams(location.hash.slice(1)).get('artist')");
    const exactMapProfile = map.artists.find(row => row.id === selectedMapArtist);
    assert.ok(exactMapProfile);
    assert.equal(await evaluate("document.querySelector('#detail h2').textContent"), exactMapProfile.name);
    await evaluate("document.querySelector('#artist-map-list-toggle').click(); document.querySelector('#artist-map-query').value = " + JSON.stringify(exactMapProfile.name) + "; document.querySelector('#artist-map-query').dispatchEvent(new Event('input'))");
    assert.ok(await evaluate("document.querySelectorAll('#artist-map-results a').length > 0"));
    await command('Page.reload');
    await wait("document.documentElement?.dataset.previewReady === 'true' && !document.querySelector('#artist-map-tools').hidden && document.querySelectorAll('#artist-map-results a').length > 0 && Boolean(document.querySelector('.genre-list'))");
    assert.equal(await evaluate("document.querySelector('#detail h2').textContent"), exactMapProfile.name);
    await evaluate("document.querySelector('#artist-map-close').click()");
    assert.ok(await evaluate("document.querySelector('#artist-map-tools').hidden && !location.hash.includes('view=artists')"));
    const singleton = metadata.genres.find(row => row.observed_artist_count === 1);
    assert.ok(singleton, 'source fixture should contain a singleton artist genre');
    await evaluate(`location.hash = new URLSearchParams({genre: ${JSON.stringify(singleton.id)}, view: 'artists'})`);
    await wait("document.querySelectorAll('#artist-map-results a').length === 1 && !document.querySelector('#artist-map-tools').hidden");
    assert.ok(await evaluate("document.querySelector('#artist-map-results small').textContent.includes('Unplaced')"));
    assert.ok(await evaluate("document.querySelector('#artist-map-status').textContent.startsWith('0 placed')"));
    await screenshot('unplaced-artist-map.png');
    await evaluate("document.querySelector('#artist-map-results a').click()");
    await wait("Boolean(document.querySelector('.genre-list'))");
    artistMapChecks = {bounded_sample_limit: 200, loaded_artist_count: map.selected_count, inferred_role_explicit: true, unevaluated_quality_explicit: true, canvas_artist_click_opens_exact_profile: true, map_sample_filter: true, artist_map_deep_link_reload: true, return_to_genre_overview: true, unplaced_artist_list_traversal: true, singleton_has_no_fabricated_coordinates: true};
  }
  let releaseContextChecks = null;
  if (metadata.releaseContexts) {
    const genreContext = Object.entries(metadata.releaseContexts.genre_paths).find(([id]) => id === metadata.defaultGenre) || Object.entries(metadata.releaseContexts.genre_paths)[0];
    assert.ok(genreContext);
    await evaluate(`location.hash = new URLSearchParams({genre: ${JSON.stringify(genreContext[0])}})`);
    await wait("Boolean(document.querySelector('.release-context')) && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
    assert.equal(await evaluate("document.querySelector('.release-context').dataset.evidenceRole"), 'source_release_credit_context');
    await evaluate("document.querySelector('.release-context').open = true");
    await wait("Boolean(document.querySelector('.release-card'))");
    assert.ok(await evaluate("document.querySelector('.release-context').textContent.includes('they do not establish genre membership for releases or tracks')"));
    const genreReleases = await evaluate(`fetch(${JSON.stringify(genreContext[1])}).then(response => response.json())`);
    assert.equal(genreReleases.native_release_genres_available, false);
    assert.deepEqual(genreReleases.album_supported_seed_evidence, []);
    assert.equal(await evaluate("document.querySelectorAll('.release-card').length"), genreReleases.releases.length);
    assert.ok(await evaluate("[...document.querySelectorAll('.release-title')].every(node => node.href.startsWith('https://musicbrainz.org/release/'))"));
    assert.ok(await evaluate("[...document.querySelectorAll('.track-title')].every(node => node.href.startsWith('https://musicbrainz.org/recording/'))"));
    await evaluate("document.querySelector('.release-tracks').open = true; document.querySelector('.release-context').scrollIntoView({block: 'start'})");
    await screenshot('genre-release-credit-context.png');
    const artistContext = Object.entries(metadata.releaseContexts.artist_paths)[0];
    assert.ok(artistContext);
    await evaluate(`location.hash = new URLSearchParams({genre: ${JSON.stringify(metadata.defaultGenre)}, artist: ${JSON.stringify(artistContext[0])}})`);
    await wait("Boolean(document.querySelector('.genre-list')) && Boolean(document.querySelector('.release-context'))");
    await evaluate("document.querySelector('.release-context').open = true");
    await wait("Boolean(document.querySelector('.release-card'))");
    assert.ok(await evaluate("document.querySelector('.release-context').textContent.includes('This source artist appears in the')"));
    await evaluate("document.querySelector('.release-tracks').open = true; document.querySelector('.release-context').scrollIntoView({block: 'start'})");
    await screenshot('artist-release-credit-context.png');
    assert.equal(await evaluate("document.querySelectorAll('audio, video, iframe, embed').length"), 0);
    releaseContextChecks = {genre_release_credits: true, artist_release_credits: true, no_release_or_track_genre_membership_claims: true, track_metadata: true, musicbrainz_source_links: true, no_embedded_media: true, displayed_genre_release_count: genreReleases.releases.length};
  }
  let fullSourceChecks = null;
  const hasFullCatalog = await evaluate("!document.querySelector('.search-scope').hidden");
  if (hasFullCatalog) {
    await evaluate("fetch('data.json').then(response => response.json()).then(payload => { location.hash = new URLSearchParams({genre: payload.default_genre}); })");
    await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify(summary.title) + " && document.querySelector('.artist-list')?.getAttribute('aria-busy') === 'false'");
    const firstSourceId = await evaluate("document.querySelector('.artist-list a').dataset.artistId");
    await evaluate("document.querySelector('.artist-list').nextElementSibling.nextElementSibling.click()");
    assert.equal(await evaluate("[...document.querySelectorAll('.artist-list a')].filter(node => !node.hidden).length"), 100);
    await evaluate("document.querySelector('.artist-page-controls button:last-child').click()");
    await wait("document.querySelector('.artist-list')?.getAttribute('aria-busy') === 'false'");
    assert.notEqual(await evaluate("document.querySelector('.artist-list a').dataset.artistId"), firstSourceId);
    assert.ok(await evaluate("location.hash.includes('ap=2')"));
    await evaluate('history.back()');
    await wait("!location.hash.includes('ap=2') && document.querySelector('.artist-list')?.getAttribute('aria-busy') === 'false'");
    assert.equal(await evaluate("document.querySelector('.artist-list a').dataset.artistId"), firstSourceId);
    const target = await evaluate("Promise.all([fetch('data.json').then(response => response.json()), fetch('artist-search.json').then(response => response.json())]).then(([payload, index]) => index.artists.toReversed().find(row => !payload.artists[row[0]]))");
    assert.ok(target, 'catalog must include source profiles outside the initial bounded examples');
    await evaluate("document.querySelector('#scope-artists').checked = true; document.querySelector('#scope-artists').dispatchEvent(new Event('change')); document.querySelector('#genre-search').value = " + JSON.stringify(target[0]) + "; document.querySelector('#genre-search').dispatchEvent(new Event('input'))");
    await wait("Boolean(document.querySelector('#search-results [data-artist-id=\"" + target[0] + "\"]'))");
    await evaluate("document.querySelector('#search-results [data-artist-id]').click()");
    await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify(target[1]));
    assert.ok(await evaluate("Boolean(document.querySelector('.genre-list [data-genre-id]'))"));
    assert.ok(await evaluate("location.hash.includes('artist=' + " + JSON.stringify(target[0]) + ")"));
    await command('Page.reload');
    await wait("document.documentElement?.dataset.previewReady === 'true' && document.querySelector('#detail h2')?.textContent === " + JSON.stringify(target[1]));
    await screenshot('complete-source-artist.png');
    await command('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
    await command('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
    await evaluate("document.querySelector('#scope-genres').click()");
    const touch = await evaluate("(() => { const rect = document.querySelector('#scope-artists').getBoundingClientRect(); return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2}; })()");
    await command('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [touch]});
    await command('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
    await wait("document.querySelector('#scope-artists').checked");
    await wait("Boolean(document.querySelector('#search-results [data-artist-id]'))");
    await evaluate("document.querySelector('#search-results [data-artist-id]').click()");
    await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify(target[1]));
    assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'), false);
    await screenshot('mobile-source-artist.png');
    fullSourceChecks = {all_source_page_size: 100, source_artist_paging: true, source_page_history: true, global_artist_search: true, lazy_artist_profile: true, artist_deep_link_reload: true, mobile_artist_search_touch: true, source_artist_id: target[0]};
  }
  const externalRequests = requests.filter(request => new URL(request.url).origin !== new URL(url).origin);
  const mediaRequests = requests.filter(request => request.type === 'Media' || /\.(?:mp3|m4a|ogg|wav|flac|aac|aiff|opus|webm|mp4)(?:[?#]|$)/i.test(request.url));
  assert.deepEqual(externalRequests, [], 'static explorer must not fetch external origins');
  assert.deepEqual(mediaRequests, [], 'metadata explorer must not fetch audio or media');
  assert.deepEqual(errors, []);
  await writeFile(join(output, 'browser-report.json'), JSON.stringify({
    revision: 'direct-custody-preview-browser-v2', scope: 'local_research_only', url,
    summary, first_source_artist: artist, unplaced_search_results: unplacedResults,
    direct_artist_genre_traversal: true, inference_roles_separate: true,
    unplaced_searchable: true, zero_match_state: true, mobile_no_overflow: true,
    zoom_changes_graph: true, drag_pans_graph: true,
    complete_genre_directory: true, directory_paging: true, genre_count_sort: true,
    placement_filter: true, browser_history_restores_directory_page: true, deep_link_reload_preserves_view: true,
    complete_source_catalog_checks: fullSourceChecks,
    lazy_genre_checks: lazyGenreChecks,
    artist_map_checks: artistMapChecks,
    release_context_checks: releaseContextChecks,
    network: {request_count: requests.length, external_request_count: externalRequests.length, media_request_count: mediaRequests.length, static_origin_only: true},
    runtime_errors: errors, public_export_authorized: false,
  }, null, 2) + '\n');
  process.stdout.write(JSON.stringify({ output, status: 'passed', screenshots: (hasFullCatalog ? 7 : 5) + (artistMapChecks ? 2 : 0) + (releaseContextChecks ? 2 : 0) }) + '\n');
} finally {
  socket?.close(); browser.kill('SIGKILL');
  await new Promise(resolve_ => browser.exitCode !== null || browser.signalCode !== null ? resolve_() : browser.once('close', resolve_));
  await rm(profile, { recursive: true, force: true });
}
