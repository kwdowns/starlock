import { Orbit } from "lucide-react";
import { Alert, Card, CardTitle, Spinner, Steps } from "@/components/ui";
import { SkyDome } from "@/components/live-view/SkyDome";
import { RetryCameraButton } from "@/components/RetryCameraButton";
import { isSetupPhase, SETUP_STEPS, stepIndexFor } from "@/lib/screen";
import type { EnginePayload } from "@/lib/types";
import {
  CalibrateCard,
  SetupCard,
  SyncCard,
  SyncConfirmCard,
  WarmingUpCard,
} from "./SetupCards";
import { RecenterTarget, RestartSetupButton, TrackingPanel } from "./TrackingPanel";

type Props = { state: EnginePayload };

function InstructionCard({ state }: Props) {
  switch (state.state) {
    case "SETUP":        return <SetupCard state={state} />;
    case "SYNC":         return <SyncCard state={state} />;
    case "SYNC_CONFIRM": return <SyncConfirmCard state={state} />;
    case "CALIBRATE":    return <CalibrateCard />;
    case "WARMING_UP":   return <WarmingUpCard state={state} />;
    default:             return null;
  }
}

/** The dome, always shown while tracking. */
function SkyView({ state, spinKey }: Props & { spinKey?: number }) {
  const p = state.pointing;
  const nav = state.nav;
  return (
    <Card aria-label="Sky view">
      <CardTitle className="flex items-center gap-2 [&_svg]:size-5">
        <Orbit aria-hidden />
        Sky view
      </CardTitle>
      <SkyDome
        className="h-64 md:h-72"
        pointingRaDeg={p.valid ? p.ra_deg : null}
        pointingDecDeg={p.valid ? p.dec_deg : null}
        targetRaDeg={nav?.active ? nav.target_ra_deg : null}
        targetDecDeg={nav?.active ? nav.target_dec_deg : null}
        targetLabel={nav?.target_name ?? null}
        latDeg={state.location.latitude}
        lonDeg={state.location.longitude}
        spinKey={spinKey}
      />
    </Card>
  );
}

/**
 * Everything under the camera frame that depends on the engine state:
 * setup → progress and instructions; tracking → target readout and the sky
 * dome. Exposure / gain live with the frame (its pencil), not here.
 * `spinKey`: bump it to spin the dome once (a target was just picked).
 */
export function StepArea({ state, spinKey }: Props & { spinKey?: number }) {
  if (isSetupPhase(state.state)) {
    const step = stepIndexFor(state.state) ?? 0;
    return (
      <div className="flex flex-col gap-3" data-section="setup">
        <Steps steps={SETUP_STEPS} current={step} />
        <InstructionCard state={state} />
      </div>
    );
  }

  if (state.state === "TRACKING") {
    return (
      <div className="flex flex-col gap-3" data-section="tracking">
        <TrackingPanel state={state} />
        <SkyView state={state} spinKey={spinKey} />
        <RecenterTarget state={state} />
        <RestartSetupButton />
      </div>
    );
  }

  // RECONNECTING / ERROR: camera trouble.
  return (
    <div className="flex flex-col gap-3" data-section="camera-trouble">
      {state.state === "RECONNECTING" ? (
        <Alert variant="warning" title="Reconnecting to the camera…" action={<Spinner label="Reconnecting" />}>
          The camera dropped out. Trying again for a few seconds.
        </Alert>
      ) : (
        // ERROR only follows a failed camera recovery; a successful retry
        // brings the engine back to SETUP, so offer that instead of a restart.
        <Alert variant="error" title="Camera lost" action={<RetryCameraButton label="Retry" />}>
          Plug it back in, then retry.
        </Alert>
      )}
    </div>
  );
}
