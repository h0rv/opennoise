/** Browser acceptance and screenshots for the local-only emerging music community explorer. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const [url, destination] = process.argv.slice(2);
if (!url || !destination) throw new Error('usage: capture_community_preview.mjs LOCAL_URL NEW_CACHE_DIRECTORY');
if (!['127.0.0.1', 'localhost', '[::1]'].includes(new URL(url).hostname)) throw new Error('Preview browser checks require a local URL');
const root = fileURLToPath(new URL('../', import.meta.url));
const output = resolve(destination);
if (!output.startsWith(resolve(root, '.cache') + sep)) throw new Error('Browser evidence must remain under .cache');
await mkdir(output);
const profile = await mkdtemp(join(tmpdir(), 'opennoise-community-preview-'));
const browser = spawn(process.env.CHROMIUM_PATH || '/usr/bin/chromium', [
  '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
  '--disable-background-networking', '--disable-default-apps', '--no-first-run',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
]);
let socket;
const errors = [];
const requests = [];
let screenshotCount = 0;
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
    screenshotCount++;
  };
  await command('Network.enable');
  await command('Runtime.enable');
  await command('Page.enable');
  await command('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
  await command('Page.navigate', {url});
  await wait("document.documentElement?.dataset.communityPreviewReady === 'true'");
  const readyMs = await evaluate('Math.round(performance.now())');
  const metadata = await evaluate("fetch('community-data.json').then(response => response.json()).then(payload => ({role: payload.role, communities: payload.communities.map(row => ({id: row.id, label: row.label, level: row.level, parent_id: row.parent_id, child_ids: row.child_ids, x: row.x, y: row.y, coarse_evidence_supported: row.coarse_evidence_supported})), coverage: payload.coverage}))");
  assert.equal(metadata.role, 'inferred_emergent_music_communities');
  const counts = Object.fromEntries(['broad', 'sub', 'micro'].map(level => [level, metadata.communities.filter(row => row.level === level).length]));
  assert.ok(counts.broad > 0 && counts.sub > 0 && counts.micro > 0, 'model must expose actual broad, sub, and micro communities');
  const records = new Map(metadata.communities.map(row => [row.id, row]));
  const skippedBranch = metadata.communities.find(row => row.level === 'broad' && row.child_ids.some(id => records.get(id)?.level === 'micro') && !row.child_ids.some(id => records.get(id)?.level === 'sub'));
  if (skippedBranch) {
    await evaluate(`location.hash = new URLSearchParams({community: ${JSON.stringify(skippedBranch.id)}})`);
    await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify("Community descriptors: " + skippedBranch.label));
    assert.ok(await evaluate("document.querySelector('.level-nav [data-level=sub]').disabled && !document.querySelector('.level-nav [data-level=micro]').disabled"));
    await evaluate("document.querySelector('.level-nav [data-level=micro]').click()");
    await wait("document.querySelector('.level-nav [data-level=micro]').getAttribute('aria-pressed') === 'true'");
    assert.ok(await evaluate("document.querySelector('#breadcrumbs [aria-current=true]').dataset.communityId").then(id => skippedBranch.child_ids.includes(id)), 'skipped resolution navigation must follow a real hierarchy edge');
    assert.equal(await evaluate("document.querySelectorAll('#breadcrumbs a').length"), 2);
  }
  const unsupportedBroad = metadata.communities.find(row => row.level === 'broad' && row.coarse_evidence_supported === false);
  if (unsupportedBroad) {
    await evaluate(`location.hash = new URLSearchParams({community: ${JSON.stringify(unsupportedBroad.id)}})`);
    await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify("Community descriptors: " + unsupportedBroad.label));
    assert.ok(await evaluate("document.querySelector('#detail .role-badge').textContent.includes('CANDIDATE') && document.querySelector('.coarse-support-state').textContent.includes('Unsupported broad candidate') && document.querySelector('.coarse-support-state').textContent.includes('fitted core')"));
    await screenshot('unsupported-broad.png');
  }
  const broad = metadata.communities.find(row => row.level === 'broad' && row.child_ids.some(id => records.get(id)?.child_ids.some(child => records.get(child)?.level === 'micro')));
  assert.ok(broad, 'model must contain a supported three-resolution path');
  const sub = broad.child_ids.map(id => records.get(id)).find(row => row?.child_ids.some(id => records.get(id)?.level === 'micro'));
  const micro = sub.child_ids.map(id => records.get(id)).find(row => row?.level === 'micro');
  await evaluate(`location.hash = new URLSearchParams({community: ${JSON.stringify(broad.id)}})`);
  await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify("Community descriptors: " + broad.label));
  assert.ok(await evaluate("document.querySelector('#detail').textContent.includes('derived from source features')"));
  assert.equal(await evaluate("document.querySelector('.artist-list').dataset.evidenceRole"), 'inferred_community_membership');
  assert.equal(await evaluate("document.querySelector('.feature-list').dataset.evidenceRole"), 'derived_feature_descriptors');
  assert.ok(await evaluate("document.querySelector('#detail .count').textContent.includes('assigned members') && document.querySelector('#detail').textContent.includes('member counts overlap')"));
  assert.ok(await evaluate("document.querySelector('#detail').textContent.includes('full retained feature catalog') && document.querySelector('.feature-list').textContent.includes('catalog artists with this feature')"));
  assert.ok(await evaluate("document.querySelector('.map-caption').textContent.includes('Suggested communities') && document.querySelector('.map-caption').textContent.includes('metadata similarity') && document.querySelector('#about').textContent.includes('model outputs inferred')"));
  await screenshot('broad.png');
  await evaluate(`document.querySelector('.branch-list [data-community-id=${JSON.stringify(sub.id)}]').click()`);
  await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify("Community descriptors: " + sub.label));
  assert.ok(await evaluate("document.querySelector('[data-level=sub]').getAttribute('aria-pressed') === 'true'"));
  await screenshot('sub.png');
  await evaluate(`document.querySelector('.branch-list [data-community-id=${JSON.stringify(micro.id)}]').click()`);
  await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify("Community descriptors: " + micro.label));
  assert.ok(await evaluate("document.querySelector('[data-level=micro]').getAttribute('aria-pressed') === 'true'"));
  assert.equal(await evaluate("document.querySelectorAll('#breadcrumbs a').length"), 3);
  await screenshot('micro.png');
  await evaluate('history.back()');
  await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify("Community descriptors: " + sub.label));
  await evaluate('history.forward()');
  await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify("Community descriptors: " + micro.label));
  await command('Page.reload');
  await wait("document.documentElement?.dataset.communityPreviewReady === 'true' && document.querySelector('#detail h2')?.textContent === " + JSON.stringify("Community descriptors: " + micro.label));
  await evaluate("document.querySelector('#view-list').click()");
  assert.ok(await evaluate("!document.querySelector('#community-directory').hidden && document.querySelectorAll('.community-card').length > 0"));
  await screenshot('community-list.png');
  await evaluate("document.querySelector('#directory-sort').value = 'artists'; document.querySelector('#directory-sort').dispatchEvent(new Event('change'))");
  const sorted = await evaluate("[...document.querySelectorAll('.community-card small')].map(row => Number(row.textContent.split(' assigned members')[0].replaceAll(',', '')))");
  assert.ok(sorted.every((value, index) => index === 0 || value <= sorted[index - 1]));
  const knownArtists = [];
  for (const name of ['Aphex Twin', 'Four Tet']) {
    await evaluate("document.querySelector('[name=search-scope][value=artists]').click(); document.querySelector('#model-search').value = " + JSON.stringify(name) + "; document.querySelector('#model-search').dispatchEvent(new Event('input'))");
    await wait("[...document.querySelectorAll('#search-results [data-artist-id]')].some(node => node.firstChild.textContent === " + JSON.stringify(name) + ")");
    const artistId = await evaluate("(() => { const item = [...document.querySelectorAll('#search-results [data-artist-id]')].find(node => node.firstChild.textContent === " + JSON.stringify(name) + "); const id = item.dataset.artistId; item.click(); return id; })()");
    await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify(name) + " && Boolean(document.querySelector('.membership-list'))");
    const artist = await evaluate("({name: document.querySelector('#detail h2').textContent, membershipCount: document.querySelectorAll('.membership-button').length, sourceObservationCount: document.querySelectorAll('.source-button').length, levels: [...new Set([...document.querySelectorAll('.membership-button')].map(node => node.dataset.level))].map(level => level[0].toUpperCase() + level.slice(1) + ' communities')})");
    const modelAssignment = await evaluate("fetch('community-artists/' + " + JSON.stringify(artistId.slice(0, 3)) + " + '.json').then(response => response.json()).then(payload => payload.artists[" + JSON.stringify(artistId) + "])");
    assert.ok(modelAssignment, name + ' must retain an exact model assignment record');
    assert.equal(artist.membershipCount, modelAssignment.memberships.length, 'UI must show actual memberships without inventing finer assignments');
    const expectedLevels = [...new Set(modelAssignment.memberships.map(row => records.get(row.community_id).level))];
    assert.ok(artist.membershipCount > 0);
    assert.deepEqual(artist.levels.map(value => value.split(' ')[0].toLowerCase()).sort(), [...expectedLevels].sort(), 'artist view must preserve actual adaptive resolutions');
    artist.modelLevels = expectedLevels; artist.microAssignmentAbstained = !expectedLevels.includes('micro');
    if (artist.microAssignmentAbstained) assert.ok(await evaluate("Boolean(document.querySelector('[data-evidence-role=model_abstention][data-level=micro]'))"));
    assert.ok(await evaluate("document.querySelector('#breadcrumbs [aria-current=true]').dataset.communityId").then(id => modelAssignment.memberships.some(row => row.community_id === id)), 'artist search must focus a supported model branch');
    assert.equal(await evaluate("document.querySelector('.membership-list').dataset.evidenceRole"), 'inferred_community_membership');
    assert.equal(await evaluate("document.querySelector('.source-list').dataset.evidenceRole"), 'direct_source_observation');
    assert.ok(await evaluate("document.querySelector('#detail').textContent.includes('not probabilities')"));
    if (await evaluate("Boolean(document.body.dataset.artistExamples)")) {
      await wait("document.querySelectorAll('.artist-work-examples a').length === 12");
      assert.deepEqual(await evaluate("[...document.querySelectorAll('.artist-work-examples h3')].map(row=>row.textContent)"), ['Recordings', 'Release context']);
      assert.ok(await evaluate("[...document.querySelectorAll('.artist-work-examples a')].every(row=>row.href.startsWith('https://musicbrainz.org/') && row.rel.includes('noopener') && row.dataset.entityId.startsWith('musicbrainz:'))"));
      assert.ok(await evaluate("document.querySelector('.artist-work-examples').textContent.includes('bounded source sample')"));
    }
    await screenshot(name === 'Aphex Twin' ? 'aphex-twin.png' : 'four-tet.png');
    if (Array.isArray(modelAssignment.feature_proposals)) {
      const suggestions = await evaluate("[...document.querySelectorAll('.suggestion-card')].map(node => ({value: node.dataset.featureValue, role: node.dataset.evidenceRole, nativeFact: node.dataset.nativeFact}))");
      assert.deepEqual(suggestions.map(row => row.value), modelAssignment.feature_proposals.map(row => row.value), 'all verified exported suggestions must render independently of source facts');
      assert.ok(suggestions.every(row => row.role === 'inferred_feature_proposal' && row.nativeFact === 'false'));
      artist.featureSuggestions = suggestions.map(row => row.value);
      assert.equal(await evaluate("document.querySelectorAll('.suggestion-notice').length"), 0);
      if (name === 'Aphex Twin' && suggestions.length) {
        await evaluate("document.querySelector('.style-suggestions').scrollIntoView({block:'start'}); document.querySelector('.suggestion-evidence').open = true");
        await screenshot('aphex-style-suggestions.png');
      }
    }
    await command('Page.reload');
    await wait("document.documentElement?.dataset.communityPreviewReady === 'true' && document.querySelector('#detail h2')?.textContent === " + JSON.stringify(name) + " && Boolean(document.querySelector('.membership-list'))");
    assert.ok(await evaluate("location.hash.includes('artist=' + " + JSON.stringify(artistId) + ")"));
    knownArtists.push({...artist, artistId});
  }
  await evaluate("document.querySelector('.membership-button').click()");
  assert.ok(await evaluate("Boolean(document.querySelector('.feature-list'))"));
  const hasPositions = metadata.communities.some(row => Number.isFinite(row.x) && Number.isFinite(row.y));
  let zoomCheck = false;
  if (hasPositions) {
    const mapCommunity = metadata.communities.find(row => Number.isFinite(row.x) && Number.isFinite(row.y));
    await evaluate(`location.hash = new URLSearchParams({community: ${JSON.stringify(mapCommunity.id)}})`);
    await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify("Community descriptors: " + mapCommunity.label));
    await evaluate("document.querySelector('#view-map').click(); document.querySelector('#fit-map').click()");
    const painted = () => evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve(document.querySelector('canvas').toDataURL()))))");
    const before = await painted(); await evaluate("document.querySelector('#zoom-in').click()");
    assert.notEqual(await painted(), before); zoomCheck = true;
  }
  await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
  assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'), false);
  await screenshot('mobile.png');
  await evaluate("document.querySelector('[name=search-scope][value=communities]').click(); document.querySelector('#model-search').value = 'missing-model-community-928724'; document.querySelector('#model-search').dispatchEvent(new Event('input'))");
  assert.ok(await evaluate("document.querySelector('#search-results').textContent.includes('No matching')"));
  const external = requests.filter(request => new URL(request.url).origin !== new URL(url).origin);
  const media = requests.filter(request => request.type === 'Media' || /\.(?:mp3|m4a|ogg|wav|flac|aac|aiff|opus|webm|mp4)(?:[?#]|$)/i.test(request.url));
  assert.deepEqual(external, []); assert.deepEqual(media, []); assert.deepEqual(errors, []);
  await writeFile(join(output, 'browser-report.json'), JSON.stringify({revision: 'emergent-community-preview-browser-v1', scope: 'local_research_only', url, ready_ms: readyMs, community_counts: counts, supported_path: {broad: broad.id, sub: sub.id, micro: micro.id}, hierarchy_navigation: true, skipped_resolution_navigation: Boolean(skippedBranch), unsupported_broad_candidates_labeled: Boolean(unsupportedBroad), browser_history: true, community_deep_link_reload: true, directory_sort: true, member_and_catalog_support_counts_distinguished: true, sibling_centroid_proximity_labeled: true, known_artists: knownArtists, exact_artist_deep_links: true, direct_and_inferred_roles_separate: true, zoom_changes_graph: zoomCheck, mobile_no_overflow: true, zero_match_state: true, request_count: requests.length, external_requests: 0, media_requests: 0, runtime_errors: errors, public_export_authorized: false}, null, 2) + '\n');
  process.stdout.write(JSON.stringify({output, status: 'passed', screenshots: screenshotCount}) + '\n');
} finally {
  socket?.close(); browser.kill('SIGKILL');
  await new Promise(resolve_ => browser.exitCode !== null || browser.signalCode !== null ? resolve_() : browser.once('close', resolve_));
  await rm(profile, {recursive: true, force: true});
}
