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
app = Flask(__name__)

@app.route('/')
def home():
    """A simple HTTP endpoint to respond to pinger services."""
    return "PTT Scraper WebSocket server is alive and running."

def run_flask_app():
    """Runs the Flask app in a separate thread."""
    # Render provides the PORT environment variable for Web Services
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)


# --- PTT Scraper ---
PTT_URL = "https://www.ptt.cc"
GOSSIPING_BOARD_URL = f"{PTT_URL}/bbs/Gossiping/index.html"

cookies = {"over18": "1"}
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
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.find_all("div", class_="r-ent")

        # This logic accumulates pushes/boos from multiple scrapes
        for article in articles:
            push_tag = article.find("div", class_="nrec")
            if push_tag and push_tag.span:
                push_str = push_tag.span.string
                if push_str:
                    if push_str.startswith('X'):
                        boo_count += int(push_str[1:]) * 10
                    elif push_str.isdigit():
                        push_count += int(push_str)
                    elif push_str == '爆':
                        push_count += 100
        
        current_time = time.time()
        if current_time - last_calculation_time > 60:
            pni = (boo_count / (push_count + boo_count)) * 100 if (push_count + boo_count) > 0 else 0
            
            # Reset counters for the next window
            push_count = 0
            boo_count = 0
            last_calculation_time = current_time
            
            print(f"計算出的 PNI: {pni:.2f}%")
            return pni
            
    except requests.RequestException as e:
        print(f"爬取 PTT 時發生錯誤: {e}")
    except Exception as e:
        print(f"處理 PTT 數據時發生錯誤: {e}")
        
    return None


# --- WebSocket Server ---
connected_clients = set()

async def register(websocket):
    connected_clients.add(websocket)
    print(f"新的客戶端連接: {websocket.remote_address}")

async def unregister(websocket):
    connected_clients.remove(websocket)
    print(f"客戶端斷開連接: {websocket.remote_address}")

async def broadcast_pni():
    while True:
        pni = get_pni_from_gossiping()
        
        if pni is not None and connected_clients:
            message = json.dumps({
                "type": "pni_update",
                "timestamp": time.time(),
                "pni": pni
            })
            await asyncio.gather(*[client.send(message) for client in connected_clients])
            print(f"已廣播 PNI 數據: {pni:.2f}%")
        
        await asyncio.sleep(10)

async def handler(websocket, path):
    await register(websocket)
    try:
        await websocket.wait_closed()
    finally:
        await unregister(websocket)

async def main():
    # The WebSocket server port should not conflict with the Flask port.
    # Render's Web Service expects the HTTP server on the PORT env var.
    # We can run WebSocket on a different, fixed port.
    websocket_port = 10000 
    async with websockets.serve(handler, "0.0.0.0", websocket_port):
        print(f"WebSocket 伺服器已啟動於 ws://localhost:{websocket_port}")
        await broadcast_pni() # Changed to await the broadcast directly

if __name__ == "__main__":
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()
    print("HTTP 伺服器已啟動於一個獨立線程中。")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("伺服器已手動關閉。")
