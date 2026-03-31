システム仕様（v1）
============

認識
----

.. spec:: カメラ色識別
   :id: SPEC_001
   :status: open
   :tags: vision
   :links: REQ_001, REQ_002

   Pi Cameraでビーズの色を識別する。

フィーダー機構
--------------

.. spec:: フィーダー機構
   :id: SPEC_002
   :status: open
   :tags: feeder
   :links: REQ_004

   DCモーター＋ロート型ケース＋テフロンチューブでビーズを供給する。
   DCモーターでロート内をかき混ぜ、ビーズが自重でチューブに入る方式。

排出・仕分け機構
----------------

.. spec:: 排出機構
   :id: SPEC_003
   :status: open
   :tags: ejector
   :links: REQ_001

   サーボモーター（SG90）でビーズを押出/落下排出する。

.. spec:: 回転テーブル仕分け
   :id: SPEC_004
   :status: open
   :tags: ejector
   :links: REQ_001, REQ_002

   ステッピングモーターで回転テーブルを制御し、排出先を10色分切り替える。

制御
----

.. spec:: Raspberry Pi制御
   :id: SPEC_005
   :status: open
   :tags: software
   :links: REQ_001

   Raspberry Pi上のPythonアプリで全体制御する。

筐体
-----

.. spec:: 3Dプリント筐体設計
   :id: SPEC_006
   :status: open
   :tags: mechanical
   :links: REQ_005

   FreeCAD等で設計し、3Dプリントで製作する。
