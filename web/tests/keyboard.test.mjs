import assert from 'node:assert/strict';
import test from 'node:test';
import { hasShortcutModifier } from '../src/keyboard.ts';

test('Alt, Ctrl and Meta shortcuts belong to the browser, not tree or map navigation', () => {
  for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End', '+', '-', '0', 'Enter', ' ']) {
    for (let modifiers = 0; modifiers < 8; modifiers++) {
      const event = {
        key,
        altKey: !!(modifiers & 1),
        ctrlKey: !!(modifiers & 2),
        metaKey: !!(modifiers & 4),
      };
      assert.equal(hasShortcutModifier(event), modifiers !== 0, `${key} modifiers=${modifiers}`);
    }
  }
  assert.equal(
    hasShortcutModifier({ altKey: false, ctrlKey: false, metaKey: false, shiftKey: true }),
    false,
    'Shift must remain available for the plus key',
  );
});
