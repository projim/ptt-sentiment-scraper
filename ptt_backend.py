import asyncio
import httpx
from bs4 import BeautifulSoup
import json
import time
import os
import random
from fastapi import FastAPI, Request, HTTPException, status
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
        # [FIX] 加入 connect_args={"sslmode": "require"} 來強制使用 SSL 連線
        engine = create_engine(
            db_url_for_sqlalchemy, 
            connect_args={"sslmode": "require"}, 
            pool_pre_ping=True
        )
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

# --- PTT Scraper using Playwright ---
PTT_URL = "https://www.ptt.cc"
GOSSIPING_BOARD_URL = f"{PTT_URL}/bbs/Gossiping/index.html"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
]

async def deep_scrape_ppi():
    """使用 Playwright 進行深度分析，模擬真人瀏覽"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=random.choice(USER_AGENTS))
            
            print("[爬蟲] 正在前往 PTT 八卦版...")
            await page.goto(GOSSIPING_BOARD_URL, wait_until='domcontentloaded', timeout=60000)
            
            try:
                agree_button = page.locator('button:has-text("我同意，我已年滿十八歲")')
                await agree_button.wait_for(timeout=5000)
                print("[爬蟲] 偵測到年齡確認，正在點擊...")
                await agree_button.click()
                await page.wait_for_load_state('networkidle', timeout=60000)
            except Exception:
                print("[爬蟲] 未偵測到年齡確認按鈕，直接繼續。")

            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")
            
            articles = soup.select("div.r-ent")
            article_urls = [PTT_URL + a.select_one("div.title a")['href'] for a in articles if a.select_one("div.title a")]

            if not article_urls:
                print("[警告] 在列表頁上沒有找到任何文章連結。")
                await browser.close()
                return 0.0

            total_push, total_boo = 0, 0
            
            scrape_tasks = [scrape_article(page, url) for url in article_urls[:10]]
            results = await asyncio.gather(*scrape_tasks)
            
            for push, boo in results:
                total_push += push
                total_boo += boo

            await browser.close()

            total_votes = total_push + total_boo
            ppi = (total_push / total_votes) * 100 if total_votes > 0 else 0
            
            print(f"--- 深度分析完成 --- PPI: {ppi:.2f}%")
            return ppi
    except Exception as e:
        print(f"[重大錯誤] Playwright 爬取時發生未知錯誤: {e}")
        return None

async def scrape_article(page, url: str):
    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=20000)
        article_soup = BeautifulSoup(await page.content(), 'html.parser')
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
        
        ppi_for_calculation = avg_ppi_query if avg_ppi_query is not None else 0.0

        if ppi_for_calculation == 0.0:
            last_valid_ppi_record = db.query(SentimentRecord.ppi).filter(SentimentRecord.ppi > 0).order_by(SentimentRecord.timestamp.desc()).first()
            if last_valid_ppi_record:
                ppi_for_calculation = last_valid_ppi_record[0]

        extra_discount = 0
        if ppi_for_calculation < ppi_threshold:
            extra_discount = (ppi_threshold - ppi_for_calculation) * conversion_factor
        
        final_discount = base_discount + extra_discount
        final_discount = min(final_discount, discount_cap)

        return {
            "current_ppi": round(ppi_for_calculation, 2),
            "final_discount_percentage": round(final_discount, 2),
            "settings": settings
        }
    finally:
        db.close()

@app.get("/api/history")
def get_history(timescale: str = "realtime"):
    if not db_ready or SessionLocal is None:
        raise HTTPException(status_code=503, detail="服務正在初始化，請稍後再試。")
    
    db = SessionLocal()
    try:
        if timescale == "realtime":
             start_time = datetime.utcnow() - timedelta(hours=1)
             records = db.query(SentimentRecord).filter(SentimentRecord.timestamp >= start_time).order_by(SentimentRecord.timestamp.asc()).all()
             return [{"timestamp": r.timestamp.isoformat() + "Z", "ppi": r.ppi} for r in records]
        
        interval_map = {"30m": '30 minutes', "1h": '1 hour'}
        if timescale not in interval_map: return {"error": "Invalid timescale"}
        
        start_time_map = {"30m": datetime.utcnow() - timedelta(hours=24), "1h": datetime.utcnow() - timedelta(days=3)}
        start_time = start_time_map[timescale]
        interval = interval_map[timescale]

        query = db.query(
            func.date_trunc(interval, SentimentRecord.timestamp).label('bucket'),
            func.avg(SentimentRecord.ppi).label('avg_pni')
        ).filter(SentimentRecord.timestamp >= start_time).group_by('bucket').order_by('bucket')
        
        return [{"timestamp": r.bucket.isoformat() + "Z", "ppi": r.avg_pni} for r in query.all()]
    finally:
        db.close()

@app.post("/api/update-settings")
def update_settings(payload: SettingsUpdate):
    if not db_ready or SessionLocal is None:
        raise HTTPException(status_code=503, detail="服務正在初始化，請稍後再試。")
    
    if payload.secret_key != ADMIN_SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="無效的管理員密碼")
    
    db = SessionLocal()
    try:
        settings_to_update = {
            "base_discount": payload.base_discount,
            "ppi_threshold": payload.ppi_threshold,
            "conversion_factor": payload.conversion_factor,
        }
        for key, value in settings_to_update.items():
            db.query(DiscountSetting).filter(DiscountSetting.setting_name == key).update({"setting_value": value})
        db.commit()
        return {"message": "折扣設定已成功更新！"}
    finally:
        db.close()

@app.get("/api/get-settings")
def get_settings():
    if not db_ready or SessionLocal is None:
        raise HTTPException(status_code=503, detail="服務正在初始化，請稍後再試。")
    
    db = SessionLocal()
    try:
        settings_query = db.query(DiscountSetting).all()
        return {s.setting_name: s.setting_value for s in settings_query}
    finally:
        db.close()
