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
let socket, evaluate, screenshot;
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
      try { if (await evaluate(expression)) return; }
      catch (error) { if (!/Execution context was destroyed|Cannot find context/.test(String(error))) throw error; }
      await new Promise(resolve_ => setTimeout(resolve_, 50));
    }
    throw new Error(`Browser condition failed: ${expression}`);
  };
  screenshot = async name => {
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
  let fallback;
  for (const prefix of '0123456789abcdef'.split('')) {
    const shard = JSON.parse(await readFile(join(source, `atlas/artists/${prefix}0.json`)));
    const entry = Object.entries(shard).find(([, row]) => row.suggestion_basis === 'artist_metadata' && row.suggested.length >= 5);
    if (entry) { fallback = {id: entry[0], ...entry[1]}; break; }
  }
  assert.ok(fallback, 'A metadata-supported isolated artist must be reachable');
  assert.equal(fallback.related.length, 0); assert.ok(!fallback.suggested.includes(fallback.id));
  const ready = "document.querySelector('main[aria-busy=false]')";
  const go = async hash => { await evaluate(`new Promise(resolve=>{location.hash=${JSON.stringify(hash)};setTimeout(resolve,0)})`); await wait(`${ready}&&location.hash===${JSON.stringify(hash)}`); };
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
  await go(`#artist/${fallback.id}`);await title(fallback.name);
  assert.ok(await evaluate("[...document.querySelectorAll('main h2')].some(h=>h.textContent==='Suggested')"));
  assert.equal(await evaluate("[...document.querySelectorAll('main h2')].some(h=>h.textContent==='Related artists')"), false);
  assert.ok(await evaluate("document.querySelector('[data-entity-source]').textContent.includes('artist metadata')"));
  assert.equal((await checkMap()).targets, fallback.suggested.length);await screenshot('desktop-metadata-artist.png');
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
  for (const [query, expected] of [['Can', 'Can (band)'], ['Yes', 'Yes (band)'], ['Love', 'Love (band)']]) {
    await go(`#q/${query}/0`);await title(query);
    const first = await evaluate("[...document.querySelectorAll('main .names a')].filter(a=>a.getAttribute('href').startsWith('#artist/')&&a.getAttribute('href').length===40).slice(0,3).map(a=>a.textContent)");
    assert.ok(first.includes(expected), `${expected} must be among the first three artist matches`);
  }
  await go('#q/Jazz/0');await title('Jazz');assert.equal(await evaluate("document.querySelector('main h2').textContent"),'Genres');
  for(const row of [artists.find(a=>/[^\u0000-\u007f]/.test(a.name)),artists.reduce((a,b)=>a.name.length>b.name.length?a:b)]) {await go(`#q/${encodeURIComponent(row.name)}/0`);await title(row.name);assert.ok(await evaluate(`document.querySelector('main a[href="#artist/${row.id}"]')!==null`));}
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await command('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:1});
  await go(`#artist/${fallback.id}`);await title(fallback.name);assert.equal(await evaluate("document.querySelector('.map-shell')!==null"),false);assert.equal(await evaluate("document.querySelectorAll('main .names a[href^=\"#artist/\"]').length"),fallback.suggested.length);assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);await screenshot('mobile-metadata-artist.png');
  await go(`#artist/${fourTet.id}`);await title('Four Tet');assert.equal(await evaluate("document.querySelector('.map-shell')!==null"),false);assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);await screenshot('mobile-artist-list.png');
  await go(`#artist/${fourTet.id}/map/0`);await title('Four Tet');await checkMap();const before=await evaluate("document.querySelector('.map-shell svg').getBoundingClientRect().width");await evaluate("document.querySelector('[aria-label=\"Zoom in\"]').click()");assert.ok(await evaluate("document.querySelector('.map-shell svg').getBoundingClientRect().width")>before);await evaluate("document.querySelector('[aria-label=\"Reset map\"]').click()");assert.equal(await evaluate("document.querySelector('.map-shell svg').getBoundingClientRect().width"),before);await screenshot('mobile-readable-map.png');
  await go(`#genre/${jazz.id}`);await title('Jazz');assert.equal(await evaluate("document.querySelector('.map-shell')!==null"),false);
  const target=await evaluate("(()=>{const a=document.querySelector('main .names a');a.scrollIntoView();const r=a.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2,id:a.getAttribute('href').split('/')[1]}})()");await command('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:target.x,y:target.y}]});await command('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await wait(`${ready}&&location.hash.includes(${JSON.stringify(target.id)})`);
  await command('Emulation.setDeviceMetricsOverride',{width:320,height:800,deviceScaleFactor:1,mobile:true});assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
  await go('#q/zzzzzzzzzzzzzzzzzz/0');await wait(`${ready}?.textContent.includes('No matches.')`);assert.equal(await evaluate("document.querySelectorAll('main .names li').length"),0);
  await evaluate("document.querySelector('details').open=true");assert.ok(await evaluate("document.querySelector('#sources img')?.complete&&document.querySelector('#sources img').naturalWidth>0"));
  const rootPage = new URL(url); rootPage.hash = '';
  const nativePage = new URL(new URL(url).protocol === 'file:' ? 'artist-network/OpenNoiseArtists.html' : 'artist-network/', rootPage);
  const nativeArtists = JSON.parse(await readFile(join(source, 'artist-network/catalog.json'))).artists;
  const miles = name(artists, 'Miles Davis'), nativeMiles = name(nativeArtists, 'Miles Davis');
  const wikiHash = `#artist/${miles.id}/list/0`;
  const rootVisit = async hash => {
    const target = new URL(rootPage); target.hash = hash;
    const token = `atlas-navigation-${Math.random()}`; await evaluate(`window.navigationProbe=${JSON.stringify(token)}`);
    const navigation = await command('Page.navigate', {url: target.href});
    if (!navigation.loaderId) await evaluate('new Promise(resolve=>setTimeout(resolve,0))');
    await wait(`location.href===${JSON.stringify(target.href)}&&${ready}${navigation.loaderId ? `&&window.navigationProbe!==${JSON.stringify(token)}` : ''}`);
  };
  const follow = async selector => {
    const target = await evaluate(`(()=>{const a=document.querySelector(${JSON.stringify(selector)});return a?new URL(a.getAttribute('href'),location.href).href:null})()`); assert.ok(target, selector);
    const crossing = new URL(target).pathname !== await evaluate('location.pathname');
    const token = `link-navigation-${Math.random()}`; await evaluate(`window.navigationProbe=${JSON.stringify(token)}`);
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}))`);
    if (!crossing) await evaluate('new Promise(resolve=>setTimeout(resolve,0))');
    await wait(`location.href===${JSON.stringify(target)}&&${ready}${crossing ? `&&window.navigationProbe!==${JSON.stringify(token)}` : ''}`); return target;
  };
  const actionTarget = async text => {
    await wait(`!![...document.querySelectorAll('main .artist-actions a')].find(a=>a.textContent===${JSON.stringify(text)})`);
    const box = await evaluate(`(()=>{const a=[...document.querySelectorAll('main .artist-actions a')].find(a=>a.textContent===${JSON.stringify(text)});if(!a)return null;const b=a.getBoundingClientRect();return{height:b.height,text:getComputedStyle(a).fontSize}})()`);
    assert.ok(box); assert.ok(box.height >= 44); assert.ok(parseFloat(box.text) >= 16); assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
  };
  for (const width of [1440, 390, 320]) {
    await command('Emulation.setDeviceMetricsOverride',{width,height:width===1440?1100:844,deviceScaleFactor:1,mobile:width!==1440});
    await rootVisit(`#genre/${jazz.id}/map/0`); await title('Jazz');
    await follow(`main .map-shell a[href="#artist/${miles.id}"]`); await title('Miles Davis'); await actionTarget('Search connections');
    const nativeSearch = await follow('main .artist-actions a');
    assert.equal(new URL(nativeSearch).pathname, nativePage.pathname); assert.equal(new URL(nativeSearch).hash,'#browse/Miles%20Davis/0'); await title('Artists');
    assert.ok(await evaluate(`document.querySelector('main .artist-list a[href="#artist/${nativeMiles.id}"]')!==null`));
    await follow(`main .artist-list a[href="#artist/${nativeMiles.id}"]`); await title('Miles Davis'); await actionTarget('Search atlas');
    if (width!==1440) assert.equal(await evaluate("document.querySelector('.map-shell')!==null"),false);
    const atlasSearch = await follow('main .artist-actions a');
    assert.equal(new URL(atlasSearch).pathname,rootPage.pathname); assert.equal(new URL(atlasSearch).hash,'#artists/search/Miles%20Davis/0'); await title('Artists');
    assert.ok(await evaluate(`document.querySelector('main .names a[href="#artist/${miles.id}"]')!==null`));
    assert.equal(await evaluate("[...document.querySelectorAll('main h2')].some(h=>h.textContent==='Connections')"),false);
    await command('Page.reload'); await wait(`${ready}&&document.querySelector('input').value==='Miles Davis'`);
    await evaluate('history.back()'); await title('Miles Davis'); assert.equal(await evaluate('location.pathname'),nativePage.pathname);
    await evaluate('history.forward()'); await wait(`${ready}&&location.hash==='#artists/search/Miles%20Davis/0'`); await title('Artists');
    await screenshot(`cross-catalog-${width}.png`);
  }
  const scopedMembership = [];
  for (const query of ['Can','Yes','Love']) {
    await rootVisit(`#q/${encodeURIComponent(query)}/0`); await title(query);
    const count = await evaluate("(()=>{const h=[...document.querySelectorAll('main h2')].find(h=>h.textContent==='Artists');return Number(h.nextElementSibling.textContent.replace(/[^0-9]/g,''))})()");
    const baseline = [];
    for(let page=0;page<Math.ceil(count/60);page++) {
      await go(`#q/${encodeURIComponent(query)}/${page}`); await title(query);
      baseline.push(...await evaluate(`[...document.querySelectorAll('main .names a[href^="#artist/"]')].map(a=>a.getAttribute('href'))`));
    }
    const scoped = [];
    for(let page=0;page<Math.ceil(count/60);page++) {
      const hash=`#artists/search/${encodeURIComponent(query)}/${page}`; await go(hash); await title('Artists');
      await wait(`${ready}&&document.querySelector('input').value===${JSON.stringify(query)}`);
      scoped.push(...await evaluate("[...document.querySelectorAll('main .names a')].map(a=>a.getAttribute('href'))"));
    }
    assert.deepEqual(scoped,baseline); assert.equal(new Set(scoped).size,count); scopedMembership.push({query,count,pages:Math.ceil(count/60)});
    await command('Page.reload'); await wait(`${ready}&&document.querySelector('input').value===${JSON.stringify(query)}`);
    await rootVisit(`#artist/${name(artists,query+' (band)').id}/list/0`); await title(query+' (band)');await actionTarget('Search connections');
    assert.equal(new URL(await evaluate("document.querySelector('main .artist-actions a').href")).hash,`#browse/${query}/0`);
  }
  const ambiguous = [];
  const nativeNames = new Map(); for (const row of nativeArtists) { const key=row.name.normalize('NFKC').toLocaleLowerCase().trim(); if(!nativeNames.has(key))nativeNames.set(key,[]);nativeNames.get(key).push(row.id); }
  for (const row of artists) { const full=row.name.normalize('NFKC').trim(),base=full.replace(/\s+\([^()]*\)$/u,'');const query=[full,base].find(q=>nativeNames.has(q.toLocaleLowerCase()));if(query&&nativeNames.get(query.toLocaleLowerCase()).length>1){ambiguous.push({row,query,ids:nativeNames.get(query.toLocaleLowerCase())});break;} }
  assert.equal(ambiguous.length,1);
  for (const {row,query,ids} of ambiguous) {
    await rootVisit(`#artist/${row.id}/list/0`);await title(row.name);await actionTarget('Search connections');await follow('main .artist-actions a');await title('Artists');
    const matches=await evaluate("[...document.querySelectorAll('main .artist-list a')].map(a=>a.getAttribute('href').split('/')[1])");assert.ok(ids.every(id=>matches.includes(id)),query);
  }
  const nonLatin = name(nativeArtists, '東京事変');
  const nativeNonLatin = new URL(nativePage);nativeNonLatin.hash=`#artist/${nonLatin.id}/list/0`;
  await command('Page.navigate',{url:nativeNonLatin.href});await title(nonLatin.name);await actionTarget('Search atlas');
  await follow('main .artist-actions a');await title('Artists');assert.equal(await evaluate("document.querySelector('input').value"),nonLatin.name);
  const unicodeMatches=await evaluate("[...document.querySelectorAll('main .names a')].map(a=>a.getAttribute('href'))");
  const expectedUnicode=artists.filter(row=>row.name.includes(nonLatin.name)).map(row=>`#artist/${row.id}`);assert.deepEqual(unicodeMatches,expectedUnicode);
  await evaluate('history.back()');await title(nonLatin.name);assert.equal(await evaluate('location.hash'),nativeNonLatin.hash);
  const noted = nativeArtists.filter(row => typeof row.comment === 'string' && row.comment);
  assert.equal(noted.length,4340);
  const noteCheck = async row => {
    await wait(`${ready}&&location.pathname===${JSON.stringify(nativePage.pathname)}&&document.querySelector('main .artist-note')?.textContent===${JSON.stringify(row.comment)}`);
    await title(row.name);
    assert.equal(await evaluate("document.querySelector('main .artist-note')?.textContent"),row.comment);
    assert.ok(await evaluate(`!!document.querySelector('main a[href="https://musicbrainz.org/artist/${row.id}"]')`));
    assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
  };
  for (const query of ['Alice Cooper','Felt']) {
    const candidates=nativeArtists.filter(row=>row.name===query);assert.equal(candidates.length,2);assert.equal(new Set(candidates.map(row=>row.comment)).size,2);
    for (const row of candidates) {
      await rootVisit(`#q/${encodeURIComponent(query)}/0`);await title(query);
      const selector=`main .names a[href$="#artist/${row.id}"]`;
      const caption=await evaluate(`(()=>{const a=document.querySelector(${JSON.stringify(selector)}),n=a?.closest('li').querySelector('.identity-note');return{note:n?.textContent,name:a?.textContent,described:!!n&&a.getAttribute('aria-describedby')===n.id}})()`);
      assert.deepEqual(caption,{note:row.comment,name:row.name,described:true});
      assert.equal(await evaluate(`[...document.querySelectorAll('main .names a[href^="#artist/"]')].some(a=>a.closest('li').querySelector('.identity-note'))`),false);
      await follow(selector);await noteCheck(row);await actionTarget('Search atlas');
      await command('Page.reload');await noteCheck(row);
      await evaluate('history.back()');await wait(`${ready}&&location.pathname===${JSON.stringify(rootPage.pathname)}&&document.querySelector('[data-view=genres]')`);await title(query);assert.equal(await evaluate('location.pathname'),rootPage.pathname);
      await evaluate('history.forward()');await noteCheck(row);
    }
  }
  const alice=nativeArtists.find(row=>row.name==='Alice Cooper'&&row.comment.includes('the band'));
  const felt=nativeArtists.find(row=>row.name==='Felt'&&row.comment.includes('hip hop'));
  const noNote=nativeArtists.find(row=>row.name==='John Williams'&&!row.comment);assert.ok(noNote);
  const longestNote=noted.reduce((a,b)=>a.comment.length>b.comment.length?a:b);
  for (const width of [390,320]) {
    await command('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:true});
    for(const row of [alice,felt,longestNote]) {
      assert.ok(row);const target=new URL(nativePage);target.hash=`#artist/${row.id}/list/0`;
      await command('Page.navigate',{url:target.href});await noteCheck(row);await actionTarget('Search atlas');
      assert.ok(await evaluate("parseFloat(getComputedStyle(document.querySelector('.artist-note')).fontSize)")>=16);
    }
    await screenshot(`identity-notes-${width}.png`);
  }
  const missingTarget=new URL(nativePage);missingTarget.hash=`#artist/${noNote.id}/list/0`;
  await command('Page.navigate',{url:missingTarget.href});await title(noNote.name);assert.equal(await evaluate("document.querySelector('main .artist-note')"),null);
  await rootVisit('#q/John%20Williams/0');await title('John Williams');
  const rootTargets=await evaluate("[...document.querySelectorAll('main .names a')].map(a=>{const r=a.getBoundingClientRect();return{width:r.width,height:r.height}})");
  assert.ok(rootTargets.length>0);assert.ok(rootTargets.every(r=>r.width>=43.99&&r.height>=43.99));
  const wikiAlice=artists.find(row=>row.name==='Alice Cooper (band)');assert.ok(wikiAlice);
  await rootVisit(`#artist/${wikiAlice.id}/list/0`);await title(wikiAlice.name);
  assert.equal(await evaluate("document.querySelector('main .artist-note')"),null);
  let literalSourceNote = 'source notes checked in complete offline data';
  if(new URL(url).protocol!=='file:') {
    const target=new URL(nativePage);target.hash=`#artist/${alice.id}/list/0`;
    await command('Page.navigate',{url:target.href});await noteCheck(alice);
    const literal='<img src="local-note-image" onerror="window.noteRan=true"> µ';
    const script=await command('Page.addScriptToEvaluateOnNewDocument',{source:`window.noteFixtureInstalled=true;const noteFetch=window.fetch;window.fetch=async(...args)=>{const response=await noteFetch(...args);if(new URL(args[0],location.href).pathname.endsWith('/artist-network/catalog.json')){const data=await response.json();data.artists.find(row=>row.id===${JSON.stringify(alice.id)}).comment=${JSON.stringify(literal)};return new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});}return response;};`});
    try {
      await command('Page.reload');await wait("window.noteFixtureInstalled===true");await title(alice.name);
      assert.equal(await evaluate("document.querySelector('main .artist-note').textContent"),literal);
      assert.equal(await evaluate("document.querySelectorAll('main .artist-note img').length"),0);
      assert.equal(await evaluate('!!window.noteRan'),false);literalSourceNote=true;
    } finally {await command('Page.removeScriptToEvaluateOnNewDocument',{identifier:script.identifier});}
  }
  // A simulated local optional-catalog failure must leave the atlas entity usable.
  let optionalFailure = 'offline bundle does not fetch optional catalogs';
  if (new URL(url).protocol !== 'file:') {
    const script = await command('Page.addScriptToEvaluateOnNewDocument',{source:"const originalFetch=window.fetch;window.fetch=(...args)=>new URL(args[0],location.href).pathname.endsWith('/artist-network/catalog.json')?Promise.resolve(new Response('',{status:404})):originalFetch(...args);"});
    try {
      await rootVisit(wikiHash);await title('Miles Davis');assert.equal(await evaluate("document.querySelector('main .artist-actions')"),null);assert.ok(await evaluate(`document.querySelectorAll('main .names a[href^="#genre/"]').length>0`)); optionalFailure=true;
    } finally { await command('Page.removeScriptToEvaluateOnNewDocument',{identifier:script.identifier}); }
    const held = await command('Page.addScriptToEvaluateOnNewDocument',{source:"const originalFetch=window.fetch,releases=[];window.releaseOptionalCatalog=()=>releases.splice(0).forEach(f=>f());window.fetch=(...args)=>new URL(args[0],location.href).pathname.endsWith('/artist-network/catalog.json')?new Promise(resolve=>releases.push(()=>resolve(originalFetch(...args)))):originalFetch(...args);"});
    try {
      await command('Page.reload');await wait("typeof window.releaseOptionalCatalog==='function'");await title('Miles Davis');assert.equal(await evaluate("document.querySelector('main .artist-actions')"),null);assert.ok(await evaluate(`document.querySelectorAll('main .names a[href^="#genre/"]').length>0`));
      await go(`#artist/${fourTet.id}/list/0`);await title('Four Tet');assert.equal(await evaluate("document.querySelector('main .artist-actions')"),null);
      await evaluate('window.releaseOptionalCatalog()');await actionTarget('Search connections');
      assert.equal(new URL(await evaluate("document.querySelector('main .artist-actions a').href")).hash,'#browse/Four%20Tet/0');
      assert.equal(await evaluate("document.querySelectorAll('main .artist-actions').length"),1);optionalFailure={immediate_failure:true,held_response_facts_visible:true,late_response_follows_current_artist:true};
    } finally { await command('Page.removeScriptToEvaluateOnNewDocument',{identifier:held.identifier}); }
  }
  await rootVisit('#artists/search/zzzzzzzzzzzzzzzzzz/0');await title('Artists');assert.ok(await evaluate("document.querySelector('main').textContent.includes('No matches.')"));
  await rootVisit('#artists/search//0');await title('Artists');assert.ok(await evaluate("document.querySelector('main').textContent.includes('Enter an artist.')"));
  await rootVisit('#');await title('Genres');
  const external=requests.filter(r=>!['data:','blob:'].includes(new URL(r.url).protocol)&&new URL(r.url).origin!==new URL(url).origin);assert.deepEqual(external,[]);assert.deepEqual(requests.filter(r=>r.type==='Media'),[]);assert.deepEqual(errors,[]);
  if(new URL(url).protocol==='file:')assert.equal(requests.filter(r=>/^https?:/.test(r.url)).length,0);
  const report={status:'passed',url,counts:receipt.counts,all_genres_reachable:true,root_map:rootMap,complete_paginated_directory:true,complete_genre_members:true,isolated_artist_metadata_suggestions:true,metadata_source_disclosure:true,keyboard_search:true,nonLatin_and_long_name_search:true,landing_search_both_catalogs:true,exact_and_qualified_search_priority:true,desktop_maps_nonoverlapping:true,mobile_default_list:true,mobile_touch:true,mobile_map_readable_44px:true,zoom:true,history_reload:true,empty_state:true,external_requests:0,runtime_errors:errors,screenshots:screenshotCount,publication:false,cross_catalog_name_search_navigation:true,automatic_identity_joins:0,scoped_search_membership:scopedMembership,ambiguous_native_candidates_preserved:true,optional_native_failure:optionalFailure,source_note_artists:noted.length,ambiguous_native_notes:true,notes_do_not_transfer_to_atlas_IDs:true,missing_note_abstention:true,root_list_targets44px:true,literal_note_text:literalSourceNote};await writeFile(join(output,'browser-report.json'),JSON.stringify(report,null,2)+'\n');process.stdout.write(JSON.stringify(report)+'\n');
}catch(error){try{await screenshot('failure.png');if(evaluate)await writeFile(join(output,'dom-state.json'),JSON.stringify(await evaluate("({hash:location.hash,main:document.querySelector('main')?.innerHTML.slice(0,3000)})"),null,2));}catch{}await writeFile(join(output,'browser-failure.json'),JSON.stringify({error:String(error),errors,requests},null,2)+'\n');throw error;}finally{socket?.close();browser.kill('SIGKILL');await new Promise(resolve_=>browser.exitCode!==null||browser.signalCode!==null?resolve_():browser.once('close',resolve_));await rm(profile,{recursive:true,force:true});}
