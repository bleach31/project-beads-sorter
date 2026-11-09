from pathlib import Path
import zipfile,xml.etree.ElementTree as ET,sys
import numpy as np
import trimesh
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
PARTS=ROOT.parent
sys.path.insert(0,r'C:\Users\10001176180\Documents\BSP\upper_base_v2\source')
from render_model import render

def load_3mf(path):
    ns={'c':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
    with zipfile.ZipFile(path) as z: root=ET.fromstring(z.read('3D/3dmodel.model'))
    v=[[float(a.attrib[k]) for k in 'xyz'] for a in root.find('.//c:vertices',ns)]
    f=[[int(a.attrib[k]) for k in ('v1','v2','v3')] for a in root.find('.//c:triangles',ns)]
    return trimesh.Trimesh(v,f,process=True)

if __name__=='__main__':
    (ROOT/'analysis').mkdir(parents=True,exist_ok=True)
    r=load_3mf(PARTS/'rack.3mf');b=load_3mf(PARTS/'upper-base_LED-filled_M3-clamp.3mf')
    # The copied repository base was renamed after export in its print pose.
    # Restore the known source pose before comparing it with the original rack.
    reference=load_3mf(Path(r'C:\Users\10001176180\Documents\BSP\upper_base_v2\parts\upper-base_LED-filled_M3-clamp.3mf'))
    rotated=reference.copy();rotation=trimesh.transformations.rotation_matrix(3*np.pi/4,[1,0,0]);rotated.apply_transform(rotation)
    shift=np.array([-rotated.bounds[:,0].mean(),-rotated.bounds[:,1].mean(),-rotated.bounds[0,2]])
    restored=b.copy();restored.apply_translation(-shift);restored.apply_transform(np.linalg.inv(rotation))
    assert abs(reference.volume-restored.volume)<.01
    assert np.allclose(reference.bounds,restored.bounds,atol=.0001)
    b=restored
    r.export(ROOT/'analysis'/'rack_original.stl');b.export(ROOT/'analysis'/'upper_base_reference.stl')
    out=Image.new('RGB',(1800,1450),'white');draw=ImageDraw.Draw(out)
    font=ImageFont.truetype(r'C:\Windows\Fonts\YuGothB.ttc',26)
    for i,(label,meshes,d,up,zoom,target) in enumerate([
        ('ラック単体：チューブ側の面',[(r,(.94,.65,.27),1)],(1,-1,-1),(0,0,-1),1,None),
        ('ラック：先端の拡大',[(r,(.94,.65,.27),1)],(1,-1,-1),(0,0,-1),3.0,(19,-6,0)),
        ('UpperBaseとの位置関係（座標を復元）',[(b,(.39,.59,.71),.6),(r,(.94,.65,.27),1)],(1,1,-.7),(0,0,-1),1,None),
        ('押し方向：+X / チューブ側：-Z',[(b,(.39,.59,.71),.25),(r,(.94,.65,.27),1)],(0,1,0),(0,0,-1),1,None),
    ]):
        x=i%2*900;y=i//2*725
        draw.text((x+20,y+5),label,font=font,fill='#18343f')
        out.paste(render(meshes,d,up,size=(900,675),zoom=zoom,target=target),(x,y+45))
    out.save(ROOT/'analysis'/'rack_inspection.png')
    print('Rack',r.bounds.tolist(),'closed',r.is_volume)
    print('Base',b.bounds.tolist(),'closed',b.is_volume)
    for name in ['camera-mount.3mf','pinion.3mf']:
        m=load_3mf(PARTS/name);print(name,m.bounds.tolist())
