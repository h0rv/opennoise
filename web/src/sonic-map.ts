import type { Genre, Manifest } from './catalog';
import { claimName, isArtistCluster, LabelGrid, priority } from './label-grid';
import { hasShortcutModifier } from './keyboard';

type Camera = { x: number; y: number; scale: number };

export function sonicLabels(
  genres: Genre[],
  width: number,
  measure: (text: string, font: string) => number,
) {
  const items = genres
    .filter((g) => g.positions.axes && !isArtistCluster(g.name))
    .map((genre) => {
      const size = Math.min(
        24,
        Math.max(12, Math.round(10 + Math.log10(Math.max(1, genre.member_count ?? 0)) * 3.5)),
      );
      const font = `${size >= 20 ? 600 : 400} ${size}px Helvetica, Arial, sans-serif`;
      return {
        genre,
        size,
        font,
        width: measure(genre.name, font),
        count: genre.member_count ?? 0,
        id: genre.id,
      };
    })
    .sort((a, b) => priority(a, b, ''));
  const height = Math.max(
    1800,
    Math.ceil(
      (items.reduce((area, item) => area + (item.width + 18) * (item.size + 16), 0) * 1.6) /
        Math.max(1, width),
    ),
  );
  const grid = new LabelGrid();
  const names = new Set<string>();
  const labels = [];
  for (const item of items) {
    if (item.width > width - 32 || !claimName(item.genre.name, names)) continue;
    const point = item.genre.positions.axes!;
    const x = 16 + point.x * (width - item.width - 32);
    for (let attempt = 0; attempt < 161; attempt++) {
      const offset = (attempt % 2 ? 1 : -1) * Math.ceil(attempt / 2) * 12;
      const y = 16 + point.y * (height - item.size * 1.25 - 32) + offset;
      if (y < 8 || y + item.size * 1.25 > height - 8) continue;
      if (
        !grid.place({
          left: x - 6,
          right: x + item.width + 6,
          top: y - 4,
          bottom: y + item.size * 1.25 + 4,
        })
      )
        continue;
      labels.push({
        ...item,
        x,
        y,
        color: `hsl(${Math.round(280 - point.x * 250 + point.y * 50)} 65% 27%)`,
      });
      break;
    }
  }
  return { labels, height };
}

export class SonicMap {
  readonly layout = 'axes';
  private scale = 1;
  private pan = 0;
  private height = 0;
  private width = 0;
  private moved = false;
  private pointer?: { x: number; y: number };
  private selected = '';
  private buttons = new Map<string, HTMLButtonElement>();
  private stage = document.createElement('div');
  private abort = new AbortController();
  private observer: ResizeObserver;

  constructor(
    private element: HTMLElement,
    private genres: Genre[],
    private open: (kind: 'genre', id: string) => void,
    camera?: Camera,
    axes?: Manifest['layouts']['axes'],
  ) {
    element.className = 'sonic-map';
    element.tabIndex = 0;
    element.setAttribute('role', 'region');
    element.setAttribute(
      'aria-label',
      'Map. Scroll to explore; drag to pan. Control plus wheel or plus and minus keys zoom. Enter opens a focused genre.',
    );
    element.append(this.stage);
    if (axes) {
      for (const [edge, text] of Object.entries(axes)) {
        const label = document.createElement('span');
        label.className = `map-axis ${edge.replace('_', '-')}`;
        label.textContent = text;
        element.append(label);
      }
    }
    if (camera) {
      this.scale = camera.scale;
      this.pan = camera.x;
    }
    this.resize();
    window.scrollTo(0, camera?.y || 0);
    const options = { signal: this.abort.signal };
    element.addEventListener(
      'click',
      (event) => {
        if (this.moved && event.detail) {
          this.moved = false;
          event.preventDefault();
          return;
        }
        const id = (event.target as HTMLElement).closest<HTMLButtonElement>('button[data-id]')
          ?.dataset.id;
        if (id) this.open('genre', id);
      },
      options,
    );
    element.addEventListener(
      'wheel',
      (event) => {
        if (!event.ctrlKey) return;
        event.preventDefault();
        this.zoom(Math.exp(-event.deltaY * 0.002), { x: event.clientX, y: event.clientY });
      },
      { ...options, passive: false },
    );
    element.addEventListener(
      'pointerdown',
      (event) => {
        if (event.pointerType === 'touch' || event.button !== 0) return;
        this.pointer = { x: event.clientX, y: event.clientY };
        this.moved = false;
        (event.target as HTMLElement).setPointerCapture(event.pointerId);
      },
      options,
    );
    element.addEventListener(
      'pointermove',
      (event) => {
        if (!this.pointer) return;
        const dx = event.clientX - this.pointer.x,
          dy = event.clientY - this.pointer.y;
        if (Math.abs(dx) + Math.abs(dy) > 4) this.moved = true;
        if (!this.moved) return;
        this.pan += dx;
        window.scrollBy(0, -dy);
        this.pointer = { x: event.clientX, y: event.clientY };
        this.transform();
      },
      options,
    );
    element.addEventListener(
      'pointerup',
      () => {
        this.pointer = undefined;
      },
      options,
    );
    element.addEventListener(
      'pointercancel',
      () => {
        this.pointer = undefined;
        this.moved = true;
      },
      options,
    );
    element.addEventListener(
      'keydown',
      (event) => {
        if (hasShortcutModifier(event)) return;
        if (['+', '=', '-', '0'].includes(event.key)) {
          event.preventDefault();
          if (event.key === '0') this.reset();
          else this.zoom(event.key === '-' ? 1 / 1.3 : 1.3);
        }
      },
      options,
    );
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(element);
  }

  get camera(): Camera {
    return { x: this.pan, y: window.scrollY, scale: this.scale };
  }

  private resize() {
    const width = this.element.clientWidth;
    if (!width || width === this.width) return;
    this.width = width;
    const context = document.createElement('canvas').getContext('2d')!;
    const scene = sonicLabels(this.genres, width, (text, font) => {
      context.font = font;
      return context.measureText(text).width;
    });
    this.height = scene.height;
    this.buttons.clear();
    const fragment = document.createDocumentFragment();
    for (const item of scene.labels.sort((a, b) => a.y - b.y || a.x - b.x)) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = item.genre.name;
      button.dataset.id = item.genre.id;
      button.style.cssText = `left:${item.x}px;top:${item.y}px;font:${item.font};line-height:1.25;color:${item.color}`;
      button.setAttribute('aria-pressed', String(item.genre.id === this.selected));
      this.buttons.set(item.genre.id, button);
      fragment.append(button);
    }
    this.stage.replaceChildren(fragment);
    this.transform();
  }

  private transform() {
    this.element.style.height = `${this.height * this.scale + 64}px`;
    this.stage.style.height = `${this.height}px`;
    this.stage.style.transform = `translateX(${this.pan}px) scale(${this.scale})`;
  }

  zoom(factor: number, point = { x: window.innerWidth / 2, y: window.innerHeight / 2 }) {
    const scale = Math.max(0.5, Math.min(3, this.scale * factor));
    const worldY = (point.y - this.element.getBoundingClientRect().top) / this.scale;
    this.pan = point.x - ((point.x - this.pan) * scale) / this.scale;
    const delta = worldY * (scale - this.scale);
    this.scale = scale;
    this.transform();
    window.scrollBy(0, delta);
  }

  reset() {
    this.scale = 1;
    this.pan = 0;
    this.moved = false;
    this.transform();
    window.scrollTo(0, 0);
  }

  selection(
    id: string,
    _artist?: { id: string; name: string; x: number; y: number },
    reveal = false,
  ) {
    this.buttons.get(this.selected)?.setAttribute('aria-pressed', 'false');
    this.selected = id;
    const button = this.buttons.get(id);
    button?.setAttribute('aria-pressed', 'true');
    if (button && reveal) {
      const rect = button.getBoundingClientRect();
      if (rect.left < 0 || rect.right > window.innerWidth) {
        this.pan += window.innerWidth / 2 - (rect.left + rect.right) / 2;
        this.transform();
      }
      if (rect.top < 0 || rect.bottom > window.innerHeight)
        button.scrollIntoView({ block: 'center', inline: 'center' });
    }
  }

  destroy() {
    this.abort.abort();
    this.observer.disconnect();
  }
}
