import assert from 'node:assert/strict';
import test from 'node:test';
import { searchMatches } from '../src/search.ts';

test('exact names outrank aliases, prefixes and substrings before the limit', () => {
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
  assert.deepEqual(matches.slice(0, 4), [entries[14], entries[13], entries[12], entries[15]]);
  assert.deepEqual(matches.slice(4), entries.slice(0, 8));
  assert.equal(matches.filter((entry) => entry === entries[13]).length, 1);
});

test('exact names remain first when more than twelve old aliases match', () => {
  const entries = [
    ...Array.from({ length: 15 }, (_, i) => ({
      name: `rapping · artist ${i}`,
      aliases: ['pop music'],
    })),
    { name: 'pop music', aliases: [] },
  ];
  const index = entries.map((entry) => ({ entry, terms: [entry.name, ...entry.aliases] }));
  assert.deepEqual(searchMatches(index, 'pop music'), [entries[15], ...entries.slice(0, 11)]);
});

test('top-level exact aliases outrank child aliases but not exact names', () => {
  const entries = [
    ...Array.from({ length: 15 }, (_, i) => ({
      name: `child ${i}`,
      aliases: ['idm'],
      parent_id: 'parent',
    })),
    { name: 'intelligent dance music', aliases: ['idm'], parent_id: null },
    { name: 'idm', aliases: [], parent_id: 'parent' },
  ];
  const index = entries.map((entry) => ({
    entry,
    terms: [entry.name, ...entry.aliases],
    topLevel: entry.parent_id === null,
  }));
  assert.deepEqual(searchMatches(index, 'idm'), [
    entries[16],
    entries[15],
    ...entries.slice(0, 10),
  ]);
});

test('empty queries, empty indices and unmatched queries return no matches', () => {
  assert.deepEqual(searchMatches([], 'idm'), []);
  assert.deepEqual(searchMatches([{ entry: 'pop', terms: ['pop'] }], ''), []);
  assert.deepEqual(searchMatches([{ entry: 'pop', terms: ['pop'] }], 'idm'), []);
});
