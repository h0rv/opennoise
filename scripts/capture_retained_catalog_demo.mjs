/** Browser acceptance and screenshots for the local-only retained-catalog pipeline demonstration. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const [requestedURL, destination] = process.argv.slice(2);
let url = requestedURL;
if (!url || !destination) throw new Error('usage: capture_retained_catalog_demo.mjs LOCAL_URL NEW_CACHE_DIRECTORY');
if (new URL(url).protocol === 'file:') { if (!fileURLToPath(new URL(url)).startsWith(resolve('.cache') + sep)) throw new Error('File demo must be under .cache'); } else if (!['127.0.0.1', 'localhost', '[::1]'].includes(new URL(url).hostname)) throw new Error('Loopback or local file required');
// The retained catalog remains a required journey after the new atlas owns root.
// The canonical build separately certifies the new root and its offline copy.
if (new URL(url).protocol !== 'file:') {
  const response = await fetch(url);
  if (!response.ok) throw new Error('Local retained export unavailable');
  if ((await response.text()).includes('src="atlas.mjs"')) url = new URL('retained.html', url).href;
}
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
  const ready="document.querySelector('#main[aria-busy=false]') !== null";
  const key=async value=>{await command('Input.dispatchKeyEvent',{type:'keyDown',key:value});await command('Input.dispatchKeyEvent',{type:'keyUp',key:value});};
  const navigate=async hash=>{await evaluate(`location.hash=${JSON.stringify(hash)}`);await wait(ready);};
  await wait("document.querySelectorAll('.genre-map .map-name').length===148");
  const data=await evaluate("globalThis.OPENNOISE_LOCAL_FILES?.['pipeline.json'] ?? fetch('pipeline.json').then(r=>r.json())");
  const genres=await evaluate("globalThis.OPENNOISE_LOCAL_FILES?.['genres.json'] ?? fetch('genres.json').then(r=>r.json())");
  assert.equal(data.artists.length,440);assert.equal(genres.length,151);
  await wait("document.querySelectorAll('.genre-map .map-name').length===148");
  assert.equal(await evaluate("document.querySelectorAll('.unlinked-genres a').length"),3);
  const labelIDs=await evaluate("[...document.querySelectorAll('.genre-map a,.unlinked-genres a')].map(a=>a.getAttribute('href').split('/').at(-1)).sort()");
  assert.deepEqual(labelIDs,genres.map(g=>g.genre_id).sort());
  const collisionCount=await evaluate(`(()=>{const nodes=[...document.querySelectorAll('.map-name')];let count=0;for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){const a=nodes[i].getBoundingClientRect(),b=nodes[j].getBoundingClientRect();if(a.left<b.right-.5&&a.right>b.left+.5&&a.top<b.bottom-.5&&a.bottom>b.top+.5)count++;}return count;})()`);
  assert.equal(collisionCount,0,'genre name hit targets must not overlap');
  assert.equal(await evaluate("document.querySelectorAll('#main details[open]').length"),0);
  await screenshot('desktop-genre-map.png');
  const before=await evaluate("document.querySelector('.name-surface').style.zoom");
  await evaluate("document.querySelector('.genre-map').focus()");await key('+');
  assert.notEqual(await evaluate("document.querySelector('.name-surface').style.zoom"),before);
  await evaluate("document.querySelector('[aria-label=\"Reset map\"]').click()");
  const jazz=genres.find(g=>g.name==='jazz');assert.ok(jazz);
  await evaluate(`document.querySelector('.genre-map [href="#genre/${jazz.genre_id}"]').focus()`);await key('Enter');
  await wait("document.querySelector('.genre-artist-map')!==null");
  assert.equal(await evaluate("document.querySelectorAll('.genre-artist-map a').length"),jazz.artists.length);
  await screenshot('desktop-genre-artists.png');
  await evaluate("[...document.querySelectorAll('.view-links a')].find(a=>a.textContent==='List').click()");
  await wait("document.querySelector('.artist-list')!==null");
  assert.equal(await evaluate("document.querySelector('.artist-list').children.length"),jazz.artists.length);
  await command('Page.reload');await wait("document.querySelector('.artist-list')!==null");
  await evaluate("history.back()");await wait("document.querySelector('.genre-artist-map')!==null");
  const selected=jazz.artists.find(([id])=>data.artists.find(a=>a.id===id).recordings.length);assert.ok(selected);
  await evaluate(`document.querySelector('.genre-artist-map [href="#artist/${selected[0]}"]').click()`);
  await wait(`document.querySelector('#main[aria-busy=false] h1')?.textContent===${JSON.stringify(selected[1])}`);
  const creditTitles=await evaluate("[...document.querySelectorAll('.credits>li')].map(li=>li.querySelector('a').textContent)");
  assert.ok(creditTitles.length);assert.ok(creditTitles.every(t=>t.trim()));assert.equal(new Set(creditTitles).size,creditTitles.length);
  assert.ok(await evaluate("[...document.querySelectorAll('.credits a')].every(a=>a.href.startsWith('https://musicbrainz.org/recording/'))"));
  await screenshot('desktop-artist-recordings.png');
  for(const name of ['Aphex Twin','Four Tet','Morrissey']){
    await evaluate(`document.querySelector('#search').value=${JSON.stringify(name)};document.querySelector('#search-form').requestSubmit()`);
    await wait(`document.querySelector('#main[aria-busy=false] h1')?.textContent===${JSON.stringify('Search: '+name)}`);
    const artist=data.artists.find(a=>a.name===name);assert.ok(artist);
    await evaluate(`document.querySelector('main a[href$="#artist/${artist.id}"]').focus()`);await key('Enter');
    await wait(`document.querySelector('#main[aria-busy=false] h1')?.textContent===${JSON.stringify(name)}`);
    assert.ok(await evaluate("document.querySelector('main h1').textContent.trim().length>0"));
    await command('Page.navigate',{url:url.split('#')[0]+'#artist/'+artist.id});await wait(`document.querySelector('#main[aria-busy=false] h1')?.textContent===${JSON.stringify(name)}`);
    assert.ok(await evaluate("!document.querySelector('main').textContent.includes('Exact native credits.')"));
    if(name==='Morrissey')assert.ok(await evaluate("document.querySelector('main').textContent.includes('No observed genres.')"));
    const titles=await evaluate("[...document.querySelectorAll('.credits>li')].map(li=>li.querySelector('a').textContent)");
    assert.ok(titles.length);assert.equal(titles.length,new Set(titles).size);
  }
  await navigate('#q/Morrissey');await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent==='Search: Morrissey'");
  await navigate('#artist/'+data.artists.find(a=>a.name==='Morrissey').id);await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent==='Morrissey'");
  await command('Page.reload');await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent==='Morrissey'");
  await evaluate("history.back()");await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent==='Search: Morrissey'");
  await evaluate("history.forward()");await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent==='Morrissey'");
  await navigate('#artists/0');await wait("document.querySelectorAll('.artist-list li').length===440");
  assert.deepEqual(await evaluate("[...document.querySelectorAll('.artist-list a')].map(a=>a.getAttribute('href').split('/').at(-1)).sort()"),data.artists.map(a=>a.id).sort());
  await navigate('#genres');await wait("document.querySelectorAll('.genre-grid li').length===151");
  await navigate('#map/source');await wait("document.querySelectorAll('.demo-map circle').length===72");
  await navigate('#map/audio');await wait("document.querySelectorAll('.demo-map circle').length===17");
  assert.ok(await evaluate("document.querySelector('h1').textContent.includes('Suggested')"));
  await evaluate("document.querySelector('.demo-map').focus()");await key('ArrowRight');
  const keyboardArtist=await evaluate("document.activeElement.dataset.artist");assert.ok(keyboardArtist);await key('Enter');
  await wait(`document.querySelector('#main[aria-busy=false] h1')?.textContent===${JSON.stringify(data.artists.find(a=>a.id===keyboardArtist).name)}`);
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await navigate('#');await wait("document.querySelector('.genre-map')!==null");
  assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
  assert.equal(await evaluate("Math.min(...[...document.querySelectorAll('.map-name')].map(a=>a.getBoundingClientRect().height))>=44"),true);
  await screenshot('mobile-genre-map.png');
  await evaluate("document.querySelector('#search').value='jazz';document.querySelector('#search').dispatchEvent(new Event('input'))");
  assert.ok(await evaluate("document.querySelector('.atlas-tools [role=status]').textContent.includes('matching genres')"));
  const tap=await evaluate("(()=>{const a=document.querySelector('.genre-map a:not(.dimmed)');a.scrollIntoView({block:'center',inline:'center'});const r=a.getBoundingClientRect();return {name:a.textContent,x:r.x+r.width/2,y:r.y+r.height/2};})()");
  await command('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:tap.x,y:tap.y}]});await command('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  await wait(`document.querySelector('#main[aria-busy=false] h1')?.textContent===${JSON.stringify(tap.name)}`);
  assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
  await screenshot('mobile-genre-artists.png');
  for(const width of [320,390]){
    await command('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:true});
    await navigate('#artists/0');await wait("document.querySelectorAll('.artist-list li').length===440");
    assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
    const long=data.artists.reduce((a,b)=>a.name.length>b.name.length?a:b);
    await navigate('#artist/'+long.id);await wait(`document.querySelector('#main[aria-busy=false] h1')?.textContent===${JSON.stringify(long.name)}`);
    assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
  }
  await navigate('#');await wait("document.querySelector('.genre-map')!==null");
  await evaluate("document.querySelector('.skip').focus()");await key('Enter');
  assert.equal(await evaluate("document.activeElement.id"),'main');
  const external=requests.filter(r=>!['data:','blob:'].includes(new URL(r.url).protocol)&&new URL(r.url).origin!==new URL(url).origin);
  const media=requests.filter(r=>r.type==='Media');
  assert.deepEqual(external,[]);assert.deepEqual(media,[]);assert.deepEqual(errors,[]);
  if(new URL(url).protocol==='file:')assert.ok(!requests.some(r=>/^https?:/.test(r.url)),'standalone must not make HTTP requests');
  await writeFile(join(output,'browser-report.json'),JSON.stringify({status:'passed',url,artists:440,genres:151,mapped_genres:148,unlinked_genres:3,genre_hit_target_overlaps:collisionCount,genre_artist_recording_loop:true,complete_directories:true,source_and_suggested_separate:true,keyboard_search_and_maps:true,history_forward_back_reload:true,mobile_320_and_390_no_overflow:true,touch_genre_drilldown:true,recordings_nonempty_unique:true,external_requests:0,media_requests:0,runtime_errors:errors,screenshots:screenshotCount,publication:false},null,2)+'\n');
  process.stdout.write(JSON.stringify({status:'passed',output,screenshots:screenshotCount})+'\n');
} catch(error) {
  await writeFile(join(output,'browser-failure.json'),JSON.stringify({error:String(error),errors,requests},null,2)+'\n');
  throw error;
} finally {
  socket?.close(); browser.kill('SIGKILL');
  await new Promise(resolve_ => browser.exitCode !== null || browser.signalCode !== null ? resolve_() : browser.once('close', resolve_));
  await rm(profile, {recursive: true, force: true});
}
