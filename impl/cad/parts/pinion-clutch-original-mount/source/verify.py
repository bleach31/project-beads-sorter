"""Verify exported models against ORIGINAL mounting datums, then real toolpaths."""
from pathlib import Path
import json,math,zipfile,re
import numpy as np
import trimesh
from shapely.geometry import Point,LineString
from shapely.ops import unary_union
import build
ROOT=Path(__file__).resolve().parents[1]

def part(name):
    m=next(iter(build.load_objects(ROOT/'parts'/f'{name}.3mf').values()))
    assert m.is_volume and len(m.split())==1
    stl=trimesh.load_mesh(ROOT/'stl'/f'{name}.stl')
    assert stl.is_volume and len(stl.split())==1
    assert np.allclose(m.bounds,stl.bounds,atol=1e-5) and abs(m.volume-stl.volume)<.001
    return m

# Normalize the untouched reference independently: original +Y face faces motor.
src=next(iter(build.load_objects(ROOT/'reference/pinion_original.3mf').values()))
v=src.vertices.copy();src.vertices=np.column_stack([v[:,0],v[:,2],v[:,1].max()-v[:,1]])
old_h=float(src.bounds[1,2]);radii=np.linalg.norm(src.vertices[:,:2],axis=1)
old_socket_z=src.vertices[np.abs(radii-2.5)<2e-5,2]
old_depth=float(old_socket_z.max()-old_socket_z.min())
ring_print=part('00_ring');ring=ring_print.copy()
ring.apply_transform(trimesh.transformations.rotation_matrix(math.pi,[1,0,0]))
ring.apply_translation([0,0,build.RING_H])
assert abs(ring.bounds[0,2])<1e-6
mask=build.cylinder(20,old_h)-build.cylinder(6,old_h+.2,-.1)
old_band=build.as_solid(src)^mask;new_band=build.as_solid(ring)^mask
band_diff=abs((old_band-new_band).volume())+abs((new_band-old_band).volume());assert band_diff<1e-4
mount=[];ends=[]
for i,(name,angle)in enumerate(build.VARIANTS):
    h=part(f'0{i+1}_hub_{name}_arc{angle}');r=np.linalg.norm(h.vertices[:,:2],axis=1)
    socket=h.vertices[np.abs(r-2.5)<2e-5,2]
    head=h.vertices[np.abs(r-build.HEAD_R)<2e-5,2]
    assert abs(socket.min())<1e-6 and abs(socket.max()-old_depth)<1e-5
    assert abs(head.min()-old_h)<1e-5
    mount.append({'hub':name,'socket_entry_mm':float(socket.min()),'socket_depth_mm':float(np.ptp(socket)),
      'screw_seat_mm':float(head.min()),'motor_side_tooth_face_offset_mm':float(ring.bounds[0,2]),
      'original_tooth_band_difference_mm3':band_diff})
    hs=build.as_solid(h)
    for j,(cname,wrap)in enumerate(build.CLIPS):
        c=part(f'0{j+4}_clip_{cname}');cs=build.as_solid(c)
        # Count clip motion in its groove, not just its nominal drawn position.
        for cz in [build.GROOVE_Z+.001,build.GROOVE_TOP-build.CLIP_H-.001]:
            placed_c=cs.translate((0,0,cz));assert abs((hs^placed_c).volume())<1e-5
            for rz in [0,cz-build.RING_H-.001]:
                rr=ring.copy();rr.apply_translation([0,0,rz]);rs=build.as_solid(rr)
                assert abs((hs^rs).volume())<1e-5 and abs((rs^placed_c).volume())<1e-5
                combined=trimesh.util.concatenate([h,rr,build.mesh(placed_c)])
                assert combined.bounds[0,2]>=-1e-5 and combined.bounds[1,2]<=6.00001
                ends.append({'hub':name,'clip':cname,'clip_z_mm':cz,'ring_z_mm':rz,'height_mm':float(combined.extents[2])})

with zipfile.ZipFile(ROOT/'print/02_all_trials_P1S_PLA_sliced.3mf')as z:
    g=z.read('Metadata/plate_1.gcode').decode();settings=json.loads(z.read('Metadata/project_settings.config'))
offset=np.array([float(a)for a in settings['extruder_offset'][0].split('x')])
segments=[];x=y=e=0.;layer=0.;width=.4;obj=None;relative=True
for line in g.splitlines():
    if line.startswith('; Z_HEIGHT:'):layer=float(line.split(':')[1])
    if line.startswith('; LINE_WIDTH:'):width=float(line.split(':')[1])
    if line.startswith('; start printing object'):obj=int(line.rsplit(':',1)[1])
    if line.startswith('; stop printing object'):obj=None
    if line.startswith('M83'):relative=True
    if line.startswith('M82'):relative=False
    if line.startswith('G92 E'):e=float(line.split('E')[1].split()[0])
    if not re.match(r'^G[0123]\s',line):continue
    d={k:float(v)for k,v in re.findall(r'([XYEIJ])(-?\d*\.?\d+)',line.split(';')[0])}
    nx,ny=d.get('X',x),d.get('Y',y);de=d.get('E',0)if relative else d.get('E',e)-e
    if obj is not None and de>0:
        if line.startswith(('G2 ','G3 ')):
            cx,cy=x+d.get('I',0),y+d.get('J',0);radius=math.hypot(x-cx,y-cy)
            a0=math.atan2(y-cy,x-cx);a1=math.atan2(ny-cy,nx-cx);sweep=(a1-a0)%(2*math.pi)
            if line.startswith('G2 '):sweep-=2*math.pi
            elif abs(sweep)<1e-8:sweep=2*math.pi
            pts=[(cx+radius*math.cos(a),cy+radius*math.sin(a))for a in np.linspace(a0,a0+sweep,max(2,int(abs(sweep)*radius/.05)+1))]
            segments.extend((layer,p,q,width)for p,q in zip(pts,pts[1:]))
        elif math.hypot(nx-x,ny-y)>.0001:segments.append((layer,(x,y),(nx,ny),width))
    x,y=nx,ny
    if 'E'in d:e=e+d['E']if relative else d['E']

def deposited(centre,z,radius=6):
    lines=[s for s in segments if abs(s[0]-z)<.005 and np.linalg.norm(np.array(s[1])-centre)<radius and np.linalg.norm(np.array(s[2])-centre)<radius]
    assert lines
    return unary_union([LineString([np.array(s[1])-centre,np.array(s[2])-centre]).buffer(s[3]/2+.015)for s in lines])

arm_checks=[];seat_checks=[]
for i,(name,angle)in enumerate(build.VARIANTS):
    centre=np.array([84+i*23,88])-offset;p=deposited(centre,.68)
    count=0;gaps=0
    for turn in [0,120,240]:
        for a in np.linspace(15,angle-20,60):
            phi=build.PHASE+turn+a
            count+=p.covers(Point(*build.xy(build.ARM_OUTER_R-build.THICKNESS/2,phi)))
            gaps+=p.covers(Point(*build.xy((build.JOURNAL_R+build.ARM_OUTER_R-build.THICKNESS)/2,phi)))
    assert count==180 and gaps==0,(name,count,gaps)
    arm_checks.append({'hub':name,'z_mm':.68,'printed_arm_samples':count,'unwanted_gap_extrusion_samples':gaps})
    # Original ~0.192 mm web is retained; check the slicer did not omit it.
    seat=deposited(centre,2.96,3.5)
    assert all(seat.covers(Point(*build.xy(1.65,a)))for a in range(0,360,15))
    seat_checks.append({'hub':name,'screw_seat_extrusion_at_z_mm':2.96})
clip_checks=[]
for j,(name,wrap)in enumerate(build.CLIPS):
    p=deposited(np.array([84+j*23,115])-offset,.68,5)
    alpha=(wrap-180)/2
    points=[Point(*build.xy(build.CLIP_CENTRE_R,a))for a in np.linspace(-alpha+5,180+alpha-5,160)]
    assert all(p.covers(q)for q in points)
    clip_checks.append({'clip':name,'printed_arc_samples':160})
report={'mount_reference':'original pinion socket entrance and original motor-side tooth face',
  'original_socket_depth_mm':old_depth,'original_screw_seat_mm':old_h,'mount_checks':mount,
  'assembly_end_checks':ends,'arm_toolpaths':arm_checks,'screw_seat_toolpaths':seat_checks,'clip_toolpaths':clip_checks,
  'physical_installation_and_torque_tested':False,'printer_transmission_performed':False}
(ROOT/'verification/original-mount-and-toolpaths.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'mount_checks':mount,'assembly_end_checks':len(ends),'arm_toolpaths':arm_checks,'clip_toolpaths':clip_checks},indent=2))
