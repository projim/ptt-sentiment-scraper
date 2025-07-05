document.addEventListener('DOMContentLoaded', () => {
    // 檢查函式庫是否已成功載入
    if (typeof Chart === 'undefined' || typeof window.dateFns === 'undefined') {
        console.error("Fatal Error: A required library failed to load.");
        document.getElementById('loading-text').innerHTML = "關鍵函式庫載入失敗，請刷新頁面重試。";
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
    
    // 應用程式狀態
    let sentimentChart;
    let mainInterval;
    let countdownInterval;

    const serviceName = "ptt-gossiping-live"; // 請務必換成您在 Render 上設定的服務名稱
    const API_BASE_URL = `https://${serviceName}.onrender.com`;
    
    const chartConfig = {
        type: 'line',
        data: {
            labels: [],
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

    // [UPDATE] 新的 WebSocket 連接邏輯
    function connectWebSocket() {
        const WEBSOCKET_URL = `wss://${serviceName}.onrender.com/ws`;
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
            setTimeout(connectWebSocket, 5000);
        };
    }

    // [UPDATE] 新的圖表初始化邏輯
    async function initializeLiveChart() {
        try {
            const response = await fetch(`${API_BASE_URL}/api/history?timescale=realtime`);
            if (!response.ok) throw new Error('Network response was not ok');
            const history = await response.json();
            
            const initialData = history.map(p => ({ x: new Date(p.timestamp), y: p.ppi }));

            sentimentChart = new Chart(ctx, chartConfig);
            sentimentChart.data.datasets[0].data = initialData;
            sentimentChart.update();

        } catch (error) {
            console.error("初始化圖表失敗:", error);
            // 即使失敗，也建立一個空圖表
            sentimentChart = new Chart(ctx, chartConfig);
        }
    }

    async function fetchDiscount() {
        // ... (此函式邏輯與之前版本相同)
    }

    function startCountdown() {
        // ... (此函式邏輯與之前版本相同)
    }

    async function initialize() {
        connectionStatusEl.textContent = "正在載入歷史數據...";
        
        // [UPDATE] 執行新的兩階段載入流程
        await initializeLiveChart(); // 1. 先用 API 填滿圖表
        fetchDiscount();             // 2. 獲取當前折扣
        connectWebSocket();          // 3. 建立 WebSocket 連線以接收即時更新
        
        mainInterval = setInterval(fetchDiscount, 60000); // 4. 設定每分鐘的折扣更新
    }

    initialize();
});
