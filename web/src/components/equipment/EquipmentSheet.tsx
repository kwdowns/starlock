import {
  Separator,
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui";
import { eyepieceSummary, finderSummary, telescopeSummary } from "@/lib/equipment";
import type { EnginePayload, ObservingBlock } from "@/lib/types";
import { EyepieceDialog, FinderDialog, TelescopeDialog } from "./GearDialogs";
import { GearSection } from "./GearSection";
import { InUseCard } from "./InUseCard";
import { SiteSection } from "./SiteSection";
import { useSelection } from "./useSelection";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  state: EnginePayload;
}

/** Sites, telescopes, eyepieces and finders, and which are in use. Opened from the top bar. */
export function EquipmentSheet({ open, onOpenChange, state }: Props) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Equipment</SheetTitle>
          <SheetDescription>Observing sites, telescopes, eyepieces and finders.</SheetDescription>
        </SheetHeader>
        <SheetBody className="gap-5 pb-[max(1rem,var(--safe-bottom))]">
          {state.observing ? (
            <EquipmentPage state={state} observing={state.observing} />
          ) : (
            <p className="text-body text-muted-foreground">
              Update your Starlock to save sites and equipment.
            </p>
          )}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}

/** The sheet's content, for an engine that sends `observing`. */
export function EquipmentPage({ state, observing }: { state: EnginePayload; observing: ObservingBlock }) {
  const selection = useSelection(observing.current);
  const { current, select } = selection;

  return (
    <>
      <InUseCard observing={observing} selection={selection} />
      <SiteSection state={state} observing={observing} selection={selection} />
      <Separator />
      <GearSection
        id="equipment-telescopes"
        title="Telescopes"
        items={observing.telescopes}
        summary={telescopeSummary}
        emptyText="No telescopes yet."
        addLabel="Add telescope"
        inUseId={current.telescope_id}
        onSelect={(id) => select("telescope_id", id)}
        dialog={(item, close) => (
          <TelescopeDialog item={item} onClose={close} onAdded={(id) => !current.telescope_id && select("telescope_id", id)} />
        )}
      />
      <Separator />
      <GearSection
        id="equipment-eyepieces"
        title="Eyepieces"
        items={observing.eyepieces}
        summary={eyepieceSummary}
        emptyText="No eyepieces yet."
        addLabel="Add eyepiece"
        inUseId={current.eyepiece_id}
        onSelect={(id) => select("eyepiece_id", id)}
        dialog={(item, close) => (
          <EyepieceDialog item={item} onClose={close} onAdded={(id) => !current.eyepiece_id && select("eyepiece_id", id)} />
        )}
      />
      <Separator />
      <GearSection
        id="equipment-finders"
        title="Finders"
        items={observing.finders}
        summary={finderSummary}
        emptyText="No finders yet."
        addLabel="Add finder"
        inUseId={current.finder_id}
        onSelect={(id) => select("finder_id", id)}
        dialog={(item, close) => (
          <FinderDialog item={item} onClose={close} onAdded={(id) => !current.finder_id && select("finder_id", id)} />
        )}
      />
    </>
  );
}
