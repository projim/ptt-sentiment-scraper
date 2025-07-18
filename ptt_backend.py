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
# [FIX] 還原完整的 CORS 中介層，這是解決 "blocked by CORS policy" 錯誤的關鍵
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
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
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
            page = await context.new_page()
            
            await page.goto(GOSSIPING_BOARD_URL, wait_until='domcontentloaded', timeout=60000)
            
            try:
                agree_button = page.locator('button:has-text("我同意，我已年滿十八歲")')
                await agree_button.wait_for(state='visible', timeout=5000)
                await agree_button.click()
                await page.wait_for_load_state('networkidle', timeout=60000)
            except Exception:
                pass

            content = await page.content()
            await page.close()
            soup = BeautifulSoup(content, "html.parser")
            
            articles = soup.select("div.r-ent")
            article_urls = [PTT_URL + a.select_one("div.title a")['href'] for a in articles if a.select_one("div.title a")]

            if not article_urls:
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
    page = await context.new_page()
    try:
        await page.goto(url, wait_until='networkidle', timeout=20000)
        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        await page.wait_for_timeout(500)

        article_soup = BeautifulSoup(await page.content(), 'html.parser')
        
        pushes = article_soup.select('div.push > span.push-tag', string=lambda text: '推' in text)
        boos = article_soup.select('div.push > span.push-tag', string=lambda text: '噓' in text)
        push_count, boo_count = len(pushes), len(boos)
        
        print(f"[成功] 已分析內頁: {url} - 推: {push_count}, 噓: {boo_count}")
        await page.close()
        return push_count, boo_count
    except Exception as e:
        print(f"[警告] 
