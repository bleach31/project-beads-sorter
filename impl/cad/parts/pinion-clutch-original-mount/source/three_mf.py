import zipfile
import xml.etree.ElementTree as ET

def export_3mf(path, objects, title):
    ns = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
    ET.register_namespace('', ns)
    tag = lambda s: '{'+ns+'}'+s
    model = ET.Element(tag('model'), {'unit':'millimeter', '{http://www.w3.org/XML/1998/namespace}lang':'ja-JP'})
    ET.SubElement(model, tag('metadata'), {'name':'Title'}).text = title
    resources = ET.SubElement(model, tag('resources'))
    build = ET.SubElement(model, tag('build'))
    for i, (name, m) in enumerate(objects, 1):
        o = ET.SubElement(resources, tag('object'), {'id':str(i), 'type':'model', 'name':name})
        me = ET.SubElement(o, tag('mesh'))
        vs, fs = ET.SubElement(me, tag('vertices')), ET.SubElement(me, tag('triangles'))
        for v in m.vertices:
            ET.SubElement(vs, tag('vertex'), {k:f'{v[j]:.7f}' for j,k in enumerate('xyz')})
        for f in m.faces:
            ET.SubElement(fs, tag('triangle'), {f'v{j+1}':str(int(f[j])) for j in range(3)})
        ET.SubElement(build, tag('item'), {'objectid':str(i)})
    ct = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'
    rel = '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rel0" Target="/3D/3dmodel.model" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ct)
        z.writestr('_rels/.rels', rel)
        z.writestr('3D/3dmodel.model', ET.tostring(model, encoding='utf-8', xml_declaration=True))
