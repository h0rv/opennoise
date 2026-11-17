type Track = { artist: string; title: string; preview: string; link: string };
const normalize = (name: string) => name.normalize('NFKC').toLocaleLowerCase().trim();

export function previewTrack(data: unknown, artist: string): Track | null {
  if (!data || typeof data !== 'object' || !('data' in data) || !Array.isArray(data.data))
    throw new Error('Deezer unavailable');
  for (const track of data.data) {
    if (
      track &&
      typeof track.title === 'string' &&
      typeof track.artist?.name === 'string' &&
      normalize(track.artist.name) === normalize(artist) &&
      typeof track.preview === 'string' &&
      /^https:\/\/[a-z0-9.-]+\.dzcdn\.net\//i.test(track.preview) &&
      typeof track.link === 'string' &&
      /^https:\/\/(www\.)?deezer\.com\/track\/\d+$/i.test(track.link)
    )
      return {
        artist: track.artist.name,
        title: track.title,
        preview: track.preview,
        link: track.link,
      };
  }
  return null;
}

let request = 0;
export function searchPreview(artist: string, signal: AbortSignal): Promise<Track | null> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const callback = `opennoisePreview${++request}`;
    const callbacks = window as unknown as Record<string, (data: unknown) => void>;
    const script = document.createElement('script');
    const cleanup = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      script.remove();
      delete callbacks[callback];
    };
    const fail = (error: unknown) => {
      cleanup();
      reject(error);
    };
    const abort = () => fail(signal.reason);
    const timer = setTimeout(() => fail(new Error('Deezer timed out')), 8000);
    callbacks[callback] = (data) => {
      cleanup();
      try {
        resolve(previewTrack(data, artist));
      } catch (error) {
        reject(error);
      }
    };
    script.onerror = () => fail(new Error('Deezer unavailable'));
    const url = new URL('https://api.deezer.com/search');
    url.search = new URLSearchParams({ q: artist, limit: '10', output: 'jsonp', callback }).toString();
    script.src = url.href;
    signal.addEventListener('abort', abort, { once: true });
    document.head.append(script);
  });
}

export class PreviewPlayer {
  private controller = new AbortController();
  private audio = document.createElement('audio');
  private host: HTMLElement;
  private toggle: HTMLButtonElement;
  private status: HTMLElement;
  private source: HTMLAnchorElement;

  constructor(host: HTMLElement) {
    this.host = host;
    host.innerHTML = `<button type="button" hidden>Play</button><span role="status"></span><a target="_blank" rel="noopener noreferrer" hidden>Deezer · 30s ↗</a><a href="https://developers.deezer.com/termsofuse" target="_blank" rel="noopener noreferrer" title="Non-commercial, private listening only">Terms</a>`;
    this.toggle = host.querySelector('button')!;
    this.status = host.querySelector('span')!;
    this.source = host.querySelector('a')!;
    this.audio.preload = 'none';
    this.toggle.onclick = () => {
      if (this.audio.paused) void this.resume(this.controller.signal);
      else this.audio.pause();
    };
    const update = () => {
      this.toggle.textContent = this.audio.paused ? 'Play' : 'Pause';
    };
    this.audio.onplay = this.audio.onpause = this.audio.onended = update;
    this.audio.onerror = () => {
      if (!this.audio.error) return;
      this.status.textContent = 'Preview unavailable. Click an artist to retry.';
      this.toggle.hidden = true;
    };
  }

  stop() {
    this.controller.abort();
    this.controller = new AbortController();
    this.audio.pause();
    this.audio.removeAttribute('src');
    this.audio.load();
    this.host.hidden = true;
  }

  async play(artists: string[]) {
    this.stop();
    const { signal } = this.controller;
    this.host.hidden = false;
    this.toggle.hidden = this.source.hidden = true;
    this.status.textContent = 'Finding preview…';
    try {
      for (const artist of [...new Set(artists)].slice(0, 3)) {
        const track = await searchPreview(artist, signal);
        if (signal.aborted) return;
        if (!track) continue;
        this.status.textContent = `${track.artist} — ${track.title}`;
        this.source.href = track.link;
        this.source.hidden = this.toggle.hidden = false;
        this.audio.src = track.preview;
        await this.resume(signal);
        return;
      }
      this.status.textContent = 'No preview available.';
    } catch {
      if (!signal.aborted) this.status.textContent = 'Preview unavailable. Click an artist to retry.';
    }
  }

  private async resume(signal: AbortSignal) {
    try {
      await this.audio.play();
    } catch (error) {
      if (signal.aborted) return;
      this.toggle.textContent = 'Play';
      if (!(error instanceof DOMException && error.name === 'NotAllowedError')) {
        this.status.textContent = 'Preview unavailable. Click an artist to retry.';
        this.toggle.hidden = true;
      }
    }
  }
}
