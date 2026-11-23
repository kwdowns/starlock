import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame, useThree } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import { LABEL_STYLE, LABEL_Z_INDEX_RANGE } from "./constants";
import { altAzTo3D, AZIMUTH_DIRECTIONS, RADIUS } from "./geometry";
import { placeLabels } from "./labelPlacement";

export interface MarkerLabel {
  id: string;
  text: string;
  color: string;
  altDeg: number;
  azDeg: number;
}

interface Props {
  /** In priority order: the first keeps its label when dots coincide. */
  markers: MarkerLabel[];
  gridColor: string;
}

/**
 * All the dome's text labels. Each frame the anchors are projected to screen
 * pixels and `placeLabels` decides which marker labels go above/below their
 * dot and which compass/zenith labels are hidden, so none overlap.
 */
export function DomeLabels({ markers, gridColor }: Props) {
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const els = useRef(new Map<string, HTMLDivElement>());

  const grid = useMemo(() => {
    const items = AZIMUTH_DIRECTIONS.filter((d) => d.label !== "").map((d) => {
      const p = altAzTo3D(0, d.az, RADIUS + 0.2);
      return { id: `grid-${d.label}`, text: d.label, pos: new THREE.Vector3(p.x, 0.02, p.z) };
    });
    items.push({ id: "grid-Z", text: "Z", pos: new THREE.Vector3(0, RADIUS + 0.15, 0) });
    return items;
  }, []);

  const markerPos = useMemo(
    () => markers.map((m) => altAzTo3D(m.altDeg, m.azDeg, RADIUS)),
    [markers],
  );

  const tmp = useMemo(() => new THREE.Vector3(), []);

  useFrame(() => {
    const project = (v: THREE.Vector3) => {
      tmp.copy(v).project(camera);
      return {
        x: ((tmp.x + 1) / 2) * size.width,
        y: ((1 - tmp.y) / 2) * size.height,
      };
    };
    const dims = (id: string) => {
      const el = els.current.get(id);
      return { w: el?.offsetWidth ?? 40, h: el?.offsetHeight ?? 12 };
    };
    const result = placeLabels(
      markers.map((m, i) => ({ id: m.id, ...project(markerPos[i]), ...dims(m.id) })),
      grid.map((g) => ({ id: g.id, ...project(g.pos), ...dims(g.id) })),
    );
    for (const [id, p] of Object.entries(result)) {
      const el = els.current.get(id);
      if (!el) continue;
      el.style.visibility = p.visible ? "visible" : "hidden";
      if (!id.startsWith("grid-")) {
        el.style.transform =
          p.side === "above" ? "translateY(calc(-100% - 10px))" : "translateY(10px)";
      }
    }
  });

  const ref = (id: string) => (el: HTMLDivElement | null) => {
    if (el) els.current.set(id, el);
    else els.current.delete(id);
  };

  return (
    <>
      {markers.map((m, i) => (
        <Html
          key={m.id}
          position={[markerPos[i].x, markerPos[i].y, markerPos[i].z]}
          center
          pointerEvents="none"
          zIndexRange={LABEL_Z_INDEX_RANGE}
        >
          <div
            ref={ref(m.id)}
            style={{
              ...LABEL_STYLE,
              color: m.color,
              transform: "translateY(calc(-100% - 10px))",
            }}
          >
            {m.text}
          </div>
        </Html>
      ))}
      {grid.map((g) => (
        <Html
          key={g.id}
          position={[g.pos.x, g.pos.y, g.pos.z]}
          center
          pointerEvents="none"
          zIndexRange={LABEL_Z_INDEX_RANGE}
        >
          <div ref={ref(g.id)} style={{ ...LABEL_STYLE, color: gridColor }}>
            {g.text}
          </div>
        </Html>
      ))}
    </>
  );
}
