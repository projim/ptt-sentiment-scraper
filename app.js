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

    const serviceName = "ptt-gossiping-live"; // 請務必換成您在 Render 上設定的服務名稱
    const API_BASE_URL = `https://${serviceName}.onrender.com`;
    const WEBSOCKET_URL = `wss://${serviceName}.onrender.com/ws`;
    
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

    function connectWebSocket() {
        const ws = new WebSocket(WEBSOCKET_URL);

        ws.onopen = () => {
            connectionStatusEl.textContent = "已連接，等待即時更新...";
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'ppi_update' && sentimentChart) {
                const newPoint = { x: new Date(data.timestamp * 1000), y: data.ppi };
                const chartData = sentimentChart.data.datasets[0].data;
                
                chartData.push(newPoint);
                if (chartData.length > 60) { // 始終保持最多 60 個數據點
                    chartData.shift();
                }
                sentimentChart.update('quiet');
            }
        };

        ws.onclose = () => {
            console.log("WebSocket 連接已斷開，5秒後重連...");
            connectionStatusEl.textContent = "已斷線，嘗試重新連接...";
            // 這裡可以加入重連邏輯
            setTimeout(connectWebSocket, 5000);
        };

        ws.onerror = (error) => {
            console.error("WebSocket 發生錯誤:", error);
            connectionStatusEl.textContent = "WebSocket 連線錯誤。";
        };
    }

    async function fetchDiscount() {
        try {
            const response = await fetch(`${API_BASE_URL}/api/current-discount`);
            if (!response.ok) throw new Error(`Network response was not ok (${response.status})`);
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            
            currentDiscountData = data;
            generateCodeBtn.disabled = false;
            updateUIDisplay(data);
            startCountdown();

        } catch (error) {
            console.error('獲取折扣失敗:', error);
            connectionStatusEl.textContent = "獲取折扣失敗，將於下一分鐘重試...";
            discountDisplayEl.textContent = "N/A";
            generateCodeBtn.disabled = true;
        }
    }

    function updateUIDisplay(data) {
        const { current_ppi, final_discount_percentage, settings } = data;
        const discountValue = (100 - final_discount_percentage) / 10;
        discountDisplayEl.textContent = `${discountValue.toFixed(1)} 折`;
        ppiDisplayEl.textContent = `${current_ppi.toFixed(2)} %`;
        const { base_discount, ppi_threshold, conversion_factor } = settings;
        formulaDisplayEl.textContent = `${base_discount}% + (${current_ppi.toFixed(1)}% - ${ppi_threshold}%) * ${conversion_factor}`;
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

    // [UPDATE] 新的、更穩健的啟動流程
    async function initialize() {
        connectionStatusEl.textContent = "正在載入歷史數據...";
        
        // 1. 初始化一個空的圖表
        sentimentChart = new Chart(ctx, chartConfig);

        // 2. 透過 API 獲取並填滿歷史數據
        try {
            const response = await fetch(`${API_BASE_URL}/api/history?timescale=realtime`);
            if (!response.ok) throw new Error('無法獲取歷史數據');
            const history = await response.json();
            if(history.error) throw new Error(history.error);

            const initialData = history.map(p => ({ x: new Date(p.timestamp), y: p.ppi }));
            sentimentChart.data.datasets[0].data = initialData;
            sentimentChart.update();
            console.log(`已成功載入 ${initialData.length} 筆歷史數據。`);
        } catch (error) {
            console.error("初始化圖表歷史數據失敗:", error);
            connectionStatusEl.textContent = "載入歷史數據失敗。";
        }

        // 3. 獲取當前折扣
        await fetchDiscount();

        // 4. 建立 WebSocket 連線以接收即時更新
        connectWebSocket();

        // 5. 設定每分鐘的折扣更新
        mainInterval = setInterval(fetchDiscount, 60000);

        // 6. 綁定按鈕事件
        generateCodeBtn.addEventListener('click', showBarcode);
        closeModalBtn.addEventListener('click', () => {
            codeModal.classList.add('hidden');
        });
    }

    initialize();
});
