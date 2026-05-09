import RPi.GPIO as GPIO
import time

# --- 設定 ---
SERVO_PIN = 21
INTERVAL = 1.0  # 同期インターバル (秒)
FREQUENCY = 50  # SG90の基本周波数 (50Hz)

# --- 初期化 ---
GPIO.setmode(GPIO.BCM)
GPIO.setup(SERVO_PIN, GPIO.OUT)
servo = GPIO.PWM(SERVO_PIN, FREQUENCY)

# サーボ初期位置
servo.start(0.0)

def set_angle(angle):
    """角度(0-180)を指定してサーボを動かす"""
    # 0度:2.5%, 90度:7.5%, 180度:12.0% (目安)
    duty = 2.5 + (11.5 - 2.5) * (angle / 180.0)
    servo.ChangeDutyCycle(duty)
    print(f"Angle: {angle} ({duty:.1f}%)")

try:
    while True:
        # 0度へ移動
        set_angle(0)
        time.sleep(INTERVAL)
        
        # 180度へ移動
        set_angle(180)
        time.sleep(INTERVAL)

except KeyboardInterrupt:
    # Ctrl+Cで終了
    print("Exiting...")
    servo.stop()
    GPIO.cleanup()