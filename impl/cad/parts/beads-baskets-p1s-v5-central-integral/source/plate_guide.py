from pathlib import Path
import json,math
import numpy as np
import shapely,trimesh
from shapely import affinity
from PIL import Image,ImageDraw,ImageFont

S=Path(__file__).resolve().parent
R=S.parents[1]/'outputs'/'beads-baskets-p1s-v5-central-integral' if S.parent.name=='work' else S.parent
manifest=json.loads((R/'plate_manifest.json').read_text(encoding='utf-8'))
polys={}
for folder in ['stl','optional_reprint_stl']:
    for f in (R/folder).glob('*.stl'):
        m=trimesh.load_mesh(f,process=False);t=m.triangles[:,:,:2]
        a=(t[:,1,0]-t[:,0,0])*(t[:,2,1]-t[:,0,1])-(t[:,1,1]-t[:,0,1])*(t[:,2,0]-t[:,0,0])
        polys[f.stem]=shapely.union_all(shapely.polygons(t[np.abs(a)>1e-9])).buffer(0)
def f(n,b=False):return ImageFont.truetype('C:/Windows/Fonts/YuGoth'+('B' if b else 'M')+'.ttc',n)
def txt(d,x,y,t,n=26,b=False,c='#284b4c'):d.text((x,y),t,font=f(n,b),fill=c)
def color(k):
    if 'gear' in k:return '#dd9c4c'
    if k=='bridge_clip':return '#cb8b7d'
    if 'lid' in k:return '#d5b878'
    if k in ['base_with_docking','smooth_u_chute','02_motor_carrier','05_split_bearing_cap']:return '#548c91'
    return '#8ab7a7'
def outline(d,g,bx,by,sc,fill,edge=None):
    def xy(coords):return [(bx+x*sc,by+(256-y)*sc) for x,y in coords]
    for q in getattr(g,'geoms',[g]):
        if q.geom_type!='Polygon':continue
        d.polygon(xy(q.exterior.coords),fill=fill,outline=edge,width=2)
        for hole in q.interiors:d.polygon(xy(hole.coords),fill='#f8faf8')
def plate(d,entry,bx,by,sc,numbers=False):
    size=256*sc
    d.rectangle((bx,by,bx+size,by+size),fill='#f8faf8',outline='#799a96',width=2)
    d.rectangle((bx,by+size-28*sc,bx+18*sc,by+size),fill='#e9b4ad')
    poses=[]
    for it in entry['objects']:
        q=affinity.translate(affinity.rotate(polys[it['part']],it['rotation_z_deg'],origin=(0,0)),*it['center_xy_mm'])
        poses.append((it['part'],q))
        outline(d,q.buffer(5),bx,by,sc,'#dce6df')
    for i,(k,q) in enumerate(poses,1):
        outline(d,q,bx,by,sc,color(k),'#3d6262')
        if numbers:
            p=q.representative_point();x=bx+p.x*sc;y=by+(256-p.y)*sc
            d.ellipse((x-18,y-18,x+18,y+18),fill='#ffffff',outline='#335957',width=2)
            d.text((x,y),str(i),font=f(24,True),fill='#284b4c',anchor='mm')

# Detailed first plate, with gears explicitly identified.
im=Image.new('RGB',(1510,1140),'#edf2ef');d=ImageDraw.Draw(im)
txt(d,38,25,'まず01の1枚で、機構試験に必要な部品をそろえる',40,True)
txt(d,40,87,'80歯と20歯の増速ギアを含む6部品。バスケットと蓋は後回し。',28)
plate(d,manifest[0],46,153,3.15,True)
labels=['位置決め付きベース','丸底スロープ','80歯ギア（モーター側）','モーター台','20歯ギア一体軸（スロープ側）','軸受キャップ']
for i,t in enumerate(labels,1):
    yy=193+(i-1)*91
    d.ellipse((900,yy,936,yy+36),fill='white',outline='#335957',width=2)
    d.text((918,yy+18),str(i),font=f(24,True),fill='#284b4c',anchor='mm')
    txt(d,953,yy+1,t,27,True)
txt(d,900,784,'大ギア80歯 → 小ギア20歯',28,True)
txt(d,900,830,'スロープ側を4倍に増速',28,True,c='#a56d23')
txt(d,900,889,'この2枚も01に入っています。',25)
txt(d,45,1000,'機構部品まで1回  →  仕分け用容器まで3回  →  保管用を含む全品7回',31,True)
txt(d,45,1060,'既存本体、モーター、制御回路、M3部品を使用。印刷後は組立と低速での動作確認から始めます。',24)
im.save(R/'startup-plate.png')

im=Image.new('RGB',(2160,2130),'#edf2ef');d=ImageDraw.Draw(im)
txt(d,40,24,'中央ケースも一体連結 / 印刷順',45,True)
txt(d,43,86,'01だけ先に印刷できます。02～03は仕分け用、04～07は後回しにできる保管用です。',26)
titles=['01  機構部品6点','02  一体連結バスケット5個','03  残りのバスケット5個','04  中央ケースと蓋3枚','05  中央の蓋と蓋3枚','06  90°バスケットと専用蓋','07  残りの蓋4枚','任意  はまり具合の試験片']
captions=['80歯 / 20歯ギアもここに含む','バスケット同士を上下に差して連結','ここまでで仕分け用10個がそろう','ここからは保管機能の追加','小さい蓋は27°バスケット用','3本目の位置決め接続もここで完成','全12個のケースと蓋がそろう','機構試験前は不要。容器製作時に使用']
for i,e in enumerate(manifest):
    x=24+(i%3)*710;y=147+(i//3)*627
    d.rounded_rectangle((x,y,x+687,y+606),22,fill='white')
    txt(d,x+20,y+18,titles[i],27,True)
    plate(d,e,x+104,y+76,1.85)
    txt(d,x+20,y+563,captions[i],23)
x=24+2*710;y=147+2*627
d.rounded_rectangle((x,y,x+687,y+606),22,fill='#d9e7df')
txt(d,x+37,y+41,'印刷回数の考え方',31,True)
for j,t in enumerate(['機構試験の部品：1回','仕分け用10個まで：累計3回','保管用もすべて：累計7回','任意の試験片を使う場合：＋1回']):txt(d,x+37,y+117+j*78,t,26,True)
txt(d,x+37,y+462,'継手はバスケットと一体で印刷。',26)
txt(d,43,2053,'P1S / 256 mm角。「層ごと」で印刷。5 mmの余白を確保。ベースとスロープは外側に通常サポートが必要です。',25)
im.save(R/'plate-guide.png')
print('guides saved',R)
