import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

// Tiny DOM surface keeps pure source-hierarchy coverage tests independent of a browser.
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.classes = new Set(); this.classList = {add: value => this.classes.add(value)}; this.handlers = {}; this.attributes = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  querySelector(selector) { return walk(this).find(node => node.tagName === selector); }
  focus() { this.focused = true; }
}
const source = await readFile(new URL('../../src/opennoise/static/fma-genre-map.js', import.meta.url), 'utf8');
const {renderGenreAtlas} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const walk = node => [node, ...node.children.flatMap(walk)];
const row = (genre_id, parent_id, title, track_count = 0) => ({genre_id, parent_id, title, track_count});

test('genre atlas preserves every identity and direct count, including orphan and cyclic source rows', t => {
  const original = globalThis.document;
  globalThis.document = {createElement: tag => new Element(tag)};
  t.after(() => { globalThis.document = original; });
  const root = new Element('div');
  const rows = [row(1, null, 'Root', 3), row(2, 1, 'Child', 8), row(3, 2, 'Grandchild', 2), row(4, 999, 'Orphan'), row(5, 6, 'Cycle A'), row(6, 5, 'Cycle B'), row(7, 7, 'Self parent'), row(8, null, '<img src=x onerror=alert(1)>')];
  renderGenreAtlas(root, rows);
  const all = walk(root), links = all.filter(node => node.tagName === 'a');
  assert.deepEqual(links.map(node => node.href).sort(), rows.map(row => '#genre=' + row.genre_id).sort());
  assert.equal(links.length, rows.length);
  assert.equal(root.dataset.evidenceRole, 'native_genre_parent_relationships');
  assert.ok(all.some(node => node.textContent === '3 tracks'));
  assert.ok(!all.some(node => node.textContent === '13 tracks'), 'child annotations must not be summed into root');
  assert.ok(all.some(node => node.textContent?.includes('Parent #999 is absent')));
  assert.ok(all.some(node => node.textContent?.includes('contains a cycle')));
  assert.equal(links.find(node => node.href === '#genre=8').textContent, rows[7].title);
  assert.match(root.children[0].textContent, /8 FMA genres/);
});

test('genre atlas accepts Map input, sorts names, and replaces earlier content on empty state', t => {
  const original = globalThis.document;
  globalThis.document = {createElement: tag => new Element(tag)};
  t.after(() => { globalThis.document = original; });
  const root = new Element('div');
  renderGenreAtlas(root, new Map([[2, row(2, null, 'Zulu')], [1, row(1, null, 'Alpha')]]));
  assert.deepEqual(walk(root).filter(node => node.tagName === 'a').map(node => node.textContent), ['Alpha', 'Zulu']);
  renderGenreAtlas(root, []);
  assert.equal(walk(root).filter(node => node.tagName === 'a').length, 0);
  assert.equal(root.children[1].textContent, 'No genre definitions are available.');
});

test('playable filter counts unique directly tagged tracks without inheriting from children', t => {
  const original = globalThis.document;
  globalThis.document = {createElement: tag => new Element(tag)};
  t.after(() => { globalThis.document = original; });
  const root = new Element('div'), updates = [];
  renderGenreAtlas(root, [row(1, null, 'Root'), row(2, 1, 'Child'), row(3, 2, 'Grandchild'), row(4, null, 'Other')], {
    playbackTracks: [{track_id: 20, genre_ids: [2, 2]}, {track_id: 20, genre_ids: [2]}, {track_id: 21, genre_ids: [3]}, {track_id: 22, genre_ids: [999]}],
    onlyWithExcerpts: true,
    onFilterChange: value => updates.push(value),
  });
  const links = walk(root).filter(node => node.tagName === 'a');
  assert.deepEqual(links.filter(node => node.dataset.genreId).map(node => node.dataset.genreId), [1, 2, 3]);
  const listen = links.filter(node => node.className === 'fma-atlas-listen');
  assert.deepEqual(listen.map(node => node.href), ['#listen&genre=2', '#listen&genre=3']);
  assert.ok(listen.every(node => node.textContent === 'Listen · 1 excerpt'));
  assert.ok(!links.some(node => node.href === '#listen&genre=1'), 'parent receives no inherited audio count');
  assert.ok(walk(root).some(node => node.textContent === 'Parent context'));
  assert.match(walk(root).find(node => node.className === 'fma-atlas-status').textContent, /2 of 4 genres with local excerpts/);
  const search = walk(root).find(node => node.className === 'fma-atlas-search');
  search.value = 'Grandchild'; search.handlers.input();
  assert.equal(walk(root).find(node => node.className === 'fma-atlas-search'), search, 'typing retains the same focused input');
  assert.deepEqual(updates.at(-1), {query: 'Grandchild', onlyWithExcerpts: true});
  assert.match(walk(root).find(node => node.className === 'fma-atlas-status').textContent, /1 of 4 genres/);
  search.value = 'no match'; search.handlers.input();
  assert.equal(walk(root).filter(node => node.tagName === 'a').length, 0);
  const clear = walk(root).find(node => node.tagName === 'button'); clear.handlers.click();
  assert.deepEqual(updates.at(-1), {query: '', onlyWithExcerpts: false});
  assert.equal(walk(root).filter(node => node.dataset.genreId).length, 4);
  assert.equal(search.focused, true);
});

test('initial query accepts native ID, and keyboard submit reaches a genre without changing audio state', t => {
  const original = globalThis.document;
  globalThis.document = {createElement: tag => new Element(tag)};
  t.after(() => { globalThis.document = original; });
  const root = new Element('div');
  renderGenreAtlas(root, [row(1, null, 'Alpha'), row(2, null, 'Beta')], {query: '2'});
  assert.deepEqual(walk(root).filter(node => node.dataset.genreId).map(node => node.dataset.genreId), [2]);
  let prevented = false;
  walk(root).find(node => node.tagName === 'form').handlers.submit({preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(walk(root).find(node => node.tagName === 'a').focused, true);
  assert.equal(walk(root).filter(node => node.tagName === 'audio').length, 0);
});
