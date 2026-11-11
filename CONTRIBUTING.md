# Contributing to Starlock

Starlock is a fork of [PushNav](https://github.com/meridianfield/pushnav)
by Arun Venkataswamy, maintained by Kyle Downs. The original project is not
accepting code contributions, so changes are developed here instead.

## Bug reports and issues

Please report problems with this fork at
[kwdowns/starlock](https://github.com/kwdowns/starlock/issues), not upstream.
This fork has diverged from the original, so a bug you see here may not
exist there.

When reporting a bug, it helps to include:

- Your operating system and version (e.g. macOS 14.5, Ubuntu 24.04, Windows 11)
- The commit hash you are running
- Your camera and lens (if relevant)
- Steps to reproduce the issue
- What you expected to happen, and what actually happened
- Any relevant log output or screenshots

## Code contributions

Pull requests are welcome. For anything larger than a small fix, open an
issue first so we can agree on the approach.

- Run `uv run pytest tests/` and, for UI changes, `npm test` in `web/`.
- Contributions are licensed under the
  [GNU General Public License v3.0](LICENSE) or later, like the rest of the
  project.
- Keep the existing copyright lines in file headers. If you make a
  substantial change to a file, add your own line below them:
  `Copyright (C) <year> <your name>`.
