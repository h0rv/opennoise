export function hasShortcutModifier(event: Pick<KeyboardEvent, 'altKey' | 'ctrlKey' | 'metaKey'>) {
  return event.altKey || event.ctrlKey || event.metaKey;
}
