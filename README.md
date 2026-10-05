# Project Beads Sorter

[![CI](https://github.com/bleach31/project-beads-sorter/actions/workflows/ci.yml/badge.svg)](https://github.com/bleach31/project-beads-sorter/actions/workflows/ci.yml)
📖 [ドキュメント](https://bleach31.github.io/project-beads-sorter/)

ビーズを自動仕分けするシステムのプロジェクトです。  
ソフトウェア（画像認識・制御）と3Dプリント用CADデータを含みます。

## プロジェクト構成

```
project-beads-sorter/
├── impl/                     # 実装成果物
│   ├── src/                  # ソースコード
│   │   └── beads_sorter/     # Pythonパッケージ（Raspberry Pi上で動作）
│   │       ├── vision/       # ビーズ色認識
│   │       └── ejector/      # 仕分け（排出）機構制御
│   ├── cad/                  # 3Dプリント用CADデータ
│   │   ├── parts/            # 個別パーツ
│   │   ├── assembly/         # アセンブリデータ
│   │   └── exports/          # エクスポート済み STL/STEP
│   └── hardware/             # 回路図・配線図
├── tests/                    # テストコード
└── docs/                     # ドキュメント（Sphinx + sphinx-needs）
```

## セットアップ

```bash
# 依存パッケージのインストール（uv が .venv を自動作成）
uv sync

# 開発用パッケージも含めてインストール
uv sync --group dev

# ドキュメント用パッケージも含めてインストール
uv sync --group docs
```

## ドキュメント

```bash
uv run sphinx-build docs docs/_build/html
```

生成されたドキュメントは `docs/_build/html/index.html` で閲覧できます。

## ライセンス

TBD


## Web UI

Pi Camera、ステッピングモーター、押し出しサーボを接続したRaspberry Piで起動する。
サーボ用ハードウェアPWMの設定は
[GPIO19でサーボを制御する](https://bleach31.github.io/project-beads-sorter/servo_pwm.html)
を参照する。

```bash
sudo apt update
sudo apt install -y python3-picamera2

rm -rf .venv
uv venv --system-site-packages
uv sync

sudo .venv/bin/beads-sorter
```

同じネットワークの端末から ``http://<Raspberry PiのIPアドレス>:8000`` にアクセスする。
Web UIでは次の操作ができる。

- ビーズ領域全体から得た平均RGB値と認識色を常時確認
- 色認識、排出先への移動、押し出し、90度への復帰を一括実行
- スロット移動、押し出し、原点設定を個別実行
- 実際のビーズを使った10色の基準色および排出スロットの個別校正
- 認識色ごとの基準RGB、RGB判定範囲、排出スロットの一覧確認
- 独立した設定枠でのステッパー可動量・速度とサーボ角度・待ち時間の調整

ステッパーは柱を横切らない有限ストロークとして制御する。手動で機構をSLOT 0の
位置に合わせて「現在位置を原点に」を押し、「SLOT 0→9 可動量」を終端までの
フルステップ数に設定する。負数を指定すると回転方向が反転する。2相励磁の
フルステップ駆動を使用し、既定値は1536ステップ。以前のハーフステップ設定値を
使う場合は値を半分にしてから、実機の終端位置に合わせて再調整する。

SG90の既定位置は待機90度、押し出し175度。設定値は「校正・機構設定」から実機に
合わせて変更できる。

色は広い探索領域からビーズ表面を抽出し、その領域全体の平均RGBで判定する。
認識結果は常時更新するが、押し出し開始からプッシャーが90度へ戻るまでは直前の
認識結果を保持する。復帰完了後の新しいカメラフレームから自動更新を再開する。
色判定には校正した基準RGBと画面に表示されるチャンネル別のRGB閾値を使用する。

GPIOを接続せず画面とAPIだけを確認する場合はシミュレーションモードで起動する。

```bash
BEADS_SORTER_SIMULATION=1 uv run beads-sorter
```