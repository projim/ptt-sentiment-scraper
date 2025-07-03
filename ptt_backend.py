import asyncio
import websockets
import requests
from bs4 import BeautifulSoup
import json
import time
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# --- FastAPI App ---
# FastAPI 會同時處理 HTTP 和 WebSocket 請求
app = FastAPI()

# --- PTT Scraper ---
PTT_URL = "https://www.ptt.cc"
GOSSIPING_BOARD_URL = f"{PTT_URL}/bbs/Gossiping/index.html"
cookies = {"over18": "1"}

# 這些變數現在放在一個類別中，方便管理
class PNI_Calculator:
    def __init__(self):
        self.push_count = 0
        self.boo_count = 0
        self.last_calculation_time = time.time()

    def get_pni(self):
        """爬取 PTT 並計算 PNI"""
        try:
            response = requests.get(GOSSIPING_BOARD_URL, cookies=cookies, timeout=5)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            articles = soup.find_all("div", class_="r-ent")

            for article in articles:
                push_tag = article.find("div", class_="nrec")
                if push_tag and push_tag.span:
                    push_str = push_tag.span.string
                    if push_str:
                        if push_str.startswith('X'):
                            try:
                                self.boo_count += int(push_str[1:]) * 10
                            except (ValueError, TypeError):
                                self.boo_count += 100
                        elif push_str.isdigit():
                            self.push_count += int(push_str)
                        elif push_str == '爆':
                            self.push_count += 100
            
            current_time = time.time()
            if current_time - self.last_calculation_time > 60:
                pni = (self.boo_count / (self.push_count + self.boo_count)) * 100 if (self.push_count + self.boo_count) > 0 else 0
                
                self.push_count = 0
                self.boo_count = 0
                self.last_calculation_time = current_time
                
                print(f"計算出的 PNI: {pni:.2f}%")
                return pni
                
        except Exception as e:
            print(f"爬取或計算 PNI 時發生錯誤: {e}")
            
        return None

# 建立一個 PNI 計算器的實例
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
            # 保持連接開啟，等待客戶端斷開
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- To run this app locally, use: uvicorn ptt_backend:app --reload ---
# On Render, the start command will be: uvicorn ptt_backend:app --host 0.0.0.0 --port 10000
