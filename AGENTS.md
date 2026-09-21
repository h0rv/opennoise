# Project instructions

Use Poe for project tasks. Do not add another task runner.

- `poe sync` installs locked dependencies.
- `poe check` runs the project checks.
- `poe dev` serves an existing static export.
- `poe build` builds and browser-certifies `dist`.
- `poe deploy` builds, certifies, and deploys `dist` to Cloudflare Pages.
- `poe bootstrap` prepares the historical source cache when needed.

Keep Python 3.13 and static-only delivery. Never deploy experimental v3 data,
local research candidates, or previews. Archived docs may mention retired Poe
aliases. Run their scripts directly when needed.
