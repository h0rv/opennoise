/** Browser acceptance and screenshots for the optional portable taxonomy explorer. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const [url, destination] = process.argv.slice(2);
if (!url || !destination) throw new Error('usage: capture_open_taxonomy.mjs LOCAL_URL NEW_CACHE_DIRECTORY');
if (!['127.0.0.1', 'localhost', '[::1]'].includes(new URL(url).hostname)) throw new Error('Preview browser checks require a local URL');
const root = fileURLToPath(new URL('../', import.meta.url));
const output = resolve(destination);
if (!output.startsWith(resolve(root, '.cache') + sep)) throw new Error('Browser evidence must remain under .cache');
await mkdir(output);
const profile = await mkdtemp(join(tmpdir(), 'opennoise-taxonomy-preview-'));
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
  await wait("Boolean(document.querySelector('.genre-list a'))");
  const metadata = await evaluate("fetch('./data.json').then(response=>response.json())");
  assert.equal(metadata.revision,'open-foundation-taxonomy-v1');
  assert.equal(metadata.scope.full_foundation_complete,false);
  assert.equal(metadata.scope.historical_inputs_used,false);
  assert.equal(metadata.scope.artist_membership_inference,false);
  assert.equal(metadata.scope.across_component_semantics,false);
  assert.equal(metadata.genres.length,1000);
  assert.equal(await evaluate("document.querySelectorAll('.genre-list a').length"),1000);
  const ids=await evaluate("[...document.querySelectorAll('.genre-list a')].map(a=>decodeURIComponent(a.hash.slice(7))).sort()");
  assert.deepEqual(ids,metadata.genres.map(g=>g.genre_id).sort());
  assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'),false);
  await screenshot('desktop.png');
  const isolated=metadata.genres.find(g=>g.position_status==='isolated');
  assert.ok(isolated);
  await evaluate("document.querySelector('#search').focus()");
  await command('Input.insertText',{text:isolated.genre_id});
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
  await wait(`document.querySelector('.genre-list a')?.textContent === ${JSON.stringify(isolated.name)}`);
  await evaluate("document.querySelector('.genre-list a').click()");
  await wait(`document.querySelector('h1')?.textContent === ${JSON.stringify(isolated.name)}`);
  assert.ok(await evaluate("document.querySelector('#main').textContent.includes('No selected genre connections')"));
  assert.ok(await evaluate("document.querySelector('#main').textContent.includes('No direct artist claim')"));
  assert.equal(await evaluate("document.querySelectorAll('.genre-list a').length"),0);
  await screenshot('unpositioned.png');
  await command('Page.reload');
  await wait(`document.querySelector('h1')?.textContent === ${JSON.stringify(isolated.name)}`);
  await evaluate('history.back()');
  await wait("document.querySelector('h1')?.textContent.startsWith('Search:')");
  await evaluate('history.forward()');
  await wait(`document.querySelector('h1')?.textContent === ${JSON.stringify(isolated.name)}`);
  const largest=[...metadata.components].sort((a,b)=>b.node_count-a.node_count)[0];
  await evaluate(`location.hash=${JSON.stringify('#component/'+encodeURIComponent(largest.component_id))}`);
  await wait("Boolean(document.querySelector('svg circle'))");
  const members=metadata.genres.filter(g=>g.component_id===largest.component_id);
  assert.equal(await evaluate("document.querySelectorAll('svg a').length"),members.length);
  assert.equal(await evaluate("document.querySelectorAll('.genre-list a').length"),members.length);
  assert.ok(await evaluate("document.querySelector('#main').textContent.includes('other components have separate coordinates')"));
  await screenshot('component.png');
  await evaluate("document.querySelector('svg a').focus()");
  assert.equal(await evaluate("document.activeElement.tagName.toLowerCase()"),'a');
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
  await wait("Boolean(document.querySelector('h1')) && !document.querySelector('svg')");
  const artistData=await evaluate("fetch('./artists/data.json').then(response=>response.json())");
  const observedGenre=metadata.genres.find(g=>artistData.artists.some(a=>a.direct_genres.includes(g.genre_id)));
  assert.ok(observedGenre);
  await evaluate(`location.hash=${JSON.stringify('#genre/'+observedGenre.genre_id)}`);
  await wait(`document.querySelector('h1')?.textContent === ${JSON.stringify(observedGenre.name)}`);
  assert.equal(await evaluate("document.querySelectorAll('.artist-list a').length"),artistData.artists.filter(a=>a.direct_genres.includes(observedGenre.genre_id)).length);
  await evaluate("document.querySelector('.artist-list a').click()");
  await wait("Boolean(document.querySelector('h1')) && location.pathname.endsWith('/artists/')");
  assert.ok(await evaluate("document.querySelector('#main').textContent.includes('Directly observed genres')"));
  await command('Page.navigate',{url});
  await wait("document.querySelectorAll('.genre-list a').length === 1000");
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'),false);
  await screenshot('mobile.png');
  await evaluate(`location.hash=${JSON.stringify('#component/'+encodeURIComponent(largest.component_id))}`);
  await wait("Boolean(document.querySelector('svg circle'))");
  assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'),false);
  await screenshot('mobile-component.png');
  assert.deepEqual(errors,[]);
  assert.ok(requests.every(request=>new URL(request.url).origin===new URL(url).origin),'browser must request static local assets only');
  assert.equal(await evaluate("document.querySelectorAll('audio,video,iframe,embed').length"),0);
  const receipt=await evaluate("fetch('receipt.json').then(response=>response.json())");
  await writeFile(join(output,'report.json'),JSON.stringify({revision:'portable-taxonomy-browser-v1',passed:true,scope:metadata.scope,counts:metadata.counts,build_files_sha256:receipt.files_sha256,artist_receipt_sha256:receipt.artist_receipt_sha256,checks:{all1000_genres_reachable:true,exact_id_keyboard_search:true,isolated_genre_abstention:true,no_inherited_membership:true,reload:true,back_forward:true,component_local_svg:true,svg_keyboard_navigation:true,exact_direct_artist_route:true,mobile_no_overflow:true,no_embedded_media:true,no_external_requests:true},errors,request_count:requests.length},null,2)+'\n');
  console.log(`Portable taxonomy browser passed: ${metadata.genres.length} genres, ${metadata.counts.positioned} positioned, ${metadata.counts.unpositioned} abstained`);
} finally {
  socket?.close();
  browser.kill('SIGTERM');
  await new Promise(resolve_=>browser.once('close',resolve_));
  await rm(profile,{recursive:true,force:true});
}
