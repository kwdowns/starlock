import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { payload } from "@/lib/testPayload";
import { HorizonEditor } from "./HorizonEditor";

vi.mock("@/lib/api", () => ({ api: { setSettings: vi.fn() } }));
const setSettings = vi.mocked(api.setSettings);

// jsdom has no layout: give the chart a 300 px box at the origin.
const SIZE = 300;
beforeEach(() => {
  setSettings.mockReset();
  setSettings.mockResolvedValue(undefined);
  vi.spyOn(SVGElement.prototype, "getBoundingClientRect").mockReturnValue({
    left: 0, top: 0, width: SIZE, height: SIZE, right: SIZE, bottom: SIZE, x: 0, y: 0,
    toJSON: () => ({}),
  } as DOMRect);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** Screen point at the middle of a cell, for the chart's geometry at SIZE. */
function at(sector: number, band: number) {
  const r = SIZE / 2 - 30;
  const w = (0.8 * r) / 9;
  const radius = r - (band + 0.5) * w;
  const a = (sector * 22.5 * Math.PI) / 180;
  return { clientX: SIZE / 2 + radius * Math.sin(a), clientY: SIZE / 2 - radius * Math.cos(a), pointerId: 1 };
}

function chart() {
  return screen.getByRole("group", { name: /Horizon chart/ });
}

describe("HorizonEditor", () => {
  it("shows the default mask until the engine sends one", () => {
    render(<HorizonEditor state={payload()} />);
    expect(screen.getAllByRole("button", { name: /degrees, (hidden|visible)$/ })).toHaveLength(144);
    expect(screen.getByRole("button", { name: "N, 0 to 10 degrees, hidden" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "NNE, 10 to 20 degrees, hidden" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "NNE, 20 to 30 degrees, visible" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset" })).toBeDisabled();
  });

  it("a tap toggles one cell at once and posts the whole mask on release", async () => {
    render(<HorizonEditor state={payload({ horizon: { obscured: Array(16).fill(0) } })} />);
    fireEvent.pointerDown(chart(), at(4, 3));
    fireEvent.pointerUp(chart(), at(4, 3));
    expect(screen.getByRole("button", { name: "E, 30 to 40 degrees, hidden" })).toBeInTheDocument();
    await waitFor(() => expect(setSettings).toHaveBeenCalledTimes(1));
    const sent = setSettings.mock.calls[0][0].horizon!.obscured;
    expect(sent[4]).toBe(8);
    expect(sent.filter((v) => v !== 0)).toHaveLength(1);
  });

  it("a drag paints every cell it crosses in the first cell's mode, with one post", async () => {
    render(<HorizonEditor state={payload()} />);
    // Starts on a visible cell (band 2): everything crossed becomes hidden.
    fireEvent.pointerDown(chart(), at(8, 2));
    fireEvent.pointerMove(chart(), at(8, 5));
    fireEvent.pointerMove(chart(), at(9, 5));
    expect(setSettings).not.toHaveBeenCalled();
    fireEvent.pointerUp(chart(), at(9, 5));
    await waitFor(() => expect(setSettings).toHaveBeenCalledTimes(1));
    const sent = setSettings.mock.calls[0][0].horizon!.obscured;
    // S: bands 0, 1 (default) + 2..5 painted; SSW: default + band 5.
    expect(sent[8]).toBe(0b111111);
    expect(sent[9]).toBe(0b100011);
  });

  it("goes back to the engine's mask and says so when saving fails", async () => {
    setSettings.mockRejectedValue(new Error("POST /api/settings → 400"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<HorizonEditor state={payload()} />);
    fireEvent.pointerDown(chart(), at(0, 5));
    fireEvent.pointerUp(chart(), at(0, 5));
    expect(await screen.findByText("Couldn't save the horizon")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "N, 50 to 60 degrees, visible" })).toBeInTheDocument();
  });

  it("follows the engine's mask after a save", async () => {
    const { rerender } = render(<HorizonEditor state={payload()} />);
    fireEvent.pointerDown(chart(), at(0, 5));
    fireEvent.pointerUp(chart(), at(0, 5));
    await waitFor(() => expect(setSettings).toHaveBeenCalled());
    await act(async () => {});
    const next = Array(16).fill(3);
    next[0] = 3 | 32;
    next[2] = 511; // another device changed it meanwhile
    rerender(<HorizonEditor state={payload({ horizon: { obscured: next } })} />);
    expect(screen.getByRole("button", { name: "NE, 80 to 90 degrees, hidden" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "N, 50 to 60 degrees, hidden" })).toBeInTheDocument();
  });

  it("Reset posts null, Clear all posts sixteen zeros; keyboard toggles a cell", async () => {
    render(<HorizonEditor state={payload({ horizon: { obscured: Array(16).fill(7) } })} />);
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(setSettings).toHaveBeenLastCalledWith({ horizon: null }));
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    await waitFor(() =>
      expect(setSettings).toHaveBeenLastCalledWith({ horizon: { obscured: Array(16).fill(0) } }),
    );
    fireEvent.keyDown(screen.getByRole("button", { name: "W, 40 to 50 degrees, visible" }), { key: "Enter" });
    await waitFor(() => expect(setSettings).toHaveBeenCalledTimes(3));
    expect(setSettings.mock.calls[2][0].horizon!.obscured[12]).toBe(16);
  });
});
