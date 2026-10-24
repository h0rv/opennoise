import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const [url, destination, siteRoot] = process.argv.slice(2);
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
let socket, evaluate;
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
  evaluate = async expression => {
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


  const source = resolve(siteRoot);
  const genres = JSON.parse(await readFile(join(source, 'atlas/genres.json')));
  const artists = JSON.parse(await readFile(join(source, 'atlas/artists.json')));
  const receipt = JSON.parse(await readFile(join(source, 'atlas/receipt.json')));
  assert.equal(genres.length, 1366); assert.equal(artists.length, 86253);
  for (const rows of [genres, artists]) { assert.equal(new Set(rows.map(r=>r.id)).size,rows.length); assert.ok(rows.every(r=>r.name.trim())); }
  const name = (rows, value) => { const row = rows.find(r=>r.name===value); assert.ok(row, value); return row; };
  const jazz = name(genres, 'Jazz'), aphex = name(artists, 'Aphex Twin'), fourTet = name(artists, 'Four Tet');
  const ready = "document.querySelector('main[aria-busy=false]')";
  const go = async hash => { await evaluate(`location.hash=${JSON.stringify(hash)}`); await wait(`${ready}&&location.hash===${JSON.stringify(hash)}`); };
  const title = async value => wait(`${ready}?.querySelector('h1')?.textContent===${JSON.stringify(value)}`);
  const checkMap = async () => {
    const result = await evaluate(`(()=>{const svg=document.querySelector('.map-shell svg');const rows=[...svg.querySelectorAll('a')]; const boxes=rows.map(a=>a.querySelector('rect').getBoundingClientRect());const texts=rows.map(a=>a.querySelector('text').getBoundingClientRect());let overlaps=0;for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){const a=boxes[i],b=boxes[j];if(a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top)overlaps++;}return{targets:rows.length,overlaps,minHeight:Math.min(...boxes.map(b=>b.height)),fontSizes:[...new Set(rows.map(a=>getComputedStyle(a.querySelector('text')).fontSize))],empty:rows.filter(a=>!a.textContent.trim()).length,overflow:document.documentElement.scrollWidth>innerWidth,clipped:texts.filter((t,i)=>t.left<boxes[i].left-.1||t.right>boxes[i].right+.1).length}})()`);
    assert.equal(result.overlaps,0);assert.equal(result.empty,0);assert.equal(result.clipped,0);assert.equal(result.overflow,false);assert.ok(result.minHeight>=43.99);assert.deepEqual(result.fontSizes,['16px']);return result;
  };
  await command('Network.enable');await command('Runtime.enable');await command('Page.enable');
  await command('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await command('Page.navigate',{url});await title('Genres');
  const reachable = await evaluate("[...document.querySelectorAll('main a[href^=\"#genre/\"]')].map(a=>a.getAttribute('href'))");
  assert.equal(new Set(reachable).size,genres.length);assert.equal(reachable.length,genres.length);
  const rootMap=await checkMap();await screenshot('desktop-genres.png');
  await go('#genres/list');await title('Genres');assert.equal(await evaluate("document.querySelectorAll('main .names li').length"),genres.length);
  await go(`#genre/${jazz.id}/list/0`);await title('Jazz');assert.equal(await evaluate("document.querySelectorAll('main .names li').length"),60);
  const jazzData=JSON.parse(await readFile(join(source,`atlas/genres/${jazz.id}.json`)));
  const jazzPage=Math.ceil(jazzData.artists.length/60)-1;
  await go(`#genre/${jazz.id}/list/${jazzPage}`);await title('Jazz');assert.equal(await evaluate("document.querySelectorAll('main .names li').length"),jazzData.artists.length-jazzPage*60);
  await go(`#genre/${jazz.id}/map/0`);await title('Jazz');assert.ok((await checkMap()).targets>30);await screenshot('desktop-jazz-map.png');
  await go('#artists');await title('Artists');assert.ok(await evaluate("document.querySelector('.scope').textContent.includes('86,253')"));assert.equal(await evaluate("document.querySelectorAll('main .names li').length"),60);
  const lastPage=Math.ceil(artists.length/60)-1;await go(`#artists/${lastPage}`);await title('Artists');assert.equal(await evaluate("document.querySelectorAll('main .names li').length"),artists.length-lastPage*60);
  await evaluate("document.querySelector('input').value='';document.querySelector('input').focus()");await command('Input.insertText',{text:'Aphex Twin'});await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r',unmodifiedText:'\r'});await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});await title('Aphex Twin');
  assert.ok(await evaluate(`document.querySelector('a[href="#artist/${aphex.id}"]')!==null`));
  await go(`#artist/${aphex.id}/map/0`);await title('Aphex Twin');await checkMap();await screenshot('desktop-artist.png');
  await go(`#artist/${aphex.id}/list/0`);await title('Aphex Twin');assert.ok(await evaluate("[...document.querySelectorAll('h2')].some(h=>h.textContent==='Suggested')"));
  await command('Page.reload');await title('Aphex Twin');await evaluate('history.back()');await wait(`${ready}&&document.querySelector('.map-shell')`);await evaluate('history.forward()');await wait(`${ready}&&!document.querySelector('.map-shell')`);
  for (const query of ['100 gecs','Four Tet']) { await go(`#q/${encodeURIComponent(query)}/0`);await title(query);assert.ok(await evaluate("document.querySelectorAll('main .names a').length>0"));assert.equal(await evaluate("document.querySelector('main').textContent.includes('No matches.')"),false); }
  for(const row of [artists.find(a=>/[^\u0000-\u007f]/.test(a.name)),artists.reduce((a,b)=>a.name.length>b.name.length?a:b)]) {await go(`#q/${encodeURIComponent(row.name)}/0`);await title(row.name);assert.ok(await evaluate(`document.querySelector('main a[href="#artist/${row.id}"]')!==null`));}
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await command('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:1});
  await go(`#artist/${fourTet.id}`);await title('Four Tet');assert.equal(await evaluate("document.querySelector('.map-shell')!==null"),false);assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);await screenshot('mobile-artist-list.png');
  await go(`#artist/${fourTet.id}/map/0`);await title('Four Tet');await checkMap();const before=await evaluate("document.querySelector('.map-shell svg').getBoundingClientRect().width");await evaluate("document.querySelector('[aria-label=\"Zoom in\"]').click()");assert.ok(await evaluate("document.querySelector('.map-shell svg').getBoundingClientRect().width")>before);await evaluate("document.querySelector('[aria-label=\"Reset map\"]').click()");assert.equal(await evaluate("document.querySelector('.map-shell svg').getBoundingClientRect().width"),before);await screenshot('mobile-readable-map.png');
  await go(`#genre/${jazz.id}`);await title('Jazz');assert.equal(await evaluate("document.querySelector('.map-shell')!==null"),false);
  const target=await evaluate("(()=>{const a=document.querySelector('main .names a');a.scrollIntoView();const r=a.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2,id:a.getAttribute('href').split('/')[1]}})()");await command('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:target.x,y:target.y}]});await command('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await wait(`${ready}&&location.hash.includes(${JSON.stringify(target.id)})`);
  await command('Emulation.setDeviceMetricsOverride',{width:320,height:800,deviceScaleFactor:1,mobile:true});assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
  await go('#q/zzzzzzzzzzzzzzzzzz/0');await wait(`${ready}?.textContent.includes('No matches.')`);assert.equal(await evaluate("document.querySelectorAll('main .names li').length"),0);
  await evaluate("document.querySelector('details').open=true");assert.ok(await evaluate("document.querySelector('#sources img')?.complete&&document.querySelector('#sources img').naturalWidth>0"));
  const external=requests.filter(r=>!['data:','blob:'].includes(new URL(r.url).protocol)&&new URL(r.url).origin!==new URL(url).origin);assert.deepEqual(external,[]);assert.deepEqual(requests.filter(r=>r.type==='Media'),[]);assert.deepEqual(errors,[]);
  if(new URL(url).protocol==='file:')assert.equal(requests.filter(r=>/^https?:/.test(r.url)).length,0);
  const report={status:'passed',url,counts:receipt.counts,all_genres_reachable:true,root_map:rootMap,complete_paginated_directory:true,complete_genre_members:true,keyboard_search:true,nonLatin_and_long_name_search:true,landing_search_both_catalogs:true,desktop_maps_nonoverlapping:true,mobile_default_list:true,mobile_touch:true,mobile_map_readable_44px:true,zoom:true,history_reload:true,empty_state:true,external_requests:0,runtime_errors:errors,screenshots:screenshotCount,publication:false};await writeFile(join(output,'browser-report.json'),JSON.stringify(report,null,2)+'\n');process.stdout.write(JSON.stringify(report)+'\n');
}catch(error){try{await screenshot('failure.png');if(evaluate)await writeFile(join(output,'dom-state.json'),JSON.stringify(await evaluate("({hash:location.hash,main:document.querySelector('main')?.innerHTML.slice(0,3000)})"),null,2));}catch{}await writeFile(join(output,'browser-failure.json'),JSON.stringify({error:String(error),errors,requests},null,2)+'\n');throw error;}finally{socket?.close();browser.kill('SIGKILL');await new Promise(resolve_=>browser.exitCode!==null||browser.signalCode!==null?resolve_():browser.once('close',resolve_));await rm(profile,{recursive:true,force:true});}
