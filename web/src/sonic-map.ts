import type { Genre } from './catalog';
import { claimName, isArtistCluster, LabelGrid, priority } from './label-grid';

type VisibleArea = { top: number; bottom: number };

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
  private height = 0;
  private width = 0;
  private selected = '';
  private highlighted = new Set<string>();
  private buttons = new Map<string, HTMLButtonElement>();
  private selectedOverlay?: HTMLButtonElement;
  private stage = document.createElement('div');
  private abort = new AbortController();
  private observer: ResizeObserver;

  constructor(
    private element: HTMLElement,
    private genres: Genre[],
    private open: (kind: 'genre', id: string) => void,
    scrollY = 0,
  ) {
    element.className = 'sonic-map';
    element.tabIndex = 0;
    element.setAttribute('role', 'region');
    element.setAttribute('aria-label', 'Map. Scroll to explore. Enter opens a focused genre.');
    element.append(this.stage);
    this.resize();
    window.scrollTo(0, scrollY);
    const options = { signal: this.abort.signal };
    element.addEventListener(
      'click',
      (event) => {
        const id = (event.target as HTMLElement).closest<HTMLButtonElement>('button[data-id]')
          ?.dataset.id;
        if (id) this.open('genre', id);
      },
      options,
    );
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(element);
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
    this.selectedOverlay = undefined;
    this.selection(this.selected);
    this.highlight([...this.highlighted]);
    this.element.style.height = `${this.height + 64}px`;
    this.stage.style.height = `${this.height}px`;
  }

  selection(id: string, visible?: VisibleArea) {
    if (id !== this.selected) {
      this.selectedOverlay?.remove();
      this.selectedOverlay = undefined;
    }
    this.buttons.get(this.selected)?.setAttribute('aria-pressed', 'false');
    this.selected = id;
    const button = this.buttons.get(id) ?? this.selectedOverlay ?? this.showSelectedOverlay(id);
    button?.setAttribute('aria-pressed', 'true');
    if (button && visible) this.reveal([button], visible);
  }

  highlight(ids: string[], visible?: VisibleArea) {
    this.highlighted = new Set(ids);
    for (const [id, button] of this.buttons)
      button.classList.toggle('artist-genre', this.highlighted.has(id));
    const buttons = ids.flatMap((id) => this.buttons.get(id) ?? []);
    this.element.classList.toggle('artist-highlight', buttons.length > 0);
    if (visible) this.reveal(buttons, visible);
  }

  private reveal(buttons: HTMLButtonElement[], visible: VisibleArea) {
    let nearest: DOMRect | undefined;
    let distance = Infinity;
    for (const button of buttons) {
      const rect = button.getBoundingClientRect();
      const next = Math.max(0, visible.top - rect.top, rect.bottom - visible.bottom);
      if (next === 0) return;
      if (next < distance) {
        nearest = rect;
        distance = next;
      }
    }
    if (nearest)
      window.scrollBy(0, (nearest.top + nearest.bottom - visible.top - visible.bottom) / 2);
  }

  private showSelectedOverlay(id: string) {
    if (!id) return;
    const genre = this.genres.find((g) => g.id === id);
    if (!genre?.positions.axes || isArtistCluster(genre.name)) return;
    const { x, y } = genre.positions.axes;
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.id = id;
    button.textContent = genre.name;
    button.className = 'selected-overlay';
    button.style.left = `calc(${x * 100}% + ${16 - 32 * x}px)`;
    button.style.top = `${16 + y * (this.height - 52)}px`;
    button.style.transform = `translateX(${-x * 100}%)`;
    this.stage.append(button);
    this.selectedOverlay = button;
    return button;
  }

  destroy() {
    this.abort.abort();
    this.observer.disconnect();
  }
}
