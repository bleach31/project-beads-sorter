"""4:1 speed-up retrofit for the user's bead sorter. Units: mm.

Assembly frame: nozzle axis X=Y=0, Z=original CAD Y+57.625675.
Original nozzle/middle-base geometry is stored unchanged in reference_parts.npz.
This is an untested FDM prototype; physical fit and motor performance need trials.
"""
from pathlib import Path
import json, math, zipfile, xml.etree.ElementTree as ET
import numpy as np
import manifold3d as md
import trimesh
from gear_profile import gear_outline

ROOT=Path(__file__).resolve().parent.parent
STL=ROOT/'stl'
ASSY=ROOT/'assembly'
CHECKS=ROOT/'verification'
M=md.Manifold
GEAR_Z=-6.0
CENTER=40.0
SHAFT_D=7.95
JOURNAL_D=8.35
BASE_BOTTOM=-46.0
BASE_TOP=-42.0
SEAT=-19.0

def union(parts):return M.batch_boolean(parts,md.OpType.Add)
def box(x0,x1,y0,y1,z0,z1):return M.cube([x1-x0,y1-y0,z1-z0]).translate([x0,y0,z0])
def cyl(r,z0,z1,x=0,y=0,n=96):return M.cylinder(z1-z0,r,circular_segments=n).translate([x,y,z0])
def rounded_rect(x0,x1,y0,y1,r,z0,z1):
    return union([cyl(r,z0,z1,x,y,32) for x in [x0+r,x1-r] for y in [y0+r,y1-r]]).hull()
def hex_z(x,y,z0,z1,af=5.8):return M.cylinder(z1-z0,af/math.sqrt(3),circular_segments=6).rotate([0,0,30]).translate([x,y,z0])
def hole_y(x,y0,y1,z,r=1.65):return M.cylinder(y1-y0,r,circular_segments=48).rotate([-90,0,0]).translate([x,y0,z])
def hex_y(x,y0,y1,z,af=5.8):return hex_z(0,0,0,y1-y0,af).rotate([-90,0,0]).translate([x,y0,z])
def hole_x(x0,x1,y,z,r=1.65):return M.cylinder(x1-x0,r,circular_segments=48).rotate([0,90,0]).translate([x0,y,z])
def hex_x(x0,x1,y,z,af=5.8):return hex_z(0,0,0,x1-x0,af).rotate([0,90,0]).translate([x0,y,z])
def double_d(d,af,z0,z1):return cyl(d/2,z0,z1)^box(-af/2,af/2,-d,d,z0-1,z1+1)
def manifold(v,f):
    t=trimesh.Trimesh(v,f,process=True)
    if t.volume<0:t.invert()
    result=M(md.Mesh(np.asarray(t.vertices,dtype=np.float32),np.asarray(t.faces,dtype=np.uint32)))
    if result.status()!=md.Error.NoError:raise ValueError(result.status())
    return result
def mesh(s):
    a=s.to_mesh();return trimesh.Trimesh(np.asarray(a.vert_properties)[:,:3],np.asarray(a.tri_verts),process=True)
def standardize(s):
    b=s.bounding_box();return s.translate([-(b[0]+b[3])/2,-(b[1]+b[4])/2,-b[2]])

ref=np.load(Path(__file__).with_name('reference_parts.npz'))
refs={name:manifold(ref[name+'_v'],ref[name+'_f']) for name in ['nozzle','middle-base','upper-base','camera-mount']}

def bearing_parts():
    body=cyl(7,0,24)
    # Two short journals; the middle is relieved to reduce rubbing.
    body=body-cyl(JOURNAL_D/2,-.1,24.1)-cyl(4.5,4,20)
    ears=union([box(x-3.7,x+3.7,-6,6,z-3,z+3) for x in [-10,10] for z in [7,19]])
    bridge=box(-13.7,13.7,-3,3,4,22)-cyl(7.01,3.9,22.1)
    body=body+ears+bridge
    fixed=body^box(-30,30,0,20,-1,25)
    cap=body^box(-30,30,-20,0,-1,25)
    for x in [-10,10]:
        for z in [7,19]:
            fixed=fixed-hole_y(x,-1,8,z)-hex_y(x,3.3,6.2,z)
            # Rear-side access holds a standard M3 nut against rotation.
            cap=cap-hole_y(x,-8,1,z)
    return fixed,cap

fixed_bearing,cap=bearing_parts()

def make_base():
    base=rounded_rect(-46,78,-38,38,5,BASE_BOTTOM,BASE_TOP)
    # Preserve the two original holes and middle-base underside Z=44.
    towers=union([cyl(5,BASE_TOP,44,x,22.045363,48) for x in [-34.874421,-20.874421]]).hull()
    # Recess the forward face only at chute height. The45degree shoulder
    # restores the full mounting bosses above the moving chute.
    relief_outline=np.array([[10,7],[22.1,7],[22.1,28],[16.9,33.2],[10,33.2]])
    relief=M.extrude(md.CrossSection([relief_outline]),50).transform([[0,0,1,-50],[1,0,0,0],[0,1,0,0]])
    towers=towers-relief-box(-22,0,10,40,7,34.2)
    for x in [-34.874421,-20.874421]:
        towers=towers-cyl(1.65,35,45,x,22.045363,48)-hex_z(x,22.045363,36,39)
        towers=towers-box(x-2.9,x+2.9,22.045363,28,36,39)
    # This rear support clears both gears. The output carrier is split to
    # capture the integral shaft's gear and thrust collar without a metal axle.
    pedestal=box(-18,-10,-10,10,BASE_TOP,4)
    carrier_bridge=box(-18,0,0,7,0,4)-cyl(JOURNAL_D/2,-.1,4.1)
    result=base+towers+pedestal+carrier_bridge+fixed_bearing
    for x in [18,46]:
        for y in [-23,23]:
            result=result-cyl(1.65,BASE_BOTTOM-.1,BASE_TOP+.1,x,y,48)
            result=result-cyl(3.0,BASE_BOTTOM-.1,BASE_BOTTOM+2.2,x,y,48)
    return result

def make_motor_carrier():
    plate=rounded_rect(13,51,-27,27,3,-42,-39)
    # Adjustment toward greater center distance,0..+0.3mm, before bolt clearance.
    for x in [18,46]:
        for y in [-23,23]:
            slot=union([cyl(1.65,-42.2,-38.8,x+dx,y,48) for dx in [-.3,0]]).hull()
            trap=union([hex_z(x+dx,y,-41.55,-38.8) for dx in [-.3,0]]).hull()
            plate=plate-slot-trap
    body_x=32.0
    cradle=(cyl(16.5,-39,SEAT,body_x)-cyl(14.5,-39.1,SEAT+.1,body_x))
    cradle=cradle^(box(10,55,10,25,-40,SEAT+1)+box(10,55,-25,-10,-40,SEAT+1))
    bosses=union([cyl(5.5,-39,SEAT,body_x,y,64) for y in [-17.5,17.5]])
    result=plate+cradle+bosses
    result=result-cyl(14.5,-39,SEAT+.1,body_x)
    for y in [-17.5,17.5]:
        result=result-cyl(1.65,-31,SEAT+.1,body_x,y,48)-hex_z(body_x,y,-28,-25)
        y0,y1=(y,28) if y>0 else (-28,y)
        result=result-box(body_x-2.9,body_x+2.9,y0,y1,-28,-25)
    return result

def make_drive_gear():
    gear=M.extrude(md.CrossSection([gear_outline(80)]),5).translate([0,0,GEAR_Z])
    hub=cyl(8,-15,GEAR_Z+.2)
    result=gear+hub
    result=result-double_d(5.2,3.2,-15.2,-8)
    result=result-hole_x(0,8.5,0,-10.5)-hex_x(4.2,7.0,0,-10.5)
    # Insert the nut from the hub's underside before fitting the motor shaft.
    result=result-box(4.2,7.0,-3.4,3.4,-15.2,-10.5)
    # Lightening holes avoid the torque-carrying rim and central hub.
    for angle in range(0,360,45):
        a=math.radians(angle)
        result=result-cyl(5.5,GEAR_Z-.1,GEAR_Z+5.1,19*math.cos(a),19*math.sin(a),64)
    return result

def make_output_gear():
    # Driver is at +40; same 189-degree neutral phase works for even tooth counts.
    gear=M.extrude(md.CrossSection([gear_outline(20,rotation_deg=189)]),5).translate([0,0,GEAR_Z])
    journal=cyl(SHAFT_D/2,-1.2,24.3)
    lower_thrust=cyl(6,-1.1,0)
    collar=cyl(6,24.3,26.100002)
    tip=double_d(5.0,3.0,26.0,32.850002)
    # Short chamfer at insertion tip, preserving the double flats.
    tip=tip^ (cyl(10,25,32.351)+M.cylinder(.5,2.5,2.25,circular_segments=96).translate([0,0,32.350002]))
    return gear+journal+lower_thrust+collar+tip

def make_coupon():
    coupon=rounded_rect(0,63,0,16,2,0,8)
    for x,d,af in [(9,5.15,3.15),(26,5.2,3.2),(43,5.25,3.25)]:
        coupon=coupon-double_d(d,af,1,8.1).translate([x,8,0])
    coupon=coupon-cyl(JOURNAL_D/2,-.1,8.1,55,8,72)
    # One, two and three witness dimples identify the socket variants.
    for index,x in enumerate([9,26,43],1):
        for j in range(index):coupon=coupon-cyl(.6,7.4,8.1,x+(j-(index-1)/2)*2,2.7,24)
    return coupon

parts={'01_base_4x':make_base(),'02_motor_carrier':make_motor_carrier(),
       '03_drive_gear_80t':make_drive_gear(),'04_output_gear_20t_spindle':make_output_gear(),
       '05_split_bearing_cap':cap,'06_fit_coupon_optional':make_coupon()}

