import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { payload, sampleObserving } from "@/lib/testPayload";
import type { EnginePayload, ObservingBlock } from "@/lib/types";
import { SettingsSheet } from "@/components/app/SettingsSheet";
import { EquipmentSheet } from "./EquipmentSheet";

vi.mock("@/lib/api", () => ({
  api: {
    setSettings: vi.fn(),
    observations: vi.fn(),
    observationsCsvUrl: vi.fn(),
    cloudStatus: vi.fn(),
    observing: { create: vi.fn(), update: vi.fn(), remove: vi.fn(), setCurrent: vi.fn() },
  },
}));
const obs = vi.mocked(api.observing);

const located = { latitude: 40.0149, longitude: -105.2705, source: "manual" as const };

function withObserving(o: Partial<ObservingBlock> = {}, over: Partial<EnginePayload> = {}) {
  return payload({ observing: { ...sampleObserving, ...o }, location: located, ...over });
}

function sheet(state: EnginePayload) {
  return render(<EquipmentSheet open onOpenChange={() => {}} state={state} />);
}

beforeEach(() => {
  for (const fn of Object.values(obs)) fn.mockReset();
  obs.create.mockResolvedValue({ id: "new" });
  obs.update.mockResolvedValue(undefined);
  obs.remove.mockResolvedValue(undefined);
  obs.setCurrent.mockResolvedValue(undefined);
  vi.mocked(api.observations).mockResolvedValue({ enabled: true, clock: "system", entries: [] });
  vi.mocked(api.cloudStatus).mockResolvedValue({ available: false, linked: false });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Equipment sheet", () => {
  it("asks for an update when the engine sends no observing block", () => {
    sheet(payload());
    expect(screen.getByText("Update your Starlock to save sites and equipment.")).toBeInTheDocument();
    expect(screen.queryByText("In use")).not.toBeInTheDocument();
    expect(screen.queryByText("Horizon")).not.toBeInTheDocument();
  });

  it("shows what is in use and the optics line", () => {
    sheet(withObserving());
    const card = screen.getByLabelText("In use");
    expect(within(card).getByRole("button", { name: "Site: Back yard" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: 'Telescope: 8" Dob' })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Eyepiece: 25 mm Plössl" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Finder: Telrad" })).toBeInTheDocument();
    expect(within(card).getByText("48× · 1.1° field · 4.2 mm exit pupil")).toBeInTheDocument();
  });

  it("without a telescope and an eyepiece it says what to pick", () => {
    sheet(
      withObserving({
        current: { ...sampleObserving.current, eyepiece_id: null },
        optics: { magnification: null, true_field_deg: null, exit_pupil_mm: null, finder_rings_deg: [0.5, 2, 4] },
      }),
    );
    expect(screen.getByRole("button", { name: "Eyepiece: None" })).toBeInTheDocument();
    expect(
      screen.getByText("Pick a telescope and an eyepiece to see the magnification and field."),
    ).toBeInTheDocument();
  });

  it("a picker posts the choice at once and shows it before the engine confirms", async () => {
    sheet(withObserving());
    fireEvent.click(screen.getByRole("button", { name: "Eyepiece: 25 mm Plössl" }));
    fireEvent.click(await screen.findByRole("radio", { name: /10 mm wide/ }));
    expect(obs.setCurrent).toHaveBeenCalledWith({ eyepiece_id: "e2" });
    expect(screen.getByRole("button", { name: "Eyepiece: 10 mm wide" })).toBeInTheDocument();
  });

  it("None clears a slot; a failed choice goes back with a short error", async () => {
    obs.setCurrent.mockRejectedValue(new Error("unknown id"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    sheet(withObserving());
    fireEvent.click(screen.getByRole("button", { name: "Finder: Telrad" }));
    fireEvent.click(await screen.findByRole("radio", { name: "None" }));
    expect(obs.setCurrent).toHaveBeenCalledWith({ finder_id: null });
    expect(await screen.findByText("Couldn't change the finder")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finder: Telrad" })).toBeInTheDocument();
  });

  it("lists the gear with summaries and marks what is in use", () => {
    sheet(withObserving());
    expect(screen.getByText("203 mm aperture, 1200 mm focal length")).toBeInTheDocument();
    expect(screen.getByText("68° field", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Reflex: 0.5°, 2°, 4°")).toBeInTheDocument();
    expect(screen.getByText("Optical, 6° field")).toBeInTheDocument();
    expect(screen.getByText("40.01, -105.27")).toBeInTheDocument();
    expect(screen.getAllByText("In use").length).toBeGreaterThan(1);
  });

  it("tapping a saved row puts it in use", () => {
    sheet(withObserving());
    fireEvent.click(screen.getByRole("button", { name: /^80 mm refractor/ }));
    expect(obs.setCurrent).toHaveBeenCalledWith({ telescope_id: "t2" });
    fireEvent.click(screen.getByRole("button", { name: /^Dark site/ }));
    expect(obs.setCurrent).toHaveBeenCalledWith({ site_id: "s2" });
  });

  it("empty lists show one muted line", () => {
    sheet(withObserving({ telescopes: [], eyepieces: [], finders: [], sites: [] }));
    expect(screen.getByText("No telescopes yet.")).toBeInTheDocument();
    expect(screen.getByText("No eyepieces yet.")).toBeInTheDocument();
    expect(screen.getByText("No finders yet.")).toBeInTheDocument();
    expect(screen.getByText("No saved sites yet.")).toBeInTheDocument();
  });

  it("adds a telescope, once the fields are valid", async () => {
    sheet(withObserving());
    fireEvent.click(screen.getByRole("button", { name: "Add telescope" }));
    const dialog = await screen.findByRole("dialog", { name: "Add telescope" });
    const add = within(dialog).getByRole("button", { name: "Add" });
    expect(add).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: " 6 inch Dob " } });
    fireEvent.change(within(dialog).getByLabelText("Aperture (mm)"), { target: { value: "5" } });
    fireEvent.change(within(dialog).getByLabelText("Focal length (mm)"), { target: { value: "1200" } });
    expect(within(dialog).getByText("Between 10 and 2000.")).toBeInTheDocument();
    expect(add).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Aperture (mm)"), { target: { value: "150" } });
    fireEvent.click(add);
    await waitFor(() =>
      expect(obs.create).toHaveBeenCalledWith("telescopes", {
        name: "6 inch Dob",
        aperture_mm: 150,
        focal_length_mm: 1200,
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add telescope" })).not.toBeInTheDocument());
  });

  it("shows the engine's reason under the form when it refuses", async () => {
    obs.update.mockRejectedValue(new Error("afov_deg must be 20–120"));
    sheet(withObserving());
    fireEvent.click(screen.getByRole("button", { name: "Edit 10 mm wide" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit eyepiece" });
    expect(within(dialog).getByLabelText("Apparent field (°)")).toHaveValue("68");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText("afov_deg must be 20–120")).toBeInTheDocument();
    expect(within(dialog).getByText("Couldn't save")).toBeInTheDocument();
  });

  it("a reflex finder takes comma-separated rings, prefilled 0.5, 2, 4", async () => {
    sheet(withObserving());
    fireEvent.click(screen.getByRole("button", { name: "Add finder" }));
    const dialog = await screen.findByRole("dialog", { name: "Add finder" });
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Telrad 2" } });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Reflex" }));
    expect(within(dialog).getByLabelText("Rings (°)")).toHaveValue("0.5, 2, 4");
    fireEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(obs.create).toHaveBeenCalledWith("finders", { name: "Telrad 2", kind: "reflex", rings_deg: [0.5, 2, 4] }),
    );
  });

  it("deletes after asking", async () => {
    sheet(withObserving());
    fireEvent.click(screen.getByRole("button", { name: "Edit Dark site" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit site" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(within(dialog).getByText("Delete Dark site?")).toBeInTheDocument();
    expect(within(dialog).getByText("Its horizon is deleted too.")).toBeInTheDocument();
    expect(obs.remove).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(obs.remove).toHaveBeenCalledWith("sites", "s2"));
  });

  it("the site in use: its name renames it; Location and Horizon edit it", async () => {
    sheet(withObserving());
    expect(screen.getByRole("heading", { name: "Site" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Location" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Horizon" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save as a site" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rename Back yard" }));
    const dialog = await screen.findByRole("dialog", { name: "Rename site" });
    expect(within(dialog).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Garden" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(obs.update).toHaveBeenCalledWith("sites", "s1", {
        name: "Garden",
        latitude: 40.0149,
        longitude: -105.2705,
        horizon: Array(16).fill(3),
      }),
    );
  });

  it("no site in use: Location heads the section; Save as a site posts it and selects it", async () => {
    const horizon = Array(16).fill(0);
    horizon[4] = 7;
    sheet(
      withObserving(
        { current: { ...sampleObserving.current, site_id: null } },
        { horizon: { obscured: horizon } },
      ),
    );
    expect(screen.queryByRole("heading", { name: "Site" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save as a site" }));
    const dialog = await screen.findByRole("dialog", { name: "Save as a site" });
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Balcony" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(obs.create).toHaveBeenCalledWith("sites", {
        name: "Balcony",
        latitude: 40.0149,
        longitude: -105.2705,
        horizon,
      }),
    );
    await waitFor(() => expect(obs.setCurrent).toHaveBeenCalledWith({ site_id: "new" }));
  });

  it("Save as a site needs a location", () => {
    sheet(
      withObserving(
        { current: { ...sampleObserving.current, site_id: null } },
        { location: { latitude: null, longitude: null, source: null } },
      ),
    );
    expect(screen.getByRole("button", { name: "Save as a site" })).toBeDisabled();
  });

  it("Add site posts name and coordinates (default horizon), then selects it", async () => {
    sheet(withObserving());
    fireEvent.click(screen.getByRole("button", { name: "Add site" }));
    const dialog = await screen.findByRole("dialog", { name: "Add site" });
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Club field" } });
    fireEvent.change(within(dialog).getByLabelText("Latitude"), { target: { value: "-33.87" } });
    fireEvent.change(within(dialog).getByLabelText("Longitude"), { target: { value: "151.21" } });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    });
    expect(obs.create).toHaveBeenCalledWith("sites", { name: "Club field", latitude: -33.87, longitude: 151.21 });
    await waitFor(() => expect(obs.setCurrent).toHaveBeenCalledWith({ site_id: "new" }));
  });
});

describe("Settings sheet", () => {
  function settings(state: EnginePayload) {
    return render(
      <SettingsSheet open onOpenChange={() => {}} state={state} showStars={false} setShowStars={() => {}} />,
    );
  }

  it("keeps Location and Horizon for an older engine", () => {
    settings(payload());
    expect(screen.getByRole("heading", { name: "Location" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Horizon" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Logbook" })).toBeInTheDocument();
  });

  it("drops them once they belong to the site, in the Equipment sheet", () => {
    settings(withObserving());
    expect(screen.queryByRole("heading", { name: "Location" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Horizon" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Logbook" })).toBeInTheDocument();
  });
});
