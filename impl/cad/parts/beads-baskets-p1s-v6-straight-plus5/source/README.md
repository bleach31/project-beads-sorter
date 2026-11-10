# 更新モデルの再生成

Pythonと `requirements.txt` のライブラリを用意し、`python build.py` を実行します。同梱の元v5形状関数 `reference/v5_chute.py` を使用し、半径111 mmと元の一定勾配でスロープを作ります。元の参照関数ファイルは変更せず、`chute_plus5.py` で寸法を指定しています。

`build.py` が再生成するのは、新スロープSTL、新しい2枚の印刷3MF、更新した稼働状態の組立3MF/GLB、寸法と配置の確認JSONです。変更対象外の部品は同梱のSTL、収納状態は固定した既存データを使います。

配置は `plate_layouts.json` に記録しています。各 `instance` が1個の独立部品で、スロープ2個用は同じ `part` を2回配置します。

`python render_preview.py` でモデル画像と2枚の配置図を作ります。画像にはWindowsのMeiryoフォントを使っています。別の環境ではフォントのパスを変更してください。

これらはCADの形状と配置の生成で、スライサーではありません。サポートやG-codeは生成しません。変更対象外の容器と蓋の元形状まで再生成したい場合は、元の `beads-baskets-p1s-v5-central-integral` のソースを使用してください。
