from pathlib import Path
import math,sys
import numpy as np
from PIL import Image,ImageDraw,ImageFont
import baskets as b
from render_core import render

S=Path(__file__).resolve().parent
OUT=S.parents[1]/'outputs'/'beads-baskets-p1s-v5-central-integral' if S.parent.name=='work' else S.parent
BG='#f7f7f3'; INK='#233e43'; MUTED='#5c7477'; TEAL='#4c9ba2'; GOLD='#dab373'
def font(n,bold=False):return ImageFont.truetype('C:/Windows/Fonts/YuGoth'+('B' if bold else 'M')+'.ttc',n)
def text(d,xy,t,n=25,c=INK,bold=False):d.text(xy,t,font=font(n,bold),fill=c)
def item(n,s,c):
    m=s.to_mesh();return [n,np.asarray(m.vert_properties)[:,:3],np.asarray(m.tri_verts),tuple(bytes.fromhex(c[1:]))]
def crop(s,x0=72,x1=108,y0=-16,y1=16,z0=-.1,z1=60):
    return s ^ b.M.cube([x1-x0,y1-y0,z1-z0]).translate([x0,y0,z0])
def arrow(d,a,c):
    a=np.asarray(a);c=np.asarray(c);u=(c-a)/np.linalg.norm(c-a);n=np.array([-u[1],u[0]])
    d.line([tuple(a),tuple(c-u*12)],fill=TEAL,width=8)
    d.polygon([tuple(c),tuple(c-u*22+n*12),tuple(c-u*22-n*12)],fill=TEAL)

D=b.build();P=D['parts'];colors=['#cb8b7c','#d3a14e','#c3b361','#8fa471','#639f88','#63a2ac','#7191b0','#958cb0','#b789a5','#c7919b']
ring=[]
for q in D['assembly']:
    if q['part'].startswith('bin_'):
        col=colors[int(q['name'][-2:])-1] if q['name'].startswith('bin_27_') else '#b6c5b5'
        ring.append(item(q['name'],b.apply_pose(P[q['part']],q),col))
overview,ovp=render(ring+[item('central_raised',P['central_case'].translate([0,0,65]),TEAL)],
                    1110,800,az=-105,el=45,ss=1.15,shadows=True,pad=35)
angle=b.central_key_angles()[0]
cc=crop(P['central_case'].rotate([0,0,-angle]))
bb=crop(P['bin_90'].rotate([0,0,113-angle]))
detail,dp=render([item('key',cc.translate([0,0,26]),TEAL),item('socket',bb,GOLD)],
                 720,480,az=-65,el=35,ss=1.3,shadows=True,pad=40)
slice_c=crop(P['central_case'].rotate([0,0,-angle]),78,94,-8,8,10,10.5)
slice_b=crop(P['bin_90'].rotate([0,0,113-angle]),78,94,-8,8,10,10.5)
section,sp=render([item('case_slice',slice_c,TEAL),item('socket_slice',slice_b,GOLD)],
                  300,230,az=-90,el=89.99,ss=1.4,shadows=False,pad=15)
sheet=Image.new('RGB',(2000,1410),'#e9efeb');d=ImageDraw.Draw(sheet)
text(d,(50,30),'BEADS SORTER / CENTRAL CASE CONNECTION',22,'#397d82',True)
text(d,(48,77),'中央ケースも、別部品なしで連結',52,INK,True)
text(d,(52,155),'ケース一体の3か所のT字キーを、バスケット内側の縦溝へ差し込みます。',28,MUTED)
d.rounded_rectangle((30,225,1165,1110),24,fill=BG)
d.rounded_rectangle((1185,225,1970,1110),24,fill=BG)
text(d,(62,245),'01  本体を外し、中央ケースを上から入れる',31,INK,True)
text(d,(1218,245),'02  太いキーと溝で位置を固定',28,INK,True)
sheet.paste(overview,(43,292));sheet.paste(detail,(1216,303));sheet.paste(section,(1215,808));d=ImageDraw.Draw(sheet)
aa=ovp([95,-48,95])+[43,292];zz=ovp([95,-48,40])+[43,292];arrow(d,aa,zz)
text(d,(aa[0]+12,aa[1]+17),'下ろす',25,TEAL,True)
text(d,(1540,839),'水平断面の拡大',24,INK,True)
text(d,(1540,887),'キーの首は4.4 mm',24,MUTED)
text(d,(1540,930),'縦に21 mmかみ合う',24,MUTED)
text(d,(1540,973),'曲げる細い爪は不要',24,MUTED)
text(d,(62,1048),'図は中央の蓋を外した状態。既存の蓋をそのまま使えます。',25,MUTED)
for x,y,w,title,body in [(35,1140,630,'追加の連結部品は0個','キーも受けも、容器と一体で印刷'),
                       (685,1140,630,'分解は中央ケースから','22 mm以上持ち上げてから横へ移動'),
                       (1335,1140,630,'印刷は全品7回のまま','最初の機構試験用プレートも変更なし')]:
    d.rounded_rectangle((x,y,x+w,y+160),18,fill='white')
    text(d,(x+25,y+23),title,29,INK,True);text(d,(x+25,y+84),body,24,MUTED)
text(d,(46,1335),'横ずれを抑える構造です。持ち運びは全体の底を支えます。形状確認済み、実物のはまり具合は印刷後に確認。',24,MUTED)
sheet.save(OUT/'central-connection.png')
# Closed storage overview, generated from all actual final parts.
closed=[]
for q in D['assembly']:
    col=TEAL if 'central' in q['name'] else '#b6c5b5'
    if q['name'].startswith(('bin_27_','lid_27_')):col=colors[int(q['name'][-2:])-1]
    closed.append(item(q['name'],b.apply_pose(P[q['part']],q),col))
view,_=render(closed,1600,1060,az=-105,el=57,ss=1.2,shadows=True,pad=60)
im=Image.new('RGB',(1700,1270),'#e9efeb');im.paste(view,(50,140));d=ImageDraw.Draw(im)
text(d,(47,25),'中央ケースまで一体連結 / すべての蓋を付けた保管状態',39,INK,True)
text(d,(49,89),'10個の27°容器 + 90°容器 + 中央ケース。外周の継手も以前と同じ形状です。',27,MUTED)
text(d,(49,1205),'全体の最大外径は約375 mm。中央ケースは上から着脱し、周囲の容器を外す前に取り出します。',27,MUTED)
im.save(OUT/'preview.png')
print('Saved central-connection.png and preview.png',flush=True)
