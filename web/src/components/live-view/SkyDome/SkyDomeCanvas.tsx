import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame, useThree } from "@react-three/fiber";
import { Edges, Line, OrbitControls } from "@react-three/drei";
import { HemisphereGrid } from "./HemisphereGrid";
import { DomeLabels, type MarkerLabel } from "./DomeLabels";
import { Marker } from "./Marker";
import type { ThemeColors } from "./types";

const RADIUS = 2;
const SCOPE_LENGTH = RADIUS * 0.3;
const SCOPE_RADIUS = 0.1;

function altAzTo3D(altDeg: number, azDeg: number, radius = RADIUS) {
  const alt = altDeg * (Math.PI / 180);
  const az = -azDeg * (Math.PI / 180);
  return new THREE.Vector3(
    radius * Math.cos(alt) * Math.sin(az),
    radius * Math.sin(alt),
    radius * Math.cos(alt) * Math.cos(az),
  );
}

interface Pos {
  altDeg: number;
  azDeg: number;
}

interface Props {
  pointing: Pos | null;
  target: (Pos & { label?: string }) | null;
  colors: ThemeColors;
  spinKey?: number;
}

const SPIN_S = 2.4;
const UP = new THREE.Vector3(0, 1, 0);

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined"
    && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

/**
 * One full turn of the camera around the dome each time `spinKey` changes
 * (not on mount). The orbit controls follow, so a drag afterwards starts
 * from wherever the turn ended.
 */
function DomeSpin({ spinKey }: { spinKey?: number }) {
  const controls = useThree((s) => s.controls) as { update?: () => void } | null;
  const seen = useRef(spinKey);
  const spin = useRef<{ t: number; angle: number } | null>(null);
  useFrame(({ camera }, delta) => {
    if (seen.current !== spinKey) {
      seen.current = spinKey;
      if (!prefersReducedMotion()) spin.current = { t: 0, angle: 0 };
    }
    const s = spin.current;
    if (!s) return;
    s.t = Math.min(1, s.t + delta / SPIN_S);
    const angle = easeInOutCubic(s.t) * 2 * Math.PI;
    camera.position.applyAxisAngle(UP, angle - s.angle);
    s.angle = angle;
    camera.lookAt(0, 0, 0);
    controls?.update?.();
    if (s.t >= 1) spin.current = null;
  });
  return null;
}

function Telescope({ direction, color }: { direction: THREE.Vector3; color: string }) {
  // Cylinder is built along the local Y axis by default; rotate so Y aligns
  // with the pointing direction, then translate to sit between origin and
  // SCOPE_LENGTH along that direction.
  const { position, quaternion } = useMemo(() => {
    const dir = direction.clone().normalize();
    const center = dir.clone().multiplyScalar(SCOPE_LENGTH / 2);
    const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
    return { position: center, quaternion: q };
  }, [direction]);

  return (
    <mesh position={position} quaternion={quaternion}>
      <cylinderGeometry args={[SCOPE_RADIUS, SCOPE_RADIUS, SCOPE_LENGTH, 16]} />
      <meshBasicMaterial color={color} transparent opacity={0.25} />
      <Edges threshold={30} color={color} />
    </mesh>
  );
}

export function SkyDomeCanvas({ pointing, target, colors, spinKey }: Props) {
  const pointingVec =
    pointing && pointing.altDeg >= 0
      ? altAzTo3D(pointing.altDeg, pointing.azDeg)
      : null;
  const targetVec =
    target && target.altDeg >= 0
      ? altAzTo3D(target.altDeg, target.azDeg)
      : null;

  const labels = useMemo(() => {
    const list: MarkerLabel[] = [];
    // Target first: when the scope is on it, the target's name is the one kept.
    if (target && target.altDeg >= 0) {
      list.push({ id: "target", text: target.label || "Target", color: colors.target, ...target });
    }
    if (pointing && pointing.altDeg >= 0) {
      list.push({ id: "scope", text: "Scope", color: colors.pointing, ...pointing });
    }
    return list;
  }, [pointing, target, colors.target, colors.pointing]);

  return (
    <>
      <OrbitControls
        makeDefault
        enableZoom={true}
        enablePan={false}
        minDistance={3.5}
        maxDistance={8}
        minPolarAngle={0}
        maxPolarAngle={Math.PI / 2}
        rotateSpeed={0.5}
      />
      <DomeSpin spinKey={spinKey} />
      <ambientLight intensity={0.5} />
      <HemisphereGrid colors={colors} />

      {targetVec && (
        <Line
          points={[[0, 0, 0], [targetVec.x, targetVec.y, targetVec.z]]}
          color={colors.line}
          lineWidth={1.5}
          dashed
          dashSize={0.1}
          gapSize={0.06}
        />
      )}
      {pointingVec && (
        <>
          <Line
            points={[[0, 0, 0], [pointingVec.x, pointingVec.y, pointingVec.z]]}
            color={colors.line}
            lineWidth={1.5}
          />
          <Telescope direction={pointingVec} color={colors.line} />
        </>
      )}

      {pointing && (
        <Marker
          altDeg={pointing.altDeg}
          azDeg={pointing.azDeg}
          color={colors.pointing}
          size={0.05}
        />
      )}
      {target && (
        <Marker
          altDeg={target.altDeg}
          azDeg={target.azDeg}
          color={colors.target}
          size={0.04}
          hollow
        />
      )}

      <DomeLabels markers={labels} gridColor={colors.gridLabels} />
    </>
  );
}
