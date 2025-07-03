import asyncio
import requests
from bs4 import BeautifulSoup
import json
import time
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy import create_engine, Column, Integer, Float, DateTime, desc
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta

# --- Database Setup (SQLAlchemy) ---
# 從環境變數讀取 Render 提供的內部資料庫 URL
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 定義資料庫中的資料表結構
class PniRecord(Base):
    __tablename__ = "pni_records"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    pni = Column(Float, index=True)

# 應用啟動時創建資料表
Base.metadata.create_all(bind=engine)

# --- FastAPI App ---
app = FastAPI()

# --- PTT Scraper (Deep Scrape Logic) ---
PTT_URL = "https://www.ptt.cc"
GOSSIPING_BOARD_URL = f"{PTT_URL}/bbs/Gossiping/index.html"
cookies = {"over18": "1"}
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

def deep_scrape_pni():
    """
    深度分析：進入每篇文章內頁，精準計算 PNI。
    """
    try:
        # 1. 爬取列表頁，取得文章網址
        response = requests.get(GOSSIPING_BOARD_URL, cookies=cookies, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.find_all("div", class_="r-ent")
        article_urls = [PTT_URL + a.find('a')['href'] for a in articles if a.find('a')]

        total_push = 0
        total_boo = 0
        
        # 2. 逐一進入文章內頁
        for url in article_urls:
            try:
                # 加入延遲，避免請求過於頻繁
                time.sleep(0.5) 
                
                article_res = requests.get(url, cookies=cookies, headers=headers, timeout=10)
                article_soup = BeautifulSoup(article_res.text, 'html.parser')
                
                # 3. 計算內頁的推噓文數
                pushes = article_soup.find_all('span', class_='push-tag', string=lambda text: '推' in text)
                boos = article_soup.find_all('span', class_='push-tag', string=lambda text: '噓' in text)
                
                total_push += len(pushes)
                total_boo += len(boos)
            except Exception as e:
                print(f"[警告] 爬取內頁 {url} 失敗: {e}")

        # 4. 計算這一批文章的總 PNI
        total_votes = total_push + total_boo
        pni = (total_boo / total_votes) * 100 if total_votes > 0 else 0
        
        print(f"--- 深度分析完成 ---")
        print(f"總推文: {total_push}, 總噓文: {total_boo}, PNI: {pni:.2f}%")
        print(f"--------------------")
        
        return pni

    except Exception as e:
        print(f"[錯誤] 爬取列表頁失敗: {e}")
        return None

# --- WebSocket Connection Manager ---
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

# --- Background Task for Scraping and Broadcasting ---
async def scrape_and_save_periodically():
    while True:
        pni = deep_scrape_pni()
        
        if pni is not None:
            # 1. 將新數據存入資料庫
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

            # 2. 廣播最新數據
            message = json.dumps({"type": "pni_update", "timestamp": time.time(), "pni": pni})
            await manager.broadcast(message)
            print(f"已廣播最新 PNI 數據。")
        
        # 將爬取週期拉長為 3 分鐘 (180秒)，以確保穩定性
        await asyncio.sleep(180)

# --- API Endpoints ---
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(scrape_and_save_periodically())

@app.get("/")
def read_root():
    return {"status": "PTT Scraper API is alive"}

@app.get("/api/history")
def get_history(timescale: str = "30m"):
    db = SessionLocal()
    try:
        if timescale == "30m":
            start_time = datetime.utcnow() - timedelta(hours=24)
        elif timescale == "1h":
            start_time = datetime.utcnow() - timedelta(days=3)
        else: # day
            start_time = datetime.utcnow() - timedelta(days=30)
            
        records = db.query(PniRecord).filter(PniRecord.timestamp >= start_time).order_by(desc(PniRecord.timestamp)).all()
        
        # 這部分可以在前端做，但為了示範，這裡也可以做簡單的彙總
        # 為保持簡單，我們先回傳原始數據點，讓前端處理
        return [{"timestamp": r.timestamp.isoformat(), "pni": r.pni} for r in records]

    except SQLAlchemyError as e:
        print(f"[錯誤] 查詢歷史數據失敗: {e}")
        return {"error": "Could not retrieve history"}
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
