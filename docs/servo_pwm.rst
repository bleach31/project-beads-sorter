GPIO19でサーボを制御する
===========================

Raspberry Pi 4のハードウェアPWMを使い、PythonライブラリなしでSG90を制御する。
GPIO19は物理ピン35にあり、PWM1を出力できる。

配線
----

.. list-table::
   :header-rows: 1
   :widths: 30 30 40

   * - SG90
     - 接続先
     - 備考
   * - 信号線
     - GPIO19（物理ピン35）
     - 3.3 VのPWM信号
   * - 電源線
     - 外部5 V電源
     - Raspberry PiのGPIOから給電しない
   * - GND線
     - 外部電源とRaspberry PiのGND
     - 両方のGNDを共通にする

.. warning::

   サーボの電源をRaspberry PiのGPIOから取ると、電圧降下による急な動作や
   Raspberry Piの再起動が発生することがある。十分な電流を供給できる外部5 V
   電源を使用すること。

ハードウェアPWMを有効にする
-----------------------------

アナログ音声はPWM0とPWM1を使用するため無効にする。
``/boot/firmware/config.txt`` にGPIO19のPWMオーバーレイを追加し、再起動する。

.. code-block:: console

   $ sudo sed -i 's/^dtparam=audio=on$/dtparam=audio=off/' /boot/firmware/config.txt
   $ grep -qxF 'dtoverlay=pwm,pin=19,func=2' /boot/firmware/config.txt \
       || echo 'dtoverlay=pwm,pin=19,func=2' \
       | sudo tee -a /boot/firmware/config.txt
   $ sudo reboot

再起動後、GPIO19が ``a5`` （Alt5）になっていることと、PWMデバイスが存在する
ことを確認する。

.. code-block:: console

   $ pinctrl get 19
   19: a5    pd | lo // GPIO19 = PWM1_CHAN1
   $ ls /sys/class/pwm/pwmchip*

サーボを指定角度へ動かす
------------------------

周期を20 ms（50 Hz）に設定し、PWM出力を開始する。以下は90度の例である。
数値の単位はナノ秒。

.. code-block:: console

   $ PWMCHIP=$(find /sys/class/pwm -maxdepth 1 -name 'pwmchip*' -print -quit)
   $ test -n "$PWMCHIP" || { echo 'PWM device not found' >&2; exit 1; }
   $ test -d "$PWMCHIP/pwm1" || echo 1 | sudo tee "$PWMCHIP/export"
   $ echo 20000000 | sudo tee "$PWMCHIP/pwm1/period"
   $ echo 1400000 | sudo tee "$PWMCHIP/pwm1/duty_cycle"
   $ echo 1 | sudo tee "$PWMCHIP/pwm1/enable"

PWMはコマンド終了後も出力されるため、サーボは指定角度を保持する。

角度を変更する
--------------

0度から180度までの角度を指定する。パルス幅は0度で0.5 ms、90度で1.4 ms、
180度で2.3 msとなる。

.. code-block:: console

   $ ANGLE=90
   $ test "$ANGLE" -ge 0 -a "$ANGLE" -le 180 \
       || { echo 'ANGLE must be between 0 and 180' >&2; exit 1; }
   $ echo $((500000 + ANGLE * 10000)) \
       | sudo tee "$PWMCHIP/pwm1/duty_cycle"

サーボによって可動範囲には差がある。端で振動したり機構に当たったりする場合は、
0度および180度付近を避けて安全な範囲に調整する。

PWMを停止する
-------------

次のコマンドでPWMを停止し、サーボを解放する。

.. code-block:: console

   $ echo 0 | sudo tee "$PWMCHIP/pwm1/enable"

停止後にサーボが負荷で動くのは、保持トルクがなくなるためである。
PWM出力中に勢いよく別の角度へ動く場合は、外部5 V電源の容量、GNDの共通接続、
信号線の接触、および別プロセスからのGPIO操作を確認する。