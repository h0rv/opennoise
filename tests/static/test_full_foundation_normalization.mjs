import assert from 'node:assert/strict';
import test from 'node:test';
import {normalizeName} from '../../src/opennoise/static/full-foundation-normalization.mjs';
test('native artist prefix normalization retains Unicode casefold and compatibility characters',()=>{
  assert.equal(normalizeName(' Straße '),'strasse');
  assert.equal(normalizeName('Σίσυφος'),'σίσυφοσ');
  assert.equal(normalizeName('Ｆｏｕｒ Tet'),'four tet');
  assert.equal(normalizeName('ﬃ'),'ffi');
  assert.equal(normalizeName('Émilie'),'émilie');
});
