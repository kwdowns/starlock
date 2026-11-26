import { useState } from "react";
import { SegmentedControl } from "@/components/ui";
import { api } from "@/lib/api";
import {
  DEFAULT_AFOV_DEG,
  DEFAULT_RINGS,
  LIMITS,
  numText,
  parseInRange,
  parseName,
  parseRings,
  plainNumber,
} from "@/lib/equipment";
import type { Eyepiece, Finder, FinderKind, Telescope } from "@/lib/types";
import { FormField } from "./fields";
import { ItemDialog } from "./ItemDialog";

interface DialogProps<T> {
  /** null: add a new one. */
  item: T | null;
  onClose: () => void;
  /** Called with the new item's id after an add (to put it in use when none of its kind is). */
  onAdded?: (id: string) => void;
}

function removeAction(kind: "telescopes" | "eyepieces" | "finders", item: { id: string; name: string } | null) {
  return item ? { name: item.name, onDelete: () => api.observing.remove(kind, item.id) } : undefined;
}

export function TelescopeDialog({ item, onClose, onAdded }: DialogProps<Telescope>) {
  const [name, setName] = useState(item?.name ?? "");
  const [aperture, setAperture] = useState(numText(item?.aperture_mm));
  const [focal, setFocal] = useState(numText(item?.focal_length_mm));
  const n = parseName(name);
  const a = parseInRange(aperture, LIMITS.aperture_mm.min, LIMITS.aperture_mm.max);
  const f = parseInRange(focal, LIMITS.focal_length_mm.min, LIMITS.focal_length_mm.max);

  return (
    <ItemDialog
      title={item ? "Edit telescope" : "Add telescope"}
      submitLabel={item ? "Save" : "Add"}
      canSubmit={n.ok && a.ok && f.ok}
      onClose={onClose}
      remove={removeAction("telescopes", item)}
      onSubmit={async () => {
        if (!n.ok || !a.ok || !f.ok) return;
        const body = { name: n.value, aperture_mm: a.value, focal_length_mm: f.value };
        if (item) await api.observing.update("telescopes", item.id, body);
        else onAdded?.((await api.observing.create("telescopes", body)).id);
      }}
    >
      <FormField label="Name" value={name} onChange={setName} parsed={n} placeholder='8" Dob' autoFocus={!item} />
      <div className="grid grid-cols-2 gap-3">
        <FormField label="Aperture (mm)" value={aperture} onChange={setAperture} parsed={a} placeholder="203" numeric />
        <FormField label="Focal length (mm)" value={focal} onChange={setFocal} parsed={f} placeholder="1200" numeric />
      </div>
    </ItemDialog>
  );
}

export function EyepieceDialog({ item, onClose, onAdded }: DialogProps<Eyepiece>) {
  const [name, setName] = useState(item?.name ?? "");
  const [focal, setFocal] = useState(numText(item?.focal_length_mm));
  const [afov, setAfov] = useState(numText(item?.afov_deg ?? DEFAULT_AFOV_DEG));
  const n = parseName(name);
  const f = parseInRange(focal, LIMITS.eyepiece_focal_length_mm.min, LIMITS.eyepiece_focal_length_mm.max);
  const a = parseInRange(afov, LIMITS.afov_deg.min, LIMITS.afov_deg.max);

  return (
    <ItemDialog
      title={item ? "Edit eyepiece" : "Add eyepiece"}
      submitLabel={item ? "Save" : "Add"}
      canSubmit={n.ok && f.ok && a.ok}
      onClose={onClose}
      remove={removeAction("eyepieces", item)}
      onSubmit={async () => {
        if (!n.ok || !f.ok || !a.ok) return;
        const body = { name: n.value, focal_length_mm: f.value, afov_deg: a.value };
        if (item) await api.observing.update("eyepieces", item.id, body);
        else onAdded?.((await api.observing.create("eyepieces", body)).id);
      }}
    >
      <FormField label="Name" value={name} onChange={setName} parsed={n} placeholder="25 mm Plössl" autoFocus={!item} />
      <div className="grid grid-cols-2 gap-3">
        <FormField label="Focal length (mm)" value={focal} onChange={setFocal} parsed={f} placeholder="25" numeric />
        <FormField
          label="Apparent field (°)"
          value={afov}
          onChange={setAfov}
          parsed={a}
          placeholder={String(DEFAULT_AFOV_DEG)}
          numeric
        />
      </div>
    </ItemDialog>
  );
}

const FINDER_KINDS = [
  { value: "optical", label: "Optical" },
  { value: "reflex", label: "Reflex" },
] as const satisfies readonly { value: FinderKind; label: string }[];

export function FinderDialog({ item, onClose, onAdded }: DialogProps<Finder>) {
  const [name, setName] = useState(item?.name ?? "");
  const [kind, setKind] = useState<FinderKind>(item?.kind ?? "optical");
  const [field, setField] = useState(numText(item?.field_deg));
  const [rings, setRings] = useState(
    item?.rings_deg?.length ? item.rings_deg.map(plainNumber).join(", ") : DEFAULT_RINGS,
  );
  const n = parseName(name);
  const fd = parseInRange(field, LIMITS.field_deg.min, LIMITS.field_deg.max);
  const rd = parseRings(rings);
  const ok = n.ok && (kind === "optical" ? fd.ok : rd.ok);

  return (
    <ItemDialog
      title={item ? "Edit finder" : "Add finder"}
      submitLabel={item ? "Save" : "Add"}
      canSubmit={ok}
      onClose={onClose}
      remove={removeAction("finders", item)}
      onSubmit={async () => {
        if (!n.ok) return;
        let body: Omit<Finder, "id">;
        if (kind === "optical") {
          if (!fd.ok) return;
          body = { name: n.value, kind, field_deg: fd.value };
        } else {
          if (!rd.ok) return;
          body = { name: n.value, kind, rings_deg: rd.value };
        }
        if (item) await api.observing.update("finders", item.id, body);
        else onAdded?.((await api.observing.create("finders", body)).id);
      }}
    >
      <FormField
        label="Name"
        value={name}
        onChange={setName}
        parsed={n}
        placeholder={kind === "optical" ? "8x50 RACI" : "Telrad"}
        autoFocus={!item}
      />
      <div className="flex flex-col gap-1.5">
        <span className="text-label text-foreground">Kind</span>
        <SegmentedControl
          aria-label="Kind"
          value={kind}
          options={FINDER_KINDS}
          fullWidth
          onValueChange={setKind}
        />
      </div>
      {kind === "optical" ? (
        <FormField
          label="True field (°)"
          value={field}
          onChange={setField}
          parsed={fd}
          placeholder="6"
          hint="Often printed on the finder, e.g. 6° for an 8x50."
          numeric
        />
      ) : (
        <FormField
          label="Rings (°)"
          value={rings}
          onChange={setRings}
          parsed={rd}
          placeholder={DEFAULT_RINGS}
          hint="Ring sizes, smallest first, with commas. A red dot is 0.1."
        />
      )}
    </ItemDialog>
  );
}
