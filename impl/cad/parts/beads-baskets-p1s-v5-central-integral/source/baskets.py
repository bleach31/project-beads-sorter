"""Printable P1S basket parts. Millimetres; common table plane is Z=0.

Importing this module does not build or export anything. ``build()`` returns
Manifolds, suggested printing poses, an assembly plan, and interface metadata.
The companion build/export script owns all user-facing output paths.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import cos, sin, radians, degrees, atan2, ceil, pi
from pathlib import Path
import sys

_WORK = Path(__file__).resolve().parent.parent
if str(_WORK / "cad-libs") not in sys.path:
    sys.path.insert(0, str(_WORK / "cad-libs"))

import numpy as np
import manifold3d as md
from shapely.geometry import Polygon, Point, box as polygon_box
from shapely.geometry.polygon import orient
from shapely import affinity

M = md.Manifold


@dataclass(frozen=True)
class Parameters:
    inner_radius: float = 90.0
    outer_radius: float = 175.0
    height: float = 30.0
    floor: float = 2.0
    wall: float = 2.2
    side_inset: float = 0.4
    lid_clearance: float = 0.3
    lid_roof: float = 2.0
    lid_skirt: float = 1.2
    lid_engagement: float = 4.0
    flexible_finger_skin: float = 0.7
    nominal_finger_interference: float = 0.08
    central_radius: float = 87.5
    peg_radius_from_ring: float = 181.0
    peg_tangent_offset: float = 4.5
    peg_neck_radius: float = 2.5
    peg_head_radius: float = 3.5
    connector_clearance: float = 0.3
    receiver_radius_from_ring: float = 97.0
    receiver_boss_radius_27: float = 5.5
    receiver_boss_radius_90: float = 6.5
    receiver_slot_width_27: float = 4.4
    receiver_slot_width_90: float = 5.8
    receiver_slot_extra_length: float = 2.2
    receiver_floor_z: float = 24.5
    joint_height: float = 22.0
    joint_clearance: float = 0.35
    joint_entry_relief: float = 0.25
    joint_entry_depth: float = 0.65
    central_joint_height: float = 21.0
    central_joint_offset_deg: float = -8.8
    central_lower_radius: float = 81.5
    central_flare_start_z: float = 19.0
    central_flare_end_z: float = 25.0


def _circle(radius, center=(0, 0), resolution=96):
    return Point(center).buffer(radius, quad_segs=max(12, int(resolution / 4)))


def _rounded_box(x0, y0, x1, y1, radius=1.0):
    return polygon_box(x0 + radius, y0 + radius,
                       x1 - radius, y1 - radius).buffer(radius, quad_segs=8)


def _cross_section(p):
    if p.is_empty or p.geom_type != "Polygon":
        raise ValueError("Expected one nonempty 2D polygon")
    p = orient(p, sign=1)
    return md.CrossSection([np.asarray(p.exterior.coords)[:-1]] +
                           [np.asarray(i.coords)[:-1] for i in p.interiors])


def _extrude(p, z0, z1):
    if z1 <= z0:
        raise ValueError("Positive extrusion height required")
    if p.geom_type == "MultiPolygon":
        result = M()
        for q in p.geoms:
            result = result + _extrude(q, z0, z1)
        return result
    return M.extrude(_cross_section(p), z1 - z0).translate([0, 0, z0])


def _cylinder(radius, z0, z1, x=0, y=0, segments=64):
    return M.cylinder(z1 - z0, radius, circular_segments=segments).translate([x, y, z0])


def _rotate(m, angle):
    return m.rotate([0, 0, angle])


def _rotate_polygon(p, angle):
    return affinity.rotate(p, angle, origin=(0, 0))


def _halfplane(angle, inward_sign, inset, extent=1000):
    a = radians(angle)
    e = np.array([cos(a), sin(a)])
    n = inward_sign * np.array([-sin(a), cos(a)])
    return Polygon([-extent * e + inset * n, extent * e + inset * n,
                    extent * e + extent * n, -extent * e + extent * n])


def sector_outline(angle_deg, start_deg, p=Parameters()):
    """Annular sector with closed, inset sides, preserving nominal radii."""
    end_deg = start_deg + angle_deg
    a = np.radians(np.linspace(start_deg, end_deg,
                               max(40, ceil(angle_deg / 0.3) + 1)))
    out = np.column_stack((p.outer_radius * np.cos(a), p.outer_radius * np.sin(a)))
    inn = np.column_stack((p.inner_radius * np.cos(a[::-1]),
                           p.inner_radius * np.sin(a[::-1])))
    shape = Polygon(np.vstack((out, inn)))
    shape = shape.intersection(_halfplane(start_deg, 1, p.side_inset))
    shape = shape.intersection(_halfplane(end_deg, -1, p.side_inset))
    # Small plan corner radii, still entirely inside the nominal sector.
    return shape.buffer(-0.65).buffer(0.65, quad_segs=6)


def _hull_between(bottom_polygon, bottom_z, top_polygon, top_z):
    points = []
    for poly, z in ((bottom_polygon, bottom_z), (top_polygon, top_z)):
        points.extend([[x, y, z] for x, y in np.asarray(poly.exterior.coords)[:-1]])
    return M.hull_points(np.asarray(points, dtype=float))


def _hull_sections(sections):
    """One hull instead of overlapping hull/extrusion outlines.

    Keeping the transition in a single hull avoids near-coincident edges from
    independently triangulated faces collapsing during STL float32 export.
    """
    points = []
    for poly, z in sections:
        points.extend([[x, y, z] for x, y in np.asarray(poly.exterior.coords)[:-1]])
    return M.hull_points(np.asarray(points, dtype=float))


def _peg(x, y, base_z=18.0, p=Parameters()):
    """Support shoulder 2 mm, 3.6 mm neck, and a chamfered capture head."""
    shoulder = _cylinder(p.peg_head_radius, base_z, base_z + 2.0, x, y)
    neck = _cylinder(p.peg_neck_radius, base_z + 1.95, base_z + 5.65, x, y)
    # 45 degree underside avoids an unsupported flat overhang on the bin print.
    head_ramp = M.cylinder(1.0, p.peg_neck_radius, p.peg_head_radius,
                           circular_segments=64).translate([x, y, base_z + 5.6])
    head_top = _cylinder(p.peg_head_radius, base_z + 6.55, base_z + 8.0, x, y)
    return shoulder + neck + head_ramp + head_top


def _ear_and_peg(side_sign, p=Parameters()):
    """One joint-local ear; +Y belongs to the counterclockwise bin."""
    y = side_sign * p.peg_tangent_offset
    top = _rounded_box(173.0, y - 3.7, 185.0, y + 3.7, 0.8)
    foot = _rounded_box(173.0, y - 2.7, 174.5, y + 2.7, 0.3)
    ear = _hull_sections([(foot, 4.0), (top, 16.0), (top, 18.0)])
    return ear + _peg(p.peg_radius_from_ring, y, 18.0, p)


def _male_joint_profiles():
    """Thick T tongue outside the annular wall; no elastic snap fingers.

    Joint local X is radial, +Y is the following basket. The negative-Y
    basket carries the tongue; the positive-Y basket carries the open socket.
    Each convex component can be chamfered without closing the T undercut.
    """
    anchor = _rounded_box(172.9, -8.2, 182.5, -2.6, 0.8)
    neck = _rounded_box(178.1, -5.5, 182.5, 4.6, 0.55)
    head = _rounded_box(176.3, 4.1, 184.3, 7.7, 0.55)
    shoulder = Polygon([(178.1, 2.7), (182.5, 2.7),
                        (184.3, 4.7), (176.3, 4.7)])
    return [anchor, neck, shoulder, head]


def _male_joint(p=Parameters()):
    result = M()
    for profile in _male_joint_profiles():
        small = profile.buffer(-p.joint_entry_relief, join_style="round")
        # A single convex hull per primitive avoids coincident horizontal
        # seam faces when writing the mesh in STL's float32 coordinates.
        result = result + _hull_sections([
            (small, 0), (profile, p.joint_entry_depth),
            (profile, p.joint_height - p.joint_entry_depth),
            (small, p.joint_height)])
    return result


def _female_joint(p=Parameters()):
    outer = _rounded_box(173.1, -0.05, 187.3, 11.35, 0.65)
    channel = Polygon()
    # No floor, end stop, or roof in this T slot. The open bottom is required
    # when the final basket is lowered between two already-connected neighbors.
    for profile in _male_joint_profiles()[1:]:
        nominal = profile.buffer(p.joint_clearance, join_style="round")
        channel = channel.union(nominal)
    # A single through extrusion has no coincident 3D cutter seams. Lead-in
    # chamfers are on both ends of the male key; the socket remains straight.
    return _extrude(outer.difference(channel), 0, p.joint_height)


def build_joint_coupons(p=Parameters()):
    """Two hand-sized samples, never required as assembly hardware."""
    male_back = _extrude(_rounded_box(164.0, -11.0, 175.0, -0.7, 0.8),
                        0, p.joint_height)
    female_back = _extrude(_rounded_box(164.0, 0.7, 175.0, 14.0, 0.8),
                          0, p.joint_height)
    return male_back + _male_joint(p), female_back + _female_joint(p)


def _receiver(angle_deg, is_key, p=Parameters()):
    rb = p.receiver_boss_radius_90 if is_key else p.receiver_boss_radius_27
    width = p.receiver_slot_width_90 if is_key else p.receiver_slot_width_27
    r = p.receiver_radius_from_ring
    boss_poly = _circle(rb, (r, 0), resolution=96)
    foot_poly = _circle(0.9, (91.1, 0), resolution=32)
    body = _hull_sections([(foot_poly, 7.5), (boss_poly, 20.0), (boss_poly, p.height)])
    half_extra = p.receiver_slot_extra_length / 2
    slot = _circle(width / 2, (r - half_extra, 0)).union(
           _circle(width / 2, (r + half_extra, 0))).convex_hull
    body = body - _extrude(slot, p.receiver_floor_z, p.height + 0.3)
    return _rotate(body, angle_deg), _rotate_polygon(boss_poly, angle_deg), {
        "center_radius_mm": r,
        "center_angle_deg": angle_deg,
        "boss_diameter_mm": 2 * rb,
        "boss_top_z_mm": p.height,
        "slot_overall_radial_length_mm": width + p.receiver_slot_extra_length,
        "slot_tangential_width_mm": width,
        "blind_slot_floor_z_mm": p.receiver_floor_z,
        "mating_round_pin_diameter_mm": 5.2 if is_key else 3.8,
        "mating_pin_bottom_z_mm": 26.8,
        "mating_pin_floor_clearance_mm": 26.8 - p.receiver_floor_z,
        "mating_tongue_underside_z_mm": 30.8,
        "boss_to_tongue_clearance_mm": 0.8,
        "keyed_for_90_degree_bin": is_key,
    }


def _xz_prism(points_xz, y0, y1):
    return _extrude(Polygon(points_xz), 0, y1 - y0).rotate([90, 0, 0]).translate([0, y1, 0])


def _add_curved_friction_finger(lid, plug_outer_radius, contact_angle_deg,
                                skirt_bottom, roof_bottom, p=Parameters()):
    """Slitted 0.7 mm plug finger with a small, ramped interference bump.

    Nominal interference is 0.08 mm; real retention depends on printed size,
    material and wear. The associated small coupon must be tried first.
    """
    r = plug_outer_radius
    # Thin only the central finger, retaining a 0.6 mm connection to the roof.
    da = degrees(5.0 / r)
    a = np.radians(np.linspace(-da, da, 20))
    ro, ri = r - p.flexible_finger_skin, r - p.lid_skirt - 0.6
    strip = Polygon(np.vstack((np.column_stack((ro * np.cos(a), ro * np.sin(a))),
                                np.column_stack((ri * np.cos(a[::-1]), ri * np.sin(a[::-1]))))))
    cutter = _extrude(strip, skirt_bottom - 0.05, roof_bottom - 0.6)
    for y in (-5.0, 5.0):
        cutter = cutter + _extrude(polygon_box(r - 1.9, y - 0.35,
                                             r + 0.7, y + 0.35),
                                    skirt_bottom - 0.05, roof_bottom - 0.6)
    bump_tip = r + p.lid_clearance + p.nominal_finger_interference
    bump = _xz_prism([(r - 0.15, skirt_bottom + 0.55),
                      (bump_tip, skirt_bottom + 1.85),
                      (r - 0.15, skirt_bottom + 3.15)], -2, 2)
    return (lid - _rotate(cutter, contact_angle_deg)) + _rotate(bump, contact_angle_deg)


def _sector_lid(outline, cavity, boss_outline, angle_deg, start_deg, p=Parameters()):
    clear = p.lid_clearance
    # The roof sits on the rim; a local recess clears the docking boss by 0.3.
    roof_poly = outline
    mid = start_deg + angle_deg / 2
    # Flat removal tab, at the same Z as the roof, prints against the build plate.
    tab = _rotate_polygon(_rounded_box(p.outer_radius - 3.0, -6.0,
                                       p.outer_radius + 2.3, 6.0, 1.0), mid)
    roof_poly = roof_poly.union(tab)
    lid = _extrude(roof_poly, p.height, p.height + p.lid_roof)
    boss_keepout = boss_outline.buffer(clear, quad_segs=12)
    # Give the shallow roof pocket 0.05 mm more lateral relief than the skirt.
    # Coincident curved pocket/skirt boundaries otherwise create microscopic
    # Boolean slivers that collapse on float32 STL export.
    lid = lid - _extrude(boss_keepout.buffer(0.05, quad_segs=12),
                        p.height - 0.1, p.height + clear)
    allowed = cavity.buffer(-clear, join_style="round").difference(boss_keepout)
    skirt_region = allowed.difference(allowed.buffer(-p.lid_skirt, join_style="round"))
    z0 = p.height - p.lid_engagement
    lid = lid + _extrude(skirt_region, z0, p.height)
    finger_angles = ([mid - 4.5, mid + 4.5] if angle_deg < 45 else
                     [start_deg + 20, mid, start_deg + angle_deg - 20])
    for a in finger_angles:
        lid = _add_curved_friction_finger(lid,
                p.outer_radius - p.wall - clear, a, z0, p.height, p)
    return lid, {
        "roof_bottom_z_mm": p.height,
        "roof_top_z_mm": p.height + p.lid_roof,
        "skirt_bottom_z_mm": z0,
        "skirt_clearance_per_side_mm": clear,
        "skirt_wall_mm": p.lid_skirt,
        "finger_skin_mm": p.flexible_finger_skin,
        "finger_nominal_interference_mm": p.nominal_finger_interference,
        "finger_angles_deg": finger_angles,
        "boss_local_roof_underside_clearance_mm": clear,
        "removal_tab_extra_radius_mm": 2.3,
        "retention": "Trial compliant friction fingers; not a positive transport latch",
        "print_rotation_xyz_deg": [180, 0, 0],
    }



def _central_key_profiles():
    # Radial T tongue; short wide root, 4.4 mm neck, 7.6 mm head.
    root = _rounded_box(80.0, -3.4, 83.7, 3.4, 0.6)
    neck = _rounded_box(81.0, -2.2, 87.2, 2.2, 0.45)
    head = _rounded_box(86.4, -3.8, 89.5, 3.8, 0.5)
    shoulder = Polygon([(85.0,-2.2),(85.0,2.2),(87.2,3.8),(87.2,-3.8)])
    return [root, neck, shoulder, head]


def _central_key(p=Parameters()):
    result = M()
    for q in _central_key_profiles():
        small = q.buffer(-p.joint_entry_relief, join_style='round')
        result = result + _hull_sections([(small,0),(q,p.joint_entry_depth),
            (q,p.central_joint_height-p.joint_entry_depth),(small,p.central_joint_height)])
    return result


def _central_socket_profile(p=Parameters()):
    outer = _rounded_box(84.0, -6.2, 92.4, 6.2, 0.65)
    channel = Polygon()
    for q in _central_key_profiles()[1:]:
        channel = channel.union(q.buffer(p.joint_clearance,join_style='round'))
    return outer, channel


def _add_central_socket(body,angle,p=Parameters()):
    outer,channel=_central_socket_profile(p)
    # Cut after union: the blind radial back remains thick and the bead cavity
    # stays sealed even where the channel enters the old inner basket wall.
    result=body + _rotate(_extrude(outer,0,p.central_joint_height),angle)
    return result - _rotate(_extrude(channel,-0.1,p.central_joint_height+0.001),angle)


def central_key_angles(p=Parameters()):
    # Same 3 broadly spaced basket positions used for machine location, with
    # an angular offset so the new empty sockets clear the unchanged machine.
    return [158.0+p.central_joint_offset_deg,297.5+p.central_joint_offset_deg,
            45.5+p.central_joint_offset_deg]


def build_sector_bin(angle_deg=27.0, start_deg=-13.5, p=Parameters()):
    outline = sector_outline(angle_deg, start_deg, p)
    cavity = outline.buffer(-p.wall, join_style="round")
    body = _extrude(outline, 0, p.height) - _extrude(cavity, p.floor, p.height + 0.5)
    body = body + _rotate(_female_joint(p), start_deg)
    body = body + _rotate(_male_joint(p), start_deg + angle_deg)
    receiver, boss_outline, receiver_meta = _receiver(start_deg + angle_deg / 2,
                                                       angle_deg > 45, p)
    body = body + receiver
    socket_angle=start_deg+angle_deg/2+p.central_joint_offset_deg
    body = _add_central_socket(body,socket_angle,p)
    lid, lid_meta = _sector_lid(outline, cavity, boss_outline, angle_deg, start_deg, p)
    return body, lid, {
        "angle_deg": angle_deg,
        "start_angle_deg": start_deg,
        "end_angle_deg": start_deg + angle_deg,
        "mid_angle_deg": start_deg + angle_deg / 2,
        "central_socket_angle_deg": socket_angle,
        "cavity_nominal_volume_without_receiver_ml": cavity.area * (p.height - p.floor) / 1000,
        "receiver": receiver_meta,
        "lid": lid_meta,
    }


def build_central_case(p=Parameters()):
    ro = p.central_radius
    ri = ro - p.wall
    low=p.central_lower_radius
    z0=p.central_flare_start_z
    z1=p.central_flare_end_z
    slope=(ro-low)/(z1-z0)
    # Offset the conical inside face along its normal: the wall never becomes
    # thinner than 2.2 mm. Its upper junction is below the old lid at Z26.
    offset=p.wall*(1+slope*slope)**0.5
    delay=(offset-p.wall)/slope
    outside=(_cylinder(low,0,z0,segments=360) +
        M.cylinder(z1-z0,low,ro,circular_segments=360).translate([0,0,z0]) +
        _cylinder(ro,z1,p.height,segments=360))
    cavity=(_cylinder(low-p.wall,p.floor,z0+delay,segments=360) +
        M.cylinder(z1-z0,low-p.wall,ri,circular_segments=360).translate([0,0,z0+delay]) +
        _cylinder(ri,z1+delay,p.height+.5,segments=360))
    body=outside-cavity
    for a in central_key_angles(p):
        body=body+_rotate(_central_key(p),a)
    # Outer-only thumbnail recesses leave an intact inner wall and expose the lid.
    for a in (0, 180):
        notch = _extrude(_rounded_box(ro - 0.95, -7, ro + 2, 7, 0.7),
                          p.height - 2.2, p.height + 0.1)
        body = body - _rotate(notch, a)
    roof = _cylinder(ro, p.height, p.height + p.lid_roof, segments=360)
    plug_r = ri - p.lid_clearance
    skirt = _cylinder(plug_r, p.height - p.lid_engagement, p.height + 0.02,
                       segments=360) - _cylinder(plug_r - p.lid_skirt,
                       p.height - p.lid_engagement - 0.05, p.height + 0.1, segments=360)
    lid = roof + skirt
    for a in (0, 90, 180, 270):
        lid = _add_curved_friction_finger(lid, plug_r, a,
                   p.height - p.lid_engagement, p.height, p)
    return body, lid, {
        "outer_diameter_mm": 2 * ro,
        "inner_diameter_mm": 2 * ri,
        "lower_body_outer_diameter_mm": 2*low,
        "lower_body_inner_diameter_mm": 2*(low-p.wall),
        "flare_outer_z_range_mm": [z0,z1],
        "flare_inner_z_range_mm": [z0+delay,z1+delay],
        "body_and_flare_nominal_wall_mm": p.wall,
        "key_angles_world_deg": central_key_angles(p),
        "key_neck_width_mm": 4.4,
        "key_head_width_mm": 7.6,
        "key_engagement_height_mm": p.central_joint_height,
        "socket_cheek_nominal_thickness_mm": 2.05,
        "joint_clearance_per_side_mm": p.joint_clearance,
        "integral_connection_count": 3,
        "separate_connecting_parts": 0,
        "vertical_latch": False,
        "lid_preserved": True,
        "nominal_capacity_ml": (pi*(low-p.wall)**2*(z0+delay-p.floor)+
            pi*(z1-z0)/3*((low-p.wall)**2+(low-p.wall)*ri+ri**2)+
            pi*ri**2*(p.height-z1-delay))/1000,
        "ring_inner_wall_clearance_mm": p.inner_radius - ro,
        "lid_clearance_per_side_mm": p.lid_clearance,
        "lid_engagement_mm": p.lid_engagement,
        "grip": "Two shallow external thumbnail recesses; no raised top handle",
        "receiver_intrusion_into_center": False,
    }


def build_bridge_clip(p=Parameters()):
    """Joint-local print geometry: origin at peg radial centre, bottom Z=0.

    Installed transform: rotate Z by boundary angle, then translate to radius
    181 and Z20.3. Slide in from outside (negative local X travel); remove in +X.
    """
    clear = p.connector_clearance
    rslot = p.peg_neck_radius + clear
    outline = _rounded_box(-3.5, -9.0, 5.0, 9.0, 0.7)
    for y in (-p.peg_tangent_offset, p.peg_tangent_offset):
        slot = _circle(rslot, (0, y), resolution=64).union(
               polygon_box(-4.5, y - rslot, 0, y + rslot))
        outline = outline.difference(slot)
    return _extrude(outline, 0, 3.0)


def build_connector_coupon(p=Parameters()):
    base = _extrude(_rounded_box(-4.2, -9.0, 4.2, 9.0, 0.8), 0, 3)
    for y in (-p.peg_tangent_offset, p.peg_tangent_offset):
        base = base + _peg(0, y, 3, p)
    return base


def build_lid_coupon(p=Parameters()):
    """Small rectangular cup and lid using the production finger dimensions."""
    height = 12.0
    outer = _rounded_box(-13, -11, 13, 11, 1.5)
    inner = outer.buffer(-p.wall, join_style="round")
    cup = _extrude(outer, 0, height) - _extrude(inner, p.floor, height + 0.5)
    allowed = inner.buffer(-p.lid_clearance, join_style="round")
    ring = allowed.difference(allowed.buffer(-p.lid_skirt, join_style="round"))
    lid = _extrude(outer, height, height + p.lid_roof) + _extrude(
           ring, height - p.lid_engagement, height + 0.02)
    # A flat-side equivalent of the 175 mm-radius production finger.
    x = 13 - p.wall - p.lid_clearance
    for angle in (0, 180):
        cutter = _extrude(polygon_box(x - 1.9, -5.0,
                                     x - p.flexible_finger_skin, 5.0), 7.95, 11.4)
        for y in (-5.0, 5.0):
            cutter = cutter + _extrude(polygon_box(x - 1.9, y - 0.35,
                                                   x + 0.7, y + 0.35), 7.95, 11.4)
        tip = x + p.lid_clearance + p.nominal_finger_interference
        bump = _xz_prism([(x - 0.15, 8.55), (tip, 9.85), (x - 0.15, 11.15)], -2, 2)
        lid = lid - _rotate(cutter, angle) + _rotate(bump, angle)
    # Flat pull tab on the other axis remains against the bed when roof-down.
    tab = _extrude(_rounded_box(-4, 8, 4, 13, 0.8), height, height + p.lid_roof)
    lid = lid + tab
    return cup, lid


def print_pose(part, rotation_xyz=(0, 0, 0)):
    """Return model centred in XY with its lowest point on the print bed."""
    s = part.rotate(rotation_xyz)
    b = s.bounding_box()
    return s.translate([-(b[0] + b[3]) / 2, -(b[1] + b[4]) / 2, -b[2]])


def interface_metadata(p=Parameters()):
    return {
        "units": "mm and degrees",
        "table_plane_z_mm": 0,
        "ring_inner_radius_mm": p.inner_radius,
        "ring_bin_outer_radius_mm": p.outer_radius,
        "bin_wall_height_mm": p.height,
        "radial_joint_gap_mm": 2 * p.side_inset,
        "all_bin_floors_closed": True,
        "each_side_ear": {
            "joint_local_coordinates": "X radially outward, Y counterclockwise; origin at ring centre",
            "positive_side_bin_peg_xy_mm": [p.peg_radius_from_ring, p.peg_tangent_offset],
            "negative_side_bin_peg_xy_mm": [p.peg_radius_from_ring, -p.peg_tangent_offset],
            "peg_neck_diameter_mm": 2 * p.peg_neck_radius,
            "peg_capture_diameter_mm": 2 * p.peg_head_radius,
            "support_ear_top_z_mm": 18,
            "lower_shoulder_top_z_mm": 20,
            "upper_head_start_z_mm": 23.6,
            "upper_head_top_z_mm": 26,
        },
        "bridge_clip": {
            "part_origin": "radial peg centre, bottom of bridge",
            "installed_radius_mm": p.peg_radius_from_ring,
            "installed_bottom_z_mm": 20.3,
            "installed_top_z_mm": 23.3,
            "slot_width_mm": 2 * (p.peg_neck_radius + p.connector_clearance),
            "slot_clearance_per_side_mm": p.connector_clearance,
            "axial_clearance_each_side_mm": 0.3,
            "assembled_radial_extents_mm": [177.5, 186.0],
            "joint_local_tangential_extents_mm": [-9, 9],
            "installation": "Slide radially inward from outside after bins are positioned",
            "removal": "Slide radially outward; no top-only insertion",
            "positive_vertical_capture": True,
            "positive_radial_latch": False,
            "warning": "Slip clip can migrate outward if bumped; assembled ring is not a carry handle",
        },
        "connector_coupon": {
            "clip_installed_transform_translation_xyz_mm": [0, 0, 5.3],
            "uses_same_bridge_clip": True,
        },
        "storage": {
            "sorter_dock_removed_before_lids": True,
            "central_case_outside_diameter_mm": 2 * p.central_radius,
            "central_case_is_storage_only": True,
        },
        "trial_fit_notes": [
            "Print connector and lid coupons before large parts",
            "0.30 mm nominal clearance per side does not guarantee printed clearance",
            "Compliant lid fingers require physical fit and fatigue evaluation",
            "Lids are not certified leakproof or transport latches",
            "Clips align floor-standing bins; do not carry loaded ring by one bin",
        ],
    }


def _assembly_plan():
    # User-approved placement: 90-degree key bin 113..203 degrees, then ten 27-degree bins.
    assembly = []
    for i in range(10):
        angle = 216.5 + i * 27
        for part in ("bin_27", "lid_27"):
            assembly.append({"name": f"{part}_{i + 1:02d}", "part": part,
                             "rotation_xyz_deg": [0, 0, angle], "translation_xyz_mm": [0, 0, 0]})
    for part in ("bin_90", "lid_90"):
        assembly.append({"name": part, "part": part,
                         "rotation_xyz_deg": [0, 0, 113], "translation_xyz_mm": [0, 0, 0]})
    for part in ("central_case", "central_lid"):
        assembly.append({"name": part, "part": part,
                         "rotation_xyz_deg": [0, 0, 0], "translation_xyz_mm": [0, 0, 0]})
    return assembly


def build(p=Parameters()):
    bin27, lid27, meta27 = build_sector_bin(27, -13.5, p)
    bin90, lid90, meta90 = build_sector_bin(90, 0, p)
    central, central_lid, central_meta = build_central_case(p)
    cup, cup_lid = build_lid_coupon(p)
    joint_male, joint_female = build_joint_coupons(p)
    parts = {"bin_27": bin27, "lid_27": lid27,
             "bin_90": bin90, "lid_90": lid90,
             "central_case": central, "central_lid": central_lid,
             "joint_fit_male": joint_male,
             "joint_fit_female": joint_female,
             "lid_fit_cup": cup, "lid_fit_lid": cup_lid}
    rotation = {name: ([180, 0, 0] if name.startswith("lid") or name == "central_lid"
                        else [0, 0, 0]) for name in parts}
    rotation["lid_fit_cup"] = [0, 0, 0]
    print_parts = {name: print_pose(s, rotation[name]) for name, s in parts.items()}
    quantities = {"bin_27": 10, "lid_27": 10, "bin_90": 1, "lid_90": 1,
                  "central_case": 1, "central_lid": 1,
                  "joint_fit_male": 1, "joint_fit_female": 1,
                  "lid_fit_cup": 1, "lid_fit_lid": 1}
    geometry = {}
    for name, s in print_parts.items():
        b = s.bounding_box()
        size = [b[i + 3] - b[i] for i in range(3)]
        geometry[name] = {
            "print_size_xyz_mm": size,
            "volume_mm3": s.volume(),
            "surface_area_mm2": s.surface_area(),
            "number_of_solids": len(s.decompose()),
            "manifold_status": str(s.status()),
            "fits_236mm_xy_margin": max(size[:2]) <= 236,
            "quantity": quantities[name],
            "print_rotation_xyz_deg": rotation[name],
        }
    interface = interface_metadata(p)
    for obsolete in ['each_side_ear', 'bridge_clip', 'connector_coupon']:
        interface.pop(obsolete, None)
    interface['integral_joint'] = {
        'type': 'Vertical through T-slot, integral with each basket',
        'male_side': 'Sector end / clockwise basket at shared boundary',
        'female_side': 'Sector start / counterclockwise basket at shared boundary',
        'joint_z_range_mm': [0, p.joint_height],
        'neck_width_mm': 4.4, 'head_width_mm': 8.0,
        'head_thickness_mm': 3.6,
        'clearance_per_side_mm': p.joint_clearance,
        'male_end_relief_mm': p.joint_entry_relief,
        'female_entry_extra_clearance_mm': 0,
        'entry_chamfer_depth_mm': p.joint_entry_depth,
        'female_open_top_and_bottom': True,
        'separate_connecting_parts': 0,
        'installation': 'Lower a basket vertically; both ends of the socket are open so the final basket can close the ring',
        'removal': 'Lift the selected basket at least 23 mm before moving it sideways; remove sorter docking pins first',
        'vertical_latch': False,
        'function': 'Horizontal alignment of floor-standing bins; support all bases while carrying',
        'print_supports': 'None for vertical joint; 0.25 mm end relief over 0.65 mm height',
    }
    interface['trial_fit_notes'] = [
        'Optional male/female test samples reproduce the basket joints and are not assembly parts',
        'A 0.35 mm nominal clearance per side requires actual printing checks',
        'T sockets are intentionally open at both Z ends; do not add floors or stops',
        'Slide vertically without bending or snapping the tongue',
        'Support the whole ring from beneath when carrying; vertical removal is intentional',
    ]
    interface['central_integral_joint']={
        'type':'Three radial T keys on central case into basket inner-wall vertical sockets',
        'key_angles_world_deg':central_key_angles(p),
        'sockets_on_all_baskets':True,
        'socket_offset_from_basket_mid_deg':p.central_joint_offset_deg,
        'socket_z_range_mm':[0,p.central_joint_height],
        'clearance_per_side_mm':p.joint_clearance,
        'key_neck_width_mm':4.4,'key_head_width_mm':7.6,
        'socket_cheek_nominal_thickness_mm':2.05,
        'separate_connecting_parts':0,'vertical_latch':False,
        'installation':'Remove the sorter; close the basket ring; align all three keys and lower the central case vertically',
        'removal':'Lift the central case at least 22 mm before moving it sideways',
        'old_v4_baskets_compatible':False,'old_v4_lids_compatible':True,
        'print_supports':'None; vertical joints and 45 degree outer bowl flare',
        'function':'Horizontal alignment only; support the entire base when carrying'}
    interface["receiver_27"] = meta27["receiver"]
    interface["receiver_90"] = meta90["receiver"]
    return {
        "parts": parts,
        "print_parts": print_parts,
        "print_rotation_xyz_deg": rotation,
        "quantities": quantities,
        "assembly": _assembly_plan(),
        "interface": interface,
        "metadata": {"parameters": asdict(p), "bin_27": meta27, "bin_90": meta90,
                     "central_case": central_meta, "geometry": geometry},
    }


def apply_pose(part, pose):
    return part.rotate(pose.get("rotation_xyz_deg", [0, 0, 0])).translate(
                       pose.get("translation_xyz_mm", [0, 0, 0]))


