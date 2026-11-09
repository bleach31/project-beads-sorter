"""Compose the final feeder overview from verified, CAD-derived source images.

The local final_source_* images are included so the diagram can be reproduced
without the older project directories. This script does not edit model geometry.
"""
from pathlib import Path
import shutil

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
OUT = ROOT / "preview"
BG = "#F5F8FA"
INK = "#17333F"
MUTED = "#516C79"
BLUE = "#376579"
LINE = "#D6E3E8"


def font(size, bold=False):
    return ImageFont.truetype(
        str(Path("C:/Windows/Fonts") / ("YuGothB.ttc" if bold else "YuGothM.ttc")), size
    )


def text(draw, xy, s, size=30, bold=False, color=INK):
    draw.text(xy, s, font=font(size, bold), fill=color)


def fit(canvas, path, rect):
    im = Image.open(path).convert("RGB")
    x, y, w, h = rect
    im.thumbnail((w, h), Image.Resampling.LANCZOS)
    canvas.paste(im, (int(x + (w - im.width) / 2), int(y + (h - im.height) / 2)))


def source_image(name, old_path):
    target = OUT / ("final_source_" + name + ".png")
    if not target.exists():
        shutil.copyfile(WORKSPACE / old_path, target)
    return target


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stand = source_image("stand", "feeder_v11_light_stand/preview/stand_annotated.png")
    adjust = source_image("adjust", "feeder_v9_height_adjust/preview/assembly_annotated.png")
    rotor = source_image("rotor", "feeder_v8_rotor_trials/preview/C_curved_rod_detail.png")

    canvas = Image.new("RGB", (2400, 2200), "white")
    d = ImageDraw.Draw(canvas)
    text(d, (66, 35), "Feeder 最終セット", 63, True)
    text(d, (68, 127), "Cローター ＋ ネジ式高さ調整 ＋ 高さ500 mmの軽量台座", 34, False, MUTED)
    d.line((66, 202, 2334, 202), fill=LINE, width=3)

    # Full assembly with the original CAD dimension lines.
    d.rounded_rectangle((60, 241, 1170, 1960), 24, fill=BG)
    text(d, (91, 267), "全体構成", 37, True)
    fit(canvas, stand, (75, 335, 1080, 1475))
    text(d, (103, 1838), "設置幅 300 × 300 mm", 32, True, BLUE)
    text(d, (103, 1890), "足元の受けに約500 gの重りを載せる。", 29, False, MUTED)

    # Adjustment overview, retaining the numbered arrows and giving the legend.
    d.rounded_rectangle((1210, 241, 2340, 1295), 24, fill=BG)
    text(d, (1246, 267), "組んだまま高さを微調整", 37, True)
    fit(canvas, adjust, (1228, 335, 1094, 810))
    text(d, (1253, 1159), "① M3×20：高さ調整　　② M3×15：ロック", 31, True)
    text(d, (1253, 1217), "設計範囲 −0.4〜＋0.6 mm ／ 1回転 0.5 mm", 29, False, MUTED)

    # Rotor detail deliberately displays only the fin part, not the long shaft.
    d.rounded_rectangle((1210, 1335, 2340, 1960), 24, fill=BG)
    text(d, (1246, 1361), "採用ローターはC：一本の丸い曲がり棒", 35, True)
    fit(canvas, rotor, (1225, 1450, 475, 435))
    text(d, (1705, 1470), "フィーダー本体 14個", 32, True)
    text(d, (1705, 1526), "台座 25個", 32, True)
    text(d, (1705, 1599), "合計 19種類 / 39個", 34, True, BLUE)
    text(d, (1705, 1672), "M3ネジ 46本 / ナット 46個", 29)
    text(d, (1705, 1725), "698Zベアリング 2個", 29)
    text(d, (1705, 1778), "PTFEチューブ 内径6 / 外径8 mm", 26)
    text(d, (1251, 1890), "羽部分の拡大。軸は省略表示。", 26, False, MUTED)

    text(d, (74, 2012), "P1S / PLA / 0.4 mmノズル", 31, True)
    text(d, (670, 2012), "台座：ブリムなし、サポートなし　　Cローター：ツリーサポート＋2層ラフト", 29)
    text(d, (74, 2070), "図は公称CAD位置。実物で効果のあった一定方向の中心ずれは、寸法未測定のため図に反映していません。", 28, False, MUTED)
    text(d, (74, 2123), "内部を見せるためファンネルを断面表示。モーター、配線、重りは省略。色は部品の識別用です。", 28, False, MUTED)

    dest = OUT / "final_overview.png"
    canvas.save(dest)
    print(dest)


if __name__ == "__main__":
    main()
