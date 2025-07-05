import asyncio
import httpx  # 使用非同步 HTTP 客戶端
from bs4 import BeautifulSoup
import json
import time
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, Float, DateTime, desc, func
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta

# --- FastAPI App & CORS ---
app = FastAPI()
origins = [
    "https://projim.github.io",  # 您的 GitHub Pages 網址
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
engine = None
SessionLocal = None
Base = declarative_base()

class PniRecord(Base):
    __tablename__ = "pni_records"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    pni = Column(Float, index=True)

def initialize_database():
    """安全地初始化資料庫連線和表格"""
    global engine, SessionLocal
    if not DATABASE_URL:
        print("[重大錯誤] 找不到環境變數 DATABASE_URL。請在 Render 上設定。")
        return False
    
    db_url_for_sqlalchemy = DATABASE_URL
    if DATABASE_URL.startswith("postgres://"):
        db_url_for_sqlalchemy = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    print(f"[偵錯] 正在嘗試使用以下 URL 連接資料庫...")

    try:
        engine = create_engine(db_url_for_sqlalchemy)
        with engine.connect() as connection:
            print("[成功] 資料庫連接成功！")
        
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        
        print("正在檢查並創建資料庫表格...")
        Base.metadata.create_all(bind=engine)
        print("資料庫表格檢查完畢。")
        return True
    except Exception as e:
        print(f"[重大錯誤] 資料庫初始化失敗: {e}")
        return False

# --- PTT Scraper (Async Deep Scrape Logic) ---
PTT_URL = "https://www.ptt.cc"
GOSSIPING_BOARD_URL = f"{PTT_URL}/bbs/Gossiping/index.html"
cookies = {"over18": "1"}
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

async def deep_scrape_pni():
    """非同步深度分析：進入每篇文章內頁，精準計算 PNI。"""
    try:
        async with httpx.AsyncClient(cookies=cookies, headers=headers, timeout=30) as client:
            response = await client.get(GOSSIPING_BOARD_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            articles = soup.find_all("div", class_="r-ent")
            article_urls = [PTT_URL + a.find('a')['href'] for a in articles if a.find('a') and 'M.' in a.find('a')['href']]

            scrape_tasks = [scrape_article(client, url) for url in article_urls]
            results = await asyncio.gather(*scrape_tasks)
            
            total_push = sum(r[0] for r in results)
            total_boo = sum(r[1] for r in results)

            total_votes = total_push + total_boo
            pni = (total_boo / total_votes) * 100 if total_votes > 0 else 0
            
            print(f"--- 深度分析完成 ---")
            print(f"總推文: {total_push}, 總噓文: {total_boo}, PNI: {pni:.2f}%")
            print(f"--------------------")
            
            return pni
    except Exception as e:
        print(f"[錯誤] 爬取列表頁失敗: {e}")
        return None

async def scrape_article(client: httpx.AsyncClient, url: str):
    """爬取單一文章頁面並回傳推噓數"""
    try:
        await asyncio.sleep(0.2)
        article_res = await client.get(url)
        article_soup = BeautifulSoup(article_res.text, 'html.parser')
        pushes = article_soup.find_all('span', class_='push-tag', string=lambda text: '推' in text)
        boos = article_soup.find_all('span', class_='push-tag', string=lambda text: '噓' in text)
        return len(pushes), len(boos)
    except Exception as e:
        print(f"[警告] 爬取內頁 {url} 失敗: {e}")
        return 0, 0

# --- WebSocket & Background Task ---
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
        await asyncio.gather(*[connection.send_text(message) for connection in self.active_connections])

manager = ConnectionManager()

async def scrape_and_save_periodically():
    while SessionLocal is None:
        print("等待資料庫初始化...")
        await asyncio.sleep(5)

    while True:
        pni = await deep_scrape_pni()
        if pni is not None:
            db = SessionLocal()
            try:
                new_record = PniRecord(pni=pni)
                db.add(new_record)
                db.commit()
                print(f"PNI {pni:.2f}% 已成功存入資料庫。")
                message = json.dumps({"type": "pni_update", "timestamp": time.time(), "pni": pni})
                await manager.broadcast(message)
            except SQLAlchemyError as e:
                print(f"[錯誤] 寫入資料庫失敗: {e}")
                db.rollback()
            finally:
                db.close()
        await asyncio.sleep(180)

# --- API Endpoints & Startup Event ---
@app.on_event("startup")
async def startup_event():
    print("伺服器啟動中...")
    if initialize_database():
        print("正在啟動背景爬蟲任務...")
        asyncio.create_task(scrape_and_save_periodically())
        print("背景任務已啟動。")
    else:
        print("由於資料庫連線失敗，背景任務無法啟動。")

@app.get("/")
def read_root():
    return {"status": "PTT Scraper API is alive"}

@app.get("/api/history")
def get_history(timescale: str = "realtime"):
    if SessionLocal is None:
        return {"error": "Database not connected"}
    db = SessionLocal()
    try:
        if timescale == "realtime":
             start_time = datetime.utcnow() - timedelta(hours=1)
             records = db.query(PniRecord).filter(PniRecord.timestamp >= start_time).order_by(PniRecord.timestamp.desc()).limit(60).all()
             return [{"timestamp": r.timestamp.isoformat() + "Z", "pni": r.pni} for r in reversed(records)]
        elif timescale == "30m":
            start_time = datetime.utcnow() - timedelta(hours=24)
            interval = '30 minutes'
        elif timescale == "1h":
            start_time = datetime.utcnow() - timedelta(days=3)
            interval = '1 hour'
        else:
            return {"error": "Invalid timescale"}

        query = db.query(
            func.date_trunc(interval, PniRecord.timestamp).label('bucket'),
            func.avg(PniRecord.pni).label('avg_pni')
        ).filter(
            PniRecord.timestamp >= start_time
        ).group_by('bucket').order_by('bucket')
        
        results = query.all()
        return [{"timestamp": r.bucket.isoformat() + "Z", "pni": r.avg_pni} for r in results]
    except Exception as e:
        print(f"[錯誤] 查詢歷史數據時發生錯誤: {e}")
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
