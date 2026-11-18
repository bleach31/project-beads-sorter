"""Original servo mounting retained. z=0 is motor-side tooth face/socket mouth.
Positive z points AWAY from the motor. All additions stay in 0 <= z <= 6.
No geometry/pipeline check in this file establishes actual PLA retention torque.
"""
from pathlib import Path
import json, math, zipfile, hashlib
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
import manifold3d as mf
from shapely.geometry import Point,Polygon,LineString
from shapely.ops import unary_union
from shapely import affinity
from three_mf import export_3mf

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'reference/pinion_original.3mf'
PHASE=-1.354
HUB_H=6.0
RING_H=4.08
CAVITY_H=2.40
SOCKET_R=2.50
HEAD_R=2.30
SCREW_R=1.00
JOURNAL_R=3.30
BEARING_R=3.50
SHOULDER_R=3.75
GROOVE_R=2.90
GROOVE_Z=4.20
GROOVE_TOP=5.52
LIP_R=3.35
CLIP_H=1.20
CLIP_Z=4.24
CLIP_INNER_R=2.95
CLIP_WIDTH=1.20
CLIP_CENTRE_R=CLIP_INNER_R+CLIP_WIDTH/2
LAND_R=5.30
POCKET_R=.85
POCKET_CENTRE_R=4.85
ARM_OUTER_R=5.05
ARM_H=2.04
ARM_COUNT=3
VARIANTS=[('J1',100),('J2',95),('J3',85)]
CLIPS=[('C1',245),('C2',255)]
THICKNESS=1.20
ENGAGEMENT=.35

def circle(r,xy=(0,0)):
    return Point(*xy).buffer(r,quad_segs=96)

def xy(r,deg):
    a=math.radians(deg);return r*math.cos(a),r*math.sin(a)

def solid(poly,height,z=0):
    polys=poly.geoms if poly.geom_type=='MultiPolygon' else [poly]
    contours=[]
    for p in polys:
        contours.append(np.array(p.exterior.coords[:-1]))
        contours.extend(np.array(r.coords[:-1])for r in p.interiors)
    return mf.CrossSection(contours,mf.FillRule.EvenOdd).extrude(height).translate((0,0,z))

def cylinder(r,h,z=0):
    return mf.Manifold.cylinder(h,r,circular_segments=192).translate((0,0,z))

def mesh(s):
    assert s.status()==mf.Error.NoError and s.volume()>0
    a=s.to_mesh64();m=trimesh.Trimesh(np.array(a.vert_properties[:,:3]),np.array(a.tri_verts),process=True)
    assert m.is_volume and len(m.split())==1
    return m

def as_solid(m):
    s=mf.Manifold(mf.Mesh64(np.asarray(m.vertices,np.float64),np.asarray(m.faces,np.uint64)))
    assert s.status()==mf.Error.NoError and s.volume()>0
    return s

def load_objects(path):
    with zipfile.ZipFile(path)as z:root=ET.fromstring(z.read('3D/3dmodel.model'))
    out={}
    for o in root.findall('.//{*}object'):
        v=np.array([[float(a.get(k))for k in'xyz']for a in o.findall('.//{*}vertex')])
        f=np.array([[int(a.get(k))for k in['v1','v2','v3']]for a in o.findall('.//{*}triangle')])
        if len(v):out[o.get('name','original')]=trimesh.Trimesh(v,f,process=True)
    return out

def original():
    m=next(iter(load_objects(SOURCE).values()))
    v=m.vertices.copy();motor_plane=float(v[:,1].max())
    m.vertices=np.column_stack([v[:,0],v[:,2],motor_plane-v[:,1]])
    assert m.is_volume
    radius=np.linalg.norm(m.vertices[:,:2],axis=1)
    socket_z=m.vertices[np.abs(radius-SOCKET_R)<2e-5,2]
    return m,float(m.bounds[1,2]),float(socket_z.max())

def cavity():
    return unary_union([circle(LAND_R)]+[circle(POCKET_R,xy(POCKET_CENTRE_R,PHASE+i*30))for i in range(12)])

def ring(original_mesh,original_height):
    # Stitch an exact extrusion onto the original far-face cap. Reuse the
    # original boundary vertices rather than unioning two nearly coincident
    # outlines, which can leave sub-resolution triangles at the seam.
    v=original_mesh.vertices.copy();f=original_mesh.faces.copy()
    cap=np.all(np.abs(v[f,2]-original_height)<1e-8,axis=1)
    cap_faces=f[cap];used=np.unique(cap_faces)
    added=v[used].copy();added[:,2]=RING_H
    mapping={int(old):len(v)+i for i,old in enumerate(used)}
    edges=np.concatenate([cap_faces[:,[0,1]],cap_faces[:,[1,2]],cap_faces[:,[2,0]]])
    _,inverse,counts=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True)
    boundary=edges[counts[inverse]==1]
    sides=[]
    for a,b in boundary:sides.extend([[a,b,mapping[int(b)]],[a,mapping[int(b)],mapping[int(a)]]])
    top=np.array([[mapping[int(k)]for k in face]for face in cap_faces])
    blank_mesh=trimesh.Trimesh(np.vstack([v,added]),np.vstack([f[~cap],top,sides]),process=True)
    assert blank_mesh.is_volume
    blank=as_solid(blank_mesh)
    return blank-solid(cavity(),CAVITY_H+.1,-.1)-cylinder(BEARING_R,RING_H+.2,-.1)

def arm_profile(angle):
    r=ARM_OUTER_R-THICKNESS/2
    beam=LineString([xy(r,a)for a in np.linspace(angle,0,120)]).buffer(THICKNESS/2,quad_segs=24)
    root=LineString([xy(2.9,angle),xy(r-.3,angle)]).buffer(.70,quad_segs=24)
    tip=circle(.6,(LAND_R+ENGAGEMENT-.6,0))
    return affinity.rotate(unary_union([beam,root,tip]),PHASE,origin=(0,0))

def hub(name,angle,original_height,socket_depth):
    arm=arm_profile(angle)
    arms=[affinity.rotate(arm,i*120,origin=(0,0))for i in range(3)]
    for i in range(3):
        tip=circle(.6,xy(LAND_R-.6-.05,PHASE+i*120))
        for j in range(3):
            if i!=j:assert tip.distance(arms[j])>.10
    s=solid(unary_union(arms+[circle(3.0)]),ARM_H)+cylinder(JOURNAL_R,HUB_H)
    s+=mf.Manifold.cylinder(.4,JOURNAL_R,SHOULDER_R,circular_segments=192).translate((0,0,2.0))
    s-=cylinder(JOURNAL_R+.2,GROOVE_TOP-GROOVE_Z,GROOVE_Z)-cylinder(GROOVE_R,GROOVE_TOP-GROOVE_Z+.2,GROOVE_Z-.1)
    s+=cylinder(LIP_R,HUB_H-GROOVE_TOP,GROOVE_TOP)
    # Servo enters from z=0, exactly as in the original pinion. Screw head seats
    # at the ORIGINAL far face, reached through a recess from the opposite side.
    s-=cylinder(SOCKET_R,socket_depth+.1,-.1)
    s-=cylinder(SCREW_R,HUB_H+.2,-.1)
    s-=cylinder(HEAD_R,HUB_H-original_height+.1,original_height)
    # One, two or three dots on the FRONT face; the motor mating face is unmarked.
    n=int(name[-1])
    for a in np.linspace(90-10*(n-1),90+10*(n-1),n):
        s-=solid(circle(.30,xy(2.85,a)),.25,HUB_H-.24)
    # Conservative radial clearance after tip deflection, at the top of the arm.
    shoulder_at_arm_top=JOURNAL_R+(SHOULDER_R-JOURNAL_R)*(ARM_H-2.0)/.4
    assert ARM_OUTER_R-THICKNESS-ENGAGEMENT-shoulder_at_arm_top>.10
    return s,unary_union(arms+[circle(JOURNAL_R)])

def clip(wrap):
    alpha=(wrap-180)/2
    p=LineString([xy(CLIP_CENTRE_R,a)for a in np.linspace(-alpha,180+alpha,300)]).buffer(CLIP_WIDTH/2,quad_segs=48)
    return solid(p,CLIP_H)

def print_pose(m,flip=False):
    m=m.copy()
    if flip:m.apply_transform(trimesh.transformations.rotation_matrix(math.pi,[1,0,0]))
    m.apply_translation([0,0,-m.bounds[0,2]])
    return m

def save(name,m):
    assert m.is_volume and len(m.split())==1
    m.export(ROOT/'stl'/f'{name}.stl')
    export_3mf(ROOT/'parts'/f'{name}.3mf',[(name,m)],name)

def generate():
    src,old_h,depth=original();r=ring(src,old_h);rm=mesh(r)
    report={'revision':'original-mount','source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
      'coordinate_basis':'z=0 is ORIGINAL motor-side tooth face and socket mouth; +z away from motor',
      'motor_side_tooth_face_mm':float(rm.bounds[0,2]),'original_tooth_width_mm':old_h,
      'new_tooth_width_mm':RING_H,'socket_diameter_mm':SOCKET_R*2,'socket_depth_mm':depth,
      'screw_seat_position_mm':old_h,'screw_seat_web_mm':old_h-depth,
      'extra_screw_length_vs_original_mm':0,'groove_diameter_mm':GROOVE_R*2,
      'groove_depth_from_journal_mm':JOURNAL_R-GROOVE_R,'retaining_lip_step_mm':LIP_R-GROOVE_R,
      'groove_wall_around_screw_access_mm':GROOVE_R-HEAD_R,
      'clip_overlap_with_lip_mm':LIP_R-CLIP_INNER_R,
      'axial_play_min_mm':GROOVE_Z-RING_H,'axial_play_max_mm':GROOVE_TOP-CLIP_H-RING_H,
      'physical_fit_and_torque_verified':False,'variants':[]}
    # Compare the original tooth band itself, not a stretched replacement.
    mask=(cylinder(20,old_h)-cylinder(6,old_h+.2,-.1))
    old_band=as_solid(src)^mask;new_band=r^mask
    delta=abs((old_band-new_band).volume())+abs((new_band-old_band).volume())
    assert delta<1e-4,delta
    assert abs(rm.bounds[0,2])<1e-6
    report['original_tooth_band_difference_mm3']=delta
    plate=[]
    def place(name,m,x,y):
        m=m.copy();m.apply_translation([x,y,0]);plate.append((name,m))
    ringprint=print_pose(rm,True);save('00_ring',ringprint);place('00_ring',ringprint,58,88)
    hubs={};profiles={}
    for i,(name,angle)in enumerate(VARIANTS):
        h,p=hub(name,angle,old_h,depth);m=mesh(h);stem=f'0{i+1}_hub_{name}_arc{angle}'
        save(stem,m);place(stem,m,84+i*23,88);hubs[name]=m;profiles[name]=p
        assert abs((h^r).volume())<1e-6
        report['variants'].append({'name':name,'arc_deg':angle,'arc_length_mm':math.radians(angle)*(ARM_OUTER_R-THICKNESS/2),
          'claw_count':3,'width_mm':THICKNESS,'height_mm':ARM_H,'engagement_mm':ENGAGEMENT})
    clips={}
    for i,(name,wrap)in enumerate(CLIPS):
        m=mesh(clip(wrap));stem=f'0{i+4}_clip_{name}';save(stem,m);place(stem,m,84+i*23,115);clips[name]=m
    assembly=[('ring',rm),('hub_J1',hubs['J1'])]
    c=clips['C1'].copy();c.apply_translation([0,0,CLIP_Z]);assembly.append(('clip_C1',c))
    export_3mf(ROOT/'assembly/assembled_J1_VIEW_ONLY.3mf',assembly,'Original mount retained - assembly reference only')
    export_3mf(ROOT/'plates/00_all_trials_geometry.3mf',plate,'Original mount: one ring, J1 J2 J3 hubs, C1 C2 clips')
    (ROOT/'verification/design.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (ROOT/'verification/plate-layout.json').write_text(json.dumps([{'name':n,'bounds':m.bounds.tolist()}for n,m in plate],indent=2),encoding='utf-8')
    render(src,rm,hubs,clips,profiles,report)
    print(json.dumps(report,indent=2),flush=True)

def render(src,ring,hubs,clips,profiles,report):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    from matplotlib.patches import Rectangle,Polygon as Patch
    plt.rcParams['font.family']=FontProperties(fname='C:/Windows/Fonts/YuGothR.ttc').get_name()
    fig,ax=plt.subplots(figsize=(10,4.8),facecolor='white')
    ax.axvline(0,color='#263e4b',lw=1.5)
    rows=[('元のピニオン',0,report['original_tooth_width_mm'],2.6),('前案（位置がずれた）',1.92,6,1.5),('修正版',0,RING_H,.4)]
    for label,start,end,y in rows:
        ax.add_patch(Rectangle((start,y),end-start,.55,facecolor='#a9cbd9',edgecolor='#30586e'))
        ax.text(-.18,y+.28,label,ha='right',va='center',fontsize=12)
        ax.text((start+end)/2,y+.28,f'歯の範囲 {start:.2f} ～ {end:.2f} mm',ha='center',va='center',fontsize=11)
    ax.add_patch(Rectangle((CLIP_Z,.32),CLIP_H,.71,facecolor='#a6caa3',edgecolor='#356039'))
    ax.annotate('抜け止めは反対側',xy=(CLIP_Z+CLIP_H/2,.95),xytext=(5.1,1.19),ha='center',fontsize=11,arrowprops={'arrowstyle':'->','color':'#356039'})
    ax.text(0,3.45,'サーボ軸穴の入口を揃えて比較',ha='left',fontsize=15)
    ax.text(0,-.28,'モーター側の歯の端面：修正版も 0.00 mm',ha='left',fontsize=12)
    ax.set_xlim(-2.25,6.3);ax.set_ylim(-.45,3.8);ax.axis('off')
    fig.tight_layout();fig.savefig(ROOT/'images/mount-comparison.png',dpi=170);plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(12,4.6),facecolor='white')
    section=ring.section(plane_origin=[0,0,1],plane_normal=[0,0,1])
    ps=sorted([Polygon(a[:,:2])for a in section.discrete],key=lambda p:p.area,reverse=True)
    rp=ps[0]
    for p in ps[1:]:rp=rp.difference(p)
    for ax,(name,angle)in zip(axes,VARIANTS):
        for p,color in [(rp,'#c8dfe8'),(profiles[name].difference(circle(SOCKET_R)),'#e7af61')]:
            ax.add_patch(Patch(np.array(p.exterior.coords),facecolor=color,edgecolor='#3b4e5b',lw=.7))
            for h in p.interiors:ax.add_patch(Patch(np.array(h.coords),facecolor='white',edgecolor='#3b4e5b',lw=.7))
        ax.set_title(f'{name} ／ 円弧 {angle}°',fontsize=13);ax.set_aspect('equal');ax.set_xlim(-10,10);ax.set_ylim(-10,10);ax.axis('off')
    fig.suptitle('モーター側から見た交換ハブ（3本爪）',fontsize=18)
    fig.text(.5,.02,'共通：幅1.20 mm ／ 高さ2.04 mm ／ 掛かり0.35 mm　　J1 → J2 → J3 の順に短い爪',ha='center',fontsize=11)
    fig.tight_layout(rect=[0,.06,1,.94]);fig.savefig(ROOT/'images/variants.png',dpi=160);plt.close(fig)
    from render_model import render as render3d
    from PIL import Image,ImageDraw,ImageFont
    out=Image.new('RGB',(1600,850),'white');d=ImageDraw.Draw(out);font=ImageFont.truetype('C:/Windows/Fonts/YuGothB.ttc',27)
    c=clips['C1'].copy();c.apply_translation([0,0,CLIP_Z])
    models=[(ring,(.48,.68,.79),1),(hubs['J1'],(.94,.65,.29),1),(c,(.54,.68,.44),1)]
    out.paste(render3d(models,(1,-1,1),size=(800,730)),(0,65))
    h=hubs['J1'].copy();h.apply_translation([0,0,-7]);c=clips['C1'].copy();c.apply_translation([0,0,8])
    models=[(ring,(.48,.68,.79),1),(h,(.94,.65,.29),1),(c,(.54,.68,.44),1)]
    out.paste(render3d(models,(1,-1,1),size=(800,730)),(800,65))
    d.text((20,15),'反モーター側：クリップと固定ねじ穴',font=font,fill='#203c4b')
    d.text((820,15),'分解図：下がモーター側',font=font,fill='#203c4b')
    d.text((20,804),'取付基準を維持 ／ 全厚6.00 mm ／ クリップはモーターと反対側',font=font,fill='#203c4b')
    out.save(ROOT/'images/assembly.png')

if __name__=='__main__':generate()
