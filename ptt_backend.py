import asyncio
import requests
from bs4 import BeautifulSoup
import json
import time
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# --- FastAPI App ---
app = FastAPI()

# --- PTT Scraper ---
PTT_URL = "https://www.ptt.cc"
GOSSIPING_BOARD_URL = f"{PTT_URL}/bbs/Gossiping/index.html"
cookies = {"over18": "1"}

class PNI_Calculator:
    def __init__(self):
        self.push_article_count = 0
        self.boo_article_count = 0
        self.last_calculation_time = time.time()

    def get_pni(self):
        """
        爬取 PTT 並計算 PNI。
        新邏輯：計算「噓文文章數」佔「總文章數」的比例，作為情緒指標。
        """
        try:
            # 添加瀏覽器標頭，模擬真人訪問，避免被快取
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(GOSSIPING_BOARD_URL, cookies=cookies, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            articles = soup.find_all("div", class_="r-ent")
            
            # 在這個爬取週期內，計算推文和噓文的文章數量
            current_push_articles = 0
            current_boo_articles = 0
            
            for article in articles:
                push_tag = article.find("div", class_="nrec")
                if push_tag and push_tag.span:
                    push_str = push_tag.span.string
                    if push_str:
                        if push_str.startswith('X'): # 任何 'X' 開頭的都算噓文文章
                            current_boo_articles += 1
                        elif push_str.isdigit() or push_str == '爆': # 數字或 '爆' 都算推文文章
                            current_push_articles += 1
            
            # 累積到全域計數器
            self.push_article_count += current_push_articles
            self.boo_article_count += current_boo_articles
            
            print(f"本次爬取: {current_push_articles} 推文文章, {current_boo_articles} 噓文文章。累積: {self.push_article_count} 推, {self.boo_article_count} 噓")

            current_time = time.time()
            if current_time - self.last_calculation_time > 60:
                total_articles = self.push_article_count + self.boo_article_count
                # PNI 現在是噓文文章的百分比
                pni = (self.boo_article_count / total_articles) * 100 if total_articles > 0 else 0
                
                # 重置計數器
                self.push_article_count = 0
                self.boo_article_count = 0
                self.last_calculation_time = current_time
                
                print(f"--- 每分鐘計算 ---")
                print(f"總文章數: {total_articles}, PNI (噓文文章比例): {pni:.2f}%")
                print(f"--------------------")
                return pni
                
        except Exception as e:
            print(f"[錯誤] 爬取或計算 PNI 時發生錯誤: {e}")
            
        return None

pni_calculator = PNI_Calculator()

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"新的客戶端連接: {websocket.client.host}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print(f"客戶端斷開連接: {websocket.client.host}")

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

# --- Background Task for Broadcasting ---
async def broadcast_pni_periodically():
    """定期爬取數據並廣播給所有客戶端"""
    while True:
        pni = pni_calculator.get_pni()
        
        if pni is not None:
            message = json.dumps({
                "type": "pni_update",
                "timestamp": time.time(),
                "pni": pni
            })
            await manager.broadcast(message)
            print(f"已廣播 PNI 數據: {pni:.2f}%")
        
        await asyncio.sleep(10) # 每 10 秒執行一次

# --- API Endpoints ---
@app.on_event("startup")
async def startup_event():
    """在應用啟動時，開始背景廣播任務"""
    asyncio.create_task(broadcast_pni_periodically())

@app.get("/")
def read_root():
    """HTTP 端點，用於回應 Pinger 服務，防止休眠"""
    return {"status": "PTT Scraper WebSocket server is alive"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 端點，處理客戶端的連接"""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
