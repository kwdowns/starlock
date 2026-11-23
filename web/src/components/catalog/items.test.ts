import { describe, expect, it } from "vitest"
import type { NgcEntry } from "@/lib/catalogTypes"
import { advancedItem, isDesignation } from "./items"

function ngc(id: string, aliases: string[]): NgcEntry {
  return {
    id, aliases, type: "G", ra_deg: 10, dec_deg: 41, mag: 8, constellation: "And", size: 10,
    source: "ngc",
  } as NgcEntry
}

describe("NGC titles", () => {
  it("uses the Messier name when there is no common name", () => {
    const item = advancedItem(
      ngc("NGC 205", ["M 110", "2MASX J00402207+4141070", "IRAS 00376+4124", "PGC 002429"]),
    )
    expect(item.title).toBe("M 110")
    expect(item.subtitle).toContain("NGC 205")
  })

  it("puts a common name first", () => {
    const item = advancedItem(ngc("NGC 224", ["M 31", "Andromeda Galaxy", "2MASX J00424433+4116074"]))
    expect(item.title).toBe("Andromeda Galaxy")
  })

  it("skips signed and hyphenated catalogue ids", () => {
    const item = advancedItem(ngc("NGC 205", ["M 110", "MCG +07-02-014", "ESO-LV 1230", "SDSS J004022.07+414107.0"]))
    expect(item.title).toBe("M 110")
  })

  it("never takes a survey designation as the name", () => {
    expect(advancedItem(ngc("NGC 1", ["2MASX J00071582+2742291", "6dFGS gJ000715.8+274229"])).title)
      .toBe("NGC 1")
  })
})

describe("isDesignation", () => {
  it.each(["M 31", "PGC 2429", "MCG +07-02-014", "ESO-LV 1230", "PN G010.1+00.7", "BD+40 1", "HD", "Sh2-155"])(
    "%s is a designation", (n) => expect(isDesignation(n)).toBe(true),
  )
  it.each(["Andromeda Galaxy", "Barnard's Galaxy", "Bow-Tie nebula", "S Nor Cluster", "the Guitar", "Omega Centauri"])(
    "%s is a name", (n) => expect(isDesignation(n)).toBe(false),
  )
})
