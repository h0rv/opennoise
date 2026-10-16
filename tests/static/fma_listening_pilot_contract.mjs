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
const page=await readFile(new URL('../../src/opennoise/static/fma-listening-pilot.html',import.meta.url),'utf8');
const track=(id)=>({track_id:id,artist_id:id,title:'Synthetic excerpt '+id,artist_name:'Fixture artist',audio_path:`audio/${id}.mp3`,license_url:'https://creativecommons.org/licenses/by/4.0/',source_url:'',attribution:'Synthetic fixture credit '+'https://example.org/'+('long'.repeat(50)),composer:'Fixture composer',copyright_c:'',copyright_p:'',embedded_source_urls:['https://example.org/source'],embedded_curators:['Fixture curator'],embedded_notices:{copyright:'Fixture notice'},embedded_extra_text_present:false});
const fixture={revision:'fma-permitted55-listening-v1',slot:1,tracks:Object.fromEntries([101,102,103].map(i=>[i,track(i)])),metadata_attribution:'Synthetic fixture',items:Array.from({length:6},(_,i)=>({item_id:`T0${i+1}`,query:101,A:102,B:i===1?102:i===2?null:103,identical_candidates:i===1,unsupported:i===2}))};

async function browser(operation,initialFailure=false){
 const root=await mkdtemp(join(tmpdir(),'candidate-discovery-test-'));let child,socket;let fail=initialFailure;const requests=[],errors=[];
 const server=createServer((request,response)=>{requests.push(request.url);if(request.url.startsWith('/packet.json')){response.writeHead(fail?503:200,{'content-type':'application/json'});response.end(JSON.stringify(fixture));}else if(request.url.startsWith('/audio/')){response.writeHead(500);response.end('Synthetic contract forbids media fetch');}else{response.writeHead(200,{'content-type':'text/html'});response.end(page);}});
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

test('synthetic pilot leaves all answers blank and exports only participant choices',{skip:!chromium,timeout:60000},async()=>{
 await browser(async({evaluate,wait,command})=>{
  await wait("document.documentElement?.dataset.pilotReady==='true'");
  assert.equal(await evaluate("document.querySelectorAll('article').length"),6);
  assert.deepEqual(await evaluate('window.__media.plays'),[]);
  assert.equal(await evaluate("answers().items.every(r=>r.choice===null&&r.heard_A===null&&r.conflict===null)"),true);
  assert.equal(await evaluate("document.querySelector('[data-item-id=T02]').textContent.includes('same recording')"),true);
  assert.equal(await evaluate("document.querySelector('[data-item-id=T03]').textContent.includes('unavailable')"),true);
  await evaluate("document.querySelector('article button').click();window.__player=document.querySelector('audio')");
  assert.deepEqual(await evaluate('window.__media.plays'),['audio/101.mp3']);
  await evaluate("document.querySelectorAll('article button')[1].click()");
  assert.equal(await evaluate("window.__player===document.querySelector('audio')&&document.querySelector('#credit').textContent.includes('102')&&document.querySelector('#notices').textContent.includes('Fixture composer')"),true);
  await evaluate("const a=document.querySelector('article');a.querySelector('[name=choice]').value='A';for(const name of ['heard_query','heard_A','heard_B'])a.querySelector('[name='+name+']').value='true';a.querySelector('[name=conflict]').value='false';a.querySelector('[name=familiarity]').value='none';URL.createObjectURL=b=>{window.__export=b;return 'blob:synthetic';};HTMLAnchorElement.prototype.click=function(){};document.querySelector('#save').click()");
  const exported=await evaluate('window.__export.text().then(JSON.parse)');
  assert.equal(exported.slot,1);assert.match(exported.packet_sha256,/^[a-f0-9]{64}$/);assert.equal(exported.items.length,6);assert.equal(exported.items[0].choice,'A');assert.equal(exported.items.filter(r=>r.choice===null).length,5);assert.equal(JSON.stringify(exported).includes('raw'),false);assert.equal(JSON.stringify(exported).includes('simple4'),false);
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});assert.equal(await evaluate('innerWidth'),390);assert.equal(await evaluate('document.documentElement.scrollWidth<=390'),true);
  await evaluate("document.querySelector('#stop').click()");assert.equal(await evaluate("document.querySelector('audio').hasAttribute('src')"),false);
  await evaluate('window.__beforeReload=true');await command('Page.reload');await wait("!window.__beforeReload&&document.documentElement?.dataset.pilotReady==='true'");assert.deepEqual(await evaluate('window.__media.plays'),[]);assert.equal(await evaluate('answers().items.every(r=>r.choice===null)'),true);
 });
});

test('synthetic pilot retry never fills answers or starts audio',{skip:!chromium,timeout:60000},async()=>{
 await browser(async({evaluate,wait,setFailure})=>{
  await wait("document.querySelector('#items button')?.textContent==='Retry'");setFailure(false);await evaluate("document.querySelector('#items button').click()");await wait("document.documentElement?.dataset.pilotReady==='true'");assert.deepEqual(await evaluate('window.__media.plays'),[]);assert.equal(await evaluate('answers().items.every(r=>r.choice===null)'),true);
 },true);
});
