import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';

// Point the three OPENNOISE_*_STATIC_ROOT variables below at actual fresh exports.
// Profiles use TMPDIR; no source export files are modified by the browser.
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
async function browser(root, operation) {
  const exportRoot = resolve(root);
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(exportRoot, '.' + (path === '/' ? '/index.html' : path));
    if (!file.startsWith(exportRoot + sep)) { response.statusCode = 403; response.end(); return; }
    try { response.setHeader('Content-Type', (/\.m?js$/.test(file)) ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : 'application/json'); response.end(await readFile(file)); }
    catch { response.statusCode = 404; response.end(); }
  });
  const profile = await mkdtemp(join(tmpdir(), 'opennoise-skip-contract-'));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}/`;
  const child = spawn(chromium, ['--headless=new', '--single-process', '--no-zygote', '--renderer-process-limit=1', '--disable-extensions', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-background-networking', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank']);
  let socket, diagnostics='';child.stderr.on('data',bytes=>{diagnostics=(diagnostics+bytes).slice(-5000);});
  const requests = [], errors = [];
  try {
    const endpoint = await new Promise((resolve, reject) => {
      let output = ''; const timeout = setTimeout(() => reject(new Error('Chromium startup timed out')), 10000);
      child.on('error', reject); child.stderr.on('data', bytes => { output += bytes; const match = output.match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\//); if (match) { clearTimeout(timeout); resolve(`http://127.0.0.1:${match[1]}`); } });
    });
    const target = await fetch(`${endpoint}/json/new?about:blank`, {method: 'PUT'}).then(response => response.json());
    socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, {once: true}); socket.addEventListener('error', reject, {once: true}); });
    let sequence = 0; const pending = new Map();
    socket.addEventListener('message', ({data}) => { const result = JSON.parse(data); if (result.method === 'Network.requestWillBeSent') requests.push(result.params); if (result.method === 'Runtime.exceptionThrown') errors.push(result.params.exceptionDetails); pending.get(result.id)?.(result); });
    const command = (method, params = {}) => new Promise((resolve, reject) => { const id = ++sequence, timeout = setTimeout(() => reject(new Error(`${method} timed out`)), 10000); pending.set(id, result => { clearTimeout(timeout); pending.delete(id); result.error ? reject(new Error(JSON.stringify(result.error))) : resolve(result.result); }); socket.send(JSON.stringify({id, method, params})); });
    const evaluate = async expression => { const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true}).catch(error=>{throw new Error(error.message+'; expression='+expression);}); if (result.exceptionDetails) throw new Error(result.exceptionDetails.text+'; expression='+expression); return result.result.value; };
    const wait = async expression => { for (let index = 0; index < 400; index++) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 20)); } throw new Error('Timed out: ' + expression); };
    await command('Network.enable'); await command('Runtime.enable'); await command('Emulation.setDeviceMetricsOverride', {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false}); const navigation=await command('Page.navigate', {url});assert.equal(navigation.errorText,undefined,JSON.stringify(navigation));
    await operation({evaluate, wait, command, requests, url});
    assert.deepEqual(errors, []); assert.ok(requests.every(row => new URL(row.request.url).origin === new URL(url).origin && row.type !== 'Media'), 'no external provider or audio requests');
  } catch(error) {throw new Error(`${error.message}; Chromium exit=${child.exitCode} signal=${child.signalCode}; ${diagnostics}`,{cause:error});} finally {
    socket?.close(); child.kill('SIGKILL'); await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('close', resolve)); await rm(profile, {recursive: true, force: true}); await new Promise(resolve => server.close(resolve));
  }
}


const root=process.env.OPENNOISE_FULL_FOUNDATION_STATIC_ROOT;
const report=process.env.OPENNOISE_FULL_FOUNDATION_BROWSER_REPORT;
test('full-input identity and genre access, bounded search, history, listening list and keyboard', {skip:!root||!chromium,timeout:120000},async()=>{
  const profile=JSON.parse(await readFile(join(root,'profile.json')));
  const genres=JSON.parse(await readFile(join(root,'genres.json')));
  const featured=profile.featured_artists;
  assert.ok(profile.counts.artists>=2999670);
  const aphex=featured.find(row=>row.name==='Aphex Twin'),four=featured.find(row=>row.name==='Four Tet');
  assert.ok(aphex&&four,'both required artists retained');
  const compactBounds=JSON.parse(await readFile(join(root,'search/index.json')));
  const unicodeCohort=[];
  const unicodeCompare=(a,b)=>{const x=[...a],y=[...b];for(let i=0;i<Math.min(x.length,y.length);i++){const delta=x[i].codePointAt(0)-y[i].codePointAt(0);if(delta)return delta;}return x.length-y.length;};
  for(const [kind,lower,upper,predicate] of [['single-character','x','x',value=>value==='x'],['Japanese','\u3040','\u30ff\u{10ffff}',value=>{const code=value.codePointAt(0);return code>=0x3040&&code<=0x30ff;}],['astral','\u{10000}','\u{10ffff}',value=>value.codePointAt(0)>0xffff]]){
    for(let page=0;page<compactBounds.pages.length;page++){const bounds=compactBounds.pages[page];if(unicodeCompare(bounds[1],lower)<0||unicodeCompare(bounds[0],upper)>0)continue;const path=`browse/${String(page).padStart(6,'0')}.json`;const rows=JSON.parse(await readFile(join(root,path)));const row=rows.find(row=>predicate(row[1].normalize('NFKC').toLowerCase()));if(row){unicodeCohort.push({kind,id:row[0],name:row[1],path});break;}}
  }
  assert.equal(unicodeCohort.length,3,'all Unicode cohorts selected from actual native source rows');
  const genre=genres.find(row=>row.artist_mbids?.length>0||row.artist_count>0);
  assert.equal(genres.length,1018);assert.ok((await readFile(join(root,'genres.json'))).length<120000,'homepage genre index excludes full artist UUID cohorts');
  const overlap=JSON.parse(await readFile(join(root,`details/${aphex.artist_mbid}.json`)));assert.ok(overlap.direct_genres.length>=2);
  const firstGenre=overlap.direct_genres[0],secondGenre=overlap.direct_genres[1],overlapCohort=JSON.parse(await readFile(join(root,`genres/${firstGenre}.json`)));const overlapIndex=overlapCohort.findIndex(row=>row[0]===aphex.artist_mbid);assert.ok(overlapIndex>=0);
  let bridge;for(let key=0;key<256&&!bridge;key++){const shard=JSON.parse(await readFile(join(root,profile.research_contexts.path,key.toString(16).padStart(2,'0')+'.json')));bridge=Object.entries(shard).find(([,context])=>context.fma_descriptor_context?.length);}
  assert.ok(bridge,'exact native MBID/FMA descriptor context exists');
  let browserEvidence,initialRequests;const screenshots=[],allRequests=[];
  const ready="document.querySelector('main').getAttribute('aria-busy')==='false'";
  const flow=operation=>browser(root,async context=>{await context.wait(ready);await operation(context);allRequests.push(...context.requests);});
  await flow(async({evaluate,wait,command,requests,url})=>{
    await wait(ready);
    assert.match(await evaluate("document.querySelector('main').textContent"),/2,999,670/);
    initialRequests=requests.length;
    assert.ok(initialRequests<12,'initial payload uses only small directory and static assets');
    for(const artist of [aphex,four]){
      await evaluate(`location.hash=${JSON.stringify('#q/'+encodeURIComponent(artist.name))}`);
      await wait(ready+" && document.querySelector('main h1').textContent.startsWith('Search:')");
      assert.equal(await evaluate(`[...document.querySelectorAll('.artist-list a')].some(a=>a.textContent===${JSON.stringify(artist.name)} && a.hash===${JSON.stringify('#artist/'+artist.artist_mbid)})`),true);
      await evaluate(`document.querySelector('a[href="#artist/${artist.artist_mbid}"]').click()`);
      await wait(ready+` && document.querySelector('main h1').textContent===${JSON.stringify(artist.name)}`);
      assert.ok(await evaluate("document.querySelectorAll('.credits li').length>0"));
      if(artist===aphex)assert.ok(await evaluate("[...document.querySelectorAll('.credits a')].some(a=>a.textContent.includes('availability unverified'))"),'literal recording destinations are distinguished from verified playback');
      await evaluate("document.querySelector('.credits button').click()");
      await evaluate("history.back()");
      await wait(ready+" && document.querySelector('main h1').textContent.startsWith('Search:')");
      await evaluate('history.forward()');await wait(ready+` && document.querySelector('main h1').textContent===${JSON.stringify(artist.name)}`);
      await command('Page.reload');await wait(ready+` && document.querySelector('main h1').textContent===${JSON.stringify(artist.name)}`);
    }
    assert.ok(await evaluate("JSON.parse(localStorage.getItem('opennoise-listening-list-v1')).length>=2"));
  });
  await flow(async({evaluate,wait,command,requests})=>{
    for(const native of unicodeCohort){await evaluate(`location.hash=${JSON.stringify('#q/'+encodeURIComponent(native.name))}`);await wait(ready+" && document.querySelector('main h1').textContent.startsWith('Search:')");assert.equal(await evaluate(`[...document.querySelectorAll('.artist-list a')].some(a=>a.hash===${JSON.stringify('#artist/'+native.id)})`),true,`native ${native.kind} name remains searchable by exact identity`);}

    await evaluate(`location.hash=${JSON.stringify('#q/'+aphex.artist_mbid)}`);await wait(ready+" && document.querySelector('main h1').textContent==='Aphex Twin'");
    const searchIndex=await readFile(join(root,'search/index.json'));assert.ok(searchIndex.length<1500000,'prefix search uses only compact global page bounds, not the multi-million-name directory');
  });
  await flow(async({evaluate,wait,command,requests})=>{
    await evaluate(`location.hash=${JSON.stringify('#genre/'+genre.genre_id)}`);await wait(ready+` && document.querySelector('main h1').textContent===${JSON.stringify(genre.name)}`);
    assert.equal(await evaluate("document.querySelectorAll('.artist-list li').length"),Math.min(500,genre.artist_mbids?.length??genre.artist_count));
    await evaluate(`location.hash=${JSON.stringify('#genre/'+firstGenre+'|'+Math.floor(overlapIndex/500))}`);await wait(ready+` && document.querySelector('a[href=\"#artist/${aphex.artist_mbid}\"]')!==null`);await evaluate(`document.querySelector('a[href=\"#artist/${aphex.artist_mbid}\"]').click()`);await wait(ready+" && document.querySelector('main h1').textContent==='Aphex Twin'");assert.equal(await evaluate("document.querySelector('.genre-grid').children.length"),overlap.direct_genres.length);await evaluate(`document.querySelector('a[href=\"#genre/${secondGenre}\"]').click()`);await wait(ready+` && location.hash===${JSON.stringify('#genre/'+secondGenre)}`);assert.ok(await evaluate("document.querySelector('main').textContent.includes('Overlapping direct claims are retained')"));
  });
  await flow(async({evaluate,wait,command,requests})=>{
    await evaluate(`location.hash=${JSON.stringify('#artist/'+bridge[0])}`);await wait(ready+" && [...document.querySelectorAll('summary')].some(row=>row.textContent==='FMA sonic context')");assert.ok(await evaluate("document.querySelector('main').textContent.includes('not musical axes or artist genre memberships')"));assert.ok(await evaluate(`document.querySelector('main').textContent.includes(${JSON.stringify('FMA artist '+bridge[1].fma_descriptor_context[0].fma_artist_id+':')})`));
    if(profile.source_completion){const modelID=profile.source_completion.example_artist_mbid;const contexts=JSON.parse(await readFile(join(root,profile.research_contexts.path,modelID.slice(0,2)+'.json')));const supplemental=contexts[modelID];assert.ok(supplemental.source_completion_proposals.length);assert.ok(supplemental.source_completion_proposals.every(row=>row.proposal_probability===null&&row.musical_membership_probability===null));await evaluate(`location.hash=${JSON.stringify('#artist/'+modelID)}`);await wait(ready+" && [...document.querySelectorAll('main h2')].some(row=>row.textContent==='Suggested from observed labels')");assert.ok(await evaluate("document.querySelector('main').textContent.includes('Musical fit is unreviewed')"));assert.equal(await evaluate("[...document.querySelectorAll('h2')].find(row=>row.textContent==='Suggested from observed labels').nextElementSibling.nextElementSibling.children.length"),supplemental.source_completion_proposals.length);const suggested=supplemental.source_completion_proposals[0].genre_qid;assert.ok(await evaluate(`document.querySelector('main a[href="#genre/${suggested}"]')!==null`));}
  });
  await flow(async({evaluate,wait,command,requests})=>{
    await evaluate("location.hash='#artists/0'");await wait(ready+" && document.querySelector('main h1').textContent==='All artists'");
    assert.equal(await evaluate("document.querySelectorAll('.artist-list li').length"),500);
    await evaluate("[...document.querySelectorAll('.pagination a')].find(a=>a.textContent==='Next').click()");await wait(ready+" && location.hash==='#artists/1'");
    assert.equal(await evaluate("document.querySelectorAll('.artist-list li').length"),500);
    const outside=await evaluate("document.querySelector('.artist-list a').getAttribute('href')");
    await evaluate("document.querySelector('.artist-list a').click()");await wait(ready+` && location.hash===${JSON.stringify(outside)}`);
    assert.ok(await evaluate("document.querySelector('main').textContent.includes('Observed genres')"));
    const outsideID=outside.split('/').at(-1);if(!existsSync(join(root,`details/${outsideID}.json`))){assert.ok(await evaluate("document.querySelector('main').textContent.includes('No direct genre evidence is available')"));assert.equal(await evaluate("document.querySelector('.genre-grid')===null"),true);assert.equal(await evaluate("[...document.querySelectorAll('h2')].some(row=>row.textContent==='Suggested from observed labels')"),false);}

    for(const width of [1280,390]){
      await command('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:width===390});
      const before=await evaluate("({hash:location.hash,history:history.length,html:document.querySelector('main').innerHTML})");
      await evaluate("document.querySelector('.skip').focus()");
      await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});
      await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
      assert.equal(await evaluate("document.activeElement===document.querySelector('main')"),true);
      assert.deepEqual(await evaluate("({hash:location.hash,history:history.length,html:document.querySelector('main').innerHTML})"),before);
      assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
      if(report){const capture=await command('Page.captureScreenshot',{format:'png'});const bytes=Buffer.from(capture.data,'base64');const path=report+`-${width}.png`;await writeFile(path,bytes);screenshots.push({path,sha256:createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length,width});}
      await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
      await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
      assert.equal(await evaluate("document.querySelector('main').contains(document.activeElement)"),true);
    }
    if(report){for(const [view,hash] of [['genres',''],['artist','#artist/'+aphex.artist_mbid]])for(const width of [1280,390]){await command('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:width===390});await evaluate(`location.hash=${JSON.stringify(hash)}`);await wait(ready+` && location.hash===${JSON.stringify(hash)}`);await evaluate('document.activeElement.blur()');const capture=await command('Page.captureScreenshot',{format:'png'});const bytes=Buffer.from(capture.data,'base64'),path=report+`-${view}-${width}.png`;await writeFile(path,bytes);screenshots.push({path,sha256:createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length,width,view});}}
    assert.equal(await evaluate("document.querySelectorAll('audio,video,iframe').length"),0);
    if(report){const hash=bytes=>createHash('sha256').update(bytes).digest('hex');const files={};for(const path of ['profile.json','genres.json','receipt.json','index.html','full-foundation.mjs','full-foundation.css','full-foundation-normalization.mjs','listening-list.mjs'])files[path]=hash(await readFile(join(root,path)));browserEvidence={revision:'opennoise-full-foundation-browser-v1',export_root:root,files,checks:{required_artists:true,complete_genre_cohort:true,identity_browse_pagination:true,outside_featured_identity:true,prefix_search:true,history_reload:true,listening_list:true,keyboard_skiplink:true,mobile_no_overflow:true,no_external_audio_requests:true,provider_links_label_unverified:true},overlapping_direct_genre_navigation:{artist_mbid:aphex.artist_mbid,genres:[firstGenre,secondGenre]},exact_fma_context:{artist_mbid:bridge[0],fma_artist_ids:bridge[1].fma_descriptor_context.map(row=>row.fma_artist_id),recording_equivalence_claim:false},unicode_cohort:unicodeCohort,screenshots,initial_requests:initialRequests,requests:requests.map(row=>new URL(row.request.url).pathname) };}
  });
  // A report is sealed only after all runtime and request-scope checks pass.
  if(report){browserEvidence.requests=allRequests.map(row=>new URL(row.request.url).pathname);browserEvidence.chromium_sessions=5;await writeFile(report,JSON.stringify(browserEvidence,null,2)+'\n');}
});
