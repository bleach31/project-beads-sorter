import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse

# 🌟 Piカメラ専用の公式モダンライブラリ
from picamera2 import Picamera2

app = FastAPI()

def generate_frames():
    print("📸 PiCamera2を初期化しています...")
    
    # カメラインスタンスの生成
    picam2 = Picamera2()
    
    # 🌟 Piカメラのハードウェア設定（OpenCVで扱いやすいBGRフォーマットに指定）
    config = picam2.create_video_configuration(main={"size": (640, 480), "format": "BGR888"})
    picam2.configure(config)
    
    # センサー起動
    picam2.start()
    print("🎥 Piカメラからのストリーミング開始！")

    try:
        while True:
            # ハードウェアから直接Numpy配列（画像データ）を超高速で取得
            frame = picam2.capture_array()

            # Picamera2はRGB順で返すため、OpenCV(BGR)に変換
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            # 中心部に20x20の枠を描画
            h, w = frame.shape[:2]
            cx, cy = w // 2, h // 2
            x1, y1 = cx - 10, cy - 10
            x2, y2 = cx + 10, cy + 10
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

            # 枠内の平均色を取得 (BGR -> RGB表示用)
            roi = frame[y1:y2, x1:x2]
            avg_bgr = np.mean(roi, axis=(0, 1)).astype(int)
            r, g, b = int(avg_bgr[2]), int(avg_bgr[1]), int(avg_bgr[0])

            # フレーム下部にRGB値テキストを描画
            text = f"R:{r} G:{g} B:{b}"
            cv2.putText(frame, text, (w // 2 - 80, h - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # FastAPIで送るためにJPEGにエンコード
            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            
            # ブラウザに映像のコマを連続送信
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
    finally:
        print("🛑 カメラを安全に解放しました")
        picam2.stop()
        picam2.close()

@app.get("/")
def index():
    """ブラウザでアクセスした時のHTMLページ"""
    html_content = """
    <html>
        <head>
            <title>Beads Sorter Live Feed</title>
            <style>
                body { background-color: #1e1e1e; color: #d4d4d4; text-align: center; font-family: sans-serif; margin-top: 50px; }
                img { border: 4px solid #e51400; border-radius: 8px; box-shadow: 0 4px 12px rgba(229, 20, 0, 0.4); }
                h2 { color: #ffffff; }
            </style>
        </head>
        <body>
            <h2>Pi Camera Live</h2>
            <img src="/video_feed" width="640" height="480" />
            <p>Powered by FastAPI & Picamera2</p>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/video_feed")
def video_feed():
    """動画ストリーミングのエンドポイント"""
    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")
