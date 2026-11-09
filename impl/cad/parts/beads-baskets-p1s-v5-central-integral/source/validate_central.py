"""Independent validation of central integral-joint P1S plates, without altering meshes.

Requires numpy>=2, trimesh>=4, shapely>=2, scipy>=1.14 and the v1
``source/validate_exports.py`` core-3MF reader.  Read projected triangles from
the exported plate, rather than assuming convex bounding outlines.  The full
height projection is deliberately conservative for support and brim planning.

Usage: python validate_central.py --root OUTPUT_FOLDER --report REPORT.json
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
import shapely
from shapely.geometry import box
import trimesh


BED_MM = 256.0
BRIM_MM = 5.0
GAP_MM = 10.0
PLACEMENT_TOL_MM = 1e-4
GEOMETRY_TOL_MM = 5e-5
PROJECTED_TRIANGLE_AREA_THRESHOLD_MM2 = 1e-9
BED = box(0.0, 0.0, BED_MM, BED_MM)
KEEP_OUT = box(0.0, 0.0, 18.0, 28.0)
REQUIRED_COUNTS = {
    "bin_27": 10, "lid_27": 10, "bin_90": 1, "lid_90": 1,
    "central_case": 1, "central_lid": 1, "base_with_docking": 1,
    "smooth_u_chute": 1,
    "02_motor_carrier": 1, "03_drive_gear_80t": 1,
    "04_output_gear_20t_spindle": 1, "05_split_bearing_cap": 1,
}
MOTION_COUNTS = {part: 1 for part in (
    "base_with_docking", "smooth_u_chute", "02_motor_carrier",
    "03_drive_gear_80t", "04_output_gear_20t_spindle", "05_split_bearing_cap",
)}
PHASE_COUNTS = {
    "motion_test": MOTION_COUNTS,
    "sorting_bins": {"bin_27": 10},
    "storage": {"bin_90": 1, "lid_90": 1, "central_case": 1,
                "central_lid": 1, "lid_27": 10},
}
PHASE_ORDER = {"motion_test": 0, "sorting_bins": 1, "storage": 2}
EXPECTED_STL_NAMES = set(REQUIRED_COUNTS) | {
    "joint_fit_male", "joint_fit_female", "lid_fit_cup", "lid_fit_lid",
    "dock_fit_socket", "dock_fit_pins",
}
APPROVED_GEOMETRY_CHANGES = {
    "stl/bin_27.stl": "Existing basket gains an integral central-case connection; outer basket joints remain compatible with v4",
    "stl/bin_90.stl": "Existing basket gains a compatible integral central-case connection; outer basket joints remain compatible with v4",
    "stl/central_case.stl": "Central case gains integral connections to surrounding baskets without separate assembly parts",
}
OPTIONAL_DRIVE_NAMES = set(MOTION_COUNTS) - {"base_with_docking", "smooth_u_chute"}
EXPECTED_STL_PATHS = {
    f"{'optional_reprint_stl' if part in OPTIONAL_DRIVE_NAMES else 'stl'}/{part}.stl"
    for part in EXPECTED_STL_NAMES
}
UNCHANGED_STL_PATHS = EXPECTED_STL_PATHS - set(APPROVED_GEOMETRY_CHANGES)
EXPECTED_FIT_COUNTS = {
    "joint_fit_male": 1, "joint_fit_female": 1,
    "lid_fit_cup": 1, "lid_fit_lid": 1,
    "dock_fit_socket": 1, "dock_fit_pins": 1,
}
PRESERVED_MOTION_PLATE = "plates/01_motion_test_complete.3mf"
EXPECTED_PLATE_NAMES = {
    "01_motion_test_complete.3mf", "02_five_bins.3mf", "03_five_bins.3mf",
    "04_central_case_and_three_lids.3mf", "05_central_lid_and_three_lids.3mf",
    "06_bin90_and_lid90.3mf", "07_four_lids.3mf", "OPTIONAL_fit_checks.3mf",
}


def issue(code, message, **details):
    return {"code": code, "message": message, **details}


def load_core_validator(root, baseline):
    candidates = [root / "source" / "validate_exports.py",
                  baseline / "source" / "validate_exports.py"]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise FileNotFoundError("source/validate_exports.py is required")
    spec = importlib.util.spec_from_file_location("_p1s_core_export_reader", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def projected_footprint(vertices, faces):
    """Union of all nonzero XY triangle shadows from the actual exported mesh."""
    triangles = np.asarray(vertices, dtype=float)[np.asarray(faces), :2]
    vectors_a = triangles[:, 1] - triangles[:, 0]
    vectors_b = triangles[:, 2] - triangles[:, 0]
    areas = np.abs(vectors_a[:, 0] * vectors_b[:, 1]
                   - vectors_a[:, 1] * vectors_b[:, 0]) * 0.5
    usable = triangles[areas > PROJECTED_TRIANGLE_AREA_THRESHOLD_MM2]
    if not len(usable):
        raise ValueError("Mesh has no nonzero XY triangle projections")
    # A one-nanometre grid only joins roundoff-sized seams between triangle edges.
    # Its size is smaller than the explicit placement tolerance by two orders.
    footprint = shapely.union_all(shapely.polygons(usable), grid_size=1e-6)
    if footprint.is_empty or not footprint.is_valid or footprint.area <= 0:
        raise ValueError("Projected triangle union is empty or invalid")
    return footprint


def canonical_faces(faces):
    rows = np.sort(np.asarray(faces, dtype=np.int64), axis=1)
    return rows[np.lexsort((rows[:, 2], rows[:, 1], rows[:, 0]))]


def compare_to_source(vertices, faces, source, placement):
    """Require the exact source triangulation with only Z rotation and XY shift."""
    errors = []
    angle = float(placement.get("rotation_z_deg", 0.0))
    translation = np.asarray(placement["center_xy_mm"], dtype=float)
    if translation.shape != (2,) or not np.isfinite(translation).all() or not math.isfinite(angle):
        raise ValueError("Placement must contain two finite XY values and a finite Z rotation")
    radians = math.radians(angle)
    rotation = np.array([[math.cos(radians), -math.sin(radians)],
                         [math.sin(radians), math.cos(radians)]])
    expected = source["vertices"].copy()
    expected[:, :2] = expected[:, :2] @ rotation.T + translation
    actual = np.asarray(vertices)
    expected_tree = cKDTree(expected)
    forward_distance, mapping = expected_tree.query(actual, k=1)
    reverse_distance, _ = cKDTree(actual).query(expected, k=1)
    distance = max(float(np.max(forward_distance)), float(np.max(reverse_distance)))
    vertex_match = distance <= GEOMETRY_TOL_MM
    face_count_match = len(faces) == len(source["faces"])
    face_match = (face_count_match and vertex_match and
                  np.array_equal(canonical_faces(mapping[np.asarray(faces)]),
                                 source["canonical_faces"]))
    if not vertex_match:
        errors.append(issue("geometry_changed", "Plate vertices do not match the source STL after its declared Z rotation and XY translation", maximum_vertex_error_mm=distance))
    if not face_match:
        errors.append(issue("triangulation_changed", "Plate triangle connectivity does not exactly match the source STL", source_triangle_count=int(len(source["faces"])), plate_triangle_count=int(len(faces))))
    return {
        "valid": not errors,
        "rotation_z_deg": angle,
        "translation_xy_mm": translation.tolist(),
        "maximum_vertex_error_mm": distance,
        "allowed_vertex_error_mm": GEOMETRY_TOL_MM,
        "exact_triangle_connectivity_match": bool(face_match),
        "scale_one_z_rotation_xy_translation_only": bool(vertex_match and face_match),
        "errors": errors,
    }


def plate_category(entry):
    return "fit_checks" if entry.get("phase") == "fit_checks" else "production"


def validate_plate(path, entry, core, sources):
    instances, metadata = core._read_plate_instances(path)
    errors = []
    warnings = []
    if metadata["declared_unit"] != "millimeter":
        errors.append(issue("wrong_unit", "3MF plate must explicitly use millimeter units"))
    if metadata["skipped_nonprintable_build_items"]:
        errors.append(issue("skipped_build_items", "Plate must not contain hidden nonprintable build items"))
    if metadata["slicer_metadata_members"]:
        warnings.append(issue("slicer_metadata_unverified", "Printer/process settings and generated toolpaths are outside this validator's scope"))
    placements = entry.get("objects", [])
    if len(instances) != len(placements):
        errors.append(issue("manifest_instance_mismatch", "Actual printable objects must exactly match the manifest object count", actual=len(instances), manifest=len(placements)))
    objects = []
    footprints = []
    for index, instance in enumerate(instances):
        info, vertices, faces = core._mesh_info(instance["vertices"], instance["faces"])
        info.update({k: instance[k] for k in ("instance", "object_id", "name")})
        footprint = projected_footprint(vertices, faces)
        brim = footprint.buffer(BRIM_MM, quad_segs=32)
        inside = bool(BED.buffer(PLACEMENT_TOL_MM).covers(brim))
        keepout_overlap = float(brim.intersection(KEEP_OUT).area)
        keepout_gap = float(footprint.distance(KEEP_OUT))
        if not inside:
            info["errors"].append(issue("brim_outside_bed", "Full-height projected outline plus 5 mm brim exceeds the 256 mm bed"))
        if keepout_gap + PLACEMENT_TOL_MM < BRIM_MM:
            info["errors"].append(issue("front_left_keepout", "Projected outline plus 5 mm brim overlaps the front-left 18 x 28 mm exclusion", overlap_mm2=keepout_overlap))
        if index < len(placements):
            placement = placements[index]
            part = str(placement["part"])
            info["part"] = part
            if part not in sources:
                info["errors"].append(issue("missing_source_stl", "Manifest part has no matching source STL", part=part))
            else:
                comparison = compare_to_source(vertices, faces, sources[part], placement)
                info["source_geometry_comparison"] = comparison
                info["errors"].extend(comparison["errors"])
        info.update({
            "projected_outline_area_mm2": float(footprint.area),
            "projected_outline_type": footprint.geom_type,
            "projected_outline_bounds_mm": list(footprint.bounds),
            "brim_xy_bounds_mm": list(brim.bounds),
            "brim_within_bed": inside,
            "brim_keepout_overlap_mm2": keepout_overlap,
            "outline_keepout_distance_mm": keepout_gap,
            "valid": not info["errors"],
        })
        for error in info["errors"]:
            errors.append({"instance": instance["instance"], "name": instance["name"], **error})
        objects.append(info)
        footprints.append(footprint)
    pairs = []
    for i, j in itertools.combinations(range(len(objects)), 2):
        gap = float(footprints[i].distance(footprints[j]))
        overlap = float(footprints[i].intersection(footprints[j]).area)
        pair = {"a": objects[i]["name"], "b": objects[j]["name"],
                "projected_outline_gap_mm": gap,
                "projected_outline_overlap_mm2": overlap,
                "required_gap_mm": GAP_MM,
                "valid": gap + PLACEMENT_TOL_MM >= GAP_MM}
        pairs.append(pair)
        if not pair["valid"]:
            errors.append(issue("insufficient_part_spacing", "Full-height projected outlines must leave 10 mm for two 5 mm brims", **pair))
    return {"file": path.name, "valid": not errors, **metadata,
            "category": plate_category(entry), "print_repeats": entry["print_repeats"],
            "phase": entry.get("phase"),
            "replaces_file": entry.get("replaces_file"),
            "printable_mesh_instance_count": len(instances), "objects": objects,
            "minimum_pair_gap_mm": min((p["projected_outline_gap_mm"] for p in pairs), default=None),
            "pair_clearances": pairs, "errors": errors, "warnings": warnings}


def validate(root: Path, baseline: Path | None = None):
    root = Path(root).resolve()
    baseline = Path(baseline).resolve() if baseline else root.parent / "beads-baskets-p1s-v4-integral"
    core = load_core_validator(root, baseline)
    manifest = json.loads((root / "plate_manifest.json").read_text(encoding="utf-8-sig"))
    if isinstance(manifest, dict):
        manifest = manifest["plates"]
    reference_hash_path = root / "source" / "baseline_stl_sha256.json"
    reference_hashes = json.loads(reference_hash_path.read_text(encoding="utf-8-sig")) if reference_hash_path.is_file() else {}
    reference_plate_hash_path = root / "source" / "baseline_plate_sha256.json"
    reference_plate_hashes = json.loads(reference_plate_hash_path.read_text(encoding="utf-8-sig")) if reference_plate_hash_path.is_file() else {}
    errors = []
    warnings = []
    sources = {}
    source_reports = []
    actual_stl_paths = set()
    if set(reference_hashes) != UNCHANGED_STL_PATHS:
        errors.append(issue("baseline_stl_hash_inventory", "Portable baseline hashes must contain exactly the 15 unchanged v4 STL paths", missing=sorted(UNCHANGED_STL_PATHS - set(reference_hashes)), unexpected=sorted(set(reference_hashes) - UNCHANGED_STL_PATHS)))
    if set(reference_plate_hashes) != {PRESERVED_MOTION_PLATE}:
        errors.append(issue("baseline_plate_hash_inventory", "Portable baseline plate hashes must contain exactly the unchanged motion plate", expected=PRESERVED_MOTION_PLATE, actual=sorted(reference_plate_hashes)))
    # These are read and hashed independently of the plate exporter.  The
    # baseline folder is the previously delivered geometry, not a regenerated
    # model.  Byte equality is required for the fifteen unaffected parts.
    # The two basket types and the central case are the only geometry exceptions.
    # All joint, lid and docking fit coupons remain byte-identical to v4.
    for folder in ("stl", "optional_reprint_stl"):
        for path in sorted((root / folder).glob("*.stl")):
            relative = f"{folder}/{path.name}"
            actual_stl_paths.add(relative)
            reference = baseline / folder / path.name
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            baseline_digest = (hashlib.sha256(reference.read_bytes()).hexdigest()
                               if reference.is_file() else reference_hashes.get(relative))
            hash_match = digest == baseline_digest
            approved_change = relative in APPROVED_GEOMETRY_CHANGES
            loaded = trimesh.load_mesh(path, file_type="stl", process=False)
            info, vertices, faces = core._mesh_info(loaded.vertices, loaded.faces)
            info.update({"file": relative, "sha256": digest,
                         "baseline_sha256": baseline_digest,
                         "baseline_reference": "previous_v4_file" if reference.is_file() else ("bundled_baseline_stl_sha256.json" if relative in reference_hashes else "approved_changed_part_without_bundled_baseline_hash"),
                         "unchanged_from_v4": hash_match if baseline_digest is not None else None,
                         "approved_geometry_change": approved_change,
                         "change_policy": APPROVED_GEOMETRY_CHANGES.get(relative, "Must be byte-identical to the previously delivered v4 STL")})
            if reference.is_file() and relative in reference_hashes and reference_hashes[relative] != baseline_digest:
                info["errors"].append(issue("baseline_hash_manifest_mismatch", "Bundled baseline hash disagrees with the existing v4 STL", file=relative))
            if not approved_change and not hash_match:
                info["errors"].append(issue("source_stl_changed", "Unaffected printable STL must be byte-identical to v4", baseline_file=str(reference)))
            info["valid"] = not info["errors"]
            sources[path.stem] = {"vertices": vertices, "faces": faces,
                                  "canonical_faces": canonical_faces(faces)}
            source_reports.append(info)
            for error in info["errors"]:
                errors.append({"file": relative, **error})
    if not sources:
        errors.append(issue("missing_stls", "No printable source STLs were found"))
    if set(sources) != EXPECTED_STL_NAMES or len(source_reports) != 18 or actual_stl_paths != EXPECTED_STL_PATHS:
        errors.append(issue("source_inventory_mismatch", "The package must contain exactly 18 expected STLs with integral joint coupons and no separate bridge clips or legacy connector coupon", expected_count=18, actual_count=len(source_reports), missing=sorted(EXPECTED_STL_PATHS - actual_stl_paths), unexpected=sorted(actual_stl_paths - EXPECTED_STL_PATHS)))
    motion_path = root / PRESERVED_MOTION_PLATE
    previous_motion_path = baseline / PRESERVED_MOTION_PLATE
    motion_digest = hashlib.sha256(motion_path.read_bytes()).hexdigest() if motion_path.is_file() else None
    bundled_motion_digest = reference_plate_hashes.get(PRESERVED_MOTION_PLATE)
    previous_motion_digest = (hashlib.sha256(previous_motion_path.read_bytes()).hexdigest()
                              if previous_motion_path.is_file() else bundled_motion_digest)
    motion_preservation = {
        "file": PRESERVED_MOTION_PLATE,
        "sha256": motion_digest,
        "baseline_sha256": previous_motion_digest,
        "baseline_reference": "previous_v4_file" if previous_motion_path.is_file() else "bundled_baseline_plate_sha256.json",
        "valid": bool(motion_digest and previous_motion_digest and motion_digest == previous_motion_digest),
    }
    if previous_motion_path.is_file() and bundled_motion_digest != previous_motion_digest:
        errors.append(issue("baseline_motion_plate_hash_mismatch", "Bundled motion-plate hash must match the existing v4 motion plate"))
    if not motion_preservation["valid"]:
        errors.append(issue("motion_plate_changed", "The complete first motion-test plate must be byte-identical to v4", **motion_preservation))
    actual_files = {p.name for p in (root / "plates").glob("*.3mf")}
    if actual_files != EXPECTED_PLATE_NAMES:
        errors.append(issue("plate_file_inventory_mismatch", "The package must retain exactly seven production plates and one optional fit plate, with the same filenames as v4", missing=sorted(EXPECTED_PLATE_NAMES - actual_files), unexpected=sorted(actual_files - EXPECTED_PLATE_NAMES)))
    declared_files = [str(e["file"]) for e in manifest]
    if len(set(declared_files)) != len(declared_files):
        errors.append(issue("duplicate_plate_manifest_entry", "Each physical plate file must appear only once in the manifest"))
    if actual_files != set(declared_files):
        errors.append(issue("plate_manifest_file_mismatch", "Manifest and plates folder must contain exactly the same 3MF files", undeclared=sorted(actual_files - set(declared_files)), missing=sorted(set(declared_files) - actual_files)))
    production_counts = Counter()
    fit_counts = Counter()
    plate_runs = Counter()
    phase_counts = {phase: Counter() for phase in PHASE_COUNTS}
    phase_runs = Counter()
    ordered_production = []
    fit_candidate_runs = 0
    plates = []
    for entry in manifest:
        filename = str(entry["file"])
        repeats = entry.get("print_repeats")
        if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 0:
            errors.append(issue("invalid_repeat_count", "print_repeats must be a nonnegative integer", file=filename))
            continue
        category = plate_category(entry)
        phase = entry.get("phase")
        if phase not in {*PHASE_COUNTS, "fit_checks"}:
            errors.append(issue("invalid_phase", "Every plate must declare motion_test, sorting_bins, storage, or fit_checks", file=filename, phase=phase))
        if entry.get("replaces_file"):
            errors.append(issue("unexpected_replacement_plate", "All four previous drive parts are required on the motion plate; no optional replacement plate is allowed", file=filename))
        entry_counts = Counter(str(p["part"]) for p in entry.get("objects", []))
        if category == "fit_checks":
            if entry.get("category") not in {"fit_checks", "optional", "optional_fit_checks"}:
                errors.append(issue("fit_category_mismatch", "A fit_checks phase must be marked as a fit or optional category", file=filename))
            fit_counts.update({part: quantity * max(1, repeats) for part, quantity in entry_counts.items()})
            plate_runs[category] += repeats
            fit_candidate_runs += max(1, repeats)
        else:
            if repeats < 1:
                errors.append(issue("unprinted_production_plate", "Every production plate must have at least one required print run", file=filename))
            weighted_counts = {part: quantity * repeats for part, quantity in entry_counts.items()}
            production_counts.update(weighted_counts)
            plate_runs[category] += repeats
            ordered_production.append({"file": filename, "phase": phase, "runs": repeats, "parts": dict(entry_counts)})
            if phase in PHASE_COUNTS:
                phase_counts[phase].update(weighted_counts)
                phase_runs[phase] += repeats
        path = root / "plates" / filename
        if path.parent.resolve() != (root / "plates").resolve():
            errors.append(issue("invalid_plate_path", "Plate manifest files must be directly inside plates/", file=filename))
            continue
        try:
            plate = validate_plate(path, entry, core, sources)
        except Exception as exc:
            plate = {"file": filename, "valid": False,
                     "errors": [issue("plate_read_or_validation_error", f"{type(exc).__name__}: {exc}")]}
        plates.append(plate)
        for error in plate.get("errors", []):
            errors.append({"file": f"plates/{filename}", **error})
        for warning in plate.get("warnings", []):
            warnings.append({"file": f"plates/{filename}", **warning})
    count_checks = []
    for part, expected in REQUIRED_COUNTS.items():
        actual = production_counts[part]
        check = {"part": part, "required": expected, "produced": actual, "valid": actual == expected}
        count_checks.append(check)
        if not check["valid"]:
            errors.append(issue("incorrect_production_quantity", "Production plate repeats must provide the exact required assembled quantity", **check))
    if set(production_counts) - set(REQUIRED_COUNTS):
        errors.append(issue("unexpected_production_parts", "Test coupons and other extras must not be included in production plates", unexpected=sorted(set(production_counts) - set(REQUIRED_COUNTS))))
    stage_checks = []
    for phase, expected in PHASE_COUNTS.items():
        check = {"phase": phase, "required_parts": expected, "produced_parts": dict(phase_counts[phase]), "print_runs": phase_runs[phase], "valid": phase_counts[phase] == Counter(expected)}
        stage_checks.append(check)
        if not check["valid"]:
            errors.append(issue("incorrect_phase_inventory", "Parts must be in their intended motion, sorting, or deferred storage phase", **check))
    motion_entries = [p for p in ordered_production if p["phase"] == "motion_test"]
    motion_plate_valid = (len(motion_entries) == 1 and motion_entries[0]["runs"] == 1
                          and f"plates/{motion_entries[0]['file']}" == PRESERVED_MOTION_PLATE
                          and Counter(motion_entries[0]["parts"]) == Counter(MOTION_COUNTS))
    if not motion_plate_valid:
        errors.append(issue("motion_plate_not_self_contained", "Exactly one first production plate must provide all six and only the six parts needed to assemble the motion mechanism, including both gears"))
    if phase_runs["sorting_bins"] != 2:
        errors.append(issue("sorting_phase_run_count", "The ten sorting bins with integral connectors must complete in two subsequent production runs", actual=phase_runs["sorting_bins"]))
    if phase_runs["storage"] != 4 or plate_runs["production"] != 7:
        errors.append(issue("deferred_storage_run_count", "Four deferred storage runs must give seven production runs in total", storage_runs=phase_runs["storage"], production_runs=plate_runs["production"]))
    fit_inventory_valid = fit_counts == Counter(EXPECTED_FIT_COUNTS) and fit_candidate_runs == 1
    if not fit_inventory_valid:
        errors.append(issue("fit_check_inventory_mismatch", "One optional fit plate must contain exactly the six joint, lid and docking fit samples, with no bridge clip", expected=EXPECTED_FIT_COUNTS, actual=dict(fit_counts), candidate_runs=fit_candidate_runs))
    order = [PHASE_ORDER.get(p["phase"], -1) for p in ordered_production]
    ordering_valid = (bool(order) and order[0] == 0 and order == sorted(order)
                      and all(p >= 0 for p in order))
    if not ordering_valid:
        errors.append(issue("incorrect_phase_order", "Production plate order must be motion_test first, then sorting_bins, then deferred storage", actual_phases=[p["phase"] for p in ordered_production]))
    production_files = [p["file"] for p in ordered_production]
    if production_files != sorted(production_files):
        errors.append(issue("filename_phase_order_mismatch", "Production file names must sort in the same chronological order as the manifest"))
    readiness = {"motion_test_after_production_runs": None, "sorting_with_ten_bins_after_production_runs": None,
                 "fit_checks_included_in_readiness": False,
                 "positioning_without_90_degree_bin": "The 04 and 08 sorting bin locating pins are available; the 90 degree key locating connection remains absent until the deferred bin is printed."}
    accumulated = Counter()
    runs = 0
    for entry in ordered_production:
        for _ in range(entry["runs"]):
            runs += 1
            accumulated.update(entry["parts"])
            if readiness["motion_test_after_production_runs"] is None and all(accumulated[p] >= n for p, n in MOTION_COUNTS.items()):
                readiness["motion_test_after_production_runs"] = runs
            sorting_target = Counter(MOTION_COUNTS) + Counter(PHASE_COUNTS["sorting_bins"])
            if readiness["sorting_with_ten_bins_after_production_runs"] is None and all(accumulated[p] >= n for p, n in sorting_target.items()):
                readiness["sorting_with_ten_bins_after_production_runs"] = runs
    if readiness["motion_test_after_production_runs"] != 1 or readiness["sorting_with_ten_bins_after_production_runs"] != 3:
        errors.append(issue("readiness_milestone_mismatch", "The mechanism must be ready after one run and the ten sorting bins after three runs, excluding optional fit checks", actual=readiness))
    return {
        "schema_version": 2, "kind": "central_integral_joint_startup_first_p1s_export_validation",
        "valid": not errors, "passed": not errors,
        "scope": {
            "mesh_checks": "finite coordinates, valid indices, watertight, consistent winding, one shell, positive volume, no degenerate triangles, Z0 and height <=256 mm",
            "placement_checks": "union of actual exported triangle XY projections at all heights, plus 5 mm brim and front-left keepout; projected pair distance >=10 mm",
            "geometry_preservation": "SHA256 byte equality of fifteen unaffected STLs and the first motion plate to v4; only bin_27, bin_90 and central_case may change; every plate mesh must have the same vertices and triangle connectivity as its source STL after its manifest Z rotation and XY translation",
            "priority_checks": "All six mechanism parts including both gears on the first required plate; ten sorting bins with integral connectors on the next two; all lids, the 90 degree bin and central case deferred to four storage runs",
            "slicing_performed": False, "support_generation_verified": False,
            "physical_print_tested": False,
        },
        "settings": {"printer_nominal": "Bambu Lab P1S", "bed_mm": [256, 256, 256],
                     "brim_mm": BRIM_MM, "required_part_gap_mm": GAP_MM,
                     "front_left_exclusion_xy_mm": [0, 0, 18, 28],
                     "placement_tolerance_mm": PLACEMENT_TOL_MM,
                     "geometry_tolerance_mm": GEOMETRY_TOL_MM,
                     "projection_union_grid_mm": 1e-6,
                     "projection_area_filter_mm2": PROJECTED_TRIANGLE_AREA_THRESHOLD_MM2},
        "counts": {"stl_files": len(source_reports), "plate_files": len(plates),
                   "production_print_runs": plate_runs["production"],
                   "fit_test_print_runs": plate_runs["fit_checks"],
                   "optional_fit_test_candidate_runs": fit_candidate_runs,
                   "total_runs_including_optional_fit_checks": plate_runs["production"] + fit_candidate_runs,
                   "production_runs_by_phase": dict(phase_runs),
                   "production_parts": dict(production_counts), "fit_test_parts": dict(fit_counts),
                   "unchanged_stl_count": sum(not p["approved_geometry_change"] for p in source_reports),
                   "approved_changed_or_new_stl_count": sum(p["approved_geometry_change"] for p in source_reports),
                   "separate_bridge_clip_count": production_counts["bridge_clip"] + fit_counts["bridge_clip"],
                   "unchanged_previous_drive_parts_are_required": True},
        "approved_geometry_changes": APPROVED_GEOMETRY_CHANGES,
        "unchanged_motion_plate_check": motion_preservation,
        "fit_inventory_valid": fit_inventory_valid,
        "production_quantity_checks": count_checks,
        "phase_quantity_checks": stage_checks,
        "production_phase_order": ordered_production,
        "production_order_valid": ordering_valid,
        "first_motion_plate_contains_exactly_six_required_parts": motion_plate_valid,
        "readiness": readiness,
        "stl_files": source_reports, "plates": plates,
        "errors": errors, "warnings": warnings,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, help="Previous v4 folder; defaults to sibling beads-baskets-p1s-v4-integral")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate(args.root, args.baseline)
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
        print(json.dumps({"valid": report["valid"], "counts": report["counts"],
                          "errors": report["errors"], "report": str(args.report)}, ensure_ascii=False))
    else:
        print(text)
    raise SystemExit(0 if report["valid"] else 1)
