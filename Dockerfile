# [UPDATE] 將基礎映像檔升級到您指定的 v1.53.0 版本
FROM mcr.microsoft.com/playwright/python:v1.53.0-jammy

# 設定伺服器內部的工作目錄
WORKDIR /app

# 將我們的程式碼複製進去
COPY requirements.txt .
COPY ptt_backend.py .

# 安裝 Python 套件
RUN pip install --no-cache-dir -r requirements.txt

# 設定環境變數，讓 Uvicorn 在 Render 指定的端口上運行
# Render 會自動將外部的 80/443 端口對應到這個內部端口
ENV PORT 10000
EXPOSE 10000

# 設定容器啟動時要執行的指令
CMD ["uvicorn", "ptt_backend:app", "--host", "0.0.0.0", "--port", "10000"]
