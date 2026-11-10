"""Long bead-sorter chute in the existing gearbox assembly coordinate frame.

A continuously descending U-bottom channel with a rounded rear intake.
Nozzle axis X=Y=0, existing shaft socket opens at Z=26.1. Outlet points -X.
The function returns one manifold solid and does not write deliverables.
"""
import math
import numpy as np
import manifold3d as md
import trimesh

M=md.Manifold
PARAMETERS={
    'outlet_radius_mm':106.0,
    'inlet_floor_z_mm':35.8,
    'outlet_floor_z_mm':-8.5,
    'inlet_inner_radius_mm':5.2,
    'main_inner_radius_mm':6.0,
    'width_blend_length_mm':10.0,
    'wall_mm':1.8,
    'external_flat_width_mm':6.4,
    'socket_diameter_mm':5.2,
    'socket_across_flats_mm':3.2,
    'socket_open_z_mm':26.1,
    'socket_blind_end_z_mm':33.1,
    'hub_outer_diameter_mm':13.0,
    'max_inlet_rim_z_mm':41.0,
}

def _box(x0,x1,y0,y1,z0,z1):
    return M.cube([x1-x0,y1-y0,z1-z0]).translate([x0,y0,z0])

def _cyl(r,z0,z1):
    return M.cylinder(z1-z0,r,circular_segments=96).translate([0,0,z0])

def _mesh_manifold(v,f):
    mesh=trimesh.Trimesh(v,f,process=True)
    if mesh.volume<0:mesh.invert()
    result=M(md.Mesh(np.asarray(mesh.vertices,dtype=np.float32),np.asarray(mesh.faces,dtype=np.uint32)))
    if result.status()!=md.Error.NoError:raise RuntimeError(result.status())
    return result

def _loft(sections):
    """Loft convex YZ outlines at descending X stations, with closed caps.

    An optional single first vertex makes a pointed rounded-rear end without
    zero-area triangles. All other sections must share one vertex count.
    """
    pointed=len(sections[0])==1
    regular=sections[1:] if pointed else sections
    count=len(regular[0]);offset=1 if pointed else 0
    v=np.concatenate(sections);faces=[]
    if pointed:
        for i in range(count):faces.append([0,offset+(i+1)%count,offset+i])
    else:
        for i in range(1,count-1):faces.append([0,i+1,i])
    for k in range(len(regular)-1):
        a=offset+k*count;b=offset+(k+1)*count
        for i in range(count):
            j=(i+1)%count
            faces.extend([[a+i,a+j,b+j],[a+i,b+j,b+i]])
    last=offset+(len(regular)-1)*count
    for i in range(1,count-1):faces.append([last,last+i,last+i+1])
    return _mesh_manifold(v,faces)

def _outline_outer(ri,wall=1.8,flat_half=3.2):
    ro=ri+wall
    bottom=-ro
    shoulder=bottom+1.25*(ro-flat_half)
    return np.array([[-ro,0],[-ro,shoulder],[-flat_half,bottom],[flat_half,bottom],[ro,shoulder],[ro,0]],dtype=float)

def _outline_inner(ri):
    a=np.linspace(math.pi,2*math.pi,65)
    arc=np.c_[ri*np.cos(a),ri*np.sin(a)]
    return np.vstack([arc,[ri,30],[-ri,30]])

def build_chute(outlet_radius=106.0,outlet_floor=-8.5):
    """Create one connected printable chute, preserving the old drive socket."""
    inlet_floor=35.8;ri0=5.2;ri1=6.0;wall=1.8
    slope=(inlet_floor-outlet_floor)/outlet_radius
    radial=[0.0,2.5,5.0,7.5,10.0,outlet_radius]
    # Both the rounded rear and descending trough are lofted in one mesh.
    # Shared vertices at X=0 avoid tangent Boolean seams in exported STL.
    outer_sections=[np.array([[ri0+wall,0,41.0]])]
    for angle in np.linspace(87.0,3.0,29):
        a=math.radians(angle);x=(ri0+wall)*math.sin(a)
        profile=_outline_outer(ri0,wall)*math.cos(a)
        outer_sections.append(np.c_[np.full(len(profile),x),profile[:,0],profile[:,1]+41.0])
    inner_sections=[]
    for x in [5.19,5.10,4.90,4.60,4.20,3.70,3.10,2.40,1.60,0.80]:
        profile=_outline_inner(math.sqrt(ri0*ri0-x*x))
        inner_sections.append(np.c_[np.full(len(profile),x),profile[:,0],profile[:,1]+41.0])
    for r in radial:
        ri=ri0+(ri1-ri0)*min(r/10.0,1.0)
        center_z=inlet_floor-slope*r+ri
        for dest,outline in [(outer_sections,_outline_outer(ri,wall)),(inner_sections,_outline_inner(ri))]:
            dest.append(np.c_[np.full(len(outline),-r),outline[:,0],outline[:,1]+center_z])
    shell=_loft(outer_sections)
    channel_void=_loft(inner_sections)
    # Low boss keeps the unchanged 20T spindle interface. Cut the cavity last
    # so the boss cannot create a ledge in the bead path.
    hub=_cyl(6.5,26.1,36.0)
    socket=_cyl(2.6,26.0,33.1)^_box(-1.6,1.6,-3,3,25.9,33.2)
    result=(shell+hub)-channel_void-socket
    if result.status()!=md.Error.NoError:raise RuntimeError(result.status())
    if len(result.decompose())!=1:raise RuntimeError('Disconnected chute: '+str([(a.volume(),a.bounding_box()) for a in result.decompose()]))
    return result

def preferred_print_orientation(shape):
    """Level the external long flat, leave the channel open upward.

The lower hub needs external supports in this orientation. Keep support
material out of the U channel and the double-flat socket. A broad brim helps.
"""
    angle=math.degrees(math.atan((35.8+8.5)/106.0))
    oriented=shape.rotate([0,angle,0])
    b=oriented.bounding_box()
    return oriented.translate([-(b[0]+b[3])/2,-(b[1]+b[4])/2,-b[2]])

def metadata():
    p=dict(PARAMETERS)
    p['slope_deg']=math.degrees(math.atan((35.8+8.5)/106.0))
    p['minimum_roof_above_socket_mm']=35.8-(35.8+8.5)/106.0*1.6-33.1
    return p




