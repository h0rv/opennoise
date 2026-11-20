import assert from 'node:assert/strict';
import test from 'node:test';
import { similarPriority } from '../src/ranking.ts';

test('similarity prior handles missing listeners and favors less familiar artists', () => {
  assert.equal(similarPriority(0.8, null), 0.8);
  assert.equal(similarPriority(0.8, 0), 0.8);
  assert.equal(similarPriority(0.8, 10000), 0.8 / 10000 ** 0.1);
  assert(similarPriority(0.8, 10) > similarPriority(0.8, 10000));
});
