import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
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
  const child = spawn(chromium, ['--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-background-networking', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank']);
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
    await operation({evaluate, wait, command, requests, url});
    assert.deepEqual(errors, []); assert.ok(requests.every(row => new URL(row.request.url).origin === new URL(url).origin && row.type !== 'Media'), 'no external provider or audio requests');
  } finally {
    socket?.close(); child.kill('SIGKILL'); await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('close', resolve)); await rm(profile, {recursive: true, force: true}); await new Promise(resolve => server.close(resolve));
  }
}

const views = [
  ['foundation', process.env.OPENNOISE_FOUNDATION_STATIC_ROOT],
  ['taxonomy', process.env.OPENNOISE_TAXONOMY_STATIC_ROOT],
  ['fma', process.env.OPENNOISE_FMA_STATIC_ROOT],
];
for (const [view, root] of views) {
  test(`actual ${view} skip link preserves deep links, focus, history and reload on desktop and mobile`, {skip: !root || !chromium, timeout: 60000}, async () => {
    const data = JSON.parse(await readFile(join(root, view === 'fma' ? 'catalog.json' : 'data.json')));
    let routes;
    if (view === 'fma') {
      const artists = JSON.parse(await readFile(join(root, 'artist-index.json'))).artists;
      routes = ['#artist=' + artists.find(row => row[2] > 0)[0], '#genre=' + data.genres.find(row => row.track_count > 0).genre_id];
    } else if (view === 'foundation') {
      routes = ['#artist/' + data.artists[0].artist_mbid, '#genre/' + data.genres[0].genre_id];
    } else {
      routes = ['#genre/' + data.genres[0].genre_id, '#component/' + data.components[0].component_id];
    }
    await browser(root, async ({evaluate, wait, command, requests, url}) => {
      const ready = "document.querySelector('main h1') && !/Loading|unavailable/.test(document.querySelector('main h1').textContent) && document.querySelector('main').getAttribute('aria-busy') !== 'true'";
      const activate = async () => {
        const before = await evaluate("({hash: location.hash, html: document.querySelector('main').innerHTML, history: history.length})");
        const count = requests.length;
        await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r'});
        await command('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
        assert.deepEqual(await evaluate("({hash: location.hash, html: document.querySelector('main').innerHTML, history: history.length})"), before, 'skip does not change route, content or history');
        assert.equal(await evaluate("document.activeElement === document.querySelector('main')"), true);
        assert.equal(await evaluate("getComputedStyle(document.activeElement).outlineStyle"), 'solid');
        assert.ok(await evaluate("parseFloat(getComputedStyle(document.activeElement).outlineWidth) >= 3"));
        assert.equal(requests.length, count, 'skip does not reload catalog files');
        await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9});
        await command('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9});
        assert.equal(await evaluate("document.querySelector('main').contains(document.activeElement)"), true, 'keyboard continues in catalog');
      };
      for (const width of [1280, 390]) {
        await command('Emulation.setDeviceMetricsOverride', {width, height: 844, deviceScaleFactor: 1, mobile: width === 390});
        await command('Page.navigate', {url: url + '?keyboard=' + width}); await wait(ready + ' && location.search === ' + JSON.stringify('?keyboard=' + width));
        await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9});
        await command('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9});
        assert.equal(await evaluate("document.activeElement.matches('.skip')"), true, 'skip is the first keyboard control');
        assert.ok(await evaluate("document.activeElement.getBoundingClientRect().left >= 0"), 'focused skip is visible');
        await activate();
        await evaluate('location.hash = ' + JSON.stringify(routes[0])); await wait(ready + ' && location.hash === ' + JSON.stringify(routes[0]));
        await evaluate("document.querySelector('.skip').focus()"); await activate();
        await evaluate('location.hash = ' + JSON.stringify(routes[1])); await wait(ready + ' && location.hash === ' + JSON.stringify(routes[1]));
        await evaluate("document.querySelector('.skip').focus()"); await activate();
        await evaluate('history.back()'); await wait(ready + ' && location.hash === ' + JSON.stringify(routes[0]));
        await evaluate('history.forward()'); await wait(ready + ' && location.hash === ' + JSON.stringify(routes[1]));
        await evaluate('history.back()'); await wait(ready + ' && location.hash === ' + JSON.stringify(routes[0]));
        await command('Page.reload'); await wait(ready + ' && location.hash === ' + JSON.stringify(routes[0]));
        await evaluate("document.querySelector('.skip').focus()"); await activate();
        assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, 'no mobile overflow');
      }
    });
  });
}
