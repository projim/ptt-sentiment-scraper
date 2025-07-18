document.addEventListener('DOMContentLoaded', () => {
    // 檢查函式庫
    if (typeof Chart === 'undefined' || typeof JsBarcode === 'undefined' || typeof window.dateFns === 'undefined') {
        console.error("Fatal Error: A required library failed to load.");
        document.getElementById('connection-status').innerHTML = "關鍵函式庫載入失敗，請檢查 libs 資料夾或網路連線並刷新頁面。";
        return;
    }
    
    const { format } = window.dateFns;

    // DOM 元素
    const connectionStatusEl = document.getElementById('connection-status');
    const discountDisplayEl = document.getElementById('discount-display');
    const countdownTextEl = document.getElementById('countdown-text');
    const countdownTimerEl = document.getElementById('countdown-timer');
    const ppiDisplayEl = document.getElementById('ppi-display');
    const formulaDisplayEl = document.getElementById('formula-display');
    const ctx = document.getElementById('sentimentChart').getContext('2d');
    const generateCodeBtn = document.getElementById('generate-code-btn');
    const codeModal = document.getElementById('code-modal');
    const closeModalBtn = document.getElementById('close-modal-btn');
    const codeCountdownEl = document.getElementById('code-countdown');
    
    // 應用程式狀態
    let sentimentChart;
    let countdownInterval;
    let currentDiscountData = null;

    const serviceName = "ptt-gossiping-live"; // 請務必換成您在 Railway 上的真實服務名稱
    const API_BASE_URL = `https://${serviceName}.up.railway.app`;
    
    const chartConfig = { /* ... (與之前版本相同) ... */ };

    // [UPDATE] 全新的折扣獲取與倒數計時邏輯
    async function fetchDiscountAndUpdate() {
        try {
            connectionStatusEl.textContent = "正在獲取最新折扣...";
            const response = await fetch(`${API_BASE_URL}/api/current-discount`);
            if (!response.ok) throw new Error(`Network response was not ok (${response.status})`);
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            
            currentDiscountData = data;
            generateCodeBtn.disabled = false;
            updateUIDisplay(data);
            startCountdown(data.valid_until); // 使用伺服器提供的時間戳記

        } catch (error) {
            console.error('獲取折扣失敗:', error);
            connectionStatusEl.textContent = "獲取失敗，10秒後重試...";
            discountDisplayEl.textContent = "N/A";
            generateCodeBtn.disabled = true;
            // 如果失敗，10秒後重試
            setTimeout(fetchDiscountAndUpdate, 10000);
        }
    }

    function updateUIDisplay(data) {
        const { current_ppi, final_discount_percentage, settings } = data;
        const discountValue = (100 - final_discount_percentage) / 10;
        discountDisplayEl.textContent = `${discountValue.toFixed(1)} 折`;
        ppiDisplayEl.textContent = `${current_ppi.toFixed(2)} %`;
        formulaDisplayEl.textContent = `${settings.base_discount}% + (${settings.ppi_threshold}% - ${current_ppi.toFixed(1)}%) * ${settings.conversion_factor}`;
    }
    
    // [UPDATE] 倒數計時器現在由伺服器時間驅動
    function startCountdown(validUntilTimestamp) {
        clearInterval(countdownInterval);
        countdownTextEl.style.display = 'block';

        countdownInterval = setInterval(() => {
            const now = Math.floor(Date.now() / 1000);
            const secondsRemaining = Math.max(0, Math.floor(validUntilTimestamp - now));
            
            countdownTimerEl.textContent = secondsRemaining;

            if (secondsRemaining <= 0) {
                clearInterval(countdownInterval);
                countdownTextEl.style.display = 'none';
                fetchDiscountAndUpdate(); // 當倒數結束時，立即獲取下一個折扣
            }
        }, 1000);
    }
    
    function showBarcode() {
        if (!currentDiscountData) return;
        codeModal.classList.remove('hidden');
        
        // [UPDATE] Barcode 現在也包含有效期限
        const qrData = {
            discount: currentDiscountData.final_discount_percentage,
            valid_until: new Date(currentDiscountData.valid_until * 1000).toISOString()
        };
        const discountCode = `MILK-${qrData.discount.toFixed(2)}-${Date.now()}`;
        
        JsBarcode("#barcode", discountCode, {
            format: "CODE128", lineColor: "#000", width: 2, height: 80, displayValue: true, fontSize: 18
        });
        // ... (其餘 Barcode 倒數邏輯不變)
    }

    async function initialize() {
        sentimentChart = new Chart(ctx, chartConfig);
        // ... (其餘初始化邏輯與之前版本相同)
        fetchDiscountAndUpdate(); // 啟動整個流程
        generateCodeBtn.addEventListener('click', showBarcode);
        closeModalBtn.addEventListener('click', () => { codeModal.classList.add('hidden'); });
    }

    initialize();
});
