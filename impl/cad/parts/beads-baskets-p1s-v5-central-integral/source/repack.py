"""Re-export unchanged STLs at the reviewed compact P1S placements."""
from pathlib import Path
import json,math,zipfile,shutil,xml.etree.ElementTree as ET
import numpy as np
import trimesh

def export(root,manifest):
    ns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
    ET.register_namespace('',ns)
    def tag(x):return '{'+ns+'}'+x
    meshes={p.stem:trimesh.load_mesh(p,process=False) for folder in ['stl','optional_reprint_stl'] for p in (root/folder).glob('*.stl')}
    for entry in manifest:
        path=root/'plates'/entry['file']
        path.parent.mkdir(exist_ok=True)
        if entry['file']=='01_motion_test_complete.3mf':
            # Preserve the already-reviewed first plate byte for byte.
            shutil.copy2(root/'source'/'reference_motion_plate.3mf',path)
            print(entry['file'],'unchanged reference',flush=True)
            continue
        model=ET.Element(tag('model'),unit='millimeter')
        ET.SubElement(model,tag('metadata'),name='Title').text=path.stem
        ET.SubElement(model,tag('metadata'),name='Description').text='Bambu P1S compact layout. Geometry only. Print by layer. No printer/material/process/support profiles or G-code. '+entry['notes']
        resources=ET.SubElement(model,tag('resources'))
        mats=ET.SubElement(resources,tag('basematerials'),id='1')
        ET.SubElement(mats,tag('base'),name='Single material',displaycolor='#77AAA2FF')
        build=ET.SubElement(model,tag('build'))
        for i,item in enumerate(entry['objects']):
            m=meshes[item['part']].copy();m.merge_vertices(digits_vertex=6)
            a=math.radians(item['rotation_z_deg'])
            rotation=np.array([[math.cos(a),-math.sin(a),0],[math.sin(a),math.cos(a),0],[0,0,1]])
            vertices=m.vertices@rotation.T+np.array([*item['center_xy_mm'],0])
            obj=ET.SubElement(resources,tag('object'),id=str(i+2),name=item['part']+f'_{i+1:02d}',type='model',pid='1',pindex='0')
            mesh=ET.SubElement(obj,tag('mesh'));vs=ET.SubElement(mesh,tag('vertices'));fs=ET.SubElement(mesh,tag('triangles'))
            for v in vertices:ET.SubElement(vs,tag('vertex'),**{key:f'{float(x):.6f}' for key,x in zip(['x','y','z'],v)})
            for f in m.faces:ET.SubElement(fs,tag('triangle'),**{key:str(int(x)) for key,x in zip(['v1','v2','v3'],f)})
            ET.SubElement(build,tag('item'),objectid=str(i+2))
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('3D/3dmodel.model',ET.tostring(model,encoding='utf-8',xml_declaration=True))
            z.writestr('[Content_Types].xml','<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
            z.writestr('_rels/.rels','<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        print(entry['file'],len(entry['objects']),flush=True)
    (root/'plate_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    source=Path(__file__).resolve().parent
    root=source.parent
    export(root,json.loads((source/'compact_layouts.json').read_text(encoding='utf-8')))
