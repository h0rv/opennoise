/** Browser acceptance and screenshots for the local-only named source style atlas. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const [url, destination] = process.argv.slice(2);
if (!url || !destination) throw new Error('usage: capture_style_atlas.mjs LOCAL_URL NEW_CACHE_DIRECTORY');
if (!['127.0.0.1', 'localhost', '[::1]'].includes(new URL(url).hostname)) throw new Error('Preview browser checks require a local URL');
const root = fileURLToPath(new URL('../', import.meta.url));
const output = resolve(destination);
if (!output.startsWith(resolve(root, '.cache') + sep)) throw new Error('Browser evidence must remain under .cache');
await mkdir(output);
const profile = await mkdtemp(join(tmpdir(), 'opennoise-style-atlas-'));
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
  await wait("document.documentElement?.dataset.styleAtlasReady === 'true'");
  const readyMs = await evaluate('Math.round(performance.now())');
  const catalog = await evaluate("fetch('data.json').then(response => response.json())");
  assert.equal(catalog.role, 'candidate_named_styles'); assert.equal(catalog.native_fact, false);
  assert.equal(catalog.coverage.artists, 198409);
  assert.ok(catalog.styles.length > 1000);
  if (catalog.display_recipe_revision) {
    const recordLabel=catalog.styles.find(style=>style.name.endsWith(' records')&&style.source_artist_support>=5);
    assert.ok(recordLabel,'repeated record-label metadata remains retained');
    for (const name of ['top 100','top 10',recordLabel.name,'sxsw']) {
      const row=catalog.styles.find(style=>style.name===name);assert.ok(row,'screened source label remains retained: '+name);
      assert.equal(row.default_visible,false);assert.equal(row.evidence_tier,'raw_source_candidate');
      assert.ok(row.display_suppression_reason);
    }
  }
  const initialRequests = [...requests];
  assert.ok(!initialRequests.some(row => /\/(?:artists|styles|cohorts)\/|artist-search\.json/.test(row.url)), 'overview must not prefetch artist profiles, cohorts, or artist search');
  assert.equal(await evaluate("document.querySelector('#tier-filter').value"), 'supported');
  assert.ok(await evaluate("document.querySelector('.map-legend').textContent.includes('not a validated taxonomy')"));
  await screenshot('overview.png');
  const findStyle = async style => {
    await evaluate("document.querySelector('#search-scope').value='styles';document.querySelector('#search-scope').dispatchEvent(new Event('change'));document.querySelector('#atlas-search').value=" + JSON.stringify(style.name) + ";document.querySelector('#atlas-search').dispatchEvent(new Event('input'))");
    await wait("Boolean(document.querySelector('#search-results [data-style-id=" + JSON.stringify(style.id) + "]'))");
    await evaluate("document.querySelector('#search-results [data-style-id=" + JSON.stringify(style.id) + "]').click()");
    await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify(style.name) + " && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
  };
  const roles = ['observed_artist_feature','credited_release_context','inferred_feature_proposal'];
  const target = catalog.styles.find(row => row.name === 'ambient' && row.counts[roles[0]] > 100 && roles.every(role => row.counts[role] > 0)) || catalog.styles.find(row => row.default_visible && row.counts[roles[0]] > 100 && roles.every(role => row.counts[role] > 0));
  assert.ok(target, 'a source style must expose real evidence cohorts and multi-page artists');
  await findStyle(target);
  const targetDetail = await evaluate("fetch(" + JSON.stringify(target.detail_path) + ").then(response=>response.json())");
  assert.equal(await evaluate("document.querySelector('.cohort-content').dataset.evidenceRole"), roles[0]);
  assert.ok(await evaluate("document.querySelector('#detail').textContent.includes('Artist observations')"));
  assert.equal(await evaluate("document.querySelectorAll('.artist-row').length"), 100);
  const firstArtist = await evaluate("document.querySelector('.artist-row').dataset.artistId");
  await screenshot('style-source-artists.png');
  await evaluate("[...document.querySelectorAll('.cohort-content .pagination button')].find(node=>node.textContent==='Next').click()");
  await wait("new URLSearchParams(location.hash.slice(1)).get('page') === '2' && document.querySelector('#detail').getAttribute('aria-busy') === 'false' && document.querySelector('.artist-row')?.dataset.artistId !== " + JSON.stringify(firstArtist));
  const secondPageArtist = await evaluate("document.querySelector('.artist-row').dataset.artistId");
  const secondPage = await evaluate("fetch(" + JSON.stringify(targetDetail.cohorts[roles[0]].pages[1]) + ").then(response=>response.json())");
  assert.equal(secondPageArtist, secondPage.artists[0].artist_mbid);
  await evaluate('history.back()');
  await wait("document.querySelector('.artist-row')?.dataset.artistId === " + JSON.stringify(firstArtist) + " && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
  await evaluate('history.forward()');
  await wait("document.querySelector('.artist-row')?.dataset.artistId === " + JSON.stringify(secondPageArtist) + " && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
  await command('Page.reload');
  await wait("document.documentElement?.dataset.styleAtlasReady === 'true' && document.querySelector('.artist-row')?.dataset.artistId === " + JSON.stringify(secondPageArtist));
  await evaluate("[...document.querySelectorAll('.cohort-content .pagination button')].find(node=>node.textContent==='Last').click()");
  const lastIndex = targetDetail.cohorts[roles[0]].pages.length - 1;
  const lastPage = await evaluate("fetch(" + JSON.stringify(targetDetail.cohorts[roles[0]].pages[lastIndex]) + ").then(response=>response.json())");
  await wait("document.querySelector('.artist-row')?.dataset.artistId === " + JSON.stringify(lastPage.artists[0].artist_mbid) + " && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
  assert.equal(await evaluate("document.querySelectorAll('.artist-row').length"), lastPage.artists.length);
  for (const role of roles.slice(1)) {
    await evaluate("document.querySelector('[data-cohort-role=" + JSON.stringify(role) + "]').click()");
    await wait("document.querySelector('.cohort-content')?.dataset.evidenceRole === " + JSON.stringify(role) + " && document.querySelectorAll('.artist-row').length > 0 && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
    assert.ok(await evaluate("document.querySelector('#detail').textContent.includes(" + JSON.stringify(role === roles[1] ? 'does not establish' : 'not probabilities') + ")"));
    assert.ok(await evaluate("document.querySelector('#detail').textContent.includes(" + JSON.stringify(role === roles[1] ? 'Release context' : 'Style suggestions') + ")"));
    await screenshot(role === roles[1] ? 'style-release-context.png' : 'style-inferred-artists.png');
  }
  await evaluate("document.querySelector('.artist-row').click()");
  await wait("Boolean(document.querySelector('.artist-evidence')) && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
  assert.ok(await evaluate("location.hash.includes('artist=')"));
  const knownArtists = [];
  for (const name of ['Aphex Twin','Four Tet']) {
    await evaluate("document.querySelector('#search-scope').value='artists';document.querySelector('#search-scope').dispatchEvent(new Event('change'));document.querySelector('#atlas-search').value=" + JSON.stringify(name) + ";document.querySelector('#atlas-search').dispatchEvent(new Event('input'))");
    await wait("[...document.querySelectorAll('#search-results [data-artist-id]')].some(node=>node.firstChild.textContent === " + JSON.stringify(name) + ")");
    const id = await evaluate("(() => {const row=[...document.querySelectorAll('#search-results [data-artist-id]')].find(node=>node.firstChild.textContent === " + JSON.stringify(name) + ");const id=row.dataset.artistId;row.click();return id})()");
    await wait("document.querySelector('#detail h2')?.textContent === " + JSON.stringify(name) + " && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
    const profile = await evaluate("fetch(" + JSON.stringify('artists/' + id.slice(0,3) + '.json') + ").then(response=>response.json()).then(payload=>payload.artists[" + JSON.stringify(id) + "])");
    const roleCounts = Object.fromEntries(roles.map(role=>[role,profile.style_memberships.filter(row=>row.role===role).length]));
    const rendered = await evaluate("Object.fromEntries(['observed_artist_feature','credited_release_context','inferred_feature_proposal'].map(role=>[role,document.querySelectorAll('.evidence-card.'+role).length]))");
    assert.deepEqual(rendered,roleCounts,'every typed source/inferred membership must render independently');
    assert.ok(await evaluate("[...document.querySelectorAll('.evidence-card')].every(node=>node.dataset.nativeFact==='false')"));
    assert.equal(await evaluate("document.querySelectorAll('#detail .error-state').length"),0);
    knownArtists.push({name,id,roleCounts,inferredValues:profile.style_memberships.filter(row=>row.role===roles[2]).map(row=>row.value)});
    await screenshot(name==='Aphex Twin'?'aphex-twin.png':'four-tet.png');
    if (name==='Aphex Twin') {
      await evaluate("document.querySelector('.artist-evidence[data-evidence-role=inferred_feature_proposal]').scrollIntoView({block:'start'});document.querySelector('.evidence-card.inferred_feature_proposal details').open=true");
      await screenshot('artist-inference-evidence.png');
    }
    await command('Page.reload');
    await wait("document.documentElement?.dataset.styleAtlasReady === 'true' && document.querySelector('#detail h2')?.textContent === " + JSON.stringify(name));
    assert.ok(await evaluate("location.hash.includes('artist='+" + JSON.stringify(id) + ")"));
  }
  const exactArtist = knownArtists.at(-1);
  await evaluate("document.querySelector('#atlas-search').value=" + JSON.stringify(exactArtist.id) + ";document.querySelector('#atlas-search').dispatchEvent(new Event('input'))");
  await wait("Boolean(document.querySelector('#search-results [data-artist-id=" + JSON.stringify(exactArtist.id) + "]'))");
  assert.equal(await evaluate("document.querySelector('#search-results [data-artist-id=" + JSON.stringify(exactArtist.id) + "] span').textContent"),exactArtist.name);
  await evaluate("document.querySelector('.back-button').click();document.querySelector('#list-view').click();document.querySelector('#tier-filter').value='all';document.querySelector('#tier-filter').dispatchEvent(new Event('change'));document.querySelector('#directory-sort').value='observed_artist_feature';document.querySelector('#directory-sort').dispatchEvent(new Event('change'))");
  assert.equal(await evaluate("document.querySelectorAll('.style-card').length"),200);
  const visibleIds = await evaluate("[...document.querySelectorAll('.style-card')].map(row=>row.dataset.styleId)");
  const byId = new Map(catalog.styles.map(row=>[row.id,row]));
  assert.ok(visibleIds.every((id,index)=>index===0||byId.get(id).counts[roles[0]]<=byId.get(visibleIds[index-1]).counts[roles[0]]));
  await screenshot('style-list.png');
  await evaluate("[...document.querySelectorAll('#directory-pager button')].find(node=>node.textContent==='Next').click()");
  assert.ok(await evaluate("new URLSearchParams(location.hash.slice(1)).get('directoryPage')==='2'"));
  assert.notEqual(await evaluate("document.querySelector('.style-card').dataset.styleId"),visibleIds[0]);
  await evaluate("document.querySelector('#evidence-filter').value='credited_release_context';document.querySelector('#evidence-filter').dispatchEvent(new Event('change'))");
  const releaseStyles = await evaluate("[...document.querySelectorAll('.style-card')].map(row=>row.dataset.styleId)");
  assert.ok(releaseStyles.length>0&&releaseStyles.every(id=>byId.get(id).counts[roles[1]]>0));
  await evaluate("document.querySelector('#placement-filter').value='unplaced';document.querySelector('#placement-filter').dispatchEvent(new Event('change'))");
  const unplacedStyles = await evaluate("[...document.querySelectorAll('.style-card')].map(row=>row.dataset.styleId)");
  assert.ok(unplacedStyles.length>0&&unplacedStyles.every(id=>!Number.isFinite(byId.get(id).x)));
  assert.ok(await evaluate("document.querySelector('#map-view').disabled && !document.querySelector('#style-directory').hidden"));
  await evaluate("document.querySelector('#placement-filter').value='all';document.querySelector('#placement-filter').dispatchEvent(new Event('change'));document.querySelector('#evidence-filter').value='all';document.querySelector('#evidence-filter').dispatchEvent(new Event('change'))");
  const raw = catalog.styles.find(row=>row.evidence_tier==='raw_source_candidate'&&!Number.isFinite(row.x));
  assert.ok(raw);await findStyle(raw);
  assert.equal(await evaluate("document.querySelector('#tier-filter').value"),'all');
  assert.ok(await evaluate("document.querySelector('#detail').textContent.includes('Unplaced:') && document.querySelector('#detail').textContent.includes('Raw source candidate')"));
  assert.ok(await evaluate("Boolean(document.querySelector('.style-card[aria-current=true]'))"));
  await screenshot('raw-unplaced-style.png');
  if (catalog.display_recipe_revision) {
    const screened=catalog.styles.find(row=>row.name==='sxsw');await findStyle(screened);
    assert.equal(await evaluate("document.querySelector('#tier-filter').value"),'all');
    assert.ok(await evaluate("document.querySelector('#detail').textContent.includes('Raw source candidate') && Boolean(document.querySelector('.style-card[aria-current=true]'))"));
  }
  await findStyle(target);await evaluate("document.querySelector('#map-view').click();document.querySelector('#fit-map').click()");
  const painted = () => evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(document.querySelector('canvas').toDataURL()))))");
  const before = await painted();await evaluate("document.querySelector('#zoom-in').click()");assert.notEqual(await painted(),before);
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))");
  assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'),false);
  assert.ok(await evaluate("document.querySelector('#atlas-status').getBoundingClientRect().top >= document.querySelector('.toolbar').getBoundingClientRect().bottom"));
  await screenshot('mobile.png');
  await evaluate("document.querySelector('#atlas-search').value='unmatched-style-query-927462';document.querySelector('#atlas-search').dispatchEvent(new Event('input'))");
  assert.ok(await evaluate("document.querySelector('#search-results').textContent.includes('No matching')"));
  const external = requests.filter(row=>new URL(row.url).origin !== new URL(url).origin);
  const media = requests.filter(row=>row.type==='Media'||/\.(?:mp3|m4a|ogg|wav|flac|aac|aiff|opus|webm|mp4)(?:[?#]|$)/i.test(row.url));
  assert.deepEqual(external,[]);assert.deepEqual(media,[]);assert.deepEqual(errors,[]);
  const report={revision:'named-style-atlas-browser-v1',scope:'local_research_only',url,ready_ms:readyMs,styles:catalog.styles.length,default_visible_styles:catalog.styles.filter(row=>row.default_visible).length,default_positioned_styles:catalog.styles.filter(row=>row.default_visible&&Number.isFinite(row.x)&&Number.isFinite(row.y)).length,display_recipe_revision:catalog.display_recipe_revision,nonstyle_labels_default_hidden:catalog.display_recipe_revision?true:null,initial_artist_or_cohort_prefetch:false,full_cohort_pagination:true,pagination_history_and_reload:true,typed_source_release_and_inferred_cohorts:true,artist_name_and_exact_id_search:true,known_artists:knownArtists,source_and_inferred_memberships_independent:true,raw_unplaced_candidates_searchable:true,directory_sort_and_pagination:true,evidence_and_placement_filters:true,zoom_changes_map:true,mobile_no_overflow:true,mobile_toolbar_status_separated:true,zero_match_state:true,request_count:requests.length,external_requests:0,media_requests:0,runtime_errors:errors,screenshots:screenshotCount,public_export_authorized:false};
  await writeFile(join(output,'browser-report.json'),JSON.stringify(report,null,2)+'\n');
  process.stdout.write(JSON.stringify({output,status:'passed',screenshots:screenshotCount})+'\n');
} finally {
  socket?.close(); browser.kill('SIGKILL');
  await new Promise(resolve_ => browser.exitCode !== null || browser.signalCode !== null ? resolve_() : browser.once('close', resolve_));
  await rm(profile, {recursive: true, force: true});
}
