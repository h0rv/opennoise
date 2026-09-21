# Project instructions

Poe is the sole project task runner. Do not add another task runner or Poe
aliases. The only supported Poe commands are:

- `poe sync` installs the locked dependencies before using the other commands.
- `poe bootstrap` prepares the historical Every Noise source cache when needed.
- `poe check` runs formatting, linting, type checks, and tests.
- `poe dev` serves an already-built static export from `dist`.
- `poe build` builds and browser-certifies `dist`.
- `poe deploy` builds, certifies, and deploys `dist` to Cloudflare Pages.

Keep Python 3.13 and static-only delivery. Never deploy experimental v3 data,
local research candidates, or previews. Archived docs may mention retired Poe
aliases. Run their scripts directly when needed.
