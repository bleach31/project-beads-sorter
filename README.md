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

- カメラ中央ROI内の3×3（9点）から得たRGB値と認識色を確認
- 色認識、排出先への移動、押し出し、90度への復帰を一括実行
- スロット移動、押し出し、原点設定を個別実行
- 実際のビーズを使った10色の基準色および排出スロットの校正
- ステッパー可動量、速度、サーボ角度、待ち時間の調整

ステッパーは柱を横切らない有限ストロークとして制御する。手動で機構をSLOT 0の
位置に合わせて「現在位置を原点に」を押し、「SLOT 0→9 可動量」を終端までの
ステップ数に設定する。負数を指定すると回転方向が反転する。既定値は3072ステップ。

SG90の既定位置は待機90度、押し出し175度。設定値は「校正・機構設定」から実機に
合わせて変更できる。

色はROI全体の単純平均ではなく、表示された9点それぞれの小領域を測定し、中央値で
判定する。反射などで一部の点だけが白飛びしても、その値に引っ張られにくい。
仕分けに使用する認識結果はプッシャーが90度へ戻った状態で確定する。押し出し後は
復帰完了より新しいカメラフレームを待ち、次のビーズの色を認識する。

GPIOを接続せず画面とAPIだけを確認する場合はシミュレーションモードで起動する。

```bash
BEADS_SORTER_SIMULATION=1 uv run beads-sorter
```