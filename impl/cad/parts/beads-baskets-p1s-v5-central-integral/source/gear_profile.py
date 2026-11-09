"""20 degree full-depth involute spur gears for the bead-sorter speed-up.

Only the planar gear perimeter is constructed here; hubs, bores and face
extrusion are deliberately left to the assembly generator.  All lengths are
millimetres and all public angle arguments are degrees unless named radians.

The involute flanks are analytical, sampled with a chord tolerance.  Below the
base circle they continue radially into an explicit tangent root fillet. This
is a printable, non-undercut root design, rather than a claim to reproduce a
particular gear-cutting rack's trochoid.  At 20 teeth and 20 degrees the standard
full-depth gear is above the usual no-undercut tooth-count limit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from math import acos, atan, atan2, ceil, cos, pi, sin, sqrt, tan
from pathlib import Path
import sys
from typing import Any

# The task's isolated dependency directory is optional when imported elsewhere.
_LIBS = Path(__file__).resolve().parent / "cad-libs"
if _LIBS.is_dir() and str(_LIBS) not in sys.path:
    sys.path.insert(0, str(_LIBS))

import numpy as np


@dataclass(frozen=True)
class GearDimensions:
    teeth: int
    module_mm: float
    pressure_angle_deg: float
    pitch_radius_mm: float
    base_radius_mm: float
    root_radius_mm: float
    outside_radius_mm: float
    tooth_thickness_at_pitch_mm: float
    tooth_thickness_reduction_mm: float
    root_fillet_radius_mm: float
    face_width_mm: float = 5.0


def dimensions(
    teeth: int,
    module: float = 0.8,
    pressure_angle_deg: float = 20.0,
    tooth_thickness_reduction: float = 0.10,
    root_fillet_radius: float = 0.16,
    face_width: float = 5.0,
) -> GearDimensions:
    """Return dimensions; use 0.10 reduction on EACH gear for 0.20 backlash.

    ``tooth_thickness_reduction`` is the full tangential thickness removed
    from one tooth at the pitch circle. Half is removed from each flank.
    """
    if teeth != int(teeth) or teeth < 18:
        raise ValueError("This unshifted, non-undercut generator requires >=18 teeth")
    if module <= 0 or not 0 < pressure_angle_deg < 45:
        raise ValueError("Invalid module or pressure angle")
    if not 0 <= tooth_thickness_reduction < pi * module / 2:
        raise ValueError("The tooth thickness reduction must leave a positive tooth")
    if root_fillet_radius < 0 or face_width <= 0:
        raise ValueError("Invalid fillet radius or face width")
    r = teeth * module / 2
    return GearDimensions(
        teeth=int(teeth),
        module_mm=module,
        pressure_angle_deg=pressure_angle_deg,
        pitch_radius_mm=r,
        base_radius_mm=r * cos(pressure_angle_deg * pi / 180),
        root_radius_mm=r - 1.25 * module,
        outside_radius_mm=r + module,
        tooth_thickness_at_pitch_mm=pi * module / 2 - tooth_thickness_reduction,
        tooth_thickness_reduction_mm=tooth_thickness_reduction,
        root_fillet_radius_mm=root_fillet_radius,
        face_width_mm=face_width,
    )


def _rotate(points: np.ndarray, angle: float) -> np.ndarray:
    c, s = cos(angle), sin(angle)
    return points @ np.array([[c, s], [-s, c]], dtype=float)


def _arc(radius: float, a0: float, a1: float, tolerance: float) -> np.ndarray:
    """Circular arc with a maximum chord sagitta, including both endpoints."""
    if radius <= 0:
        raise ValueError("Arc radius must be positive")
    max_da = 2 * acos(max(-1.0, min(1.0, 1 - tolerance / radius)))
    n = max(2, ceil(abs(a1 - a0) / max_da) + 1)
    angles = np.linspace(a0, a1, n)
    return radius * np.column_stack((np.cos(angles), np.sin(angles)))


def _involute(rb: float, parameters: np.ndarray) -> np.ndarray:
    """Canonical involute, whose tangent has angle t and polar angle t-atan(t)."""
    c, s = np.cos(parameters), np.sin(parameters)
    return rb * np.column_stack((c + parameters * s, s - parameters * c))


def gear_outline(
    teeth: int,
    module: float = 0.8,
    pressure_angle_deg: float = 20.0,
    tooth_thickness_reduction: float = 0.10,
    root_fillet_radius: float = 0.16,
    chord_tolerance: float = 0.002,
    rotation_deg: float = 0.0,
) -> np.ndarray:
    """Return an unclosed Nx2 CCW gear perimeter centred at (0, 0).

    A tooth centre is on +X at zero rotation. Pair the default 80 tooth gear
    at angle theta with the 20 tooth gear at 189 - 4*theta degrees, and put
    the latter's centre on +X at 40.0 mm. Angles differing by a tooth pitch
    are equivalent. Two gears each reduced by 0.10 mm have 0.20 mm nominal
    tangential backlash at their standard 40.0 mm centre distance.
    """
    d = dimensions(teeth, module, pressure_angle_deg,
                   tooth_thickness_reduction, root_fillet_radius)
    if not 0 < chord_tolerance <= 0.02:
        raise ValueError("Use a positive chord tolerance no larger than 0.02 mm")
    rp, rb, rr, ra = (d.pitch_radius_mm, d.base_radius_mm,
                       d.root_radius_mm, d.outside_radius_mm)
    alpha = pressure_angle_deg * pi / 180
    half_pitch_tooth = d.tooth_thickness_at_pitch_mm / (2 * rp)
    half_base_tooth = half_pitch_tooth + tan(alpha) - alpha
    t_tip = sqrt((ra / rb) ** 2 - 1)
    rf = root_fillet_radius

    # Build the lower flank from root to tip. The fillet circle is exterior
    # to the root circle and exterior to the lower flank. Its contact with
    # the root circle therefore has centre distance rr + rf.
    if rr < rb and (rf == 0 or rr * rr + 2 * rr * rf <= rb * rb):
        # The involute reaches the base before the root. A radial tangent
        # extension is exact at its base-circle endpoint (t=0).
        t_start = 0.0
        if rf:
            radial_tangent_r = sqrt(rr * rr + 2 * rr * rf)
            centre = np.array([radial_tangent_r, -rf])
            root_contact = centre * rr / (rr + rf)
            a0 = atan2(root_contact[1] - centre[1],
                       root_contact[0] - centre[0])
            fillet = _arc(rf, a0, pi / 2, chord_tolerance) + centre
            lower_root = _rotate(fillet, -half_base_tooth)
            lower_root = np.vstack((lower_root,
                                   _rotate(np.array([[rb, 0.0]]), -half_base_tooth)))
        else:
            lower_root = _rotate(np.array([[rr, 0.0], [rb, 0.0]]), -half_base_tooth)
    else:
        if rf:
            # Solve |p(t)-rf*n_left(t)| = rr+rf analytically.
            t_start = (sqrt((rr + rf) ** 2 - rb ** 2) - rf) / rb
        else:
            t_start = sqrt(max(0.0, (rr / rb) ** 2 - 1))
        p = _involute(rb, np.array([t_start]))[0]
        if rf:
            n_left = np.array([-sin(t_start), cos(t_start)])
            centre = p - rf * n_left
            root_contact = centre * rr / (rr + rf)
            a0 = atan2(root_contact[1] - centre[1],
                       root_contact[0] - centre[0])
            a1 = atan2(n_left[1], n_left[0])
            delta = (a1 - a0 + pi) % (2 * pi) - pi
            if delta > 0:
                raise ValueError("Root fillet is too large for this gear")
            lower_root = _rotate(_arc(rf, a0, a0 + delta, chord_tolerance) + centre,
                                 -half_base_tooth)
        else:
            lower_root = _rotate(p[None, :], -half_base_tooth)

    if t_start >= t_tip:
        raise ValueError("Root fillet reaches the tooth tip")
    # The tangent angle equals t; using curvature radius rb*t_tip gives a
    # conservative chord bound. At least 32 segments retain smooth flanks.
    max_dt = sqrt(8 * chord_tolerance / max(rb * t_tip, 1e-9))
    n_flank = max(33, ceil((t_tip - t_start) / max_dt) + 1)
    params = np.linspace(t_start, t_tip, n_flank)
    flank = _rotate(_involute(rb, params), -half_base_tooth)
    lower = np.vstack((lower_root, flank[1:]))
    tip_half_angle = half_base_tooth - (t_tip - atan(t_tip))
    if tip_half_angle <= 0:
        raise ValueError("The tooth tip has zero thickness")
    tip_arc = _arc(ra, -tip_half_angle, tip_half_angle, chord_tolerance)
    upper = lower[::-1] * np.array([1.0, -1.0])
    tooth = np.vstack((lower, tip_arc[1:], upper[1:]))
    upper_root_angle = atan2(upper[-1, 1], upper[-1, 0])
    pitch_angle = 2 * pi / teeth
    if 2 * upper_root_angle >= pitch_angle:
        raise ValueError("Adjacent root fillets overlap")
    gap = _arc(rr, upper_root_angle, pitch_angle - upper_root_angle,
               chord_tolerance)
    repeat = np.vstack((tooth, gap[1:-1]))
    points = np.vstack([_rotate(repeat, i * pitch_angle) for i in range(teeth)])
    if rotation_deg:
        points = _rotate(points, rotation_deg * pi / 180)
    area2 = np.sum(points[:, 0] * np.roll(points[:, 1], -1)
                   - points[:, 1] * np.roll(points[:, 0], -1))
    if area2 <= 0:
        raise ValueError("Gear perimeter orientation is not CCW")
    return points


# Readable aliases for CAD scripts that prefer an explicit descriptive name.
involute_gear_outline = gear_outline
involute_gear_polygon = gear_outline


def driven_angle_deg(driver_angle_deg: float, driver_teeth: int = 80,
                     driven_teeth: int = 20) -> float:
    """Mating phase for gears with the driven centre on the driver's +X axis."""
    return 180.0 + 180.0 / driven_teeth - driver_angle_deg * driver_teeth / driven_teeth


def validate_pair(centre_distances=(40.0, 40.1, 40.2, 40.4),
                  step_deg=0.1) -> dict[str, Any]:
    """Check real 2D polygon collisions during 0..90 degrees of driver travel."""
    from shapely.affinity import rotate, translate
    from shapely.geometry import Polygon

    large = Polygon(gear_outline(80))
    small = Polygon(gear_outline(20))
    alpha = 20 * pi / 180
    large_d, small_d = dimensions(80), dimensions(20)
    base_pitch = pi * 0.8 * cos(alpha)
    addendum_path = (sqrt(large_d.outside_radius_mm ** 2 - large_d.base_radius_mm ** 2)
                     + sqrt(small_d.outside_radius_mm ** 2 - small_d.base_radius_mm ** 2))
    nominal_ratio = (addendum_path - 40 * sin(alpha)) / base_pitch
    report: dict[str, Any] = {
        "units": "mm, degrees",
        "gear_80": asdict(large_d),
        "gear_20": asdict(small_d),
        "polygon_vertices": [len(large.exterior.coords) - 1, len(small.exterior.coords) - 1],
        "polygon_valid": [bool(large.is_valid), bool(small.is_valid)],
        "polygon_ccw": [bool(large.exterior.is_ccw), bool(small.exterior.is_ccw)],
        "nominal_tangential_backlash_mm": 0.2,
        "nominal_transverse_contact_ratio": nominal_ratio,
        "phase_rule_deg": "small = 189 - 4 * large; large center (0,0), small center (C,0)",
        "root_form": "Analytical tangent fillet; radial continuation below base circle; no rack-trochoid claim",
        "root_tip_nominal_radial_clearance_mm": 0.2,
        "test": {
            "driver_angle_start_deg": 0.0,
            "driver_angle_stop_deg": 90.0,
            "step_deg": step_deg,
            "samples_per_centre_distance": int(round(90 / step_deg)) + 1,
        },
        "centre_distance_results": [],
    }
    for centre in centre_distances:
        max_overlap = 0.0
        min_gap = float("inf")
        worst_angle = None
        intersections = 0
        for angle in np.linspace(0, 90, int(round(90 / step_deg)) + 1):
            a = rotate(large, float(angle), origin=(0, 0))
            b = translate(rotate(small, driven_angle_deg(float(angle)), origin=(0, 0)),
                          xoff=centre)
            overlap = a.intersection(b).area
            gap = a.distance(b)
            min_gap = min(min_gap, gap)
            if overlap > max_overlap:
                max_overlap, worst_angle = overlap, float(angle)
            if overlap > 1e-8:
                intersections += 1
        operating_alpha = acos((large_d.base_radius_mm + small_d.base_radius_mm) / centre)
        contact_ratio = (addendum_path - centre * sin(operating_alpha)) / base_pitch
        # Exact operating pitch backlash includes the change in involute angle.
        inv_delta = tan(operating_alpha) - operating_alpha - (tan(alpha) - alpha)
        operating_backlash = centre / 40 * 0.2 + 2 * centre * inv_delta
        report["centre_distance_results"].append({
            "centre_distance_mm": centre,
            "maximum_intersection_area_mm2": max_overlap,
            "minimum_boundary_gap_mm_neutral_phase": min_gap,
            "angles_with_interference": intersections,
            "worst_driver_angle_deg": worst_angle,
            "operating_pressure_angle_deg": operating_alpha * 180 / pi,
            "transverse_contact_ratio": contact_ratio,
            "operating_tangential_backlash_mm": operating_backlash,
        })
    return report


def validate_loaded_flanks(centre_distances=(40.0, 40.1, 40.2, 40.4),
                           step_deg=0.025) -> dict[str, Any]:
    """Test both backlash limits, where one involute flank transmits load.

    A complete 80-tooth angular period (4.5 degrees) repeats twenty times
    during the 90-degree test motion. This checks the root transitions under
    actual contact phases, in addition to the neutral-phase clearance test.
    Tiny positive boundary gaps are expected from polygon chord sampling.
    """
    from shapely.affinity import rotate, translate
    from shapely.geometry import Polygon

    large = Polygon(gear_outline(80))
    small = Polygon(gear_outline(20))
    alpha = 20 * pi / 180
    rbase_sum = 40 * cos(alpha)
    results = []
    for centre in centre_distances:
        operating_alpha = acos(rbase_sum / centre)
        inv_delta = tan(operating_alpha) - operating_alpha - (tan(alpha) - alpha)
        backlash = centre / 40 * 0.2 + 2 * centre * inv_delta
        small_operating_r = centre / 5
        half_backlash_angle = backlash / (2 * small_operating_r) * 180 / pi
        for sign in (-1, 1):
            overlaps, max_overlap, max_nearest_gap = 0, 0.0, 0.0
            min_nearest_gap = float("inf")
            for angle in np.linspace(0, 4.5, int(round(4.5 / step_deg)) + 1):
                a = rotate(large, float(angle), origin=(0, 0))
                small_angle = driven_angle_deg(float(angle)) + sign * half_backlash_angle
                b = translate(rotate(small, small_angle, origin=(0, 0)), xoff=centre)
                area = a.intersection(b).area
                distance = a.distance(b)
                max_overlap = max(max_overlap, area)
                min_nearest_gap = min(min_nearest_gap, distance)
                max_nearest_gap = max(max_nearest_gap, distance)
                overlaps += area > 1e-8
            results.append({
                "centre_distance_mm": centre,
                "driven_phase_offset_deg": sign * half_backlash_angle,
                "maximum_intersection_area_mm2": max_overlap,
                "angles_with_interference": int(overlaps),
                "minimum_nearest_gap_mm": min_nearest_gap,
                "maximum_nearest_gap_mm": max_nearest_gap,
            })
    return {
        "period_driver_degrees": 4.5,
        "step_deg": step_deg,
        "samples_per_centre_distance_and_load_direction": int(round(4.5 / step_deg)) + 1,
        "results": results,
    }


if __name__ == "__main__":
    result = validate_pair()
    result["loaded_flank_check"] = validate_loaded_flanks()
    path = Path(__file__).with_name("gear_profile_notes.json")
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
