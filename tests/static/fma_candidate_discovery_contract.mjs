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
const source=await readFile(new URL('../../src/opennoise/deployment/fma_public_candidate.py',import.meta.url),'utf8');
const page=/PAGE = r"""([\s\S]*?)"""/.exec(source)[1];
const track=(id,artist,genres,title)=>({track_id:id,artist_id:artist,title,artist_name:artist===11?'Fixture One':'Fixture Two',genre_ids:genres,audio_path:`audio/${id}.mp3`,license_url:'https://creativecommons.org/licenses/by/4.0/',source_url:'',attribution:`Synthetic fixture ${id}; not FMA audio`,composer:'Supplied fixture composer',copyright_c:'',copyright_p:'',embedded_source_urls:['https://freemusicarchive.org/music/fixture'],embedded_curators:['Fixture curator'],embedded_notices:{copyright:'Fixture notice'},embedded_extra_text_present:false});
const fixture={revision:'fma-declared-license-candidate-v1',public_deployment_authorized:false,genres:[{genre_id:1,title:'Drone & Noise'},{genre_id:2,title:'Quiet'}],tracks:[track(101,11,[1],'A&B / #'),track(102,12,[1,2],'Second'),track(103,11,[2],'Third')]};

async function browser(operation,initialFailure=false){
 const root=await mkdtemp(join(tmpdir(),'candidate-discovery-test-'));let child,socket;let fail=initialFailure;const requests=[],errors=[];
 const server=createServer((request,response)=>{requests.push(request.url);if(request.url.startsWith('/manifest.json')){response.writeHead(fail?503:200,{'content-type':'application/json'});response.end(JSON.stringify(fixture));}else if(request.url.startsWith('/audio/')){response.writeHead(500);response.end('Synthetic contract forbids media fetch');}else{response.writeHead(200,{'content-type':'text/html'});response.end(page);}});
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
  assert.deepEqual(errors,[]);assert.equal(requests.some(url=>url.startsWith('/audio/')),false,'stubbed test performs no audio requests');
 }finally{socket?.close();if(child){child.kill('SIGKILL');await new Promise(resolve=>child.exitCode!==null||child.signalCode!==null?resolve():child.once('close',resolve));}if(server.listening)await new Promise(resolve=>server.close(resolve));await rm(root,{recursive:true,force:true});}
}

test('synthetic candidate native routes, counts, history, search and persistent player',{skip:!chromium,timeout:60000},async()=>{
 await browser(async({evaluate,wait,command})=>{
  await wait("document.documentElement?.dataset.candidateReady==='true'");
  assert.deepEqual(await evaluate("[...document.querySelectorAll('#results li')].map(x=>[x.dataset.genreId,x.dataset.trackCount,x.dataset.artistCount])"),[['1','2','2'],['2','2','2']]);
  assert.deepEqual(await evaluate('window.__media.plays'),[]);
  await evaluate("document.querySelector('a[href=\"#genre/1\"]').click()");await wait("document.querySelector('#main').dataset.route==='#genre/1'");
  assert.deepEqual(await evaluate("[...document.querySelectorAll('#results li')].map(x=>x.dataset.trackId)"),['101','102']);
  await evaluate("document.querySelector('[data-play-track=\"101\"]').click();window.__player=document.querySelector('audio');window.__credit=document.querySelector('#credit').textContent");
  assert.deepEqual(await evaluate('window.__media.plays'),['audio/101.mp3']);
  for(const hash of ['#artist/11','#track/103','#genre/2','#artists','#tracks']){
   await evaluate(`location.hash=${JSON.stringify(hash)}`);await wait(`document.querySelector('#main').dataset.route===${JSON.stringify(hash)}`);
   assert.equal(await evaluate("window.__player===document.querySelector('audio')&&window.__credit===document.querySelector('#credit').textContent&&document.querySelector('audio').dataset.stubPlaying==='true'"),true);
  }
  await evaluate("document.querySelector('#search').value='A&B / #';document.querySelector('#search').dispatchEvent(new Event('input'))");
  assert.equal(await evaluate('location.hash'),'#tracks?q=A%26B%20%2F%20%23');
  const length=await evaluate('history.length');await evaluate("document.querySelector('#search').value='Second';document.querySelector('#search').dispatchEvent(new Event('input'))");assert.equal(await evaluate('history.length'),length);
  await evaluate('history.back()');await wait("document.querySelector('#main').dataset.route==='#artists'");
  await evaluate('history.forward()');await wait("document.querySelector('#search').value==='Second'");
  assert.deepEqual(await evaluate("[...document.querySelectorAll('#results li')].map(x=>x.dataset.trackId)"),['102']);
  assert.equal(await evaluate("window.__player===document.querySelector('audio')&&window.__credit===document.querySelector('#credit').textContent&&document.querySelector('audio').dataset.stubPlaying==='true'&&document.querySelector('audio').getAttribute('src')==='audio/101.mp3'"),true);
  for(const hash of ['#track/999','#artist/-1','#genre/NaN','#track/9007199254740992']){await evaluate(`location.hash=${JSON.stringify(hash)}`);await wait(`document.querySelector('#main').dataset.route===${JSON.stringify(hash)}`);assert.equal(await evaluate("document.querySelector('#main h2').textContent"),'Not found');}
  assert.deepEqual(await evaluate('window.__media.plays'),['audio/101.mp3']);
  await evaluate("location.hash='#track/101'");await wait("document.querySelector('#main').dataset.route==='#track/101'");
  await evaluate('window.__reloadSentinel=true');await command('Page.reload');await wait("!window.__reloadSentinel&&document.documentElement?.dataset.candidateReady==='true'&&document.querySelector('#main')?.dataset.route==='#track/101'");assert.deepEqual(await evaluate('window.__media.plays'),[]);
  assert.equal(await evaluate("document.querySelector('#main h2').textContent"),'A&B / #');
  await evaluate("document.querySelector('.skip').focus()");await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});assert.equal(await evaluate("document.activeElement.id==='main'&&location.hash==='#track/101'"),true);
  await evaluate("document.querySelector('nav a[href=\"#genres\"]').focus()");
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});await wait("document.querySelector('#main').dataset.route==='#genres'");
  await evaluate("document.querySelector('#results a').focus()");await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});await wait("document.querySelector('#main').dataset.route==='#genre/1'");assert.deepEqual(await evaluate('window.__media.plays'),[]);
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
  await evaluate("window.__rejectNext=true;document.querySelector('[data-play-track]').click()");await wait("document.querySelector('#error').textContent.includes('failed')");await evaluate("document.querySelector('[data-play-track]').click()");assert.equal(await evaluate("document.querySelector('#error').textContent"),'');
  await evaluate("document.querySelector('#stop').click()");assert.equal(await evaluate("document.querySelector('audio').hasAttribute('src')"),false);
 });
});

test('synthetic candidate initial failure retries latest native route without autoplay',{skip:!chromium,timeout:60000},async()=>{
 await browser(async({evaluate,wait,setFailure})=>{
  await wait("document.querySelector('#main button')?.textContent==='Retry'");
  await evaluate("location.hash='#artist/12'");setFailure(false);await evaluate("document.querySelector('#main button').click()");
  await wait("document.querySelector('#main').dataset.route==='#artist/12'");assert.equal(await evaluate("document.querySelector('#main h2').textContent"),'Fixture Two');assert.deepEqual(await evaluate('window.__media.plays'),[]);
 },true);
});
