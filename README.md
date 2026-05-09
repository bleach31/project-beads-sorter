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


## Test

camera test

```bash
sudo apt update
sudo apt install -y python3-picamera2

rm -rf .venv
uv venv --system-site-packages
uv sync

uv run uvicorn stream:app --host 0.0.0.0 --port 8000
```

pusher(sg90) test
```bash
sudo python3 pusher.py
```