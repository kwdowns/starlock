import type { EnginePayload } from "@/lib/types";

interface Props {
  state: EnginePayload;
}

/** Unit vector (SVG, y down) for an image direction clockwise from up. */
function dir(deg: number): [number, number] {
  const r = (deg * Math.PI) / 180;
  return [Math.sin(r), -Math.cos(r)];
}

/** Text rotation that keeps a label at `deg` from ever reading upside-down. */
function readable(deg: number): number {
  const r = ((deg % 360) + 360) % 360;
  return r > 90 && r < 270 ? (r + 180) % 360 : r;
}

/**
 * The mount's two axes drawn through the eyepiece origin, each label sitting
 * on the side the view moves towards. Uses the axes the engine derives from
 * the solve (alt-az with a location, or equatorial); otherwise the
 * calibrated finder_rotation (image direction of mount-up).
 */
export function AxesOverlay({ state }: Props) {
  if (!["CALIBRATE", "WARMING_UP", "TRACKING"].includes(state.state)) return null;
  if (!state.pointing.valid) return null;
  if (state.failures >= 3) return null;

  const axes = state.mount?.axes;
  const eq = state.mount?.mode === "eq" && axes;
  const upDeg = axes ? axes.axis2_angle_deg : state.finder_rotation;
  const rightDeg = axes ? axes.axis1_angle_deg : state.finder_rotation + 90;
  const [upX, upY] = dir(upDeg);
  const [rightX, rightY] = dir(rightDeg);

  const cx = state.origin_x;
  const cy = state.origin_y;
  const halfDiag = Math.sqrt(state.image_w ** 2 + state.image_h ** 2) / 2;
  // Label size tracks the frame width so it stays legible on a phone.
  const k = state.image_w / 1280;
  const d = 200 * k;

  const labels = [
    { text: eq ? "N" : "UP",    x: cx + upX * d,    y: cy + upY * d,    rot: readable(upDeg) },
    { text: eq ? "S" : "DOWN",  x: cx - upX * d,    y: cy - upY * d,    rot: readable(upDeg) },
    { text: eq ? "E" : "RIGHT", x: cx + rightX * d, y: cy + rightY * d, rot: readable(rightDeg - 90) },
    { text: eq ? "W" : "LEFT",  x: cx - rightX * d, y: cy - rightY * d, rot: readable(rightDeg - 90) },
  ];

  return (
    <g className="stroke-overlay-dim fill-overlay">
      {/* Solid, dim lines so they're not confused with the marching-ants nav line. */}
      <line
        x1={cx - upX * halfDiag} y1={cy - upY * halfDiag}
        x2={cx + upX * halfDiag} y2={cy + upY * halfDiag}
        strokeWidth={1}
      />
      <line
        x1={cx - rightX * halfDiag} y1={cy - rightY * halfDiag}
        x2={cx + rightX * halfDiag} y2={cy + rightY * halfDiag}
        strokeWidth={1}
      />
      {labels.map((l) => (
        <text
          key={l.text}
          x={l.x}
          y={l.y}
          transform={`rotate(${l.rot} ${l.x} ${l.y})`}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={48 * k}
          fontWeight="bold"
        >
          {l.text}
        </text>
      ))}
    </g>
  );
}
