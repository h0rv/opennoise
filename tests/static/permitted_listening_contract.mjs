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
    try { response.setHeader('Content-Type', (/\.m?js$/.test(file)) ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : file.endsWith('.mp3') ? 'audio/mpeg' : 'application/json'); response.end(await readFile(file)); }
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
    const evaluate = async expression => { const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true, userGesture: true}).catch(error=>{throw new Error(error.message+'; expression='+expression);}); if (result.exceptionDetails) throw new Error(result.exceptionDetails.text+'; expression='+expression); return result.result.value; };
    const wait = async expression => { for (let index = 0; index < 400; index++) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 20)); } throw new Error('Timed out: ' + expression); };
    await command('Network.enable');await command('Network.setCacheDisabled',{cacheDisabled:true}); await command('Runtime.enable'); await command('Emulation.setDeviceMetricsOverride', {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false}); const navigation=await command('Page.navigate', {url});assert.equal(navigation.errorText,undefined,JSON.stringify(navigation));
    await operation({evaluate, wait, command, requests, url});
    assert.deepEqual(errors, []); assert.ok(requests.every(row => new URL(row.request.url).origin === new URL(url).origin || row.type==='Image' && row.request.url.startsWith('data:image/svg+xml;base64,')), 'only owned static network requests and inline native SVG control icons');
  } catch(error) {throw new Error(`${error.message}; Chromium exit=${child.exitCode} signal=${child.signalCode}; ${diagnostics}`,{cause:error});} finally {
    socket?.close(); child.kill('SIGKILL'); await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('close', resolve)); await rm(profile, {recursive: true, force: true}); await new Promise(resolve => server.close(resolve));
  }
}



const root=process.env.OPENNOISE_PERMITTED_LISTENING_STATIC_ROOT;
const report=process.env.OPENNOISE_PERMITTED_LISTENING_BROWSER_REPORT;
test('permitted FMA clips decode, play and pause with native attribution and accessible controls', {skip:!root||!chromium,timeout:120000},async()=>{
  const data=JSON.parse(await readFile(join(root,'listening.json')));
  assert.equal(data.tracks.length,8);
  const results=[];
  let browserEvidence;
  // Fresh browser per clip bounds decoded-buffer retention without changing media.
  for(const track of data.tracks){await browser(root,async({evaluate,wait,command,requests,url})=>{
    await wait("document.querySelectorAll('audio').length===8");
    assert.ok(!requests.some(row=>new URL(row.request.url).pathname.endsWith('.mp3')),'no media fetched on initial loading');
    assert.equal(await evaluate("[...document.querySelectorAll('audio')].every(a=>!a.autoplay&&a.preload==='none'&&a.controls)"),true);
    const selector=`audio[data-track-id="${track.track_id}"]`;
      assert.equal(await evaluate(`document.querySelector(${JSON.stringify(selector)})!==null`),true);
      await evaluate(`(()=>{const a=document.querySelector(${JSON.stringify(selector)});a.preload='metadata';a.load();})()`);
      await wait(`(()=>{const a=document.querySelector(${JSON.stringify(selector)});return a.readyState>=1&&Number.isFinite(a.duration);})()`);
      const duration=await evaluate(`document.querySelector(${JSON.stringify(selector)}).duration`);
      assert.ok(duration>=25&&duration<=35,`native 30-second excerpt duration ${track.track_id}: ${duration}`);
      await evaluate(`document.querySelector(${JSON.stringify(selector)}).play().then(()=>true)`);
      await wait(`(()=>{const a=document.querySelector(${JSON.stringify(selector)});return !a.paused&&a.currentTime>0.08;})()`);
      const currentTime=await evaluate(`document.querySelector(${JSON.stringify(selector)}).currentTime`);
      await evaluate(`document.querySelector(${JSON.stringify(selector)}).pause()`);
      assert.equal(await evaluate(`document.querySelector(${JSON.stringify(selector)}).paused`),true);
      assert.ok(await evaluate(`document.body.textContent.includes(${JSON.stringify(track.attribution)})`),'per-track attribution visible');
      await evaluate(`(()=>{const a=document.querySelector(${JSON.stringify(selector)});a.removeAttribute('src');a.load();})()`);
      results.push({track_id:track.track_id,audio_sha256:track.audio_sha256,duration,observed_current_time:currentTime,decode_play_pause:true,activation:'Chromium DevTools userGesture playback; no listener judgment'});
  });}
  await browser(root,async({evaluate,wait,command,requests})=>{
    await wait("document.querySelectorAll('audio').length===8");
    for(const width of [1280,390]){
      await command('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:width===390});
      assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
      await evaluate("document.querySelector('.skip').focus()");
      await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});
      await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
      assert.equal(await evaluate("document.activeElement===document.querySelector('main')"),true);
    }
    assert.equal(await evaluate("document.querySelectorAll('iframe,video').length"),0);
    if(report){const files={};for(const name of ['index.html','listening.json','manifest.json',...data.tracks.map(row=>row.audio_path)]){const bytes=await readFile(join(root,name));files[name]={sha256:createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length};const track=data.tracks.find(row=>row.audio_path===name);if(track)assert.equal(files[name].sha256,track.audio_sha256,'browser-tested media bytes match native source metadata');}browserEvidence={revision:'opennoise-permitted-listening-browser-v1',export_root:root,files,tracks:results,checks:{no_initial_audio_fetch:true,no_autoplay:true,all_eight_native_clips_decode_play_pause:true,per_track_attribution:true,keyboard_skip_link:true,mobile_no_overflow:true,all_network_requests_same_origin:true,inline_native_svg_control_icons:requests.filter(row=>row.request.url.startsWith('data:image/svg+xml;base64,')).length},musical_judgments:'none',provider_availability_claim:'none' };}
  });
  // A report is sealed only after all runtime and request-scope checks pass.
  if(report)await writeFile(report,JSON.stringify(browserEvidence,null,2)+'\n');
});
