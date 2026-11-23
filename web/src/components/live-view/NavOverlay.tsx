import type { EnginePayload, MountMode, MountNav, NavData } from "@/lib/types";
import { formatDegrees, formatDistance } from "@/lib/screen";

interface Props {
  state: EnginePayload;
}

/** Older engines don't send nav.on_target_deg. */
const LOCKED_THRESHOLD_DEG = 0.15;

function lockedDeg(nav: NavData): number {
  return nav.on_target_deg ?? LOCKED_THRESHOLD_DEG;
}

type Zone = "PUSH" | "CONVERGE" | "LOCKED";

function pickZone(nav: NavData): Zone {
  if (nav.in_fov && nav.separation_deg !== null && nav.separation_deg <= lockedDeg(nav)) {
    return "LOCKED";
  }
  if (nav.in_fov) return "CONVERGE";
  return "PUSH";
}

/** Text on a dark rounded label so it reads over stars. */
function Pill({ x, y, text, fontSize }: { x: number; y: number; text: string; fontSize: number }) {
  const w = text.length * (fontSize * 0.6) + 14;
  const h = fontSize + 8;
  return (
    <g>
      <rect
        x={x - w / 2} y={y - h / 2} width={w} height={h} rx={5}
        style={{ fill: "var(--overlay-label-bg)" }}
      />
      <text
        x={x} y={y} textAnchor="middle" dominantBaseline="middle"
        fontSize={fontSize} fontWeight="bold" className="fill-overlay-strong"
      >
        {text}
      </text>
    </g>
  );
}

/** Eyepiece reticle: ring + cross arms. */
function Reticle({
  cx, cy, ringR, armOuter, armInner, strokeW, className,
}: {
  cx: number; cy: number; ringR: number; armOuter: number; armInner: number;
  strokeW: number; className: string;
}) {
  return (
    <g strokeWidth={strokeW} fill="none" className={className}>
      <circle cx={cx} cy={cy} r={ringR} />
      <line x1={cx - armOuter} y1={cy} x2={cx - armInner} y2={cy} />
      <line x1={cx + armInner} y1={cy} x2={cx + armOuter} y2={cy} />
      <line x1={cx} y1={cy - armOuter} x2={cx} y2={cy - armInner} />
      <line x1={cx} y1={cy + armInner} x2={cx} y2={cy + armOuter} />
    </g>
  );
}

/** Comet-style arrow: a solid head with fading copies trailing behind.
 * angleDeg is clockwise from up (the tip points to (0,-22) locally). */
function CometArrow({ cx, cy, angleDeg, scale }: { cx: number; cy: number; angleDeg: number; scale: number }) {
  const ghosts = [4, 3, 2, 1, 0];
  return (
    <g transform={`translate(${cx}, ${cy}) rotate(${angleDeg}) scale(${scale})`} className="fill-overlay-strong">
      {ghosts.map((i) => (
        <polygon
          key={i}
          transform={`translate(0 ${i * 9})`}
          opacity={1 - i * 0.18}
          points="0,-22 -11,0 -3,0 -3,18 3,18 3,0 11,0"
        />
      ))}
    </g>
  );
}

/** Distance from (ox, oy) along unit (ux, uy) to the frame edge inset by margin. */
function rayToEdge(
  ox: number, oy: number, ux: number, uy: number, w: number, h: number, margin: number,
): number {
  let t = Infinity;
  if (ux > 1e-9) t = Math.min(t, (w - margin - ox) / ux);
  if (ux < -1e-9) t = Math.min(t, (margin - ox) / ux);
  if (uy > 1e-9) t = Math.min(t, (h - margin - oy) / uy);
  if (uy < -1e-9) t = Math.min(t, (margin - oy) / uy);
  return Math.max(0, t);
}

/** Below this a mount axis needs no move. */
const AXIS_DONE_DEG = 0.05;

function axisLabels(mode: MountMode, m: MountNav): [string, string] {
  if (mode === "eq") {
    return [
      `RA ${m.axis1_deg >= 0 ? "E" : "W"} ${formatDegrees(m.axis1_deg)}`,
      `Dec ${m.axis2_deg >= 0 ? "N" : "S"} ${formatDegrees(m.axis2_deg)}`,
    ];
  }
  return [
    `Turn ${m.axis1_deg >= 0 ? "right" : "left"} ${formatDegrees(m.axis1_deg)}`,
    `${m.axis2_deg >= 0 ? "Raise" : "Lower"} ${formatDegrees(m.axis2_deg)}`,
  ];
}

/**
 * Target off-frame, mount axes known: one arrow per mount axis, pointing the
 * way the view moves for that push. The bigger move is drawn bold.
 */
function MountArrows({ state, m }: { state: EnginePayload; m: MountNav }) {
  const ox = state.origin_x;
  const oy = state.origin_y;
  const k = state.image_w / 1280;
  const fs = 48 * k;
  const labels = axisLabels(state.mount.mode, m);
  const moves = [
    { id: "axis1", deg: m.axis1_deg, angle: m.axis1_angle_deg, label: labels[0] },
    { id: "axis2", deg: m.axis2_deg, angle: m.axis2_angle_deg, label: labels[1] },
  ].filter((a) => Math.abs(a.deg) >= AXIS_DONE_DEG);
  const biggest = Math.max(...moves.map((a) => Math.abs(a.deg)));

  return (
    <g>
      <Reticle cx={ox} cy={oy} ringR={12} armInner={4} armOuter={20} strokeW={1}
               className="stroke-overlay-dim" />
      {moves.map((a) => {
        const primary = Math.abs(a.deg) === biggest;
        const angle = a.deg >= 0 ? a.angle : a.angle + 180;
        const r = (angle * Math.PI) / 180;
        const ux = Math.sin(r);
        const uy = -Math.cos(r);
        const reach = rayToEdge(ox, oy, ux, uy, state.image_w, state.image_h, 110 * k);
        const len = Math.min(reach, 0.42 * Math.min(state.image_w, state.image_h));
        const tipX = ox + ux * len;
        const tipY = oy + uy * len;
        // Label beside the arrow, off to the side of the push line.
        const lx = ox + ux * len * 0.55 - uy * 60 * k;
        const ly = oy + uy * len * 0.55 + ux * 60 * k;
        return (
          <g key={a.id} opacity={primary ? 1 : 0.65}>
            <line x1={ox} y1={oy} x2={tipX} y2={tipY}
                  strokeWidth={primary ? 3 : 2} strokeDasharray="8 6"
                  className="stroke-overlay-strong starlock-marching-ants" />
            <CometArrow cx={tipX} cy={tipY} angleDeg={angle} scale={(primary ? 1.6 : 1.1) * k} />
            <Pill x={lx} y={ly} text={a.label} fontSize={fs} />
          </g>
        );
      })}
    </g>
  );
}

export function NavOverlay({ state }: Props) {
  const nav = state.nav;
  if (!nav || !nav.active) return null;

  const zone = pickZone(nav);
  const ox = state.origin_x;
  const oy = state.origin_y;
  // Sized so text stays >= 12 px on a 1280 px frame shown 360 px wide (a
  // phone); scales with the frame's resolution.
  const k = state.image_w / 1280;
  const fs = 48 * k;

  if (zone === "PUSH" && nav.mount) {
    return <MountArrows state={state} m={nav.mount} />;
  }

  if (zone === "PUSH") {
    if (nav.edge_x === null || nav.edge_y === null || nav.edge_angle_deg === null) {
      return null;
    }
    const angleRad = (nav.edge_angle_deg * Math.PI) / 180;
    // Arrow tip 68 px in from the frame edge.
    const tipX = nav.edge_x - Math.sin(angleRad) * 90 * k;
    const tipY = nav.edge_y + Math.cos(angleRad) * 90 * k;
    // Distance label sits off to one side of the push line.
    const dx = tipX - ox;
    const dy = tipY - oy;
    const len = Math.hypot(dx, dy) || 1;
    const labelX = tipX + (-dy / len) * 60 * k;
    const labelY = tipY + (dx / len) * 60 * k;
    return (
      <g>
        <Reticle cx={ox} cy={oy} ringR={12} armInner={4} armOuter={20} strokeW={1}
                 className="stroke-overlay-dim" />
        <line x1={ox} y1={oy} x2={nav.edge_x} y2={nav.edge_y}
              strokeWidth={2} strokeDasharray="8 6"
              className="stroke-overlay-strong starlock-marching-ants" />
        <CometArrow cx={tipX} cy={tipY} angleDeg={nav.edge_angle_deg} scale={1.6 * k} />
        <Pill x={labelX} y={labelY} text={formatDistance(nav.separation_deg)} fontSize={fs} />
      </g>
    );
  }

  if (zone === "CONVERGE") {
    if (nav.pixel_x === null || nav.pixel_y === null) return null;
    const tx = nav.pixel_x;
    const ty = nav.pixel_y;
    // Ring showing the lock zone around the eyepiece centre.
    const scale = state.image_w / (2 * Math.tan((state.fov_h_deg / 2) * (Math.PI / 180)));
    const lockR = Math.tan(lockedDeg(nav) * (Math.PI / 180)) * scale;
    const dx = tx - ox;
    const dy = ty - oy;
    const len = Math.hypot(dx, dy) || 1;
    const perpX = -dy / len;
    const perpY = dx / len;
    return (
      <g>
        <Reticle cx={ox} cy={oy} ringR={14} armInner={5} armOuter={24} strokeW={2}
                 className="stroke-overlay" />
        <circle cx={ox} cy={oy} r={lockR} strokeWidth={1} fill="none"
                className="stroke-overlay-dim" />
        <line x1={ox} y1={oy} x2={tx} y2={ty} strokeWidth={1} strokeDasharray="8 6"
              className="stroke-overlay starlock-marching-ants" />
        {/* Target marker: glides between WebSocket updates. */}
        <g style={{ transform: `translate(${tx}px, ${ty}px)`, transition: "transform 100ms linear" }}>
          <circle cx={0} cy={0} r={18} strokeWidth={2} fill="none" className="stroke-overlay-strong" />
          <circle cx={0} cy={0} r={2} className="fill-overlay-strong" />
        </g>
        <Pill x={tx + perpX * 50 * k} y={ty + perpY * 50 * k} text={formatDistance(nav.separation_deg)} fontSize={fs} />
        {nav.target_name && (
          <Pill x={tx + perpX * 100 * k} y={ty + perpY * 100 * k} text={nav.target_name} fontSize={fs} />
        )}
      </g>
    );
  }

  // LOCKED: concentric rings + centre dot, gently pulsing.
  return (
    <g>
      <g fill="none" className="stroke-overlay-strong animate-pulse">
        <circle cx={ox} cy={oy} r={20} strokeWidth={2} />
        <circle cx={ox} cy={oy} r={14} strokeWidth={3} />
        <circle cx={ox} cy={oy} r={8} strokeWidth={2} />
        <circle cx={ox} cy={oy} r={4} className="fill-overlay-strong" stroke="none" />
      </g>
      {nav.target_name && <Pill x={ox} y={oy - 60 * k} text={nav.target_name} fontSize={fs} />}
      <Pill x={ox} y={oy + 60 * k} text="ON TARGET" fontSize={fs} />
    </g>
  );
}
