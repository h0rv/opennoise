import Panzoom from '@panzoom/panzoom';
import type { Camera } from './map-geometry';
import { hasShortcutModifier } from './keyboard';

type Options = {
  camera: Camera;
  minScale: number;
  maxScale: number;
  excludeClass: string;
  onChange?: () => void;
  onReset: () => void;
};

export type Navigation = ReturnType<typeof createNavigation>;

export function createNavigation(
  content: HTMLElement | SVGElement,
  viewport: HTMLElement,
  options: Options,
) {
  const events = new AbortController();
  const signal = events.signal;
  const panzoom = Panzoom(content, {
    startScale: options.camera.scale,
    startX: options.camera.x,
    startY: options.camera.y,
    minScale: options.minScale,
    maxScale: options.maxScale,
    canvas: true,
    excludeClass: options.excludeClass,
  });
  if (options.onChange) content.addEventListener('panzoomchange', options.onChange, { signal });
  panzoom.pan(options.camera.x, options.camera.y);
  let wheelFrame = 0,
    wheelDelta = 0;
  let wheelPoint = { clientX: 0, clientY: 0 };

  function zoomBy(factor: number, point?: { clientX: number; clientY: number }) {
    if (signal.aborted) return;
    const box = point ? null : viewport.getBoundingClientRect();
    panzoom.zoomToPoint(
      panzoom.getScale() * factor,
      point || {
        clientX: (box!.left + box!.right) / 2,
        clientY: (box!.top + box!.bottom) / 2,
      },
      { animate: false },
    );
  }

  viewport.addEventListener(
    'wheel',
    (event) => {
      event.preventDefault();
      wheelDelta +=
        (event.deltaY || event.deltaX) *
        (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1);
      wheelPoint = { clientX: event.clientX, clientY: event.clientY };
      if (wheelFrame) return;
      wheelFrame = requestAnimationFrame(() => {
        wheelFrame = 0;
        const delta = Math.max(-600, Math.min(600, wheelDelta));
        wheelDelta = 0;
        if (!signal.aborted) zoomBy(Math.exp(-delta * 0.002), wheelPoint);
      });
    },
    { passive: false, signal },
  );
  viewport.addEventListener('dblclick', (event) => zoomBy(1.8, event), { signal });
  viewport.addEventListener(
    'keydown',
    (event) => {
      if (event.target !== viewport || hasShortcutModifier(event)) return;
      const step = 64 / panzoom.getScale();
      const directions: Record<string, [number, number]> = {
        ArrowLeft: [step, 0],
        ArrowRight: [-step, 0],
        ArrowUp: [0, step],
        ArrowDown: [0, -step],
      };
      const delta = directions[event.key];
      if (delta) {
        event.preventDefault();
        panzoom.pan(delta[0], delta[1], { relative: true });
      } else if (event.key === '+' || event.key === '=') {
        event.preventDefault();
        zoomBy(1.35);
      } else if (event.key === '-') {
        event.preventDefault();
        zoomBy(1 / 1.35);
      } else if (event.key === '0') {
        event.preventDefault();
        options.onReset();
      }
    },
    { signal },
  );

  return {
    panzoom,
    zoomBy,
    destroy() {
      events.abort();
      cancelAnimationFrame(wheelFrame);
      panzoom.destroy();
    },
  };
}
