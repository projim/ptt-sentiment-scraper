import asyncio
import httpx
from bs4 import BeautifulSoup
import json
import time
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, Float, DateTime, desc, String, func
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta

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
engine = None
SessionLocal = None
Base = declarative_base()

class SentimentRecord(Base):
    __tablename__ = "sentiment_records"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    ppi = Column(Float, index=True)

def initialize_database():
    global engine, SessionLocal
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
    try:
        async with httpx.AsyncClient(cookies=cookies, headers=headers, timeout=40) as client:
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
            print(f"--- 深度分析完成 --- PPI: {ppi:.2f}%")
            return ppi
    except Exception as e:
        print(f"[錯誤] 爬取列表頁失敗: {e}")
        return None

async def scrape_article(client: httpx.AsyncClient, url: str):
    try:
        await asyncio.sleep(0.25)
        article_res = await client.get(url, timeout=15)
        article_soup = BeautifulSoup(article_res.text, 'html.parser')
        pushes = article_soup.find_all('span', class_='push-tag', string=lambda text: '推' in text)
        boos = article_soup.find_all('span', class_='push-tag', string=lambda text: '噓' in text)
        return len(pushes), len(boos)
    except Exception as e:
        print(f"[警告] 爬取內頁 {url} 失敗: {e}")
        return 0, 0

# --- Background Task ---
async def scrape_and_save_periodically():
    # [FIX] 採用階梯式啟動，給予伺服器充分的穩定時間
    print("背景任務已排程，將在 15 秒後開始第一次爬取...")
    await asyncio.sleep(15)

    while True:
        try: # [FIX] 加入最強大的錯誤保護層，確保爬蟲不會弄垮整個伺服器
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
    # [FIX] 延遲資料庫初始化和背景任務的啟動
    await asyncio.sleep(5) 
    if initialize_database():
        print("正在排程背景爬蟲任務...")
        asyncio.create_task(scrape_and_save_periodically())
    print("伺服器已準備就緒，可以接受連線。")

@app.get("/")
def read_root():
    return {"status": "PTT Scraper API is alive"}

@app.get("/api/latest-data")
def get_latest_data():
    if SessionLocal is None:
        return {"error": "Database not connected"}
    db = SessionLocal()
    try:
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        history_records = db.query(SentimentRecord).filter(SentimentRecord.timestamp >= one_hour_ago).order_by(SentimentRecord.timestamp.asc()).all()
        history_data = [{"timestamp": r.timestamp.isoformat() + "Z", "ppi": r.ppi} for r in history_records]
        
        latest_record = db.query(SentimentRecord).order_by(SentimentRecord.timestamp.desc()).first()
        latest_ppi = latest_record.ppi if latest_record else 0

        return {
            "latest_ppi": round(latest_ppi, 2),
            "history": history_data
        }
    except Exception as e:
        print(f"[錯誤] 獲取最新數據時發生錯誤: {e}")
        return {"error": "Could not retrieve data"}
    finally:
        db.close()
