import asyncio
import httpx
from bs4 import BeautifulSoup
import json
import time
import os
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, Float, DateTime, desc, String, func
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
from pydantic import BaseModel
from fastapi.concurrency import run_in_threadpool

# --- Pydantic Models for Data Validation ---
class SettingsUpdate(BaseModel):
    base_discount: float
    ppi_threshold: float
    conversion_factor: float
    secret_key: str

# --- FastAPI App & CORS ---
app = FastAPI()
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Database Setup ---
DATABASE_URL = os.environ.get('DATABASE_URL')
ADMIN_SECRET_KEY = os.environ.get('ADMIN_SECRET_KEY', 'default_secret_key')
engine = None
SessionLocal = None
Base = declarative_base()
db_ready = False

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
    """安全地初始化資料庫連線和表格 (這是一個同步函式)"""
    global engine, SessionLocal, db_ready
    if not DATABASE_URL:
        print("[重大錯誤] 找不到環境變數 DATABASE_URL。")
        return False
    
    db_url_for_sqlalchemy = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    try:
        engine = create_engine(db_url_for_sqlalchemy, pool_pre_ping=True)
        with engine.connect() as connection:
            print("[成功] 資料庫連接成功！")
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine)
        print("資料庫表格檢查完畢。")

        db = SessionLocal()
        try:
            default_settings = {
                "base_discount": 5.0, 
                "ppi_threshold": 70.0,
                "conversion_factor": 0.5,
                "discount_cap": 25.0
            }
            for key, value in default_settings.items():
                if not db.query(DiscountSetting).filter(DiscountSetting.setting_name == key).first():
                    db.add(DiscountSetting(setting_name=key, setting_value=value))
            db.commit()
            print("預設折扣設定已確認。")
        finally:
            db.close()
        
        db_ready = True
        return True
    except Exception as e:
        print(f"[重大錯誤] 資料庫初始化失敗: {e}")
        db_ready = False
        return False

# --- PTT Scraper Logic ---
PTT_URL = "https://ptt-discussion.tw"
GOSSIPING_BOARD_URL = f"{PTT_URL}/bbs/Gossiping/index.html"
cookies = {"over18": "1"}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
]

async def deep_scrape_ppi():
    """非同步深度分析：進入每篇文章內頁，精準計算 PPI。"""
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(cookies=cookies, headers=headers, timeout=40) as client:
                print(f"[偵錯] 正在使用 User-Agent: {headers['User-Agent']}")
                response = await client.get(GOSSIPING_BOARD_URL)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, "html.parser")
                # [FIX] 更新了文章列表的 CSS 選擇器以匹配新網站
                articles = soup.select("a.list-post-item")
                
                article_urls = []
                for article_link in articles:
                    if article_link.has_attr('href'):
                        article_urls.append(PTT_URL + article_link['href'])

                if not article_urls:
                    print("[警告] 在列表頁上沒有找到任何文章連結。")
                    return 0.0

                scrape_tasks = [scrape_article(client, url) for url in article_urls]
                results = await asyncio.gather(*scrape_tasks)
                
                total_push = sum(r[0] for r in results)
                total_boo = sum(r[1] for r in results)
                total_votes = total_push + total_boo
                ppi = (total_push / total_votes) * 100 if total_votes > 0 else 0
                
                print(f"--- 深度分析完成 (第 {attempt + 1} 次嘗試) --- PPI: {ppi:.2f}%")
                return ppi
        except httpx.HTTPStatusError as e:
            print(f"[錯誤] HTTP 狀態錯誤: {e.response.status_code} - {e}")
            if attempt < max_retries - 1: await asyncio.sleep(5)
            else: return None
        except Exception as e:
            print(f"[錯誤] 爬取列表頁時發生未知錯誤: {e}")
            return None
    return None

async def scrape_article(client: httpx.AsyncClient, url: str):
    try:
        await asyncio.sleep(0.3)
        article_res = await client.get(url, timeout=20)
        article_res.raise_for_status()
        article_soup = BeautifulSoup(article_res.text, 'html.parser')
        # [FIX] 更新了留言的 CSS 選擇器
        pushes = article_soup.select('div.push > span.push-tag', string=lambda text: '推' in text)
        boos = article_soup.select('div.push > span.push-tag', string=lambda text: '噓' in text)
        return len(pushes), len(boos)
    except Exception as e:
        print(f"[警告] 爬取內頁 {url} 失敗: {e}")
        return 0, 0

# --- Background Task ---
async def scrape_and_save_periodically():
    print("背景任務啟動，正在初始化資料庫...")
    initialized = await run_in_threadpool(initialize_database)

    if not initialized:
        print("[背景任務終止] 因資料庫初始化失敗，背景任務無法繼續。")
        return

    print("背景任務：資料庫已就緒。將在 15 秒後開始第一次爬取...")
    await asyncio.sleep(15)

    while True:
        try:
            ppi = await deep_scrape_ppi()
            if ppi is not None and SessionLocal:
                db = SessionLocal()
                try:
                    new_record = SentimentRecord(ppi=ppi)
                    db.add(new_record)
                    db.commit()
                    print(f"PPI {ppi:.2f}% 已成功存入資料庫。")
                    # WebSocket廣播已移除，以簡化並專注於API
                finally:
                    db.close()
        except Exception as e:
            print(f"[重大錯誤] 背景爬蟲任務主迴圈發生未知錯誤: {e}")
        
        print(f"下一次爬取將在 3 分鐘後進行...")
        await asyncio.sleep(180)

# --- API Endpoints & Startup Event ---
@app.on_event("startup")
async def startup_event():
    print("伺服器啟動中...")
    print("正在排程背景初始化與爬蟲任務...")
    asyncio.create_task(scrape_and_save_periodically())
    print("伺服器已啟動，背景任務將在後台進行初始化。")

@app.get("/")
def read_root():
    return {"status": "PTT Discount Engine API is alive"}

@app.get("/api/current-discount")
def get_current_discount():
    if not db_ready or SessionLocal is None:
        raise HTTPException(status_code=503, detail="服務正在初始化，請稍後再試。")
    
    db = SessionLocal()
    try:
        settings_query = db.query(DiscountSetting).all()
        settings = {s.setting_name: s.setting_value for s in settings_query}
        
        base_discount = settings.get("base_discount", 5.0)
        ppi_threshold = settings.get("ppi_threshold", 70.0)
        conversion_factor = settings.get("conversion_factor", 0.5)
        discount_cap = settings.get("discount_cap", 25.0)

        start_time = datetime.utcnow() - timedelta(minutes=15)
        avg_ppi_query = db.query(func.avg(SentimentRecord.ppi)).filter(SentimentRecord.timestamp >= start_time).scalar()
        
        current_ppi = avg_ppi_query if avg_ppi_query is not None else 0.0

        if current_ppi == 0.0:
            last_valid_ppi_record = db.query(SentimentRecord.ppi).filter(SentimentRecord.ppi > 0).order_by(SentimentRecord.timestamp.desc()).first()
            if last_valid_ppi_record:
                current_ppi = last_valid_ppi_record[0]

        extra_discount = 0
        if current_ppi < ppi_threshold:
            extra_discount = (ppi_threshold - current_ppi) * conversion_factor
        
        final_discount = base_discount + extra_discount
        final_discount = min(final_discount, discount_cap)

        return {
            "current_ppi": round(current_ppi, 2),
            "final_discount_percentage": round(final_discount, 2),
            "settings": settings
        }
    except Exception as e:
        print(f"[錯誤] 計算折扣時發生錯誤: {e}")
        raise HTTPException(status_code=500, detail="計算折扣時發生內部錯誤")
    finally:
        db.close()
