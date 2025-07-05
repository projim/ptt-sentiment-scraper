document.addEventListener('DOMContentLoaded', () => {
    // 檢查函式庫
    if (typeof Chart === 'undefined' || typeof window.dateFns === 'undefined' || typeof JsBarcode === 'undefined') {
        console.error("Fatal Error: A required library failed to load.");
        document.getElementById('connection-status').innerHTML = "關鍵函式庫載入失敗，請刷新頁面重試。";
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
    let mainInterval;
    let countdownInterval;
    let currentDiscountData = null;
    let ppiHistoryForChart = [];

    const serviceName = "ptt-gossiping-live"; // 請務必換成您在 Render 上設定的服務名稱
    const API_BASE_URL = `https://${serviceName}.onrender.com`;
    
    // [FIX] 還原完整的圖表設定
    const chartConfig = {
        type: 'line',
        data: {
            datasets: [{
                label: 'PPI 指數',
                data: [],
                borderColor: 'rgba(52, 211, 153, 0.8)',
                backgroundColor: 'rgba(52, 211, 153, 0.2)',
                borderWidth: 2,
                pointRadius: 0,
                tension: 0.4,
                fill: true,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { 
                    type: 'time',
                    time: { unit: 'minute', tooltipFormat: 'HH:mm', displayFormats: { minute: 'HH:mm' } },
                    display: false 
                },
                y: { display: false }
            },
            plugins: {
                legend: { display: false },
                tooltip: { enabled: false }
            }
        }
    };

    async function fetchDiscount() {
        try {
            connectionStatusEl.textContent = "正在獲取最新折扣...";
            const response = await fetch(`${API_BASE_URL}/api/current-discount`);
            if (!response.ok) {
                throw new Error(`Network response was not ok (${response.status})`);
            }
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }
            
            connectionStatusEl.textContent = `上次更新：${new Date().toLocaleTimeString('zh-TW')}`;
            currentDiscountData = data;
            generateCodeBtn.disabled = false;
            updateUI(data);
            startCountdown();

        } catch (error) {
            console.error('獲取折扣失敗:', error);
            connectionStatusEl.textContent = "獲取失敗，將於下一分鐘重試...";
            discountDisplayEl.textContent = "N/A";
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

        // 更新圖表數據
        ppiHistoryForChart.push({ x: new Date(), y: current_ppi });
        if (ppiHistoryForChart.length > 60) {
            ppiHistoryForChart.shift();
        }
        updateChartDisplay(ppiHistoryForChart);
    }
    
    function updateChartDisplay(data) {
        if (!sentimentChart || !sentimentChart.data || !sentimentChart.data.datasets) return;
        
        sentimentChart.data.datasets[0].data = data;
        sentimentChart.update('quiet');
    }

    function startCountdown() {
        clearInterval(countdownInterval);
        let seconds = 60;
        countdownTextEl.style.display = 'block';
        countdownTimerEl.textContent = seconds;

        countdownInterval = setInterval(() => {
            seconds--;
            countdownTimerEl.textContent = seconds;
            if (seconds <= 0) {
                clearInterval(countdownInterval);
                countdownTextEl.style.display = 'none';
            }
        }, 1000);
    }
    
    // [FIX] 還原完整的 Barcode 顯示邏輯
    function showBarcode() {
        if (!currentDiscountData) return;

        codeModal.classList.remove('hidden');

        const discountCode = `MILK-${currentDiscountData.final_discount_percentage.toFixed(2)}-${Date.now()}`;
        
        JsBarcode("#barcode", discountCode, {
            format: "CODE128",
            lineColor: "#000",
            width: 2,
            height: 80,
            displayValue: true,
            fontSize: 18
        });

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
        updateChartDisplay([]);

        fetchDiscount();
        mainInterval = setInterval(fetchDiscount, 60000);

        generateCodeBtn.addEventListener('click', showBarcode);
        closeModalBtn.addEventListener('click', () => {
            codeModal.classList.add('hidden');
        });
    }

    initialize();
});
