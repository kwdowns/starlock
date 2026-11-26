import { useId, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import {
  Alert,
  Button,
  Card,
  CardHeader,
  CardTitle,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui";
import {
  eyepieceSummary,
  finderSummary,
  opticsLine,
  siteCoords,
  telescopeSummary,
} from "@/lib/equipment";
import type { ObservingBlock } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { Selection, Slot } from "./useSelection";

interface Option {
  id: string;
  name: string;
  detail: string;
}

interface PickerProps {
  label: string;
  value: string | null;
  options: Option[];
  emptyHint: string;
  onChange: (id: string | null) => void;
}

/** One "In use" row: the label, and a button that opens the saved items plus "None". */
function Picker({ label, value, options, emptyHint, onChange }: PickerProps) {
  const [open, setOpen] = useState(false);
  const labelId = useId();
  const selected = options.find((o) => o.id === value) ?? null;
  const choices: (Option | { id: null; name: string; detail?: undefined })[] = [
    { id: null, name: "None" },
    ...options,
  ];

  return (
    <div className="flex items-center gap-3">
      <span id={labelId} className="w-24 shrink-0 text-label text-muted-foreground">
        {label}
      </span>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="secondary"
            className="min-w-0 flex-1 justify-between px-3"
            aria-label={`${label}: ${selected?.name ?? "None"}`}
          >
            <span className={cn("truncate", !selected && "text-muted-foreground")}>
              {selected?.name ?? "None"}
            </span>
            <ChevronsUpDown aria-hidden />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          className="max-h-(--radix-popover-content-available-height) w-(--radix-popover-trigger-width) min-w-60 gap-0 overflow-y-auto overscroll-contain p-1 starlock-scrollbar"
        >
          <div role="radiogroup" aria-labelledby={labelId} className="flex flex-col">
            {choices.map((o) => {
              const checked = o.id === (selected?.id ?? null);
              return (
                <button
                  key={o.id ?? "none"}
                  type="button"
                  role="radio"
                  aria-checked={checked}
                  className={cn(
                    "flex min-h-touch-sm items-center gap-2 rounded-md px-2 py-1.5 text-left active:bg-accent",
                    checked && "bg-accent font-semibold",
                  )}
                  onClick={() => {
                    setOpen(false);
                    if (!checked) onChange(o.id);
                  }}
                >
                  <Check className={cn("size-5 shrink-0", !checked && "invisible")} aria-hidden />
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate text-body text-foreground">{o.name}</span>
                    {o.detail && (
                      <span className="truncate text-label text-muted-foreground">{o.detail}</span>
                    )}
                  </span>
                </button>
              );
            })}
          </div>
          {options.length === 0 && (
            <p className="px-2 py-2 text-label text-muted-foreground">{emptyHint}</p>
          )}
        </PopoverContent>
      </Popover>
    </div>
  );
}

/** Site, telescope, eyepiece and finder in use, and what they make. */
export function InUseCard({ observing, selection }: { observing: ObservingBlock; selection: Selection }) {
  const { current, select, error } = selection;
  const rows: { slot: Slot; label: string; options: Option[]; emptyHint: string }[] = [
    {
      slot: "site_id",
      label: "Site",
      options: observing.sites.map((s) => ({ id: s.id, name: s.name, detail: siteCoords(s) })),
      emptyHint: "No saved sites yet. Save one below.",
    },
    {
      slot: "telescope_id",
      label: "Telescope",
      options: observing.telescopes.map((t) => ({ id: t.id, name: t.name, detail: telescopeSummary(t) })),
      emptyHint: "No telescopes yet. Add one below.",
    },
    {
      slot: "eyepiece_id",
      label: "Eyepiece",
      options: observing.eyepieces.map((e) => ({ id: e.id, name: e.name, detail: eyepieceSummary(e) })),
      emptyHint: "No eyepieces yet. Add one below.",
    },
    {
      slot: "finder_id",
      label: "Finder",
      options: observing.finders.map((f) => ({ id: f.id, name: f.name, detail: finderSummary(f) })),
      emptyHint: "No finders yet. Add one below.",
    },
  ];
  const line = opticsLine(observing.optics);

  return (
    <Card aria-label="In use">
      <CardHeader>
        <CardTitle>In use</CardTitle>
      </CardHeader>
      <div className="flex flex-col gap-2">
        {rows.map((r) => (
          <Picker
            key={r.slot}
            label={r.label}
            value={current[r.slot]}
            options={r.options}
            emptyHint={r.emptyHint}
            onChange={(id) => select(r.slot, id)}
          />
        ))}
      </div>
      {line ? (
        <p className="readout text-label text-foreground">{line}</p>
      ) : (
        <p className="text-label text-muted-foreground">
          Pick a telescope and an eyepiece to see the magnification and field.
        </p>
      )}
      {error && <Alert variant="error" title={error} />}
    </Card>
  );
}
