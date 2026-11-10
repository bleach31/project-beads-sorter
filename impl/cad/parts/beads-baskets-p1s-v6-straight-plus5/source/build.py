"""Export the changed chute, two new print plates and updated operating view.

Unchanged STL/containers/storage assets are supplied as frozen files.
No printer presets, support geometry or G-code are generated here.
"""
from pathlib import Path
import json,math,hashlib,itertools,zipfile,xml.etree.ElementTree as ET
import numpy as np
import trimesh
from shapely.geometry import MultiPoint,box
import chute_plus5 as c

ROOT=Path(__file__).resolve().parent.parent
NAME='smooth_u_chute_plus5'
NS='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'

def write_3mf(path,items,title,description,single_material=True):
    ET.register_namespace('',NS);tag=lambda k:'{'+NS+'}'+k
    doc=ET.Element(tag('model'),unit='millimeter')
    ET.SubElement(doc,tag('metadata'),name='Title').text=title
    ET.SubElement(doc,tag('metadata'),name='Description').text=description
    resources=ET.SubElement(doc,tag('resources'));mats=ET.SubElement(resources,tag('basematerials'),id='1')
    build=ET.SubElement(doc,tag('build'))
    if single_material:ET.SubElement(mats,tag('base'),name='One material',displaycolor='#77AAA2FF')
    for i,(name,mesh,color) in enumerate(items):
        if not single_material:ET.SubElement(mats,tag('base'),name=name,displaycolor=color)
        obj=ET.SubElement(resources,tag('object'),id=str(i+2),name=name,type='model',pid='1',pindex='0' if single_material else str(i))
        model=ET.SubElement(obj,tag('mesh'));vs=ET.SubElement(model,tag('vertices'));fs=ET.SubElement(model,tag('triangles'))
        for row in mesh.vertices:ET.SubElement(vs,tag('vertex'),**{k:f'{float(x):.6f}' for k,x in zip(['x','y','z'],row)})
        for row in mesh.faces:ET.SubElement(fs,tag('triangle'),**{k:str(int(x)) for k,x in zip(['v1','v2','v3'],row)})
        ET.SubElement(build,tag('item'),objectid=str(i+2))
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('3D/3dmodel.model',ET.tostring(doc,encoding='utf-8',xml_declaration=True))
        z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')

def assembly_items(shape):
    arr=np.load(ROOT/'source/reference/v5-operating.npz',allow_pickle=False)
    names=json.loads(str(arr['names']));items=[]
    for i,name in enumerate(names):
        color=str(arr[f'c{i}'])
        if name=='smooth_u_chute':
            m=c.mesh(shape.rotate([0,0,117.5]).translate([0,0,46]));name=NAME;color='#D7AA66FF'
        else:m=trimesh.Trimesh(arr[f'v{i}'],arr[f'f{i}'],process=False)
        items.append((name,m,color))
    return items

def export_plates():
    cfg=json.loads((ROOT/'source/plate_layouts.json').read_text(encoding='utf-8'))
    allowance=cfg['external_allowance_mm'];bed=box(0,0,256,256);keepout=box(*cfg['keep_out_xy_mm'])
    report=[]
    for plate in cfg['plates']:
        items=[];polygons={};parts=[]
        for e in plate['objects']:
            file=ROOT/'stl'/(e['part']+'.stl');m=trimesh.load_mesh(file,process=True)
            assert m.is_watertight and m.is_winding_consistent and m.volume>0
            a=math.radians(e['rotation_z_deg']);mat=np.eye(4)
            mat[:3,:3]=[[math.cos(a),-math.sin(a),0],[math.sin(a),math.cos(a),0],[0,0,1]]
            mat[:2,3]=e['center_xy_mm'];m.apply_transform(mat)
            p=MultiPoint(m.vertices[:,:2]).convex_hull
            assert bed.covers(p.buffer(allowance)),('bed',e['instance'])
            assert not keepout.intersects(p.buffer(allowance)),('keepout',e['instance'])
            assert abs(m.bounds[0,2])<1e-5 and m.bounds[1,2]<256
            polygons[e['instance']]=p;items.append((e['instance'],m,'#77AAA2FF'))
            parts.append({'name':e['instance'],'part':e['part'],'stl_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
                          'bounds_mm':m.bounds.tolist(),'triangles':len(m.faces)})
        pairs=[]
        for a,b in itertools.combinations(polygons,2):
            gap=polygons[a].distance(polygons[b]);assert gap>=2*allowance-1e-5,(a,b,gap)
            pairs.append({'a':a,'b':b,'convex_footprint_gap_mm':gap})
        write_3mf(ROOT/'print'/plate['file'],items,plate['title'],
            'Geometry and placement only. Print BY LAYER at 100 percent. No printer, process, material or support settings or G-code. Normal external supports for the base and chute; brim at most 5 mm; keep channel and socket free of supports.')
        report.append({'file':plate['file'],'object_count':len(items),'parts':parts,'pairs':pairs,
                       'minimum_gap_mm':min(x['convex_footprint_gap_mm'] for x in pairs),'external_allowance_mm':allowance,
                       'single_material':True,'sliced':False,'valid':True})
    (ROOT/'verification/plate-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

def main():
    shape=c.build_chute();m=c.mesh(shape);t=c.print_transform(shape)
    printable=c.mesh(c.preferred_print_orientation(shape));path=ROOT/'stl'/(NAME+'.stl');printable.export(path)
    saved=trimesh.load_mesh(path,process=True)
    data=c.metadata();data.update({'assembly_bbox_mm':m.bounds.tolist(),'print_bbox_mm':saved.bounds.tolist(),
        'print_size_mm':saved.extents.tolist(),'assembly_to_print_matrix':t.tolist(),'mesh_triangles':len(saved.faces),
        'volume_mm3':float(m.volume),'stl_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'print_orientation_y_degrees':c.SLOPE_ANGLE,'sliced':False})
    (ROOT/'verification/design-metadata.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    plates=export_plates();items=assembly_items(shape)
    write_3mf(ROOT/'assembly/VIEW_ONLY_operating_plus5.3mf',items,
        'VIEW ONLY - constant slope plus5 with unchanged v5 baskets and drive',
        'Assembly inspection only; not a print plate. The chute is replaced, all other operating view geometry is frozen v5 reference.',False)
    scene={}
    for name,mesh,color in items:
        v=mesh.copy();v.visual.face_colors=np.array(list(bytes.fromhex(color[1:])),dtype=np.uint8);scene[name]=v
    trimesh.Scene(scene).export(ROOT/'assembly/VIEW_ONLY_operating_plus5.glb')
    print(json.dumps({'model':data,'plates':[{'file':p['file'],'count':p['object_count'],'minimum_gap_mm':p['minimum_gap_mm']} for p in plates]},indent=2))

if __name__=='__main__':main()
