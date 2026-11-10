"""V5 chute extended horizontally by 5 mm at its original constant slope.

Assembly frame: inlet axis XY=0; outlet points -X; table Z=-46.
Only the open-ended straight section grows; no socket, channel or drive changes.
"""
import math
import numpy as np
import trimesh
from reference import v5_chute

OUTLET_RADIUS=111.0
ORIGINAL_RADIUS=106.0
ORIGINAL_SLOPE=44.3/106.0
SLOPE_ANGLE=math.degrees(math.atan(ORIGINAL_SLOPE))
INLET_FLOOR=35.8
OUTLET_FLOOR=INLET_FLOOR-ORIGINAL_SLOPE*OUTLET_RADIUS

def build_chute():
    return v5_chute.build_chute(outlet_radius=OUTLET_RADIUS,outlet_floor=OUTLET_FLOOR)

def floor_z(radius):
    return INLET_FLOOR-ORIGINAL_SLOPE*np.asarray(radius)

def mesh(shape):
    raw=shape.to_mesh()
    return trimesh.Trimesh(np.asarray(raw.vert_properties)[:,:3],np.asarray(raw.tri_verts),process=True)

def print_transform(shape=None):
    if shape is None:shape=build_chute()
    a=math.radians(SLOPE_ANGLE);c=math.cos(a);s=math.sin(a)
    t=np.eye(4);t[:3,:3]=[[c,0,s],[0,1,0],[-s,0,c]]
    b=shape.rotate([0,SLOPE_ANGLE,0]).bounding_box()
    t[:3,3]=[-(b[0]+b[3])/2,-(b[1]+b[4])/2,-b[2]]
    return t

def preferred_print_orientation(shape):
    return shape.transform(print_transform(shape)[:3,:])

def metadata():
    return dict(date='2026-11-10',units='mm',reference='beads-baskets-p1s-v5-central-integral',
                replaces='smooth_u_chute',outlet_radius_mm=OUTLET_RADIUS,
                horizontal_extension_mm=5.,slope_surface_extension_mm=5*math.hypot(1,ORIGINAL_SLOPE),
                constant_slope_deg=SLOPE_ANGLE,inlet_floor_assembly_z_mm=INLET_FLOOR,
                outlet_floor_assembly_z_mm=OUTLET_FLOOR,table_z_offset_mm=46.,
                outlet_floor_table_z_mm=OUTLET_FLOOR+46,outlet_outer_bottom_table_z_mm=OUTLET_FLOOR+46-1.8,
                original_geometry_retained_radius_mm=106.,inlet_width_mm=10.4,
                main_width_mm=12.,main_depth_mm=6.,central_vertical_bottom_thickness_mm=1.8,
                wall_note='V5 outer profile retained; 1.8 mm is central vertical thickness, not a global normal minimum.',
                socket_diameter_mm=5.2,socket_across_flats_mm=3.2,socket_open_z_mm=26.1,socket_blind_end_z_mm=33.1,
                additional_hardware=[],physical_print_tested=False,physical_flow_tested=False)
