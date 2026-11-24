import { useEffect, useRef, useState } from "react";
import { Eraser, RotateCcw } from "lucide-react";
import { Alert, Button } from "@/components/ui";
import { api } from "@/lib/api";
import {
  BAND_COUNT,
  CLEAR_HORIZON,
  DEFAULT_HORIZON,
  SECTOR_COUNT,
  SECTOR_NAMES,
  horizonFrom,
  isHidden,
  sameMask,
  sectorOf,
  withCell,
  type HorizonMask,
} from "@/lib/horizon";
import type { EnginePayload } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_SIZE = 360;
/** Room outside the circle for the direction labels. */
const LABEL_MARGIN = 30;
/** The empty centre disc, as a fraction of the chart radius. */
const HOLE = 0.2;
/** Pointer samples along a fast drag, in px, so no cell in between is skipped. */
const DRAG_STEP_PX = 4;

interface Geometry {
  /** Centre (x = y). */
  c: number;
  /** Chart radius: the horizon. */
  r: number;
  /** Ring width. */
  w: number;
}

function geometry(size: number): Geometry {
  const r = Math.max(10, size / 2 - LABEL_MARGIN);
  return { c: size / 2, r, w: ((1 - HOLE) * r) / BAND_COUNT };
}

/** Screen point at `radius` and `deg` clockwise from up (north at the top, east right). */
function polar(g: Geometry, radius: number, deg: number): [number, number] {
  const a = (deg * Math.PI) / 180;
  return [g.c + radius * Math.sin(a), g.c - radius * Math.cos(a)];
}

function cellPath(g: Geometry, sector: number, band: number): string {
  const outer = g.r - band * g.w;
  const inner = g.r - (band + 1) * g.w;
  const a0 = sector * 22.5 - 11.25;
  const a1 = sector * 22.5 + 11.25;
  const [x0, y0] = polar(g, outer, a0);
  const [x1, y1] = polar(g, outer, a1);
  const [x2, y2] = polar(g, inner, a1);
  const [x3, y3] = polar(g, inner, a0);
  const f = (n: number) => n.toFixed(2);
  return (
    `M${f(x0)} ${f(y0)}A${f(outer)} ${f(outer)} 0 0 1 ${f(x1)} ${f(y1)}` +
    `L${f(x2)} ${f(y2)}A${f(inner)} ${f(inner)} 0 0 0 ${f(x3)} ${f(y3)}Z`
  );
}

/** The cell under a point relative to the chart's top-left corner, or null outside the rings. */
function cellAt(g: Geometry, x: number, y: number): { sector: number; band: number } | null {
  const dx = x - g.c;
  const dy = y - g.c;
  const radius = Math.hypot(dx, dy);
  // A little slack outside the horizon ring: fingers are wide.
  if (radius < HOLE * g.r || radius > g.r + 6) return null;
  const band = Math.max(0, Math.min(BAND_COUNT - 1, Math.floor((g.r - radius) / g.w)));
  const deg = (Math.atan2(dx, -dy) * 180) / Math.PI;
  return { sector: sectorOf(deg), band };
}

function cellLabel(sector: number, band: number, hidden: boolean): string {
  return `${SECTOR_NAMES[sector]}, ${band * 10} to ${band * 10 + 10} degrees, ${hidden ? "hidden" : "visible"}`;
}

/** Width of an element, following resizes. */
function useWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      const w = Math.round(el.getBoundingClientRect().width);
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

interface Paint {
  pointerId: number;
  /** Mode set by the first cell touched: true = hide, false = clear. */
  hide: boolean;
  mask: number[];
  last: [number, number];
}

interface ChartProps {
  value: HorizonMask;
  /** Called once per tap or drag, when the finger lifts, with the new mask. */
  onCommit: (mask: number[]) => void;
  className?: string;
}

/**
 * The sky seen from above, north up and east right: 16 direction wedges ×
 * 9 rings of 10°, horizon outside, zenith in the middle. Tap a cell to
 * toggle it; drag to paint (the first cell decides hide or clear).
 */
export function HorizonChart({ value, onCommit, className }: ChartProps) {
  const [box, size] = useWidth<HTMLDivElement>(300);
  const [paint, setPaint] = useState<Paint | null>(null);
  const g = geometry(size);
  const shown = paint?.mask ?? value;

  function point(e: React.PointerEvent<SVGSVGElement>): [number, number] {
    const rect = e.currentTarget.getBoundingClientRect();
    const k = rect.width > 0 ? size / rect.width : 1;
    return [(e.clientX - rect.left) * k, (e.clientY - rect.top) * k];
  }

  function onPointerDown(e: React.PointerEvent<SVGSVGElement>) {
    if (paint || (e.pointerType === "mouse" && e.button !== 0)) return;
    const p = point(e);
    const cell = cellAt(g, p[0], p[1]);
    if (!cell) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const hide = !isHidden(value, cell.sector, cell.band);
    setPaint({
      pointerId: e.pointerId,
      hide,
      mask: withCell(value, cell.sector, cell.band, hide),
      last: p,
    });
  }

  function onPointerMove(e: React.PointerEvent<SVGSVGElement>) {
    if (!paint || e.pointerId !== paint.pointerId) return;
    const p = point(e);
    const [x0, y0] = paint.last;
    const steps = Math.max(1, Math.ceil(Math.hypot(p[0] - x0, p[1] - y0) / DRAG_STEP_PX));
    let mask = paint.mask;
    for (let i = 1; i <= steps; i++) {
      const t = i / steps;
      const cell = cellAt(g, x0 + (p[0] - x0) * t, y0 + (p[1] - y0) * t);
      if (cell && isHidden(mask, cell.sector, cell.band) !== paint.hide) {
        mask = withCell(mask, cell.sector, cell.band, paint.hide);
      }
    }
    setPaint({ ...paint, mask, last: p });
  }

  function onPointerEnd(e: React.PointerEvent<SVGSVGElement>) {
    if (!paint || e.pointerId !== paint.pointerId) return;
    setPaint(null);
    if (!sameMask(paint.mask, value)) onCommit(paint.mask);
  }

  function toggle(sector: number, band: number) {
    onCommit(withCell(value, sector, band, !isHidden(value, sector, band)));
  }

  const cells = [];
  for (let s = 0; s < SECTOR_COUNT; s++) {
    for (let b = 0; b < BAND_COUNT; b++) {
      const hidden = isHidden(shown, s, b);
      cells.push(
        <path
          key={`${s}-${b}`}
          d={cellPath(g, s, b)}
          role="button"
          tabIndex={0}
          aria-label={cellLabel(s, b, hidden)}
          data-hidden={hidden || undefined}
          className={cn(
            "outline-none focus-visible:stroke-primary focus-visible:stroke-2",
            hidden ? "fill-primary" : "fill-transparent",
          )}
          fillOpacity={hidden ? 0.45 : undefined}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              toggle(s, b);
            }
          }}
          // Clicks from a keyboard or screen reader (detail 0); pointer taps
          // are handled by the pointer events on the chart.
          onClick={(e) => {
            if (e.detail === 0) toggle(s, b);
          }}
        />,
      );
    }
  }

  const rings = [];
  for (let k = 1; k <= BAND_COUNT; k++) {
    rings.push(<circle key={k} cx={g.c} cy={g.c} r={g.r - k * g.w} />);
  }
  const spokes = [];
  for (let s = 0; s < SECTOR_COUNT; s++) {
    const [x0, y0] = polar(g, HOLE * g.r, s * 22.5 + 11.25);
    const [x1, y1] = polar(g, g.r, s * 22.5 + 11.25);
    spokes.push(<line key={s} x1={x0} y1={y0} x2={x1} y2={y1} />);
  }

  return (
    <div ref={box} className={cn("mx-auto w-full", className)} style={{ maxWidth: MAX_SIZE }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="group"
        aria-label="Horizon chart: north at the top, east on the right"
        className="block touch-none select-none"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
      >
        <g>{cells}</g>
        <g aria-hidden className="pointer-events-none fill-none stroke-border" strokeWidth={1}>
          {rings}
          {spokes}
          <circle cx={g.c} cy={g.c} r={g.r} className="stroke-input" />
        </g>
        <circle aria-hidden cx={g.c} cy={g.c} r={2.5} className="pointer-events-none fill-muted-foreground" />
        <g aria-hidden className="pointer-events-none">
          {SECTOR_NAMES.map((name, s) => {
            const [x, y] = polar(g, g.r + 15, s * 22.5);
            const tier = s % 4 === 0 ? 0 : s % 2 === 0 ? 1 : 2;
            return (
              <text
                key={name}
                x={x}
                y={y}
                textAnchor="middle"
                dominantBaseline="central"
                className={cn(
                  "font-medium",
                  tier === 2 ? "fill-muted-foreground" : "fill-foreground",
                )}
                fontSize={[14, 13, 12][tier]}
              >
                {name}
              </text>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

interface Props {
  state: EnginePayload;
}

/**
 * Settings → Horizon: mark the sky trees and buildings hide, so Tonight
 * skips objects behind them. Changes show at once and go to the engine as
 * one POST per tap or drag; on an error the chart goes back to the
 * engine's mask.
 */
export function HorizonEditor({ state }: Props) {
  const engine = horizonFrom(state.horizon?.obscured);
  const engineKey = engine.join(",");
  const [draft, setDraft] = useState<HorizonMask | null>(null);
  const [inflight, setInflight] = useState(0);
  const [error, setError] = useState(false);

  // Follow the engine once nothing of ours is in flight (adjusting state
  // while rendering, as LocationPanel does, rather than in an effect).
  const [seenKey, setSeenKey] = useState(engineKey);
  if (seenKey !== engineKey) {
    setSeenKey(engineKey);
    if (inflight === 0) setDraft(null);
  }
  const shown = draft ?? engine;

  async function save(mask: HorizonMask, body: { obscured: number[] } | null) {
    setDraft(mask);
    setError(false);
    setInflight((n) => n + 1);
    try {
      await api.setSettings({ horizon: body });
    } catch (e) {
      console.error(e);
      setDraft(null);
      setError(true);
    } finally {
      setInflight((n) => n - 1);
    }
  }

  return (
    <section className="flex flex-col gap-3" aria-labelledby="horizon-heading">
      <h3 id="horizon-heading" className="text-heading text-foreground">
        Horizon
      </h3>
      <p className="text-label text-foreground">
        Tap the parts of the sky that trees or buildings hide from you. Tonight's list skips
        objects behind them.
      </p>
      <HorizonChart value={shown} onCommit={(mask) => void save(mask, { obscured: mask })} />
      <p className="text-label text-muted-foreground">
        Outer ring: the horizon. Centre: straight up. Each ring is 10°.
      </p>
      {error && <Alert variant="error" title="Couldn't save the horizon" />}
      <div className="flex gap-2">
        <Button
          variant="secondary"
          disabled={sameMask(shown, DEFAULT_HORIZON)}
          onClick={() => void save(DEFAULT_HORIZON, null)}
        >
          <RotateCcw aria-hidden />
          Reset
        </Button>
        <Button
          variant="secondary"
          disabled={sameMask(shown, CLEAR_HORIZON)}
          onClick={() => void save(CLEAR_HORIZON, { obscured: [...CLEAR_HORIZON] })}
        >
          <Eraser aria-hidden />
          Clear all
        </Button>
      </div>
    </section>
  );
}
