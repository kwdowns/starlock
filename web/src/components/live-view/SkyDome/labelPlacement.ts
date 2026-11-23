/**
 * Screen-space placement of the sky dome's labels, so none ever overlap.
 * Pure (no three.js): the dome projects the anchors to pixels each frame and
 * applies the result.
 *
 * Rule:
 *  1. Marker labels (target first, then scope) sit above their dot by
 *     default. A later marker whose dot lies within `coincidePx` of an
 *     earlier one (on target) hides its label: one name is enough.
 *  2. Otherwise a marker label tries "above", then "below"; the first spot
 *     that touches no placed label or dot wins. If neither is free it is
 *     hidden.
 *  3. Compass / zenith labels (centred on their anchor) are hidden when
 *     they touch any visible marker label or marker dot.
 */

export type LabelSide = "above" | "below";

export interface MarkerLabelInput {
  id: string;
  /** Dot centre, px. */
  x: number;
  y: number;
  /** Label size, px. */
  w: number;
  h: number;
}

export interface GridLabelInput {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface LabelPlacement {
  visible: boolean;
  side: LabelSide;
}

export interface PlaceOptions {
  /** Gap between the dot centre and the label's near edge, px. */
  gap?: number;
  /** Dots closer than this count as the same spot, px. */
  coincidePx?: number;
  /** Radius of the keep-clear area around a dot, px. */
  dotRadius?: number;
  /** Extra clearance between labels, px. */
  pad?: number;
}

interface Rect {
  l: number;
  t: number;
  r: number;
  b: number;
}

function overlaps(a: Rect, b: Rect, pad: number): boolean {
  return a.l < b.r + pad && a.r > b.l - pad && a.t < b.b + pad && a.b > b.t - pad;
}

export function placeLabels(
  markers: MarkerLabelInput[],
  grid: GridLabelInput[],
  opts: PlaceOptions = {},
): Record<string, LabelPlacement> {
  const gap = opts.gap ?? 10;
  const coincidePx = opts.coincidePx ?? 12;
  const dotRadius = opts.dotRadius ?? 8;
  const pad = opts.pad ?? 2;

  const out: Record<string, LabelPlacement> = {};
  const taken: Rect[] = [];
  const placedDots: { x: number; y: number }[] = [];

  for (const m of markers) {
    const dot: Rect = {
      l: m.x - dotRadius,
      t: m.y - dotRadius,
      r: m.x + dotRadius,
      b: m.y + dotRadius,
    };
    const onTop = placedDots.some((d) => Math.hypot(d.x - m.x, d.y - m.y) < coincidePx);
    placedDots.push({ x: m.x, y: m.y });
    if (onTop) {
      out[m.id] = { visible: false, side: "above" };
      continue;
    }
    const box = (side: LabelSide): Rect => {
      const l = m.x - m.w / 2;
      return side === "above"
        ? { l, r: l + m.w, b: m.y - gap, t: m.y - gap - m.h }
        : { l, r: l + m.w, t: m.y + gap, b: m.y + gap + m.h };
    };
    let chosen: LabelSide | null = null;
    for (const side of ["above", "below"] as const) {
      const b = box(side);
      if (!taken.some((t) => overlaps(b, t, pad))) {
        chosen = side;
        break;
      }
    }
    taken.push(dot);
    if (chosen) {
      taken.push(box(chosen));
      out[m.id] = { visible: true, side: chosen };
    } else {
      out[m.id] = { visible: false, side: "above" };
    }
  }

  for (const g of grid) {
    const b: Rect = {
      l: g.x - g.w / 2,
      r: g.x + g.w / 2,
      t: g.y - g.h / 2,
      b: g.y + g.h / 2,
    };
    out[g.id] = {
      visible: !taken.some((t) => overlaps(b, t, pad)),
      side: "above",
    };
  }
  return out;
}
