import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

// Tiny DOM surface keeps pure source-hierarchy coverage tests independent of a browser.
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.classes = new Set(); this.classList = {add: value => this.classes.add(value)}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
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
