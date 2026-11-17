import assert from 'node:assert/strict';
import test from 'node:test';
import { searchMatches } from '../src/search.ts';

test('exact names and aliases outrank prefixes and substrings before the limit', () => {
  const entries = [
    ...Array.from({ length: 12 }, (_, i) => ({ name: `other idm ${i}`, aliases: [] })),
    { name: 'idm artists', aliases: [] },
    { name: 'intelligent dance music', aliases: ['idm', 'other idm'] },
    { name: 'idm', aliases: [] },
    { name: 'another genre', aliases: ['idm prefix'] },
  ];
  const index = entries.map((entry) => ({ entry, terms: [entry.name, ...entry.aliases] }));
  const matches = searchMatches(index, 'idm');
  assert.equal(matches.length, 12);
  assert.deepEqual(matches.slice(0, 4), [entries[13], entries[14], entries[12], entries[15]]);
  assert.deepEqual(matches.slice(4), entries.slice(0, 8));
  assert.equal(matches.filter((entry) => entry === entries[13]).length, 1);
});

test('empty queries, empty indices and unmatched queries return no matches', () => {
  assert.deepEqual(searchMatches([], 'idm'), []);
  assert.deepEqual(searchMatches([{ entry: 'pop', terms: ['pop'] }], ''), []);
  assert.deepEqual(searchMatches([{ entry: 'pop', terms: ['pop'] }], 'idm'), []);
});
