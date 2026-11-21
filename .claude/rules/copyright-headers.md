# Copyright notices and licence headers

Starlock is a fork of PushNav ([meridianfield/pushnav](https://github.com/meridianfield/pushnav),
GPL-3.0-or-later, original author Arun Venkataswamy), maintained by Kyle Downs
and renamed in November 2026. GPLv3 §4–5 require existing copyright notices to
stay intact, and modified files to show who changed them.

## Never

- Never remove, reword or reorder an existing copyright line, and never change
  another person's name or year.
- Never remove or change the licence text of a header (the "This file is part
  of Starlock" sentence is the only part of it that names the project).
- Never touch headers under `hardware/3d_models/vendor/`, `scripts/fonts/` or
  `data/catalogs/`: those are third-party files under their own licences.
- Keep the credit to PushNav and Arun Venkataswamy in `README.md`,
  `CONTRIBUTING.md`, `docs/license.md` and the `.deb` copyright file written by
  `scripts/build_headless_deb.sh`.

## Editing a file that has a header

When the change is substantial (roughly 15 or more added or rewritten lines,
or a new feature or rewritten function), add a line for Kyle Downs directly
below the existing copyright line(s), in the file's own comment style:

```python
# Copyright (C) 2026 Arun Venkataswamy
# Copyright (C) 2026 Kyle Downs
```

```c
/*
 * Copyright (C) 2026 Arun Venkataswamy
 * Copyright (C) 2026 Kyle Downs
 *
```

- Skip it for small fixes, renames, formatting, or comment and typo changes.
- If the file already has a Kyle Downs line, don't add another. If its year
  is older than the current year, extend it to a range, e.g.
  `Copyright (C) 2026-2027 Kyle Downs`.
- Keep the file's line endings (some files are CRLF) and don't touch the
  rest of the header.

## Creating a new file

- New files get **no** copyright header. The `LICENSE` file and the License
  section of `README.md` cover the whole project.
- This holds even when the neighbouring files have headers.
- Exception: if the new file is mostly copied or adapted from an existing
  headed file (for example a resized copy of another `.scad` housing), keep
  the source file's header and add the Kyle Downs line, because the original
  author's copyright carries over to the copied code.

## Files without a header

- Don't add headers to existing files that have none. Everything under
  `web/` is header-free by design.
