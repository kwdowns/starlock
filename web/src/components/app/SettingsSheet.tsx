import {
  Separator,
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui";
import { LocationPanel } from "@/components/catalog/LocationPanel";
import { DebugPanel } from "@/components/debug/DebugPanel";
import { CloudLink } from "@/components/settings/CloudLink";
import { HorizonEditor } from "@/components/settings/HorizonEditor";
import { ObservationLog } from "@/components/settings/ObservationLog";
import { Connectivity } from "@/components/settings/Connectivity";
import { Settings } from "@/components/settings/Settings";
import type { EnginePayload } from "@/lib/types";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  state: EnginePayload;
  showStars: boolean;
  setShowStars: (v: boolean) => void;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-heading">{title}</h2>
      {children}
    </div>
  );
}

/**
 * Settings, connectivity, the logbook and (dev mode) debug tools. With an
 * older engine (no `observing`) the observer location and horizon live here
 * too; otherwise they are the site's, in the Equipment sheet.
 */
export function SettingsSheet({ open, onOpenChange, state, showStars, setShowStars }: Props) {
  const siteHere = !state.observing;
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Settings</SheetTitle>
          <SheetDescription>
            {siteHere ? "Display, connections, location and horizon." : "Display, connections and the logbook."}
          </SheetDescription>
        </SheetHeader>
        <SheetBody className="gap-5 pb-[max(1rem,var(--safe-bottom))]">
          <Settings state={state} showStars={showStars} setShowStars={setShowStars} />
          <Separator />
          <Section title="Connections">
            <Connectivity state={state} />
          </Section>
          <Separator />
          {siteHere && (
            <>
              {/* LocationPanel brings its own "Location" heading. */}
              <LocationPanel state={state} />
              <Separator />
              <HorizonEditor state={state} />
              <Separator />
            </>
          )}
          <ObservationLog />
          <Separator />
          <CloudLink open={open} />
          {state.dev_mode && (
            <>
              <Separator />
              <Section title="Debug">
                <DebugPanel state={state} />
              </Section>
            </>
          )}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}
