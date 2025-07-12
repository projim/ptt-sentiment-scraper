import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json
import time
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, Float, DateTime, desc, String, func
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
from pydantic import BaseModel
from fastapi.concurrency import run_in_threadpool

# --- Pydantic Models ---
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
    global engine, SessionLocal, db_ready
    # ... (資料庫初始化邏輯與之前版本相同) ...
    db_ready = True
    return True

# --- PTT Scraper using Playwright ---
PTT_URL = "https://www.ptt.cc"
GOSSIPING_BOARD_URL = f"{PTT_URL}/bbs/Gossiping/index.html"

async def deep_scrape_ppi():
    """使用 Playwright 進行深度分析，模擬真人瀏覽"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            print("[爬蟲] 正在前往 PTT 八卦版...")
            await page.goto(GOSSIPING_BOARD_URL)
            
            # 處理 "我已滿18歲" 的按鈕
            if await page.locator('button:has-text("我同意，我已年滿十八歲")').is_visible():
                print("[爬蟲] 偵測到年齡確認，正在點擊...")
                await page.locator('button:has-text("我同意，我已年滿十八歲")').click()
                await page.wait_for_load_state('networkidle')

            print("[爬蟲] 正在分析文章列表...")
            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")
            articles = soup.select("div.r-ent")
            article_urls = [PTT_URL + a.find('a')['href'] for a in articles if a.find('a') and 'M.' in a.find('a')['href']]

            if not article_urls:
                print("[警告] 在列表頁上沒有找到任何文章連結。")
                await browser.close()
                return 0.0

            total_push = 0
            total_boo = 0
            
            for url in article_urls[:10]: # 為降低負載，先只分析前10篇
                try:
                    await page.goto(url, wait_until='domcontentloaded')
                    article_soup = BeautifulSoup(await page.content(), 'html.parser')
                    pushes = article_soup.select('div.push > span.push-tag', string=lambda text: '推' in text)
                    boos = article_soup.select('div.push > span.push-tag', string=lambda text: '噓' in text)
                    total_push += len(pushes)
                    total_boo += len(boos)
                except Exception as e:
                    print(f"[警告] 爬取內頁 {url} 失敗: {e}")

            await browser.close()

            total_votes = total_push + total_boo
            ppi = (total_push / total_votes) * 100 if total_votes > 0 else 0
            
            print(f"--- 深度分析完成 --- PPI: {ppi:.2f}%")
            return ppi
    except Exception as e:
        print(f"[重大錯誤] Playwright 爬取時發生未知錯誤: {e}")
        return None

# --- Background Task ---
# ... (背景任務 scrape_and_save_periodically 邏輯與之前版本相同) ...

# --- API Endpoints & Startup Event ---
# ... (所有 API 端點與 startup 事件邏輯與之前版本相同) ...
