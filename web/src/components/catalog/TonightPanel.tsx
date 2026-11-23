import { useMemo, useState } from "react";
import { Alert, Card, Disclosure, EmptyState, SegmentedControl } from "@/components/ui";
import objectsData from "@/data/objects.json";
import type { CatalogObject } from "@/lib/catalogTypes";
import { useSolarSystem } from "@/lib/solarSystem";
import { CatalogFilters } from "./CatalogFilters";
import { activeFilterCount, useCatalogFilters } from "./filterState";
import { DarknessBanner } from "./DarknessBanner";
import { altAzOf, solarItem, type Location, type TargetItem } from "./items";
import { readStored, writeStored } from "./storage";
import { TargetList, type TargetActions } from "./TargetList";
import { TimeControl } from "./TimeControl";
import { ALT_THRESHOLD_DEG, tonightRows, type SkyPoint, type SortKey } from "./tonight";

const objects = objectsData as CatalogObject[];
/** Planets are worth showing lower than the curated list's threshold. */
export const SOLAR_MIN_ALT_DEG = 5;
const SORT_KEY = "starlock.catalog.sort";

const SORT_OPTIONS = [
  { value: "type", label: "Type" },
  { value: "mag", label: "Bright" },
  { value: "alt", label: "Altitude" },
  { value: "near", label: "Nearest" },
] as const;

const SORT_LABELS: Record<SortKey, string> = {
  type: "by type",
  mag: "brightest first",
  alt: "highest first",
  near: "nearest to the scope",
};

function loadSort(): SortKey {
  const v = readStored(SORT_KEY);
  return SORT_OPTIONS.some((o) => o.value === v) ? (v as SortKey) : "type";
}

interface Props {
  location: Location | null;
  /** Wall-clock now in ms (ticks once a minute). */
  now: number;
  /** Where the scope points, or null without a solve. */
  scope: SkyPoint | null;
  actions: TargetActions;
  onOpen: (item: TargetItem, evalAt: Date) => void;
}

/** Curated list of what is above the horizon, with filters and an observation time. */
export function TonightPanel({ location, now, scope, actions, onOpen }: Props) {
  const [filters, setFilters] = useCatalogFilters();
  const [sort, setSortRaw] = useState<SortKey>(loadSort);
  const [offsetMin, setOffsetMin] = useState(0);

  const evalAt = useMemo(() => new Date(now + offsetMin * 60_000), [now, offsetMin]);

  const rows = useMemo(
    () => (location ? tonightRows(objects, filters, location, evalAt, sort, scope) : []),
    [location, filters, evalAt, sort, scope],
  );

  const bodies = useSolarSystem(location ? evalAt : null);
  const solarRows = useMemo(() => {
    if (!location) return [];
    return bodies
      .filter((b) => !b.near_sun)
      .map((b) => {
        const item = solarItem(b);
        const aa = altAzOf(item, location, evalAt);
        return { item, altDeg: aa?.altDeg ?? null, azDeg: aa?.azDeg ?? null, mag: b.magnitude };
      })
      .filter((r) => r.altDeg !== null && r.altDeg >= SOLAR_MIN_ALT_DEG)
      .sort((a, b) => a.mag - b.mag);
  }, [bodies, location, evalAt]);

  if (!location) {
    return (
      <Alert variant="info" title="Set your location">
        Open Settings and enter where you are to see which objects are above the horizon.
      </Alert>
    );
  }

  const narrowed = activeFilterCount(filters);
  const openRow = (item: TargetItem) => onOpen(item, evalAt);

  return (
    <div className="flex flex-col gap-3">
      <Disclosure
        title="Filter and sort"
        summary={narrowed > 0 ? `${narrowed} filtered · ${SORT_LABELS[sort]}` : SORT_LABELS[sort]}
      >
        <CatalogFilters value={filters} onChange={setFilters} />
        <div className="flex flex-col gap-2">
          <span className="text-label text-muted-foreground">Sort</span>
          <SegmentedControl
            aria-label="Sort"
            fullWidth
            value={sort}
            options={SORT_OPTIONS}
            onValueChange={(v) => {
              setSortRaw(v);
              writeStored(SORT_KEY, v);
            }}
          />
        </div>
      </Disclosure>

      <Card>
        <TimeControl now={now} appliedOffsetMin={offsetMin} onApply={setOffsetMin} />
      </Card>

      <DarknessBanner
        location={location}
        evalAt={evalAt}
        appliedOffsetMin={offsetMin}
        onApply={setOffsetMin}
      />

      {solarRows.length > 0 && (
        <section aria-label="Solar system" className="flex flex-col gap-2">
          <p className="text-label text-muted-foreground">
            Moon, planets and bright asteroids above {SOLAR_MIN_ALT_DEG}°
          </p>
          <TargetList rows={solarRows} actions={{ ...actions, onOpen: openRow }} />
        </section>
      )}

      {rows.length === 0 ? (
        <EmptyState
          title="Nothing to show"
          description={`No objects above ${ALT_THRESHOLD_DEG}° with these filters at this time. Widen the filters or move the time forward.`}
        />
      ) : (
        <>
          <p className="text-label text-muted-foreground">
            {rows.length} {rows.length === 1 ? "object" : "objects"} above {ALT_THRESHOLD_DEG}°
            {sort === "near" && !scope && " · highest first until the scope has a solve"}
          </p>
          <TargetList
            rows={rows}
            actions={{ ...actions, onOpen: openRow }}
          />
        </>
      )}
    </div>
  );
}
