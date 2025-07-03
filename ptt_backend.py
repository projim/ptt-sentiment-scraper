import asyncio
import httpx
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
# [DEBUG] 從環境變數讀取資料庫 URL
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
    
    # Render 的 URL 是 postgres://，但 SQLAlchemy 需要 postgresql://
    db_url_for_sqlalchemy = DATABASE_URL
    if DATABASE_URL.startswith("postgres://"):
        db_url_for_sqlalchemy = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    print(f"[偵錯] 正在嘗試使用以下 URL 連接資料庫: {db_url_for_sqlalchemy[:20]}...") # 只顯示部分 URL 以策安全

    try:
        engine = create_engine(db_url_for_sqlalchemy)
        # 嘗試建立連線
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
# ... (爬蟲邏輯與之前版本相同，此處省略以保持簡潔) ...
async def deep_scrape_pni():
    # ...
    return 15.0 # 範例返回值

# --- WebSocket & Background Task ---
# ... (WebSocket 邏輯與之前版本相同，此處省略) ...
class ConnectionManager:
    # ...
    pass
manager = ConnectionManager()

async def scrape_and_save_periodically():
    # 等待資料庫成功初始化
    while SessionLocal is None:
        print("等待資料庫初始化...")
        await asyncio.sleep(5)

    while True:
        pni = await deep_scrape_pni()
        
        if pni is not None:
            db = SessionLocal()
            # ... (寫入資料庫邏輯與之前版本相同) ...
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
def get_history(timescale: str = "30m"):
    if SessionLocal is None:
        return {"error": "Database not connected"}
    db = SessionLocal()
    try:
        # ... (查詢邏輯與之前版本相同) ...
        return []
    finally:
        db.close()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # ... (WebSocket 端點邏輯與之前版本相同) ...
    pass
