import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { payload } from "@/lib/testPayload";
import { WifiWarning, wifiSummary } from "./WifiWarning";

const weak = { interface: "wlan0", level_dbm: -80, avg_dbm: -79, quality: "poor" as const, warn: true };

describe("WifiWarning", () => {
  it("shows only when the engine says to warn", () => {
    const { rerender } = render(<WifiWarning state={payload({ wifi: weak })} />);
    expect(screen.getByText("Weak Wi-Fi at the scope")).toBeTruthy();
    rerender(<WifiWarning state={payload({ wifi: { ...weak, warn: false } })} />);
    expect(screen.queryByText("Weak Wi-Fi at the scope")).toBeNull();
    rerender(<WifiWarning state={payload({ wifi: null })} />);
    expect(screen.queryByText("Weak Wi-Fi at the scope")).toBeNull();
  });

  it("summarises the signal", () => {
    expect(wifiSummary(weak)).toBe("-79 dBm (poor)");
  });
});
