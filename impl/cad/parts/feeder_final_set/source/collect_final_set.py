"""Collect adopted, unchanged parts and their provenance into the final kit.

Run from the original BSP workspace. The delivered STEP files can be edited
without this script or the older version directories.
"""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent

PARTS = [
    ('body', 'feeder_v7_short_m3', '01_funnel', 'ファンネル', 1),
    ('body', 'feeder_v7_short_m3', '04_bearing_cartridge', '軸受ケース', 1),
    ('body', 'feeder_v7_short_m3', '05_lower_cap', '下軸受押さえ', 1),
    ('body', 'feeder_v7_short_m3', '06_upper_cap', '上軸受押さえ', 1),
    ('body', 'feeder_v7_short_m3', '07_shaft_collar', '軸の抜け止めカラー', 1),
    ('body', 'feeder_v7_short_m3', '08_motor_cradle', 'モーター台', 1),
    ('body', 'feeder_v7_short_m3', '09_motor_spacer_left', '左モーター支柱', 1),
    ('body', 'feeder_v7_short_m3', '10_motor_spacer_right', '右モーター支柱', 1),
    ('rotor', 'feeder_v8_rotor_trials', 'C_curved_rod', 'Cローター（丸い曲がり棒）', 1),
    ('height_adjust', 'feeder_v9_height_adjust', '01_fixed_frame', '固定外枠とガイド', 1),
    ('height_adjust', 'feeder_v9_height_adjust', '02_moving_bridge', '昇降ブリッジ', 1),
    ('height_adjust', 'feeder_v9_height_adjust', '03_guide_shoe', 'ガイドシュー', 1),
    ('height_adjust', 'feeder_v9_height_adjust', '04_screw_bridge', '調整ねじの受け', 1),
    ('height_adjust', 'feeder_v9_height_adjust', '05_head_keeper', 'ねじ頭の抜け止め', 1),
    ('stand', 'feeder_v11_light_stand', '01_leg_segment', '脚材', 12),
    ('stand', 'feeder_v11_light_stand', '02_base_spoke', '足元のつなぎ材', 4),
    ('stand', 'feeder_v11_light_stand', '03_foot', '足', 4),
    ('stand', 'feeder_v11_light_stand', '04_top_saddle', '上部取付部', 4),
    ('stand', 'feeder_v11_light_stand', '05_ballast_tray', '一体の重り受け', 1),
]

SCREWS = [
    (6, 1, 'カラー'),
    (8, 2, 'モーター台から支柱上側'),
    (12, 3, '下軸受押さえ'),
    (12, 2, '昇降ブリッジから支柱下側'),
    (15, 3, '上軸受押さえ'),
    (15, 1, 'チューブ割り締め'),
    (15, 2, 'ガイドシューと昇降ブリッジ'),
    (15, 2, '調整ねじの受けと頭押さえ'),
    (15, 1, '高さ調整部のロック'),
    (15, 16, '台座4脚の下端、中間2か所、上端'),
    (15, 8, '足元つなぎ材の両端'),
    (20, 1, '高さ調整'),
    (20, 4, '固定外枠、ファンネルリム、台座上部取付部の共締め'),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    provenance = []

    def copy(source, target):
        src, dst = WORKSPACE / source, ROOT / target
        if not src.is_file():
            raise FileNotFoundError(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        assert sha(src) == sha(dst)
        provenance.append(dict(file=target, source=source, sha256=sha(dst)))

    parts = []
    for group, version, name, label, quantity in PARTS:
        files = {}
        for suffix in ('stl', '3mf', 'step'):
            dst = f'parts/{group}/{name}.{suffix}'
            copy(f'{version}/parts/{name}.{suffix}', dst)
            files[suffix] = dst
        parts.append(dict(group=group, name=name, label_ja=label, quantity=quantity,
                          source_version=version, files=files))

    for suffix in ('', '_sliced'):
        copy(f'feeder_v11_light_stand/slicer/projects/feeder_v11_light_stand_P1S_PLA{suffix}.3mf',
             f'print/02_stand_P1S_PLA{suffix}.3mf')
    copy('feeder_v11_light_stand/plates/light_stand_one_plate.3mf', 'plates/02_stand_geometry_only.3mf')
    copy('feeder_v11_light_stand/stand_500_light_assembly.step', 'cad/feeder_with_stand_VIEW_ONLY.step')
    copy('feeder_v9_height_adjust/feeder_v9_assembly.step', 'cad/feeder_body_VIEW_ONLY.step')

    for version, filename, target in [
        ('feeder_v9_height_adjust', 'height_adjust_overview.png', 'height_adjust_overview.png'),
        ('feeder_v9_height_adjust', 'guide_structure.png', 'height_adjust_guide.png'),
        ('feeder_v9_height_adjust', 'lead_section.png', 'height_adjust_screw.png'),
        ('feeder_v8_rotor_trials', 'C_curved_rod_detail.png', 'rotor_C.png'),
        ('feeder_v11_light_stand', 'print_plate.png', 'stand_print_plate.png'),
        ('feeder_v11_light_stand', 'joint_v11.png', 'stand_joint.png'),
    ]:
        copy(f'{version}/preview/{filename}', f'preview/{target}')
    copy('feeder_v11_light_stand/slicer/slice_summary.json', 'verification/stand_slice_summary.json')
    copy('feeder_v11_light_stand/slicer/toolpath_verification.json', 'verification/stand_toolpath_verification.json')
    copy('feeder_v11_light_stand/analysis/independent_verification.json', 'verification/stand_cad_verification.json')

    totals = {str(length): sum(n for l, n, _ in SCREWS if l == length) for length in (6, 8, 12, 15, 20)}
    assert len(parts) == 19 and sum(p['quantity'] for p in parts) == 39
    assert sum(totals.values()) == 46
    manifest = dict(
        kit='Feeder final set', collected_date='2026-11-08', units='mm',
        geometry_changed=False, parts=parts, part_types=19, printed_part_count=39,
        screws=[dict(size='M3', length_mm=l, quantity=n, use_ja=use) for l, n, use in SCREWS],
        screw_totals_by_length_mm=totals, screw_total=46, nut_M3_total=46,
        screw_head_reference=dict(type='socket cap', diameter_mm=5.5, height_mm=3.0),
        nut_reference=dict(across_flats_mm=5.5, thickness_mm=2.4),
        purchased_items=[
            dict(item='698Z', quantity=2, bore_mm=8, outer_diameter_mm=19, width_mm=6),
            dict(item='PTFE tube', inner_diameter_mm=6, outer_diameter_mm=8, length='route dependent'),
            dict(item='existing motor', quantity=1, model='not recorded'),
            dict(item='motor cable tie', quantity=2, width_mm='2 to 2.5'),
            dict(item='low-mounted ballast', mass_g_approx=500),
        ],
        constraints=dict(bead_diameter_mm=5, bead_length_mm=5, outlet_height_mm=500,
                         stand_footprint_mm=[300, 300], max_M3_length_mm=20),
        physical_observations_ja=[
            'Cは一本の丸い曲がり棒。A/B/Cの供給は良好との試験報告があり、Cの支持材除去がしやすかった。',
            'V9の片持ち支持で中心が一定方向へずれ、安定したビーズ群が形成されなくなったとの報告。',
            '落下前のビーズが羽と出口の間に挟まり、Cがたわんでパチンと解放することがある。',
            '偏心量は未測定でCADへ意図した数値としては組み込んでいない。',
            'V11台座の実印刷、実物の剛性、転倒、長期クリープは未確認。',
        ],
        cad_notes_ja=[
            '組立STEPは金物とPTFEの参照形状を含み、印刷対象ではない。',
            '組立STEPの参照金物ではカラー用M3×6とナット1組が省略されている。BOMには含める。',
            '組立STEPは公称中心位置。実物の静的な偏心を再現したものではない。',
        ],
        excluded_parts=['V7 02_ramp_rotor', 'V7 03_flat_bridge', 'V8 A/B/D trial rotors', 'V10 stand parts'],
        unchanged_copy_provenance=provenance,
    )
    target = ROOT / 'manifest.json'
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Collected {len(parts)} unique parts, 39 pieces, 46 screws; {len(provenance)} unchanged files.')


if __name__ == '__main__':
    main()
