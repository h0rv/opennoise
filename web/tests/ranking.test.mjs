import assert from 'node:assert/strict';
import test from 'node:test';
import { genrePriority, artistGenres, similarPriority } from '../src/ranking.ts';

test('genre prior favors pop over a tiny high-score genre without mutating memberships', () => {
  const genres = new Map([
    ['pop', { member_count: 11589 }],
    ['bedroom', { member_count: 690 }],
  ]);
  const data = {
    genres: [
      { id: 'bedroom', score: 1 },
      { id: 'pop', score: 0.605 },
    ],
  };
  assert.equal(artistGenres(data, genres)[0].id, 'pop');
  assert.equal(data.genres[0].id, 'bedroom');
  assert(genrePriority(1, 10000) > genrePriority(1, 1000000));
  assert.deepEqual(artistGenres({ genres: null }, genres), []);
  assert.equal(genrePriority(1, 0), 0);
  assert.deepEqual(
    artistGenres(
      {
        genres: [
          { id: 'z', score: 1 },
          { id: 'a', score: 1 },
        ],
      },
      new Map(),
    ).map((g) => g.id),
    ['a', 'z'],
  );
});

test('similarity prior handles missing listeners and favors less familiar artists', () => {
  assert.equal(similarPriority(0.8, null), 0.8);
  assert.equal(similarPriority(0.8, 0), 0.8);
  assert.equal(similarPriority(0.8, 10000), 0.8 / 10000 ** 0.1);
  assert(similarPriority(0.8, 10) > similarPriority(0.8, 10000));
});
