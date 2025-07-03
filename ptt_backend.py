import asyncio
import websockets
import requests
from bs4 import BeautifulSoup
import json
import time
import os
import threading
from flask import Flask

# --- Flask App for Health Checks (to keep Web Service alive) ---
# 用於接收外部監控服務的請求，防止服務休眠
app = Flask(__name__)

@app.route('/')
def home():
    """A simple HTTP endpoint to respond to pinger services."""
    return "PTT Scraper WebSocket server is alive and running."

def run_flask_app():
    """Runs the Flask app in a separate thread."""
    # Render 會提供 PORT 環境變數給 Web Service
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)


# --- PTT Scraper ---
PTT_URL = "https://www.ptt.cc"
GOSSIPING_BOARD_URL = f"{PTT_URL}/bbs/Gossiping/index.html"

# PTT 八卦版需要 cookies 來通過 "我已滿18歲" 的檢查
cookies = {"over18": "1"}

# 在一個時間窗口內收集數據來計算 PNI
push_count = 0
boo_count = 0
last_calculation_time = time.time()

def get_pni_from_gossiping():
    """
    爬取 PTT 八卦版最新頁面，計算推文和噓文數。
    """
    global push_count, boo_count, last_calculation_time

    try:
        response = requests.get(GOSSIPING_BOARD_URL, cookies=cookies, timeout=5)
        response.raise_for_status() # 如果請求失敗，會拋出例外
        
        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.find_all("div", class_="r-ent")

        # 這個邏輯會累積多次爬取的推噓文數
        for article in articles:
            push_tag = article.find("div", class_="nrec")
            if push_tag and push_tag.span:
                push_str = push_tag.span.string
                if push_str:
                    if push_str.startswith('X'): # 被噓到X的文章
                        try:
                            boo_count += int(push_str[1:]) * 10
                        except (ValueError, TypeError):
                            boo_count += 100 # 如果轉換失敗，當作X10
                    elif push_str.isdigit():
                        push_count += int(push_str)
                    elif push_str == '爆':
                        push_count += 100
        
        # 每分鐘計算一次 PNI 並廣播
        current_time = time.time()
        if current_time - last_calculation_time > 60:
            pni = (boo_count / (push_count + boo_count)) * 100 if (push_count + boo_count) > 0 else 0
            
            # 重置計數器，為下一個時間窗口做準備
            push_count = 0
            boo_count = 0
            last_calculation_time = current_time
            
            print(f"計算出的 PNI: {pni:.2f}%")
            return pni
            
    except requests.RequestException as e:
        print(f"爬取 PTT 時發生錯誤: {e}")
    except Exception as e:
        print(f"處理 PTT 數據時發生錯誤: {e}")
        
    return None # 如果還沒到計算時間，返回 None


# --- WebSocket Server ---
connected_clients = set()

async def register(websocket):
    """註冊新的客戶端連接"""
    connected_clients.add(websocket)
    print(f"新的客戶端連接: {websocket.remote_address}")

async def unregister(websocket):
    """移除斷開的客戶端連接"""
    connected_clients.remove(websocket)
    print(f"客戶端斷開連接: {websocket.remote_address}")

async def broadcast_pni():
    """定期爬取數據並廣播給所有客戶端"""
    while True:
        pni = get_pni_from_gossiping()
        
        if pni is not None and connected_clients:
            message = json.dumps({
                "type": "pni_update",
                "timestamp": time.time(),
                "pni": pni
            })
            # 使用 asyncio.gather 來並行發送消息給所有客戶端
            await asyncio.gather(*[client.send(message) for client in connected_clients])
            print(f"已廣播 PNI 數據: {pni:.2f}%")
        
        # 每 10 秒爬取一次
        await asyncio.sleep(10)

async def handler(websocket, path):
    """處理 WebSocket 連接的主函數"""
    await register(websocket)
    try:
        # 保持連接開啟，直到客戶端斷開
        await websocket.wait_closed()
    finally:
        await unregister(websocket)

async def main_websocket():
    """WebSocket 伺服器主邏輯"""
    # WebSocket 伺服器端口。Render 會自動處理端口映射。
    websocket_port = 10000 
    async with websockets.serve(handler, "0.0.0.0", websocket_port):
        print(f"WebSocket 伺服器已啟動於 ws://localhost:{websocket_port}")
        await broadcast_pni()

if __name__ == "__main__":
    # 在一個獨立的線程中啟動 Flask HTTP 伺服器
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()
    print("HTTP 伺服器已啟動於一個獨立線程中。")

    # 在主線程中啟動 WebSocket 伺服器
    try:
        asyncio.run(main_websocket())
    except KeyboardInterrupt:
        print("伺服器已手動關閉。")
