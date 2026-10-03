import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';

// Set OPENNOISE_LISTENER_PILOT_ROOT to the extracted, verified pilot directory.
// Profiles use TMPDIR; no source export files are modified by the browser.
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
async function browser(root, operation) {
  const exportRoot = resolve(root);
  const profile = await mkdtemp(join(tmpdir(), 'opennoise-skip-contract-'));
  let server;const httpFallback=process.env.OPENNOISE_LISTENER_PILOT_HTTP==='1';
  if(httpFallback){server=createServer(async(request,response)=>{const pathname=new URL(request.url,'http://localhost').pathname;const file=resolve(exportRoot,'.'+(pathname==='/'?'/listen.html':pathname));if(!file.startsWith(exportRoot+sep)){response.statusCode=403;response.end();return;}try{response.setHeader('Content-Type',file.endsWith('.html')?'text/html':file.endsWith('.mp3')?'audio/mpeg':'application/json');response.end(await readFile(file));}catch{response.statusCode=404;response.end();}});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));}
  const url = server?`http://127.0.0.1:${server.address().port}/`:pathToFileURL(join(exportRoot,'listen.html')).href;
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
    const evaluate = async expression => { const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true, userGesture: true}).catch(error=>{throw new Error(error.message+'; expression='+expression);}); if (result.exceptionDetails) throw new Error(result.exceptionDetails.text); return result.result.value; };
    const wait = async expression => { for (let index = 0; index < 400; index++) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 20)); } throw new Error('Timed out: ' + expression+'; page='+JSON.stringify(await evaluate('({url:location.href,title:document.title,body:document.body?.textContent.slice(0,500),audio:document.querySelectorAll(\'audio\').length})'))); };
    await command('Network.enable');await command('Network.setCacheDisabled',{cacheDisabled:true}); await command('Runtime.enable'); await command('Emulation.setDeviceMetricsOverride', {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false}); const navigation=await command('Page.navigate', {url});assert.equal(navigation.errorText,undefined,JSON.stringify(navigation));
    await operation({evaluate, wait, command, requests, url});
    assert.deepEqual(errors, []); assert.ok(requests.every(row => (httpFallback?new URL(row.request.url).origin===new URL(url).origin:row.request.url.startsWith(pathToFileURL(exportRoot+sep).href)) || row.type==='Image' && row.request.url.startsWith('data:image/svg+xml;base64,')), 'only owned static network requests and inline native SVG control icons');
  } catch(error) {throw new Error(`${error.message}; Chromium exit=${child.exitCode} signal=${child.signalCode}; ${diagnostics}`,{cause:error});} finally {
    socket?.close(); child.kill('SIGKILL'); await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('close', resolve)); await rm(profile, {recursive: true, force: true});if(server)await new Promise(resolve=>server.close(resolve));
  }
}




const root=process.env.OPENNOISE_LISTENER_PILOT_ROOT;
const report=process.env.OPENNOISE_LISTENER_PILOT_BROWSER_REPORT;
test('extracted independent listening pilot works offline with relative media paths and no fit candidate', {skip:!root||!chromium,timeout:120000},async()=>{
  const cohort=JSON.parse(await readFile(join(root,'cohort.json')));
  assert.equal(cohort.items.length,8);
  const results=[];
  // Fresh browser per clip bounds decoded-buffer retention without changing media.
  for(const item of cohort.items){await browser(root,async({evaluate,wait,command,requests,url})=>{
    await wait("document.querySelectorAll('audio').length===8");
    assert.equal(new URL(url).protocol,process.env.OPENNOISE_LISTENER_PILOT_HTTP==='1'?'http:':'file:');
    assert.ok(!requests.some(row=>row.request.url.endsWith('.mp3')),'no initial media fetch');
    assert.equal(await evaluate("[...document.querySelectorAll('audio')].every(a=>a.controls&&!a.autoplay&&a.preload==='none')"),true);
    const selector=`audio[data-track-id="${item.native_track_id}"]`;
      assert.equal(await evaluate(`document.querySelector(${JSON.stringify(selector)}).getAttribute('src')`),item.playback_url);
      assert.ok(!item.playback_url.startsWith('/')&&!item.playback_url.includes('://'));
      await evaluate(`(()=>{const a=document.querySelector(${JSON.stringify(selector)});a.preload='metadata';a.load();})()`);
      await wait(`(()=>{const a=document.querySelector(${JSON.stringify(selector)});return a.readyState>=1&&Number.isFinite(a.duration);})()`);
      const duration=await evaluate(`document.querySelector(${JSON.stringify(selector)}).duration`);assert.ok(duration>=25&&duration<=35);
      await evaluate(`document.querySelector(${JSON.stringify(selector)}).play().then(()=>true)`);
      await wait(`(()=>{const a=document.querySelector(${JSON.stringify(selector)});return !a.paused&&a.currentTime>0.08;})()`);
      const currentTime=await evaluate(`document.querySelector(${JSON.stringify(selector)}).currentTime`);
      await evaluate(`document.querySelector(${JSON.stringify(selector)}).pause()`);assert.equal(await evaluate(`document.querySelector(${JSON.stringify(selector)}).paused`),true);
      assert.ok(await evaluate(`document.body.textContent.includes(${JSON.stringify(item.attribution)})`));
      const bytes=await readFile(join(root,item.playback_url));assert.equal(createHash('sha256').update(bytes).digest('hex'),item.clip_sha256);
      await evaluate(`(()=>{const a=document.querySelector(${JSON.stringify(selector)});a.removeAttribute('src');a.load();})()`);
      results.push({item_id:item.item_id,track_id:item.native_track_id,audio_sha256:item.clip_sha256,duration,observed_current_time:currentTime,actual_decode_play_pause:true});
  });}
  await browser(root,async({evaluate,wait,command})=>{
    await wait("document.querySelectorAll('audio').length===8");
    assert.ok(await evaluate("document.body.textContent.includes('Leave fit_1_5 blank')"));
    assert.equal(await evaluate("document.querySelectorAll('iframe,video').length"),0);
    await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
    assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
    await evaluate("document.querySelector('.skip').focus()");await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});assert.equal(await evaluate("document.activeElement===document.querySelector('main')"),true);
  });
  // Write evidence only after runtime and request-scope checks also pass.
  if(report){const files={};for(const name of ['listen.html','cohort.json','declaration.json','review-form.csv','reviewer-assignments.json','listener-request.txt','README.md','SHA256SUMS',...cohort.items.map(row=>row.playback_url)]){const bytes=await readFile(join(root,name));files[name]={sha256:createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length};}await writeFile(report,JSON.stringify({revision:'opennoise-offline-listener-pilot-browser-v1',root,files,tracks:results,checks:{file_protocol_open:process.env.OPENNOISE_LISTENER_PILOT_HTTP!=='1',local_http_fallback:process.env.OPENNOISE_LISTENER_PILOT_HTTP==='1',relative_audio_paths:true,no_initial_media_fetch:true,no_autoplay:true,all_eight_clips_decode_play_pause:true,per_clip_attribution:true,fit_candidate_absent:true,fit_rating_explicitly_blank:true,mobile_no_overflow:true,keyboard_skip_link:true},musical_judgments:0,physical_listeners:0,playback_activation:'Chromium DevTools userGesture; no perceptual judgment'},null,2)+'\n');}
});
