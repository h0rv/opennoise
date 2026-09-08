#!/usr/bin/env node

import { readFile } from "node:fs/promises";

const source = await readFile("src/musix/static/semantic-map.js", "utf8");
const start = source.indexOf("// display-transform-testable-start");
const end = source.indexOf("// display-transform-testable-end");
if (start < 0 || end < start) throw new Error("display transform test seam unavailable");
const helper = source.slice(start, end).replace("// display-transform-testable-start", "");
const { createMonotonicAxisTransform } = Function(`${helper}; return { createMonotonicAxisTransform };`)();
const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};
const near = (left, right) => Math.abs(left - right) < 0.000001;

const transform = createMonotonicAxisTransform([
  { raw: -10, display: 0 }, { raw: 0, display: 100 }, { raw: 5, display: 160 }, { raw: 20, display: 240 },
]);
for (const raw of [-20, -10, -4, 0, 3, 5, 14, 20, 35]) {
  assert(near(transform.inverse(transform.forward(raw)), raw), `round trip failed at ${raw}`);
}
const duplicate = createMonotonicAxisTransform([
  { raw: 0, display: 10 }, { raw: 0, display: 14 }, { raw: 10, display: 30 },
]);
assert(near(duplicate.forward(0), 12), "duplicate raw coordinates were not averaged");
assert(near(duplicate.inverse(12), 0), "duplicate coordinate inverse failed");
const degenerate = createMonotonicAxisTransform([{ raw: 7, display: 11 }]);
assert(degenerate.forward(-100) === 11 && degenerate.inverse(999) === 7, "degenerate transform is not stable");
console.log(JSON.stringify({ contract: "open-v2-display-transform-v1", passed: true }));
