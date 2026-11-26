import { Card, Separator, SettingRow, Switch } from "@/components/ui";
import { SolveStats } from "@/components/step/TrackingPanel";
import { useFieldCircle } from "@/hooks/useFieldCircles";
import { formatField, plainNumber, ringsText } from "@/lib/equipment";
import type { EnginePayload, Optics } from "@/lib/types";
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
  const optics = state.observing?.optics;
  const circles = optics && (optics.true_field_deg != null || optics.finder_rings_deg != null);
  return (
    <Card id={id} aria-label="Camera settings" className={className}>
      <CameraControls controls={state.controls} />
      {circles && (
        <>
          <Separator />
          <FieldCircleSwitches optics={optics} />
        </>
      )}
      <Separator />
      <SolveStats state={state} />
    </Card>
  );
}

/** Per-device switches for the eyepiece and finder circles on the frame. */
function FieldCircleSwitches({ optics }: { optics: Optics }) {
  const [eyepiece, setEyepiece] = useFieldCircle("eyepiece");
  const [finder, setFinder] = useFieldCircle("finder");
  const rings = optics.finder_rings_deg;
  return (
    <div className="-my-2 flex flex-col">
      {optics.true_field_deg != null && (
        <SettingRow
          label="Eyepiece field"
          description={`The eyepiece's ${formatField(optics.true_field_deg)} view, around the scope's aim.`}
        >
          <Switch checked={eyepiece} onCheckedChange={setEyepiece} />
        </SettingRow>
      )}
      {rings != null && rings.length > 0 && (
        <SettingRow
          label="Finder field"
          description={
            rings.length === 1
              ? `The finder's ${plainNumber(rings[0])}° view.`
              : `The finder's rings: ${ringsText(rings)}.`
          }
        >
          <Switch checked={finder} onCheckedChange={setFinder} />
        </SettingRow>
      )}
    </div>
  );
}
