document.addEventListener('DOMContentLoaded', () => {
    // 檢查函式庫是否已成功載入
    if (typeof Chart === 'undefined' || typeof JsBarcode === 'undefined' || typeof window.dateFns === 'undefined') {
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
    const generateCodeBtn = document.getElementById('generate-code-btn');
    const codeModal = document.getElementById('code-modal');
    const closeModalBtn = document.getElementById('close-modal-btn');
    const codeCountdownEl = document.getElementById('code-countdown');
    
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
            currentDiscountData = data;
            generateCodeBtn.disabled = false;
            updateUI(data);
            startCountdown();

        } catch (error) {
            console.error('獲取折扣失敗:', error);
            connectionStatusEl.textContent = "獲取折扣失敗，請稍後重試。";
            discountDisplayEl.textContent = "---";
            generateCodeBtn.disabled = true;
        }
    }

    function updateUI(data) {
        const { current_ppi, final_discount_percentage, settings } = data;
        const discountValue = (100 - final_discount_percentage) / 10;
        discountDisplayEl.textContent = `${discountValue.toFixed(1)} 折`;
        ppiDisplayEl.textContent = `${current_ppi.toFixed(2)} %`;
        const { base_discount, ppi_threshold, conversion_factor } = settings;
        formulaDisplayEl.textContent = `${base_discount}% + (${current_ppi.toFixed(1)}% - ${ppi_threshold}%) * ${conversion_factor}`;
        updateChart(current_ppi);
    }
    
    function updateChart(newPpi) {
        // ... (與之前版本相同) ...
    }

    function startCountdown() {
        // ... (與之前版本相同) ...
    }

    // [UPDATE] 產生並顯示 Barcode 的函式
    function showBarcode() {
        if (!currentDiscountData) return;

        codeModal.classList.remove('hidden');

        // 產生一個給 POS 系統讀取的條碼字串
        const discountCode = `MILK-${currentDiscountData.final_discount_percentage.toFixed(2)}-${Date.now()}`;
        
        JsBarcode("#barcode", discountCode, {
            format: "CODE128",
            lineColor: "#000",
            width: 2,
            height: 80,
            displayValue: true,
            fontSize: 18
        });

        // 開始 Barcode 倒數計時
        let seconds = 60;
        codeCountdownEl.textContent = seconds;
        const codeInterval = setInterval(() => {
            seconds--;
            codeCountdownEl.textContent = seconds;
            if (seconds <= 0 || codeModal.classList.contains('hidden')) {
                clearInterval(codeInterval);
            }
        }, 1000);
    }

    function initialize() {
        sentimentChart = new Chart(ctx, chartConfig);
        fetchDiscount();
        mainInterval = setInterval(fetchDiscount, 60000);

        // [UPDATE] 綁定按鈕事件
        generateCodeBtn.addEventListener('click', showBarcode);
        closeModalBtn.addEventListener('click', () => {
            codeModal.classList.add('hidden');
        });
    }

    initialize();
});
</script>
