import asyncio
import httpx  # [UPGRADE] 使用非同步 HTTP 客戶端
from bs4 import BeautifulSoup
import json
import time
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, Float, DateTime, desc
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta

# --- FastAPI App & CORS ---
app = FastAPI()
origins = [
    "https://projim.github.io",
    "http://localhost",
    "http://127.0.0.1",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Database Setup ---
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class PniRecord(Base):
    __tablename__ = "pni_records"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    pni = Column(Float, index=True)

# [FIX] 資料表創建邏輯被移到下面的 startup_event 中

# --- PTT Scraper (Async Deep Scrape Logic) ---
PTT_URL = "https://www.ptt.cc"
GOSSIPING_BOARD_URL = f"{PTT_URL}/bbs/Gossiping/index.html"
cookies = {"over18": "1"}
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

async def deep_scrape_pni():
    """
    非同步深度分析：進入每篇文章內頁，精準計算 PNI。
    """
    try:
        async with httpx.AsyncClient(cookies=cookies, headers=headers, timeout=20) as client:
            # 1. 爬取列表頁
            response = await client.get(GOSSIPING_BOARD_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            articles = soup.find_all("div", class_="r-ent")
            article_urls = [PTT_URL + a.find('a')['href'] for a in articles if a.find('a')]

            total_push = 0
            total_boo = 0
            
            # 2. 逐一進入文章內頁
            for url in article_urls:
                try:
                    await asyncio.sleep(0.5)  # [UPGRADE] 使用非同步延遲
                    article_res = await client.get(url)
                    article_soup = BeautifulSoup(article_res.text, 'html.parser')
                    pushes = article_soup.find_all('span', class_='push-tag', string=lambda text: '推' in text)
                    boos = article_soup.find_all('span', class_='push-tag', string=lambda text: '噓' in text)
                    total_push += len(pushes)
                    total_boo += len(boos)
                except Exception as e:
                    print(f"[警告] 爬取內頁 {url} 失敗: {e}")

            # 3. 計算 PNI
            total_votes = total_push + total_boo
            pni = (total_boo / total_votes) * 100 if total_votes > 0 else 0
            
            print(f"--- 深度分析完成 ---")
            print(f"總推文: {total_push}, 總噓文: {total_boo}, PNI: {pni:.2f}%")
            print(f"--------------------")
            
            return pni

    except Exception as e:
        print(f"[錯誤] 爬取列表頁失敗: {e}")
        return None

# --- WebSocket & Background Task ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

async def scrape_and_save_periodically():
    while True:
        pni = await deep_scrape_pni()  # [UPGRADE] 使用 await
        
        if pni is not None:
            db = SessionLocal()
            try:
                new_record = PniRecord(pni=pni)
                db.add(new_record)
                db.commit()
                print(f"PNI {pni:.2f}% 已成功存入資料庫。")
            except SQLAlchemyError as e:
                print(f"[錯誤] 寫入資料庫失敗: {e}")
                db.rollback()
            finally:
                db.close()

            message = json.dumps({"type": "pni_update", "timestamp": time.time(), "pni": pni})
            await manager.broadcast(message)
            print(f"已廣播最新 PNI 數據。")
        
        await asyncio.sleep(180)

# --- API Endpoints & Startup Event ---
@app.on_event("startup")
async def startup_event():
    """在應用啟動時，安全地初始化資料庫並開始背景任務"""
    print("伺服器啟動中...")
    try:
        # [FIX] 將資料表創建移到這裡，確保在伺服器啟動後才執行
        print("正在檢查並創建資料庫表格...")
        Base.metadata.create_all(bind=engine)
        print("資料庫表格檢查完畢。")
    except Exception as e:
        print(f"[重大錯誤] 資料庫初始化失敗: {e}")
        # 在生產環境中，這裡可能需要更複雜的重試邏輯
    
    print("正在啟動背景爬蟲任務...")
    asyncio.create_task(scrape_and_save_periodically())
    print("背景任務已啟動。")

@app.get("/")
def read_root():
    return {"status": "PTT Scraper API is alive"}

@app.get("/api/history")
def get_history(timescale: str = "30m"):
    db = SessionLocal()
    try:
        # ... (此部分邏輯不變) ...
        if timescale == "30m":
            start_time = datetime.utcnow() - timedelta(hours=24)
        elif timescale == "1h":
            start_time = datetime.utcnow() - timedelta(days=3)
        else:
            start_time = datetime.utcnow() - timedelta(days=30)
        records = db.query(PniRecord).filter(PniRecord.timestamp >= start_time).order_by(desc(PniRecord.timestamp)).all()
        return [{"timestamp": r.timestamp.isoformat(), "pni": r.pni} for r in records]
    finally:
        db.close()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
