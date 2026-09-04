#!/usr/bin/env node

/**
 * Exercise historical-map rendering with a deliberately synthetic hierarchy.
 * The fixture tests navigation mechanics and renderer bounds only; it does
 * not claim that these labels or parent relationships are musically correct.
 */

import { createServer } from "node:http";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { spawn } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const mapSource = await readFile(resolve(root, "src/musix/static/semantic-map.js"), "utf8");
const cytoscapeSource = await readFile(resolve(root, "src/musix/static/cytoscape-3.34.0.min.js"), "utf8");
const cssSource = await readFile(resolve(root, "src/musix/static/app.css"), "utf8");
const requests = [];
const hierarchy = (id, level, label, x = level + 0.15, y = level + 0.25) => ({
  hierarchy_id: id, level, representative_genre_id: `${id}-representative`,
  representative_label: label, member_count: 3, x, y,
});
const leaf = (id, x, y) => ({ genre_id: id, name: id, membership_count: 1, x, y });
const overview = Array.from({ length:12 }, (_, index) => hierarchy(
  `overview-${index}`, 0, `Overview ${String(index + 1).padStart(2, "0")}`,
  index / 11, 0.500 + (index % 2) * 0.00001,
));
const payloads = new Map([
  ["/api/historical-signal-map?level=0", { initial_edge_count: 0, hierarchy: overview }],
  ["/api/historical-signal-map?level=1&parent_id=overview-3", { hierarchy: [hierarchy("sub", 1, "Subgenre")] }],
  ["/api/historical-signal-map?level=2&parent_id=sub", { hierarchy: [hierarchy("micro", 2, "Microgenre")] }],
  ["/api/historical-signal-map?level=3&parent_id=micro", { nodes: [leaf("Leaf A", 0.1, 0.2), leaf("Leaf B", 0.8, 0.7), leaf("Leaf C", 0.5, 0.4)] }],
]);
const page = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"><script src="/cytoscape.js" defer></script><script src="/semantic-map.js" defer></script></head><body>
<section id="workspace"><main id="map" data-map-view="historical"><div id="semantic-map" role="application" data-map-mode="historical" data-graph-url="/api/historical-signal-map?level=0"></div>
<section id="historical-fallback"><p>Historical compatibility overview</p><ul>${overview.map((node) => `<li><a href="/api/historical-signal-map?level=1&amp;parent_id=${node.hierarchy_id}">${node.representative_label}</a></li>`).join("")}</ul></section>
<aside id="historical-detail"></aside><div id="map-controls"><button data-map-action="historical-back">Back</button><button data-map-action="zoom-in">+</button><button data-map-action="zoom-out">−</button><button data-map-action="fit">Fit</button><button id="theme-toggle">Dark</button><label for="theme-select">Theme</label><select id="theme-select"><option value="light">Light</option><option value="dark">Dark</option><option value="system">System</option></select></div><p id="map-status" class="sr-only"></p></main>
<form id="search" role="search"><label class="sr-only" for="query">Artist or genre</label><input id="query" type="search" placeholder="Artist or genre"></form><aside id="results"></aside></section>
</body></html>`;
const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", "http://fixture.invalid");
  if (url.pathname === "/") {
    response.writeHead(200, { "content-type": "text/html" }); response.end(page); return;
  }
  if (url.pathname === "/cytoscape.js") { response.writeHead(200, { "content-type": "text/javascript" }); response.end(cytoscapeSource); return; }
  if (url.pathname === "/semantic-map.js") { response.writeHead(200, { "content-type": "text/javascript" }); response.end(mapSource); return; }
  if (url.pathname === "/app.css") { response.writeHead(200, { "content-type": "text/css" }); response.end(cssSource); return; }
  const key = `${url.pathname}${url.search}`;
  if (payloads.has(key)) {
    requests.push(key); response.writeHead(200, { "content-type": "application/json" }); response.end(JSON.stringify(payloads.get(key))); return;
  }
  response.writeHead(404); response.end();
});
await new Promise((resolve_) => server.listen(0, "127.0.0.1", resolve_));
const address = server.address();
if (!address || typeof address === "string") throw new Error("fixture did not bind a TCP port");
const url = `http://127.0.0.1:${address.port}/`;
const chromePort = 9427;
const sleep = (milliseconds) => new Promise((resolve_) => setTimeout(resolve_, milliseconds));
const json = async (target, options) => {
  const response = await fetch(target, options);
  if (!response.ok) throw new Error(`${target} returned ${response.status}`);
  return response.json();
};
class Cdp {
  constructor(socketUrl) {
    this.socket = new WebSocket(socketUrl); this.sequence = 0; this.pending = new Map(); this.errors = [];
    this.socket.addEventListener("message", ({ data }) => {
      const message = JSON.parse(data);
      if (message.method === "Runtime.exceptionThrown") this.errors.push(message.params.exceptionDetails.text);
      const pending = this.pending.get(message.id); if (!pending) return;
      this.pending.delete(message.id); message.error ? pending.reject(new Error(JSON.stringify(message.error))) : pending.resolve(message.result ?? {});
    });
  }
  async connect() { await new Promise((resolve_, reject) => { this.socket.addEventListener("open", resolve_, { once:true }); this.socket.addEventListener("error", reject, { once:true }); }); }
  command(method, params = {}) { return new Promise((resolve_, reject) => { const id = ++this.sequence; this.pending.set(id, { resolve:resolve_, reject }); this.socket.send(JSON.stringify({ id, method, params })); }); }
  async evaluate(expression) {
    const response = await this.command("Runtime.evaluate", { expression, awaitPromise:true, returnByValue:true, userGesture:true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
    return response.result?.value;
  }
  async wait(expression, label) { for (let count = 0; count < 120; count += 1) { if (await this.evaluate(expression)) return; await sleep(25); } throw new Error(`timed out: ${label}`); }
}
const profile = `${tmpdir()}/musix-historical-browser-${process.pid}`;
const captureDirectory = resolve(root, ".cache/ui-qa");
const screenshot = async (cdp, name) => {
  await mkdir(captureDirectory, { recursive:true });
  const response = await cdp.command("Page.captureScreenshot", { format:"png", captureBeyondViewport:false });
  const path = resolve(captureDirectory, name);
  const bytes = Buffer.from(response.data, "base64");
  await writeFile(path, bytes);
  return { path, byte_size:bytes.length };
};
const chrome = spawn("/usr/bin/chromium", ["--headless=new", "--no-sandbox", "--disable-gpu", `--remote-debugging-port=${chromePort}`, `--user-data-dir=${profile}`, "about:blank"], { stdio:"ignore" });
try {
  for (let count = 0; count < 120; count += 1) { try { await json(`http://127.0.0.1:${chromePort}/json/version`); break; } catch { await sleep(25); } }
  const target = await json(`http://127.0.0.1:${chromePort}/json/new?about:blank`, { method:"PUT" });
  const cdp = new Cdp(target.webSocketDebuggerUrl); await cdp.connect(); await cdp.command("Page.enable"); await cdp.command("Runtime.enable");
  const viewport = async (width, height, mobile = false) => cdp.command("Emulation.setDeviceMetricsOverride", { width, height, mobile, deviceScaleFactor:1, screenWidth:width, screenHeight:height });
  await viewport(1366, 768); await cdp.command("Page.navigate", { url });
  await cdp.wait("Boolean(window.__musixMap)", "historical map init");
  // Cytoscape's renderer calculates label geometry on its first animation frame.
  await sleep(120);
  await cdp.wait(
    "window.__musixMap.nodes().filter(n => Boolean(n.data('displayLabel'))).length === window.__musixMap.nodes().length",
    "initial overview labels",
  );
  const nodeLabels = () => cdp.evaluate("window.__musixMap.nodes().map(n => n.data('label')).sort()");
  const clickNode = async (id) => {
    const point = await cdp.evaluate(`(() => { const node=window.__musixMap.$id(${JSON.stringify(`historical-${id}`)}); const point=node.renderedPosition(); return {x:point.x,y:point.y}; })()`);
    await cdp.command("Input.dispatchMouseEvent", { type:"mousePressed", x:point.x, y:point.y, button:"left", buttons:1, clickCount:1 });
    await cdp.command("Input.dispatchMouseEvent", { type:"mouseReleased", x:point.x, y:point.y, button:"left", buttons:0, clickCount:1 });
  };
  const waitLabel = async (label, depth) => {
    await cdp.wait(`window.__musixMap.nodes().some(n => n.data('label') === ${JSON.stringify(label)}) && window.__musixMapMetrics.semanticDepth === ${depth}`, `${label} depth ${depth}`);
  };
  const overviewGeometry = await cdp.evaluate(`(() => {
    const map=document.querySelector('#semantic-map').getBoundingClientRect();
    const nodes=window.__musixMap.nodes(); const points=nodes.map(node => node.renderedPosition());
    const labels=nodes.filter(node => Boolean(node.data('displayLabel'))).length;
    return { nodeCount:nodes.length, labels, width:(Math.max(...points.map(point => point.x))-Math.min(...points.map(point => point.x)))/map.width,
      height:(Math.max(...points.map(point => point.y))-Math.min(...points.map(point => point.y)))/map.height };
  })()`);
  const readyLayout = await cdp.evaluate(`(() => {
    const fallback=document.querySelector('#historical-fallback'); const search=document.querySelector('#search').getBoundingClientRect(); const controls=document.querySelector('#map-controls').getBoundingClientRect();
    const overlap=search.left < controls.right && search.right > controls.left && search.top < controls.bottom && search.bottom > controls.top;
    const map=document.querySelector('#semantic-map').getBoundingClientRect();
    const overlays=[search, controls]; const cy=window.__musixMap;
    const intersects=(first, second) => first.left < second.right && first.right > second.left && first.top < second.bottom && first.bottom > second.top;
    const unobscured=cy.nodes().every(node => {
      const circle=node.renderedBoundingBox();
      node.boundingBox({includeLabels:true}); const label=node[0]._private.labelBounds.main;
      const pan=cy.pan(); const zoom=cy.zoom();
      const boxes=[{left:map.left + circle.x1, right:map.left + circle.x2, top:map.top + circle.y1, bottom:map.top + circle.y2}];
      if (node.data('displayLabel') && label) boxes.push({left:map.left + label.x1 * zoom + pan.x, right:map.left + label.x2 * zoom + pan.x, top:map.top + label.y1 * zoom + pan.y, bottom:map.top + label.y2 * zoom + pan.y});
      return boxes.every(box => box.left >= map.left && box.right <= map.right && box.top >= map.top && box.bottom <= map.bottom
        && overlays.every(overlay => !intersects(box, overlay)));
    });
    return { fallbackHidden:getComputedStyle(fallback).display === 'none', controlsSearchSeparate:!overlap, nodesAndLabelsUnobscured:unobscured };
  })()`);
  const desktopScreenshot = await screenshot(cdp, "historical-landscape-desktop.png");
  await clickNode("overview-3"); await waitLabel("Subgenre", 1);
  await clickNode("sub"); await waitLabel("Microgenre", 2);
  await clickNode("micro"); await waitLabel("Leaf A", 3);
  const leaves = await nodeLabels();
  const beforeCameraRequests = requests.length;
  await cdp.command("Input.dispatchMouseEvent", { type:"mouseWheel", x:600, y:360, deltaX:0, deltaY:-220, pointerType:"mouse" });
  await cdp.command("Input.dispatchMouseEvent", { type:"mousePressed", x:600, y:360, button:"left", buttons:1, clickCount:1 });
  await cdp.command("Input.dispatchMouseEvent", { type:"mouseMoved", x:660, y:390, button:"left", buttons:1 });
  await cdp.command("Input.dispatchMouseEvent", { type:"mouseReleased", x:660, y:390, button:"left", buttons:0, clickCount:1 });
  await sleep(80);
  if (JSON.stringify(leaves) !== JSON.stringify(await nodeLabels()) || requests.length !== beforeCameraRequests) throw new Error("camera interaction changed the semantic cohort or fetched global tiles");
  const clickBack = async () => { await cdp.evaluate("document.querySelector('[data-map-action=historical-back]').click()"); await sleep(50); };
  await clickBack(); await waitLabel("Microgenre", 2);
  await clickBack(); await waitLabel("Subgenre", 1);
  await clickBack(); await waitLabel("Overview 01", 0);
  const depthAndStack = await cdp.evaluate("({depth:window.__musixMapMetrics.semanticDepth, stack:window.__musixMapMetrics.cohortCount, back:document.querySelector('[data-map-action=historical-back]').disabled})");
  await viewport(390, 844, true); await sleep(80);
  const mobileState = await cdp.evaluate("(() => { const map=document.querySelector('#semantic-map'); const c=[...map.querySelectorAll('canvas')]; const box=map.getBoundingClientRect(); const query=document.querySelector('#query'); const cy=window.__musixMap; return { live:c.some(x => x.width > 0 && x.height > 0) && cy.nodes().length === 12, canvas:c.map(x => ({width:x.width,height:x.height})), box:{width:box.width,height:box.height}, viewportWidth:innerWidth, queryFontSize:Number.parseFloat(getComputedStyle(query).fontSize), labelFontSize:Number.parseFloat(cy.nodes().first().style('font-size')) * cy.zoom(), zoom:cy.zoom(), nodes:cy.nodes().length }; })()");
  const mobileLive = mobileState.live && mobileState.viewportWidth === 390 && mobileState.queryFontSize >= 12 && mobileState.labelFontSize >= 12;
  await cdp.evaluate("document.querySelector('#theme-toggle').click()"); await cdp.wait("document.documentElement.dataset.theme === 'dark'", "dark theme");
  const mobileScreenshot = await screenshot(cdp, "historical-landscape-mobile.png");
  await cdp.command("Emulation.setScriptExecutionDisabled", { value:true }); await cdp.command("Page.navigate", { url });
  await cdp.wait("document.readyState === 'complete'", "no-JS document");
  const noJs = await cdp.evaluate("(() => { const fallback=document.querySelector('#historical-fallback'); return Boolean(fallback && fallback.querySelectorAll('a').length === 12 && getComputedStyle(fallback).display !== 'none'); })()");
  const expectedRequests = [...payloads.keys()];
  const geometryPasses = overviewGeometry.labels === overviewGeometry.nodeCount && overviewGeometry.width >= 0.7 && overviewGeometry.height >= 0.45;
  if (JSON.stringify(requests) !== JSON.stringify(expectedRequests) || !geometryPasses || !readyLayout.fallbackHidden || !readyLayout.controlsSearchSeparate || !readyLayout.nodesAndLabelsUnobscured || !mobileLive || !noJs || depthAndStack.depth !== 0 || depthAndStack.stack !== 0 || !depthAndStack.back || cdp.errors.length) {
    throw new Error(JSON.stringify({ requests, expectedRequests, overviewGeometry, geometryPasses, readyLayout, mobileState, noJs, depthAndStack, errors:cdp.errors }));
  }
  process.stdout.write(`${JSON.stringify({ requests, leaves, overviewGeometry, readyLayout, desktopScreenshot, mobileScreenshot, mobileState, mobileLive, noJs, depthAndStack })}\n`);
} finally {
  chrome.kill("SIGTERM"); await new Promise((resolve_) => chrome.once("exit", resolve_));
  await rm(profile, { recursive:true, force:true }); await new Promise((resolve_) => server.close(resolve_));
}
