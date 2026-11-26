import { useState } from "react";
import { LocateFixed } from "lucide-react";
import { Button } from "@/components/ui";
import { api, type ObservingItemBody } from "@/lib/api";
import { numText, parseInRange, parseName } from "@/lib/equipment";
import type { ObservingSite } from "@/lib/types";
import { FormField } from "./fields";
import { ItemDialog } from "./ItemDialog";

/** Create a site, then put it in use. */
async function createAndSelect(body: ObservingItemBody<"sites">) {
  const { id } = await api.observing.create("sites", body);
  // The site exists now; if selecting fails it is still in the list to tap.
  await api.observing.setCurrent({ site_id: id }).catch(console.error);
}

/** Rename a saved site; from the list it can also be deleted. */
export function RenameSiteDialog({
  site,
  canDelete,
  onClose,
}: {
  site: ObservingSite;
  canDelete: boolean;
  onClose: () => void;
}) {
  const [name, setName] = useState(site.name);
  const n = parseName(name);
  return (
    <ItemDialog
      title={canDelete ? "Edit site" : "Rename site"}
      submitLabel="Save"
      canSubmit={n.ok && n.value !== site.name}
      onClose={onClose}
      remove={
        canDelete
          ? {
              name: site.name,
              detail: "Its horizon is deleted too.",
              onDelete: () => api.observing.remove("sites", site.id),
            }
          : undefined
      }
      onSubmit={async () => {
        if (!n.ok) return;
        const { id, ...rest } = site;
        await api.observing.update("sites", id, { ...rest, name: n.value });
      }}
    >
      <FormField label="Name" value={name} onChange={setName} parsed={n} placeholder="Back yard" />
    </ItemDialog>
  );
}

/** Saves the location and horizon in use now as a named site, and selects it. */
export function SaveAsSiteDialog({
  latitude,
  longitude,
  horizon,
  onClose,
}: {
  latitude: number;
  longitude: number;
  horizon: readonly number[];
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const n = parseName(name);
  return (
    <ItemDialog
      title="Save as a site"
      description="Keeps this location and horizon under a name, to pick again next time."
      submitLabel="Save"
      canSubmit={n.ok}
      onClose={onClose}
      onSubmit={async () => {
        if (!n.ok) return;
        await createAndSelect({ name: n.value, latitude, longitude, horizon: [...horizon] });
      }}
    >
      <FormField label="Name" value={name} onChange={setName} parsed={n} placeholder="Back yard" autoFocus />
    </ItemDialog>
  );
}

/** Browsers only hand out the location on HTTPS or localhost, not to a Pi on plain HTTP. */
function canLocate(): boolean {
  return typeof window !== "undefined" && window.isSecureContext && "geolocation" in navigator;
}

/** A new site: name and coordinates (typed, or this device's); default horizon; then selected. */
export function AddSiteDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState<string | null>(null);
  const n = parseName(name);
  const la = parseInRange(lat, -90, 90);
  const lo = parseInRange(lon, -180, 180);

  function locate() {
    setLocating(true);
    setLocateError(null);
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setLat(numText(Math.round(p.coords.latitude * 10000) / 10000));
        setLon(numText(Math.round(p.coords.longitude * 10000) / 10000));
        setLocating(false);
      },
      () => {
        setLocateError("Couldn't get this device's location.");
        setLocating(false);
      },
      { enableHighAccuracy: false, timeout: 15000 },
    );
  }

  return (
    <ItemDialog
      title="Add site"
      description="Starts with the default horizon (below 20° hidden); edit it once the site is in use."
      submitLabel="Add"
      canSubmit={n.ok && la.ok && lo.ok}
      onClose={onClose}
      onSubmit={async () => {
        if (!n.ok || !la.ok || !lo.ok) return;
        await createAndSelect({ name: n.value, latitude: la.value, longitude: lo.value });
      }}
    >
      <FormField label="Name" value={name} onChange={setName} parsed={n} placeholder="Dark site" autoFocus />
      <div className="grid grid-cols-2 gap-3">
        <FormField label="Latitude" hint="+ north, - south" value={lat} onChange={setLat} parsed={la} placeholder="40.71" />
        <FormField label="Longitude" hint="+ east, - west" value={lon} onChange={setLon} parsed={lo} placeholder="-74.01" />
      </div>
      {canLocate() && (
        <Button type="button" variant="secondary" loading={locating} onClick={locate}>
          <LocateFixed aria-hidden />
          Use this device's location
        </Button>
      )}
      {locateError && <p className="text-label text-foreground">{locateError}</p>}
    </ItemDialog>
  );
}
