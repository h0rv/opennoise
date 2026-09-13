#!/usr/bin/env node

/** Capture static-public-map browser evidence without any runtime graph code. */

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

const args = process.argv.slice(2);
const [baseUrl, output] = args;
if (!baseUrl || !output) throw new Error("usage: capture_production_map_browser.mjs URL OUTPUT [--captures DIR]");
const option = (name) => {
  const index = args.indexOf(name);
  return index < 0 ? null : args[index + 1] ?? null;
};
const captures = resolve(option("--captures") ?? "artifacts/production-map/captures");
const acceptancePath = option("--acceptance");
const port = 9322;
const sleep = (milliseconds) => new Promise((done) => setTimeout(done, milliseconds));

class Cdp {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.next = 0;
    this.waiting = new Map();
    this.runtimeErrors = [];
    this.socket.addEventListener("message", ({ data }) => {
      const message = JSON.parse(data);
      if (message.method === "Runtime.exceptionThrown") this.runtimeErrors.push(message.params.exceptionDetails.text);
      if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
        this.runtimeErrors.push(message.params.args.map((item) => item.value ?? item.description ?? "console error").join(" "));
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
    const result = await this.command("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(`page evaluation failed: ${result.exceptionDetails.text}`);
    return result.result?.value;
  }

  requireNoBrowserErrors(context) {
    if (this.runtimeErrors.length) throw new Error(`${context} browser errors: ${this.runtimeErrors.join(" | ")}`);
  }

  close() { this.socket.close(); }
}

async function json(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

async function launch() {
  const profile = `${tmpdir()}/musix-static-map-${process.pid}`;
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
  return cdp;
}

async function navigate(cdp, width, height, suffix = "", colorScheme = "light") {
  await cdp.command("Emulation.setDeviceMetricsOverride", {
    width, height, deviceScaleFactor: 1, mobile: width <= 480, screenWidth: width, screenHeight: height,
  });
  await cdp.command("Emulation.setEmulatedMedia", {
    media: "screen",
    features: [{ name: "prefers-color-scheme", value: colorScheme === "dark" ? "dark" : "light" }],
  });
  const target = new URL(baseUrl);
  target.search = suffix;
  await cdp.command("Page.navigate", { url: target.toString() });
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (await cdp.evaluate("document.readyState === 'complete' && Boolean(document.querySelector('#static-map-viewport #plot'))")) return;
    await sleep(25);
  }
  throw new Error("static map page did not become ready");
}

async function screenshot(cdp, name, viewport, colorScheme, width, height) {
  const result = await cdp.command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  const bytes = Buffer.from(result.data, "base64");
  const path = resolve(captures, name);
  await writeFile(path, bytes);
  return {
    name, viewport, color_scheme: colorScheme, width, height, path,
    byte_size: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex"),
  };
}

const fitState = "(() => { const v=document.querySelector('#static-map-viewport'); const plot=document.querySelector('#plot'); const resources=performance.getEntriesByType('resource').map(entry=>({name:entry.name,transfer_size:entry.transferSize ?? 0})); const navigation=performance.getEntriesByType('navigation')[0]; const paints=performance.getEntriesByType('paint'); return {fit: location.search === '', svg: Boolean(plot), links: [...document.querySelectorAll('#static-map-levels a')].map(a=>a.href), ordinary_genre_link:Boolean(plot.querySelector('a[href^=\"/genres/key/\"]')), no_runtime_graph_assets: !resources.some(entry=>entry.name.includes('cytoscape') || entry.name.includes('semantic-map')), network:{request_count:resources.length + 1,transfer_bytes:resources.reduce((total, entry)=>total + entry.transfer_size, navigation?.transferSize ?? 0),resources}, timing:{navigation_ms:navigation?.duration ?? null,first_contentful_paint_ms:paints.find(entry=>entry.name === 'first-contentful-paint')?.startTime ?? null}, client_width:v.clientWidth, scroll_width:v.scrollWidth, client_height:v.clientHeight, scroll_height:v.scrollHeight}; })()";
const zoomState = "(() => { const v=document.querySelector('#static-map-viewport'); const before={left:v.scrollLeft,top:v.scrollTop}; v.scrollLeft=160; v.scrollTop=120; return {client_width:v.clientWidth,scroll_width:v.scrollWidth,client_height:v.clientHeight,scroll_height:v.scrollHeight,before,after:{left:v.scrollLeft,top:v.scrollTop}}; })()";

async function run() {
  const chrome = await launch();
  try {
    await mkdir(captures, { recursive: true });
    const cdp = await page();
    await navigate(cdp, 1366, 768);
    const fit = await cdp.evaluate(fitState);
    const desktopFit = await screenshot(cdp, "desktop-light.png", "desktop", "light", 1366, 768);
    await navigate(cdp, 1366, 768, "?level=1&zoom=1");
    const zoom = await cdp.evaluate(zoomState);
    const desktopZoom = await screenshot(cdp, "desktop-zoom.png", "desktop", "light", 1366, 768);
    const screenshots = [desktopFit, desktopZoom];
    for (const [viewport, width, height] of [["desktop", 1366, 768], ["mobile", 390, 844]]) {
      for (const colorScheme of ["light", "dark", "system"]) {
        if (viewport === "desktop" && colorScheme === "light") continue;
        await navigate(cdp, width, height, "", colorScheme);
        screenshots.push(await screenshot(cdp, `${viewport}-${colorScheme}.png`, viewport, colorScheme, width, height));
      }
    }
    cdp.requireNoBrowserErrors("static map QA");
    cdp.close();
    const interactions = {
      evidence_kind: "static_public_map",
      fit_route: fit.fit && fit.svg,
      url_lod_control: fit.links.some((href) => href.endsWith("/?level=0&zoom=0")) && fit.links.some((href) => href.endsWith("/?level=1&zoom=1")),
      native_scroll: zoom.scroll_width > zoom.client_width && zoom.scroll_height > zoom.client_height,
      programmatic_scroll: zoom.after.left > zoom.before.left && zoom.after.top > zoom.before.top,
      ordinary_genre_link: fit.ordinary_genre_link,
      no_runtime_graph_assets: fit.no_runtime_graph_assets,
      no_browser_errors: cdp.runtimeErrors.length === 0,
    };
    if (!Object.entries(interactions).filter(([name]) => name !== "evidence_kind").every(([, passed]) => passed)) throw new Error(`static navigation evidence failed: ${JSON.stringify({ fit, zoom, interactions })}`);
    const evidence = {
      evidence_revision: "browser-static-public-map-v1",
      capture_method: "Chrome DevTools Protocol screenshots and native overflow scroll inspection",
      screenshots,
      fit,
      zoom,
      interactions,
    };
    await writeFile(output, `${JSON.stringify(evidence, null, 2)}\n`);
    if (acceptancePath) {
      const acceptance = JSON.parse(await readFile(acceptancePath, "utf8"));
      acceptance.screenshots = screenshots.filter((item) => item.name !== "desktop-zoom.png");
      acceptance.interactions = interactions;
      await writeFile(acceptancePath, `${JSON.stringify(acceptance, null, 2)}\n`);
    }
  } finally {
    chrome.process_.kill("SIGTERM");
    for (let attempt = 0; attempt < 8; attempt += 1) {
      try {
        await rm(chrome.profile, { recursive: true, force: true, maxRetries: 1, retryDelay: 100 });
        break;
      } catch {
        await sleep(100);
      }
    }
  }
}

await run();
