document.addEventListener('DOMContentLoaded', () => {
    // 檢查所有必要的函式庫是否都已成功載入
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
    
    const chartConfig = {
        type: 'line',
        data: {
            datasets: [{
                label: '折扣率 (% OFF)',
                data: [],
                borderColor: 'rgba(52, 211, 153, 0.8)',
                backgroundColor: 'rgba(52, 211, 153, 0.2)',
                borderWidth: 2,
                pointRadius: 0,
                tension: 0,
                fill: true,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'minute',
                        tooltipFormat: 'HH:mm:ss',
                        displayFormats: { minute: 'HH:mm' }
                    },
                    display: true,
                    grid: { color: 'rgba(255, 255, 255, 0.1)' },
                    ticks: { color: 'rgba(255, 255, 255, 0.7)', maxRotation: 0, autoSkip: true, maxTicksLimit: 7 }
                },
                y: {
                    display: true,
                    grid: { color: 'rgba(255, 255, 255, 0.1)' },
                    ticks: {
                        color: 'rgba(255, 255, 255, 0.7)',
                        callback: function(value) {
                            return `${((100 - value) / 10).toFixed(1)}折`;
                        }
                    },
                    title: { display: true, text: '即時折扣', color: 'rgba(255, 255, 255, 0.9)' }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: true, mode: 'index', intersect: false,
                    callbacks: {
                        title: function(context) { return format(context[0].parsed.x, 'HH:mm:ss'); },
                        label: function(context) {
                            const discountOff = context.parsed.y;
                            const discountValue = (100 - discountOff) / 10;
                            return `折扣: ${discountValue.toFixed(1)} 折 (${discountOff.toFixed(2)}% OFF)`;
                        }
                    }
                }
            }
        }
    };

    function calculateDiscountFromPpi(ppi, settings) {
        const { base_discount = 5.0, ppi_threshold = 70.0, conversion_factor = 0.5, discount_cap = 25.0 } = settings;
        const extra_discount = Math.max(0, (ppi_threshold - ppi) * conversion_factor);
        const final_discount = Math.min(base_discount + extra_discount, discount_cap);
        return final_discount;
    }

    async function initializeChartWithHistory() {
        try {
            connectionStatusEl.textContent = "正在載入歷史數據...";
            if (!currentDiscountData) {
                const response = await fetch(`${API_BASE_URL}/api/current-discount`);
                if (!response.ok) throw new Error('無法獲取折扣設定來初始化圖表');
                currentDiscountData = await response.json();
                if (currentDiscountData.error) throw new Error(currentDiscountData.error);
            }

            const response = await fetch(`${API_BASE_URL}/api/history?timescale=realtime`);
            if (!response.ok) throw new Error('無法獲取歷史數據');
            const history = await response.json();
            if(history.error) throw new Error(history.error);

            const initialData = history.map(p => ({ 
                x: new Date(p.timestamp), 
                y: calculateDiscountFromPpi(p.ppi, currentDiscountData.settings) 
            }));
            sentimentChart.data.datasets[0].data = initialData;
            sentimentChart.update();
            console.log(`已成功載入 ${initialData.length} 筆歷史折扣數據。`);
        } catch (error) {
            console.error("初始化圖表歷史數據失敗:", error);
            connectionStatusEl.textContent = "載入歷史數據失敗。";
        }
    }

    // [UPDATE] 核心的數據獲取與動態輪詢函式
    async function pollingLoop() {
        try {
            const response = await fetch(`${API_BASE_URL}/api/current-discount`);
            if (!response.ok) throw new Error(`Network response was not ok (${response.status})`);
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            
            currentDiscountData = data;
            generateCodeBtn.disabled = false;
            updateUIDisplay(data);
            
            // [NEW] 使用後端提供的秒數來啟動倒數和排程下一次請求
            const secondsLeft = data.seconds_until_next_update;
            startCountdown(secondsLeft);
            
            // 加上 2 秒的緩衝，確保在下一分鐘開始後才發出請求
            const delay = (secondsLeft + 2) * 1000; 
            console.log(`下一次 API 請求將在 ${delay / 1000} 秒後發送。`);
            setTimeout(pollingLoop, delay);

            connectionStatusEl.textContent = `連線正常 | 上次更新：${new Date().toLocaleTimeString('zh-TW')}`;
            connectionStatusEl.classList.remove('text-yellow-400', 'text-red-500');
            connectionStatusEl.classList.add('text-green-400');

        } catch (error) {
            console.error('獲取折扣失敗:', error);
            connectionStatusEl.textContent = "獲取失敗，將於 15 秒後重試...";
            connectionStatusEl.classList.remove('text-green-400', 'text-yellow-400');
            connectionStatusEl.classList.add('text-red-500');
            discountDisplayEl.textContent = "N/A";
            generateCodeBtn.disabled = true;
            // 如果失敗，則在 15 秒後重試
            setTimeout(pollingLoop, 15000);
        }
    }

    function updateUIDisplay(data) {
        const { current_ppi, final_discount_percentage, settings } = data;
        const discountValue = (100 - final_discount_percentage) / 10;
        discountDisplayEl.textContent = `${discountValue.toFixed(1)} 折`;
        ppiDisplayEl.textContent = `${current_ppi.toFixed(2)} %`;
        formulaDisplayEl.textContent = `${settings.base_discount}% + (${settings.ppi_threshold}% - ${current_ppi.toFixed(1)}%) * ${settings.conversion_factor}`;
        
        const chartData = sentimentChart.data.datasets[0].data;
        chartData.push({ x: new Date(), y: final_discount_percentage });
        if (chartData.length > 60) chartData.shift();
        sentimentChart.update('quiet');
    }
    
    // [UPDATE] 倒數計時器現在由後端提供的秒數啟動
    function startCountdown(initialSeconds) {
        clearInterval(countdownInterval);
        let seconds = initialSeconds >= 0 ? initialSeconds : 59; // 處理邊界情況
        countdownTextEl.style.display = 'block';
        countdownTimerEl.textContent = seconds;

        countdownInterval = setInterval(() => {
            seconds--;
            countdownTimerEl.textContent = Math.max(0, seconds);
            if (seconds < 0) {
                clearInterval(countdownInterval);
                countdownTextEl.style.display = 'none';
            }
        }, 1000);
    }
    
    function showBarcode() {
        if (!currentDiscountData) return;
        codeModal.classList.remove('hidden');
        const discountCode = `MILK-${currentDiscountData.final_discount_percentage.toFixed(2)}-${Date.now()}`;
        JsBarcode("#barcode", discountCode, {
            format: "CODE128", lineColor: "#000", width: 2, height: 80, displayValue: true, fontSize: 18
        });
        let seconds = parseInt(countdownTimerEl.textContent) || 60;
        codeCountdownEl.textContent = seconds;
        const codeInterval = setInterval(() => {
            seconds--;
            codeCountdownEl.textContent = Math.max(0, seconds);
            if (seconds <= 0 || codeModal.classList.contains('hidden')) {
                clearInterval(codeInterval);
            }
        }, 1000);
    }

    async function initialize() {
        sentimentChart = new Chart(ctx, chartConfig);
        await initializeChartWithHistory();
        
        // [UPDATE] 啟動全新的動態輪詢機制，取代舊的 setInterval
        pollingLoop(); 

        generateCodeBtn.addEventListener('click', showBarcode);
        closeModalBtn.addEventListener('click', () => {
            codeModal.classList.add('hidden');
        });
    }

    initialize();
});
