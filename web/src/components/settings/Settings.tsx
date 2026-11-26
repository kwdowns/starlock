import { RotateCcw } from "lucide-react";
import { Button, Field, Input, SegmentedControl, Separator, SettingRow, Switch } from "@/components/ui";
import { api } from "@/lib/api";
import { mountModelLines } from "@/lib/mountModel";
import type { EnginePayload, MountMode, MountModel } from "@/lib/types";
import { useOnTargetSound } from "@/hooks/useOnTargetFeedback";

export const DEFAULT_SHOW_STARS = false;
const DEFAULT_AUDIO_ENABLED = true;
const DEFAULT_MIN_MATCHES = 8;
const DEFAULT_MAX_PROB = 0.2;

const MOUNT_MODES = [
  { value: "altaz", label: "Alt-az" },
  { value: "eq", label: "Equatorial" },
] as const satisfies readonly { value: MountMode; label: string }[];

interface Props {
  state: EnginePayload;
  showStars: boolean;
  setShowStars: (v: boolean) => void;
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="text-heading">{children}</h2>;
}

export function Settings({ state, showStars, setShowStars }: Props) {
  function resetToDefaults() {
    setShowStars(DEFAULT_SHOW_STARS);
    api.setSettings({ audio_enabled: DEFAULT_AUDIO_ENABLED }).catch(console.error);
    api
      .setAdvanced({ min_matches: DEFAULT_MIN_MATCHES, max_prob: DEFAULT_MAX_PROB })
      .catch(console.error);
  }

  return (
    <section className="flex flex-col" aria-label="Settings">
      <SectionTitle>Mount</SectionTitle>
      <div className="mt-3 flex flex-col gap-2">
        <SegmentedControl
          aria-label="Mount type"
          value={state.mount.mode}
          options={MOUNT_MODES}
          fullWidth
          onValueChange={(m) => api.setSettings({ mount_mode: m }).catch(console.error)}
        />
        <p className="text-label text-muted-foreground">
          {state.mount.mode === "eq"
            ? "Directions are given as RA east/west and Dec north/south."
            : `Directions are given as turning the base and raising or lowering the tube. Needs your location (${
                state.observing ? "Equipment, Site" : "below"
              }).`}
        </p>
        {state.mount.model && <MountModelBlock model={state.mount.model} mode={state.mount.mode} />}
      </div>

      <Separator className="my-4" />
      <SectionTitle>Display and sound</SectionTitle>
      <SettingRow label="Show detected stars" description="Circle every star the solver found.">
        <Switch checked={showStars} onCheckedChange={setShowStars} />
      </SettingRow>
      <OnTargetSoundRow />
      <SettingRow
        label="Sounds on the Starlock"
        description="Lock, loss and new-target sounds played by the Starlock itself. A Pi needs a speaker for these."
      >
        <Switch
          checked={state.audio_enabled}
          onCheckedChange={(v) => api.setSettings({ audio_enabled: v }).catch(console.error)}
        />
      </SettingRow>
      {state.power?.available && (
        <SettingRow
          label="Power saving"
          description={`Caps the CPU at ${state.power.max_freq_mhz} MHz. Solves take a little longer but stay well under an exposure.`}
        >
          <Switch
            checked={state.power.cpu_cap}
            onCheckedChange={(v) => api.setSettings({ cpu_cap: v }).catch(console.error)}
          />
        </SettingRow>
      )}

      <Separator className="my-4" />
      <SectionTitle>Solver</SectionTitle>
      <div className="mt-3 grid grid-cols-2 gap-3">
        <Field label="Min matches" hint="Stars matched before a solve counts. Higher is stricter.">
          <Input
            type="number"
            inputMode="numeric"
            min={3}
            max={50}
            step={1}
            defaultValue={state.min_matches}
            key={`min-${state.min_matches}`}
            onBlur={(e) =>
              api.setAdvanced({ min_matches: Number(e.currentTarget.value) }).catch(console.error)
            }
          />
        </Field>
        <Field label="Max probability" hint="False-match probability allowed. Lower is stricter.">
          <Input
            type="number"
            inputMode="decimal"
            min={0}
            max={1}
            step={0.01}
            defaultValue={state.max_prob}
            key={`max-${state.max_prob}`}
            onBlur={(e) =>
              api.setAdvanced({ max_prob: Number(e.currentTarget.value) }).catch(console.error)
            }
          />
        </Field>
      </div>
      <Button variant="secondary" className="mt-4" onClick={resetToDefaults}>
        <RotateCcw aria-hidden />
        Reset to defaults
      </Button>
    </section>
  );
}


/**
 * What the engine has learnt about how the mount sits (base tilt or polar
 * alignment) from solves at different heights and directions.
 */
function MountModelBlock({ model, mode }: { model: MountModel; mode: MountMode }) {
  const [first, ...rest] = mountModelLines(model, mode);
  return (
    <div className="mt-2 flex flex-col gap-1">
      <h3 className="text-label font-semibold text-foreground">Mount model (experimental)</h3>
      <p className="text-label text-foreground">{first}</p>
      {rest.map((line) => (
        <p key={line} className="text-label text-muted-foreground">
          {line}
        </p>
      ))}
      {model.samples > 0 && (
        <Button
          variant="ghost"
          size="sm"
          className="-ml-3 self-start"
          aria-label="Reset mount model"
          onClick={() => api.resetMountModel().catch(console.error)}
        >
          <RotateCcw aria-hidden />
          Reset
        </Button>
      )}
    </div>
  );
}

/** This browser's on-target chime (and vibration where the browser supports it). */
function OnTargetSoundRow() {
  const [on, setOn] = useOnTargetSound();
  return (
    <SettingRow
      label="On-target sound"
      description="A chime on this device when the scope arrives on target (and a buzz on Android)."
    >
      <Switch checked={on} onCheckedChange={setOn} />
    </SettingRow>
  );
}
