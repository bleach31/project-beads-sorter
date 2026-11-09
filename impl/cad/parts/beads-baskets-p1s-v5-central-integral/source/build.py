"""Build the P1S basket system. Units mm. Geometry-only 3MF, never G-code."""
from pathlib import Path
import math, json, sys, zipfile, shutil, itertools, xml.etree.ElementTree as ET
import numpy as np
import trimesh
import manifold3d as md
import baskets
import chute
import legacy_4x as old

SOURCE=Path(__file__).resolve().parent
ROOT=(SOURCE.parents[1]/'outputs'/'beads-baskets-p1s-v5-central-integral' if SOURCE.parent.name=='work' else SOURCE.parent)
SPEC=json.loads((SOURCE/'system_spec.json').read_text(encoding='utf-8'))
M=md.Manifold
COLORS=['#CD796AFF','#D5A04BFF','#C9B751FF','#8BAB65FF','#559D7DFF',
        '#58A5B1FF','#648AB3FF','#8A82B0FF','#AD7FA1FF','#C08C96FF']

def mesh(shape):
    data=shape.to_mesh()
    return trimesh.Trimesh(np.asarray(data.vert_properties)[:,:3],np.asarray(data.tri_verts),process=True)

def standard(shape):
    b=shape.bounding_box()
    return shape.translate([-(b[0]+b[3])/2,-(b[1]+b[4])/2,-b[2]])

def size(shape):
    b=shape.bounding_box()
    return [b[i+3]-b[i] for i in range(3)]

def point(r,angle,z=0):
    a=math.radians(angle)
    return [r*math.cos(a),r*math.sin(a),z]

def pin(d,z0,z1,x=0,y=0):
    return (old.cyl(d/2,z0+.4,z1,x,y,64)+
            M.cylinder(.4,d/2-.35,d/2,circular_segments=64).translate([x,y,z0]))

def build_dock():
    """Replace only the old base: original mounting interfaces remain identical."""
    extensions=[]
    for angle,diameter in zip(SPEC['dock_angles_world_deg'],SPEC['dock_pin_diameters_mm']):
        foot=old.rounded_rect(24,89,-6,6,2,-46,-42)
        post=old.rounded_rect(81.5,89,-5.5,5.5,1.8,-42,-15.1)
        tongue=old.rounded_rect(84,100.2,-5,5,1.3,-15.2,-12.0)
        locating_pin=pin(diameter,-19.2,-15.1,97,0)
        # The short 45-degree shoulder remains inside R90, clear of the bin wall.
        shoulder=old.union([old.box(82,86,-4.5,4.5,-20,-19.8),
                            old.box(82,89,-4.5,4.5,-15.3,-15.1)]).hull()
        extensions.append((foot+post+tongue+locating_pin+shoulder).rotate([0,0,angle]))
    result=old.parts['01_base_4x']+old.union(extensions)
    # A new spoke crosses one floor mounting hole; recut every original hole
    # after the union so the unchanged carrier and bottom screw heads still fit.
    for x in [18,46]:
        for y in [-23,23]:
            result=result-old.cyl(1.65,-46.1,-41.9,x,y,48)
            result=result-old.cyl(3.0,-46.1,-43.8,x,y,48)
    return result

def dock_coupons():
    female=old.rounded_rect(-25,25,-10,10,2,0,8)
    male=old.rounded_rect(-25,25,-9,9,2,0,3.2)
    for x,w,d in [(-12.5,4.4,3.8),(12.5,5.8,5.2)]:
        slot=old.union([old.cyl(w/2,2.5,8.1,x+dx,0,64) for dx in [-1.1,1.1]]).hull()
        female=female-slot
        # Test pins point up for printing, using the same diameter and end chamfer.
        male=male+old.cyl(d/2,3.1,6.8,x,0,64)+M.cylinder(.4,d/2,d/2-.35,circular_segments=64).translate([x,0,6.8])
    return female,male

def build_system():
    print('Building baskets and unchanged drive geometry',flush=True)
    data=baskets.build()
    base=build_dock();new_chute=chute.build_chute()
    socket_coupon,pin_coupon=dock_coupons()
    print_parts=dict(data['print_parts'])
    print_parts.update({'base_with_docking':standard(base),
                        'smooth_u_chute':chute.preferred_print_orientation(new_chute),
                        'dock_fit_socket':standard(socket_coupon),'dock_fit_pins':standard(pin_coupon)})
    quantities={**data['quantities'],'base_with_docking':1,'smooth_u_chute':1,'dock_fit_socket':1,'dock_fit_pins':1}
    optional={k:old.standardize(v.rotate([180,0,0]) if k=='03_drive_gear_80t' else v)
              for k,v in old.parts.items() if k in ['02_motor_carrier','03_drive_gear_80t','04_output_gear_20t_spindle','05_split_bearing_cap']}
    return {'baskets':data,'base':base,'chute':new_chute,'print_parts':print_parts,'quantities':quantities,'optional':optional}

def write_3mf(path,items,description):
    ns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
    ET.register_namespace('',ns)
    def tag(x):return '{'+ns+'}'+x
    root=ET.Element(tag('model'),unit='millimeter')
    ET.SubElement(root,tag('metadata'),name='Title').text=path.stem
    ET.SubElement(root,tag('metadata'),name='Description').text=description
    resources=ET.SubElement(root,tag('resources'));build=ET.SubElement(root,tag('build'))
    mats=ET.SubElement(resources,tag('basematerials'),id='1')
    for i,(name,s,col) in enumerate(items):
        ET.SubElement(mats,tag('base'),name=name,displaycolor=col)
        obj=ET.SubElement(resources,tag('object'),id=str(i+2),name=name,type='model',pid='1',pindex=str(i))
        m=ET.SubElement(obj,tag('mesh'));vs=ET.SubElement(m,tag('vertices'));fs=ET.SubElement(m,tag('triangles'))
        t=mesh(s)
        for v in t.vertices:ET.SubElement(vs,tag('vertex'),**{k:f'{float(a):.6f}' for k,a in zip(['x','y','z'],v)})
        for f in t.faces:ET.SubElement(fs,tag('triangle'),**{k:str(int(a)) for k,a in zip(['v1','v2','v3'],f)})
        ET.SubElement(build,tag('item'),objectid=str(i+2))
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('3D/3dmodel.model',ET.tostring(root,encoding='utf-8',xml_declaration=True))
        z.writestr('[Content_Types].xml','<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr('_rels/.rels','<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')

def export_parts(system):
    report={}
    for folder,parts in [('stl',system['print_parts']),('optional_reprint_stl',system['optional'])]:
        (ROOT/folder).mkdir(exist_ok=True)
        for name,s in parts.items():
            t=mesh(s)
            assert s.status()==md.Error.NoError,(name,s.status())
            assert len(s.decompose())==1,(name,'disconnected solids')
            assert t.is_watertight and t.is_winding_consistent and t.volume>0,(name,'bad mesh')
            t.export(ROOT/folder/(name+'.stl'))
            report[name]={'file':folder+'/'+name+'.stl','size_mm':size(s),'watertight':t.is_watertight,
                          'consistent_winding':t.is_winding_consistent,'manifold_solids':len(s.decompose()),
                          'volume_mm3':float(t.volume),'triangles':len(t.faces),
                          'quantity':system['quantities'].get(name,1),'optional_existing_part_reprint':folder!='stl'}
    (ROOT/'verification'/'mesh_checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')

def plate_layouts(system):
    from repack import export
    manifest=json.loads((SOURCE/'compact_layouts.json').read_text(encoding='utf-8'))
    export(ROOT,manifest)
    return manifest


def scenes(system):
    b=system['baskets'];operating=[];storage=[]
    for pose in b['assembly']:
        name=pose['name'];part=pose['part'];s=baskets.apply_pose(b['parts'][part],pose)
        col='#CAD4CEFF'
        if name.startswith('bin_27') or name.startswith('lid_27'):
            col=COLORS[int(name[-2:])-1]
        elif 'central' in name:col='#A5C3B9FF'
        elif 'bridge' in name:col='#537F80FF'
        storage.append((name,s,col))
        if part.startswith('bin') or part=='bridge_clip':operating.append((name,s,col))
    # Actual modeled lower mechanism only. Upper feeder assembly is not reconstructed.
    angle=117.5
    lower=[('base_with_docking',system['base'],'#517F83FF'),
           ('motor_carrier',old.parts['02_motor_carrier'],'#6E9597FF'),
           ('drive80',old.parts['03_drive_gear_80t'].rotate([0,0,-angle/4]).translate([40,0,0]),'#D3A04BFF'),
           ('output20',old.parts['04_output_gear_20t_spindle'].rotate([0,0,angle]),'#C7854AFF'),
           ('bearing_cap',old.parts['05_split_bearing_cap'],'#537D80FF'),
           ('smooth_u_chute',system['chute'].rotate([0,0,angle]),'#D7AA66FF'),
           ('REFERENCE_existing_middle_plate',old.refs['middle-base'],'#B7C9C0FF')]
    motor=old.cyl(14,-38.1,-19,32)
    lower.append(('REFERENCE_28BYJ48_motor',motor,'#969F9FFF'))
    operating.extend([(n,s.translate([0,0,46]),col) for n,s,col in lower])
    for name,scene in [('VIEW_ONLY_operating',operating),('VIEW_ONLY_storage',storage)]:
        write_3mf(ROOT/'assembly'/(name+'.3mf'),scene,'Assembly inspection only. Not a print plate. Contains positioned parts and reference shapes.')
        tscene={}
        for n,s,c in scene:
            t=mesh(s);t.visual.face_colors=np.array(list(bytes.fromhex(c[1:])),dtype=np.uint8);tscene[n]=t
        trimesh.Scene(tscene).export(ROOT/'assembly'/(name+'.glb'))
    return operating,storage

def overlap(a,b):
    ba=a.bounding_box();bb=b.bounding_box()
    if any(ba[i+3]<=bb[i]+1e-7 or bb[i+3]<=ba[i]+1e-7 for i in range(3)):return 0.
    return max(0.,float((a^b).volume()))

def validate_mechanics(system):
    print('Checking docking and chute movement',flush=True)
    bd=system['baskets'];binshapes=[]
    for pose in bd['assembly']:
        if pose['part'].startswith('bin'):
            binshapes.append((pose['name'],baskets.apply_pose(bd['parts'][pose['part']],pose).translate([0,0,-46])))
    # The base and all its locating pins have physical clearance in the receivers.
    bolt_checks=[]
    for x in [18,46]:
        for y in [-23,23]:
            v=overlap(system['base'],old.cyl(1.64,-46.05,-41.95,x,y,48))
            assert v<1e-4,('original bolt hole blocked',x,y,v)
            bolt_checks.append({'x_mm':x,'y_mm':y,'overlap_mm3':v})
    dock_contacts=[]
    for name,s in binshapes:
        v=overlap(system['base'],s)
        assert v<1e-4,('dock/bin overlap',name,v)
        dock_contacts.append({'bin':name,'overlap_mm3':v})
    lifts=[]
    for lift in [0,.5,1,2,3,4,5,8,16,32,48]:
        vv=max(overlap(system['base'].translate([0,0,lift]),b) for _,b in binshapes)
        assert vv<1e-4,('dock lift obstruction',lift,vv)
        lifts.append({'lift_mm':lift,'maximum_overlap_mm3':vv})
    # A solid annulus is a conservative bound for every bin, receiver and separator.
    # The outlet and all moving surfaces stay above this envelope at all angles.
    annulus=old.cyl(190,-46,-16)-old.cyl(90,-46.1,-15.9)
    gear_envelope=old.cyl(32.8,-6,-1,40)+old.cyl(8,-15,-6,40)
    static=old.union([system['base'],old.parts['02_motor_carrier'],old.parts['05_split_bearing_cap'],
                      old.refs['middle-base'],old.refs['upper-base'],old.refs['camera-mount'],gear_envelope,annulus])
    poses=[]
    for tilt in [0,-1.2,1.2]:
        altered=system['chute'].translate([0,0,-12]).rotate([0,tilt,0]).translate([0,0,12])
        for dz in [0,-.3]:
            maxv=0.;worst=None
            for angle in np.arange(23,293.001,1.0):
                v=overlap(altered.rotate([0,0,float(angle)]).translate([0,0,dz]),static)
                if v>maxv:maxv=v;worst=float(angle)
            poses.append({'radial_tilt_deg':tilt,'axial_shift_mm':dz,'max_overlap_mm3':maxv,'worst_angle_deg':worst})
            print('sweep',poses[-1],flush=True)
            assert maxv<1e-4,('sweep collision',poses[-1])
    # Exact centre-line floor heights are included to support manual inspection.
    m=chute.metadata();slope=(m['inlet_floor_z_mm']-m['outlet_floor_z_mm'])/m['outlet_radius_mm']
    report={'units':'millimeter/degrees','preserved_original_floor_bolt_holes':bolt_checks,'dock_to_bin_intersections':dock_contacts,'vertical_base_removal_checks':lifts,
            'nozzle_sweep_rotation_deg':[23,293],'sweep_increment_deg':1,'sweep_pose_count':len(poses)*271,
            'sweep_cases':poses,'tilt_pivot_old_z_mm':12,'annular_basket_solid_envelope_table_z_mm':[0,30],
            'dock_tongue_top_table_z_mm':34.,'dock_tongue_basket_top_clearance_mm':.8,
            'slot_floor_to_pin_tip_clearance_mm':2.3,
            'chute_floor_table_z_at_r100_mm':m['inlet_floor_z_mm']-100*slope+46,
            'chute_outer_bottom_table_z_at_r100_mm':m['inlet_floor_z_mm']-100*slope+46-1.8,
            'chute':m,'scope':'New base, upper references at provided CAD positions, old drive envelopes, conservative solid basket ring. No physical print or speed testing.',
            'actual_print_fit_tested':False,'physical_speed_tested':False}
    (ROOT/'verification'/'mechanical_checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report

def copy_sources():
    dest=ROOT/'source';dest.mkdir(exist_ok=True)
    for name in ['build.py','legacy_4x.py','gear_profile.py','reference_parts.npz','baskets.py','chute.py','validate_exports.py','system_spec.json']:
        if (SOURCE/name).resolve()!=(dest/name).resolve():shutil.copy2(SOURCE/name,dest/name)
    (dest/'requirements.txt').write_text('numpy>=2.0\nmanifold3d>=3.5\ntrimesh>=4\nshapely>=2\nscipy>=1.14\npillow>=10\n',encoding='utf-8')

def main():
    ROOT.mkdir(exist_ok=True)
    for f in ['stl','optional_reprint_stl','plates','assembly','verification']: (ROOT/f).mkdir(exist_ok=True)
    system=build_system()
    export_parts(system);manifest=plate_layouts(system)
    (ROOT/'basket_dimensions.json').write_text(json.dumps(system['baskets']['metadata'],indent=2),encoding='utf-8')
    (ROOT/'interface_dimensions.json').write_text(json.dumps(system['baskets']['interface'],indent=2),encoding='utf-8')
    scenes(system)
    if '--skip-mechanics' not in sys.argv:validate_mechanics(system)
    from validate_central import validate
    print('Checking exported meshes and P1S plates',flush=True)
    report=validate(ROOT)
    (ROOT/'verification'/'p1s_export_checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    assert report['valid'], report['errors']
    for name in ['baskets_validation.json','chute-review.json','chute-tilt-review.json']:
        if (SOURCE/name).exists():shutil.copy2(SOURCE/name,ROOT/'verification'/name)
    copy_sources()
    print('EXPORT COMPLETE',ROOT,flush=True)

if __name__=='__main__':main()
