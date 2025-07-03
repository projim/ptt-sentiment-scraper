import asyncio
import websockets
import requests
from bs4 import BeautifulSoup
import json
import time

# --- PTT Scraper ---
PTT_URL = "https://www.ptt.cc"
GOSSIPING_BOARD_URL = f"{PTT_URL}/bbs/Gossiping/index.html"

# PTT 八卦版需要 cookies 來通過 "我已滿18歲" 的檢查
cookies = {
    "over18": "1"
}

# 我們將在一個時間窗口內收集數據來計算 PNI
# 例如，每60秒計算一次這段時間內的總推噓文
push_count = 0
boo_count = 0
last_calculation_time = time.time()

def get_pni_from_gossiping():
    """
    爬取 PTT 八卦版最新頁面，計算推文和噓文數。
    這是一個簡化的方法，只看最新頁面的文章狀況作為即時指標。
    """
    global push_count, boo_count, last_calculation_time

    try:
        response = requests.get(GOSSIPING_BOARD_URL, cookies=cookies, timeout=5)
        response.raise_for_status() # 如果請求失敗，會拋出例外
        
        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.find_all("div", class_="r-ent")

        for article in articles:
            push_tag = article.find("div", class_="nrec")
            if push_tag and push_tag.span:
                push_str = push_tag.span.string
                if push_str:
                    if push_str.startswith('X'): # 爆文也是推文
                        push_count += 100 
                    elif push_str.isdigit():
                        push_count += int(push_str)
                    elif push_str == '爆':
                        push_count += 100
                    elif push_str.startswith('XX'): # 被噓到X
                        boo_count += 100
        
        # 每分鐘計算一次 PNI
        current_time = time.time()
        if current_time - last_calculation_time > 60:
            if (push_count + boo_count) > 0:
                pni = (boo_count / (push_count + boo_count)) * 100
            else:
                pni = 0 # 沒有推噓文

            # 重置計數器
            push_count = 0
            boo_count = 0
            last_calculation_time = current_time
            
            print(f"計算出的 PNI: {pni:.2f}%")
            return pni
            
    except requests.RequestException as e:
        print(f"爬取 PTT 時發生錯誤: {e}")
    except Exception as e:
        print(f"處理 PTT 數據時發生錯誤: {e}")
        
    return None # 如果沒有到計算時間，返回 None


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
            # 使用 asyncio.gather 來並行發送消息
            await asyncio.gather(
                *[client.send(message) for client in connected_clients]
            )
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

async def main():
    """程式進入點"""
    # 啟動廣播任務
    broadcast_task = asyncio.create_task(broadcast_pni())
    
    # 啟動 WebSocket 伺服器
    # 監聽所有網絡介面上的 8765 port
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("WebSocket 伺服器已啟動於 ws://localhost:8765")
        await asyncio.Future()  # 永遠運行

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("伺服器已手動關閉。")

