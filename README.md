# Project Beads Sorter

ビーズを自動仕分けするシステムのプロジェクトです。  
ソフトウェア（画像認識・制御）と3Dプリント用CADデータを含みます。

## プロジェクト構成

```
project-beads-sorter/
├── src/                  # ソースコード
│   ├── beads_sorter/     # メインパッケージ
│   └── firmware/         # ファームウェア（組み込み用）
├── tests/                # テストコード
├── docs/                 # ドキュメント（Sphinx）
├── cad/                  # 3Dプリント用CADデータ
│   ├── parts/            # 個別パーツ
│   ├── assembly/         # アセンブリデータ
│   └── exports/          # エクスポート済み STL/STEP
├── hardware/             # 回路図・配線図
├── scripts/              # ユーティリティスクリプト
├── configs/              # 設定ファイル
└── resources/            # 画像・モデルなどリソース
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
cd docs
uv run make html      # Linux/Mac
uv run make.bat html  # Windows
```

生成されたドキュメントは `docs/_build/html/index.html` で閲覧できます。

## ライセンス

TBD
