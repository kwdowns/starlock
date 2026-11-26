import { useState } from "react";
import { MapPinPlus, Pencil, Plus } from "lucide-react";
import { Button } from "@/components/ui";
import { LocationPanel } from "@/components/catalog/LocationPanel";
import { HorizonEditor } from "@/components/settings/HorizonEditor";
import { siteCoords } from "@/lib/equipment";
import { horizonFrom } from "@/lib/horizon";
import type { EnginePayload, ObservingBlock, ObservingSite } from "@/lib/types";
import { ItemList } from "./GearSection";
import { AddSiteDialog, RenameSiteDialog, SaveAsSiteDialog } from "./SiteDialogs";
import type { Selection } from "./useSelection";

type Open =
  | { kind: "rename"; site: ObservingSite; fromList: boolean }
  | { kind: "add" }
  | { kind: "save-as" }
  | null;

/**
 * The site in use (name, Location panel, Horizon editor, which edit it
 * through the same /api/settings calls as before), or the ad-hoc location
 * and horizon with "Save as a site"; then the saved sites.
 */
export function SiteSection({
  state,
  observing,
  selection,
}: {
  state: EnginePayload;
  observing: ObservingBlock;
  selection: Selection;
}) {
  const [open, setOpen] = useState<Open>(null);
  const close = () => setOpen(null);
  const site = observing.sites.find((s) => s.id === selection.current.site_id) ?? null;
  const lat = state.location?.latitude ?? null;
  const lon = state.location?.longitude ?? null;

  return (
    <section className="flex flex-col gap-3" aria-label={site ? "Site" : "Location"}>
      {site ? (
        <>
          <h2 className="text-heading">Site</h2>
          <Button
            variant="secondary"
            className="justify-between px-3"
            aria-label={`Rename ${site.name}`}
            onClick={() => setOpen({ kind: "rename", site, fromList: false })}
          >
            <span className="truncate text-heading">{site.name}</span>
            <Pencil aria-hidden />
          </Button>
          {/* Brings its own "Location" heading. */}
          <LocationPanel state={state} />
          <HorizonEditor state={state} />
        </>
      ) : (
        <>
          {/* No site in use: the Location panel's heading heads the section. */}
          <LocationPanel state={state} />
          <HorizonEditor state={state} />
          <Button
            variant="secondary"
            className="self-start"
            disabled={lat === null || lon === null}
            onClick={() => setOpen({ kind: "save-as" })}
          >
            <MapPinPlus aria-hidden />
            Save as a site
          </Button>
          {(lat === null || lon === null) && (
            <p className="text-label text-muted-foreground">Set a location first to save it as a site.</p>
          )}
        </>
      )}

      <h3 className="mt-2 text-label font-semibold text-foreground">Saved sites</h3>
      {observing.sites.length === 0 ? (
        <p className="text-label text-muted-foreground">No saved sites yet.</p>
      ) : (
        <ItemList
          items={observing.sites}
          summary={siteCoords}
          inUseId={selection.current.site_id}
          onSelect={(id) => selection.select("site_id", id)}
          onEdit={(s) => setOpen({ kind: "rename", site: s, fromList: true })}
        />
      )}
      <Button variant="secondary" className="self-start" onClick={() => setOpen({ kind: "add" })}>
        <Plus aria-hidden />
        Add site
      </Button>

      {open?.kind === "rename" && (
        <RenameSiteDialog site={open.site} canDelete={open.fromList} onClose={close} />
      )}
      {open?.kind === "add" && <AddSiteDialog onClose={close} />}
      {open?.kind === "save-as" && lat !== null && lon !== null && (
        <SaveAsSiteDialog
          latitude={lat}
          longitude={lon}
          horizon={horizonFrom(state.horizon?.obscured)}
          onClose={close}
        />
      )}
    </section>
  );
}
