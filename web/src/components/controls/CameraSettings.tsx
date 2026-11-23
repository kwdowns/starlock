import { Card, Separator } from "@/components/ui";
import { SolveStats } from "@/components/step/TrackingPanel";
import type { EnginePayload } from "@/lib/types";
import { CameraControls } from "./CameraControls";

/**
 * Exposure / gain and the plate-solve stats they drive, under the camera
 * frame. Opened with the pencil on the frame.
 */
export function CameraSettings({
  state,
  id,
  className,
}: {
  state: EnginePayload;
  id?: string;
  className?: string;
}) {
  return (
    <Card id={id} aria-label="Camera settings" className={className}>
      <CameraControls controls={state.controls} />
      <Separator />
      <SolveStats state={state} />
    </Card>
  );
}
