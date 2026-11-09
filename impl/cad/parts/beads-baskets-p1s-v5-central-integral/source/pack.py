"""Place six unchanged print meshes on one P1S plate; geometry only."""
from pathlib import Path
import json,math,hashlib,itertools,zipfile,xml.etree.ElementTree as ET
import numpy as np
import trimesh
from shapely.geometry import MultiPoint,box
from shapely import affinity
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parent.parent
NS='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
COLOR=['#729c96','#cf984e','#c6ac66','#8caca6','#daab65','#adc2bc']

def main():
    cfg=json.loads((ROOT/'source/layout.json').read_text(encoding='utf-8'))
    for name in ['print','verification','images']:(ROOT/name).mkdir(exist_ok=True)
    allowance=cfg['external_allowance_mm'];bed=box(0,0,256,256);keepout=box(*cfg['keep_out_xy_mm'])
    meshlist=[];footprints={};reports=[]
    for e in cfg['objects']:
        file=ROOT/'stl'/(e['part']+'.stl');m=trimesh.load_mesh(file,process=True)
        assert m.is_watertight and m.is_winding_consistent and m.volume>0
        assert abs(m.bounds[0,2])<1e-4 and m.bounds[1,2]<256
        a=math.radians(e['rotation_z_deg']);rot=np.array([[math.cos(a),-math.sin(a),0],[math.sin(a),math.cos(a),0],[0,0,1]])
        v=m.vertices@rot.T+np.array([*e['center_xy_mm'],0])
        p=MultiPoint(v[:,:2]).convex_hull
        assert bed.covers(p.buffer(allowance)),('bed',e['part'],p.bounds)
        assert not keepout.intersects(p.buffer(allowance)),('keepout',e['part'])
        meshlist.append((e['part'],v,m.faces));footprints[e['part']]=p
        reports.append({'part':e['part'],'source_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
                        'triangles':len(m.faces),'bounds_mm':[v.min(0).tolist(),v.max(0).tolist()],
                        'watertight':True,'single_shell':len(m.split())==1,
                        'external_allowance_mm':allowance,'bed_and_keepout_pass':True})
    pairs=[]
    for a,b in itertools.combinations(footprints,2):
        distance=footprints[a].distance(footprints[b]);assert distance>=2*allowance-1e-5,(a,b,distance)
        pairs.append({'a':a,'b':b,'convex_footprint_gap_mm':distance})
    ET.register_namespace('',NS);tag=lambda k:'{'+NS+'}'+k
    model=ET.Element(tag('model'),unit='millimeter')
    ET.SubElement(model,tag('metadata'),name='Title').text='P1S - six lower motion parts with plus20 chute'
    ET.SubElement(model,tag('metadata'),name='Description').text='Print all six parts once BY LAYER. Geometry and placement only. No printer/process/material/support settings or G-code. External normal supports on base and chute, brim approximately 5 mm. Do not rescale or auto-orient.'
    res=ET.SubElement(model,tag('resources'));materials=ET.SubElement(res,tag('basematerials'),id='1')
    ET.SubElement(materials,tag('base'),name='One material',displaycolor='#77AAA2FF')
    build=ET.SubElement(model,tag('build'))
    for i,(name,v,f) in enumerate(meshlist):
        obj=ET.SubElement(res,tag('object'),id=str(i+2),name=name,type='model',pid='1',pindex='0')
        mesh=ET.SubElement(obj,tag('mesh'));vs=ET.SubElement(mesh,tag('vertices'));fs=ET.SubElement(mesh,tag('triangles'))
        for row in v:ET.SubElement(vs,tag('vertex'),**{k:f'{float(x):.6f}' for k,x in zip(['x','y','z'],row)})
        for row in f:ET.SubElement(fs,tag('triangle'),**{k:str(int(x)) for k,x in zip(['v1','v2','v3'],row)})
        ET.SubElement(build,tag('item'),objectid=str(i+2))
    target=ROOT/'print/01_motion_complete_plus20_P1S.3mf'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('3D/3dmodel.model',ET.tostring(model,encoding='utf-8',xml_declaration=True))
        z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    out={'date':'2026-11-09','objects':reports,'pairs':pairs,'minimum_gap_mm':min(q['convex_footprint_gap_mm'] for q in pairs),
         'print_plate_count':1,'objects_per_plate':6,'print_repeats':1,'all_print_orientations_preserved':True,
         'support_check_scope':'Convex XY envelopes expanded by 5 mm; actual supports have not been sliced.',
         'sliced':False,'valid':True}
    (ROOT/'verification/layout-checks.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    render(cfg,footprints)
    print(json.dumps(out,indent=2))

def render(cfg,polygons):
    im=Image.new('RGB',(1500,1120),'#f3f5f2');d=ImageDraw.Draw(im)
    font=lambda n:ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc',n)
    def txt(x,y,t,n=25,col='#284347'):d.text((x,y),t,font=font(n),fill=col)
    txt(40,30,'延長スロープ＋従来5部品を1枚に配置',36)
    txt(43,93,'P1S / 256 × 256 mm / 各1個 / 「層ごと」で印刷',24,'#657773')
    ox,oy,sc=63,180,3.25
    def xy(points):return [(ox+x*sc,oy+(256-y)*sc) for x,y in points]
    d.rectangle((ox,oy,ox+256*sc,oy+256*sc),fill='#fffefa',outline='#657c74',width=3)
    for v in range(32,256,32):
        d.line((ox+v*sc,oy,ox+v*sc,oy+256*sc),fill='#e7ebe5',width=1)
        d.line((ox,oy+v*sc,ox+256*sc,oy+v*sc),fill='#e7ebe5',width=1)
    d.rectangle((ox,oy+(256-28)*sc,ox+18*sc,oy+256*sc),fill='#ebc0b2')
    txt(960,182,'印刷する6部品',28)
    for i,e in enumerate(cfg['objects']):
        p=polygons[e['part']]
        d.polygon(xy(p.buffer(5).exterior.coords),fill='#e2e8df')
        d.polygon(xy(p.exterior.coords),fill=COLOR[i],outline='#4d6963',width=2)
        x,y=xy([(p.centroid.x,p.centroid.y)])[0]
        d.ellipse((x-18,y-18,x+18,y+18),fill='#ffffff',outline='#58736a',width=2)
        txt(x-8,y-17,str(i+1),22)
        d.ellipse((955,245+i*68,990,280+i*68),fill=COLOR[i],outline='#58736a',width=1)
        txt(966,245+i*68,str(i+1),21)
        txt(1007,245+i*68,e['label'],23)
    txt(955,715,'淡い縁：周囲5 mmの余白',24)
    txt(955,762,'左手前の赤い範囲は避けています。',22)
    txt(955,818,'ベースとスロープは通常サポート。',22)
    txt(955,856,'ブリムは5 mm程度。単色印刷できます。',21)
    txt(955,909,'投影形状を囲む凸包による配置図です。',19,'#657773')
    txt(955,942,'穴や凹部は省略しています。',19,'#657773')
    txt(43,1046,'形状と配置のみ。プリンター設定やG-codeは含みません。スライスと実際の印刷は未実施。',22,'#637773')
    im.save(ROOT/'images/plate-layout.png')

if __name__=='__main__':main()
