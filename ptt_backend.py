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
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from fastapi.concurrency import run_in_threadpool
from playwright.async_api import async_playwright, Page, BrowserContext

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
    timestamp = Column(DateTime(timezone=True), nullable=False)
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
        engine = create_engine(db_url_for_sqlalchemy, pool_pre_ping=True, connect_args={"sslmode": "require"})
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
            context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
            page = await context.new_page()
            
            print("[爬蟲] 正在前往 PTT 八卦版...")
            await page.goto(GOSSIPING_BOARD_URL, wait_until='domcontentloaded', timeout=60000)
            
            try:
                agree_button = page.locator('button:has-text("我同意，我已年滿十八歲")')
                await agree_button.wait_for(state='visible', timeout=5000)
                print("[爬蟲] 偵測到年齡確認，正在點擊...")
                await agree_button.click()
                await page.wait_for_load_state('networkidle', timeout=60000)
            except Exception:
                print("[爬蟲] 未偵測到年齡確認按鈕或已超時，直接繼續。")

            content = await page.content()
            await page.close()
            soup = BeautifulSoup(content, "html.parser")
            
            articles = soup.select("div.r-ent")
            article_urls = [PTT_URL + a.select_one("div.title a")['href'] for a in articles if a.select_one("div.title a")]

            if not article_urls:
                print("[警告] 在列表頁上沒有找到任何文章連結。")
                await browser.close()
                return 0.0

            total_push, total_boo = 0, 0
            
            scrape_tasks = [scrape_article(context, url) for url in article_urls[:10]]
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

async def scrape_article(context: BrowserContext, url: str):
    """每個任務都使用自己的獨立分頁，並模擬滾動"""
    page = await context.new_page()
    try:
        await page.goto(url, wait_until='networkidle', timeout=20000)
        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        await page.wait_for_timeout(500)

        article_soup = BeautifulSoup(await page.content(), 'html.parser')
        
        push_count = 0
        boo_count = 0
        
        all_pushes = article_soup.select('div.push')
        for push_div in all_pushes:
            tag_span = push_div.select_one('span.push-tag')
            if tag_span and tag_span.string:
                tag_text = tag_span.string.strip()
                if tag_text == '推':
                    push_count += 1
                elif tag_text == '噓':
                    boo_count += 1
        
        print(f"[成功] 已分析內頁: {url} - 推: {push_count}, 噓: {boo_count}")
        await page.close()
        return push_count, boo_count
    except Exception as e:
        print(f"[警告] 爬取內頁 {url} 失敗: {e}")
        await page.close()
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
                    new_record = SentimentRecord(ppi=ppi, timestamp=datetime.now(timezone.utc))
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

        latest_record = db.query(SentimentRecord).order_by(SentimentRecord.id.desc()).first()
        
        ppi_for_calculation = 0.0
        if latest_record:
            ppi_for_calculation = latest_record.ppi
            if ppi_for_calculation == 0.0:
                fallback_record = db.query(SentimentRecord).filter(SentimentRecord.ppi > 0).order_by(SentimentRecord.id.desc()).first()
                if fallback_record:
                    ppi_for_calculation = fallback_record.ppi

        extra_discount = 0
        if ppi_for_calculation < ppi_threshold:
            extra_discount = (ppi_threshold - ppi_for_calculation) * conversion_factor
        
        final_discount = base_discount + extra_discount
        final_discount = min(final_discount, discount_cap)

        # [NEW] 計算並回傳有效期限
        valid_until_timestamp = time.time() + 60

        return {
            "current_ppi": round(ppi_for_calculation, 2),
            "final_discount_percentage": round(final_discount, 2),
            "settings": settings,
            "valid_until": valid_until_timestamp
        }
    finally:
        db.close()

# ... (其餘 API 端點與之前版本相同)
