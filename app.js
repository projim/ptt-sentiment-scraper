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
    
    // [UPDATE] 全新的、更詳細的圖表設定
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
                    time: {
                        unit: 'minute',
                        tooltipFormat: 'HH:mm:ss', // 提示框顯示到秒
                        displayFormats: {
                            minute: 'HH:mm' // X 軸只顯示小時和分鐘
                        }
                    },
                    display: true, // 顯示 X 軸
                    grid: {
                        color: 'rgba(255, 255, 255, 0.1)'
                    },
                    ticks: {
                        color: 'rgba(255, 255, 255, 0.7)',
                        maxRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 7 // 最多顯示 7 個時間刻度，避免擁擠
                    }
                },
                y: {
                    display: true, // 顯示 Y 軸
                    grid: {
                        color: 'rgba(255, 255, 255, 0.1)'
                    },
                    ticks: {
                        color: 'rgba(255, 255, 255, 0.7)',
                        callback: function(value) {
                            return value.toFixed(1) + '%'; // 刻度顯示到小數點後一位
                        }
                    },
                    title: {
                        display: true,
                        text: '正向情緒指數 (PPI)',
                        color: 'rgba(255, 255, 255, 0.9)'
                    }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: true, // 啟用提示框
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        title: function(context) {
                            return format(context[0].parsed.x, 'HH:mm:ss');
                        },
                        label: function(context) {
                            return `PPI: ${context.parsed.y.toFixed(2)}%`; // 提示框顯示到小數點後兩位
                        }
                    }
                }
            }
        }
    };

    async function initializeChartWithHistory() {
        try {
            connectionStatusEl.textContent = "正在載入歷史數據...";
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
    }

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
                if (chartData.length > 60) {
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
            connectionStatusEl.textContent = "獲取失敗，將於下一分鐘重試...";
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
            if (seconds <= 0) clearInterval(countdownInterval);
        }, 1000);
    }
    
    function showBarcode() {
        if (!currentDiscountData) return;
        codeModal.classList.remove('hidden');
        const discountCode = `MILK-${currentDiscountData.final_discount_percentage.toFixed(2)}-${Date.now()}`;
        JsBarcode("#barcode", discountCode, {
            format: "CODE128", lineColor: "#000", width: 2, height: 80, displayValue: true, fontSize: 18
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

    async function initialize() {
        sentimentChart = new Chart(ctx, chartConfig);
        await initializeChartWithHistory();
        await fetchDiscount();
        connectWebSocket();
        mainInterval = setInterval(fetchDiscount, 60000);
        generateCodeBtn.addEventListener('click', showBarcode);
        closeModalBtn.addEventListener('click', () => {
            codeModal.classList.add('hidden');
        });
    }

    initialize();
});
