import type { ArtistDetail, Genre, GenreDetail } from './catalog';
import { createNavigation, type Navigation } from './navigation';
import { layoutTree, type Branch, type TreeNode } from './tree-layout';
import { indexTree } from './tree-scene';

type Selection = { kind: 'genre' | 'artist'; id: string };
type Item = { kind: 'genre' | 'artist' | 'more' | 'status'; id: string; name: string };
function svg<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attributes: Record<string, string | number>,
) {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}

export class GenreTree {
  readonly element = document.createElement('div');
  private readonly viewport: HTMLElement;
  private readonly content: SVGGElement;
  private readonly diagram: SVGSVGElement;
  private readonly links: SVGGElement;
  private readonly labels: SVGGElement;
  private readonly children = new Map<string | null, Genre[]>();
  private readonly genres: Map<string, Genre>;
  private readonly expanded = new Set<string>();
  private readonly details = new Map<string, GenreDetail>();
  private readonly limits = new Map<string, number>();
  private readonly widths = new Map<string, number>();
  private readonly measure = document.createElement('canvas').getContext('2d')!;
  private readonly rendered = new Map<
    string,
    { group: SVGGElement; text: SVGTextElement; rect: SVGRectElement }
  >();
  private layout = layoutTree<Item>([]);
  private scene = indexTree(this.layout.nodes);
  private keyboard: TreeNode<Item>[] = [];
  private readonly keyboardIndex = new Map<string, number>();
  private readonly edges = new Map<string, SVGPathElement>();
  private dirty = true;
  private paintFrame = 0;
  private navigation?: Navigation;
  private camera?: { scale: number; x: number; y: number };
  private selection: Selection | null = null;
  private focused = '';
  private anchor = '';

  constructor(
    genres: Genre[],
    private readonly select: (selection: Selection) => void,
  ) {
    this.genres = new Map(genres.map((genre) => [genre.id, genre]));
    for (const genre of genres) {
      const siblings = this.children.get(genre.parent_id) || [];
      siblings.push(genre);
      this.children.set(genre.parent_id, siblings);
      if (genre.parent_id === null) this.expanded.add(genre.id);
    }
    this.element.className = 'tree-map';
    this.element.innerHTML = `<div class="map-viewport tree-viewport" tabindex="0" role="group" aria-label="Genre tree; arrows pan, plus and minus zoom, zero fits"><svg role="tree" aria-label="Genre and artist hierarchy"><g class="tree-content"><g class="tree-links"></g><g class="tree-labels"></g></g></svg></div><div class="map-bottom"><span></span><div class="zoom" aria-label="Tree controls"><button data-tree-zoom="out" aria-label="Zoom tree out">−</button><button data-tree-zoom="in" aria-label="Zoom tree in">+</button><button data-tree-zoom="reset">Reset</button></div></div>`;
    this.viewport = this.element.querySelector('.tree-viewport')!;
    this.diagram = this.element.querySelector('svg')!;
    this.content = this.element.querySelector('.tree-content')!;
    this.links = this.element.querySelector('.tree-links')!;
    this.labels = this.element.querySelector('.tree-labels')!;
    this.element.addEventListener('click', (event) => {
      const target = event.target as Element;
      const zoom = target.closest<HTMLElement>('[data-tree-zoom]')?.dataset.treeZoom;
      if (zoom === 'reset') this.fit();
      if (zoom === 'in') this.navigation?.zoomBy(1.35);
      if (zoom === 'out') this.navigation?.zoomBy(1 / 1.35);
      const key = target.closest<SVGGElement>('.tree-node')?.dataset.key;
      if (key && event.detail < 2) this.activate(key);
    });
    this.element.addEventListener('keydown', (event) => this.keydown(event));
  }

  show(
    container: HTMLElement,
    selection: Selection | null,
    detail: GenreDetail | ArtistDetail | null,
  ) {
    const changed =
      selection?.kind !== this.selection?.kind || selection?.id !== this.selection?.id;
    this.selection = selection;
    if (detail && 'genre' in detail && !this.details.has(detail.genre.id)) {
      this.details.set(detail.genre.id, detail);
      this.dirty = true;
    }
    if (selection?.kind === 'genre' && changed) {
      let genre = this.genres.get(selection.id);
      const seen = new Set<string>();
      while (genre?.parent_id && !seen.has(genre.id)) {
        seen.add(genre.id);
        if (!this.expanded.has(genre.parent_id)) this.dirty = true;
        this.expanded.add(genre.parent_id);
        genre = this.genres.get(genre.parent_id);
      }
      if (!this.anchor && !this.expanded.has(selection.id)) {
        this.expanded.add(selection.id);
        this.dirty = true;
      }
      this.focused = `genre:${selection.id}`;
    }
    if (this.element.parentElement !== container) container.replaceChildren(this.element);
    if (this.dirty) this.draw(this.anchor || this.focused);
    this.anchor = '';
    if (!this.navigation) {
      const scale = Math.min(
        1,
        Math.max(
          0.75,
          Math.min(
            (this.viewport.clientWidth - 32) / this.layout.width,
            (this.viewport.clientHeight - 32) / this.layout.height,
          ),
        ),
      );
      const first = this.scene.byKey.get(this.focused)?.node;
      const home =
        this.layout.height * scale > this.viewport.clientHeight * 3 && first
          ? {
              scale,
              x: 24 / scale - first.x,
              y: this.viewport.clientHeight / (2 * scale) - first.y,
            }
          : this.center(scale);
      this.navigation = createNavigation(this.content, this.viewport, {
        camera: this.camera || home,
        minScale: 0.2,
        maxScale: 4,
        excludeClass: 'tree-node',
        onChange: () => this.schedulePaint(),
        onReset: () => this.fit(),
      });
    }
    if (changed && selection?.kind === 'artist') {
      const node = this.layout.nodes.find(
        (node) => node.value.kind === 'artist' && node.value.id === selection.id,
      );
      if (node) this.focused = node.key;
    }
    if (changed) this.reveal(this.focused);
    this.paint();
  }

  hide() {
    if (!this.navigation) return;
    this.camera = {
      scale: this.navigation.panzoom.getScale(),
      ...this.navigation.panzoom.getPan(),
    };
    this.navigation.destroy();
    this.navigation = undefined;
    cancelAnimationFrame(this.paintFrame);
  }

  resize() {
    if (this.viewport.clientWidth <= 32 || this.viewport.clientHeight <= 48) return;
    this.sizeDiagram();
    this.reveal(this.focused);
    this.paint();
  }

  private branch(genre: Genre, seen = new Set<string>()): Branch<Item> {
    const children: Branch<Item>[] = [];
    if (this.expanded.has(genre.id) && !seen.has(genre.id)) {
      const next = new Set([...seen, genre.id]);
      for (const child of this.children.get(genre.id) || [])
        children.push(this.branch(child, next));
      const detail = this.details.get(genre.id);
      if (detail) {
        if (detail.members === null)
          children.push(this.leaf('status', genre.id, 'Artists not computed'));
        else {
          const limit = this.limits.get(genre.id) || 32;
          for (const { artist } of detail.members.slice(0, limit))
            children.push(this.leaf('artist', artist.id, artist.name, genre.id));
          if (detail.members.length > limit)
            children.push(
              this.leaf('more', genre.id, `More artists (${detail.members.length - limit})`),
            );
          else if (!detail.members.length && !children.length)
            children.push(this.leaf('status', genre.id, 'No member artists'));
        }
      }
    }
    return { ...this.leaf('genre', genre.id, genre.name), children };
  }

  private leaf(kind: Item['kind'], id: string, name: string, parent = ''): Branch<Item> {
    const key = `${kind}:${parent ? `${parent}:` : ''}${id}`;
    const metric = `${kind}:${name}`;
    let width = this.widths.get(metric);
    if (width === undefined) {
      this.measure.font = `${kind === 'genre' ? '700 16' : '400 13'}px Helvetica, Arial, sans-serif`;
      width = this.measure.measureText(name).width + 22;
      this.widths.set(metric, width);
    }
    return { key, width, value: { kind, id, name }, children: [] };
  }

  private draw(anchor: string) {
    const old = this.scene.byKey.get(anchor)?.node;
    this.layout = layoutTree((this.children.get(null) || []).map((genre) => this.branch(genre)));
    this.scene = indexTree(this.layout.nodes);
    this.keyboard = this.layout.nodes.filter((node) => node.value.kind !== 'status');
    this.keyboardIndex.clear();
    this.keyboard.forEach((node, index) => this.keyboardIndex.set(node.key, index));
    if (!this.scene.byKey.has(this.focused)) this.focused = this.keyboard[0]?.key || '';
    this.dirty = false;
    this.sizeDiagram();
    const next = this.scene.byKey.get(anchor)?.node;
    if (old && next && this.navigation) {
      const pan = this.navigation.panzoom.getPan();
      this.move(this.navigation.panzoom.getScale(), pan.x + old.x - next.x, pan.y + old.y - next.y);
    }
  }

  private sizeDiagram() {
    this.diagram.style.width =
      String(Math.max(this.viewport.clientWidth, this.layout.width)) + 'px';
    this.diagram.style.height =
      String(Math.max(this.viewport.clientHeight, this.layout.height)) + 'px';
  }

  private schedulePaint() {
    cancelAnimationFrame(this.paintFrame);
    this.paintFrame = requestAnimationFrame(() => this.paint());
  }

  private paint() {
    const map = this.navigation?.panzoom;
    if (!map || this.viewport.clientWidth <= 0) return;
    const scale = map.getScale(),
      pan = map.getPan();
    const padding = 96 / scale;
    const visible = this.scene.tree.search({
      minX: -pan.x - padding,
      minY: -pan.y - padding,
      maxX: this.viewport.clientWidth / scale - pan.x + padding,
      maxY: this.viewport.clientHeight / scale - pan.y + padding,
    });
    const focused = this.scene.byKey.get(this.focused);
    if (focused && !visible.includes(focused)) visible.push(focused);
    const nodes = visible.filter((item) => item.kind === 'node').sort((a, b) => a.order - b.order);
    const keys = new Set(nodes.map((item) => item.key));
    const edgeKeys = new Set<string>();
    for (const item of visible) {
      if (item.kind !== 'edge') continue;
      edgeKeys.add(item.key);
      let path = this.edges.get(item.key);
      if (!path) {
        path = svg('path', {});
        this.edges.set(item.key, path);
        this.links.append(path);
      }
      this.attribute(path, 'd', item.path);
    }
    for (const [key, path] of this.edges)
      if (!edgeKeys.has(key)) {
        path.remove();
        this.edges.delete(key);
      }
    const hadFocus = this.element.contains(document.activeElement);
    for (const [key, elements] of this.rendered) {
      if (!keys.has(key)) {
        elements.group.remove();
        this.rendered.delete(key);
      }
    }
    let previous: ChildNode | null = null;
    for (const { node } of nodes) {
      let elements = this.rendered.get(node.key);
      if (!elements) {
        const group = svg('g', { class: `tree-node tree-${node.value.kind}` });
        group.dataset.key = node.key;
        const rect = svg('rect', { x: 0, y: -22, height: 44 });
        const text = svg('text', { x: 10, y: 5 });
        group.append(rect, text);
        elements = { group, rect, text };
        this.rendered.set(node.key, elements);
      }
      const { group, rect, text } = elements;
      this.attribute(group, 'transform', `translate(${node.x},${node.y})`);
      this.attribute(group, 'role', node.value.kind === 'status' ? 'note' : 'treeitem');
      if (node.value.kind !== 'status') {
        this.attribute(group, 'aria-level', String(node.depth + 1));
        this.attribute(
          group,
          'aria-selected',
          String(node.value.kind === this.selection?.kind && node.value.id === this.selection.id),
        );
        this.attribute(group, 'tabindex', node.key === this.focused ? '0' : '-1');
      }
      if (node.value.kind === 'genre')
        this.attribute(group, 'aria-expanded', String(this.expanded.has(node.value.id)));
      this.attribute(rect, 'width', String(node.width));
      if (text.textContent !== node.value.name) text.textContent = node.value.name;
      const cursor: ChildNode | null = previous ? previous.nextSibling : this.labels.firstChild;
      if (cursor !== group) this.labels.insertBefore(group, cursor);
      previous = group;
    }
    const active = this.rendered.get(this.focused)?.group;
    if (hadFocus && document.activeElement !== active) active?.focus({ preventScroll: true });
  }

  private attribute(element: Element, name: string, value: string) {
    if (element.getAttribute(name) !== value) element.setAttribute(name, value);
  }

  private center(scale: number) {
    return {
      scale,
      x: this.viewport.clientWidth / (2 * scale) - this.layout.width / 2,
      y: this.viewport.clientHeight / (2 * scale) - this.layout.height / 2,
    };
  }

  private move(scale: number, x: number, y: number) {
    const map = this.navigation?.panzoom;
    if (!map) return;
    map.setOptions({ startX: x, startY: y });
    map.zoom(scale, { animate: false });
    map.pan(x, y);
  }

  private fit() {
    if (this.viewport.clientWidth <= 32 || this.viewport.clientHeight <= 48) return;
    if (this.layout.height * 0.2 > this.viewport.clientHeight) {
      const node = this.scene.byKey.get(this.focused)?.node;
      if (node) this.move(1, 24 - node.x, this.viewport.clientHeight / 2 - node.y);
      return;
    }
    const scale = Math.max(
      0.2,
      Math.min(
        1,
        (this.viewport.clientWidth - 32) / this.layout.width,
        (this.viewport.clientHeight - 32) / this.layout.height,
      ),
    );
    const camera = this.center(scale);
    this.move(camera.scale, camera.x, camera.y);
  }

  private reveal(key: string) {
    if (this.viewport.clientWidth <= 32 || this.viewport.clientHeight <= 48) return;
    const node = this.scene.byKey.get(key)?.node;
    const map = this.navigation?.panzoom;
    if (!node || !map) return;
    const pan = map.getPan(),
      scale = map.getScale();
    const left = (node.x + pan.x) * scale,
      top = (node.y + pan.y) * scale;
    if (
      left >= 16 &&
      left + node.width * scale <= this.viewport.clientWidth - 16 &&
      top >= 24 &&
      top <= this.viewport.clientHeight - 24
    )
      return;
    const zoom = Math.max(0.2, Math.min(scale, (this.viewport.clientWidth - 32) / node.width));
    this.move(
      zoom,
      this.viewport.clientWidth / (2 * zoom) - node.x - node.width / 2,
      this.viewport.clientHeight / (2 * zoom) - node.y,
    );
  }

  private focus(key: string) {
    this.rendered.get(this.focused)?.group.setAttribute('tabindex', '-1');
    this.focused = key;
    this.reveal(key);
    this.paint();
    const group = this.rendered.get(key)?.group;
    group?.setAttribute('tabindex', '0');
    group?.focus({ preventScroll: true });
  }

  private activate(key: string) {
    const node = this.scene.byKey.get(key)?.node;
    if (!node || node.value.kind === 'status') return;
    this.focus(key);
    const { kind, id } = node.value;
    if (kind === 'more') {
      const limit = this.limits.get(id) || 32;
      this.limits.set(id, limit + 32);
      this.dirty = true;
      this.draw(`genre:${id}`);
      const member = this.details.get(id)?.members?.[limit];
      if (member) this.focus(`artist:${id}:${member.artist.id}`);
      return;
    }
    this.anchor = key;
    if (kind === 'genre') {
      this.dirty = true;
      if (this.expanded.has(id)) this.expanded.delete(id);
      else this.expanded.add(id);
    }
    this.select({ kind, id });
  }

  private keydown(event: KeyboardEvent) {
    const key = (event.target as Element).closest<SVGGElement>('.tree-node')?.dataset.key;
    if (!key) return;
    const nodes = this.keyboard;
    const index = this.keyboardIndex.get(key) ?? -1;
    const node = nodes[index];
    if (!node) return;
    if (
      ![
        'ArrowDown',
        'ArrowUp',
        'ArrowLeft',
        'ArrowRight',
        'Home',
        'End',
        'Enter',
        ' ',
        '+',
        '=',
        '-',
        '0',
      ].includes(event.key)
    )
      return;
    event.preventDefault();
    event.stopPropagation();
    if (event.key === 'ArrowDown') this.focus(nodes[Math.min(nodes.length - 1, index + 1)].key);
    if (event.key === 'ArrowUp') this.focus(nodes[Math.max(0, index - 1)].key);
    if (event.key === 'Home') this.focus(nodes[0].key);
    if (event.key === 'End') this.focus(nodes[nodes.length - 1].key);
    if (event.key === 'ArrowRight') {
      if (node.value.kind === 'genre' && !this.expanded.has(node.value.id)) this.activate(key);
      else {
        const child = nodes.find((child) => child.parent === key);
        if (child) this.focus(child.key);
      }
    }
    if (event.key === 'ArrowLeft') {
      if (node.value.kind === 'genre' && this.expanded.has(node.value.id)) this.activate(key);
      else if (node.parent) this.focus(node.parent);
    }
    if (event.key === 'Enter' || event.key === ' ') this.activate(key);
    if (event.key === '+' || event.key === '=') this.navigation?.zoomBy(1.35);
    if (event.key === '-') this.navigation?.zoomBy(1 / 1.35);
    if (event.key === '0') this.fit();
  }
}
