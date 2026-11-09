"""Shared 3MF and G-code readers for the rotor trial validation."""
from pathlib import Path
import math,re,zipfile,xml.etree.ElementTree as ET
import numpy as np
NS={"c":"http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
PNS="{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"

def transform(text):
    mat=np.eye(4)
    if text:
        a=np.array(list(map(float,text.split()))).reshape((4,3))
        mat[:3,:3]=a[:3,:].T;mat[:3,3]=a[3,:]
    return mat


def points_3mf(path):
    caches={};vertices=[];triangles=0;object_bounds=[]
    with zipfile.ZipFile(path) as z:
        def get(member):
            member=member.lstrip('/')
            if member not in caches:
                x=ET.fromstring(z.read(member))
                caches[member]=(x,{o.get('id'):o for o in x.findall('c:resources/c:object',NS)})
            return caches[member]
        def walk(member,oid,matrix):
            nonlocal triangles
            root,objects=get(member);obj=objects[oid]
            vs=obj.findall('c:mesh/c:vertices/c:vertex',NS)
            if vs:
                pts=np.array([[float(v.get(k)) for k in 'xyz'] for v in vs])
                vertices.append(pts@matrix[:3,:3].T+matrix[:3,3])
                triangles+=len(obj.findall('c:mesh/c:triangles/c:triangle',NS))
            for comp in obj.findall('c:components/c:component',NS):
                target=comp.get(PNS+'path',member).lstrip('/')
                walk(target,comp.get('objectid'),matrix@transform(comp.get('transform')))
        root,_=get('3D/3dmodel.model')
        for item in root.findall('c:build/c:item',NS):
            start=len(vertices)
            walk('3D/3dmodel.model',item.get('objectid'),transform(item.get('transform')))
            pts=np.vstack(vertices[start:]);object_bounds.append([pts.min(0),pts.max(0)])
    return np.vstack(vertices),triangles,object_bounds


def read_paths(path,capture_features=False):
    pos=np.zeros(3);e=0.;relative_e=False;relative_xyz=False
    active=False;layer_z=None;feature='Custom'
    segments=[];types=[];layers=[];extrusions=[];segment_features=[]
    feature_e={}
    for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
        if line.startswith('; Z_HEIGHT:'):
            layer_z=float(line.split(':',1)[1]);active=True
        if line.startswith('; FEATURE:'):feature=line.split(':',1)[1].strip()
        cmd=line.split(';',1)[0].strip()
        if not cmd:continue
        parts=cmd.split();code=parts[0]
        if code=='M83':relative_e=True;continue
        if code=='M82':relative_e=False;continue
        if code=='G90':relative_xyz=False;continue
        if code=='G91':relative_xyz=True;continue
        if code not in ['G0','G1','G2','G3','G92']:continue
        vals={m.group(1):float(m.group(2)) for m in re.finditer(r'([XYZEIJ])([+-]?(?:\d+(?:\.\d*)?|\.\d+))',cmd)}
        if code=='G92':
            if 'E' in vals:e=vals['E']
            for i,k in enumerate('XYZ'):
                if k in vals:pos[i]=vals[k]
            continue
        nxt=pos.copy()
        for i,k in enumerate('XYZ'):
            if k in vals:nxt[i]=pos[i]+vals[k] if relative_xyz else vals[k]
        de=0.
        if 'E' in vals:
            de=vals['E'] if relative_e else vals['E']-e
            e=e+vals['E'] if relative_e else vals['E']
        if active and feature!='Custom' and de>1e-7 and np.linalg.norm(nxt[:2]-pos[:2])>1e-7:
            category=1 if feature.startswith('Support') else (2 if feature in ['Brim','Skirt'] else 0)
            points=[pos.copy(),nxt.copy()]
            if code in ['G2','G3'] and ('I' in vals or 'J' in vals):
                center=pos[:2]+[vals.get('I',0),vals.get('J',0)]
                radius=np.linalg.norm(pos[:2]-center)
                a0=math.atan2(pos[1]-center[1],pos[0]-center[0]);a1=math.atan2(nxt[1]-center[1],nxt[0]-center[0])
                if code=='G2':
                    while a1>=a0:a1-=2*math.pi
                else:
                    while a1<=a0:a1+=2*math.pi
                count=max(2,math.ceil(abs(a1-a0)/math.radians(5))+1)
                points=[np.array([center[0]+radius*math.cos(a),center[1]+radius*math.sin(a),pos[2]+t*(nxt[2]-pos[2])]) for t,a in zip(np.linspace(0,1,count),np.linspace(a0,a1,count))]
                points[0]=pos.copy();points[-1]=nxt.copy()
            for a,b in zip(points,points[1:]):
                segments.append([a,b]);types.append(category);layers.append(layer_z);extrusions.append(de/(len(points)-1))
                if capture_features:segment_features.append(feature)
            feature_e[feature]=feature_e.get(feature,0.)+de
        pos=nxt
    result=(np.array(segments),np.array(types),np.array(layers),np.array(extrusions),feature_e)
    return result+(np.array(segment_features,dtype=object),) if capture_features else result


def hits_rectangle(segments,lower,upper):
    a=segments[:,0,:2];d=segments[:,1,:2]-a
    lo=np.zeros(len(a));hi=np.ones(len(a));possible=np.ones(len(a),dtype=bool)
    for k in range(2):
        parallel=np.abs(d[:,k])<1e-10
        possible&=~(parallel & ((a[:,k]<lower[k])|(a[:,k]>upper[k])))
        safe=np.where(parallel,1,d[:,k])
        t0=(lower[k]-a[:,k])/safe;t1=(upper[k]-a[:,k])/safe
        lo=np.maximum(lo,np.where(parallel,-np.inf,np.minimum(t0,t1)))
        hi=np.minimum(hi,np.where(parallel,np.inf,np.maximum(t0,t1)))
    return possible & (lo<=hi)
