#!/usr/bin/env node

/** Run repeatable Chromium/CDP evidence for the single Open v2 surface. */

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

const args = process.argv.slice(2);
const url = args[0];
const focusedOnly = args.includes("--focused");
const output = resolve(args[1] ?? ".cache/open-v2-runtime-qa/browser");
const artifactPath = resolve(args[2] ?? "data/model/open-construction-graph-v2.json");
if (!url) throw new Error("usage: capture_open_construction_v2_browser.mjs URL [OUTPUT] [ARTIFACT]");
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const port = 9400 + (process.pid % 500);

class Cdp {
  constructor(socketUrl) {
    this.socket = new WebSocket(socketUrl);
    this.pending = new Map();
    this.sequence = 0;
    this.runtimeErrors = [];
    this.mapRequests = [];
    this.socket.addEventListener("message", ({ data }) => {
      const message = JSON.parse(data);
      if (message.method === "Runtime.exceptionThrown") this.runtimeErrors.push(message.params.exceptionDetails.text);
      if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
        this.runtimeErrors.push(message.params.args.map((item) => item.value ?? item.description ?? "error").join(" "));
      }
      if (message.method === "Network.requestWillBeSent" && message.params.request.url.includes("/api/open-construction-map/v2")) {
        this.mapRequests.push(message.params.request.url);
      }
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(`${pending.method}: ${JSON.stringify(message.error)}`));
      else pending.resolve(message.result ?? {});
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
        method,
        resolve: (value) => { clearTimeout(timeout); resolve_(value); },
        reject: (error) => { clearTimeout(timeout); reject(error); },
      });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.command("Runtime.evaluate", {
      expression, returnByValue: true, awaitPromise: true, userGesture: true,
    });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text ?? "browser evaluation failed");
    return result.result?.value;
  }

  async waitFor(expression, label, timeout = 15_000) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      if (await this.evaluate(expression)) return;
      await sleep(50);
    }
    throw new Error(`${label} did not become true`);
  }
}

async function json(url_, options) {
  const response = await fetch(url_, options);
  if (!response.ok) throw new Error(`${url_} returned ${response.status}`);
  return response.json();
}

async function launch() {
  const profile = `${tmpdir()}/musix-open-v2-cdp-${process.pid}`;
  await rm(profile, { recursive: true, force: true });
  const chrome = spawn("/usr/bin/chromium", [
    "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-background-networking",
    "--disable-default-apps", "--no-first-run", `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`, "about:blank",
  ], { stdio: "ignore" });
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try { await json(`http://127.0.0.1:${port}/json/version`); break; }
    catch { await sleep(50); }
    if (attempt === 99) throw new Error("Chromium did not expose DevTools");
  }
  const target = await json(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" });
  const cdp = new Cdp(target.webSocketDebuggerUrl);
  await cdp.connect();
  await cdp.command("Page.enable");
  await cdp.command("Runtime.enable");
  await cdp.command("Network.enable");
  return { chrome, cdp, profile };
}

async function navigate(cdp, viewport, theme, javascript = true) {
  await cdp.command("Emulation.setScriptExecutionDisabled", { value: !javascript });
  await cdp.command("Emulation.setDeviceMetricsOverride", {
    width: viewport.width, height: viewport.height, deviceScaleFactor: 1,
    mobile: viewport.mobile, screenWidth: viewport.width, screenHeight: viewport.height,
  });
  await cdp.command("Emulation.setTouchEmulationEnabled", { enabled: viewport.mobile, maxTouchPoints: viewport.mobile ? 5 : 1 });
  await cdp.command("Emulation.setEmulatedMedia", { media: "screen", features: [{ name: "prefers-color-scheme", value: theme }] });
  const target = new URL(url);
  target.searchParams.set("theme", theme);
  target.searchParams.set("browser_evidence", `${Date.now()}-${viewport.name}-${javascript}`);
  await cdp.command("Page.navigate", { url: target.toString() });
  await cdp.waitFor("document.readyState === 'complete'", "document load");
  if (javascript) await cdp.waitFor("Boolean(window.__musixMap) && document.documentElement.classList.contains('js-map-ready')", "map initialization");
}

async function click(cdp, x, y) {
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none" });
  await cdp.command("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1 });
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1 });
}

async function drag(cdp, x, y, toX, toY) {
  await cdp.command("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1 });
  for (let step = 1; step <= 8; step += 1) {
    await cdp.command("Input.dispatchMouseEvent", { type: "mouseMoved", x: x + ((toX - x) * step) / 8, y: y + ((toY - y) * step) / 8, button: "left", buttons: 1 });
  }
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseReleased", x: toX, y: toY, button: "left", buttons: 0, clickCount: 1 });
}

async function box(cdp, selector) {
  return cdp.evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)}); if (!e || e.hidden) return null; const b = e.getBoundingClientRect(); return {x:b.x,y:b.y,width:b.width,height:b.height}; })()`);
}

async function screenshot(cdp, path) {
  const result = await cdp.command("Page.captureScreenshot", { format: "png" });
  const bytes = Buffer.from(result.data, "base64");
  await writeFile(path, bytes);
  return { path, byte_size: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") };
}

const assert = (condition, message) => { if (!condition) throw new Error(message); };

async function liveMetrics(cdp) {
  return cdp.evaluate(`(() => {
    const map = document.querySelector('#semantic-map').getBoundingClientRect();
    const cy = window.__musixMap;
    const labels = cy.nodes(':visible').filter(node => Boolean(node.data('displayLabel')));
    const nodes = cy.nodes(':visible');
    const world = cy.nodes().boundingBox({ includeLabels: false });
    const labelBounds = labels.map((node) => {
      node.boundingBox({ includeLabels: true });
      const raw = node[0]._private.labelBounds.main;
      const pan = cy.pan();
      const zoom = cy.zoom();
      return {
        x1: raw.x1 * zoom + pan.x, y1: raw.y1 * zoom + pan.y,
        x2: raw.x2 * zoom + pan.x, y2: raw.y2 * zoom + pan.y,
        font: Number.parseFloat(node.style("font-size")) * zoom,
      };
    });
    let labelOverlaps = 0;
    for (let left = 0; left < labelBounds.length; left += 1) {
      for (let right = left + 1; right < labelBounds.length; right += 1) {
        const first = labelBounds[left];
        const second = labelBounds[right];
        if (first.x1 < second.x2 && first.x2 > second.x1 && first.y1 < second.y2 && first.y2 > second.y1) labelOverlaps += 1;
      }
    }
    const boundsOk = nodes.every(node => { const b = node.renderedBoundingBox(); return b.x1 >= 0 && b.y1 >= 0 && b.x2 <= map.width && b.y2 <= map.height; });
    return { ...(window.__musixMapMetrics ?? {}), visibleNodes:nodes.length, visibleEdges:cy.edges(':visible').length, labels:labels.length,
      boundsOk, worldAspect:world.w / Math.max(world.h, 0.0001), labelOverlaps,
      labelFontMin:labelBounds.length ? Math.min(...labelBounds.map((item) => item.font)) : 0,
      occupancyWidth:world.w * cy.zoom() / map.width, occupancyHeight:world.h * cy.zoom() / map.height,
      hiddenNodes:cy.nodes('.neighborhood-hidden').length,
      selectedLabel:Boolean(cy.nodes(':selected').filter(node => Boolean(node.data('displayLabel'))).length),
      visibleIds:nodes.map(node => node.id()).sort(),
      zoom:cy.zoom(), pan:cy.pan(), backHidden:Boolean(document.querySelector('[data-map-action="open-back"]')?.hidden),
      selected:cy.nodes(':selected').length, map:{width:map.width,height:map.height} };
  })()`);
}

async function main() {
  await mkdir(output, { recursive: true });
  const artifact = JSON.parse(await readFile(artifactPath, "utf8"));
  const endpoints = new Set(artifact.edges.flatMap((edge) => [edge.source_node_id, edge.target_node_id]));
  const isolate = artifact.nodes.find((node) => !endpoints.has(node.node_id));
  assert(isolate, "artifact has no isolated node for all-name search evidence");
  const isolateLayout = artifact.layout.find((item) => item.node_id === isolate.node_id);
  assert(isolateLayout, "isolated node has no layout coordinate");
  const { chrome, cdp, profile } = await launch();
  const captures = {};
  const checks = {};
  try {
    await navigate(cdp, { name: "desktop", width: 1366, height: 768, mobile: false }, "light");
    await sleep(500);
    const initial = await liveMetrics(cdp);
    if (focusedOnly) {
      const selectedId = "catalog:wikidata:genre:Q7749";
      const expectedIds = artifact.edges
        .filter((edge) => edge.source_node_id === selectedId || edge.target_node_id === selectedId)
        .flatMap((edge) => [edge.source_node_id, edge.target_node_id]);
      const expectedCohort = [...new Set([selectedId, ...expectedIds])].sort();
      const query = await box(cdp, "#query");
      await click(cdp, query.x + 40, query.y + query.height / 2);
      await cdp.command("Input.insertText", { text: "rock and roll" });
      await cdp.waitFor(
        `Boolean(document.querySelector('[data-open-node-id=${JSON.stringify(selectedId)}]'))`,
        "rock and roll search result",
      );
      const result = await box(cdp, `[data-open-node-id="${selectedId}"]`);
      await click(cdp, result.x + result.width / 2, result.y + result.height / 2);
      await cdp.waitFor(
        `document.querySelector('#semantic-map').dataset.openSelectedNodeId === ${JSON.stringify(selectedId)}`,
        "selected local neighborhood",
      );
      const selected = await cdp.evaluate(`(() => {
        const map = document.querySelector('#semantic-map');
        return {
          selected: map.dataset.openSelectedNodeId,
          ids: JSON.parse(map.dataset.openRenderedNodeIds ?? '[]'),
          labels: JSON.parse(map.dataset.openRenderedLabels ?? '[]'),
          camera: JSON.parse(map.dataset.openCamera ?? '{}'),
          canvases: map.querySelectorAll('canvas').length,
          cyNodes: window.__musixMap.nodes().length,
          cyEdges: window.__musixMap.edges().length,
        };
      })()`);
      checks.focused_exact_local_cohort = selected.selected === selectedId
        && JSON.stringify(selected.ids.sort()) === JSON.stringify(expectedCohort)
        && ["rock and roll", "rock music", "rockabilly", "rock-and-roll"].every((label) => selected.labels.includes(label))
        && Number.isFinite(selected.camera.zoom)
        && Object.values(selected.camera.bounds ?? {}).every(Number.isFinite)
        && selected.canvases === 3
        && selected.cyNodes === expectedCohort.length
        && selected.cyEdges === 3;
      const back = await box(cdp, '[data-map-action="open-back"]');
      await click(cdp, back.x + back.width / 2, back.y + back.height / 2);
      await cdp.waitFor(
        "window.__musixMapMetrics.level === 0 && !document.querySelector('#semantic-map').dataset.openSelectedNodeId",
        "Back overview restoration",
      );
      const restored = await liveMetrics(cdp);
      checks.focused_back_restores_overview = restored.backHidden
        && restored.visibleNodes === initial.visibleNodes
        && JSON.stringify(restored.visibleIds) === JSON.stringify(initial.visibleIds);
      assert(cdp.runtimeErrors.length === 0, `runtime errors: ${cdp.runtimeErrors.join("; ")}`);
      assert(Object.values(checks).every(Boolean), `failed checks: ${Object.entries(checks).filter(([, value]) => !value).map(([name]) => name).join(", ")}`);
      console.log(JSON.stringify(checks));
      return;
    }
    checks.initial_square_fit_and_labels = initial.boundsOk && initial.labels >= 16 && initial.labelFontMin >= 12
      && initial.labelOverlaps === 0 && initial.worldAspect > 1.1
      && initial.occupancyWidth > 0.55 && initial.occupancyHeight > 0.55;
    captures.desktop_light = await screenshot(cdp, `${output}/desktop-light.png`);
    const map = await box(cdp, "#semantic-map");
    const beforeZoomRequests = cdp.mapRequests.length;
    const zoomIn = await box(cdp, '[data-map-action="zoom-in"]');
    await click(cdp, zoomIn.x + zoomIn.width / 2, zoomIn.y + zoomIn.height / 2);
    await sleep(700);
    const zoomed = await liveMetrics(cdp);
    checks.zoom_lod_and_label_growth = zoomed.level > initial.level && zoomed.labels > initial.labels;
    const afterZoomRequests = cdp.mapRequests.length;
    const beforePanIds = zoomed.visibleIds;
    await drag(cdp, map.x + map.width * 0.25, map.y + map.height * 0.42, map.x + map.width * 0.75, map.y + map.height * 0.62);
    await sleep(700);
    const afterPanRequests = cdp.mapRequests.length;
    const afterPan = await liveMetrics(cdp);
    checks.pan_changes_viewport_cohort = afterPanRequests > afterZoomRequests && afterPanRequests > beforeZoomRequests
      && JSON.stringify(afterPan.visibleIds) !== JSON.stringify(beforePanIds);
    const settledRequests = cdp.mapRequests.length;
    await sleep(1200);
    checks.fetches_quiesce_after_camera = cdp.mapRequests.length === settledRequests;
    await navigate(cdp, { name: "desktop-dark", width: 1366, height: 768, mobile: false }, "dark");
    await sleep(500);
    checks.desktop_dark_theme = (await liveMetrics(cdp)).map.width > 1000
      && await cdp.evaluate("document.documentElement.dataset.theme === 'dark'");
    captures.desktop_dark = await screenshot(cdp, `${output}/desktop-dark.png`);
    const initialNode = await cdp.evaluate(`(() => {
      const node = window.__musixMap.nodes(':visible')[0];
      const point = node.renderedPosition();
      const map = document.querySelector('#semantic-map').getBoundingClientRect();
      return { x:map.left + point.x, y:map.top + point.y };
    })()`);
    await click(cdp, initialNode.x, initialNode.y);
    await sleep(700);
    const directTap = await liveMetrics(cdp);
    checks.direct_node_tap_persistence = directTap.selected === 1 && directTap.selectedLabel && directTap.labels >= 2
      && directTap.hiddenNodes > 0 && directTap.labelOverlaps === 0 && !directTap.backHidden;
    captures.desktop_neighborhood = await screenshot(cdp, `${output}/desktop-neighborhood.png`);
    await sleep(550);
    checks.direct_node_tap_persists_over_500ms = (await liveMetrics(cdp)).selected === 1;
    await click(cdp, map.x + map.width - 8, map.y + map.height / 2);
    await sleep(500);
    checks.background_clear_returns_overview = (await liveMetrics(cdp)).level === 0 && (await liveMetrics(cdp)).backHidden;
    const query = await box(cdp, "#query");
    await click(cdp, query.x + 40, query.y + query.height / 2);
    await cdp.command("Input.insertText", { text: isolate.name });
    await cdp.waitFor("Boolean(document.querySelector('[data-open-node-id]'))", "search result");
    const searchLink = await box(cdp, "[data-open-node-id]");
    checks.search_all_names = Boolean(searchLink);
    await click(cdp, searchLink.x + searchLink.width / 2, searchLink.y + searchLink.height / 2);
    await sleep(700);
    const focused = await liveMetrics(cdp);
    checks.search_focus_and_neighborhood_persistence = focused.selected === 1 && focused.selectedLabel
      && !focused.backHidden && focused.visibleNodes >= 1;
    await sleep(550);
    const persistent = await liveMetrics(cdp);
    checks.click_persists_over_500ms_without_detail_panel = persistent.selected === 1 && !persistent.backHidden
      && !(await cdp.evaluate("Boolean(document.querySelector('#open-detail'))"));
    const back = await box(cdp, '[data-map-action="open-back"]');
    await click(cdp, back.x + back.width / 2, back.y + back.height / 2);
    await cdp.waitFor(`window.__musixMapMetrics.level === 0 && document.querySelector('[data-map-action="open-back"]').hidden`, "back overview");
    checks.back_returns_to_overview = (await liveMetrics(cdp)).level === 0;
    const fit = await box(cdp, '[data-map-action="fit"]');
    await click(cdp, fit.x + fit.width / 2, fit.y + fit.height / 2);
    await cdp.waitFor("window.__musixMapMetrics.level === 0", "fit overview");
    checks.fit_returns_to_overview = (await liveMetrics(cdp)).level === 0;
    assert(cdp.runtimeErrors.length === 0, `runtime errors: ${cdp.runtimeErrors.join("; ")}`);
    await navigate(cdp, { name: "mobile", width: 390, height: 844, mobile: true }, "dark");
    await sleep(700);
    const mobile = await liveMetrics(cdp);
    const controls = await cdp.evaluate("[...document.querySelectorAll('#map-controls, #search')].every((e) => { const b=e.getBoundingClientRect(); return b.left >= 0 && b.right <= innerWidth && b.top >= 0 && b.bottom <= innerHeight; })");
    checks.mobile_dark_visible_and_contained = mobile.map.width > 0 && mobile.map.height > 0 && controls
      && mobile.labels > 0 && mobile.labelFontMin >= 12 && mobile.occupancyWidth > 0.55
      && (await cdp.evaluate("document.documentElement.dataset.theme === 'dark'"));
    captures.mobile_dark = await screenshot(cdp, `${output}/mobile-dark.png`);
    await navigate(cdp, { name: "nojs", width: 1366, height: 768, mobile: false }, "light", false);
    checks.no_js_html_fallback = await cdp.evaluate("Boolean(document.querySelector('#open-fallback')) && getComputedStyle(document.querySelector('#open-fallback')).display !== 'none' && !document.querySelector('canvas')");
    captures.nojs = await screenshot(cdp, `${output}/nojs.png`);
    assert(Object.values(checks).every(Boolean), `failed checks: ${Object.entries(checks).filter(([, value]) => !value).map(([name]) => name).join(", ")}`);
    const report = { artifact: { nodes: artifact.nodes.length, edges: artifact.edges.length, isolate: isolate.node_id }, checks, captures, map_requests: cdp.mapRequests };
    await writeFile(`${output}/report.json`, `${JSON.stringify(report, null, 2)}\n`);
    console.log(JSON.stringify(checks));
  } finally {
    cdp.socket.close();
    if (chrome.exitCode === null) {
      const exited = new Promise((done) => chrome.once("exit", done));
      chrome.kill("SIGTERM");
      await Promise.race([exited, sleep(5_000)]);
      if (chrome.exitCode === null) {
        chrome.kill("SIGKILL");
        await sleep(500);
      }
    }
    for (let attempt = 0; attempt < 10; attempt += 1) {
      try {
        await rm(profile, { recursive: true, force: true });
        break;
      } catch (error) {
        if (attempt === 9) throw error;
        await sleep(100);
      }
    }
  }
}

main().catch((error) => { console.error(error.stack ?? error); process.exitCode = 1; });
