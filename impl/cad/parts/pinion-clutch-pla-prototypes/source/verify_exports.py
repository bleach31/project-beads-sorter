"""Reload exported files and inspect real slicer paths through each PLA arm."""
from pathlib import Path
import json, zipfile, re, math
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
from shapely.geometry import Point, LineString
from shapely.ops import unary_union
import build
ROOT=Path(__file__).resolve().parents[1]


def read_objects(path):
    with zipfile.ZipFile(path) as z: root=ET.fromstring(z.read('3D/3dmodel.model'))
    out=[]
    for o in root.findall('.//{*}object'):
        v=np.array([[float(e.get(k))for k in 'xyz']for e in o.findall('.//{*}vertex')])
        f=np.array([[int(e.get(k))for k in ('v1','v2','v3')]for e in o.findall('.//{*}triangle')])
        out.append((o.get('name'),trimesh.Trimesh(v,f,process=True)))
    return out


checks={}
for path in sorted((ROOT/'parts').glob('*.3mf')):
    name,m=read_objects(path)[0]
    assert m.is_volume and len(m.split())==1,(name,'3mf topology')
    stl=trimesh.load_mesh(ROOT/'stl'/f'{name}.stl')
    assert stl.is_volume and len(stl.split())==1,(name,'stl topology')
    assert np.allclose(m.bounds,stl.bounds,atol=1e-5)
    assert abs(m.volume-stl.volume)<.001
    checks[name]={'3mf_watertight':True,'stl_watertight':True,'connected_components':1}
assert len(checks)==7

with zipfile.ZipFile(ROOT/'print'/'02_all_trials_P1S_PLA_sliced.3mf') as z:
    g=z.read('Metadata/plate_1.gcode').decode()
    settings=json.loads(z.read('Metadata/project_settings.config'))
nozzle_offset=np.array([float(v)for v in settings['extruder_offset'][0].split('x')])
segments=[];x=y=e=0.;layer=0.;width=.4;obj=None;relative=True;feature=''
for line in g.splitlines():
    if line.startswith('; Z_HEIGHT:'): layer=float(line.split(':')[1])
    if line.startswith('; LINE_WIDTH:'): width=float(line.split(':')[1])
    if line.startswith('; FEATURE:'): feature=line.split(':',1)[1].strip()
    if line.startswith('; start printing object'): obj=int(line.rsplit(':',1)[1])
    if line.startswith('; stop printing object'): obj=None
    if line.startswith('M83'): relative=True
    if line.startswith('M82'): relative=False
    if line.startswith('G92 E'): e=float(line.split('E')[1].split()[0])
    if not re.match(r'^G[0123]\s',line):continue
    d={k:float(v)for k,v in re.findall(r'([XYEIJ])(-?\d*\.?\d+)',line.split(';')[0])}
    nx,ny=d.get('X',x),d.get('Y',y)
    de=d.get('E',0) if relative else d.get('E',e)-e
    if obj is not None and de>0:
        if line.startswith(('G2 ','G3 ')):
            cx,cy=x+d.get('I',0),y+d.get('J',0)
            radius=math.hypot(x-cx,y-cy)
            a0=math.atan2(y-cy,x-cx);a1=math.atan2(ny-cy,nx-cx)
            sweep=(a1-a0)%(2*math.pi)
            if line.startswith('G2 '):sweep=sweep-2*math.pi
            elif abs(sweep)<1e-8:sweep=2*math.pi
            points=[(cx+radius*math.cos(a),cy+radius*math.sin(a))for a in np.linspace(a0,a0+sweep,max(2,int(abs(sweep)*radius/.05)+1))]
            for start,end in zip(points,points[1:]):segments.append((layer,obj,start,end,width,feature))
        elif math.hypot(nx-x,ny-y)>.0001:
            segments.append((layer,obj,(x,y),(nx,ny),width,feature))
    x,y=nx,ny
    if 'E'in d:e=e+d['E']if relative else d['E']

arms=[]
for i,(letter,t,engagement)in enumerate(build.VARIANTS):
    center=np.array([84+i*23,88])-nozzle_offset
    local=[s for s in segments if abs(s[0]-.68)<.005 and np.linalg.norm(np.array(s[2])-center)<7 and np.linalg.norm(np.array(s[3])-center)<7]
    assert local,letter
    deposited=unary_union([LineString([np.array(s[2])-center,np.array(s[3])-center]).buffer(s[4]/2+.015)for s in local])
    samples=[];gaps=[]
    for arm_angle in [0,180]:
        for a in np.linspace(15,105,60):
            angle=build.PHASE+a+arm_angle
            samples.append(deposited.covers(Point(*build.xyz(build.ARM_OUTER_R-t/2,angle))))
            gaps.append(deposited.covers(Point(*build.xyz((build.JOURNAL_R+build.ARM_OUTER_R-t)/2,angle))))
    assert all(samples),(letter,'missing arm centreline',sum(samples))
    assert not any(gaps),(letter,'fused arm gap',sum(gaps))
    arms.append({'variant':letter,'layer_z_mm':.68,'centreline_samples_with_extrusion':sum(samples),
        'centreline_samples_total':len(samples),'gap_samples_with_unwanted_extrusion':sum(gaps)})

# Check the thin original screw-seat web is actually represented by extrusion.
seats=[]
for i,(letter,_,_)in enumerate(build.VARIANTS):
    center=np.array([84+i*23,88])-nozzle_offset;found=[]
    for h in [1.52,1.64]:
        lines=[s for s in segments if abs(s[0]-h)<.005 and np.linalg.norm(np.array(s[2])-center)<3.3 and np.linalg.norm(np.array(s[3])-center)<3.3]
        deposited=unary_union([LineString([np.array(s[2])-center,np.array(s[3])-center]).buffer(s[4]/2+.015)for s in lines])
        if all(deposited.covers(Point(*build.xyz(1.65,a)))for a in range(0,360,15)):found.append(h)
    assert found,(letter,'screw seat absent')
    seats.append({'variant':letter,'screw_seat_present_at_layers_mm':found})

result={'exported_parts':checks,'gcode_arms':arms,'gcode_screw_seats':seats,
 'configured_nozzle_offset_mm':nozzle_offset.tolist(),
 'physical_function_verified':False,'printer_transmission_performed':False}
(ROOT/'verification'/'export-and-toolpath.json').write_text(json.dumps(result,indent=2),encoding='utf-8')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.font_manager import FontProperties
plt.rcParams['font.family']=FontProperties(fname='C:/Windows/Fonts/YuGothR.ttc').get_name()
fig,axes=plt.subplots(1,5,figsize=(15,4),facecolor='white')
for i,((letter,t,d),ax)in enumerate(zip(build.VARIANTS,axes)):
    center=np.array([84+i*23,88])-nozzle_offset;lines=[s for s in segments if abs(s[0]-.68)<.005 and np.linalg.norm(np.array(s[2])-center)<7 and np.linalg.norm(np.array(s[3])-center)<7]
    ax.add_collection(LineCollection([[np.array(s[2])-center,np.array(s[3])-center]for s in lines],colors='#137f9b',linewidths=.8))
    ax.set_xlim(-6,6);ax.set_ylim(-6,6);ax.set_aspect('equal');ax.axis('off');ax.set_title(f'{letter}：爪 {t:.2f} mm',fontsize=13)
fig.suptitle('実際の印刷経路：高さ 0.68 mm の層（5種類とも爪を保持）',fontsize=17)
fig.tight_layout();fig.savefig(ROOT/'verification'/'arm-toolpaths.png',dpi=150);plt.close(fig)
print(json.dumps({'parts_checked':len(checks),'arm_paths':arms,'screw_seats':seats},indent=2))
