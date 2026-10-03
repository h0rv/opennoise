import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';

const root = process.env.OPENNOISE_FMA_MAP_ROOT;
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const skip = !root || !chromium;
async function browser(operation) {
  const exportRoot = resolve(root);
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(exportRoot, '.' + (path === '/' ? '/index.html' : path));
    if (!file.startsWith(exportRoot + sep)) { response.statusCode = 403; response.end(); return; }
    try { response.setHeader('Content-Type', (file.endsWith('.js') || file.endsWith('.mjs')) ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : 'application/json'); response.end(await readFile(file)); }
    catch { response.statusCode = 404; response.end(); }
  });
  const profile = await mkdtemp(join(tmpdir(), 'opennoise-fma-contract-'));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}/`;
  const child = spawn(chromium, ['--headless=new', '--no-sandbox', '--disable-gpu', '--single-process', '--no-zygote', '--renderer-process-limit=1', '--disable-extensions', '--disable-dev-shm-usage', '--disable-background-networking', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank']);
  let socket;
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
    const evaluate = async expression => { const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true}); if (result.exceptionDetails) throw new Error(result.exceptionDetails.text); return result.result.value; };
    const wait = async expression => { for (let index = 0; index < 400; index++) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 20)); } throw new Error('Timed out: ' + expression); };
    await command('Network.enable'); await command('Runtime.enable'); await command('Emulation.setDeviceMetricsOverride', {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false}); await command('Page.navigate', {url});
    await wait("document.querySelector('#results li') && !document.querySelector('#status').textContent.includes('Loading')");
    await operation({evaluate, wait, command, requests, url});
    assert.deepEqual(errors, []); assert.ok(requests.every(row => new URL(row.request.url).origin === new URL(url).origin && row.type !== 'Media'), 'no external provider or audio requests');
  } finally {
    socket?.close(); child.kill('SIGKILL'); await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('close', resolve)); await rm(profile, {recursive: true, force: true}); await new Promise(resolve => server.close(resolve));
  }
}
test('actual native FMA descriptor map retains all source contexts and mathematical axis limits', {skip, timeout:60000}, async () => {
  const coordinates = JSON.parse(await readFile(join(root, 'coordinates.json')));
  assert.equal(coordinates.pca_training.finite_training_tracks,92270);
  assert.equal(coordinates.denominators.native_artists,16916);
  assert.equal(coordinates.denominators.native_genres,164);
  assert.equal(coordinates.denominators.positioned_genres,158);
  assert.equal(coordinates.artist_genres_inferred,false);
  await browser(async ({evaluate,wait,command}) => {
    assert.match(await evaluate("document.querySelector('#status').textContent"),/164 of 164.*158 positioned, 6 unavailable/);
    assert.equal(await evaluate("document.querySelectorAll('#map circle').length"),158);
    assert.equal(await evaluate("document.querySelectorAll('#results li').length"),100);
    await evaluate("document.querySelector('#next').click()");
    assert.equal(await evaluate("document.querySelectorAll('#results li').length"),64);
    const absent = coordinates.genres.find(row => row.position === null);
    await evaluate(`document.querySelector('#search').value=${JSON.stringify(String(absent.genre_id))};document.querySelector('#search').dispatchEvent(new Event('input',{bubbles:true}))`);
    await evaluate(`Array.from(document.querySelectorAll('#results button')).find(row=>row.textContent.includes(${JSON.stringify(`(FMA ${absent.genre_id})`)})).click()`);
    assert.match(await evaluate("document.querySelector('#selected').textContent"),/Position unavailable/);
    await evaluate("document.querySelector('#search').value='';document.querySelector('#kind').value='artists';document.querySelector('#kind').dispatchEvent(new Event('change',{bubbles:true}))");
    assert.match(await evaluate("document.querySelector('#status').textContent"),/16916 of 16916.*16109 positioned, 807 unavailable/);
    assert.equal(await evaluate("document.querySelectorAll('#map circle').length"),16109);
    const unpositioned = coordinates.artists.find(row => row.position === null);
    await evaluate(`document.querySelector('#search').value=${JSON.stringify(String(unpositioned.artist_id))};document.querySelector('#search').dispatchEvent(new Event('input',{bubbles:true}))`);
    await evaluate(`Array.from(document.querySelectorAll('#results button')).find(row=>row.textContent.includes(${JSON.stringify(`(FMA ${unpositioned.artist_id})`)})).click()`);
    assert.match(await evaluate("document.querySelector('#selected').textContent"),/native FMA artist.*Position unavailable/);
    for (const width of [1280,390]) {
      await command('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:width===390});
      await evaluate("document.querySelector('.skip').focus()");
      await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});
      await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
      assert.equal(await evaluate("document.activeElement === document.querySelector('main')"),true);
      assert.equal(await evaluate("getComputedStyle(document.activeElement).outlineStyle"),'solid');
      assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"),true);
    }
    assert.match(await evaluate("document.body.textContent"),/musical similarity has not been established/);
  });
});
