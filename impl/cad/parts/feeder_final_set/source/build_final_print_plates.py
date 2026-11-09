"""Repack adopted, unmodified feeder meshes. No reference hardware is printable."""
from pathlib import Path
import json, math, sys, shutil, hashlib
import numpy as np
import trimesh
from shapely.geometry import MultiPoint, Point, box
from shapely.affinity import translate, rotate

ROOT=Path(__file__).resolve().parents[1]; WS=ROOT.parent
from three_mf_export import export_3mf

SOURCES=[('feeder_v7_short_m3',n) for n in ['01_funnel','04_bearing_cartridge','05_lower_cap','06_upper_cap','07_shaft_collar','08_motor_cradle','09_motor_spacer_left','10_motor_spacer_right']]+[('feeder_v8_rotor_trials','C_curved_rod')]+[('feeder_v9_height_adjust',n) for n in ['01_fixed_frame','02_moving_bridge','03_guide_shoe','04_screw_bridge','05_head_keeper']]

def main():
    for p in ['plates','slicer','print']:(ROOT/p).mkdir(parents=True,exist_ok=True)
    data={}
    for version,name in SOURCES:
        group={'feeder_v7_short_m3':'body','feeder_v8_rotor_trials':'rotor','feeder_v9_height_adjust':'height_adjust'}[version]
        src=ROOT/'parts'/group/f'{name}.stl'; mesh=trimesh.load(src,force='mesh')
        assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume>0
        hull=MultiPoint(mesh.vertices[:,:2]).convex_hull
        shape=hull.buffer(3)
        if name=='C_curved_rod':shape=Point(0,0).buffer(20)
        data[name]=dict(mesh=mesh,shape=shape,version=version,path=src)
    occupied=[]; layout={}; bed=box(3,3,253,253); excluded=box(-10,-10,20,30)
    def place(name,x,y,a=0):
        s=translate(rotate(data[name]['shape'],a,origin=(0,0)),x,y)
        assert bed.covers(s) and not s.intersects(excluded)
        assert not any(s.intersects(q) for q in occupied)
        occupied.append(s);layout[name]=dict(x=x,y=y,angle_deg=a)
    place('01_funnel',72,72)
    place('01_fixed_frame',184,184)
    remaining=[n for _,n in SOURCES if n not in layout]
    remaining.sort(key=lambda n:data[n]['shape'].area,reverse=True)
    for name in remaining:
        found=False
        for a in [0,90]:
            s0=rotate(data[name]['shape'],a,origin=(0,0));minx,miny,maxx,maxy=s0.bounds
            for y in np.arange(math.ceil(3-miny),math.floor(253-maxy)+1,3):
                for x in np.arange(math.ceil(3-minx),math.floor(253-maxx)+1,3):
                    s=translate(s0,x,y)
                    if not bed.covers(s) or s.intersects(excluded) or any(s.intersects(q) for q in occupied):continue
                    place(name,float(x),float(y),a);found=True;break
                if found:break
            if found:break
        if not found:raise RuntimeError('Cannot pack '+name)
    objects=[];records=[]
    for version,name in SOURCES:
        m=data[name]['mesh'].copy();p=layout[name]
        m.apply_transform(trimesh.transformations.rotation_matrix(math.radians(p['angle_deg']),[0,0,1]))
        m.apply_translation([p['x'],p['y'],-m.bounds[0,2]])
        objects.append((name,m,'#E89A45' if name=='C_curved_rod' else '#738F9A'))
        records.append(dict(name=name,source=str(data[name]['path'].relative_to(ROOT)),source_version=version,source_sha256=hashlib.sha256(data[name]['path'].read_bytes()).hexdigest(),**p,bounds=m.bounds.tolist(),triangles=len(m.faces)))
    export_3mf(ROOT/'plates/01_feeder_geometry.3mf',objects,'Adopted feeder: V7 base, C rotor, V9 height adjustment')
    c=data['C_curved_rod']['mesh'].copy();c.apply_translation([128,128,-c.bounds[0,2]])
    export_3mf(ROOT/'plates/optional_rotor_C_geometry.3mf',[('C_curved_rod',c,'#E89A45')],'Replacement rotor C only')
    (ROOT/'source/final_feeder_plate_layout.json').write_text(json.dumps(dict(units='mm',parts=records,packing_clearance='Convex model projections offset 3 mm; C reserved radius 20 mm; edge margin 3 mm; excluded area expanded to 20 x 30 mm.'),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(layout,indent=2))
if __name__=='__main__':main()
