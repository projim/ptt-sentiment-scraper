document.addEventListener('DOMContentLoaded', () => {
    // 檢查函式庫是否已成功載入
    if (typeof Chart === 'undefined' || typeof QRCode === 'undefined' || typeof window.dateFns === 'undefined') {
        console.error("Fatal Error: A required library failed to load.");
        document.getElementById('connection-status').innerHTML = "關鍵函式庫載入失敗，請檢查 libs 資料夾或網路連線並刷新頁面。";
        return;
    }
    
    const { format } = window.dateFns;

    // DOM 元素
    const connectionStatusEl = document.getElementById('connection-status');
    const discountDisplayEl = document.getElementById('discount-display');
    const countdownTimerEl = document.getElementById('countdown-timer');
    const ppiDisplayEl = document.getElementById('ppi-display');
    const formulaDisplayEl = document.getElementById('formula-display');
    const ctx = document.getElementById('sentimentChart').getContext('2d');
    const generateQrBtn = document.getElementById('generate-qr-btn');
    const qrModal = document.getElementById('qr-modal');
    const closeModalBtn = document.getElementById('close-modal-btn');
    const qrcodeContainer = document.getElementById('qrcode-container');
    const qrCountdownEl = document.getElementById('qr-countdown');
    
    // 應用程式狀態
    let sentimentChart;
    let mainInterval;
    let countdownInterval;
    let currentDiscountData = null; // 儲存最新的折扣數據

    const serviceName = "ptt-gossiping-live"; // 請務必換成您在 Render 上設定的服務名稱
    const API_BASE_URL = `https://${serviceName}.onrender.com`;
    
    const chartConfig = { /* ... (與之前版本相同) ... */ };

    async function fetchDiscount() {
        try {
            connectionStatusEl.textContent = "正在獲取最新折扣...";
            const response = await fetch(`${API_BASE_URL}/api/current-discount`);
            if (!response.ok) throw new Error(`Network response was not ok (${response.status})`);
            const data = await response.json();

            if (data.error) throw new Error(data.error);
            
            connectionStatusEl.textContent = `上次更新：${new Date().toLocaleTimeString('zh-TW')}`;
            currentDiscountData = data; // [NEW] 儲存最新數據
            generateQrBtn.disabled = false; // [NEW] 啟用按鈕
            updateUI(data);
            startCountdown();

        } catch (error) {
            console.error('獲取折扣失敗:', error);
            connectionStatusEl.textContent = "獲取折扣失敗，請稍後重試。";
            discountDisplayEl.textContent = "---";
            generateQrBtn.disabled = true;
        }
    }

    function updateUI(data) {
        // ... (與之前版本相同) ...
    }
    
    function updateChart(newPpi) {
        // ... (與之前版本相同) ...
    }

    function startCountdown() {
        clearInterval(countdownInterval);
        let seconds = 60;
        countdownTimerEl.parentElement.style.display = 'block';

        countdownInterval = setInterval(() => {
            seconds--;
            countdownTimerEl.textContent = `${seconds}`;
            if (seconds <= 0) {
                clearInterval(countdownInterval);
                 countdownTimerEl.parentElement.style.display = 'none';
            }
        }, 1000);
    }

    // [NEW] 產生並顯示 QR Code 的函式
    function showQRCode() {
        if (!currentDiscountData) return;

        qrModal.classList.remove('hidden');
        qrcodeContainer.innerHTML = ''; // 清空舊的 QR Code

        const qrData = {
            discount: currentDiscountData.final_discount_percentage,
            ppi: currentDiscountData.current_ppi,
            timestamp: new Date().toISOString()
        };

        new QRCode(qrcodeContainer, {
            text: JSON.stringify(qrData),
            width: 200,
            height: 200,
            colorDark : "#000000",
            colorLight : "#ffffff",
            correctLevel : QRCode.CorrectLevel.H
        });

        // 開始 QR Code 倒數計時
        let seconds = 60;
        const qrInterval = setInterval(() => {
            seconds--;
            qrCountdownEl.textContent = seconds;
            if (seconds <= 0 || qrModal.classList.contains('hidden')) {
                clearInterval(qrInterval);
            }
        }, 1000);
    }

    function initialize() {
        sentimentChart = new Chart(ctx, chartConfig);
        
        fetchDiscount();
        mainInterval = setInterval(fetchDiscount, 60000);

        // [NEW] 綁定按鈕事件
        generateQrBtn.addEventListener('click', showQRCode);
        closeModalBtn.addEventListener('click', () => {
            qrModal.classList.add('hidden');
        });
    }

    initialize();
});
