import { useMemo } from "react";
import * as THREE from "three";
import { Line } from "@react-three/drei";
import { AZIMUTH_DIRECTIONS } from "./geometry";
import type { ThemeColors } from "./types";

const RADIUS = 2;
const ALTITUDE_STEPS = [15, 30, 45, 60, 75];

function altAzTo3D(altDeg: number, azDeg: number, radius: number) {
  const alt = altDeg * (Math.PI / 180);
  const az = -azDeg * (Math.PI / 180);
  return new THREE.Vector3(
    radius * Math.cos(alt) * Math.sin(az),
    radius * Math.sin(alt),
    radius * Math.cos(alt) * Math.cos(az),
  );
}

function createAltitudeCircle(altDeg: number, radius: number): THREE.Vector3[] {
  const points: THREE.Vector3[] = [];
  const segments = 64;
  for (let i = 0; i <= segments; i++) {
    const azDeg = (i / segments) * 360;
    points.push(altAzTo3D(altDeg, azDeg, radius));
  }
  return points;
}

function createAzimuthLine(azDeg: number, radius: number): THREE.Vector3[] {
  const points: THREE.Vector3[] = [];
  const segments = 16;
  for (let i = 0; i <= segments; i++) {
    const altDeg = (i / segments) * 90;
    points.push(altAzTo3D(altDeg, azDeg, radius));
  }
  return points;
}

export function HemisphereGrid({ colors }: { colors: ThemeColors }) {
  const altitudeCircles = useMemo(
    () => ALTITUDE_STEPS.map((alt) => createAltitudeCircle(alt, RADIUS)),
    [],
  );
  const azimuthLines = useMemo(
    () => AZIMUTH_DIRECTIONS.map((dir) => createAzimuthLine(dir.az, RADIUS)),
    [],
  );
  const horizonCircle = useMemo(() => createAltitudeCircle(0, RADIUS), []);

  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
        <circleGeometry args={[RADIUS, 64]} />
        <meshBasicMaterial color={colors.ground} transparent opacity={0.25} side={2} />
      </mesh>

      <Line
        points={horizonCircle}
        color={colors.horizon}
        lineWidth={1}
        transparent
        opacity={0.5}
      />

      {altitudeCircles.map((points, i) => (
        <Line
          key={`alt-${ALTITUDE_STEPS[i]}`}
          points={points}
          color={colors.gridLines}
          lineWidth={1}
          transparent
          opacity={0.35}
        />
      ))}

      {azimuthLines.map((points, i) => (
        <Line
          key={`az-${AZIMUTH_DIRECTIONS[i].az}`}
          points={points}
          color={colors.gridLines}
          lineWidth={1}
          transparent
          opacity={0.35}
        />
      ))}
    </group>
  );
}
