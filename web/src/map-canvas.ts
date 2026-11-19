import type { Genre } from './catalog';
import { hasShortcutModifier } from './keyboard';
import {
  LabelGrid,
  baseName,
  claimName,
  labelBox,
  priority,
  visibleDepth,
  type Box,
} from './label-grid';

type Camera = { x: number; y: number; scale: number };
const MAX_ZOOM = 256;
type Item = {
  id: string;
  name: string;
  label: string;
  x: number;
  y: number;
  count: number;
  depth: number;
  width: number;
  fullWidth: number;
  size: number;
  font: string;
  kind: 'genre' | 'artist';
  order: number;
};
type Label = { item: Item; box: Box; x: number; y: number };
type Scene = { items: Map<string, Item>; points: Map<string, Item[]> };
const scenes = new WeakMap<Genre[], Scene>();

export class MapCanvas {
  camera: Camera = { x: 0, y: 0, scale: 1 };
  home: Camera = { ...this.camera };
  labels: Label[] = [];
  private points = new Map<string, Item[]>();
  private items = new Map<string, Item>();
  private selected = '';
  private artist?: Item;
  private frame = 0;
  private width = 0;
  private height = 0;
  private wheel = 0;
  private wheelPoint = { x: 0, y: 0 };
  private pointers = new Map<number, { x: number; y: number }>();
  private moved = false;
  private movement = 0;
  private frames = 0;
  private focusIndex = -1;
  private observer: ResizeObserver;
  private context: CanvasRenderingContext2D;
  private abort = new AbortController();

  constructor(
    readonly element: HTMLCanvasElement,
    genres: Genre[],
    readonly layout: 'islands',
    private open: (kind: 'genre' | 'artist', id: string) => void,
    camera?: Camera,
  ) {
    this.context = element.getContext('2d')!;
    const scene = scenes.get(genres);
    if (scene) {
      this.items = scene.items;
      this.points = scene.points;
    } else {
      const byId = new Map(genres.map((g) => [g.id, g]));
      for (const genre of genres) {
        const point = genre.positions[layout];
        if (!point) continue;
        let depth = 0,
          parent = genre.parent_id;
        const seen = new Set<string>();
        while (parent && byId.has(parent) && !seen.has(parent)) {
          seen.add(parent);
          depth++;
          parent = byId.get(parent)!.parent_id;
        }
        const size = Math.min(
          16,
          13 + Math.floor(Math.log10(Math.max(1, genre.member_count ?? 0))),
        );
        const font = `${depth ? '400' : '600'} ${size}px Helvetica, Arial, sans-serif`;
        this.context.font = font;
        const label = baseName(genre.name);
        const item: Item = {
          id: genre.id,
          name: genre.name,
          label,
          x: 90 + point.x * 820,
          y: 65 + point.y * 440,
          count: genre.member_count ?? 0,
          depth,
          width: this.context.measureText(label).width,
          fullWidth: this.context.measureText(genre.name).width,
          size,
          font,
          kind: 'genre',
          order: 0,
        };
        this.items.set(item.id, item);
        const key = `${Math.floor(item.x / 16)}:${Math.floor(item.y / 16)}`;
        const cell = this.points.get(key);
        if (cell) cell.push(item);
        else this.points.set(key, [item]);
      }
      [...this.items.values()]
        .sort((a, b) => priority(a, b, ''))
        .forEach((item, order) => {
          item.order = order;
        });
      scenes.set(genres, { items: this.items, points: this.points });
    }
    this.resize();
    if (camera) {
      this.camera = { ...camera };
      this.zoom(1);
    }
    const options = { signal: this.abort.signal };
    element.addEventListener(
      'dblclick',
      (event) => {
        event.preventDefault();
        const rect = element.getBoundingClientRect();
        this.zoom(1.7, { x: event.clientX - rect.left, y: event.clientY - rect.top });
      },
      options,
    );
    element.addEventListener(
      'wheel',
      (event) => {
        event.preventDefault();
        const rect = element.getBoundingClientRect();
        this.wheel +=
          (event.deltaY || event.deltaX) *
          (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? this.height : 1);
        this.wheelPoint = { x: event.clientX - rect.left, y: event.clientY - rect.top };
        this.redraw();
      },
      { ...options, passive: false },
    );
    element.addEventListener(
      'pointerdown',
      (event) => {
        element.focus({ preventScroll: true });
        element.setPointerCapture(event.pointerId);
        this.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
        this.moved = false;
        this.movement = 0;
      },
      options,
    );
    element.addEventListener(
      'pointermove',
      (event) => {
        const previous = this.pointers.get(event.pointerId);
        if (!previous) {
          const rect = element.getBoundingClientRect();
          const item = this.hit(event.clientX - rect.left, event.clientY - rect.top);
          element.style.cursor = item ? 'pointer' : 'grab';
          element.title = item?.name || '';
          return;
        }
        const other = [...this.pointers].find(([id]) => id !== event.pointerId)?.[1];
        if (other) {
          const oldDistance = Math.hypot(previous.x - other.x, previous.y - other.y);
          const distance = Math.hypot(event.clientX - other.x, event.clientY - other.y);
          const rect = element.getBoundingClientRect();
          if (oldDistance > 0)
            this.zoom(distance / oldDistance, {
              x: (event.clientX + other.x) / 2 - rect.left,
              y: (event.clientY + other.y) / 2 - rect.top,
            });
          this.moved = true;
        } else {
          const dx = event.clientX - previous.x,
            dy = event.clientY - previous.y;
          this.movement += Math.abs(dx) + Math.abs(dy);
          if (this.movement > 4) this.moved = true;
          this.camera.x += dx;
          this.camera.y += dy;
        }
        this.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
        this.redraw();
      },
      options,
    );
    element.addEventListener(
      'pointerup',
      (event) => this.pointers.delete(event.pointerId),
      options,
    );
    element.addEventListener(
      'click',
      (event) => {
        if (!this.moved) {
          const rect = element.getBoundingClientRect();
          const item = this.hit(event.clientX - rect.left, event.clientY - rect.top);
          if (item) this.open(item.kind, item.id);
        }
      },
      options,
    );
    element.addEventListener(
      'pointercancel',
      (event) => {
        this.moved = true;
        this.pointers.delete(event.pointerId);
      },
      options,
    );
    element.addEventListener(
      'keydown',
      (event) => {
        if (hasShortcutModifier(event)) return;
        const directions: Record<string, [number, number]> = {
          ArrowLeft: [64, 0],
          ArrowRight: [-64, 0],
          ArrowUp: [0, 64],
          ArrowDown: [0, -64],
        };
        if (directions[event.key]) {
          event.preventDefault();
          this.camera.x += directions[event.key][0];
          this.camera.y += directions[event.key][1];
          this.redraw();
        } else if (['+', '=', '-', '0'].includes(event.key)) {
          event.preventDefault();
          if (event.key === '0') this.reset();
          else this.zoom(event.key === '-' ? 1 / 1.4 : 1.4);
        } else if (['PageDown', 'PageUp'].includes(event.key) && this.labels.length) {
          event.preventDefault();
          this.focusIndex =
            this.focusIndex < 0
              ? event.key === 'PageDown'
                ? 0
                : this.labels.length - 1
              : (this.focusIndex + (event.key === 'PageDown' ? 1 : -1) + this.labels.length) %
                this.labels.length;
          element.setAttribute(
            'aria-label',
            `${this.layout} map. ${this.labels[this.focusIndex].item.name}. Enter to open.`,
          );
          this.redraw();
        } else if (event.key === 'Enter' && this.labels[this.focusIndex]) {
          const item = this.labels[this.focusIndex].item;
          this.open(item.kind, item.id);
        }
      },
      options,
    );
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(element);
  }

  private resize() {
    const width = this.element.clientWidth,
      height = this.element.clientHeight;
    if (!width || !height) return;
    const initial = !this.width;
    if (!initial) {
      this.camera.x += (width - this.width) / 2;
      this.camera.y += (height - this.height) / 2;
    }
    this.width = width;
    this.height = height;
    const ratio = window.devicePixelRatio || 1;
    this.element.width = Math.round(width * ratio);
    this.element.height = Math.round(height * ratio);
    const scale = Math.min(width / 1000, height / 570);
    this.home = { scale, x: width / 2 - 500 * scale, y: height / 2 - 285 * scale };
    if (initial) this.camera = { ...this.home };
    else if (this.camera.scale > this.home.scale * MAX_ZOOM) this.zoom(1);
    this.redraw();
  }

  zoom(factor: number, point = { x: this.width / 2, y: this.height / 2 }) {
    const scale = Math.min(
      this.home.scale * MAX_ZOOM,
      Math.max(this.home.scale / 2, this.camera.scale * factor),
    );
    const ratio = scale / this.camera.scale;
    this.camera.x = point.x - (point.x - this.camera.x) * ratio;
    this.camera.y = point.y - (point.y - this.camera.y) * ratio;
    this.camera.scale = scale;
    this.redraw();
  }

  reset() {
    this.camera = { ...this.home };
    this.redraw();
  }

  selection(
    id: string,
    artist?: { id: string; name: string; x: number; y: number },
    reveal = false,
  ) {
    this.selected = id;
    this.artist = undefined;
    if (artist) {
      const font = '600 15px Helvetica, Arial, sans-serif';
      this.context.font = font;
      this.artist = {
        ...artist,
        label: baseName(artist.name),
        x: 90 + artist.x * 820,
        y: 65 + artist.y * 440,
        size: 15,
        width: this.context.measureText(baseName(artist.name)).width,
        fullWidth: this.context.measureText(artist.name).width,
        font,
        count: Infinity,
        depth: 0,
        kind: 'artist',
        order: -1,
      };
    }
    const item = this.artist || this.items.get(id);
    if (item && reveal) {
      const x = item.x * this.camera.scale + this.camera.x,
        y = item.y * this.camera.scale + this.camera.y;
      if (
        x < 100 ||
        x > this.width - Math.min(item.width + 20, this.width / 2) ||
        y < 30 ||
        y > this.height - 30
      )
        this.center(item.x, item.y);
    }
    this.redraw();
  }

  center(x: number, y: number) {
    this.camera.x = this.width / 2 - x * this.camera.scale;
    this.camera.y = this.height / 2 - y * this.camera.scale;
    this.redraw();
  }

  private hit(x: number, y: number) {
    return this.labels.find(
      ({ box }) => x >= box.left && x <= box.right && y >= box.top && y <= box.bottom,
    )?.item;
  }

  redraw() {
    if (!this.frame) this.frame = requestAnimationFrame(() => this.draw());
  }

  private draw() {
    this.frame = 0;
    const start = performance.now();
    if (this.wheel) {
      const delta = this.wheel;
      this.wheel = 0;
      this.zoom(Math.exp(-Math.max(-600, Math.min(600, delta)) * 0.0015), this.wheelPoint);
      cancelAnimationFrame(this.frame);
      this.frame = 0;
    }
    const ctx = this.context,
      ratio = window.devicePixelRatio || 1;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, this.width, this.height);
    const { scale, x, y } = this.camera;
    const grid = new LabelGrid();
    const viewport = { width: this.width, height: this.height };
    const candidates: Item[] = [];
    const maxDepth = visibleDepth(scale, this.home.scale);
    const left = Math.max(0, Math.floor(-x / scale / 16)),
      right = Math.min(63, Math.floor((this.width - x) / scale / 16));
    const top = Math.max(0, Math.floor(-y / scale / 16)),
      bottom = Math.min(36, Math.floor((this.height - y) / scale / 16));
    for (let a = left; a <= right; a++)
      for (let b = top; b <= bottom; b++)
        for (const item of this.points.get(`${a}:${b}`) || []) {
          const px = item.x * scale + x,
            py = item.y * scale + y;
          if (
            px >= 6 &&
            px < this.width - 6 &&
            py >= 20 &&
            py < this.height - 10 &&
            (item.depth <= maxDepth || item.id === this.selected)
          )
            candidates.push(item);
        }
    candidates.sort((a, b) => a.order - b.order);
    const selected = candidates.findIndex((item) => item.id === this.selected);
    if (selected > 0) candidates.unshift(...candidates.splice(selected, 1));
    if (this.artist) candidates.unshift(this.artist);
    const names = new Set<string>();
    this.labels = [];
    const detailed = scale >= this.home.scale * 4;
    for (const item of candidates) {
      const px = item.x * scale + x,
        py = item.y * scale + y;
      ctx.fillStyle = item.id === this.selected ? '#b32013' : '#999';
      ctx.beginPath();
      ctx.arc(px, py - 4, 2, 0, Math.PI * 2);
      ctx.fill();
    }
    for (const item of candidates) {
      const label = detailed ? item.name : item.label;
      if (!claimName(label, names, detailed)) continue;
      const px = item.x * scale + x,
        py = item.y * scale + y;
      const placement = labelBox(
        px,
        py,
        detailed ? item.fullWidth : item.width,
        item.size,
        viewport,
      );
      if (!placement || !grid.place(placement.box)) continue;
      const { box, textX } = placement;
      ctx.font = item.font;
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 4;
      ctx.strokeText(label, textX, py);
      ctx.fillStyle = item.id === this.selected ? '#b32013' : '#111';
      ctx.fillText(label, textX, py);
      this.labels.push({ item, box, x: px, y: py });
    }
    const focus = this.labels[this.focusIndex];
    if (focus && document.activeElement === this.element) {
      ctx.strokeStyle = '#b32013';
      ctx.strokeRect(
        focus.box.left,
        focus.box.top,
        focus.box.right - focus.box.left,
        focus.box.bottom - focus.box.top,
      );
    }
    performance.measure('opennoise:map-frame', {
      start,
      end: performance.now(),
      detail: { labels: this.labels.length, candidates: candidates.length, scale },
    });
    if (++this.frames % 600 === 0) performance.clearMeasures('opennoise:map-frame');
  }

  destroy() {
    cancelAnimationFrame(this.frame);
    this.observer.disconnect();
    this.abort.abort();
  }
}
