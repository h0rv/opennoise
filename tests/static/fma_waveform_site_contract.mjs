import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';

// All records and media operations here are synthetic. This does not decode or assess real audio.
const chromium=process.env.CHROMIUM_PATH??['/usr/bin/chromium','/usr/bin/chromium-browser'].find(existsSync);
const page=await readFile(new URL('../../src/opennoise/static/fma-waveform-site.html',import.meta.url),'utf8');
const track=(id,artist,genres,title)=>({track_id:id,artist_id:artist,title,artist_name:artist===11?'Fixture One':'Fixture Two',genre_ids:genres,audio_path:`audio/${id}.mp3`,license_url:'https://creativecommons.org/licenses/by/4.0/',source_url:'',attribution:`Synthetic fixture ${id}; not FMA audio`,composer:'Supplied fixture composer',copyright_c:'',copyright_p:'',embedded_source_urls:['https://freemusicarchive.org/music/fixture'],embedded_curators:['Fixture curator'],embedded_notices:{copyright:'Fixture notice'},embedded_extra_text_present:false});
const fixture={revision:'fma-declared-license-candidate-v1',public_deployment_authorized:false,genres:[{genre_id:1,title:'Drone & Noise'},{genre_id:2,title:'Quiet'}],tracks:[track(101,11,[1],'A&B / #'),track(102,12,[1,2],'Second'),track(103,11,[2],'Third')]};

const layout={revision:'fma-permitted55-waveform-layout-v1',axes:['PC1','PC2'],musical_quality_validated:false,tracks:[{track_id:101,position:[0,0],neighbors:[102],component_id:1,fold:2,neighbor_reason:null,projection_reason:null},{track_id:102,position:[1,2],neighbors:[],component_id:2,fold:0,neighbor_reason:null,projection_reason:null},{track_id:103,position:null,neighbors:[],component_id:1,fold:1,neighbor_reason:'zero_norm',projection_reason:'projection_degenerate'}],genres:[1,2].map(genre_id=>({genre_id,training_track_count:1,training_component_count:1,eligible_training_track_count:1,eligible_training_component_count:1,position:null,reason:'insufficient_training_components'}))};

async function browser(operation,initialFailure=false,layoutFixture=layout,candidateFixture=fixture){
 const root=await mkdtemp(join(tmpdir(),'candidate-discovery-test-'));let child,socket;let fail=initialFailure;const requests=[],errors=[];
 const server=createServer((request,response)=>{requests.push(request.url);if(request.url.startsWith('/candidate/manifest.json')){response.writeHead(fail?503:200,{'content-type':'application/json'});response.end(JSON.stringify(candidateFixture));}else if(request.url.startsWith('/model/layout.json')){response.writeHead(200,{'content-type':'application/json'});response.end(JSON.stringify(layoutFixture));}else if(request.url.startsWith('/candidate/audio/')){response.writeHead(500);response.end('Synthetic contract forbids media fetch');}else{response.writeHead(200,{'content-type':'text/html'});response.end(page);}});
 try{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin=`http://127.0.0.1:${server.address().port}`;
  child=spawn(chromium,['--headless=new','--no-first-run','--no-default-browser-check','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-background-networking','--remote-debugging-port=0',`--user-data-dir=${root}`,'about:blank']);
  const endpoint=await new Promise((resolve,reject)=>{let output='';const timer=setTimeout(()=>reject(Error('Chromium startup exceeded30s')),30000);child.once('error',reject);child.stderr.on('data',bytes=>{output+=bytes;const match=/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\//.exec(output);if(match){clearTimeout(timer);resolve(`http://127.0.0.1:${match[1]}`);}});});
  const target=await fetch(`${endpoint}/json/new?about:blank`,{method:'PUT'}).then(r=>r.json());socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise(resolve=>socket.addEventListener('open',resolve,{once:true}));let next=0;const pending=new Map();
  socket.addEventListener('message',({data})=>{const message=JSON.parse(data);if(message.method==='Runtime.exceptionThrown')errors.push(message.params);pending.get(message.id)?.(message);});
  const command=(method,params={})=>new Promise((resolve,reject)=>{const id=++next,timer=setTimeout(()=>reject(Error(`${method} timeout`)),10000);pending.set(id,message=>{clearTimeout(timer);pending.delete(id);message.error?reject(Error(JSON.stringify(message.error))):resolve(message.result);});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const result=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,userGesture:true});if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));return result.result?.value;};
  const wait=async expression=>{for(let i=0;i<250;i++){if(await evaluate(expression))return;await new Promise(resolve=>setTimeout(resolve,20));}throw Error('Readiness failed: '+expression);};
  await command('Runtime.enable');await command('Page.enable');
  await command('Page.addScriptToEvaluateOnNewDocument',{source:`window.__media={plays:[],pauses:0};HTMLMediaElement.prototype.play=function(){window.__media.plays.push(this.getAttribute('src'));this.dataset.stubPlaying='true';if(window.__rejectNext){window.__rejectNext=false;return Promise.reject(Error('synthetic failure'));}return Promise.resolve();};HTMLMediaElement.prototype.pause=function(){window.__media.pauses++;this.dataset.stubPlaying='false';};HTMLMediaElement.prototype.load=function(){};`});
  await command('Page.navigate',{url:origin});
  await operation({evaluate,wait,command,origin,requests,setFailure:value=>{fail=value;}});
  assert.deepEqual(errors,[]);assert.equal(requests.some(url=>url.startsWith('/candidate/audio/')),false,'stubbed test performs no audio requests');
 }finally{socket?.close();if(child){child.kill('SIGKILL');await new Promise(resolve=>child.exitCode!==null||child.signalCode!==null?resolve():child.once('close',resolve));}if(server.listening)await new Promise(resolve=>server.close(resolve));await rm(root,{recursive:true,force:true});}
}

test('synthetic waveform map and inferred suggestions preserve navigation, credits and unplaced access',{skip:!chromium,timeout:60000},async()=>{
 await browser(async({evaluate,wait,command})=>{
  await wait("document.documentElement?.dataset.candidateReady==='true'");
  await evaluate("location.hash='#track/101'");await wait("document.querySelector('#suggestions [data-play-track]')");
  assert.equal(await evaluate("document.querySelector('#suggestions [data-play-track]').dataset.playTrack"),'102');
  assert.equal(await evaluate("document.querySelector('section[aria-label=Suggested]').textContent.includes('Inferred')"),true);
  await evaluate("document.querySelector('#main [data-play-track=\"101\"]').click();window.__player=document.querySelector('audio');window.__credit=document.querySelector('#credit').textContent;location.hash='#map'");
  await wait("document.querySelectorAll('[data-map-track]').length===2");
  assert.equal(await evaluate("document.querySelector('#results [data-track-id=\"103\"]')!==null"),true);
  assert.equal(await evaluate("window.__player===document.querySelector('audio')&&window.__credit===document.querySelector('#credit').textContent"),true);
  assert.deepEqual(await evaluate('window.__media.plays'),['candidate/audio/101.mp3']);
  await evaluate("document.querySelector('[data-map-track=\"102\"]').dispatchEvent(new MouseEvent('click',{bubbles:true}));location.hash='#track/102'");
  await wait("document.querySelector('#main').dataset.route==='#track/102'");
  await evaluate("location.hash='#track/103'");await wait("document.querySelector('#main').dataset.route==='#track/103'");
  assert.equal(await evaluate("document.querySelector('section[aria-label=Suggested]').textContent.includes('No supported')"),true);
  await evaluate('history.back()');await wait("document.querySelector('#main').dataset.route==='#track/102'");
  assert.deepEqual(await evaluate('window.__media.plays'),['candidate/audio/101.mp3']);
  await evaluate('window.__reload=true');await command('Page.reload');await wait("!window.__reload&&document.documentElement?.dataset.candidateReady==='true'");assert.deepEqual(await evaluate('window.__media.plays'),[]);
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await evaluate("location.hash='#map'");await wait("document.querySelector('svg')");assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
 });
});

test('synthetic malformed layout cannot disable reviewed list or player',{skip:!chromium,timeout:60000},async()=>{
 const invalid=structuredClone(layout);invalid.tracks[0].neighbors=[103];
 await browser(async({evaluate,wait})=>{
  await wait("document.documentElement?.dataset.candidateReady==='true'");
  await evaluate("location.hash='#map'");await wait("document.querySelector('#main').textContent.includes('map is unavailable')");
  await evaluate("location.hash='#track/103'");await wait("document.querySelector('#main').dataset.route==='#track/103'");
  assert.equal(await evaluate("document.querySelector('#main').textContent.includes('Suggestions are unavailable')"),true);
  await evaluate("document.querySelector('#main [data-play-track]').click()");
  assert.deepEqual(await evaluate('window.__media.plays'),['candidate/audio/103.mp3']);
  await evaluate("location.hash='#tracks'");await wait("document.querySelectorAll('#results [data-track-id]').length===3");
 },false,invalid);
});

test('synthetic supported genre centroid links preserve native source identity',{skip:!chromium,timeout:60000},async()=>{
 const candidate=structuredClone(fixture);candidate.genres=candidate.genres.slice(0,1);candidate.tracks.forEach(r=>r.genre_ids=[1]);
 const mapped=structuredClone(layout);mapped.tracks.forEach((r,i)=>Object.assign(r,{fold:0,component_id:i+1,position:[i,i],neighbors:[],neighbor_reason:null,projection_reason:null}));
 mapped.genres=[{genre_id:1,training_track_count:3,training_component_count:3,eligible_training_track_count:3,eligible_training_component_count:3,position:[1,1],reason:null}];
 await browser(async({evaluate,wait})=>{
  await wait("document.documentElement?.dataset.candidateReady==='true'");await evaluate("location.hash='#map'");await wait("document.querySelector('[data-map-genre]')");
  assert.equal(await evaluate("document.querySelector('[data-map-genre]').textContent"),'Drone & Noise');
  assert.equal(await evaluate("document.querySelector('[data-map-genre]').getAttribute('href')"),'#genre/1');
  await evaluate("document.querySelector('[data-map-genre]').dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}))");await wait("document.querySelector('#main').dataset.route==='#genre/1'");
  assert.equal(await evaluate("document.querySelectorAll('#results [data-track-id]').length"),3);assert.deepEqual(await evaluate('window.__media.plays'),[]);
 },false,mapped,candidate);
});

test('long supplied credits wrap without inflating the mobile viewport',{skip:!chromium,timeout:60000},async()=>{
 const candidate=structuredClone(fixture);
 candidate.tracks[0].attribution='Synthetic supplied credit https://example.com/'+ 'long-credit-'.repeat(30);
 await browser(async({evaluate,wait,command})=>{
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await wait("document.documentElement?.dataset.candidateReady==='true'");
  await evaluate("location.hash='#track/101'");await wait("document.querySelector('#main').dataset.route==='#track/101'");
  await evaluate("document.querySelector('#main [data-play-track]').click()");
  await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  const dimensions=await evaluate('({inner:innerWidth,client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,visual:visualViewport.width,scale:visualViewport.scale})');
  assert.equal(dimensions.inner,390);assert.equal(dimensions.client,390);assert.equal(dimensions.scroll,390);
  assert.ok(Math.abs(dimensions.visual-390)<1);assert.ok(Math.abs(dimensions.scale-1)<0.01);
  assert.equal(await evaluate("document.querySelector('#credit small').textContent"),candidate.tracks[0].attribution);
 },false,layout,candidate);
});
