// ============================================================
// Starlock Star Knob — for a plain M4 × 20 pan-head screw
// ============================================================
//
// A printed stand-in for the M4 × 20 star knob that clamps the camera
// housing to its mount (v3 low mount, v4 Pi mount, U20CAM housing).
// An ordinary M4 × 20 Phillips pan-head screw is glued into the knob.
//
// The screw head sits in a pocket that is open at the bottom, and
// stands HEAD_PROUD (0.3 mm) out of the knob's bottom face, so:
//   - the head itself bears on the mount, just like the bought knob's
//     collar, and the clamping force never goes through the glue
//   - all 20 mm of thread stays below the head, so the screw still
//     reaches through the whole insert (housing_v3.scad's knob_tip)
// A cross-shaped key in the pocket ceiling drops into the Phillips
// recess and turns the screw, so the glue mainly keeps the knob on.
//
// ASSEMBLY:
//   1. Turn the screw until the key drops into its Phillips recess,
//      and check the head stands slightly proud of the knob's bottom.
//   2. Take it out, put a few drops of super glue (gel CA fills the
//      gap better than thin) into the pocket, press the screw back in
//      with the key in the recess, and wipe off what squeezes out.
//   3. Leave it to set screw-up for an hour before tightening it.
//
// MEASURE BEFORE PRINTING — check one screw with calipers:
//   head_dia    — ISO 7045 M4 pan head is 8.0 max
//   head_height — 3.1 max; often 2.8–3.0 on cheap screws
//
// PRINTING: top face on the bed (the pocket opens upward), no supports.
// 0.2 mm layers, 3 walls, 30%+ infill — PETG or PLA.

// ============================================================
// DIMENSIONS — all values in millimeters
// ============================================================

head_dia        = 8.0;    // MEASURE
head_height     = 3.1;    // MEASURE
head_clearance  = 0.2;    // per side: holes print ~0.1–0.2 mm under, and
                          // the glue needs a gap to fill
head_proud      = 0.3;    // head stands out of the knob's bottom by this

key_width       = 0.8;    // Phillips key arm width (PH2 recess ≈ 1.0 at
                          // its mouth); 2 lines at 0.4 mm
key_span        = 3.8;    // tip-to-tip (PH2 recess mouth ≈ 4.4 on M4)
key_depth       = 1.0;    // how far the key reaches into the recess;
                          // 0 leaves it out

knob_dia        = 25;     // across the lobes
knob_lobes      = 5;
lobe_dia        = 8;      // grip lobe diameter
knob_core_dia   = 17;     // body the lobes stand out from
knob_fillet     = 1.5;    // rounds the valleys between lobes
knob_height     = 10;
top_chamfer     = 0.8;    // stepped 45° chamfer on the top edge (prints
                          // on the bed, also hides elephant's foot)

$fn = 64;

// ============================================================
// DERIVED
// ============================================================

pocket_dia   = head_dia + 2 * head_clearance;
pocket_depth = head_height - head_proud;
lobe_r       = knob_dia / 2 - lobe_dia / 2;

assert(knob_height - pocket_depth - key_depth >= 4,
       "too little knob above the screw head");
assert(knob_core_dia >= pocket_dia + 6, "knob wall round the head under 3 mm");

// ============================================================
// MODULES
// ============================================================

module _knob_outline() {
    offset(r = -knob_fillet) offset(r = knob_fillet)
        union() {
            circle(d = knob_core_dia);
            for (i = [0 : knob_lobes - 1])
                rotate(i * 360 / knob_lobes)
                    translate([lobe_r, 0]) circle(d = lobe_dia);
        }
}

// Modeled in print orientation: knob top on the bed (Z = 0), pocket
// opening at Z = knob_height.
module star_knob() {
    steps = round(top_chamfer / 0.2);
    difference() {
        union() {
            // Stepped chamfer — one 0.2 mm layer per step
            for (i = [0 : steps - 1])
                translate([0, 0, i * 0.2])
                    linear_extrude(0.2 + 0.01)
                        offset(delta = -(top_chamfer - i * 0.2))
                            _knob_outline();
            translate([0, 0, top_chamfer])
                linear_extrude(knob_height - top_chamfer)
                    _knob_outline();
        }

        // Head pocket, open at the knob's bottom
        translate([0, 0, knob_height - pocket_depth])
            cylinder(d = pocket_dia, h = pocket_depth + 1);
        // 0.4 mm × 45° chamfer at the pocket mouth: the screw starts in
        // easily and the glue has somewhere to collect
        translate([0, 0, knob_height - 0.4])
            cylinder(d1 = pocket_dia, d2 = pocket_dia + 0.8 + 0.02, h = 0.41);
    }

    // Phillips key, standing up from the pocket ceiling
    if (key_depth > 0)
        translate([0, 0, knob_height - pocket_depth - 0.01])
            for (a = [0, 90])
                rotate(a)
                    translate([-key_span / 2, -key_width / 2, 0])
                        cube([key_span, key_width, key_depth + 0.01]);
}

star_knob();
