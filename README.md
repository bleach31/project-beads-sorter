# Project Beads Sorter

[![CI](https://github.com/bleach31/project-beads-sorter/actions/workflows/ci.yml/badge.svg)](https://github.com/bleach31/project-beads-sorter/actions/workflows/ci.yml)
📖 [ドキュメント](https://bleach31.github.io/project-beads-sorter/)

ビーズを自動仕分けするシステムのプロジェクトです。  
ソフトウェア（画像認識・制御）と3Dプリント用CADデータを含みます。

## セットアップ（Raspberry Pi 実機）

**Raspberry Pi では、最初に `uv sync` を単独で実行しないこと。**
Picamera2 は Raspberry Pi OS のパッケージとして提供されるため、OS 標準の Python を使い、
システムパッケージを参照できる仮想環境を先に作成する必要がある。

### 1. 初回インストール

Raspberry Pi OS 上で、uv をインストール済みの状態から、リポジトリのルートで実行する。
OS 標準の Python は 3.10 以上が必要。

```bash
sudo apt update
sudo apt install -y python3-picamera2

uv venv --python /usr/bin/python3 --system-site-packages
uv sync --python /usr/bin/python3
```

既に通常の `uv sync` などで `.venv` を作ってしまった場合、または Permission denied
が発生する場合は、アプリを停止したうえで、リポジトリのルートから以下を実行して
仮想環境を作り直す。`.venv` のインストール済みパッケージは削除される。

```bash
sudo rm -rf .venv
uv venv --python /usr/bin/python3 --system-site-packages
uv sync --python /usr/bin/python3
```

`uv venv` と `uv sync` は一般ユーザーで実行する（sudo 不要）。

### 2. ハードウェアPWMを有効にする（初回のみ）

Raspberry Pi 4ではサーボの信号線をGPIO19（物理ピン35）に接続する。
アナログ音声とPWMが競合するため、以下の設定が必要。

```bash
sudo nano /boot/firmware/config.txt
```

既存の `dtparam=audio=on` は `off` に変更する。
**`dtoverlay=pwm,pin=19,func=2` は新しい行として追加する。既存の `dtoverlay` を上書き・削除しないこと。**
特に `dtoverlay=vc4-kms-v3d` はディスプレイ用の設定であり、削除するとデスクトップGUIが表示されなくなる場合がある。
設定が重複しないようにし、適用対象のセクション（例: `[all]`）に記載する。

設定例（既存のディスプレイ用オーバーレイを残したままPWM用の行を追加）：

```ini
dtparam=audio=off
dtoverlay=vc4-kms-v3d
dtoverlay=pwm,pin=19,func=2
```

上記は関連行のみの例であり、config.txt全体を置き換えるものではない。その他の既存設定は維持する。

保存して再起動する。

```bash
sudo reboot
```

再起動後、GPIO19の機能とPWMデバイスを確認する。

```bash
pinctrl get 19
ls /sys/class/pwm/
cat /sys/class/pwm/pwmchip*/npwm
```

GPIO19がAlt5のPWM機能になっており、チャンネル1を利用できる
PWMデバイス（npwmが2以上）が存在することを確認する。
PWMのexport、周期、デューティ比の設定はアプリが行うため、手動操作は不要。
サーボの電源には外部5 V電源を使い、Raspberry PiとGNDを共通にする。
詳細は [GPIO19でサーボを制御する](docs/servo_pwm.rst) を参照。

### 3. カメラの確認と起動

```bash
.venv/bin/python -c "from picamera2 import Picamera2; print('Picamera2 OK')"
```

上記が成功したら起動する。

```bash
sudo .venv/bin/beads-sorter
```

Picamera2 が見つからない場合は、まず OS 側で
`/usr/bin/python3 -c "import picamera2"` が成功するか確認する。
OS 側だけ成功する場合は、上記の仮想環境再構築手順を実行する。

### 4. 2回目以降の起動・アップデート

通常は仮想環境を作り直す必要はない。コード更新時のみ依存関係を同期する。

```bash
git pull
uv sync --python /usr/bin/python3
sudo .venv/bin/beads-sorter
```

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

## Web UI

Pi Camera、ステッピングモーター、押し出しサーボを接続したRaspberry Piで起動する。
サーボ用ハードウェアPWMの設定は
[GPIO19でサーボを制御する](https://bleach31.github.io/project-beads-sorter/servo_pwm.html)
を参照する。

起動は上記の「セットアップ（Raspberry Pi 実機）」を参照する。

同じネットワークの端末から ``http://<Raspberry PiのIPアドレス>:8000`` にアクセスする。
Web UIでは次の操作ができる。

- ビーズ領域全体から得た平均RGB値と認識色を常時確認
- 色認識、排出先への移動、押し出し、90度への復帰を一括実行
- RGB値が変化した次のビーズを待ちながら連続処理する完全自動仕分け
- スロット移動、押し出し、原点設定を個別実行
- 実際のビーズを使った10色の基準色および排出スロットの個別校正
- ビーズを外した状態の探索領域のRGB中央値を背景色として登録し、背景判定幅を個別調整
- 認識色ごとの基準RGB、RGB判定範囲、排出スロットの一覧確認
- ステッパー可動量・速度、全スロットの左右位置、サーボ角度・待ち時間の調整

ステッパーは柱を横切らない有限ストロークとして制御する。手動で機構をSLOT 0の
位置に合わせて「現在位置を原点に」を押し、「SLOT 0→9 可動量」を終端までの
フルステップ数に設定する。負数を指定すると回転方向が反転する。2相励磁の
フルステップ駆動を使用し、既定値は350ステップ。以前のハーフステップ設定値を
使う場合は値を半分にしてから、実機の終端位置に合わせて再調整する。
「全体位置調整」でステップ数を指定して左右へ動かすと、現在位置を即座に移動し、
全スロットの目標位置を同じ量だけずらす。右はSLOT 9方向、左はSLOT 0方向を表し、
可動量を負数にしても左右の意味は変わらない。「現在位置を原点に」を実行すると
位置オフセットは0へ戻る。画面上の位置オフセットは右を正、左を負として表示する。

SG90の既定位置は待機90度、押し出し175度。設定値は「校正・機構設定」から実機に
合わせて変更できる。

色は広い探索領域からビーズ表面を抽出し、その領域全体の平均RGBで判定する。
探索領域はカメラ画像の左16%・上20%から右98%・下91%までとする。
背景RGBの許容幅を超える画素から最大の連結領域を抽出する。固定基準点は使用せず、
穴や背景の画素を平均RGBに含めない。200画素未満の場合はビーズなしと判定する。
認識結果は常時更新するが、押し出し開始からプッシャーが90度へ戻るまでは直前の
認識結果を保持する。復帰完了後の新しいカメラフレームから自動更新を再開する。
色判定には校正した基準RGBと画面に表示されるチャンネル別のRGB閾値を使用する。
初期色はRGBベクトル距離が近い順に、白、ピンク、マゼンタ、紫、青、水色、緑、
緑茶、オレンジ、赤をSLOT 0～9へ割り当てる。マゼンタの初期基準RGBは
215 / 12 / 118とし、黒はソート対象に含めない。
判定外や信頼度不足の場合は押し出さず、完全自動仕分けでは1秒間隔で最大60秒間
新しいフレームで再判定し、未解決ならエラー停止する。
背景の初期RGBは黒背景の推定値30 / 30 / 30、許容幅は各チャンネル±25。
ビーズを外して背景を校正すると実測値に更新される。ビーズなしの場合、手動仕分け
では押し出さず、完全自動仕分けでは供給待ちに移行する。背景設定は再起動で初期値に戻る。

完全自動仕分けは開始時のビーズを処理した後、押し出し完了後のカメラ画像が
2フレーム以上かつ0.5秒間安定したときに次のビーズを処理する。直前との差を
条件にしないため、同じ色のビーズが連続する場合も処理を継続する。
停止操作は進行中の1回を完了してから反映し、カメラや機構のエラー時は自動停止する。

## 開発PC向けセットアップ（Raspberry Pi 実機用ではない）

PCでソフトウェア開発・テスト・ドキュメント生成を行う場合の手順。

```bash
uv sync --group dev
uv run pytest

# ドキュメント生成
uv sync --group docs
uv run sphinx-build docs docs/_build/html
```

生成されたドキュメントは `docs/_build/html/index.html` で閲覧できる。

GPIOを接続せず画面とAPIだけを確認する場合はシミュレーションモードで起動する。
開発PCにPi Cameraがない場合、カメラ映像は利用できない。

```bash
BEADS_SORTER_SIMULATION=1 uv run beads-sorter
```

## ライセンス

TBD
