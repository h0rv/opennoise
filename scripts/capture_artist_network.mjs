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
if (!output.startsWith(resolve(root, '.cache') + sep)) throw new Error('Evidence must remain under listening-candidate');
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


  await command('Network.enable');await command('Runtime.enable');await command('Page.enable');
  await command('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await command('Page.navigate',{url});await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent==='Genres'");
  assert.equal(await evaluate("document.querySelectorAll('.genre-map a').length||document.querySelectorAll('.demo-genre-map a').length||document.querySelectorAll('.genre-atlas a').length"),148);
  await screenshot('genres-preserved.png');
  await evaluate("document.querySelector('#search').value='100 gecs';document.querySelector('#search-form').requestSubmit()");await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent==='Search: 100 gecs'");assert.ok(await evaluate("[...document.querySelectorAll('main a')].some(a=>a.textContent==='100 gecs'&&a.href.includes('artist-network/'))"));await command('Page.navigate',{url});await wait("document.querySelector('#main[aria-busy=false] h1')?.textContent==='Genres'");
  await evaluate("[...document.querySelectorAll('#music-navigation a')].find(a=>a.textContent==='Artists').click()");
  await wait("document.querySelector('main[aria-busy=false] h1')?.textContent==='Artists'");
  const catalog=await evaluate("globalThis.OPENNOISE_ARTIST_FILES?.['catalog.json']??fetch('catalog.json').then(r=>r.json())");
  assert.ok(catalog.artists.length>=5000);assert.equal(new Set(catalog.artists.map(a=>a.id)).size,catalog.artists.length);assert.ok(catalog.artists.every(a=>a.name.trim()));
  assert.equal(await evaluate("document.querySelectorAll('.artist-list li').length"),60);
  await screenshot('desktop-artists.png');
  for (const query of ['Can', 'Yes']) {
    await evaluate(`location.hash='#browse/${query}/0'`);await wait(`document.querySelector('main[aria-busy=false] h1')?.textContent==='Artists'&&document.querySelector('input').value==='${query}'`);
    assert.equal(await evaluate("document.querySelector('.artist-list a').textContent"), query);
  }
  await evaluate("location.hash='#browse//0'");await wait("document.querySelector('main[aria-busy=false] h1')?.textContent==='Artists'&&document.querySelector('input').value===''&&document.querySelectorAll('.artist-list li').length===60");
  const aphex=catalog.artists.find(a=>a.name==='Aphex Twin'),fourTet=catalog.artists.find(a=>a.name==='Four Tet');assert.ok(aphex&&fourTet);
  await evaluate("document.querySelector('input').focus()");await command('Input.insertText',{text:'Aphex Twin'});await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r',unmodifiedText:'\r'});await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r',unmodifiedText:'\r'});
  await wait("document.querySelectorAll('.artist-list li').length>=1&&document.querySelectorAll('.artist-list li').length<60");
  await evaluate(`document.querySelector('.artist-list a[href="#artist/${aphex.id}"]').click()`);await wait("document.querySelector('main[aria-busy=false] h1')?.textContent==='Aphex Twin'");
  assert.ok(await evaluate("document.querySelectorAll('.map-shell svg a').length>5"));
  const overlaps=await evaluate("(()=>{const rows=[...document.querySelectorAll('.map-shell text')].map(t=>t.getBoundingClientRect());let n=0;for(let i=0;i<rows.length;i++)for(let j=i+1;j<rows.length;j++){const a=rows[i],b=rows[j];if(a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top)n++;}return n;})()");
  assert.equal(overlaps,0);await screenshot('desktop-artist-map.png');
  const artistURL=await evaluate('location.href');await evaluate("[...document.querySelectorAll('.view-links a')].find(a=>a.textContent==='List').click()");await wait("document.querySelector('main[aria-busy=false]')&&!document.querySelector('.map-shell')");
  assert.ok(await evaluate("document.querySelectorAll('.artist-list a').length>5"));
  await command('Page.reload');await wait("document.querySelector('main[aria-busy=false] h1')?.textContent==='Aphex Twin'");
  await evaluate('history.back()');await wait("document.querySelector('.map-shell')");await evaluate('history.forward()');await wait("!document.querySelector('.map-shell')&&document.querySelector('main[aria-busy=false]')");
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await command('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:1});
  await evaluate(`location.hash='#artist/${fourTet.id}'`);await wait("document.querySelector('main[aria-busy=false] h1')?.textContent==='Four Tet'");assert.equal(await evaluate("document.querySelector('.map-shell')!==null"),false);assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);await screenshot('mobile-artist-list.png');
  await evaluate("[...document.querySelectorAll('.view-links a')].find(a=>a.textContent==='Map').click()");await wait("document.querySelector('.map-shell svg')!==null");assert.ok(await evaluate("Math.min(...[...document.querySelectorAll('.map-shell svg a')].map(a=>a.getBoundingClientRect().height))>=43.99"));const widthBefore=await evaluate("document.querySelector('.map-shell svg').getBoundingClientRect().width");await evaluate("document.querySelector('[aria-label=\"Zoom in\"]').click()");assert.ok(await evaluate("document.querySelector('.map-shell svg').getBoundingClientRect().width")>widthBefore);await screenshot('mobile-readable-map.png');await evaluate("[...document.querySelectorAll('.view-links a')].find(a=>a.textContent==='List').click()");await wait("document.querySelector('.artist-list a')!==null&&!document.querySelector('.map-shell')");
  const target=await evaluate("(()=>{const a=document.querySelector('.artist-list a');const r=a.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2,id:a.getAttribute('href').split('/')[1]}})()");await command('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:target.x,y:target.y}]});await command('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await wait(`location.hash.includes(${JSON.stringify(target.id)})&&document.querySelector('main[aria-busy=false]')`);
  await command('Emulation.setDeviceMetricsOverride',{width:320,height:800,deviceScaleFactor:1,mobile:true});assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
  const ant=catalog.artists.find(a=>a.name==='Ant Saunders');assert.ok(ant);
  const visibleMapQuery="(()=>{const shell=document.querySelector('.map-shell'),a=shell?.querySelector('text.selected')?.closest('a');if(!a)return{visible:false};const b=shell.getBoundingClientRect(),r=a.getBoundingClientRect();return{visible:r.left>=Math.max(0,b.left)-1&&r.right<=Math.min(innerWidth,b.right)+1&&r.top>=Math.max(0,b.top)-1&&r.bottom<=Math.min(innerHeight,b.bottom)+1,height:r.height,overflow:document.documentElement.scrollWidth>innerWidth};})()";
  for(const [width,height] of [[390,844],[320,740]]){
    await command('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:true});
    await evaluate(`location.hash='#artist/${ant.id}'`);await wait("document.querySelector('main[aria-busy=false] h1')?.textContent==='Ant Saunders'&&!document.querySelector('.map-shell')");
    await evaluate("[...document.querySelectorAll('.view-links a')].find(a=>a.textContent==='Map').click()");await wait("document.querySelector('main[aria-busy=false] .map-shell svg')!==null");
    let initial=await evaluate(visibleMapQuery);assert.ok(initial.visible,JSON.stringify(initial));assert.ok(initial.height>=43.99);assert.equal(initial.overflow,false);await screenshot(`mobile-initial-map-${width}.png`);
    await command('Page.reload');await wait("document.querySelector('main[aria-busy=false] h1')?.textContent==='Ant Saunders'&&document.querySelector('.map-shell svg')!==null");initial=await evaluate(visibleMapQuery);assert.ok(initial.visible,JSON.stringify(initial));
    await evaluate("document.querySelector('[aria-label=\"Zoom in\"]').click()");assert.ok((await evaluate(visibleMapQuery)).visible);await evaluate("document.querySelector('[aria-label=\"Reset map\"]').click()");assert.ok((await evaluate(visibleMapQuery)).visible);
  }
  await evaluate("location.hash='#browse/zzzzzzzzzzzzzzzzzzzzz/0'");await wait("document.querySelector('main[aria-busy=false]')?.textContent.includes('No matching artists.')");assert.equal(await evaluate("document.querySelectorAll('.artist-list li').length"),0);
  const external=requests.filter(r=>!['data:','blob:'].includes(new URL(r.url).protocol)&&new URL(r.url).origin!==new URL(url).origin);const media=requests.filter(r=>r.type==='Media');assert.deepEqual(external,[]);assert.deepEqual(media,[]);assert.deepEqual(errors,[]);
  const report={status:'passed',url,artists:catalog.artists.length,counts:catalog.counts,genre_map_preserved:148,complete_paginated_directory:true,keyboard_search:true,exact_search_priority:true,desktop_map_nonoverlapping:true,mobile_default_list:true,mobile_touch:true,landing_search_large_catalog:true,mobile_map_readable_44px_targets:true,mobile_map_initial_query_visible:true,zoom_controls:true,history_reload:true,empty_state:true,external_requests:0,audio_or_video_requests:0,runtime_errors:errors,screenshots:screenshotCount,publication:false};await writeFile(join(output,'browser-report.json'),JSON.stringify(report,null,2)+'\n');process.stdout.write(JSON.stringify(report)+'\n');
}catch(error){await screenshot('failure.png');await writeFile(join(output,'dom-state.json'),JSON.stringify(await evaluate("({hash:location.hash,input:document.querySelector('input')?.value,active:document.activeElement.outerHTML,main:document.querySelector('main').innerHTML.slice(0,2000)})"),null,2));await writeFile(join(output,'browser-failure.json'),JSON.stringify({error:String(error),errors,requests},null,2)+'\n');throw error;}finally{socket?.close();browser.kill('SIGKILL');await new Promise(resolve_=>browser.exitCode!==null||browser.signalCode!==null?resolve_():browser.once('close',resolve_));await rm(profile,{recursive:true,force:true});}
