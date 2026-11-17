import assert from 'node:assert/strict';
import test from 'node:test';
import { PreviewPlayer, previewTrack, searchPreview } from '../src/preview.ts';

const track = (artist = 'Aphex Twin') => ({
  title: 'Avril 14th',
  artist: { name: artist },
  preview: 'https://cdnt-preview.dzcdn.net/preview.mp3',
  link: 'https://www.deezer.com/track/29377601',
});

function browser(t) {
  const scripts = [];
  const audio = {
    paused: true,
    src: '',
    error: null,
    play() {
      this.paused = false;
      this.onplay?.();
      return Promise.resolve();
    },
    pause() {
      this.paused = true;
      this.onpause?.();
    },
    removeAttribute() {
      this.src = '';
    },
    load() {},
  };
  const nodes = { button: {}, span: {}, a: {} };
  const host = { hidden: true, querySelector: (tag) => nodes[tag] };
  t.mock.method(globalThis, 'setTimeout', () => 1);
  t.mock.method(globalThis, 'clearTimeout', () => {});
  globalThis.window = {};
  globalThis.document = {
    createElement: (tag) =>
      tag === 'audio'
        ? audio
        : { remove() { this.removed = true; } },
    head: { append: (script) => scripts.push(script) },
  };
  t.after(() => {
    delete globalThis.window;
    delete globalThis.document;
  });
  const reply = (data, script = scripts.at(-1)) => {
    const key = new URL(script.src).searchParams.get('callback');
    window[key](data);
  };
  return { scripts, audio, nodes, host, reply };
}

test('only matches the requested artist and accepts Deezer media and track URLs', () => {
  const result = previewTrack({ data: [track('Someone else'), track()] }, ' APHEX TWIN ');
  assert.equal(result.title, 'Avril 14th');
  assert.equal(previewTrack({ data: [track('Aphex Twin tribute')] }, 'Aphex Twin'), null);
  for (const preview of ['', 'http://cdnt-preview.dzcdn.net/x', 'https://evil.com?x=.dzcdn.net/x'])
    assert.equal(previewTrack({ data: [{ ...track(), preview }] }, 'Aphex Twin'), null);
  assert.equal(previewTrack({ data: [{ ...track(), link: 'javascript:alert(1)' }] }, 'Aphex Twin'), null);
  assert.throws(() => previewTrack({ error: { code: 4 } }, 'Aphex Twin'));
  assert.equal(previewTrack({ data: [] }, 'Aphex Twin'), null);
});

test('JSONP is lazy, encodes artist names, and cleans up after success', async (t) => {
  const { scripts, reply } = browser(t);
  assert.equal(scripts.length, 0);
  const pending = searchPreview('AC/DC & friends', new AbortController().signal);
  const url = new URL(scripts[0].src);
  assert.equal(url.origin, 'https://api.deezer.com');
  assert.equal(url.searchParams.get('q'), 'AC/DC & friends');
  assert.equal(url.searchParams.get('output'), 'jsonp');
  reply({ data: [] });
  assert.equal(await pending, null);
  assert.equal(scripts[0].removed, true);
  assert.equal(Object.keys(window).length, 0);
});

test('JSONP abort, network errors, and API errors reject and clean up', async (t) => {
  const { scripts, reply } = browser(t);
  const controller = new AbortController();
  const pending = searchPreview('A', controller.signal);
  controller.abort();
  await assert.rejects(pending, { name: 'AbortError' });
  const network = searchPreview('B', new AbortController().signal);
  scripts.at(-1).onerror();
  await assert.rejects(network, /unavailable/);
  const api = searchPreview('C', new AbortController().signal);
  reply({ error: { code: 4 } });
  await assert.rejects(api, /unavailable/);
  assert.ok(scripts.every((script) => script.removed));
  assert.equal(Object.keys(window).length, 0);
});

test('genre fallback plays the next member and pause/resume controls the single audio', async (t) => {
  const { scripts, audio, nodes, host, reply } = browser(t);
  const player = new PreviewPlayer(host);
  assert.equal(scripts.length, 0);
  const pending = player.play(['Missing', 'Aphex Twin']);
  reply({ data: [] });
  await Promise.resolve();
  assert.equal(scripts.length, 2);
  reply({ data: [track()] });
  await pending;
  assert.equal(audio.paused, false);
  assert.equal(nodes.button.textContent, 'Pause');
  assert.equal(nodes.span.textContent, 'Aphex Twin — Avril 14th');
  assert.equal(nodes.a.href, track().link);
  nodes.button.onclick();
  assert.equal(audio.paused, true);
  nodes.button.onclick();
  assert.equal(audio.paused, false);
  player.stop();
  assert.equal(audio.src, '');
  assert.equal(host.hidden, true);
});

test('a newer click cancels pending lookups and stops the old track', async (t) => {
  const { scripts, audio, nodes, reply } = browser(t);
  const player = new PreviewPlayer(browserHost());
  function browserHost() {
    return { hidden: true, querySelector: (tag) => nodes[tag] };
  }
  const old = player.play(['Old artist']);
  const latest = player.play(['Aphex Twin']);
  assert.equal(scripts[0].removed, true);
  reply({ data: [track()] });
  await Promise.all([old, latest]);
  assert.equal(nodes.span.textContent, 'Aphex Twin — Avril 14th');
  assert.equal(audio.paused, false);
  const next = player.play([]);
  assert.equal(audio.paused, true);
  await next;
  assert.equal(nodes.span.textContent, 'No preview available.');
});

test('blocked autoplay leaves a working Play button, while media failures are visible', async (t) => {
  const { audio, nodes, host, reply } = browser(t);
  audio.play = () => Promise.reject(new DOMException('Gesture required', 'NotAllowedError'));
  const player = new PreviewPlayer(host);
  const pending = player.play(['Aphex Twin']);
  reply({ data: [track()] });
  await pending;
  assert.equal(nodes.button.hidden, false);
  assert.equal(nodes.button.textContent, 'Play');
  audio.error = { code: 2 };
  audio.onerror();
  assert.equal(nodes.button.hidden, true);
  assert.match(nodes.span.textContent, /unavailable/);
});
