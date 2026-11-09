"""PLA detent-clutch trials. mm. Original external tooth mesh is retained.

Run with numpy, shapely, manifold3d, trimesh, matplotlib, Pillow and vtk.
No printer transmission. Each output is a prototype, not a calibrated limiter.
"""
from pathlib import Path
import sys, json, math, zipfile, hashlib
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
import manifold3d as mf
from shapely.geometry import Point, LineString, Polygon
from shapely.ops import unary_union
from shapely import affinity

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'reference' / 'pinion_original.3mf'
if not SOURCE.is_file():
    SOURCE = ROOT.parent / 'pinion.3mf'
TAU = 2 * math.pi
PHASE = -1.354  # original tooth-tip centres; 12 pockets behind the 12 teeth
LAND_R = 5.30
POCKET_CENTRE_R = 4.85
POCKET_R = .85
ARM_OUTER_R = 5.05
ARM_ANGLE = 125
ARM_H = 1.68
GEAR_H = 3.0000534
CAVITY_H = 2.16
JOURNAL_R = 3.25
BEARING_R = 3.45
HUB_H = 4.44
SOCKET_R = 2.5
SOCKET_DEPTH = 2.8085067
GROOVE_R = 3.05
VARIANTS = [('A', .80, .20), ('B', 1.00, .20), ('C', 1.20, .20),
            ('D', 1.00, .12), ('E', 1.00, .28)]


def circle(r, xy=(0, 0)):
    return Point(*xy).buffer(r, quad_segs=96)


def xyz(r, deg):
    a = math.radians(deg)
    return (r * math.cos(a), r * math.sin(a))


def solid(poly, h, z=0):
    polys = list(poly.geoms) if poly.geom_type == 'MultiPolygon' else [poly]
    contours = []
    for p in polys:
        contours.append(np.array(p.exterior.coords[:-1]))
        contours.extend(np.array(r.coords[:-1]) for r in p.interiors)
    return mf.CrossSection(contours, mf.FillRule.EvenOdd).extrude(h).translate((0, 0, z))


def cylinder(r, h, z=0):
    return mf.Manifold.cylinder(h, r, circular_segments=192).translate((0, 0, z))


def mesh(s):
    a = s.to_mesh64()
    return trimesh.Trimesh(np.array(a.vert_properties[:, :3]), np.array(a.tri_verts), process=True)


def original():
    with zipfile.ZipFile(SOURCE) as z:
        root = ET.fromstring(z.read('3D/3dmodel.model'))
    v = np.array([[float(e.get(k)) for k in 'xyz'] for e in root.findall('.//{*}vertex')])
    f = np.array([[int(e.get(k)) for k in ('v1', 'v2', 'v3')] for e in root.findall('.//{*}triangle')])
    v = v[:, [0, 2, 1]]
    v[:, 2] += 1.5000267
    m = trimesh.Trimesh(v, f[:, ::-1], process=True)
    assert m.is_volume
    return mf.Manifold(mf.Mesh(np.asarray(m.vertices, np.float32), np.asarray(m.faces, np.uint32)))


def cavity():
    return unary_union([circle(LAND_R)] + [circle(POCKET_R, xyz(POCKET_CENTRE_R, PHASE + i*30)) for i in range(12)])


def arm_profile(thickness, engagement):
    r = ARM_OUTER_R - thickness/2
    arc = [xyz(r, a) for a in np.linspace(ARM_ANGLE, 0, 120)]
    beam = LineString(arc).buffer(thickness/2, cap_style=1, join_style=1, quad_segs=24)
    # Rounded, widened root; its outer edge stays within the arm envelope.
    root = LineString([xyz(2.9, ARM_ANGLE), xyz(r-.3, ARM_ANGLE)]).buffer(.70, quad_segs=24)
    tip = circle(.60, (LAND_R + engagement - .60, 0))
    arm = unary_union([beam, root, tip])
    return affinity.rotate(arm, PHASE, origin=(0, 0))


def hub(letter, thickness, engagement):
    arm = arm_profile(thickness, engagement)
    both = unary_union([arm, affinity.rotate(arm, 180, origin=(0, 0)), circle(JOURNAL_R)])
    planar = unary_union([arm, affinity.rotate(arm, 180, origin=(0, 0)), circle(3.0)])
    s = solid(planar, ARM_H) + cylinder(JOURNAL_R, HUB_H)
    # A 45-degree shoulder locates the cup axially, without a plate under the arms.
    s += mf.Manifold.cylinder(.45, JOURNAL_R, 3.70, circular_segments=192).translate((0, 0, 1.47))
    s -= cylinder(JOURNAL_R+.1, 1.0, 3.20) - cylinder(GROOVE_R, 1.1, 3.15)
    s -= cylinder(SOCKET_R, SOCKET_DEPTH+.2, HUB_H-SOCKET_DEPTH)
    s -= cylinder(1.0, HUB_H+.2, -.1)
    # Recess the existing servo screw head, keeping its seat-to-socket distance.
    # This deliberately retains the original source's ~0.192 mm screw-seat web.
    s -= cylinder(2.30, HUB_H-GEAR_H+.1, -.1)
    # A=one dot ... E=five dots, on the screw-access face outside the recess.
    count = ord(letter)-ord('A')+1
    for angle in np.linspace(90-10*(count-1),90+10*(count-1),count):
        s -= solid(circle(.30,xyz(2.85,angle)), .24, -.001)
    return s, both


def retaining_clip():
    pts = [xyz(3.70, a) for a in np.linspace(-27.5, 207.5, 220)]
    p = LineString(pts).buffer(.55, quad_segs=32, cap_style=1)
    return solid(p, .84), p


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


def print_pose(m, flip=False):
    m = m.copy()
    if flip:
        m.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1,0,0]))
    m.apply_translation([0, 0, -m.bounds[0,2]])
    return m


def save_part(name, m):
    assert m.is_volume and len(m.split()) == 1, name
    m.export(ROOT/'stl'/f'{name}.stl')
    export_3mf(ROOT/'parts'/f'{name}.3mf', [(name, m)], name)


def generate():
    for f in ['parts', 'stl', 'plates', 'assembly', 'verification', 'images']:
        (ROOT/f).mkdir(parents=True, exist_ok=True)
    src = original()
    pocket = cavity()
    ring = src - solid(pocket, CAVITY_H+.1, -.1) - cylinder(BEARING_R, GEAR_H+.2, -.1)
    ringshape = mesh(ring)
    ringprint = print_pose(ringshape, flip=True)
    save_part('00_common_pinion', ringprint)
    clip, clip2d = retaining_clip()
    clipshape = mesh(clip)
    save_part('06_retaining_clip', clipshape)
    report = {'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
      'prototype':True, 'physical_test_performed':False,
      'outer_teeth':12, 'pockets':12, 'external_tooth_mesh_preserved':True,
      'gear_thickness_mm':GEAR_H, 'assembly_height_mm':HUB_H,
      'extra_height_vs_original_mm':HUB_H-GEAR_H,
      'socket_diameter_mm':SOCKET_R*2, 'socket_depth_mm':SOCKET_DEPTH,
      'screw_passage_diameter_mm':2.0, 'journal_diametral_clearance_mm':.4,
      'screw_head_recess_diameter_mm':4.6, 'screw_head_recess_depth_mm':HUB_H-GEAR_H,
      'retained_original_screw_seat_web_mm':GEAR_H-SOCKET_DEPTH,
      'arm_height_mm':ARM_H, 'variants':[], 'parts':{}}
    # The mesh outside r=6 mm must be identical to the source, including flank facets.
    outer = cylinder(20, 4, -.1) - cylinder(6, 4.2, -.2)
    tooth_diff = ((src-ring) ^ outer).volume()
    assert abs(tooth_diff) < 1e-6
    report['external_tooth_change_volume_mm3'] = tooth_diff
    plate = []
    locations = []
    def place(name, m, x, y):
        a = m.copy(); a.apply_translation([x,y,0]); plate.append((name,a)); locations.append({'name':name,'x':x,'y':y})
    place('00_common_pinion_copy1', ringprint, 58, 88)
    place('00_common_pinion_copy2', ringprint, 58, 115)
    hubs, shapes = {}, {}
    for i,(letter,t,d) in enumerate(VARIANTS, 1):
        s, p = hub(letter,t,d)
        m = mesh(s)
        name = f'0{i}_hub_{letter}_t{t:.2f}_d{d:.2f}'
        save_part(name, m)
        place(name, m, 84+(i-1)*23, 88)
        hubs[letter], shapes[letter] = m, p
        interference = (s ^ ring).volume()
        assert interference < 1e-6, (letter, interference)
        assert (s ^ clip.translate((0,0,3.24))).volume() < 1e-6
        assert (ring ^ clip.translate((0,0,3.24))).volume() < 1e-6
        # Contact model: circle tip translated radially inwards; no FEA or torque claim.
        required = []
        for angle in np.linspace(-15,15,121):
            lo, hi = 0., .6
            for _ in range(20):
                mid = (lo+hi)/2
                tip = circle(.6, xyz(LAND_R+d-.6-mid, PHASE+angle))
                if pocket.buffer(1e-7).covers(tip): hi = mid
                else: lo = mid
            required.append(hi)
        assert max(required) < d+.002
        report['variants'].append({'id':letter, 'name':name, 'beam_thickness_mm':t,
          'tip_engagement_mm':d, 'arm_angle_deg':ARM_ANGLE,
          'nominal_arc_length_mm':math.radians(ARM_ANGLE)*(ARM_OUTER_R-t/2),
          'tip_radial_clearance_at_seat_mm':POCKET_CENTRE_R+POCKET_R-(LAND_R+d),
          'required_tip_inward_motion_mm':max(required),
          'seated_intersection_volume_mm3':interference,
          'slip_torque_Nmm':None})
    for i in range(3): place(f'06_clip_spare{i+1}', clipshape, 84+i*23, 115)
    # Object spacing, bed contact, mesh topology.
    for name,m in plate:
        assert abs(m.bounds[0,2]) < 1e-5
        report['parts'][name] = {'watertight':m.is_watertight, 'connected_components':len(m.split()),
          'volume_mm3':float(m.volume), 'bounds_mm':m.bounds.tolist()}
    for i,(_,a) in enumerate(plate):
        for _,b in plate[i+1:]:
            assert np.any(a.bounds[1,:2]+3 < b.bounds[0,:2]) or np.any(b.bounds[1,:2]+3 < a.bounds[0,:2])
    export_3mf(ROOT/'plates'/'00_all_trials_geometry.3mf', plate, 'PLA clutch trials A-E, common gears x2, clips x3')
    assembly = [('common_pinion', ringshape), ('hub_B',hubs['B']), ('retaining_clip',mesh(clip.translate((0,0,3.24))))]
    export_3mf(ROOT/'assembly'/'assembled_B_VIEW_ONLY.3mf', assembly, 'Assembly reference ONLY - do not print assembled')
    (ROOT/'verification'/'geometry.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'verification'/'plate-layout.json').write_text(json.dumps(locations,indent=2),encoding='utf-8')
    render_figures(ringshape, hubs, clipshape, shapes, pocket, plate)
    print(json.dumps({'parts':len(plate),'variants':report['variants'],'output':str(ROOT)},indent=2),flush=True)


def render_figures(ring, hubs, clip, profiles, pocket, plate):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font = FontProperties(fname='C:/Windows/Fonts/YuGothR.ttc')
    plt.rcParams['font.family'] = font.get_name()
    plt.rcParams['axes.unicode_minus'] = False
    from matplotlib.patches import Polygon as Patch
    def drawpoly(ax,p,color):
        for sub in (p.geoms if p.geom_type=='MultiPolygon' else [p]):
            ax.add_patch(Patch(np.asarray(sub.exterior.coords),facecolor=color,edgecolor='#253f50',lw=.65))
            for interior in sub.interiors:
                ax.add_patch(Patch(np.asarray(interior.coords),facecolor='white',edgecolor='#253f50',lw=.5))
    fig, axes = plt.subplots(2,3,figsize=(13,8),facecolor='white')
    section = ring.section(plane_origin=[0,0,1],plane_normal=[0,0,1])
    loops = sorted([Polygon(a[:,:2]) for a in section.discrete],key=lambda p:p.area,reverse=True)
    ring2d = loops[0]
    for p in loops[1:]: ring2d=ring2d.difference(p)
    for ax,(letter,t,d) in zip(axes.flat,VARIANTS):
        drawpoly(ax,ring2d,'#d5e4ed')
        drawpoly(ax,profiles[letter].difference(circle(1)),'#e6aa5a')
        ax.set_title(f'{letter}  爪 {t:.2f} mm ／ 掛かり {d:.2f} mm',fontsize=12,pad=10)
        ax.set_aspect('equal');ax.set_xlim(-10,10);ax.set_ylim(-10,10);ax.axis('off')
    ax=axes.flat[-1];ax.axis('off')
    ax.text(0,.94,'同じ外周にハブを交換',fontsize=16,weight='bold')
    ax.text(0,.78,'A → B → C：爪の厚さを比較\nD → B → E：掛かりの深さを比較',fontsize=12,linespacing=1.9)
    ax.text(0,.49,'共通の外周 × 2\n交換ハブ A〜E × 各1\n印刷製の抜け止め × 3',fontsize=12,linespacing=1.9)
    ax.text(0,.17,'初回は D または A から\n強さは実機で比較・トルク未校正',fontsize=11,linespacing=1.8)
    fig.suptitle('PLA 弾性爪クラッチ：5種類の試作セット',fontsize=20,y=.99)
    fig.tight_layout(rect=[0,0,1,.96]);fig.savefig(ROOT/'images'/'variants.png',dpi=160);plt.close(fig)
    # Portable VTK renderer copied next to this source.
    from render_model import render
    from PIL import Image,ImageDraw,ImageFont
    jp=ImageFont.truetype('C:/Windows/Fonts/YuGothB.ttc',29)
    canvas=Image.new('RGB',(1600,850),'white');draw=ImageDraw.Draw(canvas)
    pieces=[(ring,(.48,.68,.79),1),(hubs['B'],(.94,.65,.29),1)]
    c=clip.copy();c.apply_translation([0,0,3.24]);pieces.append((c,(.54,.68,.44),1))
    canvas.paste(render(pieces,(1,-1,-1),up=(0,0,1),size=(800,720)),(0,80))
    exploded=[]
    h=hubs['B'].copy();h.apply_translation([0,0,-5]);exploded.append((h,(.94,.65,.29),1))
    exploded.append((ring,(.48,.68,.79),1))
    c=clip.copy();c.apply_translation([0,0,8]);exploded.append((c,(.54,.68,.44),1))
    canvas.paste(render(exploded,(1,-1,-.6),up=(0,0,1),size=(800,720)),(800,80))
    draw.text((25,20),'組立状態：爪が見える側',font=jp,fill='#183442')
    draw.text((825,20),'分解：ハブ／共通外周／抜け止め',font=jp,fill='#183442')
    draw.text((25,803),'元の歯形を保持・全厚 4.44 mm（元より約 1.44 mm 増）',font=jp,fill='#183442')
    canvas.save(ROOT/'images'/'assembly.png')


if __name__ == '__main__':
    generate()
