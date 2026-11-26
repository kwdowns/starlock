import { describe, expect, it } from "vitest";
import {
  circleRadiusPx,
  equipmentLine,
  eyepieceSummary,
  finderSummary,
  formatField,
  formatMagnification,
  opticsLine,
  parseInRange,
  parseName,
  parseRings,
  plainNumber,
  siteCoords,
  telescopeSummary,
} from "./equipment";

describe("optics line", () => {
  // The spec's example line says "1.08° field", but its rule (1 decimal from
  // 1° up) gives 1.1°; the rule wins.
  it("joins magnification, field and exit pupil", () => {
    expect(
      opticsLine({ magnification: 48, true_field_deg: 1.08, exit_pupil_mm: 4.23, finder_rings_deg: null }),
    ).toBe("48× · 1.1° field · 4.2 mm exit pupil");
  });

  it("magnification with no decimals; field 2 decimals under 1°, else 1", () => {
    expect(formatMagnification(120.4)).toBe("120×");
    expect(formatMagnification(47.5)).toBe("48×");
    expect(formatField(0.52)).toBe("0.52°");
    expect(formatField(0.999)).toBe("1.00°");
    expect(formatField(1.08)).toBe("1.1°");
    expect(formatField(2.6)).toBe("2.6°");
    expect(
      opticsLine({ magnification: 120, true_field_deg: 0.43, exit_pupil_mm: 1.69, finder_rings_deg: null }),
    ).toBe("120× · 0.43° field · 1.7 mm exit pupil");
  });

  it("is null without a magnification", () => {
    expect(opticsLine(null)).toBeNull();
    expect(opticsLine(undefined)).toBeNull();
    expect(
      opticsLine({ magnification: null, true_field_deg: null, exit_pupil_mm: null, finder_rings_deg: [0.5] }),
    ).toBeNull();
  });
});

describe("summaries", () => {
  it("telescope, eyepiece and finder rows", () => {
    expect(telescopeSummary({ aperture_mm: 203, focal_length_mm: 1200 })).toBe(
      "203 mm aperture, 1200 mm focal length",
    );
    expect(eyepieceSummary({ focal_length_mm: 25, afov_deg: 52 })).toBe("25 mm, 52° field");
    expect(eyepieceSummary({ focal_length_mm: 6.5, afov_deg: 82 })).toBe("6.5 mm, 82° field");
    expect(finderSummary({ kind: "optical", field_deg: 6 })).toBe("Optical, 6° field");
    expect(finderSummary({ kind: "reflex", rings_deg: [0.5, 2, 4] })).toBe("Reflex: 0.5°, 2°, 4°");
    expect(finderSummary({ kind: "reflex", rings_deg: [0.1] })).toBe("Reflex: 0.1°");
  });

  it("site coordinates with 2 decimals", () => {
    expect(siteCoords({ latitude: 40.0149, longitude: -105.2705 })).toBe("40.01, -105.27");
  });

  it("plain numbers drop trailing zeros", () => {
    expect(plainNumber(6)).toBe("6");
    expect(plainNumber(0.5)).toBe("0.5");
    expect(plainNumber(1.256)).toBe("1.26");
  });
});

describe("logbook equipment line", () => {
  it("joins what is known, magnification after the eyepiece", () => {
    expect(
      equipmentLine({ site_name: "Back yard", telescope: '8" Dob', eyepiece: "25 mm Plössl", magnification: 48 }),
    ).toBe('Back yard · 8" Dob · 25 mm Plössl (48×)');
    expect(equipmentLine({ site_name: "Back yard", telescope: null, eyepiece: null, finder: "Telrad" })).toBe(
      "Back yard · Telrad",
    );
    expect(equipmentLine({ eyepiece: "25 mm Plössl", magnification: null })).toBe("25 mm Plössl");
  });

  it("is null when nothing is known (older engines send none of it)", () => {
    expect(equipmentLine({})).toBeNull();
    expect(equipmentLine({ site_name: null, telescope: "", magnification: 48 })).toBeNull();
  });
});

describe("circle radius", () => {
  it("is (deg / 2) × image_w / fov_h_deg", () => {
    // 1280 px across 8 degrees: 160 px per degree, so a 1° field has an 80 px radius.
    expect(circleRadiusPx(1, 1280, 8)).toBe(80);
    expect(circleRadiusPx(4, 1280, 8)).toBe(320);
    expect(circleRadiusPx(1.08, 1280, 8.86)).toBeCloseTo(78.01, 2);
  });

  it("is null without a field of view or a size", () => {
    expect(circleRadiusPx(1, 1280, 0)).toBeNull();
    expect(circleRadiusPx(0, 1280, 8)).toBeNull();
    expect(circleRadiusPx(1, 0, 8)).toBeNull();
  });
});

describe("form input", () => {
  it("names are trimmed, 1–60 characters", () => {
    expect(parseName("  Telrad ")).toEqual({ ok: true, value: "Telrad" });
    expect(parseName("   ").ok).toBe(false);
    expect(parseName("x".repeat(61)).ok).toBe(false);
    expect(parseName("x".repeat(60)).ok).toBe(true);
  });

  it("numbers in range, with a short reason", () => {
    expect(parseInRange("203", 10, 2000)).toEqual({ ok: true, value: 203 });
    expect(parseInRange("−33.9", -90, 90)).toEqual({ ok: true, value: -33.9 });
    expect(parseInRange("5", 10, 2000)).toEqual({ ok: false, error: "Between 10 and 2000." });
    expect(parseInRange("abc", 10, 2000).ok).toBe(false);
    expect(parseInRange("", 10, 2000).ok).toBe(false);
  });

  it("rings: 1–4 sizes 0.1–10°, ascending", () => {
    expect(parseRings("0.5, 2, 4")).toEqual({ ok: true, value: [0.5, 2, 4] });
    expect(parseRings("0.1")).toEqual({ ok: true, value: [0.1] });
    expect(parseRings("0.5° 2° 4°")).toEqual({ ok: true, value: [0.5, 2, 4] });
    expect(parseRings("").ok).toBe(false);
    expect(parseRings("1, 2, 3, 4, 5").ok).toBe(false);
    expect(parseRings("0.05").ok).toBe(false);
    expect(parseRings("11").ok).toBe(false);
    expect(parseRings("4, 2")).toEqual({ ok: false, error: "Smallest first, each bigger than the one before." });
    expect(parseRings("2, 2").ok).toBe(false);
  });
});
