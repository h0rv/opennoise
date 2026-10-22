/** Browser acceptance and screenshots for the local-only retained-catalog pipeline demonstration. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const [url, destination] = process.argv.slice(2);
if (!url || !destination) throw new Error('usage: capture_retained_catalog_demo.mjs LOCAL_URL NEW_CACHE_DIRECTORY');
if (new URL(url).protocol === 'file:') { if (!fileURLToPath(new URL(url)).startsWith(resolve('.cache') + sep)) throw new Error('File demo must be under .cache'); } else if (!['127.0.0.1', 'localhost', '[::1]'].includes(new URL(url).hostname)) throw new Error('Loopback or local file required');
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
  await command('Emulation.setDeviceMetricsOverride', {width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  const navigation=await command('Page.navigate',{url});
  if(navigation.errorText)throw new Error(`Navigation failed: ${navigation.errorText}`);
  await wait("document.querySelector('#main[aria-busy=false] .demo-map') !== null");
  const data = await evaluate("globalThis.OPENNOISE_LOCAL_FILES?.['pipeline.json'] ?? fetch('pipeline.json').then(r=>r.json())");
  assert.equal(data.artists.length,440); assert.equal(data.source_edges.length,290);
  assert.equal(await evaluate("document.querySelectorAll('.demo-map circle').length"),72);
  await screenshot('desktop-source-map.png');
  const broad = data.artists.find(a=>a.name==='Morrissey'); assert.ok(broad);
  await evaluate(`location.hash='#artist/${broad.id}'`);
  await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent === 'Morrissey'");
  assert.ok(await evaluate("document.querySelector('#main').textContent.includes('No acoustic feature rows')"));
  assert.equal(await evaluate("[...document.querySelectorAll('#main a')].some(a=>a.textContent==='Locate on the map')"),false);
  assert.ok(await evaluate("document.querySelector('#main').textContent.includes('no source-map position')"));
  await screenshot('broad-artist.png');
  for(const name of ['Aphex Twin','Four Tet']) {
    const artist=data.artists.find(a=>a.name===name);assert.ok(artist);
    await evaluate(`location.hash='#artist/${artist.id}'`);
    await wait(`document.querySelector('#main[aria-busy=false] h1')?.textContent === ${JSON.stringify(name)}`);
    assert.ok(await evaluate("document.querySelector('#main').textContent.includes('Recording features and provenance')"));
  }
  const fourTet=data.artists.find(a=>a.name==='Four Tet');
  await command('Page.reload');
  await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent === 'Four Tet'");
  assert.ok(await evaluate("document.querySelector('#main a[href^=\"https://musicbrainz.org/artist/\"]') !== null"));
  await screenshot('artist-features.png');
  await evaluate("location.hash='#map/audio'");
  await wait("document.querySelector('#main[aria-busy=false] .demo-map') !== null");
  assert.equal(await evaluate("document.querySelectorAll('.demo-map circle').length"),17);
  assert.ok(await evaluate("document.querySelector('#main').textContent.includes('Suggested')"));
  await screenshot('desktop-acoustic-map.png');
  const before=await evaluate("document.querySelector('.demo-map g').getAttribute('transform')");
  await evaluate("document.querySelector('.demo-map').focus()");
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'+',code:'Equal'});
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'+',code:'Equal'});
  assert.notEqual(await evaluate("document.querySelector('.demo-map g').getAttribute('transform')"),before);
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowRight',code:'ArrowRight'});
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'ArrowRight',code:'ArrowRight'});
  const keyboardArtist=await evaluate("document.activeElement.dataset.artist");
  assert.ok(keyboardArtist);
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter'});
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter'});
  await wait(`document.querySelector('#main[aria-busy=false] h1')?.textContent === ${JSON.stringify(data.artists.find(a=>a.id===keyboardArtist).name)}`);
  await evaluate("location.hash='#map/source'");
  await wait("document.querySelectorAll('.demo-map circle').length === 72");
  await evaluate("document.querySelector('#search').value='missing-name-392881';document.querySelector('#search').dispatchEvent(new Event('input'))");
  assert.ok(await evaluate("document.querySelector('#demo-artist-list').textContent.includes('No matching artists')"));
  await evaluate("document.querySelector('#search').value='Morrissey';document.querySelector('#search').dispatchEvent(new Event('input'))");
  assert.equal(await evaluate("document.querySelectorAll('#demo-artist-list li').length"),1);
  await evaluate("document.querySelector('#demo-artist-list a').focus()");
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter'});
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter'});
  await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent==='Morrissey'");
  await evaluate("history.back()");
  await wait("document.querySelector('#main[aria-busy=false] .demo-map') !== null");
  await evaluate("document.querySelector('#search').value='Frans';document.querySelector('#search-form').requestSubmit()");
  await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent==='Search: Frans'");
  assert.ok(await evaluate("document.querySelector('#main').textContent.includes('Frans Brüggen')"));
  await evaluate("location.hash='#artists/0'");
  await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent==='All artists'");
  assert.equal(await evaluate("document.querySelectorAll('#main .artist-list li').length"),440);
  await evaluate("location.hash='#genres'");
  await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent==='Genres'");
  assert.equal(await evaluate("document.querySelectorAll('.genre-grid li').length"),151);
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await evaluate("location.hash='#map/source'");
  await wait("document.querySelector('#main[aria-busy=false] .demo-map') !== null");
  await evaluate("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))");
  assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
  await screenshot('mobile-source-map.png');
  await evaluate("document.querySelector('.demo-map').scrollIntoView({block:'center'})");
  const tap=await evaluate("(()=>{const a=document.querySelector('.demo-map a');const r=a.querySelector('circle').getBoundingClientRect();return {id:a.dataset.artist,x:r.x+r.width/2,y:r.y+r.height/2};})()");
  await command('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:tap.x,y:tap.y}]});
  await command('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  await wait(`document.querySelector('#main[aria-busy=false] h1')?.textContent === ${JSON.stringify(data.artists.find(a=>a.id===tap.id).name)}`);
  await evaluate(`location.hash='#artist/${fourTet.id}'`);
  await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent==='Four Tet'");
  await command('Emulation.setDeviceMetricsOverride',{width:320,height:800,deviceScaleFactor:1,mobile:true});
  assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
  const external=requests.filter(r=>!['data:','blob:'].includes(new URL(r.url).protocol)&&new URL(r.url).origin!==new URL(url).origin);
  const media=requests.filter(r=>r.type==='Media');
  assert.deepEqual(external,[]);assert.deepEqual(media,[]);assert.deepEqual(errors,[]);
  if(new URL(url).protocol==='file:')assert.ok(!requests.some(r=>/^https?:/.test(r.url)),'standalone must not make HTTP requests');
  await writeFile(join(output,'browser-report.json'),JSON.stringify({status:'passed',url,artists:440,genres:151,acoustic_artists:17,complete_directory:true,source_and_suggested_separate:true,keyboard_search_and_map:true,history_and_reload:true,mobile_no_overflow:true,external_requests:0,media_requests:0,runtime_errors:errors,screenshots:screenshotCount,publication:false},null,2)+'\n');
  process.stdout.write(JSON.stringify({status:'passed',output,screenshots:screenshotCount})+'\n');
} catch(error) {
  await writeFile(join(output,'browser-failure.json'),JSON.stringify({error:String(error),errors,requests},null,2)+'\n');
  throw error;
} finally {
  socket?.close(); browser.kill('SIGKILL');
  await new Promise(resolve_ => browser.exitCode !== null || browser.signalCode !== null ? resolve_() : browser.once('close', resolve_));
  await rm(profile, {recursive: true, force: true});
}
