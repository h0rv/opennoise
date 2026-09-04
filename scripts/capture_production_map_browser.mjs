#!/usr/bin/env node

/**
 * Capture browser-owned acceptance evidence for the production map.
 *
 * Measurements below are made from the running Cytoscape renderer after real
 * Chrome input events; they are never reconstructed from model coordinates.
 */

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

const arguments_ = process.argv.slice(2);
const [url, output] = arguments_;
if (!url || !output) {
  throw new Error(
    "usage: capture_production_map_browser.mjs URL OUTPUT [--acceptance PATH] [--report PATH] [--captures DIR]",
  );
}
const option = (name) => {
  const index = arguments_.indexOf(name);
  return index < 0 ? null : arguments_[index + 1] ?? null;
};
const acceptancePath = option("--acceptance");
const reportPath = option("--report");
const capturesDirectory = resolve(option("--captures") ?? "artifacts/production-map/captures");
const chromePort = 9322;
const desktop = { name: "desktop", width: 1366, height: 768, mobile: false };
const mobile = { name: "mobile", width: 390, height: 844, mobile: true };
const appearances = ["light", "dark", "system"];
const sleep = (milliseconds) => new Promise((resolve_) => setTimeout(resolve_, milliseconds));

class CdpError extends Error {
  constructor(prefix, detail) {
    super(`${prefix}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
    this.name = "CdpError";
  }
}

class Cdp {
  constructor(webSocketUrl) {
    this.socket = new WebSocket(webSocketUrl);
    this.sequence = 0;
    this.pending = new Map();
    this.socket.addEventListener("message", ({ data }) => {
      const message = JSON.parse(data);
      const entry = this.pending.get(message.id);
      if (!entry) return;
      this.pending.delete(message.id);
      if (message.error) entry.reject(new CdpError(entry.method, message.error));
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
        reject(new CdpError(method, "timed out"));
      }, 15_000);
      this.pending.set(id, {
        method,
        resolve: (value) => { clearTimeout(timeout); resolve_(value); },
        reject: (error) => { clearTimeout(timeout); reject(error); },
      });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression, description = "Runtime.evaluate") {
    const value = await this.command("Runtime.evaluate", {
      expression, returnByValue: true, awaitPromise: true, userGesture: true,
    });
    // A JavaScript exception is carried inside a successful CDP response. Never
    // collapse it to undefined and accidentally record a passing claim.
    if (value.exceptionDetails) {
      const exception = value.exceptionDetails.exception ?? {};
      throw new CdpError(description, {
        text: value.exceptionDetails.text,
        lineNumber: value.exceptionDetails.lineNumber,
        columnNumber: value.exceptionDetails.columnNumber,
        description: exception.description,
        value: exception.value,
      });
    }
    if (!value.result) throw new CdpError(description, "missing evaluation result");
    if (value.result.subtype === "error") throw new CdpError(description, value.result.description);
    return value.result.value;
  }

  async waitFor(expression, description, timeout = 15_000) {
    const started = Date.now();
    while (Date.now() - started < timeout) {
      if (await this.evaluate(expression, description)) return;
      await sleep(50);
    }
    throw new CdpError(description, "condition did not become true");
  }

  close() { this.socket.close(); }
}

async function json(url_, options) {
  const response = await fetch(url_, options);
  if (!response.ok) throw new Error(`${url_} returned ${response.status}`);
  return response.json();
}

async function launchChrome() {
  const userDataDirectory = `${tmpdir()}/musix-production-map-cdp-${process.pid}`;
  await rm(userDataDirectory, { recursive: true, force: true });
  const process_ = spawn("/usr/bin/chromium", [
    "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-background-networking",
    "--disable-default-apps", "--no-first-run", `--remote-debugging-port=${chromePort}`,
    `--user-data-dir=${userDataDirectory}`, "about:blank",
  ], { stdio: "ignore" });
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      await json(`http://127.0.0.1:${chromePort}/json/version`);
      return { process_, userDataDirectory };
    } catch { await sleep(50); }
  }
  process_.kill("SIGKILL");
  throw new Error("Chromium did not expose a DevTools endpoint");
}

async function createPage() {
  const target = await json(`http://127.0.0.1:${chromePort}/json/new?about:blank`, { method: "PUT" });
  const cdp = new Cdp(target.webSocketDebuggerUrl);
  await cdp.connect();
  await cdp.command("Page.enable");
  await cdp.command("Runtime.enable");
  return cdp;
}

async function setViewport(cdp, viewport, appearance) {
  await cdp.command("Emulation.setDeviceMetricsOverride", {
    width: viewport.width, height: viewport.height, deviceScaleFactor: 1, mobile: viewport.mobile,
    screenWidth: viewport.width, screenHeight: viewport.height,
  });
  await cdp.command("Emulation.setTouchEmulationEnabled", { enabled: viewport.mobile, maxTouchPoints: viewport.mobile ? 5 : 1 });
  await cdp.command("Emulation.setEmulatedMedia", {
    media: "screen",
    features: [{ name: "prefers-color-scheme", value: appearance === "dark" ? "dark" : "light" }],
  });
}

async function navigate(cdp, viewport, appearance, javascript = true) {
  await cdp.command("Emulation.setScriptExecutionDisabled", { value: !javascript });
  await setViewport(cdp, viewport, appearance);
  const target = new URL(url);
  target.searchParams.set("theme", appearance);
  target.searchParams.set("browser_evidence", "1");
  await cdp.command("Page.navigate", { url: target.toString() });
  await cdp.waitFor("document.readyState === 'complete'", "document load");
  if (javascript) {
    await cdp.waitFor("Boolean(window.__musixMap)", "semantic map initialization");
    await cdp.waitFor("document.documentElement.classList.contains('js-map-ready')", "semantic map visibility");
  }
}

async function click(cdp, x, y) {
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none" });
  await cdp.command("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1 });
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1 });
}

async function drag(cdp, x, y, toX, toY) {
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none" });
  await cdp.command("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
  for (let step = 1; step <= 6; step += 1) {
    await cdp.command("Input.dispatchMouseEvent", {
      type: "mouseMoved", x: x + ((toX - x) * step) / 6, y: y + ((toY - y) * step) / 6,
      button: "left", buttons: 1,
    });
  }
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseReleased", x: toX, y: toY, button: "left", clickCount: 1 });
}

async function touch(cdp, type, points) {
  await cdp.command("Input.dispatchTouchEvent", {
    type, touchPoints: points.map(([x, y], id) => ({ x, y, id, radiusX: 1, radiusY: 1, force: 1 })),
  });
}

async function box(cdp, selector) {
  return cdp.evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)}); if (!e) return null; const b = e.getBoundingClientRect(); return {x:b.x,y:b.y,width:b.width,height:b.height}; })()`, `bounding box for ${selector}`);
}

async function screenshot(cdp, path) {
  const response = await cdp.command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  const bytes = Buffer.from(response.data, "base64");
  await writeFile(path, bytes);
  return { path, sha256: createHash("sha256").update(bytes).digest("hex"), byte_size: bytes.length };
}

const state = (cdp) => cdp.evaluate(`(() => { const cy = window.__musixMap; if (!cy) return null; return { pan:cy.pan(), zoom:cy.zoom(), lod:cy.nodes('.overview:visible').length ? 0 : cy.nodes(':visible').max(n => Number(n.data('lodMin'))).value }; })()`, "map state");
const currentLod = (cdp) => cdp.evaluate("window.__musixMap.nodes('.overview:visible').length ? 0 : window.__musixMap.nodes(':visible').max(n => Number(n.data('lodMin'))).value", "map LOD");

async function zoomUntil(cdp, expected) {
  const plus = await box(cdp, '[data-map-action="zoom-in"]');
  if (!plus) throw new Error("zoom-in control not found");
  for (let attempt = 0; attempt < 32; attempt += 1) {
    if (await currentLod(cdp) === expected) return;
    await click(cdp, plus.x + plus.width / 2, plus.y + plus.height / 2);
    await sleep(80);
  }
  throw new Error(`could not reach LOD ${expected}; current ${await currentLod(cdp)}`);
}

function renderedLabels(cdp) {
  return cdp.evaluate(`(() => {
    const cy = window.__musixMap;
    const map = document.querySelector('#semantic-map').getBoundingClientRect();
    const labels = cy.nodes(':visible').filter(n => Boolean(n.data('displayLabel'))).map(n => {
      // Renderer calculated text geometry; not a model-derived or node-union box.
      n.boundingBox({includeLabels:true});
      const raw = n[0]._private.labelBounds.main;
      const pan = cy.pan();
      const zoom = cy.zoom();
      const b = {x1:raw.x1 * zoom + pan.x, y1:raw.y1 * zoom + pan.y, x2:raw.x2 * zoom + pan.x, y2:raw.y2 * zoom + pan.y};
      const font = Number.parseFloat(n.style('font-size'));
      return {entity_id:String(n.data('itemId')), min_x:b.x1, min_y:b.y1, max_x:b.x2, max_y:b.y2, font_size_px:Number.isFinite(font) ? font : 0};
    });
    const clipped = labels.filter(label => label.min_x < map.left || label.min_y < map.top || label.max_x > map.right || label.max_y > map.bottom);
    if (clipped.length) throw new Error('a shown label is clipped by the interactive map viewport: ' + JSON.stringify(clipped.slice(0, 3)));
    return labels;
  })()`, "actual Cytoscape rendered label bounds");
}

async function lodMeasurements(cdp) {
  const measurements = [];
  for (let level = 0; level < 4; level += 1) {
    await zoomUntil(cdp, level);
    measurements.push({ level, labels: await renderedLabels(cdp) });
  }
  return measurements;
}

async function overviewFocusRevealsLabel(cdp) {
  const candidate = await cdp.evaluate(`(() => {
    const cy = window.__musixMap;
    const map = document.querySelector('#semantic-map').getBoundingClientRect();
    const node = cy.nodes('.overview:visible').filter(n => !n.data('displayLabel')).map(n => ({
      node: n, point: n.renderedPosition(),
    })).filter(({ point }) => point.x > map.left + 8 && point.x < map.right - 8
      && point.y > map.top + 8 && point.y < map.bottom - 8).sort(
      (left, right) => String(left.node.data('itemId')).localeCompare(String(right.node.data('itemId'))),
    )[0]?.node;
    if (!node) throw new Error('no initially unlabeled overview community');
    const point = node.renderedPosition();
    return { id: node.id(), x: point.x, y: point.y };
  })()`, "initially unlabeled overview community");
  await click(cdp, candidate.x, candidate.y);
  await sleep(120);
  const result = await cdp.evaluate(`(() => {
    const cy = window.__musixMap;
    const node = cy.$id(${JSON.stringify(candidate.id)});
    const map = document.querySelector('#semantic-map').getBoundingClientRect();
    const label = String(node.data('displayLabel') ?? '');
    node.boundingBox({includeLabels:true});
    const raw = node[0]._private.labelBounds.main;
    if (!raw) return {
      selected: node.selected(), label, raw: null,
      currentLod: cy.nodes('.overview:visible').length ? 0 : 1,
    };
    const pan = cy.pan(); const zoom = cy.zoom();
    const bounds = { x1:raw.x1 * zoom + pan.x, y1:raw.y1 * zoom + pan.y, x2:raw.x2 * zoom + pan.x, y2:raw.y2 * zoom + pan.y };
    return {
      selected: node.selected(), label, bounds,
      visible: node.selected() && label.length > 0
      && [bounds.x1, bounds.y1, bounds.x2, bounds.y2].every(Number.isFinite)
      && bounds.x1 >= map.left && bounds.y1 >= map.top
      && bounds.x2 <= map.right && bounds.y2 <= map.bottom,
    };
  })()`, "selected overview label is visible in renderer");
  if (!result.visible) throw new CdpError("selected overview label is visible in renderer", result);
  return true;
}

async function desktopInteractions(cdp) {
  const map = await box(cdp, "#semantic-map");
  if (!map) throw new Error("map bounding box not found");
  const x = map.x + map.width * 0.72;
  const y = map.y + map.height * 0.62;
  const initial = await state(cdp);
  await drag(cdp, x, y, x + 64, y + 38);
  await sleep(100);
  const afterDrag = await state(cdp);
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseWheel", x, y, deltaX: 0, deltaY: -220, pointerType: "mouse" });
  await sleep(150);
  const afterWheel = await state(cdp);
  const theme = await box(cdp, "#theme-toggle");
  if (!theme) throw new Error("theme toggle not found");
  let darkMode = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await click(cdp, theme.x + theme.width / 2, theme.y + theme.height / 2);
    await sleep(50);
    darkMode = await cdp.evaluate(`(() => ({ theme:document.documentElement.dataset.theme, text:document.querySelector('#theme-toggle')?.textContent, active:document.activeElement?.id, canvas:getComputedStyle(document.documentElement).getPropertyValue('--canvas').trim() }))()`, "dark mode result");
    if (darkMode.theme === "dark") break;
  }
  if (darkMode.theme !== "dark") throw new CdpError("dark mode selection", darkMode);
  const keyboard_focus_visible = await keyboardFocus(cdp);
  const search = await box(cdp, "#query");
  if (!search) throw new Error("search input not found");
  const beforeSearch = await state(cdp);
  await click(cdp, search.x + 16, search.y + search.height / 2);
  await cdp.command("Input.insertText", { text: "electronic" });
  await cdp.waitFor("document.querySelectorAll('#results .result').length > 0", "search results");
  const afterSearch = await state(cdp);
  await zoomUntil(cdp, 3);
  const beforeSelection = await state(cdp);
  const initialUrl = await cdp.evaluate("location.pathname + location.search", "initial location");
  const node = await cdp.evaluate(`(() => {
    const cy = window.__musixMap;
    const candidates = cy.nodes(':visible').filter(v => !v.data('overview') && v.data('detailHref')).map(v => ({ node:v, point:v.renderedPosition() })).filter(({point}) => point.x > 420 && point.x < innerWidth - 80 && point.y > 90 && point.y < innerHeight - 100).sort((a, b) => Math.hypot(a.point.x - innerWidth / 2, a.point.y - innerHeight / 2) - Math.hypot(b.point.x - innerWidth / 2, b.point.y - innerHeight / 2));
    const candidate = candidates[0];
    if (!candidate) throw new Error('no visible, unobscured detail node');
    return {x:candidate.point.x,y:candidate.point.y,href:candidate.node.data('detailHref')};
  })()`, "selectable rendered node");
  await click(cdp, node.x, node.y);
  await cdp.waitFor("document.querySelector('#genre-detail-slot').textContent.trim().length > 0", "detail after real node click");
  const selectedUrl = await cdp.evaluate("location.pathname + location.search", "selected location");
  // Browser-level back pointer button, rather than a synthetic popstate/history callback.
  await cdp.command("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "back", buttons: 8, clickCount: 1 });
  await cdp.command("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "back", buttons: 0, clickCount: 1 });
  await sleep(350);
  const backUrl = await cdp.evaluate("location.pathname + location.search", "back location");
  const backState = await cdp.evaluate(`(() => {
    const map = document.querySelector('#semantic-map');
    const cy = window.__musixMap;
    const style = map ? getComputedStyle(map) : null;
    const status = document.querySelector('#map-status')?.textContent ?? '';
    return { connected:Boolean(map?.isConnected), visible:Boolean(map && style?.display !== 'none' && map.getBoundingClientRect().width > 0 && map.getBoundingClientRect().height > 0), visible_nodes:cy ? cy.nodes(':visible').length : 0, shown_labels:cy ? cy.nodes(':visible').filter(n => Boolean(n.data('displayLabel'))).length : 0, pan:cy?.pan(), zoom:cy?.zoom(), status };
  })()`, "map state after browser back");
  return {
    drag_pan: afterDrag.pan.x !== initial.pan.x || afterDrag.pan.y !== initial.pan.y,
    wheel_zoom: afterWheel.zoom !== afterDrag.zoom,
    click_opens_detail: selectedUrl !== "/" && node.href.length > 0,
    search_preserves_map_state: beforeSearch.pan.x === afterSearch.pan.x && beforeSearch.pan.y === afterSearch.pan.y && beforeSearch.zoom === afterSearch.zoom,
    browser_back_restores_map_state: selectedUrl !== backUrl && backUrl === initialUrl
      && backState.connected && backState.visible && backState.visible_nodes > 0 && backState.shown_labels > 0
      && backState.status.includes("genres available")
      && Math.abs(backState.pan.x - beforeSelection.pan.x) < 0.001
      && Math.abs(backState.pan.y - beforeSelection.pan.y) < 0.001
      && Math.abs(backState.zoom - beforeSelection.zoom) < 0.001,
    dark_mode_toggle: true,
    keyboard_focus_visible,
    diagnostics: { initial_url: initialUrl, selected_url: selectedUrl, back_url: backUrl, before_selection: beforeSelection, after_back: backState },
  };
}

async function mobileInteractions(cdp) {
  const map = await box(cdp, "#semantic-map");
  if (!map) throw new Error("mobile map bounding box not found");
  const x = map.x + map.width * 0.68;
  const y = map.y + map.height * 0.54;
  const overview_focus_reveals_label = await overviewFocusRevealsLabel(cdp);
  const initial = await state(cdp);
  await touch(cdp, "touchStart", [[x, y]]);
  await touch(cdp, "touchMove", [[x + 40, y + 55]]);
  await touch(cdp, "touchEnd", []);
  await sleep(120);
  const afterPan = await state(cdp);
  await touch(cdp, "touchStart", [[x - 42, y], [x + 42, y]]);
  await touch(cdp, "touchMove", [[x - 78, y], [x + 78, y]]);
  await touch(cdp, "touchEnd", []);
  await sleep(180);
  const afterPinch = await state(cdp);
  return {
    touch_pan: afterPan.pan.x !== initial.pan.x || afterPan.pan.y !== initial.pan.y,
    pinch_zoom: afterPinch.zoom !== afterPan.zoom,
    overview_focus_reveals_label,
  };
}

async function keyboardFocus(cdp) {
  for (let index = 0; index < 5; index += 1) {
    for (const type of ["rawKeyDown", "keyUp"]) await cdp.command("Input.dispatchKeyEvent", { type, key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, modifiers: 8 });
    if (await cdp.evaluate(`(() => { const map = document.querySelector('#semantic-map'); const style = getComputedStyle(map); return document.activeElement === map && map.classList.contains('keyboard-focus-visible') && Number.parseFloat(style.outlineWidth) >= 3; })()`, "visible keyboard map focus")) return true;
  }
  return false;
}

async function fallback(cdp) {
  await navigate(cdp, desktop, "light", false);
  return cdp.evaluate(`(() => { const svg=document.querySelector('#plot'); return Boolean(svg && getComputedStyle(svg).display !== 'none' && svg.getBoundingClientRect().width > 0 && svg.querySelectorAll('a[href]').length > 0); })()`, "no-JavaScript SVG fallback");
}

async function patchAcceptance(path, measurement) {
  const evidence = JSON.parse(await readFile(path, "utf8"));
  for (const viewport of ["desktop", "mobile"]) {
    const byLod = new Map(measurement.labels[viewport].map((item) => [item.level, item.labels]));
    for (const lod of evidence.lods) lod[`${viewport}_labels`] = byLod.get(lod.level) ?? [];
  }
  evidence.screenshots = measurement.screenshots;
  evidence.interactions = measurement.interactions;
  await writeFile(path, `${JSON.stringify(evidence, null, 2)}\n`);
}

async function run() {
  const chrome = await launchChrome();
  try {
    await mkdir(capturesDirectory, { recursive: true });
    const desktopPage = await createPage();
    await navigate(desktopPage, desktop, "light");
    const desktopLabels = await lodMeasurements(desktopPage);
    const desktopRun = await desktopInteractions(desktopPage);
    const { diagnostics, ...desktopChecks } = desktopRun;
    const screenshots = [];
    for (const viewport of [desktop, mobile]) {
      for (const appearance of appearances) {
        const page = viewport === desktop && appearance === "light" ? desktopPage : await createPage();
        await navigate(page, viewport, appearance);
        const path = resolve(capturesDirectory, `${viewport.name}-${appearance}.png`);
        screenshots.push({ viewport: viewport.name, color_scheme: appearance, width: viewport.width, height: viewport.height, ...(await screenshot(page, path)) });
        if (page !== desktopPage) page.close();
      }
    }
    const mobilePage = await createPage();
    await navigate(mobilePage, mobile, "light");
    const mobileLabels = await lodMeasurements(mobilePage);
    // Measurements intentionally traverse every level. Reload before interaction
    // proof so the focus test starts at the real overview level.
    await navigate(mobilePage, mobile, "light");
    const mobileChecks = await mobileInteractions(mobilePage);
    mobilePage.close();
    const fallbackPage = await createPage();
    const no_javascript_svg_fallback = await fallback(fallbackPage);
    fallbackPage.close();
    desktopPage.close();
    const measurement = {
      evidence_revision: "browser-production-map-v2",
      capture_method: "Chrome DevTools Protocol input plus live Cytoscape renderedBoundingBox(includeLabels:true)",
      labels: { desktop: desktopLabels, mobile: mobileLabels },
      screenshots,
      interactions: { ...desktopChecks, ...mobileChecks, no_javascript_svg_fallback },
      interaction_diagnostics: diagnostics,
    };
    await writeFile(output, `${JSON.stringify(measurement, null, 2)}\n`);
    if (acceptancePath) await patchAcceptance(acceptancePath, measurement);
    return measurement;
  } finally {
    chrome.process_.kill("SIGTERM");
    await new Promise((resolve_) => chrome.process_.once("exit", resolve_));
    // Chromium can leave short-lived utility processes after its parent exits.
    // Cleanup must never mask a validation failure.
    for (let attempt = 0; attempt < 8; attempt += 1) {
      try {
        await rm(chrome.userDataDirectory, { recursive: true, force: true, maxRetries: 1, retryDelay: 100 });
        break;
      } catch {
        await sleep(100);
      }
    }
  }
}

const measurement = await run();
if (reportPath && acceptancePath) {
  const evaluator = spawn(process.execPath, ["scripts/evaluate_production_map.py", acceptancePath, "--report", reportPath], { stdio: "inherit" });
  const code = await new Promise((resolve_) => evaluator.once("exit", resolve_));
  if (code !== 0) throw new Error(`production map evaluator exited ${code}`);
}
process.stdout.write(`${JSON.stringify({ screenshots: measurement.screenshots.length, interactions: measurement.interactions }, null, 2)}\n`);
