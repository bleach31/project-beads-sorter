"""Read-only mesh and P1S plate checks for portable, unsliced core 3MF files.

Public API: ``validate_export_tree(root: Path) -> dict``.  The returned value is
JSON serializable and never claims that Bambu Studio slicing or physical fit
has been verified.  No geometry is repaired or rewritten.  Coincident vertices
are welded in memory solely to recover STL topology before checking it.
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import trimesh
from shapely.geometry import MultiPoint, box


CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": CORE}
BED_MM = 256.0
BRIM_MM = 5.0
PAIR_GAP_MM = 2.0 * BRIM_MM
TOL_MM = 1e-4
BED = box(0.0, 0.0, BED_MM, BED_MM)
KEEP_OUT = box(0.0, 0.0, 18.0, 28.0)
UNIT_TO_MM = {
    "micron": 0.001,
    "millimeter": 1.0,
    "centimeter": 10.0,
    "inch": 25.4,
    "foot": 304.8,
    "meter": 1000.0,
}


def _issue(code: str, message: str, **details) -> dict:
    return {"code": code, "message": message, **details}


def _transform(text: str | None) -> np.ndarray:
    """3MF stores a 4 x 3 row-vector affine transform, translation last."""
    result = np.eye(4, dtype=float)
    if text:
        numbers = np.array([float(x) for x in text.split()], dtype=float)
        if numbers.size != 12 or not np.isfinite(numbers).all():
            raise ValueError("A 3MF transform must contain 12 finite numbers")
        result[:, :3] = numbers.reshape(4, 3)
        if abs(np.linalg.det(result[:3, :3])) < 1e-12:
            raise ValueError("A 3MF transform must not collapse the mesh")
    return result


def _mesh_info(vertices, faces, *, require_ground: bool = True):
    vertices = np.asarray(vertices, dtype=float)
    faces = np.asarray(faces, dtype=np.int64)
    errors = []
    if vertices.ndim != 2 or vertices.shape[1:] != (3,) or not len(vertices):
        raise ValueError("Missing or malformed mesh vertices")
    if faces.ndim != 2 or faces.shape[1:] != (3,) or not len(faces):
        raise ValueError("Missing or malformed mesh triangles")
    if not np.isfinite(vertices).all():
        raise ValueError("Mesh contains non-finite coordinates")
    if int(faces.min()) < 0 or int(faces.max()) >= len(vertices):
        raise ValueError("Triangle index is outside the vertex array")

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    # STL repeats vertices per face.  Six decimal places retains sub-micron
    # detail while joining coincident float32 STL coordinates.  Do not remove
    # degenerate faces, fill holes, or fix winding as part of validation.
    mesh.merge_vertices(digits_vertex=6)
    bounds = np.asarray(mesh.bounds, dtype=float)
    watertight = bool(mesh.is_watertight)
    winding = bool(mesh.is_winding_consistent)
    volume = float(mesh.volume)
    components = len(mesh.split(only_watertight=False))
    degenerate = int(np.count_nonzero(np.asarray(mesh.area_faces) <= 1e-12))
    if not watertight:
        errors.append(_issue("not_watertight", "Mesh is not watertight"))
    if not winding:
        errors.append(_issue("inconsistent_winding", "Triangle winding is inconsistent"))
    if not np.isfinite(volume) or volume <= 0:
        errors.append(_issue("nonpositive_volume", "Signed mesh volume must be positive"))
    if components != 1:
        errors.append(_issue("disconnected_mesh", "Each printable mesh must have one connected shell", count=components))
    if degenerate:
        errors.append(_issue("degenerate_triangles", "Mesh contains zero-area triangles", count=degenerate))
    if require_ground and abs(float(bounds[0, 2])) > TOL_MM:
        errors.append(_issue("not_grounded", "Printable mesh minimum Z must be 0 mm", minimum_z_mm=float(bounds[0, 2])))
    if float(bounds[1, 2]) > BED_MM + TOL_MM:
        errors.append(_issue("above_build_height", "Mesh exceeds the nominal 256 mm build height"))

    result = {
        "valid": not errors,
        "vertices_after_welding": int(len(mesh.vertices)),
        "triangles": int(len(mesh.faces)),
        "watertight": watertight,
        "consistent_winding": winding,
        "connected_shells": components,
        "degenerate_triangles": degenerate,
        "volume_mm3": volume,
        "bounds_mm": bounds.tolist(),
        "size_mm": np.ptp(bounds, axis=0).tolist(),
        "errors": errors,
    }
    return result, np.asarray(mesh.vertices), np.asarray(mesh.faces)


def _validate_stl(path: Path) -> dict:
    loaded = trimesh.load_mesh(str(path), file_type="stl", process=False)
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError("STL did not load as a single mesh")
    report, _, _ = _mesh_info(loaded.vertices, loaded.faces)
    report["file"] = path.name
    return report


def _read_plate_instances(path: Path):
    """Read the package and expand core mesh/component/build transforms."""
    with zipfile.ZipFile(path) as archive:
        members = set(archive.namelist())
        for required in ("[Content_Types].xml", "_rels/.rels"):
            if required not in members:
                raise ValueError(f"3MF package is missing {required}")
        ET.fromstring(archive.read("[Content_Types].xml"))
        rels = ET.fromstring(archive.read("_rels/.rels"))
        links = [x for x in rels.findall(f"{{{REL}}}Relationship")
                 if x.get("Type", "").endswith("/3dmodel")]
        if len(links) != 1 or links[0].get("TargetMode", "Internal") != "Internal":
            raise ValueError("3MF must have one internal root model relationship")
        model_path = posixpath.normpath(links[0].get("Target", "").lstrip("/"))
        if model_path not in members:
            raise ValueError(f"3MF model relationship target is missing: {model_path}")
        model = ET.fromstring(archive.read(model_path))
        if model.tag != f"{{{CORE}}}model":
            raise ValueError("3MF model does not use the standard core namespace")
        unit = model.get("unit", "millimeter")
        if unit not in UNIT_TO_MM:
            raise ValueError(f"Unsupported 3MF unit: {unit}")
        scale = UNIT_TO_MM[unit]
        objects = {}
        for obj in model.findall("m:resources/m:object", NS):
            object_id = obj.get("id")
            if not object_id or object_id in objects:
                raise ValueError("3MF object IDs must be present and unique")
            objects[object_id] = obj

        def expand(object_id, transform, label, ancestry=()):
            if object_id not in objects:
                raise ValueError(f"Missing 3MF object {object_id}")
            if object_id in ancestry:
                raise ValueError("Cyclic 3MF component reference")
            obj = objects[object_id]
            mesh_element = obj.find("m:mesh", NS)
            components = obj.find("m:components", NS)
            if (mesh_element is None) == (components is None):
                raise ValueError(f"Object {object_id} must have either a mesh or components")
            if mesh_element is not None:
                vertices = np.array([[float(v.attrib[k]) for k in ("x", "y", "z")]
                                     for v in mesh_element.findall("m:vertices/m:vertex", NS)], dtype=float)
                faces = np.array([[int(f.attrib[k]) for k in ("v1", "v2", "v3")]
                                  for f in mesh_element.findall("m:triangles/m:triangle", NS)], dtype=np.int64)
                if vertices.ndim != 2 or vertices.shape[1:] != (3,):
                    raise ValueError(f"Object {object_id} has no valid vertices")
                vertices = (np.c_[vertices, np.ones(len(vertices))] @ transform)[:, :3] * scale
                # A reflected affine transform changes handedness, not whether
                # an originally outward-oriented physical shell is valid.
                if np.linalg.det(transform[:3, :3]) < 0:
                    faces = faces[:, ::-1]
                yield {"instance": label, "object_id": object_id,
                       "name": obj.get("name", f"object_{object_id}"),
                       "vertices": vertices, "faces": faces}
            else:
                children = components.findall("m:component", NS)
                if not children:
                    raise ValueError(f"Object {object_id} has no components")
                for index, component in enumerate(children, 1):
                    if any(key.endswith("}path") for key in component.attrib):
                        raise ValueError("Cross-file production-extension components are not supported by this core validator")
                    local = _transform(component.get("transform"))
                    yield from expand(component.get("objectid"), local @ transform,
                                      f"{label}/component_{index}", ancestry + (object_id,))

        build = model.findall("m:build/m:item", NS)
        if not build:
            raise ValueError("3MF print plate has no build items")
        instances = []
        skipped = []
        for index, item in enumerate(build, 1):
            if item.get("printable", "1").lower() in ("0", "false"):
                skipped.append(index)
                continue
            if any(key.endswith("}path") for key in item.attrib):
                raise ValueError("Cross-file production-extension build items are not supported by this core validator")
            instances.extend(expand(item.get("objectid"), _transform(item.get("transform")), f"build_{index}"))
        if not instances:
            raise ValueError("3MF print plate has no printable mesh instances")
        slicer_metadata = sorted(name for name in members if name.startswith("Metadata/")
                                 and any(token in name.lower() for token in ("config", "gcode", "slice")))
        return instances, {
            "declared_unit": unit, "root_model": model_path,
            "build_item_count": len(build), "skipped_nonprintable_build_items": skipped,
            "slicer_metadata_members": slicer_metadata,
        }


def _validate_plate(path: Path) -> dict:
    instances, metadata = _read_plate_instances(path)
    errors = []
    warnings = []
    if metadata["declared_unit"] != "millimeter":
        errors.append(_issue("unexpected_unit", "Deliverable plates must explicitly use millimeter units; dimensions below have been converted to mm"))
    if metadata["skipped_nonprintable_build_items"]:
        warnings.append(_issue("nonprintable_items", "Nonprintable build items were omitted from placement checks"))
    if metadata["slicer_metadata_members"]:
        warnings.append(_issue("slicer_metadata_not_validated", "Slicer metadata exists, but this validator does not validate settings or toolpaths"))
    details = []
    hulls = []
    all_bounds = []
    for instance in instances:
        info, vertices, _ = _mesh_info(instance["vertices"], instance["faces"])
        info.update({key: instance[key] for key in ("instance", "object_id", "name")})
        hull = MultiPoint(vertices[:, :2]).convex_hull
        if hull.geom_type != "Polygon" or hull.area <= 0:
            info["errors"].append(_issue("invalid_xy_footprint", "Printable part must have a nonzero projected XY footprint"))
        brim = hull.buffer(BRIM_MM)
        within_bed = bool(BED.buffer(TOL_MM).covers(brim))
        keepout_overlap = float(brim.intersection(KEEP_OUT).area)
        if not within_bed:
            info["errors"].append(_issue("brim_outside_bed", "Projected convex hull plus 5 mm brim exceeds the nominal 256 mm square bed"))
        if keepout_overlap > TOL_MM * TOL_MM:
            info["errors"].append(_issue("front_left_keepout", "Projected convex hull plus 5 mm brim overlaps the front-left 18 x 28 mm exclusion", overlap_mm2=keepout_overlap))
        info.update({"projected_convex_hull_area_mm2": float(hull.area),
                     "footprint_xy_bounds_mm": list(hull.bounds),
                     "brim_xy_bounds_mm": list(brim.bounds),
                     "brim_within_nominal_bed": within_bed,
                     "brim_keepout_overlap_mm2": keepout_overlap,
                     "valid": not info["errors"]})
        for error in info["errors"]:
            errors.append({**error, "instance": instance["instance"], "name": instance["name"]})
        details.append(info)
        hulls.append(hull)
        all_bounds.append(np.array(info["bounds_mm"]))

    pairs = []
    for i, j in itertools.combinations(range(len(details)), 2):
        distance = float(hulls[i].distance(hulls[j]))
        overlap = float(hulls[i].intersection(hulls[j]).area)
        valid = distance + TOL_MM >= PAIR_GAP_MM
        pair = {"a": details[i]["instance"], "b": details[j]["instance"],
                "a_name": details[i]["name"], "b_name": details[j]["name"],
                "convex_hull_gap_mm": distance, "convex_hull_overlap_mm2": overlap,
                "required_gap_mm": PAIR_GAP_MM, "valid": valid}
        pairs.append(pair)
        if not valid:
            errors.append(_issue("insufficient_part_spacing", "Projected convex hulls must be separated by at least 10 mm for two 5 mm brims", **pair))
    bounds = np.array([np.min([b[0] for b in all_bounds], axis=0),
                       np.max([b[1] for b in all_bounds], axis=0)])
    return {"file": path.name, "valid": not errors, **metadata,
            "printable_mesh_instance_count": len(details), "bounds_mm": bounds.tolist(),
            "size_mm": np.ptp(bounds, axis=0).tolist(), "objects": details,
            "pair_clearances": pairs, "errors": errors, "warnings": warnings}


def validate_export_tree(root: Path) -> dict:
    """Validate ``stl/*.stl`` and ``plates/*.3mf`` without changing files.

    Each file is inspected even when another file fails.  Errors are reported
    in the returned dictionary.  Use ``assert_valid`` if an exception is wanted.
    """
    root = Path(root)
    errors = []
    warnings = []
    stls = []
    plates = []
    files_stl = sorted((root / "stl").glob("*.stl"))
    files_plate = sorted((root / "plates").glob("*.3mf"))
    if not files_stl:
        errors.append(_issue("missing_stl_files", "No stl/*.stl deliverables were found"))
    if not files_plate:
        errors.append(_issue("missing_plate_files", "No plates/*.3mf deliverables were found"))
    for paths, validator, results, directory in (
        (files_stl, _validate_stl, stls, "stl"),
        (files_plate, _validate_plate, plates, "plates"),
    ):
        for path in paths:
            try:
                report = validator(path)
            except Exception as exc:
                report = {"file": path.name, "valid": False,
                          "errors": [_issue("unreadable_or_invalid_export", f"{type(exc).__name__}: {exc}")]}
            results.append(report)
            for error in report.get("errors", []):
                errors.append({"file": f"{directory}/{path.name}", **error})
            for warning in report.get("warnings", []):
                warnings.append({"file": f"{directory}/{path.name}", **warning})
    valid = not errors
    return {
        "schema_version": 1,
        "kind": "portable_core_3mf_geometry_validation",
        "valid": valid, "passed": valid,
        "scope": {
            "mesh_validation": "finite coordinates, valid indices, watertight, consistent winding, positive signed volume, one connected shell, no degenerate triangles, minimum Z=0",
            "placement_validation": "transformed XY convex hulls including a 5 mm brim; conservative footprint separation",
            "self_intersection_certification": False,
            "slicing_performed": False,
            "printer_profile_verified": False,
            "physical_print_or_fit_tested": False,
        },
        "settings": {"printer_nominal": "Bambu Lab P1S", "bed_mm": [256, 256, 256],
                     "brim_mm": BRIM_MM, "required_part_gap_mm": PAIR_GAP_MM,
                     "front_left_exclusion_xy_mm": [0, 0, 18, 28], "tolerance_mm": TOL_MM},
        "counts": {"stl_files": len(stls), "plate_files": len(plates),
                   "plate_mesh_instances": sum(p.get("printable_mesh_instance_count", 0) for p in plates)},
        "stl_files": stls, "plates": plates, "errors": errors, "warnings": warnings,
    }


def assert_valid(report: dict) -> None:
    if not report.get("valid", False):
        summary = "; ".join(f"{x.get('file', '')}: {x['code']}" for x in report.get("errors", [])[:12])
        raise ValueError(f"P1S export validation failed: {summary}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--report", type=Path, help="Optional explicit JSON report destination")
    args = parser.parse_args()
    result = validate_export_tree(args.root)
    serialized = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)
    if args.report:
        args.report.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    raise SystemExit(0 if result["valid"] else 1)
