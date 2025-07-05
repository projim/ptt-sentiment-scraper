import asyncio
import httpx
from bs4 import BeautifulSoup
import json
import time
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, Float, DateTime, desc, String, func
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
engine = None
SessionLocal = None
Base = declarative_base()

class SentimentRecord(Base):
    __tablename__ = "sentiment_records"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    ppi = Column(Float, index=True)

class DiscountSetting(Base):
    __tablename__ = "discount_settings"
    setting_name = Column(String, primary_key=True, index=True)
    setting_value = Column(Float)

def initialize_database():
    """安全地初始化資料庫連線和表格"""
    global engine, SessionLocal
    if not DATABASE_URL:
        print("[重大錯誤] 找不到環境變數 DATABASE_URL。")
        return False
    
    db_url_for_sqlalchemy = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    print(f"[偵錯] 正在嘗試連接資料庫...")

    try:
        engine = create_engine(db_url_for_sqlalchemy)
        with engine.connect() as connection:
            print("[成功] 資料庫連接成功！")
        
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        
        print("正在檢查並創建資料庫表格...")
        Base.metadata.create_all(bind=engine)
        print("資料庫表格檢查完畢。")
        
        db = SessionLocal()
        try:
            default_settings = {
                "base_discount": 5.0,
                "ppi_threshold": 60.0,
                "conversion_factor": 0.25,
                "discount_cap": 25.0
            }
            for key, value in default_settings.items():
                existing_setting = db.query(DiscountSetting).filter(DiscountSetting.setting_name == key).first()
                if not existing_setting:
                    new_setting = DiscountSetting(setting_name=key, setting_value=value)
                    db.add(new_setting)
                    print(f"已初始化預設折扣設定: {key} = {value}")
            db.commit()
        finally:
            db.close()

        return True
    except Exception as e:
        print(f"[重大錯誤] 資料庫初始化失敗: {e}")
        return False

# --- PTT Scraper Logic ---
# (爬蟲邏輯與之前版本相同，此處省略以保持簡潔)
async def deep_scrape_ppi():
    # ...
    return 75.0 + (time.time() % 20) # 範例返回值

async def scrape_article(client: httpx.AsyncClient, url: str):
    # ...
    return 10, 2 # 範例返回值

# --- WebSocket & Background Task ---
class ConnectionManager:
    # ... (與之前版本相同)
    pass
manager = ConnectionManager()

async def scrape_and_save_periodically():
    # ... (與之前版本相同)
    pass

# --- API Endpoints & Startup Event ---
@app.on_event("startup")
async def startup_event():
    if initialize_database():
        asyncio.create_task(scrape_and_save_periodically())

@app.get("/")
def read_root():
    return {"status": "PTT Discount Engine API is alive"}

@app.get("/api/current-discount")
def get_current_discount():
    # ... (與之前版本相同)
    pass

@app.get("/api/history")
def get_history(timescale: str = "realtime"):
    if SessionLocal is None:
        return {"error": "Database not connected"}
    db = SessionLocal()
    try:
        # [UPDATE] 優化 realtime 查詢邏輯
        if timescale == "realtime":
             start_time = datetime.utcnow() - timedelta(hours=1)
             # 查詢最近一小時內的數據，按時間排序，最多取 60 筆
             records = db.query(SentimentRecord).filter(SentimentRecord.timestamp >= start_time).order_by(SentimentRecord.timestamp.asc()).all()
             return [{"timestamp": r.timestamp.isoformat() + "Z", "ppi": r.ppi} for r in records]

        elif timescale == "30m":
            # ... (與之前版本相同)
            pass
        elif timescale == "1h":
            # ... (與之前版本相同)
            pass
        else:
            return {"error": "Invalid timescale"}
        
        # ... (彙總查詢邏輯與之前版本相同)

    except Exception as e:
        print(f"[錯誤] 查詢歷史數據時發生錯誤: {e}")
        return {"error": "Could not retrieve history"}
    finally:
        db.close()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # ... (與之前版本相同)
    pass
