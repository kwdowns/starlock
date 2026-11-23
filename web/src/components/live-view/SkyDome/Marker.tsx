import * as THREE from "three";
import { altAzTo3D, RADIUS } from "./geometry";
import { Billboard } from "@react-three/drei";

interface MarkerProps {
  altDeg: number;
  azDeg: number;
  color: string;
  size?: number;
  /** Hollow ring (target) instead of a solid dot (pointing). */
  hollow?: boolean;
}

export function Marker({ altDeg, azDeg, color, size = 0.06, hollow = false }: MarkerProps) {
  if (altDeg < 0) return null;
  const pos = altAzTo3D(altDeg, azDeg, RADIUS);

  return (
    <group position={[pos.x, pos.y, pos.z]}>
      {hollow ? (
        // Always faces the camera so the ring reads as a ring from any angle.
        <Billboard>
          <mesh>
            <ringGeometry args={[size * 1.4, size * 2, 32]} />
            <meshBasicMaterial color={color} side={THREE.DoubleSide} />
          </mesh>
        </Billboard>
      ) : (
        <mesh>
          <sphereGeometry args={[size, 16, 16]} />
          <meshBasicMaterial color={color} />
        </mesh>
      )}
    </group>
  );
}
