/** Browser acceptance and screenshots for the partial portable CC0 explorer. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const [url, destination] = process.argv.slice(2);
if (!url || !destination) throw new Error('usage: capture_open_foundation.mjs LOCAL_URL NEW_CACHE_DIRECTORY');
if (!['127.0.0.1', 'localhost', '[::1]'].includes(new URL(url).hostname)) throw new Error('Preview browser checks require a local URL');
const root = fileURLToPath(new URL('../', import.meta.url));
const output = resolve(destination);
if (!output.startsWith(resolve(root, '.cache') + sep)) throw new Error('Browser evidence must remain under .cache');
await mkdir(output);
const profile = await mkdtemp(join(tmpdir(), 'opennoise-portable-preview-'));
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
  await wait("Boolean(document.querySelector('.genre-grid a'))");
  const metadata = await evaluate("fetch('./data.json').then(response=>response.json())");
  assert.equal(metadata.revision,'open-foundation-portable-v1');
  assert.equal(metadata.scope.status,'partial_selected_cohort');
  assert.equal(metadata.scope.full_foundation_complete,false);
  assert.equal(metadata.scope.historical_inputs_used,false);
  assert.equal(metadata.scope.noncommercial_packs_used,false);
  assert.equal(metadata.counts.artists,150);
  assert.equal(await evaluate("document.querySelectorAll('.genre-grid a').length"),metadata.genres.length);
  assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'),false);
  await screenshot('desktop.png');
  // Use real keyboard submission, then a native route link and browser history.
  await evaluate("document.querySelector('#search').focus()");
  await command('Input.insertText',{text:'f22942a1-6f70-4f48-866e-238cb2308fbd'});
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
  await wait("document.querySelector('.artist-list a')?.textContent === 'Aphex Twin'");
  await evaluate("document.querySelector('.artist-list a').click()");
  await wait("document.querySelector('h1')?.textContent === 'Aphex Twin'");
  assert.equal(await evaluate("document.querySelectorAll('.credits li').length"),6);
  assert.ok(await evaluate("Boolean(document.querySelector('.genre-grid a'))"));
  await screenshot('artist.png');
  await command('Page.reload');
  await wait("document.querySelector('h1')?.textContent === 'Aphex Twin' && document.querySelectorAll('.credits li').length === 6");
  await evaluate('history.back()');
  await wait("document.querySelector('h1')?.textContent.startsWith('Search:')");
  // Every bounded genre cohort is reachable and complete, with no hidden samples.
  for(const genre of metadata.genres){
    await evaluate(`location.hash=${JSON.stringify('#genre/'+genre.genre_id)}`);
    await wait(`document.querySelector('h1')?.textContent === ${JSON.stringify(genre.name)}`);
    assert.equal(await evaluate("document.querySelectorAll('.artist-list a').length"),genre.artist_mbids.length);
  }
  await evaluate("location.hash='#artists'");
  await wait("document.querySelectorAll('.artist-list a').length === 150");
  const ids=await evaluate("[...document.querySelectorAll('.artist-list a')].map(a=>decodeURIComponent(a.hash.slice(8))).sort()");
  assert.deepEqual(ids,metadata.artists.map(a=>a.artist_mbid).sort());
  const missing=metadata.artists.find(a=>!a.direct_genres.length);
  assert.ok(missing);
  await evaluate(`location.hash=${JSON.stringify('#artist/'+missing.artist_mbid)}`);
  await wait(`document.querySelector('h1')?.textContent === ${JSON.stringify(missing.name)}`);
  assert.ok(await evaluate("document.querySelector('#main').textContent.includes('No direct genre was observed')"));
  // Native ten-artist recording cohort must retain exact IDs and bounded credits.
  const benchmarks=metadata.artists.filter(a=>a.recordings.length);
  assert.equal(benchmarks.length,10);
  for(const artist of benchmarks){
    await evaluate(`location.hash=${JSON.stringify('#artist/'+artist.artist_mbid)}`);
    await wait(`document.querySelector('h1')?.textContent === ${JSON.stringify(artist.name)}`);
    assert.equal(await evaluate("document.querySelectorAll('.credits li').length"),artist.recordings.length);
    assert.equal(await evaluate("document.querySelectorAll('audio,video,iframe,embed').length"),0);
  }
  await evaluate("document.querySelector('.credits button').click();document.querySelector('.listening-list-toggle').click()");
  assert.equal(await evaluate("document.querySelector('dialog').open"),true);
  assert.ok(await evaluate("document.querySelector('.listening-tracks').textContent.includes('Remove')"));
  await evaluate("[...document.querySelectorAll('dialog button')].find(b=>b.textContent==='Close').click()");
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await evaluate("location.hash='#'");
  await wait("document.querySelector('h1')?.textContent === 'Open music discovery'");
  assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'),false);
  await screenshot('mobile.png');
  assert.deepEqual(errors,[]);
  assert.ok(requests.every(request=>new URL(request.url).origin===new URL(url).origin),'browser must request static local assets only');
  const receipt=await evaluate("fetch('receipt.json').then(response=>response.json())");
  await writeFile(join(output,'report.json'),JSON.stringify({revision:'portable-foundation-browser-v1',passed:true,scope:metadata.scope,counts:metadata.counts,build_files_sha256:receipt.files_sha256,checks:{exact_id_keyboard_search:true,artist_selection:true,reload:true,history:true,complete_artist_list:true,complete_genre_cohorts:metadata.genres.length,missingness:true,native_benchmark_artist_routes:benchmarks.length,listening_list:true,mobile_no_overflow:true,no_embedded_media:true,no_external_requests:true},errors,request_count:requests.length},null,2)+'\n');
  console.log(`Portable foundation browser passed: ${metadata.counts.artists} artists, ${metadata.genres.length} complete genre cohorts`);
} finally {
  socket?.close();
  browser.kill('SIGTERM');
  await new Promise(resolve_=>browser.once('close',resolve_));
  await rm(profile,{recursive:true,force:true});
}
