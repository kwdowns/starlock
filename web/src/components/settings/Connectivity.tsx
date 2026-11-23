import { useState } from "react";
import { QrCode } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { Button, Field, Input, SegmentedControl, StatusDot } from "@/components/ui";
import { api } from "@/lib/api";
import type { ActivityLine, EnginePayload } from "@/lib/types";
import { wifiSummary } from "@/components/app/WifiWarning";

// --red-300 on --red-950. qrcode.react writes these into SVG attributes,
// where CSS variables don't resolve, so they are spelled out.
const QR_FG = "#ff0000";
const QR_BG = "#0a0000";

const EPOCHS = [
  { value: "jnow", label: "JNow" },
  { value: "j2000", label: "J2000" },
] as const;

function ClientRow({ name, line }: { name: string; line: ActivityLine }) {
  return (
    <div className="flex min-h-touch-sm items-center justify-between gap-3">
      <StatusDot active={line.active} label={name} />
      <span className="readout truncate text-label text-muted-foreground">
        {line.address ?? "Not connected"}
      </span>
    </div>
  );
}

/** Where Starlock asks Stellarium for the name of a target sent from it. */
function StellariumAddress({ saved }: { saved: string }) {
  const [error, setError] = useState<string | null>(null);

  function save(value: string) {
    const next = value.trim();
    if (next === saved) {
      setError(null);
      return;
    }
    api
      .setSettings({ stellarium_rc_host: next })
      .then(() => setError(null))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not save."));
  }

  return (
    <Field
      label="Stellarium computer address"
      hint="Leave empty to use the computer that's connected. Used to get the name of targets you send from Stellarium."
      error={error ?? undefined}
    >
      <Input
        type="text"
        inputMode="url"
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        maxLength={253}
        placeholder="192.168.1.20"
        defaultValue={saved}
        key={saved}
        onBlur={(e) => save(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
      />
    </Field>
  );
}

export function Connectivity({ state }: { state: EnginePayload }) {
  const [showQR, setShowQR] = useState(false);
  const url = state.webserver.url;

  return (
    <section className="flex flex-col gap-3" aria-label="Connectivity">
      <div className="flex flex-col gap-1">
        <span className="text-label text-foreground">Open on your phone</span>
        {url ? (
          <code className="readout text-body break-all">{url}</code>
        ) : (
          <span className="text-label text-muted-foreground">No network address found.</span>
        )}
      </div>
      {url && (
        <>
          <Button
            variant="secondary"
            className="self-start"
            aria-expanded={showQR}
            onClick={() => setShowQR((v) => !v)}
          >
            <QrCode aria-hidden />
            {showQR ? "Hide QR code" : "Show QR code"}
          </Button>
          {showQR && (
            <div className="self-start rounded-lg border border-border p-3" style={{ background: QR_BG }}>
              <QRCodeSVG value={url} size={176} bgColor={QR_BG} fgColor={QR_FG} />
            </div>
          )}
        </>
      )}

      {state.wifi && (
        <div className="flex flex-col gap-1">
          <span className="text-label text-foreground">Starlock's Wi-Fi signal</span>
          <span className="readout text-body">{wifiSummary(state.wifi)}</span>
          <span className="text-label text-muted-foreground">
            Better than -70 dBm is comfortable; below -75 dBm the live view starts to suffer.
          </span>
        </div>
      )}

      <div className="flex flex-col">
        <ClientRow name="Stellarium (desktop)" line={state.stellarium} />
        <ClientRow name="LX200 (SkySafari, Stellarium Mobile)" line={state.lx200} />
      </div>

      <StellariumAddress saved={state.stellarium.remote_control_host ?? ""} />

      <div className="flex flex-col gap-2">
        <span className="text-label text-foreground">LX200 coordinate epoch</span>
        <SegmentedControl
          aria-label="LX200 coordinate epoch"
          value={state.lx200.epoch ?? "jnow"}
          options={EPOCHS}
          onValueChange={(e) => api.setSettings({ lx200_epoch: e }).catch(console.error)}
        />
        <p className="text-label text-muted-foreground">
          JNow for SkySafari (standard). Switch to J2000 if Stellarium Mobile
          PLUS centers slightly off target.
        </p>
      </div>
    </section>
  );
}
