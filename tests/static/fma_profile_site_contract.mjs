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
const page=await readFile(new URL('../../src/opennoise/static/fma-profile-site.html',import.meta.url),'utf8');
const track=(id,artist,genres,title)=>({track_id:id,artist_id:artist,title,artist_name:artist===11?'Fixture One':'Fixture Two',genre_ids:genres,audio_path:`audio/${id}.mp3`,license_url:'https://creativecommons.org/licenses/by/4.0/',source_url:'',attribution:`Synthetic fixture ${id}; not FMA audio`,composer:'Supplied fixture composer',copyright_c:'',copyright_p:'',embedded_source_urls:['https://freemusicarchive.org/music/fixture'],embedded_curators:['Fixture curator'],embedded_notices:{copyright:'Fixture notice'},embedded_extra_text_present:false});
const fixture={revision:'fma-declared-license-candidate-v1',public_deployment_authorized:false,genres:[{genre_id:1,title:'Drone & Noise'},{genre_id:2,title:'Quiet'}],tracks:[track(101,11,[1],'A&B / #'),track(102,12,[1,2],'Second'),track(103,11,[2],'Third')]};

const layout={revision:'fma-permitted55-waveform-layout-v1',axes:['PC1','PC2'],musical_quality_validated:false,tracks:[{track_id:101,position:[0,0],neighbors:[102],component_id:1,fold:2,neighbor_reason:null,projection_reason:null},{track_id:102,position:[1,2],neighbors:[],component_id:2,fold:0,neighbor_reason:null,projection_reason:null},{track_id:103,position:[2,1],neighbors:[],component_id:1,fold:2,neighbor_reason:null,projection_reason:null}],genres:[1,2].map(genre_id=>({genre_id,training_track_count:1,training_component_count:1,eligible_training_track_count:1,eligible_training_component_count:1,position:null,reason:'insufficient_training_components'}))};

const discovery={revision:'fma55-recording-profile-discovery-v1',claims:{musical_quality_validated:false,new_fit:false,new_evaluation:false,artist_style_inference:false,genre_relationships:'All visible catalog source co-tags, not training/evaluation input'},counts:{artists:2,tracks:3,genres:2,singleton_artists:1,eligible_training_artists:1,eligible_training_components:1},artists:[{artist_id:11,track_ids:[101,103],track_count:2,singleton:false,component_id:1,fold:2,position:[1,.5],projection_reason:null,neighbor_reason:null,neighbors:[12]},{artist_id:12,track_ids:[102],track_count:1,singleton:true,component_id:2,fold:0,position:[1,2],projection_reason:null,neighbor_reason:'no_eligible_components',neighbors:[]}],genres:[{genre_id:1,track_ids:[101,102],artist_ids:[11,12],component_ids:[1,2],track_count:2,artist_count:2,component_count:2,relationships:[{genre_id:2,track_ids:[102],artist_ids:[12],component_ids:[2],track_count:1,artist_count:1,component_count:1}]},{genre_id:2,track_ids:[102,103],artist_ids:[11,12],component_ids:[1,2],track_count:2,artist_count:2,component_count:2,relationships:[{genre_id:1,track_ids:[102],artist_ids:[12],component_ids:[2],track_count:1,artist_count:1,component_count:1}]}]};

async function browser(operation,discoveryFixture=discovery,delay=0){
 const root=await mkdtemp(join(tmpdir(),'candidate-discovery-test-'));let child,socket;let fail=false;const requests=[],errors=[];
 const server=createServer((request,response)=>{requests.push(request.url);if(request.url.startsWith('/candidate/manifest.json')){response.writeHead(fail?503:200,{'content-type':'application/json'});response.end(JSON.stringify(fixture));}else if(request.url.startsWith('/model/layout.json')){response.writeHead(200,{'content-type':'application/json'});response.end(JSON.stringify(layout));}else if(request.url.startsWith('/discovery/discovery.json')){setTimeout(()=>{response.writeHead(discoveryFixture?200:503,{'content-type':'application/json'});response.end(JSON.stringify(discoveryFixture));},delay);}else if(request.url.startsWith('/candidate/audio/')){response.writeHead(500);response.end('Synthetic contract forbids media fetch');}else{response.writeHead(200,{'content-type':'text/html'});response.end(page);}});
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

test('synthetic artist profiles connect maps, suggested members and exact source co-tags',{skip:!chromium,timeout:60000},async()=>{
 await browser(async({evaluate,wait,command})=>{
  await wait("document.documentElement?.dataset.candidateReady==='true'");await evaluate("location.hash='#map'");await wait("document.querySelectorAll('[data-map-artist]').length===2");
  assert.deepEqual(await evaluate('window.__media.plays'),[]);
  await evaluate("location.hash='#artist/11'");await wait("document.querySelector('#artist-suggestions')");
  assert.equal(await evaluate("document.querySelector('#main').textContent.includes('Recording profile from 2 excerpts')"),true);
  assert.equal(await evaluate("document.querySelector('#artist-suggestions [data-artist-id]').dataset.artistId"),'12');
  await evaluate("document.querySelector('#artist-suggestions [data-play-track]').click();window.__player=document.querySelector('audio');window.__credit=document.querySelector('#credit').textContent;location.hash='#genre/1'");await wait("document.querySelector('#genre-connections')");
  assert.equal(await evaluate("document.querySelector('#genre-connections li').dataset.trackCount"),'1');
  await evaluate("document.querySelector('#genre-connections a[href=\"#shared/1/2\"]').click()");await wait("document.querySelector('#main').dataset.route==='#shared/1/2'");assert.deepEqual(await evaluate("[...document.querySelectorAll('#results [data-track-id]')].map(x=>x.dataset.trackId)"),['102']);
  await evaluate('history.back()');await wait("document.querySelector('#main').dataset.route==='#genre/1'");await evaluate('history.forward()');await wait("document.querySelector('#main').dataset.route==='#shared/1/2'");
  await evaluate("location.hash='#map?view=artists&selected=11'");await wait("document.querySelector('[data-map-artist][data-selected=true]')");assert.equal(await evaluate("document.querySelector('[data-map-artist][data-selected=true]').dataset.mapArtist"),'11');
  await evaluate("document.querySelector('[data-map-artist][data-selected=true]').focus()");await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});await wait("document.querySelector('#main').dataset.route==='#artist/11'");
  await evaluate("location.hash='#map?view=excerpts&genre=1'");await wait("document.querySelectorAll('[data-map-track]').length===3");assert.equal(await evaluate("document.querySelectorAll('[data-map-track][data-highlighted=true]').length"),2);
  assert.equal(await evaluate("window.__player===document.querySelector('audio')&&window.__credit===document.querySelector('#credit').textContent"),true);assert.deepEqual(await evaluate('window.__media.plays'),['candidate/audio/102.mp3']);
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await wait("document.querySelector('svg').viewBox.baseVal.width<400");assert.equal(await evaluate('innerWidth'),390);assert.equal(await evaluate('document.documentElement.scrollWidth<=390'),true);
  for(const hash of ['#shared/1/1','#shared/999/2','#map?view=artists&selected=999','#map?view=bad','#map?view=excerpts&selected=0']){await evaluate(`location.hash=${JSON.stringify(hash)}`);await wait(`document.querySelector('#main').dataset.route===${JSON.stringify(hash)}`);assert.equal(await evaluate("document.querySelector('#main').textContent.includes('Not found')"),true);}
  await evaluate("location.hash='#artist/11';window.__before=true");await command('Page.reload');await wait("!window.__before&&document.documentElement?.dataset.candidateReady==='true'");assert.deepEqual(await evaluate('window.__media.plays'),[]);
 });
});

test('synthetic invalid discovery isolates failure from unchanged tracks and excerpt map',{skip:!chromium,timeout:60000},async()=>{
 const bad=structuredClone(discovery);bad.genres[0].relationships[0].track_count=999;
 await browser(async({evaluate,wait})=>{
  await wait("document.documentElement?.dataset.candidateReady==='true'");await evaluate("location.hash='#artist/11'");await wait("document.querySelector('#main').textContent.includes('suggestions are unavailable')");await evaluate("document.querySelector('#results [data-play-track]').click();location.hash='#map?view=excerpts'");await wait("document.querySelectorAll('[data-map-track]').length===3");assert.deepEqual(await evaluate('window.__media.plays'),['candidate/audio/101.mp3']);
  await evaluate("location.hash='#map?view=artists'");await wait("document.querySelector('#main').textContent.includes('artist map is unavailable')");await evaluate("location.hash='#genre/1'");await wait("document.querySelector('#main').textContent.includes('Connections are unavailable')");assert.equal(await evaluate("document.querySelectorAll('#results [data-track-id]').length"),2);
 },bad);
});

test('synthetic unplaced artist remains listed and playable with explicit absence',{skip:!chromium,timeout:60000},async()=>{
 const limited=structuredClone(discovery);Object.assign(limited.artists[0],{position:null,projection_reason:'unsupported_member',neighbor_reason:'unsupported_member',neighbors:[]});
 await browser(async({evaluate,wait})=>{await wait("document.documentElement?.dataset.candidateReady==='true'");await evaluate("location.hash='#map?view=artists&selected=11'");await wait("document.querySelector('#map-artists')");assert.equal(await evaluate("document.querySelectorAll('[data-map-artist]').length"),1);assert.equal(await evaluate("document.querySelectorAll('#map-artists li').length"),2);assert.equal(await evaluate("document.querySelector('#main').textContent.includes('no supported map position')"),true);await evaluate("document.querySelector('#results [data-play-track]').click()");assert.deepEqual(await evaluate('window.__media.plays'),['candidate/audio/101.mp3']);},limited);
});

test('synthetic delayed profile response follows current route and disconnects old map observer',{skip:!chromium,timeout:60000},async()=>{
 await browser(async({evaluate,wait,command})=>{await wait("document.documentElement?.dataset.candidateReady==='true'");await evaluate("location.hash='#artist/11'");await wait("document.querySelector('#main').dataset.route==='#artist/11'");await evaluate("document.querySelector('#results [data-play-track]').click();location.hash='#track/103'");await wait("discovery!==null");assert.equal(await evaluate("document.querySelector('#main').dataset.route"),'#track/103');assert.deepEqual(await evaluate('window.__media.plays'),['candidate/audio/101.mp3']);await evaluate("location.hash='#map'");await wait("document.querySelector('[data-map-artist]')");await evaluate("location.hash='#track/101'");await wait("document.querySelector('#main').dataset.route==='#track/101'");assert.equal(await evaluate('mapObserver===null'),true);await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});assert.equal(await evaluate("document.querySelector('#main').dataset.route"),'#track/101');},discovery,700);
});


test('synthetic mobile artist map has no colliding labels and bounded accessible view controls',{skip:!chromium,timeout:60000},async()=>{
 await browser(async({evaluate,wait,command})=>{
  await command('Page.bringToFront');
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await wait("document.documentElement?.dataset.candidateReady==='true'");
  await evaluate("location.hash='#track/101'");await wait("document.querySelector('#main [data-play-track]')");
  await evaluate("document.querySelector('#main [data-play-track]').click();window.__player=document.querySelector('audio');window.__src=window.__player.getAttribute('src');window.__credit=document.querySelector('#credit').textContent;location.hash='#map?view=artists&selected=11'");
  await wait("document.querySelectorAll('[data-map-artist]').length===2");
  const original=await evaluate("[...document.querySelectorAll('svg circle')].map(c=>[c.getAttribute('cx'),c.getAttribute('cy')]).sort()");
  assert.equal(await evaluate("document.querySelectorAll('svg text').length"),0,'no labels can overlap points or intercept another artist');
  assert.equal(await evaluate("document.querySelector('#map-artist-name a').getAttribute('href')"),'#artist/11');
  const initial=await evaluate("document.querySelector('svg').viewBox.baseVal.width");
  const click=label=>evaluate(`(()=>{const b=[...document.querySelectorAll('.map-controls button')].find(b=>b.textContent===${JSON.stringify(label)});b.focus();b.click()})()`);
  await click('Zoom in');assert.equal(await evaluate("document.querySelector('svg').viewBox.baseVal.width"),initial/2);
  const before=await evaluate("document.querySelector('svg').viewBox.baseVal.x");await click('Pan right');assert.ok(await evaluate("document.querySelector('svg').viewBox.baseVal.x")>before);
  for(let i=0;i<8;i++){await click('Zoom in');await click('Pan down');await click('Pan right');}
  assert.equal(await evaluate("document.querySelector('svg').viewBox.baseVal.width"),initial/8);
  assert.ok(await evaluate("document.querySelector('svg').viewBox.baseVal.y+document.querySelector('svg').viewBox.baseVal.height<=500.001"));
  await evaluate("document.querySelector('[data-map-artist][data-selected=true]').focus()");
  assert.equal(await evaluate("(()=>{const s=document.querySelector('svg'),v=s.viewBox.baseVal,c=document.activeElement.querySelector('circle'),x=Number(c.getAttribute('cx')),y=Number(c.getAttribute('cy'));return x>=v.x-.001&&x<=v.x+v.width+.001&&y>=v.y-.001&&y<=v.y+v.height+.001})()"),true,'focused point brought into viewport');
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});await wait("document.querySelector('#main').dataset.route==='#artist/11'");
  await evaluate('history.back()');await wait("document.querySelector('[data-map-artist]')");assert.equal(await evaluate("document.querySelector('svg').viewBox.baseVal.width"),initial/8);
  assert.equal(await evaluate("Number(document.querySelector('svg circle').getAttribute('r'))*8"),7);
  await evaluate('history.forward()');await wait("document.querySelector('#main').dataset.route==='#artist/11'");
  await evaluate("location.hash='#map?view=artists&selected=12'");await wait("document.querySelector('[data-map-artist][data-selected=true]')");
  assert.equal(await evaluate("document.querySelector('svg').lastElementChild.dataset.mapArtist"),'12');
  assert.equal(await evaluate("(()=>{const v=document.querySelector('svg').viewBox.baseVal,c=document.querySelector('[data-selected=true] circle'),x=Number(c.getAttribute('cx')),y=Number(c.getAttribute('cy'));return x>=v.x-.001&&x<=v.x+v.width+.001&&y>=v.y-.001&&y<=v.y+v.height+.001})()"),true);
  await click('Pan down');await click('Pan right');await evaluate("location.hash='#artist/12'");await wait("document.querySelector('#main').dataset.route==='#artist/12'");
  await evaluate("location.hash='#map?view=artists&selected=12'");await wait("document.querySelector('[data-selected=true]')");
  assert.equal(await evaluate("(()=>{const v=document.querySelector('svg').viewBox.baseVal,c=document.querySelector('[data-selected=true] circle'),y=Number(c.getAttribute('cy'));return y>=v.y-.001&&y<=v.y+v.height+.001})()"),true,'fresh Locate on map recenters same artist');
  for(let i=0;i<5;i++){await evaluate("location.hash='#map?view=artists'");await wait("document.querySelector('.map-controls')");await click('Reset view');await evaluate("location.hash='#genre/1'");await wait("document.querySelector('#main').dataset.route==='#genre/1'");}
  await evaluate("location.hash='#map?view=artists'");await wait("document.querySelector('.map-controls')");
  assert.deepEqual(await evaluate("[...document.querySelectorAll('svg circle')].map(c=>[c.getAttribute('cx'),c.getAttribute('cy')]).sort()"),original);
  assert.equal(await evaluate("document.querySelectorAll('.map-controls').length"),1);
  assert.equal(await evaluate("window.__player===document.querySelector('audio')&&window.__src===document.querySelector('audio').getAttribute('src')&&window.__credit===document.querySelector('#credit').textContent"),true);
  assert.deepEqual(await evaluate('window.__media.plays'),['candidate/audio/101.mp3']);
  assert.equal(await evaluate('innerWidth'),390);assert.equal(await evaluate('document.documentElement.scrollWidth<=390'),true);
 });
});
