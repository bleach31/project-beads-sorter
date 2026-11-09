"""Read back geometry, actual first-layer and support/raft paths in final plates."""
from pathlib import Path
import sys,json,zipfile,xml.etree.ElementTree as ET
import numpy as np
import trimesh
from scipy.spatial import cKDTree,ConvexHull
from shapely.geometry import MultiPoint,Point
from shapely import contains_xy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Rectangle
from matplotlib.font_manager import FontProperties
ROOT=Path(__file__).resolve().parents[1];WS=ROOT.parent
from gcode_helpers import points_3mf,read_paths,hits_rectangle
NS={'c':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
FONT=FontProperties(fname=r'C:\Windows\Fonts\YuGothM.ttc')

def meshes(path):
    with zipfile.ZipFile(path) as z:r=ET.fromstring(z.read('3D/3dmodel.model'))
    out={}
    for o in r.findall('c:resources/c:object',NS):
        v=np.array([[float(e.get(k)) for k in 'xyz'] for e in o.findall('c:mesh/c:vertices/c:vertex',NS)])
        f=np.array([[int(e.get(k)) for k in ['v1','v2','v3']] for e in o.findall('c:mesh/c:triangles/c:triangle',NS)])
        out[o.get('name')]=trimesh.Trimesh(vertices=v,faces=f,process=True)
    return out

def one(kind):
    base=ROOT/'slicer'/kind;summary=json.loads((base/'slice_summary.json').read_text(encoding='utf-8'))
    source=ROOT/summary['source'];sliced=ROOT/summary['sliced_project'];plate=summary['result']['sliced_plates'][0]
    sv,st,sb=points_3mf(source);pv,pt,pb=points_3mf(sliced)
    dev=max(cKDTree(sv).query(pv)[0].max(),cKDTree(pv).query(sv)[0].max())
    assert st==pt and dev<5e-5 and len(pb)==(14 if kind=='feeder' else 1)
    mm=meshes(source);names=list(mm);hulls={n:MultiPoint(m.vertices[:,:2]).convex_hull for n,m in mm.items()}
    for n,m in mm.items():assert m.is_watertight and m.is_winding_consistent and m.volume>0,n
    seg,typ,layers,e,features=read_paths(base/'logs/plate_1.gcode')
    seg[:,:,:2]+=[0,2]
    xyz=seg.reshape((-1,3));lo=xyz.min(0);hi=xyz.max(0)
    assert lo[:2].min()>.25 and hi[:2].max()<255.75
    excluded=int(hits_rectangle(seg,[-.25,-.25],[18.25,28.25]).sum());assert excluded==0
    mid=seg[:,:,:2].mean(1);assignment=np.full(len(seg),-1);coverage=np.zeros(len(seg),int)
    cc=mm['C_curved_rod'].bounds[:,:2].mean(0)
    regions={n:(Point(*cc).buffer(20) if n=='C_curved_rod' else h.buffer(3)) for n,h in hulls.items()}
    for i,n in enumerate(names):
        chosen=contains_xy(regions[n],mid[:,0],mid[:,1]);assignment[chosen]=i;coverage+=chosen
    assert np.all(coverage==1),np.unique(coverage,return_counts=True)
    per={};envelopes={};first=np.isclose(layers,.2)
    for i,n in enumerate(names):
        chosen=assignment==i;model=chosen&(typ==0);support=chosen&(typ==1);brim=chosen&(typ==2)
        endpoints=seg[chosen,:,:2].reshape((-1,2));envelopes[n]=MultiPoint(endpoints).convex_hull.buffer(.25)
        rec=dict(first_model_layer_z=float(layers[model].min()),initial_model_segments=int((model&first).sum()),initial_support_segments=int((support&first).sum()),support_segments=int(support.sum()),brim_segments=int(brim.sum()),print_extrusion_mm=float(e[chosen].sum()))
        if n=='C_curved_rod':
            raft=support&(layers<=.5+1e-7);above=support&~raft
            assert support.any() and raft.any() and not brim.any() and not rec['initial_model_segments']
            assert rec['initial_support_segments']>0 and set(np.round(np.unique(layers[raft]),4))=={.2,.5}
            xy=seg[raft,:,:2].reshape((-1,2));hull=ConvexHull(xy)
            covered=lambda p:bool(np.all(p@hull.equations[:,:2].T+hull.equations[:,2]<=.25))
            fm=seg[model&np.isclose(layers,rec['first_model_layer_z']),:,:2].reshape((-1,2))
            rootz=float(layers[above].min());roots=seg[above&np.isclose(layers,rootz),:,:2].reshape((-1,2))
            rec.update(actual_raft_layers=[.2,.5],raft_covers_first_model=covered(fm),raft_covers_support_roots=covered(roots),support_max_z_mm=float(seg[support,:,-1].max()),support_max_radius_mm=float(np.linalg.norm(seg[support,:,:2]-cc,axis=2).max()))
            assert covered(fm) and covered(roots)
        else:assert rec['initial_model_segments']>0 and rec['support_segments']==0 and rec['brim_segments']>0,n
        per[n]=rec
    gaps={}
    for i,a in enumerate(names):
        for b in names[i+1:]:
            d=envelopes[a].distance(envelopes[b]);assert d>0,(a,b,d);gaps[a+'/'+b]=d
    report=dict(slicer=summary['slicer'],plate_count=1,object_count=len(mm),geometry_preserved=True,max_project_vertex_deviation_mm=float(dev),triangle_count=st,all_source_meshes_closed=True,settings_preserved=True,all_objects_start_z0=all(abs(b[0][2])<1e-5 for b in pb),estimated_seconds=plate['total_predication'],estimated_filament_g=sum(f['total_used_g'] for f in plate['filaments']),warnings=plate.get('warning_message',''),official_nozzle_offset_xy_mm=[0,2],extrusion_bounds_mm=[lo.tolist(),hi.tolist()],all_print_paths_inside_bed=True,paths_touching_expanded_exclusion=excluded,support_enabled_objects=['C_curved_rod'],per_object=per,minimum_print_path_envelope_clearance_mm=min(gaps.values()) if gaps else None,printer_transmission_performed=False,verification_scope='All positive model/support/brim extrusion after layer markers; machine startup/end custom G-code excluded.')
    assert not report['warnings'] and plate['filament_change_times']==0
    report['all_checks_passed']=True
    (base/'toolpath_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if kind=='feeder':preview(mm,seg,typ,layers,report)
    print(kind,json.dumps({k:v for k,v in report.items() if k!='per_object'},ensure_ascii=False),flush=True)

def preview(mm,seg,typ,layers,report):
    out=ROOT/'preview';out.mkdir(exist_ok=True)
    fig,ax=plt.subplots(figsize=(10,11));fig.patch.set_facecolor('#f7f9fb')
    for n,m in mm.items():
        h=MultiPoint(m.vertices[:,:2]).convex_hull;xy=np.array(h.exterior.coords)
        ax.fill(xy[:,0],xy[:,1],color='#e7edf0',zorder=0)
        c=m.bounds[:,:2].mean(0)
        label={'01_funnel':'Funnel','01_fixed_frame':'Fixed frame','04_bearing_cartridge':'Bearing case','05_lower_cap':'Lower cap','06_upper_cap':'Upper cap','07_shaft_collar':'Collar','08_motor_cradle':'Motor cradle','09_motor_spacer_left':'L','10_motor_spacer_right':'R','C_curved_rod':'Rotor C','02_moving_bridge':'Moving bridge','03_guide_shoe':'Guide shoe','04_screw_bridge':'Screw bridge','05_head_keeper':'Head keeper'}[n]
        ax.text(*c,label,ha='center',va='center',fontsize=8,bbox=dict(facecolor='white',edgecolor='none',alpha=.85,pad=1),zorder=5)
    first=np.isclose(layers,.2)
    for t,col in [(2,'#8597a0'),(1,'#d68d2d'),(0,'#2e6579')]:
        s=seg[(typ==t)&first]
        ax.add_collection(LineCollection(s[:,:,:2],colors=col,linewidths=.5))
    ax.add_patch(Rectangle((0,0),18,28,facecolor='#f7cece',edgecolor='#be7777'))
    ax.set(xlim=(0,256),ylim=(0,256),xlabel='X [mm]',ylabel='Y [mm]');ax.set_aspect('equal');ax.grid(alpha=.15)
    mins=round(report['estimated_seconds']/60)
    fig.suptitle('最終フィーダー本体：14部品・1プレート',fontproperties=FONT,fontsize=19,x=.08,ha='left',y=.97)
    fig.text(.08,.925,f'P1S / PLA / 0.4mm / 積層0.16mm　推定 {mins//60}時間{mins%60:02d}分・{report["estimated_filament_g"]:.1f}g',fontproperties=FONT,fontsize=11)
    fig.text(.08,.07,'青：モデルの初層　橙：Cのラフト　灰：2mmブリム　薄灰：全体の投影',fontproperties=FONT,fontsize=10)
    fig.text(.08,.043,'Cのみツリーサポート＋2層ラフト。他13部品はサポートなし。台座は別プレート。',fontproperties=FONT,fontsize=10)
    fig.subplots_adjust(left=.09,right=.97,top=.89,bottom=.12)
    fig.savefig(out/'final_feeder_print_plate.png',dpi=155,facecolor=fig.get_facecolor());plt.close(fig)

if __name__=='__main__':
    for kind in ['feeder','rotor']:one(kind)
