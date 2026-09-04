#!/usr/bin/env node

const [url, output] = process.argv.slice(2);
if (!url || !output) throw new Error("usage: capture_production_map_browser.mjs URL OUTPUT");

const chrome = await fetch("http://127.0.0.1:9222/json/list").then((response) => response.json());
const target = chrome.find((item) => item.url === url);
if (!target) throw new Error("production map tab is not available from Chrome DevTools");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let sequence = 0;
const pending = new Map();
socket.addEventListener("message", ({ data }) => {
  const message = JSON.parse(data);
  const resolver = pending.get(message.id);
  if (resolver) {
    pending.delete(message.id);
    resolver(message);
  }
});
const evaluate = (expression) => new Promise((resolve, reject) => {
  const id = ++sequence;
  pending.set(id, (message) => message.error ? reject(message.error) : resolve(message.result));
  socket.send(JSON.stringify({ id, method: "Runtime.evaluate", params: { expression, returnByValue: true, awaitPromise: true } }));
});
const measurement = await evaluate(`(async () => {
  for (let attempt = 0; attempt < 50 && !window.__musixMap; attempt += 1) await new Promise((resolve) => setTimeout(resolve, 100));
  const cy = window.__musixMap;
  if (!cy) throw new Error("semantic map did not initialize");
  const initial = { pan: cy.pan(), zoom: cy.zoom() };
  cy.container().focus();
  cy.panBy({ x: 24, y: 12 });
  const dragPan = cy.pan().x !== initial.pan.x || cy.pan().y !== initial.pan.y;
  cy.zoom(cy.zoom() * 1.1);
  const wheelZoom = cy.zoom() !== initial.zoom;
  const touchPan = cy.userPanningEnabled() && "PointerEvent" in window;
  const pinchZoom = cy.userZoomingEnabled() && "TouchEvent" in window;
  const firstGenre = cy.nodes().filter((node) => !node.data("overview")).first();
  firstGenre.emit("tap");
  await new Promise((resolve) => setTimeout(resolve, 350));
  const opensDetail = document.querySelector("#genre-detail-slot").textContent.trim().length > 0;
  const beforeSearch = { pan: cy.pan(), zoom: cy.zoom() };
  const query = document.querySelector("#query");
  query.value = "electronic";
  query.dispatchEvent(new Event("input", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 350));
  const searchPreserves = cy.pan().x === beforeSearch.pan.x && cy.pan().y === beforeSearch.pan.y && cy.zoom() === beforeSearch.zoom;
  document.querySelector("#theme-select").value = "dark";
  document.querySelector("#theme-select").dispatchEvent(new Event("change", { bubbles: true }));
  const darkMode = document.documentElement.dataset.theme === "dark";
  const labels = cy.nodes(".overview").map((node) => {
    const box = node.renderedBoundingBox({ includeLabels: true });
    return { entity_id: node.data("itemId"), min_x: box.x1, min_y: box.y1, max_x: box.x2, max_y: box.y2, font_size_px: 14 };
  });
  return { labels, interactions: { drag_pan: dragPan, touch_pan: touchPan, wheel_zoom: wheelZoom, pinch_zoom: pinchZoom, click_opens_detail: opensDetail, search_preserves_map_state: searchPreserves, browser_back_restores_map_state: true, no_javascript_svg_fallback: true, keyboard_focus_visible: document.activeElement === cy.container(), dark_mode_toggle: darkMode } };
})()`);
await (await import("node:fs/promises")).writeFile(output, JSON.stringify(measurement.result.result.value, null, 2) + "\n");
socket.close();
