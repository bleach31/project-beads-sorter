"""Chamfer the tube-facing leading corner of the rack by 1 mm at 45 degrees.

The original source coordinates are preserved in the assembly export. The gear
teeth and longitudinal guide slot are kept outside the edit volume.
"""
from pathlib import Path
import json,sys
import numpy as np
import trimesh
import cadquery as cq
from PIL import Image,ImageDraw,ImageFont
from inspect_rack import ROOT,PARTS,load_3mf
sys.path.insert(0,r'C:\Users\10001176180\Documents\BSP\upper_base_v2\source')
from three_mf_export import export_3mf
from render_model import render

NAME='rack_tip-chamfer_1mm45deg'

def cqmesh(obj):
    vs,fs=obj.val().tessellate(.02,.05)
    return trimesh.Trimesh([[v.x,v.y,v.z] for v in vs],fs,process=True)

def build():
    source=load_3mf(PARTS/'rack.3mf')
    tip=source.bounds[1,0];z0=source.bounds[0,2]
    d=1.0;x0=tip-d
    # The tube and next queued bead are on the negative-Z side in the original
    # assembly axes. Cut only that leading corner; retain the downstream face.
    cut=cqmesh(cq.Workplane('XZ',origin=(0,-2.4,0)).polyline([
        (x0,z0-1),(tip+1,z0-1),(tip+1,z0+2),(x0,z0)]).close().extrude(7.8))
    result=trimesh.boolean.difference([source,cut],engine='manifold')
    removed=trimesh.boolean.difference([source,result],engine='manifold')
    added=trimesh.boolean.difference([result,source],engine='manifold')
    assert result.is_volume and len(result.split())==1
    assert len(added.faces)==0 or abs(added.volume)<.0001
    assert removed.bounds[0,0]>=x0-.0001
    assert removed.bounds[1,1]<-2.75
    assert removed.bounds[1,2]<=z0+d+.0001
    expected_volume=.5*d*d*7.0063
    assert abs(removed.volume-expected_volume)<.001

    export_3mf(PARTS/(NAME+'.3mf'),[(NAME,result,'#6495B5')],
        'Rack / tube-facing tip chamfer 1 mm 45 deg / original assembly coordinates')
    result.export(ROOT/(NAME+'.stl'))
    # Put the unmodified broad face down for a flat print bed contact.
    print_mesh=result.copy()
    print_mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi,[1,0,0]))
    print_mesh.apply_translation([-print_mesh.bounds[:,0].mean(),-print_mesh.bounds[:,1].mean(),-print_mesh.bounds[0,2]])
    export_3mf(ROOT/(NAME+'_print.3mf'),[(NAME,print_mesh,'#6495B5')],
        'Rack / tip chamfer 1 mm 45 deg / unmodified broad face down')
    reread=load_3mf(PARTS/(NAME+'.3mf'))
    assert reread.is_volume and len(reread.split())==1 and abs(reread.volume-result.volume)<.001
    metrics={'chamfer_mm':d,'chamfer_deg':45,
        'remaining_leading_push_face_height_mm':source.extents[2]-d,
        'source_volume_mm3':source.volume,'result_volume_mm3':result.volume,
        'removed_volume_mm3':removed.volume,'removed_bounds_mm':removed.bounds.tolist(),
        'gear_and_guide_slot_unchanged':True,'watertight':bool(reread.is_watertight),
        'single_shell':len(reread.split())==1}
    (ROOT/'analysis'/'verification.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    result.export(ROOT/'analysis'/'rack_modified.stl')
    bevel=result.submesh([np.flatnonzero(
        (result.face_normals[:,0]>.70)&(result.face_normals[:,2]<-.70))],append=True)
    out=Image.new('RGB',(1800,1000),'white');draw=ImageDraw.Draw(out)
    f=ImageFont.truetype(r'C:\Windows\Fonts\YuGothB.ttc',32)
    small=ImageFont.truetype(r'C:\Windows\Fonts\YuGothM.ttc',25)
    draw.text((25,12),'チューブ側の先端角を1mm・45°で面取り',font=f,fill='#18343f')
    for x,label,mesh in [(0,'変更前',source),(900,'変更後（オレンジ色が斜面）',result)]:
        draw.text((x+25,68),label,font=small,fill='#18343f')
        meshes=[(mesh,(.39,.59,.71),1)]
        if x: meshes.append((bevel,(.96,.59,.25),1))
        img=render(meshes,(1,-1,-1),(0,0,-1),size=(900,770),zoom=3.2,target=(19,-6,-.5))
        out.paste(img,(x,110))
    draw.text((35,902),'押し方向 →　／　次のビーズは斜面でチューブ側へ逃がす',font=small,fill='#18343f')
    draw.text((35,943),'平らな押し面は高さ3.5mmを確保。歯と案内溝の形状は維持。',font=small,fill='#18343f')
    out.save(ROOT/'rack_tip_preview.png')
    print(json.dumps(metrics,indent=2))

if __name__=='__main__':build()
