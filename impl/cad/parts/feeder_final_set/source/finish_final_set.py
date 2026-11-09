"""Write the final kit entry page and verify/capture its distribution files."""
from pathlib import Path
import hashlib
import json
import re
import zipfile
import trimesh

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def estimate(source):
    data = read_json(source)
    assert data['returncode'] == 0 and data['result']['return_code'] == 0
    plates = data['result']['sliced_plates']
    assert len(plates) == 1 and not plates[0]['warning_message']
    plate = plates[0]
    return dict(source=source, seconds=plate['total_predication'],
                PLA_g=sum(f['total_used_g'] for f in plate['filaments']),
                warnings=plate['warning_message'])


def time_ja(seconds):
    mins = int(seconds / 60 + .5)
    hours, minutes = divmod(mins, 60)
    return (f'{hours}時間' if hours else '') + f'{minutes:02d}分'


def main():
    manifest = read_json('manifest.json')
    feeder = estimate('slicer/feeder/slice_summary.json')
    stand = estimate('verification/stand_slice_summary.json')
    rotor = estimate('slicer/rotor/slice_summary.json')
    total_seconds = feeder['seconds'] + stand['seconds']
    total_g = feeder['PLA_g'] + stand['PLA_g']
    summary = dict(main_plates=2, main_parts=39, feeder=feeder, stand=stand, optional_rotor=rotor,
                   complete_set_seconds=total_seconds, complete_set_PLA_g=total_g,
                   optional_rotor_included_in_main_feeder_plate=True,
                   physical_print_time_measured=False, printer_transmission_performed=False)
    (ROOT / 'print_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    readme = f'''# Feeder最終セット

Cの丸い曲がり棒ローター、ネジ式高さ調整、出口高さ約50cmの軽量台座をまとめたセットです。
採用部品の形状を保ったまま、必要な部品だけを2枚の印刷プレートへ整理しました。
2026年11月8日時点の構成です。

![最終構成](preview/final_overview.png)

## 印刷するファイル

Bambu Studioで下のスライス済み3MFを開きます。
P1S、0.4mmノズル、単色PLA、Textured PEIプレートを設定済みです。

| 印刷 | 開くファイル | 内容 | 時間の予測 | PLAの予測 |
|---|---|---|---:|---:|
| 1枚目 | [本体の3MF](print/01_feeder_P1S_PLA_sliced.3mf) | ファンネル、Cローター、高さ調整など14個 | 約{time_ja(feeder['seconds'])} | {feeder['PLA_g']:.1f}g |
| 2枚目 | [台座の3MF](print/02_stand_P1S_PLA_sliced.3mf) | 脚、足、重り受けなど25個 | 約{time_ja(stand['seconds'])} | {stand['PLA_g']:.1f}g |
| 合計 | 上の2枚 | 19種類、39個 | **約{time_ja(total_seconds)}** | **{total_g:.1f}g** |

時間と材料量はBambu Studio 2.8.2.61のスライサー予測です。
実測時間ではなく、準備、冷却、支持材除去、組立の作業時間は含みません。
2枚目は既存V11の最終プロジェクトと同一データです。

[本体のプレート配置](preview/final_feeder_print_plate.png) ／ [台座のプレート配置](preview/stand_print_plate.png)

**Cローターだけ再印刷する場合**は、[C単品の3MF](print/optional_rotor_C_P1S_PLA_sliced.3mf)を使います。
予測は約{time_ja(rotor['seconds'])}、{rotor['PLA_g']:.1f}gです。
Cは1枚目にすでに含まれるため、初回に3枚すべてを印刷する必要はありません。
すでに本体が完成していれば、2枚目の台座だけで追加できます。

## 印刷設定

| 設定 | 本体プレート | 台座プレート |
|---|---|---|
| 主層／初層 | 0.16／0.20mm | 0.20／0.20mm |
| 外周 | 4周 | 4周 |
| 充填 | 40% Gyroid | 40% Gyroid |
| 上下 | 各6層 | 各5層 |
| サポート | Cだけツリー。他13個はOFF | 全部OFF |
| ラフト | Cだけ2層 | なし |
| ブリム | Cはなし。他13個は外側2mm | なし |

台座はブリムもサポートも使わない設計です。
本体はこれまでの印刷条件を引き継ぎ、Cの支持材と他部品の2mmブリムを残しています。
部品別設定を保存しているため、プレート全体のサポート設定だけで判断せず、Cのオブジェクト設定も確認できます。

ノズル220℃、プレート55℃を設定しています。
使用するPLAやプレートの指定温度が異なる場合は、その条件に合わせて再スライスします。
全体を層ごとに印刷する設定を使い、オブジェクトごとの順次印刷には変更しません。
個別STLもベッドへ置く向きを設定済みです。

`print` の末尾が `_sliced` ではない同名3MFは、再スライス用の設定済みプロジェクトです。
`plates` は形状と配置だけの3MFなので、そのまま同じ支持材設定が得られるわけではありません。

## 用意する部材

| 部材 | 最終セット全体の必要数 |
|---|---:|
| M3×6 | 1本 |
| M3×8 | 2本 |
| M3×12 | 5本 |
| M3×15 | 33本 |
| M3×20 | 5本 |
| M3ナット | 46個 |
| 698Zベアリング（8×19×6mm） | 2個 |
| PTFEチューブ | 内径6mm、外径8mm |
| 現在のモーター、適合する電源と配線 | 1式 |
| 幅2〜2.5mmの結束バンド | モーター用2本 |
| 低位置の重り | 約500g |

ねじは計46本です。
六角穴付き円筒頭を使い、ねじ長さは頭を除いて数えます。
リム4か所は本体と台座をM3×20で共締めします。
台座なし時のM3×12を重ねて数えていません。

## 組み立てと調整

[組立説明書](docs/assembly_ja.md)に、全部品一覧、ねじの使用箇所、初回組立、台座だけの追加、高さ調整をまとめました。
足元のつなぎ材とナットを先に組み、それから脚を付ける順番です。
高さは上のM3×20で動かし、外側のM3×15で固定します。
吐出口まで約500mm、足幅約300×300mmで、足元へ約500gの重りを載せます。

現物で効果のあった一定方向の中心ずれは、寸法未測定のためCADに数値として反映していません。
現在うまく動いている本体は、その設定のまま使えます。
V11台座の実印刷と強度、長期使用は未検証です。

## ファイルの使い分け

| フォルダー／ファイル | 用途 |
|---|---|
| print | P1S用の設定済み3MFとスライス済み3MF |
| parts | 採用した19種類の個別STL、3MF、編集用STEP |
| cad | 本体と台座の組立STEP。金物を含む確認用 |
| preview | 全体図、印刷配置、高さ調整、Cの拡大図 |
| docs/assembly_ja.md | 組立説明書 |
| manifest.json | 部品数、金物、元データとの対応 |
| print_summary.json | 2プレートとC単品の時間と材料量 |
| verification、slicer | 検証結果とスライス条件 |
| source | 今回の整理、配置、図の再生成スクリプト |

組立STEPには金物とPTFEの参照形状が含まれるので、印刷対象にはしません。
個別STEPはそのままCADで編集できます。
旧2枚羽、固定ブリッジ、A/B/D比較案、V10台座は配布用の印刷部品から除いています。
'''
    (ROOT / 'README_ja.md').write_text(readme, encoding='utf-8')

    checks = []
    for item in manifest['unchanged_copy_provenance']:
        path = ROOT / item['file']
        assert sha(path) == item['sha256'], item['file']
    for part in manifest['parts']:
        path = ROOT / part['files']['stl']
        mesh = trimesh.load_mesh(path)
        item = dict(name=part['name'], quantity=part['quantity'],
                    closed=bool(mesh.is_watertight), winding_consistent=bool(mesh.is_winding_consistent),
                    volume_mm3=float(mesh.volume), bottom_z_mm=float(mesh.bounds[0, 2]))
        assert item['closed'] and item['winding_consistent'] and item['volume_mm3'] > 0, item
        assert abs(item['bottom_z_mm']) < 1e-5, item
        checks.append(item)
    for doc in [ROOT / 'README_ja.md', ROOT / 'docs/assembly_ja.md']:
        content = doc.read_text(encoding='utf-8')
        for href in re.findall(r'\]\(([^)]+)\)', content):
            if '://' not in href:
                assert (doc.parent / href).exists(), (doc, href)
    for name in ['01_feeder', '02_stand', 'optional_rotor_C']:
        for suffix in ['', '_sliced']:
            path = ROOT / f'print/{name}_P1S_PLA{suffix}.3mf'
            with zipfile.ZipFile(path) as z:
                assert z.testzip() is None
                assert 'Metadata/project_settings.config' in z.namelist()
                if suffix:
                    assert any(n.endswith('.gcode') for n in z.namelist())
    for key, expected in [('feeder', 14), ('rotor', 1)]:
        paths = read_json(f'slicer/{key}/toolpath_verification.json')
        assert paths['object_count'] == expected and paths['plate_count'] == 1
        assert paths['geometry_preserved'] and paths['settings_preserved']
        assert paths['all_print_paths_inside_bed'] and paths['paths_touching_expanded_exclusion'] == 0
        assert paths['support_enabled_objects'] == ['C_curved_rod']
        assert not paths['warnings']
    report = dict(unchanged_source_files_verified=len(manifest['unchanged_copy_provenance']),
                  unique_print_meshes=checks, total_printed_parts=39,
                  hardware_screws=46, hardware_nuts=46, document_links_valid=True,
                  final_feeder_and_rotor_toolpath_reports_passed=True,
                  all_six_print_projects_valid_zip=True,
                  all_three_sliced_projects_contain_gcode=True)
    (ROOT / 'verification/final_package_verification.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    candidates = []
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(x in rel.parts for x in ['logs', 'draft', '__pycache__']):
            continue
        if path.suffix.lower() in ['.pyc', '.log', '.gcode']:
            continue
        if path.name in ['package_checksums.json']:
            continue
        candidates.append(path)
    checksums = {p.relative_to(ROOT).as_posix(): sha(p) for p in candidates}
    index = ROOT / 'package_checksums.json'
    index.write_text(json.dumps(checksums, ensure_ascii=False, indent=2), encoding='utf-8')
    candidates.append(index)
    output = ROOT.parent / 'feeder_final_set.zip'
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in candidates:
            z.write(path, Path(ROOT.name) / path.relative_to(ROOT))
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
        for rel, digest in checksums.items():
            assert hashlib.sha256(z.read(ROOT.name + '/' + rel)).hexdigest() == digest
    print(json.dumps(dict(package=str(output), files=len(candidates), bytes=output.stat().st_size,
                          print_summary=summary), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
