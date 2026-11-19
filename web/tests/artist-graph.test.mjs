import assert from 'node:assert/strict';
import test from 'node:test';
import { artistNeighbors, artistGraph } from '../src/artist-graph.ts';

const artist = (id, name = id) => ({ id, name });
const detail = (similar) => ({ artist: artist('center'), similar });

test('keeps every immediate neighbor in ranked order, without self-links or duplicates', () => {
  const similar = [
    'center',
    'first',
    'second',
    'first',
    ...Array.from({ length: 20 }, (_, i) => `artist-${i}`),
  ].map((id) => ({ artist: artist(id), score: 0.5 }));
  assert.deepEqual(
    artistNeighbors(detail(similar)).map(({ artist }) => artist.id),
    ['first', 'second', ...Array.from({ length: 20 }, (_, i) => `artist-${i}`)],
  );
  assert.deepEqual(artistNeighbors(detail(null)), []);
});

test('renders a clickable node and a visible edge for each neighbor using plain text', () => {
  class Element {
    children = [];
    attributes = {};
    style = {};
    dataset = {};
    constructor(tag, namespaceURI) {
      this.tag = tag;
      this.namespaceURI = namespaceURI;
    }
    setAttribute(key, value) {
      this.attributes[key] = value;
    }
    append(...nodes) {
      this.children.push(...nodes);
    }
  }
  const oldDocument = globalThis.document;
  globalThis.document = {
    createElement: (tag) => new Element(tag),
    createElementNS: (namespace, tag) => new Element(tag, namespace),
  };
  try {
    const graph = artistGraph(
      detail([
        { artist: artist('one', '<One & two>'), score: 0.8 },
        { artist: artist('two'), score: 0.7 },
      ]),
    );
    const [svg, root, first, second] = graph.children;
    assert.equal(svg.children.length, 2);
    assert.equal(root.textContent, 'center');
    assert.equal(first.textContent, '<One & two>');
    assert.deepEqual(first.dataset, { kind: 'artist', id: 'one' });
    assert.deepEqual(second.dataset, { kind: 'artist', id: 'two' });
    assert.equal(graph.style.height, '240px');
    assert.equal(svg.children[0].attributes.d, 'M50 15 V50 H25');
    assert.equal(svg.children[1].attributes.d, 'M50 15 V50 H75');
    assert.equal(first.style.left, '25%');
    assert.equal(second.style.left, '75%');
    assert.equal(svg.attributes['aria-hidden'], 'true');
    assert.equal(first.attributes['aria-label'], 'Explore <One & two>, similar to center');
  } finally {
    globalThis.document = oldDocument;
  }
});
