import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type ObservationEntry } from "@/lib/api";
import { ObservationLog } from "./ObservationLog";

vi.mock("@/lib/api", () => ({
  api: { observations: vi.fn(), observationsCsvUrl: vi.fn(), setSettings: vi.fn() },
}));

const entry: ObservationEntry = {
  id: 1,
  start_utc: "2026-11-25T03:00:00Z",
  end_utc: "2026-11-25T03:05:00Z",
  duration_s: 300,
  open: false,
  ra_j2000_deg: 83.82,
  dec_j2000_deg: -5.39,
  alt_deg: 40,
  az_deg: 150,
  target_name: "M 42",
  clock: "system",
};

afterEach(cleanup);

describe("Logbook", () => {
  it("is titled Logbook and shows the equipment line on entries that have it", async () => {
    vi.mocked(api.observations).mockResolvedValue({
      enabled: true,
      clock: "system",
      entries: [
        { ...entry, site_name: "Back yard", telescope: '8" Dob', eyepiece: "25 mm Plössl", finder: null, magnification: 48 },
        { ...entry, id: 2, target_name: "M 31" },
      ],
    });
    render(<ObservationLog />);
    expect(screen.getByRole("heading", { name: "Logbook" })).toBeInTheDocument();
    expect(await screen.findByText('Back yard · 8" Dob · 25 mm Plössl (48×)')).toBeInTheDocument();
    expect(screen.getByText("M 31")).toBeInTheDocument();
    expect(screen.getAllByText(/ · /).filter((el) => el.textContent?.includes("Dob"))).toHaveLength(1);
  });
});
