"""Independent checks of central-case integral connections; no geometry edits."""
from pathlib import Path
import hashlib, importlib.util, io, json, sys, time
import numpy as np
import trimesh
import baskets as b

ROOT = Path(__file__).resolve().parent
BASELINE = ROOT.parents[1] / 'outputs/beads-baskets-p1s-v4-integral/source'
if not BASELINE.exists():
    BASELINE = ROOT
sys.path.append(str(BASELINE))
REPORT_PATH = (ROOT.parent/'verification'/'central_checks.json') if (ROOT.parent/'verification').is_dir() else ROOT/'central_checks.json'
START = time.time()
EPS = 1e-7
REPORT = {'source_sha256': hashlib.sha256((ROOT/'baskets.py').read_bytes()).hexdigest(),
          'intersection_tolerance_mm3': EPS, 'errors': [], 'warnings': []}

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

previous_path = BASELINE/'baskets.py' if BASELINE != ROOT else ROOT/'reference_v4_baskets.py'
previous = load_module('previous_v4_baskets', previous_path)
build = load_module('central_audit_build', BASELINE/'build.py')
D = b.build()
P = D['parts']
OLD = previous.build()['parts']

def overlap(a, c):
    ab, cb = a.bounding_box(), c.bounding_box()
    if any(ab[k+3] <= cb[k]+1e-9 or cb[k+3] <= ab[k]+1e-9 for k in range(3)):
        return 0.0
    return max(0.0, float((a ^ c).volume()))

def difference_volume(a, c):
    return max(0.0, float((a-c).volume())) + max(0.0, float((c-a).volume()))

def finish_section(name, data, error=None):
    REPORT[name] = data
    if error:
        REPORT['errors'].append(error)
    REPORT_PATH.write_text(json.dumps(REPORT, indent=2), encoding='utf-8')
    print('Checked '+name+(' FAIL: '+error if error else ''), flush=True)

topology = {}
for name, part in D['print_parts'].items():
    mesh = part.to_mesh()
    tm = trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=True)
    rt = trimesh.load(io.BytesIO(tm.export(file_type='stl')), file_type='stl')
    cc = lambda m: len(trimesh.graph.connected_components(m.face_adjacency, nodes=np.arange(len(m.faces)), engine='scipy'))
    item = {'manifold_status': str(part.status()), 'manifold_components': len(part.decompose()),
            'volume_mm3': float(tm.volume), 'triangles': len(tm.faces),
            'watertight': bool(tm.is_watertight), 'consistent_winding': bool(tm.is_winding_consistent),
            'components': cc(tm), 'zero_area_faces': int((tm.area_faces < 1e-10).sum()),
            'stl_roundtrip_watertight': bool(rt.is_watertight),
            'stl_roundtrip_consistent_winding': bool(rt.is_winding_consistent),
            'stl_roundtrip_components': cc(rt),
            'stl_roundtrip_zero_area_faces': int((rt.area_faces < 1e-10).sum())}
    item['valid'] = (item['volume_mm3'] > 0 and item['watertight'] and item['consistent_winding']
        and item['components'] == item['manifold_components'] == 1 and item['zero_area_faces'] == 0
        and item['stl_roundtrip_watertight'] and item['stl_roundtrip_consistent_winding']
        and item['stl_roundtrip_components'] == 1 and item['stl_roundtrip_zero_area_faces'] == 0)
    topology[name] = item
finish_section('topology', topology, 'topology' if any(not q['valid'] for q in topology.values()) else None)

lids = {}
for name, body in [('lid_27','bin_27'),('lid_90','bin_90'),('central_lid','central_case')]:
    delta = difference_volume(P[name], OLD[name])
    old_friction = overlap(OLD[body], OLD[name])
    new_friction = overlap(P[body], P[name])
    lids[name] = {'symmetric_difference_mm3': delta, 'previous_friction_overlap_mm3': old_friction,
                 'current_friction_overlap_mm3': new_friction,
                 'valid': delta < EPS and abs(old_friction-new_friction) < EPS}
finish_section('unchanged_lids_and_friction', lids, 'lid compatibility' if any(not q['valid'] for q in lids.values()) else None)

AS = {q['name']: {'part': q['part'], 'shape': b.apply_pose(P[q['part']], q)} for q in D['assembly']}
names = list(AS)
unexpected, own_friction = [], []
for i, name in enumerate(names):
    for other in names[i+1:]:
        v = overlap(AS[name]['shape'], AS[other]['shape'])
        if v <= EPS:
            continue
        own_lid = (name.startswith('bin_') and other == name.replace('bin_', 'lid_', 1)) or (name == 'central_case' and other == 'central_lid')
        row = {'a': name, 'b': other, 'overlap_mm3': v}
        (own_friction if own_lid else unexpected).append(row)
finish_section('closed_storage_assembly', {'objects': len(AS), 'checked_pairs': len(names)*(len(names)-1)//2,
    'expected_own_lid_friction': own_friction, 'unexpected_overlaps': unexpected, 'valid': not unexpected},
    'closed storage assembly' if unexpected else None)

bin_names = [n for n in names if n.startswith('bin_')]
fixed_storage = [(n, q['shape']) for n,q in AS.items() if n not in ('central_case','central_lid')]
closed_center = P['central_case'] + P['central_lid']
zs = sorted(set(np.arange(0, 35.001, .5).tolist() + [.1,.25,.35,.65,19.,19.35,19.9,20.1,20.35,20.65,20.9,21.1,21.35,24.9,25.1]))
failures = []
for z in zs:
    moving = closed_center.translate([0,0,z])
    for n, shape in fixed_storage:
        v = overlap(moving, shape)
        if v > EPS:
            failures.append({'central_lift_mm': z, 'fixed': n, 'overlap_mm3': v})
finish_section('central_vertical_insertion_and_removal', {'z_range_mm': [0,35], 'sample_count': len(zs),
    'central_own_lid_fitted': True, 'all_other_lids_fitted': True, 'failures': failures,
    'max_overlap_mm3': max([q['overlap_mm3'] for q in failures],default=0), 'valid': not failures},
    'central vertical insertion' if failures else None)

capture = []
for shift in [[1,0,0],[-1,0,0],[0,1,0],[0,-1,0]]:
    moving = P['central_case'].translate(shift)
    contacts = [{'fixed':n,'overlap_mm3':overlap(moving,AS[n]['shape'])} for n in bin_names]
    capture.append({'translation_mm':shift,'contacts':[q for q in contacts if q['overlap_mm3']>EPS],
                    'total_overlap_mm3':sum(q['overlap_mm3'] for q in contacts)})
rotation = []
for angle in [-1.,1.]:
    moving = P['central_case'].rotate([0,0,angle])
    contacts = [{'fixed':n,'overlap_mm3':overlap(moving,AS[n]['shape'])} for n in bin_names]
    rotation.append({'angle_deg':angle,'contacts':[q for q in contacts if q['overlap_mm3']>EPS],
                     'total_overlap_mm3':sum(q['overlap_mm3'] for q in contacts)})
valid_capture = all(q['total_overlap_mm3']>EPS for q in capture+rotation)
finish_section('central_horizontal_and_rotation_capture', {'translation_checks':capture,'rotation_checks':rotation,
    'vertical_latch':False,'valid':valid_capture}, 'central capture' if not valid_capture else None)

# The unchanged base is expressed in original CAD Z; storage table is original Z+46.
base = build.build_dock().translate([0,0,46])
base_checks = []
base_z = sorted(set(np.arange(0,48.001,.5).tolist()+[.1,.35,.65,3.9,4.1,19.9,20.1,20.65]))
for z in base_z:
    moving = base.translate([0,0,z])
    contacts = [{'bin':n,'overlap_mm3':overlap(moving,AS[n]['shape']),
                 'gap_mm_capped_at_10':float(moving.min_gap(AS[n]['shape'],10.))} for n in bin_names]
    positive = [q for q in contacts if q['overlap_mm3']>EPS]
    base_checks.append({'base_lift_mm':z,'maximum_overlap_mm3':max(q['overlap_mm3'] for q in contacts),
                        'minimum_gap_mm_capped_at_10':min(q['gap_mm_capped_at_10'] for q in contacts),
                        'collisions':positive})
base_valid = not any(q['collisions'] for q in base_checks)
socket_gaps = []
outer, channel = b._central_socket_profile()
socket = b._extrude(outer.difference(channel),0,b.Parameters().central_joint_height)
for pose in D['assembly']:
    if not pose['part'].startswith('bin'):
        continue
    local_angle = D['metadata'][pose['part']]['central_socket_angle_deg']
    shape = b.apply_pose(socket.rotate([0,0,local_angle]),pose)
    gaps = [float(base.translate([0,0,z]).min_gap(shape,10.)) for z in base_z]
    socket_gaps.append({'basket':pose['name'],'installed_gap_mm_capped_at_10':gaps[0],
        'minimum_lift_path_gap_mm_capped_at_10':min(gaps)})
finish_section('unchanged_machine_base_and_vertical_removal', {'sample_count':len(base_z),
    'z_range_mm':[0,48], 'central_case_absent':True, 'all_baskets_present':True,
    'checks':base_checks, 'new_socket_only_gaps':socket_gaps,
    'minimum_new_socket_lift_path_gap_mm':min(q['minimum_lift_path_gap_mm_capped_at_10'] for q in socket_gaps),
    'minimum_complete_basket_lift_path_gap_mm':min(q['minimum_gap_mm_capped_at_10'] for q in base_checks),
    'valid':base_valid}, 'base insertion/removal' if not base_valid else None)

# Verify the whole receiver working-height region rather than only three sample holes.
receiver_checks = {}
upper_halfspace = b.M.cube([500,500,100]).translate([-250,-250,24.49])
for name in ['bin_27','bin_90']:
    delta = difference_volume(P[name]^upper_halfspace, OLD[name]^upper_halfspace)
    new_features = P[name]-OLD[name]
    removed_features = OLD[name]-P[name]
    receiver_checks[name] = {'symmetric_difference_above_z24_49_mm3':delta,
        'added_feature_bounds_xyz_mm':list(new_features.bounding_box()),
        'removed_volume_mm3':max(0,float(removed_features.volume())),
        'valid':delta<EPS}
finish_section('original_machine_receiver_geometry', receiver_checks,
    'original receiver changed' if any(not q['valid'] for q in receiver_checks.values()) else None)

# Prove new low inner sockets cannot meet the unchanged rotating chute using Z bounds.
chute = build.chute.build_chute()
chute_min = []
for tilt in [0,-1.2,1.2]:
    shape = chute.translate([0,0,-12]).rotate([0,tilt,0]).translate([0,0,58-.3])
    chute_min.append({'tilt_deg':tilt,'minimum_table_z_mm':shape.bounding_box()[2]})
added_high = max(receiver_checks[n]['added_feature_bounds_xyz_mm'][5] for n in receiver_checks)
min_chute = min(q['minimum_table_z_mm'] for q in chute_min)
finish_section('new_features_chute_vertical_separation', {'added_feature_maximum_z_mm':added_high,
    'chute_minimum_z_with_1_2degree_tilt_and_0_3mm_drop':chute_min,
    'minimum_vertical_gap_mm':min_chute-added_high,
    'rotation_about_vertical_axis_cannot_change_z':True,
    'prior_unchanged_chute_full_sweep_check_inherited':True,'valid':min_chute>added_high},
    'new features may meet chute' if min_chute<=added_high else None)

# With center present, the flared bowl intentionally obstructs upward removal of
# basket sockets. Check no center-free basket is trapped by its neighbors.
lift_reports = []
for name in bin_names:
    lid_name = name.replace('bin_','lid_',1)
    moving = AS[name]['shape']+AS[lid_name]['shape']
    fixed = [(n,q['shape']) for n,q in AS.items() if n not in (name,lid_name,'central_case','central_lid')]
    neighbor_collisions, center_collisions = [], []
    for z in zs:
        shifted = moving.translate([0,0,z])
        vc = overlap(shifted,closed_center)
        if vc>EPS:
            center_collisions.append({'lift_mm':z,'overlap_mm3':vc})
        for n,shape in fixed:
            v = overlap(shifted,shape)
            if v>EPS:
                neighbor_collisions.append({'lift_mm':z,'fixed':n,'overlap_mm3':v})
    lift_reports.append({'basket':name,'own_lid_fitted':True,'other_lids_fitted':True,
        'sample_count':len(zs),'center_absent_failures':neighbor_collisions,
        'center_absent_valid':not neighbor_collisions,
        'center_present_blocked':bool(center_collisions),
        'first_sampled_center_interference_lift_mm':center_collisions[0]['lift_mm'] if center_collisions else None,
        'maximum_center_overlap_mm3':max([q['overlap_mm3'] for q in center_collisions],default=0)})
    print('Basket removal checked '+name,flush=True)
lift_valid = all(q['center_absent_valid'] for q in lift_reports)
finish_section('basket_removal_sequence', {'checks':lift_reports,
    'required_sequence':'Remove central closed case vertically first, then lift any basket at least 23 mm.',
    'central_case_must_be_absent_when_closing_the_outer_ring':True,
    'valid':lift_valid},'center-free basket removal' if not lift_valid else None)

# Existing v4 outer T joints remain usable. Only the three baskets receiving
# central-case keys need the new inner socket; the other eight can remain v4.
outer_region = b.M.cube([500,500,100]).translate([-250,-250,-1]) - b._cylinder(110,-2,101,segments=360)
outer_joint_preservation = {}
for name in ['bin_27','bin_90']:
    delta = difference_volume(P[name]^outer_region,OLD[name]^outer_region)
    outer_joint_preservation[name] = {'symmetric_difference_outside_radius110_mm3':delta,'valid':delta<EPS}
finish_section('v4_outer_joint_preservation',outer_joint_preservation,
    'v4 outer joints changed' if any(not q['valid'] for q in outer_joint_preservation.values()) else None)

new_baskets = {'bin_27_04','bin_27_08','bin_90'}
MIXED = {}
for pose in D['assembly']:
    name, part = pose['name'],pose['part']
    use_old = name.startswith('bin_') and name not in new_baskets
    # All lids are v4 as explicitly checked identical above.
    use_old = use_old or name.startswith('lid_') or name == 'central_lid'
    shape = b.apply_pose(OLD[part] if use_old else P[part],pose)
    MIXED[name] = {'shape':shape,'version':'v4' if use_old else 'v5'}
mixed_static = []
for i,name in enumerate(names):
    for other in names[i+1:]:
        own_lid = (name.startswith('bin_') and other==name.replace('bin_','lid_',1)) or (name=='central_case' and other=='central_lid')
        if own_lid:
            continue
        v = overlap(MIXED[name]['shape'],MIXED[other]['shape'])
        if v>EPS:
            mixed_static.append({'a':name,'b':other,'overlap_mm3':v})
mixed_lift = []
for z in zs:
    moving = closed_center.translate([0,0,z])
    for name in names:
        if name in ('central_case','central_lid'):
            continue
        v = overlap(moving,MIXED[name]['shape'])
        if v>EPS:
            mixed_lift.append({'central_lift_mm':z,'fixed':name,'overlap_mm3':v})
mixed_valid = not mixed_static and not mixed_lift and all(q['valid'] for q in outer_joint_preservation.values())
finish_section('mixed_v4_v5_reuse',{'new_v5_baskets':sorted(new_baskets),
    'retained_v4_sorting_baskets':[n for n in bin_names if n not in new_baskets],
    'new_central_case_required':True,'all_v4_lids_retained':True,
    'static_objects':len(MIXED),'static_unexpected_overlaps':mixed_static,
    'central_vertical_insertion_z_range_mm':[0,35],'central_vertical_insertion_sample_count':len(zs),
    'central_vertical_insertion_failures':mixed_lift,
    'required_27_basket_orientation':'New bin_27 at original indexed positions 04 and 08 in assembly plan.',
    'valid':mixed_valid},'mixed v4/v5 reuse' if not mixed_valid else None)

old_case_contacts = []
for name in bin_names:
    v = overlap(OLD['central_case'],AS[name]['shape'])
    if v>EPS:
        old_case_contacts.append({'basket':name,'overlap_mm3':v})
finish_section('old_v4_central_case_compatibility',{'compatible_with_new_inner_sockets':not old_case_contacts,
    'contacts_with_new_baskets':old_case_contacts,
    'interpretation':'The old cylindrical central case conflicts with new basket inner sockets. Replace the central case when fitting any new socket baskets.'},
    'old central case unexpectedly reported compatible' if not old_case_contacts else None)

REPORT['limits'] = ['Geometry only; no physical printing, fit, strength, fatigue, load or leakage tests.',
    'Finite 0.5 mm motion samples with extra transition points; not a formal continuous collision proof.',
    'Own lid friction intersections intentionally retained and matched with baseline.',
    'Center must be removed before lifting individual baskets; no vertical carry latch.',
    'Machine and central storage case are alternative occupants of the middle space.']
REPORT['elapsed_s'] = time.time()-START
REPORT['valid'] = not REPORT['errors']
REPORT_PATH.write_text(json.dumps(REPORT,indent=2),encoding='utf-8')
print(json.dumps({'valid':REPORT['valid'],'errors':REPORT['errors'],'elapsed_s':REPORT['elapsed_s']}),flush=True)

