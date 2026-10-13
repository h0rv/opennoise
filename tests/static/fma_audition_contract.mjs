import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const skip = !chromium || !process.env.OPENNOISE_FMA_AUDITION_SLOT;
async function browser(operation, options = {}) {
  const root = resolve(process.env.OPENNOISE_FMA_AUDITION_SLOT);
  const profile = resolve(await mkdtemp(join(tmpdir(), 'opennoise-genuine-playback-')));
  const held = [];
  const release = () => { for (const resolve of held.splice(0)) resolve(); };
  const requests = [], errors = []; let failAudio = false, socket, child;
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(root, '.' + path);
    if (!file.startsWith(root + sep) || (failAudio && path.endsWith('.mp3'))) { response.statusCode = 404; response.end(); return; }
    try {
      let body = await readFile(file);
      if (path.endsWith('/playable-neighbors/manifest.json')) {
        if (options.missing) throw Error('Fixture missing pack');
        if (options.hold) await new Promise(resolve=>held.push(resolve));
        if (options.mutate) { const value=JSON.parse(body); options.mutate(value); body=Buffer.from(JSON.stringify(value)); }
      }
      response.setHeader('Content-Type', file.endsWith('.mp3') ? 'audio/mpeg' : file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : 'application/json');
      response.setHeader('Cache-Control', 'no-store'); response.setHeader('Content-Length', body.length); response.end(body);
    } catch { response.statusCode = 404; response.end(); }
  });
  try {
    const externalOrigin = process.env.OPENNOISE_FMA_AUDITION_ORIGIN;
    if (externalOrigin && !/^http:\/\/127\.0\.0\.1:\d+$/.test(externalOrigin)) throw Error('External genuine test origin must be localhost.');
    if (!externalOrigin) await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const origin = externalOrigin ?? `http://127.0.0.1:${server.address().port}`;
    child = spawn(chromium, ['--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-background-networking', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank']);
    const endpoint = await new Promise((resolve, reject) => {
      let output = ''; const timer = setTimeout(() => reject(new Error('Chromium startup timed out')), 10000);
      child.on('error', reject); child.stderr.on('data', bytes => { output += bytes; const match = output.match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\//); if (match) { clearTimeout(timer); resolve(`http://127.0.0.1:${match[1]}`); } });
    });
    const target = await fetch(`${endpoint}/json/new?about:blank`, {method: 'PUT'}).then(response => response.json());
    socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, {once: true}); socket.addEventListener('error', reject, {once: true}); });
    let sequence = 0; const pending = new Map();
    socket.addEventListener('message', ({data}) => { const result = JSON.parse(data); if (result.method === 'Network.requestWillBeSent') requests.push(result.params); if (result.method === 'Runtime.exceptionThrown') errors.push(result.params.exceptionDetails); pending.get(result.id)?.(result); });
    const command = (method, params = {}) => new Promise((resolve, reject) => { const id = ++sequence, timer = setTimeout(() => reject(new Error(`${method} timed out`)), 10000); pending.set(id, result => { clearTimeout(timer); pending.delete(id); result.error ? reject(new Error(JSON.stringify(result.error))) : resolve(result.result); }); socket.send(JSON.stringify({id, method, params})); });
    const evaluate = async expression => { const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true, userGesture: true}); if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails)); return result.result.value; };
    const wait = async expression => { for (let i = 0; i < 400; i++) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 20)); } throw new Error(`Timed out: ${expression}`); };
    await command('Network.enable'); await command('Runtime.enable'); await command('Emulation.setDeviceMetricsOverride', {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false});
    await command('Page.navigate', {url: `${origin}/index.html`});
    await wait("document.querySelector('#save')?.disabled === false");
    assert.ok(!requests.some(row => /\/audio\//.test(row.request.url)), 'landing does not fetch audio or its manifest');
    await operation({evaluate, wait, command, requests, release, failAudio: value => { failAudio = value; }});
    assert.deepEqual(errors, []);
    assert.ok(requests.every(row => new URL(row.request.url).origin === origin || (row.type === 'Image' && row.request.url.startsWith('data:image/'))), 'network requests stay local; native controls may use embedded image icons');
  } finally {
    release();
    socket?.close(); if (child) { child.kill('SIGKILL'); await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('close', resolve)); }
    if (server.listening) await new Promise(resolve => server.close(resolve));
    await rm(profile, {recursive: true, force: true});
  }
}

test('real audition slot plays locally and downloads genuinely blank responses', {skip,timeout:60000}, async()=>{
  await browser(async ({evaluate,wait,command})=>{
    assert.equal(await evaluate("document.querySelectorAll('article').length"),24);
    assert.ok(await evaluate("[...document.querySelectorAll('select,textarea')].every(n=>n.value==='')"));
    await command('Browser.setDownloadBehavior',{behavior:'deny'});
    await evaluate("{const original=URL.createObjectURL;URL.createObjectURL=blob=>{window.answerBlob=blob;return original(blob)};document.querySelector('#save').click()}");
    const answers=JSON.parse(await evaluate('window.answerBlob.text()'));
    assert.equal(answers.responses.length,24);
    for(const row of answers.responses) for(const [k,v] of Object.entries(row)) if(!['item_id','reviewer_slot'].includes(k)) assert.equal(v,'');
    await evaluate("document.querySelectorAll('audio')[0].play()");
    await wait("document.querySelectorAll('audio')[0].currentTime>.1&&!document.querySelectorAll('audio')[0].paused");
    await evaluate("document.querySelectorAll('audio')[1].play()");
    await wait("document.querySelectorAll('audio')[1].currentTime>.1&&!document.querySelectorAll('audio')[1].paused");
    assert.ok(await evaluate("document.querySelectorAll('audio')[0].paused"));
    await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
    assert.ok(await evaluate('document.documentElement.scrollWidth<=innerWidth'));
  });
});
