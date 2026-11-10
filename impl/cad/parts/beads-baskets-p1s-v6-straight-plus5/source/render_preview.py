"""Actual CAD preview and conservative plan footprints for both new plates."""
import json,math
import numpy as np
import trimesh
from PIL import Image,ImageDraw,ImageFont
from shapely.geometry import MultiPoint
import chute_plus5 as c
from build import ROOT,assembly_items
import render_core

COLORS=['#729c96','#cf984e','#c6ac66','#8caca6','#daab65','#adc2bc']
def font(n):return ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc',n)
def txt(d,x,y,s,n=24,col='#284347'):d.text((x,y),s,font=font(n),fill=col)
def item(name,m,col):return(name,m.vertices,m.faces,render_core.rgb(col)[:3])

def model():
    shape=c.build_chute();shown=c.mesh(shape.translate([0,0,-shape.bounding_box()[2]]))
    part,_=render_core.render([item('chute',shown,'#dfab5e')],900,415,az=-125,el=40,ss=1.15,shadows=True,pad=30)
    part.save(ROOT/'images/chute-model.png')
    a=assembly_items(shape)
    scene=[item(n,m,col) for n,m,col in a if not n.startswith('bin_') or n in ['bin_27_03','bin_27_04','bin_27_05']]
    assembly,_=render_core.render(scene,850,355,az=-40,el=48,ss=1.1,shadows=True,pad=20)
    page=Image.new('RGB',(1600,1030),'#f3f5f1');d=ImageDraw.Draw(page)
    txt(d,45,25,'5 mm延長スロープ：元の傾斜を維持',39)
    txt(d,49,83,'水平距離106 → 111 mm / 一定勾配22.68° / 内幅12 mmの丸底',25,'#61756c')
    d.rounded_rectangle((35,140,970,605),18,fill='white');page.paste(part,(50,160))
    d.rounded_rectangle((995,140,1565,605),18,fill='white')
    txt(d,1028,170,'今回の変更',28)
    txt(d,1028,222,'元の一定勾配のまま、先端を延長。',23)
    txt(d,1028,265,'入口、軸穴、断面は元の形状。',23)
    txt(d,1028,324,'印刷時の外寸',24,'#61756c')
    txt(d,1028,367,'129.5 × 15.6 × 17.0 mm',28)
    txt(d,1028,436,'長い外底はベッドから約9.8 mm浮くため、',20)
    txt(d,1028,470,'外側の通常サポートとブリムが必要です。',20)
    txt(d,1028,541,'追加の固定ねじはありません。',23)
    d.rounded_rectangle((35,630,1565,982),18,fill='white');page.paste(assembly,(45,628))
    txt(d,920,659,'組み込み位置',28)
    txt(d,920,711,'オレンジ色が更新したスロープです。',24)
    txt(d,920,760,'トレー上端への隙間：通常位置 約3.61 mm',22)
    txt(d,920,804,'仮定した傾きと下がり込みで 約0.99 mm',22)
    txt(d,920,866,'歯車、ベース、容器、蓋は変更していません。',21)
    txt(d,920,918,'組立図は位置確認用で、印刷には使いません。',20,'#61756c')
    txt(d,45,995,'2026-11-10 / CAD形状を表示。新モデルのスライス、印刷、ビーズの流れ試験は未実施。',19,'#61756c')
    page.save(ROOT/'images/model-preview.png')

def plates():
    cfg=json.loads((ROOT/'source/plate_layouts.json').read_text(encoding='utf-8'))
    im=Image.new('RGB',(1600,1160),'#f3f5f1');d=ImageDraw.Draw(im)
    txt(d,45,28,'目的に合わせて選ぶ2枚の印刷データ',38)
    txt(d,48,87,'どちらもP1Sの1枚分 / 各ファイルを1回印刷 / 「層ごと」で印刷',25,'#61756c')
    for j,p in enumerate(cfg['plates']):
        ox=63+j*786;oy=235;scale=2.6
        txt(d,ox,154,('01  ' if j==0 else '02  ')+p['title'],26)
        def xy(points):return[(ox+x*scale,oy+(256-y)*scale) for x,y in points]
        d.rectangle((ox,oy,ox+256*scale,oy+256*scale),fill='#fffefa',outline='#80938a',width=2)
        for v in range(32,256,32):
            d.line((ox+v*scale,oy,ox+v*scale,oy+256*scale),fill='#e8ece6')
            d.line((ox,oy+v*scale,ox+256*scale,oy+v*scale),fill='#e8ece6')
        d.rectangle((ox,oy+(256-28)*scale,ox+18*scale,oy+256*scale),fill='#e8b9a7')
        for i,e in enumerate(p['objects']):
            m=trimesh.load_mesh(ROOT/'stl'/(e['part']+'.stl'),process=False)
            a=math.radians(e['rotation_z_deg']);rot=np.array([[math.cos(a),-math.sin(a)],[math.sin(a),math.cos(a)]])
            points=m.vertices[:,:2]@rot.T+e['center_xy_mm'];poly=MultiPoint(points).convex_hull
            d.polygon(xy(poly.buffer(5).exterior.coords),fill='#e0e7da')
            color=COLORS[i] if j==0 else '#cf984e'
            d.polygon(xy(poly.exterior.coords),fill=color,outline='#5c776c',width=2)
            x,y=xy([(poly.centroid.x,poly.centroid.y)])[0]
            d.ellipse((x-16,y-16,x+16,y+16),fill='white',outline='#5c776c',width=1)
            txt(d,x-7,y-16,str(i+1),20)
        if j==0:
            txt(d,ox,918,'ベース、スロープ、80歯ギア、モーター台、',22)
            txt(d,ox,955,'20歯ギア一体軸、軸受キャップを各1個。',22)
        else:
            txt(d,ox,918,'5 mm延長スロープを2個だけ。',22)
            txt(d,ox,955,'交換用と予備を1回で印刷できます。',22)
    txt(d,48,1026,'淡い縁は周囲5 mmの余白。輪郭は余白確認用に穴や凹部を省略しています。',22,'#61756c')
    txt(d,48,1067,'両方を印刷するとスロープは計3個になります。容器と蓋のプレートは別フォルダーに同梱しています。',22)
    txt(d,48,1110,'形状と配置のみ。サポート等の印刷設定は含まれません。',20,'#61756c')
    im.save(ROOT/'images/print-plates.png')

if __name__=='__main__':model();plates()
