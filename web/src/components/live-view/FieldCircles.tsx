import { circleRadiusPx, formatMagnification } from "@/lib/equipment";
import type { EnginePayload } from "@/lib/types";

interface Props {
  state: EnginePayload;
  eyepiece: boolean;
  finder: boolean;
}

/** After sync the origin is the scope's aim; before it, it is only the frame centre. */
const AIMED_STATES = ["CALIBRATE", "WARMING_UP", "TRACKING"];

/**
 * The eyepiece's true field (solid) and the finder's field or reflex rings
 * (dashed), centred on the telescope's aim. Strokes are in screen pixels;
 * circles bigger than the frame are clipped by it. Red only.
 */
export function FieldCircles({ state, eyepiece, finder }: Props) {
  const optics = state.observing?.optics;
  if (!optics || !AIMED_STATES.includes(state.state)) return null;

  const { origin_x: cx, origin_y: cy, image_w, image_h, fov_h_deg } = state;
  const radius = (deg: number) => circleRadiusPx(deg, image_w, fov_h_deg);
  const eyepieceR = eyepiece && optics.true_field_deg != null ? radius(optics.true_field_deg) : null;
  const rings = finder
    ? (optics.finder_rings_deg ?? [])
        .map((deg) => ({ deg, r: radius(deg) }))
        .filter((x): x is { deg: number; r: number } => x.r !== null)
    : [];
  if (eyepieceR === null && rings.length === 0) return null;

  // As the other frame labels: >= 12 px on a 1280 px frame shown 360 px wide.
  const k = image_w / 1280;
  const fs = 44 * k;
  let label: { x: number; y: number; text: string } | null = null;
  if (eyepieceR !== null && optics.magnification != null) {
    const text = formatMagnification(optics.magnification);
    const w = text.length * fs * 0.62;
    const pad = 8 * k;
    // Just outside the circle at its upper right, kept inside the frame.
    const x = cx + eyepieceR * Math.SQRT1_2 + pad;
    const y = cy - eyepieceR * Math.SQRT1_2 - pad;
    label = {
      text,
      x: Math.min(Math.max(x, pad), image_w - w - pad),
      y: Math.min(Math.max(y, fs + pad), image_h - pad),
    };
  }

  return (
    <g data-slot="field-circles" fill="none" className="stroke-overlay-strong">
      {rings.map(({ deg, r }) => (
        <circle
          key={deg}
          data-ring={deg}
          cx={cx}
          cy={cy}
          r={r}
          strokeWidth={1}
          strokeOpacity={0.45}
          strokeDasharray="6 5"
          vectorEffect="non-scaling-stroke"
        />
      ))}
      {eyepieceR !== null && (
        <circle
          data-eyepiece=""
          cx={cx}
          cy={cy}
          r={eyepieceR}
          strokeWidth={1.5}
          strokeOpacity={0.7}
          vectorEffect="non-scaling-stroke"
        />
      )}
      {label && (
        <text
          x={label.x}
          y={label.y}
          fontSize={fs}
          fontWeight="bold"
          stroke="none"
          className="fill-overlay-strong"
          fillOpacity={0.85}
        >
          {label.text}
        </text>
      )}
    </g>
  );
}
