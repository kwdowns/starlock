# Copyright (C) 2026 Arun Venkataswamy
# Copyright (C) 2026 Kyle Downs
#
# This file is part of Starlock.
#
# Starlock is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Starlock is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Starlock. If not, see <https://www.gnu.org/licenses/>.

"""Generate the PWA / home-screen icons in web/public/.

The branding (marketing/logo.png) is already drawn for the strictly
red-on-black UI: a red reticle and star on #0a0000, full bleed. So the icons
are just the logo scaled onto that same background. The maskable icon shrinks
it so the reticle's tick marks stay inside the central 80% safe circle.

Usage (from the repo root):  uv run python scripts/make_pwa_icons.py
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "marketing" / "logo.png"
OUT = ROOT / "web" / "public"

BACKGROUND = (10, 0, 0)  # #0a0000, the logo's own background


def render(size: int, scale: float, logo: Image.Image) -> Image.Image:
    """Square icon with the logo drawn `scale` of the canvas wide, centred."""
    inner = round(size * scale)
    canvas = Image.new("RGB", (size, size), BACKGROUND)
    off = (size - inner) // 2
    canvas.paste(logo.resize((inner, inner), Image.LANCZOS), (off, off))
    return canvas


def main() -> None:
    logo = Image.open(SOURCE).convert("RGB")
    # Maskable: content must sit inside the central 80% circle. The tick
    # marks reach 40% of the width from centre at full size, so 0.8 brings
    # them in to 32%.
    icons = {
        "icon-192.png": (192, 1.0),
        "icon-512.png": (512, 1.0),
        "icon-maskable-512.png": (512, 0.8),
        "apple-touch-icon.png": (180, 1.0),
    }
    for name, (size, scale) in icons.items():
        render(size, scale, logo).save(OUT / name, optimize=True)
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
