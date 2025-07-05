import asyncio
import httpx
from bs4 import BeautifulSoup
import json
import time
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, Float, DateTime, desc, String
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
        
        # 初始化預設折扣設定 (如果不存在)
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
PTT_URL = "https://www.ptt.cc"
GOSSIPING_BOARD_URL = f"{PTT_URL}/bbs/Gossiping/index.html"
cookies = {"over18": "1"}
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

async def deep_scrape_ppi():
    """非同步深度分析：進入每篇文章內頁，精準計算 PPI。"""
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
            ppi = (total_push / total_votes) * 100 if total_votes > 0 else 0
            
            print(f"--- 深度分析完成 ---")
            print(f"總推文: {total_push}, 總噓文: {total_boo}, PPI: {ppi:.2f}%")
            print(f"--------------------")
            
            return ppi
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

# --- Background Task ---
async def scrape_and_save_periodically():
    while SessionLocal is None:
        print("等待資料庫初始化...")
        await asyncio.sleep(5)

    while True:
        ppi = await deep_scrape_ppi()
        if ppi is not None:
            db = SessionLocal()
            try:
                new_record = SentimentRecord(ppi=ppi)
                db.add(new_record)
                db.commit()
                print(f"PPI {ppi:.2f}% 已成功存入資料庫。")
            except SQLAlchemyError as e:
                print(f"[錯誤] 寫入資料庫失敗: {e}")
                db.rollback()
            finally:
                db.close()
        
        await asyncio.sleep(180) # 每 3 分鐘執行一次深度爬取

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
    return {"status": "PTT Discount Engine API is alive"}

@app.get("/api/current-discount")
def get_current_discount():
    if SessionLocal is None:
        return {"error": "Database not connected", "discount": 0}
    
    db = SessionLocal()
    try:
        # 1. 讀取折扣設定
        settings_query = db.query(DiscountSetting).all()
        settings = {s.setting_name: s.setting_value for s in settings_query}
        
        base_discount = settings.get("base_discount", 5.0)
        ppi_threshold = settings.get("ppi_threshold", 60.0)
        conversion_factor = settings.get("conversion_factor", 0.25)
        discount_cap = settings.get("discount_cap", 25.0)

        # 2. 計算過去 15 分鐘的滾動平均 PPI
        start_time = datetime.utcnow() - timedelta(minutes=15)
        avg_ppi_query = db.query(func.avg(SentimentRecord.ppi)).filter(SentimentRecord.timestamp >= start_time).scalar()
        
        current_ppi = avg_ppi_query if avg_ppi_query is not None else 0

        # 3. 執行公式
        extra_discount = 0
        if current_ppi > ppi_threshold:
            extra_discount = (current_ppi - ppi_threshold) * conversion_factor
        
        final_discount = base_discount + extra_discount
        
        # 4. 套用上限
        final_discount = min(final_discount, discount_cap)

        return {
            "current_ppi": round(current_ppi, 2),
            "final_discount_percentage": round(final_discount, 2),
            "settings": settings
        }

    except Exception as e:
        print(f"[錯誤] 計算折扣時發生錯誤: {e}")
        return {"error": "Could not calculate discount", "discount": 0}
    finally:
        db.close()
