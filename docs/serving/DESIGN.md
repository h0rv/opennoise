# Design direction

User direction, recorded 2026-09-30: minimal design, “grug brain” vibe, with
usability and UI/UX preserved. This applies to every OpenNoise discovery view.

Make a small, useful music tool. Put names, music relationships, search, and
navigation first. Use ordinary words and familiar controls. The interface
should feel direct, quiet, and specific to exploring music.

## What “AI slop” means here

The current UI has some of these problems. Treat these as concrete failure
patterns to remove in the next design pass:

- Generic dashboard chrome: nested cards, rounded containers around everything,
  pill badges, tiny uppercase labels, and decorative status indicators.
- Template styling: interchangeable teal/beige palettes, gradients, soft shadows,
  oversized headings, and excessive empty space regardless of the content.
- Generic copy such as “Explore named musical styles,” plus repeated introductory
  paragraphs, caveats, and explanations of the same evidence roles.
- Research machinery in the main flow: provenance hashes, model terminology,
  taxonomy qualifications, and counts that do not help the current action.
- Every option exposed at once: filter bars, view switches, competing buttons,
  and separate navigation systems without a clear primary action.
- Decoration and animation that add visual activity without helping discovery.

No individual color, radius, card, or badge is inherently wrong. Use one when
it has a clear job. Avoid accumulating these patterns into a generic template.

## Shape of the interface

Start with a readable map or list of names, one search field, and simple links.
Use a restrained type scale, a neutral background, and a small number of colors
with explicit meaning. Prefer normal text, rows, and separators to boxed panels.
Use space to establish hierarchy while keeping useful information in view.

Show details when a person selects a style or artist. Keep common actions easy
to find; put less-used filters and technical explanations behind a clearly
named control. Progressive disclosure should reduce clutter without making
ordinary navigation harder. Avoid introducing a design system or abstraction
where a small amount of straightforward HTML and CSS solves the problem.

Say “Artists,” “Releases,” “Suggested,” “Back,” “List,” and “Search” where those
words describe the action. Put research status once in a quiet, discoverable
place. Keep provenance and method details available through About or Sources.
Retain an immediate “Suggested” label wherever a model inference could be
mistaken for an observed relationship. Show release context clearly at the
relationship itself. Removing repeated caveats must preserve these distinctions.

## Usability is a requirement

Preserve complete artist and style access, useful search, map/list alternatives,
pagination, deep links, browser Back/Forward, and reload behavior. A bounded map
sample must identify its size and provide a clear route to the complete list.
Missing data and unplaced artists must remain understandable and reachable.

Keep legible text, adequate contrast, visible keyboard focus, labeled controls,
usable touch targets, and mobile layouts without horizontal overflow. Never
make color, hover, or the canvas the only way to understand or reach something.
Keep loading, empty, and error states short and actionable. Preserve quick
initial loading and lazy detail requests.

## Review the next UI pass

Check actual desktop and mobile exports, including long names and missing data.
Find Aphex Twin and Four Tet; open an artist from a style; reach an artist outside
the map sample; return through history; reload a deep link; and repeat the
essential navigation with a keyboard. Existing browser contracts must still
pass. Judge the design by how easily these tasks work and how much unnecessary
chrome and copy disappeared. Visual minimalism alone is insufficient.
