import { CheckIcon } from "lucide-react";
import { Button, List, ListRow } from "@/components/ui";
import { azimuthCompass } from "@/lib/catalogTypes";
import { formatDistance } from "@/lib/screen";
import type { TargetItem } from "./items";

export interface TargetRowData {
  item: TargetItem;
  altDeg: number | null;
  azDeg: number | null;
  /** Distance from the scope; shown under alt/az when set. */
  sepDeg?: number | null;
}

export interface TargetActions {
  isActive: (item: TargetItem) => boolean;
  /** Key of the item whose goto request is in flight. */
  pendingKey: string | null;
  /** Row button: set the target, do not open anything. */
  onGo: (item: TargetItem) => void;
  /** Row body: open the detail sheet. */
  onOpen: (item: TargetItem) => void;
}

/** A flowing list of targets; each row has its own "Go to" button. */
export function TargetList({
  rows,
  actions,
}: {
  rows: TargetRowData[];
  actions: TargetActions;
}) {
  return (
    <List>
      {rows.map(({ item, altDeg, azDeg, sepDeg }) => {
        const active = actions.isActive(item);
        const below = altDeg !== null && altDeg < 0;
        const altAz = altDeg !== null && azDeg !== null
          ? `${Math.round(altDeg)}° ${azimuthCompass(azDeg)}`
          : null;
        const away = sepDeg != null ? `${formatDistance(sepDeg)} away` : null;
        return (
          <ListRow
            key={item.key}
            title={item.title}
            subtitle={item.subtitle}
            meta={
              altAz && away ? (
                <span className="flex flex-col">
                  <span>{altAz}</span>
                  <span>{away}</span>
                </span>
              ) : (altAz ?? away ?? undefined)
            }
            selected={active}
            onPress={() => actions.onOpen(item)}
            action={
              <Button
                size="sm"
                variant={active ? "primary" : "secondary"}
                loading={actions.pendingKey === item.key}
                disabled={below}
                aria-label={
                  active ? `${item.title}, current target` : `Go to ${item.title}`
                }
                title={below ? "Below the horizon" : undefined}
                onClick={() => actions.onGo(item)}
              >
                {active && <CheckIcon />}
                {active ? "Target" : "Go to"}
              </Button>
            }
          />
        );
      })}
    </List>
  );
}
