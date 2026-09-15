#!/usr/bin/env node

/**
 * Browser-only acceptance checks for the OpenNoise semantic map.
 *
 * The map stays untouched: Canvas drawing primitives are observed from a
 * preload script so this harness can count points, labels, and focused edges
 * without adding a production debug API.  The output is both a report and a
 * useful pair of light/dark screenshots for human review.
 */

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

const args = process.argv.slice(2);
const baseUrl = args[0];
const output = args[1];
if (!baseUrl || !output) {
  throw new Error("usage: capture_semantic_map_browser.mjs URL OUTPUT [--captures DIR]");
}
const option = (name) => {
  const index = args.indexOf(name);
  return index < 0 ? null : args[index + 1] ?? null;
};
const captures = resolve(option("--captures") ?? "artifacts/semantic-map/captures");
const port = Number(option("--port") ?? 9323);
const sleep = (milliseconds) => new Promise((done) => setTimeout(done, milliseconds));

class Cdp {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.next = 0;
    this.waiting = new Map();
    this.runtimeErrors = [];
    this.socket.addEventListener("message", ({ data }) => {
      const message = JSON.parse(data);
      if (message.method === "Runtime.exceptionThrown") {
        this.runtimeErrors.push(message.params.exceptionDetails.text);
      }
      if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
        this.runtimeErrors.push(
          message.params.args.map((item) => item.value ?? item.description ?? "console error").join(" "),
        );
      }
      const entry = this.waiting.get(message.id);
      if (!entry) return;
      this.waiting.delete(message.id);
      if (message.error) entry.reject(new Error(`${entry.method}: ${JSON.stringify(message.error)}`));
      else entry.resolve(message.result ?? {});
    });
  }

  async connect() {
    await new Promise((resolve_, reject) => {
      this.socket.addEventListener("open", resolve_, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
  }

  command(method, params = {}) {
    return new Promise((resolve_, reject) => {
      const id = ++this.next;
      const timeout = setTimeout(() => {
        this.waiting.delete(id);
        reject(new Error(`${method}: timed out`));
      }, 15_000);
      this.waiting.set(id, {
        method,
        resolve: (result) => { clearTimeout(timeout); resolve_(result); },
        reject: (error) => { clearTimeout(timeout); reject(error); },
      });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.command("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) throw new Error(`page evaluation failed: ${result.exceptionDetails.text}`);
    return result.result?.value;
  }

  close() { this.socket.close(); }
}

async function json(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

async function launch() {
  const profile = `${tmpdir()}/opennoise-semantic-map-${process.pid}`;
  await rm(profile, { recursive: true, force: true });
  const process_ = spawn("/usr/bin/chromium", [
    "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-background-networking",
    "--disable-default-apps", "--no-first-run", `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`, "about:blank",
  ], { stdio: "ignore" });
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      await json(`http://127.0.0.1:${port}/json/version`);
      return { process_, profile };
    } catch { await sleep(50); }
  }
  process_.kill("SIGKILL");
  throw new Error("Chromium did not expose DevTools");
}

async function page() {
  const target = await json(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" });
  const cdp = new Cdp(target.webSocketDebuggerUrl);
  await cdp.connect();
  await cdp.command("Page.enable");
  await cdp.command("Runtime.enable");
  await cdp.command("Input.setIgnoreInputEvents", { ignore: false });
  await cdp.command("Page.addScriptToEvaluateOnNewDocument", { source: PRELOAD });
  return cdp;
}

async function navigate(cdp, width, height, colorScheme) {
  await cdp.command("Emulation.setDeviceMetricsOverride", {
    width, height, deviceScaleFactor: 1, mobile: width <= 500,
    screenWidth: width, screenHeight: height,
  });
  await cdp.command("Emulation.setEmulatedMedia", {
    media: "screen",
    features: [{ name: "prefers-color-scheme", value: colorScheme }],
  });
  await cdp.command("Page.navigate", { url: baseUrl });
  for (let attempt = 0; attempt < 240; attempt += 1) {
    const ready = await cdp.evaluate(
      "document.readyState === 'complete' && Boolean(document.querySelector('#semantic-map')) && Boolean(window.__opennoiseMapQA?.frames?.length)",
    );
    if (ready) return;
    await sleep(25);
  }
  throw new Error("semantic map did not become renderer-ready");
}

async function waitForFrame(cdp, previousFrame = -1) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const frame = await cdp.evaluate("window.__opennoiseMapQA?.frames?.length ?? 0");
    if (frame > previousFrame) return frame;
    await sleep(25);
  }
  throw new Error("semantic map did not redraw");
}

async function diagnostics(cdp) {
  return cdp.evaluate(`(() => {
    const qa = window.__opennoiseMapQA;
    const canvas = document.querySelector('#semantic-map');
    const rect = canvas?.getBoundingClientRect();
    const frame = qa?.frames?.at(-1) ?? {
      arcs: [], labels: [], label_boxes: [], edges: 0, edge_endpoints: [],
      connected_path_arcs: 0, path_fills: 0,
    };
    const extent = (items, x, y) => items.length ? {
      min_x: Math.min(...items.map(item => item[x])), max_x: Math.max(...items.map(item => item[x])),
      min_y: Math.min(...items.map(item => item[y])), max_y: Math.max(...items.map(item => item[y])),
    } : null;
    const style = canvas ? getComputedStyle(document.documentElement) : null;
    const detail = document.querySelector('#map-detail');
    const detailRect = detail?.getBoundingClientRect();
    return {
      frame_count: qa?.frames?.length ?? 0,
      viewport: rect ? { width: rect.width, height: rect.height } : null,
      points: frame.arcs.length,
      labels: frame.labels.length,
      lod: Number(canvas?.dataset.mapLod ?? -1),
      scale: Number(canvas?.dataset.mapScale ?? 0),
      cohorts: (canvas?.dataset.mapCohorts ?? '').split('|').filter(Boolean),
      label_names: [...new Set(frame.labels.map((item) => item.text))],
      label_boxes: frame.label_boxes,
      edges: frame.edges,
      edge_endpoints: frame.edge_endpoints,
      connected_path_arcs: frame.connected_path_arcs,
      path_fills: frame.path_fills,
      point_extent: extent(frame.arcs, 'x', 'y'),
      background: style?.getPropertyValue('--canvas').trim() ?? '',
      back_hidden: document.querySelector('[data-map-action="back"]')?.hidden ?? true,
      detail_hidden: document.querySelector('#map-detail')?.hidden ?? true,
      detail_links: document.querySelectorAll('#map-detail [data-open-node-id]').length,
      detail_names: [...document.querySelectorAll('#map-detail [data-open-node-id]')]
        .map((link) => link.textContent),
      detail_box: detailRect ? { x: detailRect.x, y: detailRect.y, width: detailRect.width, height: detailRect.height } : null,
      focus_url: new URL(location.href).searchParams.get('open_focus'),
      canvas_ready: Boolean(canvas),
    };
  })()`);
}

async function screenshot(cdp, name, colorScheme, width, height) {
  const result = await cdp.command("Page.captureScreenshot", {
    format: "png", captureBeyondViewport: false,
  });
  const bytes = Buffer.from(result.data, "base64");
  const path = resolve(captures, name);
  await writeFile(path, bytes);
  return {
    name, color_scheme: colorScheme, width, height, path,
    byte_size: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex"),
  };
}

function requireCheck(condition, message, details = {}) {
  if (!condition) throw new Error(`${message}: ${JSON.stringify(details)}`);
}

function boxesInViewport(items, viewport) {
  return items.every((box) => box.x0 >= 0 && box.y0 >= 0
    && box.x1 <= viewport.width && box.y1 <= viewport.height);
}

function edgesInViewport(items, viewport) {
  return items.every((edge) => edge.x0 >= 0 && edge.y0 >= 0
    && edge.x1 >= 0 && edge.y1 >= 0
    && edge.x0 <= viewport.width && edge.y0 <= viewport.height
    && edge.x1 <= viewport.width && edge.y1 <= viewport.height);
}

function boxInViewport(box, viewport) {
  return Boolean(box) && box.x >= 0 && box.y >= 0
    && box.x + box.width <= viewport.width && box.y + box.height <= viewport.height;
}

async function wheel(cdp, x, y, deltaY) {
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseWheel", x, y, deltaY, deltaX: 0 });
}

async function clickControl(cdp, action) {
  const previousFrame = await cdp.evaluate("window.__opennoiseMapQA?.frames?.length ?? 0");
  await cdp.evaluate(`document.querySelector('[data-map-action="${action}"]')?.click()`);
  await waitForFrame(cdp, previousFrame);
  return diagnostics(cdp);
}

async function drag(cdp, fromX, fromY, toX, toY) {
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseMoved", x: fromX, y: fromY });
  await cdp.command("Input.dispatchMouseEvent", { type: "mousePressed", x: fromX, y: fromY, button: "left", clickCount: 1 });
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseMoved", x: toX, y: toY, button: "left", buttons: 1 });
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseReleased", x: toX, y: toY, button: "left", clickCount: 1 });
}

async function pinch(cdp, centerX, centerY, startRadius, endRadius) {
  const first = { x: centerX - startRadius, y: centerY };
  const second = { x: centerX + startRadius, y: centerY };
  await cdp.command('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [first, second] });
  await cdp.command('Input.dispatchTouchEvent', {
    type: 'touchMove',
    touchPoints: [{ x: centerX - endRadius, y: centerY }, { x: centerX + endRadius, y: centerY }],
  });
  await cdp.command('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
}

const PRELOAD = String.raw`(() => {
  const original = {
    arc: CanvasRenderingContext2D.prototype.arc,
    fillText: CanvasRenderingContext2D.prototype.fillText,
    fill: CanvasRenderingContext2D.prototype.fill,
    lineTo: CanvasRenderingContext2D.prototype.lineTo,
    stroke: CanvasRenderingContext2D.prototype.stroke,
    moveTo: CanvasRenderingContext2D.prototype.moveTo,
  };
  const NativePath2D = window.Path2D;
  const pathStates = new WeakMap();
  class QAPath2D extends NativePath2D {
    constructor(...args) {
      super(...args);
      pathStates.set(this, { arcs: [], connectedArcs: 0, lastCommand: null });
    }
    moveTo(...args) {
      const state = pathStates.get(this);
      if (state) state.lastCommand = "moveTo";
      return super.moveTo(...args);
    }
    arc(x, y, radius, ...rest) {
      const state = pathStates.get(this);
      if (state) {
        if (state.lastCommand !== "moveTo") state.connectedArcs += 1;
        state.arcs.push({ x, y, radius });
        state.lastCommand = "arc";
      }
      return super.arc(x, y, radius, ...rest);
    }
  }
  window.Path2D = QAPath2D;
  const qa = {
    frames: [],
    current: {
      arcs: [], labels: [], label_boxes: [], edges: 0, edge_endpoints: [],
      line_segments: 0, connected_path_arcs: 0, path_fills: 0,
    },
  };
  const finish = () => {
    if (qa.current.arcs.length || qa.current.labels.length || qa.current.edges || qa.current.path_fills) {
      qa.frames.push(qa.current);
      if (qa.frames.length > 40) qa.frames.shift();
    }
    qa.current = {
      arcs: [], labels: [], label_boxes: [], edges: 0, edge_endpoints: [],
      line_segments: 0, connected_path_arcs: 0, path_fills: 0,
    };
  };
  CanvasRenderingContext2D.prototype.arc = function(x, y, radius, ...rest) {
    if (this.canvas?.id === 'semantic-map') qa.current.arcs.push({ x, y, radius });
    return original.arc.call(this, x, y, radius, ...rest);
  };
  CanvasRenderingContext2D.prototype.fillText = function(text, x, y, ...rest) {
    if (this.canvas?.id === 'semantic-map') {
      const width = this.measureText(text).width;
      qa.current.labels.push({ text, x, y });
      qa.current.label_boxes.push({ x0: x - 3, y0: y - 19, x1: x + width + 3, y1: y + 3 });
    }
    return original.fillText.call(this, text, x, y, ...rest);
  };
  CanvasRenderingContext2D.prototype.fill = function(pathOrRule, ...rest) {
    if (this.canvas?.id === "semantic-map" && pathOrRule instanceof QAPath2D) {
      const state = pathStates.get(pathOrRule);
      if (state) {
        qa.current.arcs.push(...state.arcs);
        qa.current.connected_path_arcs += state.connectedArcs;
        qa.current.path_fills += 1;
      }
    }
    return original.fill.call(this, pathOrRule, ...rest);
  };
  CanvasRenderingContext2D.prototype.lineTo = function(x, y) {
    if (this.canvas?.id === 'semantic-map') {
      qa.current.line_segments += 1;
      if (this.lineWidth === 1.5 || this.lineWidth === 1.75) {
        const start = this.__opennoiseQaMoveTo;
        if (start) qa.current.edge_endpoints.push({ x0: start.x, y0: start.y, x1: x, y1: y });
      }
    }
    return original.lineTo.call(this, x, y);
  };
  CanvasRenderingContext2D.prototype.moveTo = function(x, y) {
    if (this.canvas?.id === 'semantic-map') this.__opennoiseQaMoveTo = { x, y };
    return original.moveTo.call(this, x, y);
  };
  CanvasRenderingContext2D.prototype.stroke = function(...args) {
    // Similarity and direct hierarchy lines use dedicated strokes. One-pixel
    // label callouts should not inflate the focused graph edge budget.
    if (this.canvas?.id === 'semantic-map' && (this.lineWidth === 1.5 || this.lineWidth === 1.75)) qa.current.edges += 1;
    return original.stroke.call(this, ...args);
  };
  const request = window.requestAnimationFrame;
  window.requestAnimationFrame = (callback) => request.call(window, (timestamp) => {
    finish();
    callback(timestamp);
    finish();
  });
  window.__opennoiseMapQA = qa;
})();`;

async function run() {
  const chrome = await launch();
  const screenshots = [];
  try {
    await mkdir(captures, { recursive: true });
    const cdp = await page();
    await navigate(cdp, 1440, 900, "light");
    const initial = await diagnostics(cdp);
    requireCheck(initial.canvas_ready, "canvas is missing", initial);
    requireCheck(initial.viewport?.width === 1440 && initial.viewport?.height === 900, "viewport is wrong", initial);
    requireCheck(initial.points >= 1 && initial.points <= 50, "overview point budget failed", initial);
    requireCheck(initial.labels >= 1 && initial.labels <= 35, "overview label budget failed", initial);
    requireCheck(initial.edges === 0, "overview must not draw global edges", initial);
    requireCheck(initial.label_names.includes("rock"), "overview omitted the rock hierarchy landmark", initial);
    const extent = initial.point_extent;
    const widthFraction = extent ? (extent.max_x - extent.min_x) / initial.viewport.width : 0;
    const heightFraction = extent ? (extent.max_y - extent.min_y) / initial.viewport.height : 0;
    requireCheck(widthFraction >= 0.75, "overview does not use horizontal space", { initial, width_fraction: widthFraction });
    requireCheck(heightFraction >= 0.70, "overview does not use vertical space", { initial, height_fraction: heightFraction });
    requireCheck(boxesInViewport(initial.label_boxes, initial.viewport), "overview label box escaped viewport", initial);
    screenshots.push(await screenshot(cdp, "desktop-light.png", "light", 1440, 900));

    const buttonL1 = await clickControl(cdp, "in");
    const buttonL2 = await clickControl(cdp, "in");
    const buttonL3 = await clickControl(cdp, "in");
    const buttonDeep = await clickControl(cdp, 'in');
    requireCheck(buttonL1.lod === 1 && buttonL2.lod === 2 && buttonL3.lod === 3, "plus control did not cross semantic zoom tiers", {
      initial_lod: initial.lod, button_l1_lod: buttonL1.lod, button_l2_lod: buttonL2.lod, button_l3_lod: buttonL3.lod,
    });
    const buttonL1New = buttonL1.label_names.filter((name) => !initial.label_names.includes(name));
    const buttonL2New = buttonL2.label_names.filter((name) => !buttonL1.label_names.includes(name));
    requireCheck(buttonL1New.length >= 1 && buttonL2New.length >= 1, "plus control did not disclose new local names", {
      button_l1_new: buttonL1New, button_l2_new: buttonL2New,
    });
    const retainedCohorts = buttonL1.cohorts.filter((cohort) => buttonL2.cohorts.includes(cohort));
    requireCheck(retainedCohorts.length >= 1, "plus control did not retain a semantic neighborhood", {
      button_l1_cohorts: buttonL1.cohorts, button_l2_cohorts: buttonL2.cohorts,
    });
    requireCheck(buttonDeep.lod === 3 && buttonDeep.scale > buttonL3.scale, 'L3 imposed a camera zoom wall', { buttonL3, buttonDeep });
    screenshots.push(await screenshot(cdp, "desktop-button-deep.png", "light", 1440, 900));
    await navigate(cdp, 1440, 900, "light");

    const firstFrame = initial.frame_count - 1;
    await wheel(cdp, 720, 450, -650);
    await waitForFrame(cdp, firstFrame);
    const zoom1 = await diagnostics(cdp);
    await wheel(cdp, 720, 450, -650);
    await waitForFrame(cdp, zoom1.frame_count - 1);
    const zoom2 = await diagnostics(cdp);
    // A closer camera can legitimately move past sparse nodes, so visible
    // point count need not increase on every wheel tick. Both zoom tiers must
    // still reveal more than the overview and render their batched primitives.
    requireCheck(
      zoom1.points > initial.points && zoom2.points > initial.points
        && zoom1.labels > 0 && zoom2.labels > 0
        && zoom1.path_fills > 0 && zoom2.path_fills > 0,
      "zoom reveal is unavailable",
      { initial, zoom1, zoom2 },
    );

    const beforePan = zoom2.point_extent;
    await drag(cdp, 720, 450, 240, 220);
    await waitForFrame(cdp, zoom2.frame_count - 1);
    const afterPan = await diagnostics(cdp);
    requireCheck(JSON.stringify(beforePan) !== JSON.stringify(afterPan.point_extent), "pan did not move camera", { beforePan, afterPan });

    const focusQuery = async (term, previousFrame) => {
      await cdp.evaluate(`(() => { const input=document.querySelector('#query'); input.value=${JSON.stringify(term)}; input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true})); })()`);
      await waitForFrame(cdp, previousFrame);
      let value = await diagnostics(cdp);
      for (let attempt = 0; attempt < 80 && value.edges === 0; attempt += 1) {
        await sleep(25); value = await diagnostics(cdp);
      }
      return value;
    };
    let focused = await focusQuery('idm', afterPan.frame_count - 1);
    // The focused view has at most twelve similarity links plus direct, verified
    // display-parent links.  They are deliberately distinct in the renderer.
    requireCheck(focused.edges > 0 && focused.edges <= 24, "focused neighborhood edge budget failed", focused);
    requireCheck(focused.connected_path_arcs === 0, "batched dots formed connected polygons", focused);
    requireCheck(boxesInViewport(focused.label_boxes, focused.viewport), "focused label box escaped viewport", focused);
    requireCheck(edgesInViewport(focused.edge_endpoints, focused.viewport), "focused edge endpoint escaped viewport", focused);
    requireCheck(!focused.back_hidden, "Back control did not appear after focus", focused);
    requireCheck(focused.focus_url === "legacy:item887", "IDM alias did not focus its stable seed", focused);
    requireCheck(focused.points <= focused.edges + 1, "focused view leaked unconnected dots", focused);
    requireCheck(!focused.detail_hidden && focused.detail_links === focused.edges && boxInViewport(focused.detail_box, focused.viewport), 'IDM list does not match its shown links', focused);
    screenshots.push(await screenshot(cdp, "desktop-idm-focus.png", "light", 1440, 900));

    await cdp.evaluate("document.querySelector('[data-map-action=\\\"back\\\"]')?.click()");
    await sleep(150);
    const backed = await diagnostics(cdp);
    requireCheck(backed.back_hidden && !backed.focus_url, "Back did not restore map state", backed);

    const postPunk = await focusQuery('post-punk', backed.frame_count - 1);
    requireCheck(postPunk.focus_url === 'legacy:item577' && postPunk.edges > 0, 'post-punk did not focus its structural neighborhood', postPunk);
    requireCheck(postPunk.points <= postPunk.edges + 1, 'post-punk view leaked unconnected dots', postPunk);
    requireCheck(!postPunk.detail_hidden && postPunk.detail_links === postPunk.edges && boxInViewport(postPunk.detail_box, postPunk.viewport), 'post-punk list does not match its shown links', postPunk);
    screenshots.push(await screenshot(cdp, 'desktop-post-punk-focus.png', 'light', 1440, 900));

    const modernRock = await focusQuery('modern rock', postPunk.frame_count - 1);
    requireCheck(
      modernRock.focus_url === 'legacy:item10' && modernRock.detail_names.includes('rock'),
      'modern rock did not retain its verified rock parent in the focused zoom view',
      modernRock,
    );
    screenshots.push(await screenshot(cdp, 'desktop-rock-modern-rock-focus.png', 'light', 1440, 900));

    await navigate(cdp, 1440, 900, "dark");
    const dark = await diagnostics(cdp);
    requireCheck(dark.background !== initial.background, "dark mode did not change the map palette", { initial, dark });
    screenshots.push(await screenshot(cdp, "desktop-dark.png", "dark", 1440, 900));
    await navigate(cdp, 390, 844, "light");
    const mobile = await diagnostics(cdp);
    requireCheck(mobile.canvas_ready && mobile.viewport?.width === 390 && mobile.viewport?.height === 844, "mobile viewport failed", mobile);
    requireCheck(mobile.connected_path_arcs === 0, "mobile batched dots formed connected polygons", mobile);
    requireCheck(boxesInViewport(mobile.label_boxes, mobile.viewport), "mobile label box escaped viewport", mobile);
    await pinch(cdp, 195, 500, 34, 132);
    await waitForFrame(cdp, mobile.frame_count - 1);
    const mobilePinch = await diagnostics(cdp);
    requireCheck(mobilePinch.scale > mobile.scale && mobilePinch.lod >= mobile.lod, 'mobile pinch did not zoom the map', { mobile, mobilePinch });
    screenshots.push(await screenshot(cdp, "mobile-light.png", "light", 390, 844));
    requireCheck(cdp.runtimeErrors.length === 0, "browser errors detected", cdp.runtimeErrors);
    const report = {
      evidence_revision: "browser-semantic-map-v1",
      capture_method: "Chrome DevTools Protocol with preload Canvas primitive instrumentation",
      viewport: { width: 1440, height: 900 },
      acceptance: {
        overview_width_fraction: widthFraction,
        overview_height_fraction: heightFraction,
        overview_points: initial.points,
        overview_labels: initial.labels,
        overview_edges: initial.edges,
        zoom_points: [initial.points, zoom1.points, zoom2.points],
        button_labels: [buttonL1.labels, buttonL2.labels, buttonL3.labels, buttonDeep.labels],
        button_new_labels: [
          buttonL1New,
          buttonL2New,
        ],
        button_lods: [initial.lod, buttonL1.lod, buttonL2.lod, buttonL3.lod],
        deep_zoom_scale: buttonDeep.scale,
        focused_edges: focused.edges,
        post_punk_edges: postPunk.edges,
        rock_modern_rock_hierarchy: modernRock.detail_names.includes('rock'),
        pan_changed_extent: JSON.stringify(beforePan) !== JSON.stringify(afterPan.point_extent),
        back_restored: backed.back_hidden && !backed.focus_url,
        dark_mode: dark.background !== initial.background,
        mobile_ready: mobile.canvas_ready && mobile.viewport?.width === 390 && mobile.viewport?.height === 844,
        mobile_pinch_zoomed: mobilePinch.scale > mobile.scale,
      },
      diagnostics: { initial, buttonL1, buttonL2, buttonL3, buttonDeep, zoom1, zoom2, afterPan, focused, backed, postPunk, modernRock, dark, mobile, mobilePinch },
      screenshots,
    };
    await writeFile(resolve(output), `${JSON.stringify(report, null, 2)}\n`);
  } finally {
    chrome.process_.kill("SIGTERM");
    for (let attempt = 0; attempt < 8; attempt += 1) {
      try {
        await rm(chrome.profile, { recursive: true, force: true, maxRetries: 1, retryDelay: 100 });
        break;
      } catch { await sleep(100); }
    }
  }
}

await run();
