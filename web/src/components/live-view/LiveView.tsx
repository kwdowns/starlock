import type { CSSProperties } from "react";
import { CameraOff, OctagonAlert, Pencil } from "lucide-react";
import { Button } from "@/components/ui";
import type { EnginePayload } from "@/lib/types";
import { useLatestFrame } from "@/hooks/useLatestFrame";
import { useFieldCircle } from "@/hooks/useFieldCircles";
import { hasNoStars } from "@/lib/screen";
import { cn } from "@/lib/utils";
import { StarOverlay } from "./StarOverlay";
import { NavOverlay } from "./NavOverlay";
import { SyncCandidatesOverlay } from "./SyncCandidatesOverlay";
import { AxesOverlay } from "./AxesOverlay";
import { FieldCircles } from "./FieldCircles";

interface Props {
  state: EnginePayload;
  showStars: boolean;
  className?: string;
  /** Camera settings under the frame: shown, and its toggle (the pencil). */
  editOpen?: boolean;
  onToggleEdit?: () => void;
  /** id of the camera settings section, for aria-controls. */
  editId?: string;
}

/**
 * Camera frame (natural colour) + overlays. The box is sized to the frame's aspect ratio and
 * capped in height (`--frame-max-h`, default 40svh) by narrowing it, so the
 * image always fills it exactly: no letterbox strips.
 */
export function LiveView({ state, showStars, className, editOpen = false, onToggleEdit, editId }: Props) {
  const { image_w, image_h } = state;
  const noStars = hasNoStars(state);
  const frameUrl = useLatestFrame(state.camera?.frame_id);
  const [eyepieceCircle] = useFieldCircle("eyepiece");
  const [finderCircle] = useFieldCircle("finder");
  const style = {
    aspectRatio: `${image_w} / ${image_h}`,
    "--frame-ar": String(image_w / image_h),
  } as CSSProperties;

  return (
    <div
      data-slot="live-view"
      className={cn(
        "relative mx-auto w-[min(100%,calc(var(--frame-max-h,40svh)*var(--frame-ar)))] overflow-hidden rounded-xl border border-border bg-card",
        className,
      )}
      style={style}
    >
      {frameUrl ? (
        // The camera's own image (greyscale for the mono cameras), shown as is.
        <img
          src={frameUrl}
          alt="Live camera frame"
          className="absolute inset-0 h-full w-full object-cover"
        />
      ) : (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-muted-foreground">
          <CameraOff className="size-8" aria-hidden />
          <span className="text-label">
            {state.camera.connected ? "Waiting for a frame…" : "No camera"}
          </span>
        </div>
      )}
      <svg
        // Dark halo so the red overlays stay readable over a grey frame.
        className="absolute inset-0 h-full w-full drop-shadow-[0_0_2px_rgb(0_0_0/0.9)]"
        viewBox={`0 0 ${image_w} ${image_h}`}
        preserveAspectRatio="xMidYMid slice"
      >
        {showStars && <StarOverlay state={state} />}
        <FieldCircles state={state} eyepiece={eyepieceCircle} finder={finderCircle} />
        {!noStars && <AxesOverlay state={state} />}
        {!noStars && <NavOverlay state={state} />}
        {state.state === "SYNC_CONFIRM" && <SyncCandidatesOverlay state={state} />}
      </svg>
      {onToggleEdit && (
        <Button
          variant={editOpen ? "primary" : "secondary"}
          size="icon-sm"
          className={cn("absolute top-2 left-2", !editOpen && "bg-card/80")}
          aria-label="Camera settings"
          aria-expanded={editOpen}
          aria-controls={editId}
          onClick={onToggleEdit}
        >
          <Pencil />
        </Button>
      )}
      {noStars && (
        <div
          role="alert"
          className="absolute top-3 left-1/2 flex max-w-[calc(100%-7rem)] -translate-x-1/2 items-center gap-2 rounded-lg border-[1.5px] border-primary bg-card px-3 py-2 text-label font-semibold"
        >
          <OctagonAlert className="size-5 shrink-0" aria-hidden />
          No stars. Point at darker sky, or check for clouds.
        </div>
      )}
    </div>
  );
}
