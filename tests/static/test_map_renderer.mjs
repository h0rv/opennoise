import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { mkdtemp, rm } from 'node:fs/promises';
import test from 'node:test';

const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome'].find(existsSync);
const atlas = {
  initial_camera: { x0: 0, y0: 0, x1: 10, y1: 10 },
  browse_landmarks: [{ root_id: 'jazz', label: 'jazz', x: 2, y: 2, member_count: 2 }],
  nodes: [{ id: 'jazz', name: 'jazz', x: 2, y: 2 }, { id: 'folk', name: 'folk', x: 4, y: 4 }],
};
const membership = (node_id) => ({ node_id, catalog_genre_name: node_id });
const discovery = {
  revision: 'static-direct-discovery-v2', availability: 'ready',
  genres: [{ node_id: 'jazz', artist_ids: ['a', 'b'] }],
  artists: [
    { artist_id: 'a', name: 'Alpha', memberships: [membership('jazz'), membership('folk')], shared_genre_artists: [{ artist_id: 'b', shared_genre_ids: ['jazz'], shared_genre_count: 1 }] },
    { artist_id: 'b', name: 'Beta', memberships: [membership('jazz')], shared_genre_artists: [] },
  ],
};

function page(scenario) {
  return `<!doctype html><html><body>
    <canvas id="semantic-map" width="800" height="600" data-map-url="/atlas.json" ${scenario === 'missing' ? '' : 'data-discovery-url="/discovery.json"'}></canvas>
    <div id="map-controls"><button data-map-action="back">Back</button></div>
    <aside id="overview-guide" hidden><p id="atlas-coverage"></p><details id="overview-families"><div id="overview-family-list"></div></details></aside><aside id="map-detail"></aside><form id="search"><input id="query"><div id="search-results"></div><p id="search-status" hidden></p></form>
    <pre id="result">pending</pre>
    <script type="module">
      const scenario = ${JSON.stringify(scenario)};
      const fixture = ${JSON.stringify(discovery)};
      const originalFetch = window.fetch;
      let release;
      const pending = new Promise((resolve, reject) => { release = (value) => value instanceof Error ? reject(value) : resolve(value); });
      window.fetch = (url, options) => String(url).endsWith('/discovery.json') ? pending : originalFetch(url, options);
      const waitFor = async (predicate) => { for (let i = 0; i < 200; i++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 10)); } throw new Error('Timed out: ' + document.querySelector('#map-detail').textContent); };
      try {
        await import('/map-renderer.js');
        const panel = document.querySelector('#map-detail');
        await waitFor(() => panel.textContent.includes('Artists in this genre'));
        const loading = panel.textContent;
        if (scenario === 'collapsed-loading') panel.querySelector('[data-map-action="toggle-detail"]').click();
        if (scenario === 'network') release(new Error('network unavailable'));
        else if (scenario === 'invalid-json') release({ ok: true, json: async () => { throw new Error('invalid JSON'); } });
        else {
          if (scenario === 'unsupported') fixture.revision = 'future-revision';
          if (scenario === 'unavailable') fixture.availability = 'unavailable';
          if (scenario === 'empty') { fixture.genres = []; fixture.artists = []; }
          release({ ok: scenario !== 'http', json: async () => fixture });
        }
        await waitFor(() => !panel.textContent.includes('Loading direct artist observations'));
        const settled = panel.textContent;
        const collapsedAfterLoad = panel.classList.contains('is-collapsed');
        const collapseControlAfterLoad = panel.querySelector('[data-map-action="toggle-detail"]')?.getAttribute('aria-expanded');
        const artistUrl = new URL(location.href).searchParams.get('open_artist');
        const query = document.querySelector('#query'); query.value = 'Alpha'; query.dispatchEvent(new Event('input'));
        const search = document.querySelector('#search-results').textContent;
        const firstResult = document.querySelector('[data-search-match]');
        firstResult?.focus();
        firstResult?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        const searchDismissed = document.querySelector('#search-results').hidden;

        let peer = null, genre = null, restoredArtistUrl = null, interaction = null;
        if (scenario === 'ready' || scenario === 'collapsed-loading') {
          document.querySelector('[data-open-similar-artist-id="b"]').click();
          peer = { title: panel.querySelector('h2').textContent, artist: new URL(location.href).searchParams.get('open_artist'), focus: new URL(location.href).searchParams.get('open_focus') };
          panel.querySelector('[data-open-node-id="jazz"]').click();
          genre = { text: panel.textContent, artist: new URL(location.href).searchParams.get('open_artist') };
          panel.querySelector('[data-map-action="toggle-detail"]').click();
          const collapsed = panel.classList.contains('is-collapsed');
          const expanded = panel.querySelector('[data-map-action="toggle-detail"]').getAttribute('aria-expanded');
          panel.querySelector('[data-map-action="toggle-detail"]').click();
          query.value = 'zzzz-no-match'; query.dispatchEvent(new Event('input'));
          const noMatch = document.querySelector('#search-status').textContent;
          panel.querySelector('[data-map-action="close-detail"]').click();
          const browseLabel = document.querySelector('#overview-family-list').textContent;
          document.querySelector('[data-browse-node-id]').click();
          interaction = { browseLabel, collapsed, expanded, restored: !panel.classList.contains('is-collapsed'), noMatch, hidden: panel.hidden, focus: new URL(location.href).searchParams.get('open_focus') };

        }
        if (scenario !== 'ready' && scenario !== 'collapsed-loading') {
          history.pushState({}, '', '?open_focus=jazz&open_artist=a');
          window.dispatchEvent(new PopStateEvent('popstate'));
          restoredArtistUrl = new URL(location.href).searchParams.get('open_artist');
        }
        document.querySelector('#result').textContent = JSON.stringify({ loading, settled, artistUrl, search, peer, genre, restoredArtistUrl, interaction, searchDismissed, collapsedAfterLoad, collapseControlAfterLoad });
      } catch (error) { document.querySelector('#result').textContent = JSON.stringify({ error: String(error) }); }
    </script></body></html>`;
}

async function capture(url) {
  const profile = await mkdtemp(join(tmpdir(), 'opennoise-renderer-'));
  const child = spawn(chromium, ['--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-background-networking', '--disable-default-apps', '--no-first-run', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank']);
  let socket;
  try {
    const endpoint = await new Promise((resolve, reject) => {
      let stderr = '';
      const timeout = setTimeout(() => reject(new Error('Chromium did not expose DevTools')), 10_000);
      child.on('error', error => { clearTimeout(timeout); reject(error); });
      child.stderr.on('data', data => {
        stderr += data;
        const match = stderr.match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\//);
        if (match) { clearTimeout(timeout); resolve(`http://127.0.0.1:${match[1]}`); }
      });
    });
    const target = await fetch(`${endpoint}/json/new?about:blank`, { method: 'PUT' }).then(response => response.json());
    socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }); });
    let sequence = 0;
    const pending = new Map();
    socket.addEventListener('message', ({ data }) => {
      const message = JSON.parse(data);
      const callback = pending.get(message.id);
      if (callback) { pending.delete(message.id); callback(message); }
    });
    const command = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++sequence;
      const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`Timed out: ${method}`)); }, 10_000);
      pending.set(id, message => { clearTimeout(timeout); message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result); });
      socket.send(JSON.stringify({ id, method, params }));
    });
    await command('Page.navigate', { url });
    for (let attempt = 0; attempt < 200; attempt++) {
      const result = await command('Runtime.evaluate', { expression: "document.querySelector('#result')?.textContent", returnByValue: true });
      const value = result.result?.value;
      if (value && value !== 'pending') return JSON.parse(value);
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw new Error('Renderer fixture did not complete');
  } finally {
    socket?.close();
    child.kill('SIGKILL');
    await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('close', resolve));
    await rm(profile, { recursive: true, force: true });
  }
}

test('renderer distinguishes discovery loading, failed assets, absent observations, and direct traversal', { skip: !chromium || !existsSync(chromium) ? 'requires Chromium; set CHROMIUM_PATH to its executable' : false, timeout: 120_000 }, async (t) => {
  const server = createServer(async (request, response) => {
    const url = new URL(request.url, 'http://localhost');
    if (url.pathname === '/atlas.json') { response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(atlas)); }
    else if (url.pathname === '/map-renderer.js' || url.pathname === '/map-atlas.mjs') {
      response.setHeader('Content-Type', 'text/javascript');
      response.end(await readFile(new URL(`../../src/opennoise/static${url.pathname}`, import.meta.url)));
    } else { response.setHeader('Content-Type', 'text/html'); response.end(page(url.searchParams.get('scenario'))); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    for (const scenario of ['network', 'http', 'invalid-json', 'unsupported', 'unavailable', 'missing', 'empty', 'ready', 'collapsed-loading']) {
      await t.test(scenario, async () => {
        const result = await capture(`${base}/?scenario=${scenario}&open_focus=jazz&open_artist=a`);
        assert.equal(result.error, undefined);
        if (scenario !== 'missing') assert.match(result.loading, /Loading direct artist observations/);
        if (scenario === 'ready' || scenario === 'collapsed-loading') {
          assert.equal(result.collapsedAfterLoad, scenario === 'collapsed-loading', 'discovery settlement must preserve the user\'s collapsed panel');
          assert.equal(result.collapseControlAfterLoad, scenario === 'collapsed-loading' ? 'false' : 'true');
          assert.match(result.settled, /Alpha/);
          assert.equal(result.artistUrl, 'a');
          assert.match(result.search, /Alpha/);
          assert.equal(result.searchDismissed, true, 'Escape from a result must keep results closed when focus returns to input');
          assert.deepEqual(result.peer, { title: 'Beta', artist: 'b', focus: 'jazz' });
          assert.match(result.genre.text, /Artists in this genre/);
          assert.equal(result.genre.artist, null);
          assert.deepEqual(result.interaction, { browseLabel: 'jazz2 labels', collapsed: true, expanded: 'false', restored: true, noMatch: 'No matches. Try another genre or artist name.', hidden: true, focus: null });
        } else {
          assert.equal(result.artistUrl, null);
          assert.equal(result.restoredArtistUrl, null, 'unavailable discovery must reject artist IDs restored through history');
          assert.equal(result.search, '');
          assert.match(result.settled, scenario === 'empty' ? /No direct catalog observations for this map label/ : /Direct artist observations are unavailable/);
          assert.doesNotMatch(result.settled, /Alpha|Beta/);
        }
      });
    }
  } finally { await new Promise(resolve => server.close(resolve)); }
});
