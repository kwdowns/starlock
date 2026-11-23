import * as THREE from "three";

export const RADIUS = 2;

export const AZIMUTH_DIRECTIONS = [
  { az: 0, label: "N" },
  { az: 22.5, label: "" },
  { az: 45, label: "NE" },
  { az: 67.5, label: "" },
  { az: 90, label: "E" },
  { az: 112.5, label: "" },
  { az: 135, label: "SE" },
  { az: 157.5, label: "" },
  { az: 180, label: "S" },
  { az: 202.5, label: "" },
  { az: 225, label: "SW" },
  { az: 247.5, label: "" },
  { az: 270, label: "W" },
  { az: 292.5, label: "" },
  { az: 315, label: "NW" },
  { az: 337.5, label: "" },
];

export function altAzTo3D(altDeg: number, azDeg: number, radius: number) {
  const alt = altDeg * (Math.PI / 180);
  const az = -azDeg * (Math.PI / 180);
  return new THREE.Vector3(
    radius * Math.cos(alt) * Math.sin(az),
    radius * Math.sin(alt),
    radius * Math.cos(alt) * Math.cos(az),
  );
}
