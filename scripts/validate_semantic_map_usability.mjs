#!/usr/bin/env node

/**
 * Deterministic browser contract checks for the historical semantic map.
 *
 * This harness serves a synthetic 13-umbrella hierarchy from loopback and
 * loads the checked-in map assets. It deliberately does not use production
 * data or an external browser automation package. All geometry is measured
 * from the live Cytoscape renderer after real CDP input events.
 */

import { createServer } from "node:http";
import { createHash } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { spawn } from "node:child_process";
import { createServer as createTcpServer } from "node:net";

const root = resolve(import.meta.dirname, "..");
const mapSource = await readFile(resolve(root, "src/musix/static/semantic-map.js"), "utf8");
const cytoscapeSource = await readFile(resolve(root, "src/musix/static/cytoscape-3.34.0.min.js"), "utf8");
const cssSource = await readFile(resolve(root, "src/musix/static/app.css"), "utf8");
const sleep = (milliseconds) => new Promise((resolve_) => setTimeout(resolve_, milliseconds));
const option = (name) => {
  const index = process.argv.indexOf(name);
  return index < 0 ? null : process.argv[index + 1] ?? null;
};
const captureDirectory = resolve(option("--captures") ?? process.env.MUSIX_MAP_VALIDATION_CAPTURE_DIR ?? ".cache/ui-qa");

const umbrellaLabels = [
  "Alternative and Indie Rock", "Ambient and Atmospheric", "Blues and Roots Music",
  "Classical and Contemporary", "Country and Americana", "Dance and Electronic",
  "Experimental and Avant-Garde", "Folk and Singer Songwriter", "Hip Hop and Rap",
  "Jazz and Improvised Music", "Latin and Caribbean", "Metal and Heavy Music",
  "Pop, Soul and R&B",
];
const hierarchy = (id, level, label, x = level + 0.15, y = level + 0.25) => ({
  hierarchy_id: id,
  level,
  representative_genre_id: `${id}-representative`,
  representative_label: label,
  member_count: 3,
  x,
  y,
});
const leaf = (id, x, y) => ({ genre_id: id, name: id, membership_count: 1, x, y });
const overview = umbrellaLabels.map((label, index) => hierarchy(
  `overview-${index}`,
  0,
  label,
  index === 12 ? 12.5 : index / 12,
  0.14 + (index % 3) * 0.34,
));
// Deliberately exceed the number of labels that should be visible at deeper
// levels. The contract is that the cohort remains bounded, not that all names
// are painted at once.
const subgenres = Array.from({ length: 20 }, (_, index) => hierarchy(
  `sub-${index}`, 1, `Subgenre ${String(index + 1).padStart(2, "0")}`, index / 19, (index % 5) / 4,
));
const microgenres = Array.from({ length: 18 }, (_, index) => hierarchy(
  `micro-${index}`, 2, `Microgenre ${String(index + 1).padStart(2, "0")}`, index / 17, (index % 6) / 5,
));
const leaves = Array.from({ length: 12 }, (_, index) => leaf(
  `Leaf ${String.fromCharCode(65 + index)}`, (index % 4) / 3, Math.floor(index / 4) / 2,
));
const payloads = new Map([
  ["/api/historical-signal-map?level=0", { initial_edge_count: 0, hierarchy: overview }],
  ["/api/historical-signal-map?level=1&parent_id=overview-3", { hierarchy: subgenres }],
  ["/api/historical-signal-map?level=2&parent_id=sub-0", { hierarchy: microgenres }],
  ["/api/historical-signal-map?level=3&parent_id=micro-0", { nodes: leaves }],
]);
const requests = [];

const page = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"><script src="/cytoscape.js" defer></script><script src="/semantic-map.js?v=validation" defer></script></head><body>
<section id="workspace"><main id="map" data-map-view="historical"><div id="semantic-map" role="application" data-map-mode="historical" data-graph-url="/api/historical-signal-map?level=0"></div>
<section id="historical-fallback"><p>Historical compatibility overview</p><ul>${overview.map((node) => `<li><a href="/api/historical-signal-map?level=1&amp;parent_id=${node.hierarchy_id}">${node.representative_label}</a></li>`).join("")}</ul></section>
<aside id="historical-detail"></aside><div id="map-controls"><button data-map-action="historical-back">Back</button><button data-map-action="zoom-in">+</button><button data-map-action="zoom-out">−</button><button data-map-action="fit">Fit</button><button id="theme-toggle">Dark</button><label for="theme-select">Theme</label><select id="theme-select"><option value="light">Light</option><option value="dark">Dark</option><option value="system">System</option></select></div><p id="map-status" class="sr-only"></p></main>
<form id="search" role="search"><label class="sr-only" for="query">Artist or genre</label><input id="query" type="search" placeholder="Artist or genre"></form><aside id="results"></aside></section>
</body></html>`;

const server = createServer((request, response) => {
  const requestUrl = new URL(request.url ?? "/", "http://fixture.invalid");
  if (requestUrl.pathname === "/") {
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end(page);
    return;
  }
  if (requestUrl.pathname === "/cytoscape.js") {
    response.writeHead(200, { "content-type": "text/javascript" });
    response.end(cytoscapeSource);
    return;
  }
  if (requestUrl.pathname === "/semantic-map.js") {
    response.writeHead(200, { "content-type": "text/javascript" });
    response.end(mapSource);
    return;
  }
  if (requestUrl.pathname === "/app.css") {
    response.writeHead(200, { "content-type": "text/css" });
    response.end(cssSource);
    return;
  }
  if (requestUrl.pathname === "/favicon.ico") {
    response.writeHead(204);
    response.end();
    return;
  }
  const key = `${requestUrl.pathname}${requestUrl.search}`;
  if (payloads.has(key)) {
    requests.push(key);
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify(payloads.get(key)));
    return;
  }
  response.writeHead(404);
  response.end();
});

const freePort = async () => {
  const tcp = createTcpServer();
  await new Promise((resolve_, reject) => {
    tcp.once("error", reject);
    tcp.listen(0, "127.0.0.1", resolve_);
  });
  const address = tcp.address();
  if (!address || typeof address === "string") throw new Error("could not allocate local port");
  const port = address.port;
  await new Promise((resolve_) => tcp.close(resolve_));
  return port;
};

const json = async (target, options) => {
  const response = await fetch(target, options);
  if (!response.ok) throw new Error(`${target} returned ${response.status}`);
  return response.json();
};

class Cdp {
  constructor(socketUrl) {
    this.socket = new WebSocket(socketUrl);
    this.sequence = 0;
    this.pending = new Map();
    this.errors = [];
    this.socket.addEventListener("message", ({ data }) => {
      const message = JSON.parse(data);
      if (message.method === "Runtime.exceptionThrown") {
        this.errors.push(message.params.exceptionDetails.text ?? "runtime exception");
      }
      if (message.method === "Runtime.consoleAPICalled" && ["error", "assert"].includes(message.params.type)) {
        this.errors.push(message.params.args.map((argument) => argument.value ?? argument.description ?? "console error").join(" "));
      }
      if (message.method === "Log.entryAdded" && message.params.entry.level === "error") this.errors.push(message.params.entry.text);
      const entry = this.pending.get(message.id);
      if (!entry) return;
      this.pending.delete(message.id);
      if (message.error) entry.reject(new Error(JSON.stringify(message.error)));
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
      const id = ++this.sequence;
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, 15_000);
      this.pending.set(id, {
        resolve: (value) => { clearTimeout(timeout); resolve_(value); },
        reject: (error) => { clearTimeout(timeout); reject(error); },
      });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression, label = "Runtime.evaluate") {
    const response = await this.command("Runtime.evaluate", {
      expression, awaitPromise: true, returnByValue: true, userGesture: true,
    });
    if (response.exceptionDetails) throw new Error(`${label}: ${response.exceptionDetails.text}`);
    if (!response.result) throw new Error(`${label}: missing result`);
    if (response.result.subtype === "error") throw new Error(`${label}: ${response.result.description}`);
    return response.result.value;
  }

  async wait(expression, label, timeout = 15_000) {
    const started = Date.now();
    while (Date.now() - started < timeout) {
      if (await this.evaluate(expression, label)) return;
      await sleep(25);
    }
    throw new Error(`${label} timed out`);
  }

  close() { this.socket.close(); }
}

const launchChrome = async (port) => {
  const profile = `${tmpdir()}/musix-semantic-map-validation-${process.pid}`;
  await rm(profile, { recursive: true, force: true });
  const chrome = spawn("/usr/bin/chromium", [
    "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-background-networking",
    "--disable-default-apps", "--no-first-run", `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`, "about:blank",
  ], { stdio: "ignore" });
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      await json(`http://127.0.0.1:${port}/json/version`);
      return { chrome, profile };
    } catch { await sleep(25); }
  }
  chrome.kill("SIGKILL");
  throw new Error("Chromium did not expose a DevTools endpoint");
};

const viewport = async (cdp, width, height, mobile) => cdp.command("Emulation.setDeviceMetricsOverride", {
  width, height, mobile, deviceScaleFactor: 1, screenWidth: width, screenHeight: height,
});

const navigate = async (cdp, url, width, height, mobile, theme, javascript = true) => {
  await cdp.command("Emulation.setScriptExecutionDisabled", { value: !javascript });
  await viewport(cdp, width, height, mobile);
  const target = new URL(url);
  target.searchParams.set("theme", theme);
  await cdp.command("Page.navigate", { url: target.toString() });
  await cdp.wait("document.readyState === 'complete'", "document load");
  if (javascript) {
    await cdp.wait("Boolean(window.__musixMap)", "semantic map initialization");
    await cdp.wait("document.documentElement.classList.contains('js-map-ready')", "semantic map visibility");
    await sleep(100);
  }
};

const click = async (cdp, x, y) => {
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none" });
  await cdp.command("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1 });
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1 });
};

const clickSelector = async (cdp, selector) => {
  const point = await cdp.evaluate(`(() => { const element = document.querySelector(${JSON.stringify(selector)}); if (!element) return null; const box = element.getBoundingClientRect(); return { x: box.left + box.width / 2, y: box.top + box.height / 2 }; })()`, `find ${selector}`);
  if (!point) throw new Error(`selector not found: ${selector}`);
  await click(cdp, point.x, point.y);
};

const clickNode = async (cdp, id) => {
  const point = await cdp.evaluate(`(() => { const node = window.__musixMap.$id(${JSON.stringify(`historical-${id}`)}); if (node.empty()) return null; const point = node.renderedPosition(); return { x: point.x, y: point.y }; })()`, `find node ${id}`);
  if (!point) throw new Error(`node not found: ${id}`);
  await click(cdp, point.x, point.y);
};

const captureScreenshot = async (cdp, name, width, height) => {
  await mkdir(captureDirectory, { recursive: true });
  const response = await cdp.command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  const bytes = Buffer.from(response.data, "base64");
  // PNG IHDR dimensions make the screenshot check independent of CSS or CDP
  // metadata and catch a zero-sized or stale capture.
  assert(bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])), "screenshot must be a PNG");
  const pngWidth = bytes.readUInt32BE(16);
  const pngHeight = bytes.readUInt32BE(20);
  assert(pngWidth === width && pngHeight === height, "screenshot dimensions must match viewport", { pngWidth, pngHeight, width, height });
  const path = resolve(captureDirectory, name);
  await writeFile(path, bytes);
  return { path, width: pngWidth, height: pngHeight, byteSize: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") };
};

const geometry = (cdp) => cdp.evaluate(`(() => {
  const map = document.querySelector('#semantic-map');
  const mapBox = map.getBoundingClientRect();
  const cy = window.__musixMap;
  const pan = cy.pan();
  const zoom = cy.zoom();
  const overlays = ['#search', '#results', '#map-controls', '#map-view-switch', '#historical-detail']
    .map((selector) => document.querySelector(selector))
    .filter((element) => element && getComputedStyle(element).display !== 'none')
    .map((element) => element.getBoundingClientRect());
  const overlap = (first, second) => first.left < second.right && first.right > second.left && first.top < second.bottom && first.bottom > second.top;
  const viewportBox = { left: mapBox.left, right: mapBox.right, top: mapBox.top, bottom: mapBox.bottom };
  const bodyBox = (node) => {
    const body = node.renderedBoundingBox();
    return { left: mapBox.left + body.x1, right: mapBox.left + body.x2, top: mapBox.top + body.y1, bottom: mapBox.top + body.y2 };
  };
  const labelBox = (node) => {
    node.boundingBox({ includeLabels: true });
    const label = node[0]._private.labelBounds?.main;
    if (!label || !node.data('displayLabel')) return null;
    return { left: mapBox.left + label.x1 * zoom + pan.x, right: mapBox.left + label.x2 * zoom + pan.x, top: mapBox.top + label.y1 * zoom + pan.y, bottom: mapBox.top + label.y2 * zoom + pan.y };
  };
  const nodes = cy.nodes().map((node) => ({
    id: node.id(), label: node.data('label'), displayLabel: node.data('displayLabel'),
    point: node.renderedPosition(), body: bodyBox(node), labelBox: labelBox(node),
    effectiveFontSize: Number.parseFloat(node.style('font-size')) * zoom,
  }));
  const points = nodes.map((node) => node.point);
  const renderedWidth = points.length ? Math.max(...points.map((point) => point.x)) - Math.min(...points.map((point) => point.x)) : 0;
  const renderedHeight = points.length ? Math.max(...points.map((point) => point.y)) - Math.min(...points.map((point) => point.y)) : 0;
  const canvases = [...map.querySelectorAll('canvas')].map((canvas) => ({ width: canvas.width, height: canvas.height, box: canvas.getBoundingClientRect().toJSON() }));
  const readable = nodes.length === 13 && nodes.every((node) => {
    if (!node.displayLabel || !node.labelBox) return false;
    const boxes = [node.body, node.labelBox];
    return boxes.every((box) => box.left >= viewportBox.left && box.right <= viewportBox.right && box.top >= viewportBox.top && box.bottom <= viewportBox.bottom && overlays.every((overlay) => !overlap(box, overlay)));
  });
  return {
    map: { width: mapBox.width, height: mapBox.height },
    nodeCount: nodes.length,
    labels: nodes.filter((node) => Boolean(node.displayLabel)).length,
    labelsExpected: nodes.map((node) => node.label).sort(),
    readable,
    allEffectiveFontSizes: nodes.map((node) => node.effectiveFontSize),
    points,
    renderedWidth,
    renderedHeight,
    widthOccupancy: mapBox.width ? renderedWidth / mapBox.width : 0,
    heightOccupancy: mapBox.height ? renderedHeight / mapBox.height : 0,
    aspect: renderedHeight ? renderedWidth / renderedHeight : 0,
    canvasCount: canvases.length,
    liveCanvases: canvases.filter((canvas) => canvas.width > 0 && canvas.height > 0 && canvas.box.width > 0 && canvas.box.height > 0).length,
    canvases,
    zoom,
    pan,
    depth: window.__musixMapMetrics.semanticDepth,
    cohortCount: window.__musixMapMetrics.cohortCount,
    overlayCount: overlays.length,
  };
})()`);

const state = (cdp) => cdp.evaluate(`(() => ({ nodes: window.__musixMap.nodes().length, elements: window.__musixMap.elements().length, depth: window.__musixMapMetrics.semanticDepth, cohortCount: window.__musixMapMetrics.cohortCount, requests: ${JSON.stringify(requests.length)}, zoom: window.__musixMap.zoom(), pan: window.__musixMap.pan() }))()`);

const assert = (condition, message, details = undefined) => {
  if (!condition) throw new Error(details === undefined ? message : `${message}: ${JSON.stringify(details)}`);
};

const report = { contract: "semantic-map-usability-v1", viewport: {}, overview: {}, mobile: {}, bounded: {}, responsiveness: {}, themes: {}, fallback: {} };
let serverAddress;
let chrome;
let profile;
let cdp;
try {
  await new Promise((resolve_, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve_);
  });
  serverAddress = server.address();
  if (!serverAddress || typeof serverAddress === "string") throw new Error("fixture did not bind a TCP port");
  const url = `http://127.0.0.1:${serverAddress.port}/`;
  const chromePort = await freePort();
  ({ chrome, profile } = await launchChrome(chromePort));
  const target = await json(`http://127.0.0.1:${chromePort}/json/new?about:blank`, { method: "PUT" });
  cdp = new Cdp(target.webSocketDebuggerUrl);
  await cdp.connect();
  await cdp.command("Page.enable");
  await cdp.command("Runtime.enable");
  await cdp.command("Log.enable");

  await navigate(cdp, url, 1440, 900, false, "light");
  const desktop = await geometry(cdp);
  report.viewport.desktop = desktop.map;
  report.overview = desktop;
  assert(desktop.nodeCount === 13, "overview node count must be 13", desktop);
  assert(desktop.labels === 13, "all 13 overview labels must be painted", desktop);
  assert(JSON.stringify(desktop.labelsExpected) === JSON.stringify([...umbrellaLabels].sort()), "overview labels changed", desktop.labelsExpected);
  assert(desktop.widthOccupancy >= 0.65 && desktop.heightOccupancy >= 0.65 && desktop.aspect >= 1.15, "overview must occupy a landscape viewport", desktop);
  assert(desktop.readable && Math.min(...desktop.allEffectiveFontSizes) >= 12, "overview labels must be readable, within the map, and unobscured", desktop);
  assert(desktop.liveCanvases > 0, "overview must have a non-zero canvas", desktop);
  assert(desktop.overlayCount >= 2, "fixture must include search and map controls", desktop);
  report.overviewScreenshot = await captureScreenshot(cdp, "semantic-map-validation-desktop.png", 1440, 900);

  const initial = await state(cdp);
  assert(initial.nodes === 13 && initial.elements <= 24 && initial.depth === 0, "initial cohort must be bounded", initial);
  const initialRequestCount = requests.length;

  // Real wheel and drag events are a responsiveness proxy. Camera changes must
  // happen promptly without fetching another semantic cohort.
  const beforeZoom = await state(cdp);
  await cdp.evaluate("window.__responsivenessStart = performance.now()");
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseWheel", x: 720, y: 500, deltaX: 0, deltaY: -180, pointerType: "mouse" });
  const afterZoom = await state(cdp);
  const zoomLatencyMs = await cdp.evaluate("performance.now() - window.__responsivenessStart");
  assert(afterZoom.zoom !== beforeZoom.zoom, "wheel zoom must change camera", { beforeZoom, afterZoom });
  assert(zoomLatencyMs < 500, "wheel zoom responsiveness exceeded proxy budget", zoomLatencyMs);
  const beforePan = await state(cdp);
  await cdp.evaluate("window.__responsivenessStart = performance.now()");
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseMoved", x: 720, y: 500, button: "none" });
  await cdp.command("Input.dispatchMouseEvent", { type: "mousePressed", x: 720, y: 500, button: "left", buttons: 1, clickCount: 1 });
  for (let step = 1; step <= 6; step += 1) {
    await cdp.command("Input.dispatchMouseEvent", {
      type: "mouseMoved", x: 720 + (70 * step) / 6, y: 500 + (40 * step) / 6, button: "left", buttons: 1,
    });
  }
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseReleased", x: 790, y: 540, button: "left", buttons: 0, clickCount: 1 });
  const afterPan = await state(cdp);
  const panLatencyMs = await cdp.evaluate("performance.now() - window.__responsivenessStart");
  assert(afterPan.pan.x !== beforePan.pan.x || afterPan.pan.y !== beforePan.pan.y, "drag pan must change camera", { beforePan, afterPan });
  assert(panLatencyMs < 500, "drag pan responsiveness exceeded proxy budget", panLatencyMs);
  assert(afterPan.nodes === 13 && afterPan.depth === 0 && requests.length === initialRequestCount, "camera interaction must preserve cohort and avoid fetches", { afterPan, requests });
  report.responsiveness = { zoomLatencyMs, panLatencyMs, beforeZoom, afterZoom, beforePan, afterPan };

  const drillCounts = [];
  const drill = async (id, label, depth) => {
    await clickNode(cdp, id);
    await cdp.wait(`window.__musixMapMetrics.semanticDepth === ${depth} && window.__musixMap.nodes().length > 0`, `${label} drill`);
    await sleep(50);
    const drilled = await state(cdp);
    assert(drilled.elements <= 24 && drilled.nodes <= 24, `${label} cohort must remain bounded`, drilled);
    drillCounts.push({ depth, ...drilled });
  };
  await drill("overview-3", "level 1", 1);
  await drill("sub-0", "level 2", 2);
  await drill("micro-0", "level 3", 3);
  const leafState = await state(cdp);
  const beforeLeafCameraRequests = requests.length;
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseWheel", x: 620, y: 420, deltaX: 0, deltaY: -120, pointerType: "mouse" });
  assert((await state(cdp)).nodes === leafState.nodes && requests.length === beforeLeafCameraRequests, "leaf camera interaction must stay bounded and semantic", { leafState, after: await state(cdp) });
  for (let depth = 2; depth >= 0; depth -= 1) {
    await clickSelector(cdp, '[data-map-action="historical-back"]');
    await cdp.wait(`window.__musixMapMetrics.semanticDepth === ${depth}`, `back to depth ${depth}`);
  }
  const restored = await state(cdp);
  assert(restored.nodes === 13 && restored.elements <= 24 && restored.depth === 0 && restored.cohortCount === 0, "Back must restore bounded overview cohort", restored);
  report.bounded = { initial, drillCounts, leafState, restored, requests: [...requests] };

  await cdp.evaluate("document.querySelector('#theme-toggle').click()");
  await cdp.wait("document.documentElement.dataset.theme === 'dark'", "dark theme");
  const darkTheme = await cdp.evaluate("({ theme: document.documentElement.dataset.theme, canvas: getComputedStyle(document.documentElement).getPropertyValue('--canvas').trim(), ink: getComputedStyle(document.documentElement).getPropertyValue('--ink').trim() })");
  await cdp.evaluate("document.querySelector('#theme-toggle').click()");
  await cdp.wait("document.documentElement.dataset.theme === 'light'", "light theme");
  const lightTheme = await cdp.evaluate("({ theme: document.documentElement.dataset.theme, canvas: getComputedStyle(document.documentElement).getPropertyValue('--canvas').trim(), ink: getComputedStyle(document.documentElement).getPropertyValue('--ink').trim() })");
  assert(darkTheme.canvas && darkTheme.ink && lightTheme.canvas && lightTheme.ink && darkTheme.canvas !== lightTheme.canvas && darkTheme.ink !== lightTheme.ink, "dark and light themes must have distinct readable tokens", { lightTheme, darkTheme });
  report.themes = { light: lightTheme, dark: darkTheme };

  await navigate(cdp, url, 390, 844, true, "dark");
  const mobile = await geometry(cdp);
  report.viewport.mobile = mobile.map;
  report.mobile = mobile;
  assert(mobile.nodeCount === 13 && mobile.labels === 13 && mobile.readable, "mobile overview must retain all readable labels", mobile);
  assert(mobile.liveCanvases > 0 && mobile.map.width > 0 && mobile.map.height > 0, "mobile map must have a non-zero canvas", mobile);
  assert(Math.min(...mobile.allEffectiveFontSizes) >= 12, "mobile labels must remain readable", mobile);
  report.mobileScreenshot = await captureScreenshot(cdp, "semantic-map-validation-mobile.png", 390, 844);

  await navigate(cdp, url, 390, 844, true, "light", false);
  const fallback = await cdp.evaluate("(() => { const element = document.querySelector('#historical-fallback'); const map = document.querySelector('#semantic-map'); const box = element.getBoundingClientRect(); return { visible: getComputedStyle(element).display !== 'none', links: element.querySelectorAll('a').length, mapDisplay: getComputedStyle(map).display, fallbackSize: { width: box.width, height: box.height } }; })()");
  assert(fallback.visible && fallback.links === 13 && fallback.mapDisplay === "none" && fallback.fallbackSize.width > 0 && fallback.fallbackSize.height > 0, "no-JavaScript mobile fallback must remain usable", fallback);
  report.fallback = fallback;

  const expectedRequests = [...payloads.keys()];
  // A no-JavaScript navigation can replay the initial URL while the browser
  // tears down the prior document. It is harmless, but no drill or unknown
  // route may be fetched beyond the four interactive requests.
  assert(JSON.stringify(requests.slice(0, expectedRequests.length)) === JSON.stringify(expectedRequests), "fixture request sequence changed during map interaction", requests);
  assert(requests.every((request) => payloads.has(request)) && requests.slice(expectedRequests.length).every((request) => request === expectedRequests[0]), "fixture requests must stay bounded", { requests, expected: expectedRequests });
  assert(cdp.errors.length === 0, "browser emitted runtime or console errors", cdp.errors);
  process.stdout.write(`${JSON.stringify(report)}\n`);
} finally {
  cdp?.close();
  if (chrome) {
    chrome.kill("SIGTERM");
    await new Promise((resolve_) => chrome.once("exit", resolve_));
  }
  if (profile) await rm(profile, { recursive: true, force: true });
  await new Promise((resolve_) => server.close(resolve_));
}
