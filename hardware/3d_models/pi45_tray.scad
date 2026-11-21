// Copyright (C) 2026 Arun Venkataswamy
// Copyright (C) 2026 Kyle Downs
//
// This file is part of Starlock.
//
// Starlock is free software: you can redistribute it and/or modify it
// under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// Starlock is distributed in the hope that it will be useful, but
// WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
// General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with Starlock. If not, see <https://www.gnu.org/licenses/>.

// ============================================================
// Starlock Pi 4 / Pi 5 Tube Tray and Cover
// ============================================================
//
// An open tray that carries a Raspberry Pi 4 or 5 on the telescope
// tube, for Starlock headless. Its base is curved to the tube like the
// tube shoe (tube_shoe.scad), and it sticks on with 3M VHB tape; a
// 25 mm Velcro strap through the end slots and round the tube is
// optional insurance. Use an Active Cooler on a Pi 5, which runs the
// solver continuously.
//
// The Pi's long edge runs along the tube. Mount it near the tube shoe
// so the camera's 1 m lead reaches without strain, and with the USB-C
// power side facing where your power bank lives.
//
// BOARD MOUNTING (PI_PINS):
//   false — 4 × M2.5 × 6 screws into 2.2 mm pilots in the standoffs
//   true  — each standoff ends in a pin that goes up through the Pi's
//           mounting hole; a drop of thin super glue (CA) on each pin
//           holds the board
//
// COVER (optional): a roof that snaps over the Pi and keeps dew and
// dust off it. Two beads inside each skirt click into pockets in the
// tray's long sides, which also stop it sliding along the tube. It
// leaves open:
//   - the USB / Ethernet end (camera lead), fully
//   - the USB-C and micro-HDMI side, through windows at port height
//   - the microSD, through a slot in the other end wall
//   - vents in the roof over the SoC / Active Cooler fan
// To take it off, spread the skirts at the middle of each side.
//
// MEASURE YOUR TUBE: set tube_od = circumference / π (as tube_shoe).
//
// HARDWARE: screws as above (none with PI_PINS); VHB tape ~ 90 × 50 mm;
// optional 25 mm Velcro strap.
//
// PRINTING: set one RENDER_* flag true (the other false) and export.
//   - Tray: base down, with TREE supports "on build plate only" — they
//     are needed only under the shallow curved underside. PETG preferred.
//   - Cover: roof down, no supports (the port windows' lower edges are
//     bridges of 25 mm or less). PETG preferred.

$fn = 180;

RENDER_TRAY  = true;
RENDER_COVER = false;
PI_PINS      = false;

/* Telescope tube */
tube_od          = 237;     // Apertura AD8: measured 744 mm round / π

/* Raspberry Pi 4 / 5 — same board outline and hole pattern */
pi_length        = 85;
pi_width         = 56;
pi_hole_x        = [3.5, 61.5];   // from the board's corner
pi_hole_y        = [3.5, 52.5];
pi_hole_dia      = 2.7;     // mounting holes (Pi mechanical drawing)
pcb_thickness    = 1.5;     // Pi 4 / 5 are 1.4–1.6

/* Tray */
margin           = 5;       // plate beyond the board, each side (Y)
floor_thickness  = 3;       // at the centre line
standoff_height  = 6;       // clears the microSD and the Pi 4's underside parts
standoff_dia     = 6;
pilot_dia        = 2.2;     // M2.5 self-tap
pilot_depth      = 7;
strap_width      = 27;      // slot for a 25 mm strap
strap_slot       = 4;       // slot size along the tube
strap_end        = 4;       // plate beyond each slot

/* Pins (PI_PINS) */
pin_clearance    = 0.15;    // per side: slips in, and thin CA wicks into the gap
pin_dia          = pi_hole_dia - 2 * pin_clearance;   // 2.4
pin_protrusion   = 1.0;     // above the board's top face
pin_chamfer      = 0.4;     // 45° tip chamfer

/* Cover */
cover_wall       = 1.7;     // 4 lines at 0.42
cover_roof       = 1.6;
cover_side_gap   = 0.2;     // skirt to tray side, per side
cover_end_gap    = 0.5;     // end wall to board edge
cover_headroom   = 18;      // board top to roof: clears the Ethernet jack
                            // (~13.5) and a Pi 5 Active Cooler with air
                            // over its fan
skirt_tube_gap   = 0.8;     // skirt bottom above the tube (plus the tape)
snap_depth       = 0.6;     // tray pocket depth; the bead is 0.1 shallower
snap_len         = 12;      // pocket length; the bead is 1 mm shorter
snap_x           = [-20, 20];   // pocket centres along the tube
snap_z           = -0.5;    // pocket centre height
// Port windows on the USB-C side, along the board from its SD-card end:
// USB-C at 11.2, micro-HDMI at 26 and 39.5, Pi 4 audio at 54
port_windows     = [[4, 19], [21, 46], [48, 60]];
port_below_pcb   = 2;       // windows start this far under the board
port_above_pcb   = 7;       // ... and end this far over its top face
sd_slot_width    = 22;      // microSD slot in the end wall, centred
vent_x           = [-20, 12];   // vent slot range along the tube
vent_y           = [-16, 22];   // across (−Y is the USB-C side)
vent_slot        = 2;
vent_pitch       = 4;

// ============================================================
// DERIVED
// ============================================================

tube_r      = tube_od / 2;
tray_width  = pi_width + 2 * margin;
tray_length = pi_length + 2 * (strap_end + strap_slot + 3);
edge_sag    = tube_r - sqrt(tube_r * tube_r - (tray_width / 2) * (tray_width / 2));

pcb_bottom_z = floor_thickness + standoff_height;
pcb_top_z    = pcb_bottom_z + pcb_thickness;

cover_in_y   = tray_width / 2 + cover_side_gap;           // skirt inner face
cover_out_y  = cover_in_y + cover_wall;
cover_in_x   = pi_length / 2 + cover_end_gap;             // end wall inner face
cover_out_x  = cover_in_x + cover_wall;
roof_z       = pcb_top_z + cover_headroom;                // roof underside
skirt_z      = sqrt(tube_r * tube_r - cover_in_y * cover_in_y) - tube_r
               + skirt_tube_gap;                           // skirt bottom
slot_inner_x = tray_length / 2 - strap_end - strap_slot;  // strap slot's inner edge

assert(strap_width < tray_width - 6, "strap slot too wide for the tray");
assert(pin_dia >= 2, "pins too thin to print and survive handling");
assert(cover_out_x < slot_inner_x, "cover end wall would cover the strap slots");
assert(snap_z - snap_depth > skirt_z + 1, "snap pockets below the skirt");
assert(snap_z + snap_depth < floor_thickness - 1, "snap pockets above the tray side");

// ============================================================
// TRAY — X along the tube, Y across, Z away from it; tube top at Z = 0
// ============================================================

module pi45_tray() {
    difference() {
        union() {
            translate([-tray_length / 2, -tray_width / 2, -edge_sag - 1])
                _rounded_block(tray_length, tray_width,
                               floor_thickness + edge_sag + 1, 4);
            for (hx = pi_hole_x, hy = pi_hole_y)
                translate([hx - pi_length / 2, hy - pi_width / 2, floor_thickness - 0.01]) {
                    cylinder(d = standoff_dia, h = standoff_height + 0.01, $fn = 48);
                    if (PI_PINS)
                        translate([0, 0, standoff_height]) _pin();
                }
        }

        // Tube
        translate([-tray_length, 0, -tube_r])
            rotate([0, 90, 0])
                cylinder(r = tube_r, h = 2 * tray_length);

        // Pilots
        if (!PI_PINS)
            for (hx = pi_hole_x, hy = pi_hole_y)
                translate([hx - pi_length / 2, hy - pi_width / 2,
                           pcb_bottom_z - pilot_depth])
                    cylinder(d = pilot_dia, h = pilot_depth + 1, $fn = 24);

        // Strap slots, one at each end
        for (s = [-1, 1])
            translate([s * (tray_length / 2 - strap_end - strap_slot / 2) - strap_slot / 2,
                       -strap_width / 2, -edge_sag - 2])
                cube([strap_slot, strap_width, floor_thickness + edge_sag + 4]);

        // Snap pockets for the cover's beads, in both long sides
        for (s = [-1, 1], x = snap_x)
            translate([x, s * tray_width / 2, snap_z])
                _snap_prism(snap_len, snap_depth + 0.01, s);
    }
}

module _pin() {
    pin_h = pcb_thickness + pin_protrusion;
    cylinder(d = pin_dia, h = pin_h - pin_chamfer + 0.01, $fn = 24);
    translate([0, 0, pin_h - pin_chamfer])
        cylinder(d1 = pin_dia, d2 = pin_dia - 2 * pin_chamfer,
                 h = pin_chamfer, $fn = 24);
}

// Triangular (45°) ridge along X, centred on the origin, pointing
// toward −s·Y from the plane Y = 0 with the given depth.
module _snap_prism(len, depth, s) {
    rotate([90, 0, 90])
        linear_extrude(len, center = true)
            polygon([[0, -depth], [-s * depth, 0], [0, depth]]);
}

module _rounded_block(l, w, h, r) {
    hull()
        for (x = [r, l - r], y = [r, w - r])
            translate([x, y, 0]) cylinder(r = r, h = h, $fn = 32);
}

// ============================================================
// COVER — in the tray's frame (as fitted)
// ============================================================

module pi45_cover() {
    board_x0 = -pi_length / 2;   // board's SD-card end
    difference() {
        translate([-cover_out_x, -cover_out_y, skirt_z])
            cube([2 * cover_out_x, 2 * cover_out_y, roof_z + cover_roof - skirt_z]);

        // Inside, open at the USB / Ethernet end (+X)
        translate([-cover_in_x, -cover_in_y, skirt_z - 1])
            cube([cover_in_x + cover_out_x + 1, 2 * cover_in_y, roof_z - skirt_z + 1]);
        // End walls stop at the tray's top face; only the skirts reach down
        translate([-cover_out_x - 1, -cover_in_y, skirt_z - 1])
            cube([2 * cover_out_x + 2, 2 * cover_in_y, floor_thickness - skirt_z + 1]);
        // Open end, keeping a post at each corner outside the board's width
        translate([cover_in_x - 1, -pi_width / 2 - 0.5, floor_thickness - 1])
            cube([cover_wall + 2, pi_width + 1, roof_z - floor_thickness + 1]);

        // Port windows in the −Y side
        for (w = port_windows)
            translate([board_x0 + w[0], -cover_out_y - 1, pcb_bottom_z - port_below_pcb])
                cube([w[1] - w[0], cover_wall + 2,
                      port_below_pcb + pcb_thickness + port_above_pcb]);

        // microSD slot in the −X end wall, open at the bottom
        translate([-cover_out_x - 1, -sd_slot_width / 2, floor_thickness - 1])
            cube([cover_wall + 2, sd_slot_width, pcb_top_z + 1 - floor_thickness + 1]);

        // Roof vents
        for (x = [vent_x[0] : vent_pitch : vent_x[1]])
            translate([x - vent_slot / 2, vent_y[0], roof_z - 1])
                cube([vent_slot, vent_y[1] - vent_y[0], cover_roof + 2]);
    }

    // Snap beads on the skirts' inner faces
    for (s = [-1, 1], x = snap_x)
        translate([x, s * (cover_in_y + 0.01), snap_z])
            _snap_prism(snap_len - 1, cover_side_gap + snap_depth - 0.1 + 0.01, s);
}

// ============================================================
// RENDER
// ============================================================

if (RENDER_TRAY && !RENDER_COVER)
    // Print orientation: lowest point (the curved edges) on the bed
    translate([0, 0, edge_sag]) pi45_tray();
else if (RENDER_COVER && !RENDER_TRAY)
    // Print orientation: roof on the bed
    translate([0, 0, roof_z + cover_roof]) rotate([180, 0, 0]) pi45_cover();
else {
    pi45_tray();
    if (RENDER_COVER) %pi45_cover();
}

// Board outline, preview only
if ($preview && RENDER_TRAY)
    %translate([-pi_length / 2, -pi_width / 2,
                (RENDER_COVER ? 0 : edge_sag) + pcb_bottom_z])
        cube([pi_length, pi_width, pcb_thickness]);
