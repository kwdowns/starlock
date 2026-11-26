import { useState } from "react";
import { Crosshair, RotateCcw, X } from "lucide-react";
import {
  Alert,
  Button,
  Card,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  Readout,
  ReadoutGrid,
  Separator,
} from "@/components/ui";
import { targetMagnitude } from "@/components/catalog/targetMagnitude";
import { useNearestObject } from "@/hooks/useNearestObject";
import { api } from "@/lib/api";
import { moonGlare, moonGlareText } from "@/lib/moonGlare";
import { CENTERED_DEG } from "@/lib/nearest";
import { useSolarSystem } from "@/lib/solarSystem";
import { formatDec, formatDistance, formatMountMove, formatRa, mountDeltas } from "@/lib/screen";
import type { EnginePayload } from "@/lib/types";

type Props = { state: EnginePayload };

function TargetReadout({ state }: Props) {
  const nav = state.nav!;
  const p = state.pointing;
  const now = new Date();
  const bodies = useSolarSystem(now);
  const loc = state.location.latitude !== null && state.location.longitude !== null
    ? { latitude: state.location.latitude, longitude: state.location.longitude }
    : null;
  const isMoon = bodies.some((b) => b.kind === "moon" && b.name === nav.target_name);
  const glare = moonGlare(
    { ra_deg: nav.target_ra_deg, dec_deg: nav.target_dec_deg, isMoon }, bodies, loc, now,
  );
  const mag = targetMagnitude(nav);
  const deltas =
    p.valid && nav.in_fov && nav.pixel_x !== null && nav.pixel_y !== null
      ? mountDeltas(state, nav.pixel_x, nav.pixel_y)
      : null;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start gap-3">
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-caption text-muted-foreground uppercase">Target</span>
          <span className="truncate text-heading">{nav.target_name ?? "Custom position"}</span>
          {mag !== null && (
            <span className="text-label text-muted-foreground">
              Magnitude <span className="readout">{mag.toFixed(1)}</span>
            </span>
          )}
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => api.clearGoto().catch(console.error)}
        >
          <X aria-hidden />
          Clear
        </Button>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="readout text-display" aria-label="Distance to target">
          {formatDistance(nav.separation_deg)}
        </span>
        {!p.valid ? (
          <span className="text-body text-muted-foreground">Waiting for a solve…</span>
        ) : nav.mount ? (
          <span className="readout text-body">{formatMountMove(state.mount.mode, nav.mount)}</span>
        ) : deltas ? (
          <span className="readout text-body">
            {deltas.right >= 0 ? "Right" : "Left"} {Math.abs(deltas.right).toFixed(2)}° ·{" "}
            {deltas.up >= 0 ? "Up" : "Down"} {Math.abs(deltas.up).toFixed(2)}°
          </span>
        ) : (
          nav.direction_text && <span className="text-body">{nav.direction_text}</span>
        )}
      </div>
      {p.valid && nav.mount?.near_pole && (
        <p className="text-label">
          {state.mount.mode === "eq"
            ? "Near the pole a small move can need a big turn in RA. Set RA first, then Dec."
            : "Near the zenith a small move can need a big turn of the base. Lower the tube, turn the base, then raise it."}
        </p>
      )}
      {state.mount.needs_location && (
        <p className="text-label text-muted-foreground">
          Set your site in Equipment to get turn and raise directions.
        </p>
      )}
      {glare && <p className="text-label">{moonGlareText(glare, nav.target_name ?? "The target")}</p>}
      <p className="text-label text-muted-foreground">1° is about two full moons wide.</p>
    </div>
  );
}

/** Offered when the target is close: a bumped finder shows as a small, steady offset. */
const RECENTER_SHOW_DEG = 3;

/** "Recenter on target", while there is a target close to the scope. */
export function RecenterTarget({ state }: Props) {
  const nav = state.nav;
  if (!nav?.active || !state.pointing.valid) return null;
  if (nav.separation_deg === null || nav.separation_deg > RECENTER_SHOW_DEG) return null;
  return <RecenterButton name={nav.target_name ?? "the target"} />;
}

/**
 * "It's centred in my eyepiece": re-aims the alignment on the target, for
 * when the finder or shoe got bumped. Confirmed first; the engine refuses
 * anything bigger than a bump.
 */
function RecenterButton({ name }: { name: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const { shift_deg } = await api.recenter();
      setDone(`Recentered: the alignment moved ${shift_deg.toFixed(2)}°.`);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (o) setError(null); }}>
      <div className="flex flex-col gap-1">
        <Button variant="secondary" size="sm" className="self-start" onClick={() => { setDone(null); setOpen(true); }}>
          <Crosshair aria-hidden />
          Recenter on target
        </Button>
        {done && <p className="text-label text-muted-foreground">{done}</p>}
      </div>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Is {name} centred in the eyepiece?</DialogTitle>
          <DialogDescription>
            Starlock will take where the scope points now as exactly on {name}, and
            correct its alignment for the rest of the session. Use it when the finder
            or shoe got bumped.
          </DialogDescription>
        </DialogHeader>
        {error && <Alert variant="error" title="Couldn't recenter">{error}</Alert>}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="secondary">Cancel</Button>
          </DialogClose>
          <Button loading={busy} onClick={() => void confirm()}>It's centred</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Names what the scope is on, or the closest named object to it. */
function NearestObject({ state }: Props) {
  const p = state.pointing;
  const nearest = useNearestObject(p.valid ? p.ra_deg : null, p.valid ? p.dec_deg : null);
  if (!nearest) return null;
  const centered = nearest.sep_deg <= CENTERED_DEG;
  return (
    <div className="flex min-w-0 flex-col">
      <span className="text-caption text-muted-foreground uppercase">
        {centered ? "Centered on" : "Nearest object"}
      </span>
      <span className="text-heading">{nearest.place.name}</span>
      <span className="text-label text-muted-foreground">
        {nearest.place.kind}
        {!centered && (
          <>
            {" · "}
            <span className="readout">{formatDistance(nearest.sep_deg)}</span> away
          </>
        )}
      </span>
    </div>
  );
}

const DASH = "—";

function PointingReadouts({ state }: Props) {
  const p = state.pointing;
  return (
    <ReadoutGrid cols={2} className="lg:grid-cols-3">
      <Readout label="RA" value={p.valid ? formatRa(p.ra_deg) : DASH} />
      <Readout label="Dec" value={p.valid ? formatDec(p.dec_deg) : DASH} />
      <Readout label="Roll" value={p.valid ? `${p.roll_deg.toFixed(1)}°` : DASH} />
    </ReadoutGrid>
  );
}

/** Plate-solve quality, for tuning exposure and gain. */
export function SolveStats({ state }: Props) {
  const p = state.pointing;
  return (
    <ReadoutGrid cols={3}>
      <Readout label="Matches" value={p.valid ? p.matches : DASH} />
      <Readout label="Prob" value={p.valid ? p.prob.toExponential(1) : DASH} />
      <Readout
        label="Age"
        value={p.solve_age_s !== null ? `${p.solve_age_s.toFixed(1)} s` : DASH}
      />
    </ReadoutGrid>
  );
}

/** Tracking: where the target is, and where the scope points. */
export function TrackingPanel({ state }: Props) {
  const hasTarget = !!state.nav?.active;
  return (
    <Card aria-label="Tracking">
      {hasTarget ? (
        <TargetReadout state={state} />
      ) : (
        <EmptyState
          className="py-3"
          icon={<Crosshair />}
          title="No target"
          description={
            <>
              Pick one from <span className="md:hidden">the list below</span>
              <span className="hidden md:inline">the list</span>, or send one
              from SkySafari or Stellarium.
            </>
          }
        />
      )}
      <Separator />
      <NearestObject state={state} />
      <PointingReadouts state={state} />
    </Card>
  );
}

/** Stops tracking and starts the wizard over, after a confirmation. */
export function RestartSetupButton() {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button variant="ghost" className="self-start" onClick={() => setOpen(true)}>
        <RotateCcw aria-hidden />
        Restart setup
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Restart setup?</DialogTitle>
          <DialogDescription>
            Tracking stops and the wizard starts again from camera setup. You
            can reuse this calibration at the sync step.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="secondary">Keep tracking</Button>
          </DialogClose>
          <Button
            variant="danger"
            onClick={() => {
              setOpen(false);
              api.wizardAdvance().catch(console.error);
            }}
          >
            <RotateCcw aria-hidden />
            Restart setup
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
