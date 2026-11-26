import { useState } from "react";
import {
  Maximize,
  Minimize,
  Settings as SettingsIcon,
  CircleCheck,
  Telescope,
  TriangleAlert,
  Volume2,
  VolumeX,
} from "lucide-react";
import { AppBar, Button } from "@/components/ui";
import { useFullscreen } from "@/hooks/useFullscreen";
import { useOnTargetSound } from "@/hooks/useOnTargetFeedback";
import { cn } from "@/lib/utils";
import { statusBadgeFor } from "@/lib/screen";
import type { EnginePayload } from "@/lib/types";
import { EquipmentSheet } from "@/components/equipment/EquipmentSheet";
import { SettingsSheet } from "./SettingsSheet";

interface Props {
  state: EnginePayload;
  showStars: boolean;
  setShowStars: (v: boolean) => void;
}

export function TopBar({ state, showStars, setShowStars }: Props) {
  const fullscreen = useFullscreen();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [equipmentOpen, setEquipmentOpen] = useState(false);
  const badge = statusBadgeFor(state);
  const [sound, setSound] = useOnTargetSound();

  return (
    <AppBar>
      <img
        src={`${import.meta.env.BASE_URL}inapp-title.png`}
        alt="Starlock"
        // A long badge matters more than the wordmark on a narrow phone. Below
        // 480 px the wordmark shrinks, and makes way when a full-screen button
        // (Android) makes four controls beside the status.
        className={cn(
          "h-8 w-auto shrink-0 max-[30rem]:h-6",
          badge.label.length > 7 && "max-sm:hidden",
          fullscreen.supported && "max-[30rem]:hidden",
        )}
      />
      <div className="flex flex-1 justify-end">
        {/* Status, not a control: plain icon + text. Borders and fills are
            reserved for things you can tap. */}
        <span
          role="status"
          aria-live="polite"
          className={cn(
            "inline-flex items-center gap-1.5 text-label whitespace-nowrap",
            badge.variant === "solid" ? "font-semibold text-foreground" : "text-muted-foreground",
          )}
        >
          {badge.alert ? (
            <TriangleAlert className="size-4" aria-hidden />
          ) : badge.variant === "solid" ? (
            <CircleCheck className="size-4" aria-hidden />
          ) : null}
          {badge.label}
        </span>
      </div>
      <div className="flex items-center">
        <Button
          variant="ghost"
          size="icon"
          aria-label={sound ? "Mute the on-target sound" : "Unmute the on-target sound"}
          aria-pressed={sound}
          onClick={() => setSound(!sound)}
        >
          {sound ? <Volume2 /> : <VolumeX />}
        </Button>
        {fullscreen.supported && (
          <Button
            variant="ghost"
            size="icon"
            aria-label={fullscreen.active ? "Exit full screen" : "Full screen"}
            onClick={fullscreen.toggle}
          >
            {fullscreen.active ? <Minimize /> : <Maximize />}
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          aria-label="Equipment"
          title="Equipment"
          onClick={() => setEquipmentOpen(true)}
        >
          <Telescope />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Settings"
          onClick={() => setSettingsOpen(true)}
        >
          <SettingsIcon />
        </Button>
      </div>
      <EquipmentSheet open={equipmentOpen} onOpenChange={setEquipmentOpen} state={state} />
      <SettingsSheet
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        state={state}
        showStars={showStars}
        setShowStars={setShowStars}
      />
    </AppBar>
  );
}
