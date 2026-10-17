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
 const root=await mkdtemp(join(tmpdir(),'candidate-discovery-test-'));let child,socket;let fail=initialFailure;const requests=[],errors=[],network=[];
 const server=createServer((request,response)=>{requests.push(request.url);if(request.url.startsWith('/packet.json')){response.writeHead(fail?503:200,{'content-type':'application/json'});response.end(JSON.stringify(fixture));}else if(request.url.startsWith('/audio/')){response.writeHead(500);response.end('Synthetic contract forbids media fetch');}else{response.writeHead(200,{'content-type':'text/html'});response.end(page);}});
 try{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin=`http://127.0.0.1:${server.address().port}`;
  child=spawn(chromium,['--headless=new','--no-first-run','--no-default-browser-check','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-background-networking','--remote-debugging-port=0',`--user-data-dir=${root}`,'about:blank']);
  const endpoint=await new Promise((resolve,reject)=>{let output='';const timer=setTimeout(()=>reject(Error('Chromium startup exceeded30s')),30000);child.once('error',reject);child.stderr.on('data',bytes=>{output+=bytes;const match=/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\//.exec(output);if(match){clearTimeout(timer);resolve(`http://127.0.0.1:${match[1]}`);}});});
  const target=await fetch(`${endpoint}/json/new?about:blank`,{method:'PUT'}).then(r=>r.json());socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise(resolve=>socket.addEventListener('open',resolve,{once:true}));let next=0;const pending=new Map();
  socket.addEventListener('message',({data})=>{const message=JSON.parse(data);if(message.method==='Network.requestWillBeSent')network.push(message.params.request.url);if(message.method==='Runtime.exceptionThrown')errors.push(message.params);pending.get(message.id)?.(message);});
  const command=(method,params={})=>new Promise((resolve,reject)=>{const id=++next,timer=setTimeout(()=>reject(Error(`${method} timeout`)),10000);pending.set(id,message=>{clearTimeout(timer);pending.delete(id);message.error?reject(Error(JSON.stringify(message.error))):resolve(message.result);});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const result=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,userGesture:true});if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));return result.result?.value;};
  const wait=async expression=>{for(let i=0;i<250;i++){if(await evaluate(expression))return;await new Promise(resolve=>setTimeout(resolve,20));}throw Error('Readiness failed: '+expression);};
  await command('Runtime.enable');await command('Page.enable');await command('Network.enable');
  await command('Page.addScriptToEvaluateOnNewDocument',{source:`window.__media={plays:[],pauses:0};HTMLMediaElement.prototype.play=function(){window.__media.plays.push(this.getAttribute('src'));this.dataset.stubPlaying='true';if(window.__rejectNext){window.__rejectNext=false;return Promise.reject(Error('synthetic failure'));}return Promise.resolve();};HTMLMediaElement.prototype.pause=function(){window.__media.pauses++;this.dataset.stubPlaying='false';};HTMLMediaElement.prototype.load=function(){};`});
  await command('Page.navigate',{url:origin});
  await operation({evaluate,wait,command,origin,requests,setFailure:value=>{fail=value;}});
  assert.deepEqual(errors,[]);assert.equal(network.some(url=>!url.startsWith(origin+'/')&&!url.startsWith('blob:')&&!url.startsWith('data:')),false,'no external requests: '+JSON.stringify(network));assert.equal(requests.some(url=>url.startsWith('/audio/')),false,'stubbed test performs no audio requests');
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
  await wait("document.querySelector('#items button')?.textContent==='Retry'");assert.equal(await evaluate("document.querySelector('#restore').disabled"),true);setFailure(false);await evaluate("document.querySelector('#items button').click()");await wait("document.documentElement?.dataset.pilotReady==='true'");assert.deepEqual(await evaluate('window.__media.plays'),[]);assert.equal(await evaluate('answers().items.every(r=>r.choice===null)'),true);
 },true);
});

// These files contain synthetic answers only; imports use the actual browser File API.
async function importText(evaluate, text) {
 await evaluate(`(() => {
   const files = new DataTransfer();
   files.items.add(new File([${JSON.stringify(text)}], 'synthetic-responses.json', {type:'application/json'}));
   const input = document.querySelector('#restore');
   input.files = files.files;
   input.dispatchEvent(new Event('change', {bubbles:true}));
 })()`);
}

async function exportAnswers(evaluate) {
 return evaluate(`(async () => {
   URL.createObjectURL = blob => {window.__export = blob; return 'blob:synthetic';};
   HTMLAnchorElement.prototype.click = function(){};
   document.querySelector('#save').click();
   return JSON.parse(await window.__export.text());
 })()`);
}

test('synthetic saved answers round trip after reload with Unicode and false preserved', {skip:!chromium,timeout:60000}, async () => {
 await browser(async ({evaluate, wait, command, requests}) => {
  await wait("document.documentElement?.dataset.pilotReady==='true'");
  assert.equal(await evaluate("document.querySelector('#restore').disabled"), false);
  await evaluate(`(() => {
   const article = document.querySelector('article');
   for (const [name,value] of Object.entries({choice:'neither',heard_query:'true',heard_A:'false',conflict:'false',familiarity:'candidate',notes:'🎵'.repeat(1000)})) article.querySelector('[name='+name+']').value=value;
   article.querySelector('[name=choice]').dispatchEvent(new Event('change',{bubbles:true}));
  })()`);
  assert.equal(await evaluate("document.querySelector('#progress').textContent"), 'Choices recorded: 1 of 6');
  const saved = await exportAnswers(evaluate);
  assert.equal(saved.items[0].notes.length,2000);
  assert.equal(saved.items[0].heard_A,false);
  assert.equal(saved.items[0].heard_B,null);
  await evaluate('window.__oldPage=true');
  await command('Page.reload');
  await wait("!window.__oldPage&&document.documentElement?.dataset.pilotReady==='true'");
  const beforeRequests = requests.length;
  await evaluate("window.__confirmCalls=0;window.confirm=()=>{window.__confirmCalls++;return true;}");
  const reversed = {...saved,items:[...saved.items].reverse()};
  await importText(evaluate,JSON.stringify(reversed));
  await wait("document.querySelector('#status').textContent.startsWith('Saved answers restored')");
  assert.deepEqual(await exportAnswers(evaluate),saved);
  assert.equal(await evaluate('window.__confirmCalls'),0);
  assert.equal(await evaluate("document.querySelector('#restore').value"),'');
  assert.equal(await evaluate("document.querySelector('#progress').textContent"),'Choices recorded: 1 of 6');
  // Restoring the same file again is possible and asks before replacing nonblank answers.
  await importText(evaluate,JSON.stringify(saved));
  await wait('window.__confirmCalls===1');
  assert.deepEqual(await evaluate('answers()'),saved);
  assert.equal(requests.length,beforeRequests,'local restore requests no packet, media or other resource');
  assert.deepEqual(await evaluate('window.__media.plays'),[]);
  assert.equal(await evaluate('localStorage.length+sessionStorage.length'),0);
  await command('Emulation.setDeviceMetricsOverride',{width:320,height:740,deviceScaleFactor:1,mobile:true});
  assert.equal(await evaluate('innerWidth'),320,JSON.stringify(await evaluate(`Array.from(document.querySelectorAll('body *')).map(e=>({tag:e.tagName,id:e.id,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right})).filter(e=>e.right>320)`)));
  assert.equal(await evaluate('document.documentElement.scrollWidth<=320'),true);
  await evaluate("document.querySelector('#save').focus()");
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
  assert.equal(await evaluate('document.activeElement.id'),'restore');
 });
});

test('synthetic invalid restores are atomic and strict, and replacement cancellation preserves edits', {skip:!chromium,timeout:60000}, async () => {
 await browser(async ({evaluate,wait}) => {
  await wait("document.documentElement?.dataset.pilotReady==='true'");
  await evaluate("document.querySelector('[name=heard_A]').value='false';window.__confirmCalls=0;window.confirm=()=>{window.__confirmCalls++;return false;}");
  const current=await evaluate('answers()');
  const valid=structuredClone(current);valid.items[0].choice='B';
  await importText(evaluate,JSON.stringify(valid));
  await wait("document.querySelector('#status').textContent.startsWith('Restore cancelled')");
  assert.equal(await evaluate('window.__confirmCalls'),1,'false is a nonblank answer requiring confirmation');
  assert.deepEqual(await evaluate('answers()'),current);
  const cases=[
   value=>{value.packet_sha256='0'.repeat(64);},value=>{value.slot=2;},value=>{value.slot=true;},
   value=>{value.extra='untrusted';},value=>{delete value.revision;},
   value=>{value.items.pop();},value=>{value.items[5]=structuredClone(value.items[0]);},
   value=>{value.items[5].item_id='T99';},value=>{value.items[5].extra=1;},
   value=>{delete value.items[5].notes;},value=>{value.items[5].choice='unknown';},
   value=>{value.items[5].choice=0;},value=>{value.items[5].familiarity=false;},
   value=>{value.items[5].heard_A=0;},value=>{value.items[5].heard_B='false';},
   value=>{value.items[5].conflict=1;},value=>{value.items[5].notes=null;},
   value=>{value.items[5].notes='🎵'.repeat(1001);},
  ];
  for(const change of cases){
   const invalid=structuredClone(valid);change(invalid);
   await importText(evaluate,JSON.stringify(invalid));
   await wait("document.querySelector('#status').textContent.startsWith('Answers were not restored')");
   assert.deepEqual(await evaluate('answers()'),current);
  }
  for(const text of ['{malformed','null','[]',' '.repeat(200001)]){
   await importText(evaluate,text);
   await wait("document.querySelector('#status').textContent.startsWith('Answers were not restored')");
   assert.deepEqual(await evaluate('answers()'),current);
  }
  assert.equal(await evaluate('window.__confirmCalls'),1,'invalid files never ask to replace');
  assert.deepEqual(await evaluate('window.__media.plays'),[]);
  // A cancelled chooser is a no-op, and reset permits a later valid import.
  await evaluate("document.querySelector('#restore').dispatchEvent(new Event('change'));document.querySelector('#restore').dispatchEvent(new Event('cancel'))");
  assert.deepEqual(await evaluate('answers()'),current);
  await evaluate('window.confirm=()=>true');
  await importText(evaluate,JSON.stringify(valid));
  await wait("document.querySelector('#status').textContent.startsWith('Saved answers restored')");
  assert.deepEqual(await evaluate('answers()'),valid);
 });
});

test('synthetic restore bounds reads and rejects stale imports without overwriting edits', {skip:!chromium,timeout:60000}, async () => {
 await browser(async ({evaluate,wait}) => {
  await wait("document.documentElement?.dataset.pilotReady==='true'");
  const blank=await evaluate('answers()');
  const old=structuredClone(blank);old.items[0].choice='A';
  const newer=structuredClone(blank);newer.items[0].choice='B';
  // Hook only reading, preserving real File input dispatch, to expose the async race deterministically.
  await evaluate("window.__nativeText=File.prototype.text;window.__reads=0;File.prototype.text=function(){window.__reads++;return new Promise(resolve=>window.__resolveRead=resolve);}");
  await importText(evaluate,' '.repeat(200001));
  await wait("document.querySelector('#status').textContent.includes('200000 bytes')");
  assert.equal(await evaluate('window.__reads'),0,'advertised file size is checked before reading');
  await importText(evaluate,'small');
  await wait('window.__reads===1');
  await evaluate(`window.__resolveRead(${JSON.stringify('é'.repeat(100001))})`);
  await wait("document.querySelector('#status').textContent.includes('200000 bytes')");
  assert.deepEqual(await evaluate('answers()'),blank,'encoded content bound also applies after read');
  await importText(evaluate,'small');
  await wait('window.__reads===2');
  await evaluate("document.querySelector('[name=notes]').value='New local edit';document.querySelector('[name=notes]').dispatchEvent(new Event('input',{bubbles:true}))");
  await evaluate(`window.__resolveRead(${JSON.stringify(JSON.stringify(old))})`);
  assert.equal(await evaluate("document.querySelector('[name=notes]').value"),'New local edit');
  assert.equal(await evaluate("document.querySelector('[name=choice]').value"),'');
  await importText(evaluate,'small');
  await wait('window.__reads===3');
  await evaluate('window.__oldResolve=window.__resolveRead;File.prototype.text=window.__nativeText;window.confirm=()=>true');
  await importText(evaluate,JSON.stringify(newer));
  await wait("document.querySelector('#status').textContent.startsWith('Saved answers restored')");
  await evaluate(`window.__oldResolve(${JSON.stringify(JSON.stringify(old))})`);
  assert.deepEqual(await evaluate('answers()'),newer,'older read cannot replace a newer restore');
  assert.deepEqual(await evaluate('window.__media.plays'),[]);
 });
});
