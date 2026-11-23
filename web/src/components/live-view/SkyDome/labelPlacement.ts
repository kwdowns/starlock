/**
 * Screen-space placement of the sky dome's labels, so none ever overlap.
 * Pure (no three.js): the dome projects the anchors to pixels each frame and
 * applies the result. Mirrors the iOS StarlockKit SkyDomeLabels.swift.
 *
 * Rule (px, y down; gap = 3):
 *  - Obstacles: every marker dot (a circle's bounding square, padded gap/2),
 *    the canvas edge, and every label already placed (padded gap/2).
 *  - Marker labels (target first, then scope) are never hidden. Candidate
 *    centres, in order: above, below, right, left of the dot, at a distance of
 *    radius + 2*gap + half the label's height (above/below) or width
 *    (right/left). The first with zero cost wins; otherwise the lowest cost.
 *    cost = label area outside the canvas + overlap area with placed boxes.
 *  - Exception: a marker whose dot is closer than 1.6 * max(radius) to an
 *    earlier marker's dot (scope on target) gets no label.
 *  - Compass / zenith labels (droppable) have one spot, centred on their
 *    anchor; hidden if their box would overlap anything placed, leave the
 *    canvas, or touch a line segment (scope shaft, lines to the target).
 */

export interface Bounds {
  w: number;
  h: number;
}

export interface MarkerLabelInput {
  id: string;
  /** Dot centre, px. */
  x: number;
  y: number;
  /** Dot radius, px. */
  radius: number;
  /** Label size, px. */
  w: number;
  h: number;
}

export interface GridLabelInput {
  id: string;
  /** Label centre, px. */
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Segment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface LabelPlacement {
  visible: boolean;
  /** Label centre minus anchor, px. */
  dx: number;
  dy: number;
}

export const MERGE_RADII = 1.6;

interface Rect {
  l: number;
  t: number;
  r: number;
  b: number;
}

const area = (a: Rect) => Math.max(0, a.r - a.l) * Math.max(0, a.b - a.t);

function overlapArea(a: Rect, b: Rect): number {
  const w = Math.min(a.r, b.r) - Math.max(a.l, b.l);
  const h = Math.min(a.b, b.b) - Math.max(a.t, b.t);
  return w > 0 && h > 0 ? w * h : 0;
}

const grow = (a: Rect, p: number): Rect => ({
  l: a.l - p,
  t: a.t - p,
  r: a.r + p,
  b: a.b + p,
});

const centred = (x: number, y: number, w: number, h: number): Rect => ({
  l: x - w / 2,
  t: y - h / 2,
  r: x + w / 2,
  b: y + h / 2,
});

/** Does the segment pass through the rectangle (Liang-Barsky)? */
export function segmentHitsRect(s: Segment, r: Rect): boolean {
  let t0 = 0;
  let t1 = 1;
  const dx = s.x2 - s.x1;
  const dy = s.y2 - s.y1;
  const edges: [number, number][] = [
    [-dx, s.x1 - r.l],
    [dx, r.r - s.x1],
    [-dy, s.y1 - r.t],
    [dy, r.b - s.y1],
  ];
  for (const [p, q] of edges) {
    if (p === 0) {
      if (q < 0) return false;
    } else {
      const t = q / p;
      if (p < 0) {
        if (t > t1) return false;
        t0 = Math.max(t0, t);
      } else {
        if (t < t0) return false;
        t1 = Math.min(t1, t);
      }
    }
  }
  return true;
}

export function placeLabels(
  markers: MarkerLabelInput[],
  grid: GridLabelInput[],
  bounds: Bounds,
  segments: Segment[] = [],
  gap = 3,
): Record<string, LabelPlacement> {
  const canvas: Rect = { l: 0, t: 0, r: bounds.w, b: bounds.h };
  const pad = gap / 2;
  const placed: Rect[] = markers.map((m) =>
    grow(centred(m.x, m.y, m.radius * 2, m.radius * 2), pad),
  );
  const out: Record<string, LabelPlacement> = {};

  const cost = (rect: Rect): number => {
    const padded = grow(rect, pad);
    let total = area(rect) - overlapArea(rect, canvas);
    for (const o of placed) total += overlapArea(padded, o);
    return total < 1e-6 ? 0 : total;
  };

  const seen: MarkerLabelInput[] = [];
  for (const m of markers) {
    const merged = seen.some(
      (o) => Math.hypot(o.x - m.x, o.y - m.y) < Math.max(o.radius, m.radius) * MERGE_RADII,
    );
    seen.push(m);
    if (merged) {
      out[m.id] = { visible: false, dx: 0, dy: -m.radius - 2 * gap - m.h / 2 };
      continue;
    }
    const dy = m.radius + 2 * gap + m.h / 2;
    const dx = m.radius + 2 * gap + m.w / 2;
    const candidates: [number, number][] = [
      [0, -dy],
      [0, dy],
      [dx, 0],
      [-dx, 0],
    ];
    let best = candidates[0];
    let bestCost = Infinity;
    for (const c of candidates) {
      const k = cost(centred(m.x + c[0], m.y + c[1], m.w, m.h));
      if (k < bestCost) {
        best = c;
        bestCost = k;
        if (k === 0) break;
      }
    }
    placed.push(grow(centred(m.x + best[0], m.y + best[1], m.w, m.h), pad));
    out[m.id] = { visible: true, dx: best[0], dy: best[1] };
  }

  for (const g of grid) {
    const rect = centred(g.x, g.y, g.w, g.h);
    const hit = cost(rect) > 0 || segments.some((s) => segmentHitsRect(s, grow(rect, pad)));
    if (!hit) placed.push(grow(rect, pad));
    out[g.id] = { visible: !hit, dx: 0, dy: 0 };
  }
  return out;
}
