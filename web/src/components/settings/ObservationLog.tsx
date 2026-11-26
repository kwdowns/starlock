import { useCallback, useEffect, useState } from "react";
import { Download } from "lucide-react";
import {
  Alert,
  Button,
  EmptyState,
  Field,
  Input,
  List,
  ListRow,
  SegmentedControl,
  SettingRow,
  Switch,
} from "@/components/ui";
import { api, type ObservationEntry, type ObservationList } from "@/lib/api";
import { equipmentLine } from "@/lib/equipment";
import { formatDec, formatRa } from "@/lib/screen";

type Preset = "tonight" | "day" | "week" | "custom";

const PRESETS = [
  { value: "tonight", label: "Tonight" },
  { value: "day", label: "24 h" },
  { value: "week", label: "7 days" },
  { value: "custom", label: "Custom" },
] as const satisfies readonly { value: Preset; label: string }[];

const POLL_MS = 10_000;

/** `YYYY-MM-DDTHH:mm` in local time, the format a datetime-local input uses. */
function toLocalInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** Tonight = since the most recent local noon. */
function tonightStart(now: Date): Date {
  const d = new Date(now);
  d.setHours(12, 0, 0, 0);
  if (d > now) d.setDate(d.getDate() - 1);
  return d;
}

function presetRange(preset: Exclude<Preset, "custom">, now: Date): [Date, Date] {
  const hour = 3_600_000;
  const end = new Date(now.getTime() + 60_000);
  if (preset === "tonight") return [tonightStart(now), end];
  return [new Date(now.getTime() - (preset === "day" ? 24 : 168) * hour), end];
}

function formatDuration(s: number): string {
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} m`;
}

function whenLabel(e: ObservationEntry): string {
  const start = new Date(e.start_utc);
  const day = start.toLocaleDateString([], { month: "short", day: "numeric" });
  const time = start.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return `${day}, ${time}${e.open ? " (now)" : ""}`;
}

function frameUrl(e: ObservationEntry): string {
  return `/api/observations/${e.id}/frame.jpg`;
}

function Entry({ e }: { e: ObservationEntry }) {
  const [expanded, setExpanded] = useState(false);
  const where = `${formatRa(e.ra_j2000_deg)} ${formatDec(e.dec_j2000_deg)}`;
  const label = e.target_name ?? where;
  const when = e.target_name ? `${whenLabel(e)} · ${where}` : whenLabel(e);
  const gear = equipmentLine(e);
  return (
    <>
      <ListRow
        title={label}
        subtitle={
          gear ? (
            <>
              <span className="block truncate">{when}</span>
              <span className="block truncate">{gear}</span>
            </>
          ) : (
            when
          )
        }
        meta={formatDuration(e.duration_s)}
        leading={
          e.has_frame ? (
            <img
              src={frameUrl(e)}
              alt=""
              loading="lazy"
              className="h-10 w-16 rounded-sm object-cover"
            />
          ) : undefined
        }
        onPress={e.has_frame ? () => setExpanded((x) => !x) : undefined}
        aria-expanded={e.has_frame ? expanded : undefined}
      />
      {expanded && e.has_frame && (
        <li className="list-none px-3 pb-3">
          <img
            src={frameUrl(e)}
            alt={`Camera frame: ${label}`}
            className="w-full rounded-sm"
          />
        </li>
      )}
    </>
  );
}

/** The logbook: what the scope dwelt on, with a time-range picker and a CSV download. */
export function ObservationLog() {
  const [preset, setPreset] = useState<Preset>("tonight");
  const [customStart, setCustomStart] = useState(() => toLocalInput(tonightStart(new Date())));
  const [customEnd, setCustomEnd] = useState(() => toLocalInput(new Date(Date.now() + 3_600_000)));
  const [data, setData] = useState<ObservationList | null>(null);
  const [error, setError] = useState<string | null>(null);

  const rangeIso = useCallback((): [string, string] | null => {
    if (preset !== "custom") {
      const [s, e] = presetRange(preset, new Date());
      return [s.toISOString(), e.toISOString()];
    }
    const s = new Date(customStart);
    const e = new Date(customEnd);
    if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime()) || s > e) return null;
    return [s.toISOString(), e.toISOString()];
  }, [preset, customStart, customEnd]);

  const customInvalid = preset === "custom" && rangeIso() === null;

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      const range = rangeIso();
      if (!range) return;
      api
        .observations(range[0], range[1])
        .then((d) => {
          if (cancelled) return;
          setData(d);
          setError(null);
        })
        .catch((err) => {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        });
    };
    load();
    const id = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [rangeIso]);

  function download() {
    const range = rangeIso();
    if (range) window.location.assign(api.observationsCsvUrl(range[0], range[1]));
  }

  function setEnabled(v: boolean) {
    setData((d) => (d ? { ...d, enabled: v } : d));
    api.setSettings({ observation_log_enabled: v }).catch(console.error);
  }

  const entries = data?.entries ?? [];

  return (
    <section className="flex flex-col gap-3" aria-label="Logbook">
      <h2 className="text-heading">Logbook</h2>
      <SettingRow
        label="Record observations"
        description="Logs where the scope rests for about 30 seconds."
      >
        <Switch checked={data?.enabled ?? true} onCheckedChange={setEnabled} />
      </SettingRow>
      <SegmentedControl
        aria-label="Time range"
        value={preset}
        options={PRESETS}
        fullWidth
        onValueChange={setPreset}
      />
      {preset === "custom" && (
        <div className="grid grid-cols-1 gap-3">
          <Field label="From">
            <Input
              type="datetime-local"
              value={customStart}
              onChange={(e) => setCustomStart(e.target.value)}
            />
          </Field>
          <Field
            label="To"
            error={customInvalid ? "Pick a start before the end." : undefined}
          >
            <Input
              type="datetime-local"
              value={customEnd}
              onChange={(e) => setCustomEnd(e.target.value)}
            />
          </Field>
        </div>
      )}
      {error && <Alert variant="error">{error}</Alert>}
      {data?.clock === "client" && (
        <p className="text-label text-muted-foreground">
          The scope&apos;s clock was wrong, so times come from this device.
        </p>
      )}
      {entries.length === 0 ? (
        <EmptyState
          title="Nothing logged in this range"
          description="Rest the scope on something for half a minute and it appears here."
        />
      ) : (
        <List>
          {entries.map((e) => (
            <Entry key={e.id} e={e} />
          ))}
        </List>
      )}
      <Button
        variant="secondary"
        onClick={download}
        disabled={customInvalid || entries.length === 0}
      >
        <Download aria-hidden /> Download CSV
      </Button>
    </section>
  );
}
