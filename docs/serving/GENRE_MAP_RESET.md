# Genre map reset

The landing page is a map of genre names. Selecting a genre opens its artist
map, and selecting an artist opens its observed genres and recording links.
Both maps have list alternatives. Search and the complete artist directory
include identities without genre claims.

## Original interface observations

On 2026-10-24, the browser opened
[Every Noise at Once](https://everynoise.com/engenremap.html) and its
[jazz artist map](https://everynoise.com/engenremap-jazz.html).
The requested everynoise.net hostname did not resolve in the browser.

The original page presents genre names at spatial positions, with little
interface text. Selecting jazz changed its label to include a music marker
and a separate » control. Selecting » opened the jazz artist map, which also
uses spatial names and offers a list alternative. The original description
explains its approximate musical axes and credits Glenn McDonald. The
reconstruction does not copy those coordinates or claim those axes.

The safe public OpenNoise input contains 151 observed genre labels and 440
artist identities. Only 78 artists have observed genre claims. The landing
map groups 148 genre labels through shared artists. Three labels have no
shared artists and appear in a separate group below the map. Label placement
uses only those source memberships and resolves overlapping name targets.
Colors distinguish disconnected groups, and do not encode sound or quality.

Artist detail pages show distinct, nonempty recording titles from source
metadata. The display accepts title, display_title and name in that order.
Repeated recording identities and repeated visible titles are omitted.
Source links and native attribution remain in one Sources disclosure. Inferred
relationships retain the Suggested label.

## REA review

The user supplied [morluto/rea](https://github.com/morluto/rea).
Its [browser observation documentation](https://github.com/morluto/rea/blob/main/docs/browser-observation.md)
describes bounded observations, explicit capture comparisons and the difference
between missing evidence and proven equivalence. Those principles informed the
checks for navigation, history, visible names and recorded requests.

The GitHub source directory fetch was restricted. No claim of code safety or
complete code review follows from reading its README and documentation. REA
was not installed or executed. Existing local tools are enough to inspect the
static reference interface and test the reconstruction.

## Verification

The local browser acceptance script is
`scripts/capture_retained_catalog_demo.mjs`. It checks every genre identity,
separate unlinked labels, nonoverlapping genre targets, genre and artist lists,
recording links, Aphex Twin, Four Tet, Morrissey, history, reload, keyboard use,
and touch navigation. It checks widths of 320 and 390 pixels, and rejects
external requests, media requests and runtime exceptions.

Public input files and promotion pins are unchanged. The standalone export
includes the new map functions. The release gate still checks all 701 promoted
JSON data files. No research data or new playback source is added.

## Limits

The maps arrange observed memberships. They do not establish perceptual
similarity, representative examples, broad music coverage or Every Noise
parity. Existing descriptor suggestions remain a separate, small unvalidated
layer. Source metadata links are usable, but audio playback is absent.

The installed Codex binary exposes the goals feature and generated
thread/goal/get and thread/goal/set schemas. The runtime has no goal tool.
The app-server control-socket connection initially lacked sandbox permission;
a permitted connection then timed out during initialization. No goal was
created, and the work continued in the managed task.
