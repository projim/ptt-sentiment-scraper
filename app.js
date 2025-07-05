document.addEventListener('DOMContentLoaded', () => {
    // 檢查函式庫是否已成功載入
    if (typeof Chart === 'undefined' || typeof window.dateFns === 'undefined' || typeof window.dateFns.format !== 'function') {
        console.error("Fatal Error: A required library (Chart.js or date-fns) failed to load correctly.");
        document.getElementById('loading-text').innerHTML = "關鍵函式庫載入失敗，請檢查 libs 資料夾或網路連線並刷新頁面。";
        return;
    }
    
    // 從全域物件中預先解構出所有會用到的 date-fns 函式
    const { format, setMinutes, startOfHour, subDays, subHours, startOfDay } = window.dateFns;

    // DOM 元素
    const baselineDateEl = document.getElementById('baseline-date');
    const timeUnitEl = document.getElementById('time-unit');
    const baselineValueEl = document.getElementById('baseline-value');
    const analysisText = document.getElementById('analysis-text');
    const lastUpdatedEl = document.getElementById('last-updated');
    const loadingOverlay = document.getElementById('loading-overlay');
    const loadingText = document.getElementById('loading-text');
    const connectionDot = document.getElementById('connection-dot');
    const connectionStatus = document.getElementById('connection-status');
    const ctx = document.getElementById('sentimentChart').getContext('2d');
    
    // 應用程式狀態
    let sentimentChart;
    let baselinePni = 0;
    let ws;
    let isConnected = false;
    let realtimePniHistory = [];

    const serviceName = "ptt-gossiping-live"; // 請換成您在 Render 上設定的服務名稱
    const API_BASE_URL = `https://${serviceName}.onrender.com`;
    const WEBSOCKET_URL = `wss://${serviceName}.onrender.com/ws`;
    
    const chartConfig = {
        type: 'line',
        data: {
            datasets: [{
                label: '負面情緒趨勢',
                data: [],
                borderColor: 'rgba(255, 255, 255, 0.5)',
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
                    time: {},
                    grid: { color: 'rgba(255, 255, 255, 0.1)' },
                    ticks: { color: 'rgba(255, 255, 255, 0.7)' }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.1)' },
                    ticks: {
                        color: 'rgba(255, 255, 255, 0.7)',
                        callback: value => value.toFixed(0) + '%'
                    },
                    title: {
                        display: true,
                        text: '趨勢 (與基準比較)',
                        color: 'rgba(255, 255, 255, 0.9)'
                    }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: context => `趨勢: ${context.parsed.y.toFixed(1)}%`
                    }
                },
                annotation: {
                    annotations: {
                        baseline: {
                            type: 'line',
                            yMin: 0,
                            yMax: 0,
                            borderColor: 'rgba(255, 255, 0, 0.7)',
                            borderWidth: 2,
                            borderDash: [6, 6],
                            label: {
                                content: '基準線',
                                enabled: true,
                                position: 'end',
                                backgroundColor: 'rgba(255, 255, 0, 0.7)',
                                color: 'black',
                                font: { weight: 'bold' }
                            }
                        }
                    }
                }
            }
        }
    };

    function connectWebSocket() {
        ws = new WebSocket(WEBSOCKET_URL);

        ws.onopen = () => {
            isConnected = true;
            connectionStatus.textContent = "已連接";
            connectionDot.classList.remove('text-yellow-500', 'text-red-500');
            connectionDot.classList.add('text-green-500');
            updateChart(); 
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'pni_update') {
                const newPoint = { timestamp: new Date(data.timestamp * 1000), pni: data.pni };
                realtimePniHistory.push(newPoint);
                if (realtimePniHistory.length > 60) realtimePniHistory.shift();

                if (timeUnitEl.value === 'realtime') {
                    updateChart();
                }
                lastUpdatedEl.textContent = new Date().toLocaleTimeString('zh-TW');
            }
        };
        
        ws.onclose = () => {
            console.log("WebSocket 連接已斷開。");
            connectionDot.classList.remove('text-green-500', 'text-yellow-500');
            connectionDot.classList.add('text-red-500');
            if (isConnected) {
                isConnected = false;
                connectionStatus.textContent = "已斷線，5秒後嘗試重新連接...";
                setTimeout(connectWebSocket, 5000);
            } else {
                const errorMsg = `連線失敗。<br><strong class="text-yellow-400">請確認Python後端伺服器已部署並正確運行。</strong>`;
                connectionStatus.innerHTML = errorMsg;
                loadingText.innerHTML = errorMsg;
                analysisText.innerHTML = "無法連接到後端伺服器。請部署 Python 爬蟲程式，然後刷新此頁面。";
            }
        };

        ws.onerror = (error) => {
            console.error("WebSocket 發生錯誤:", error);
        };
    }
    
    async function updateChart() {
        const mode = timeUnitEl.value;
        loadingOverlay.style.display = 'flex';
        loadingText.textContent = `正在從資料庫獲取 ${mode} 歷史數據...`;
        
        try {
            const response = await fetch(`${API_BASE_URL}/api/history?timescale=${mode}`);
            if (!response.ok) throw new Error(`Network response was not ok (${response.status})`);
            
            const historyData = await response.json();
            if (historyData.error) throw new Error(historyData.error);
            
            const dataForChart = historyData.map(record => ({
                x: new Date(record.timestamp),
                y: record.pni - baselinePni
            }));

            if (sentimentChart) sentimentChart.destroy();
            
            const newConfig = initializeChartConfig(mode);
            sentimentChart = new Chart(ctx, newConfig);
            
            sentimentChart.data.datasets[0].data = dataForChart;
            sentimentChart.update();
            generateAnalysis(dataForChart, mode);

        } catch (error) {
            console.error('獲取或處理歷史數據失敗:', error);
            analysisText.innerHTML = "無法從資料庫獲取歷史數據。請稍後再試。";
        } finally {
            loadingOverlay.style.display = 'none';
        }
    }
    
    function initializeChartConfig(mode) {
        const newConfig = JSON.parse(JSON.stringify(chartConfig));
        const timeFormats = {
            realtime: { unit: 'minute', tooltipFormat: 'HH:mm', displayFormats: { minute: 'HH:mm' } },
            '30m': { unit: 'minute', tooltipFormat: 'HH:mm', displayFormats: { minute: 'HH:mm' } },
            '1h': { unit: 'hour', tooltipFormat: 'MM/dd HH:mm', displayFormats: { hour: 'HH:00' } }
        };
        newConfig.options.scales.x.time = timeFormats[mode];
        return newConfig;
    }
    
    function generateAnalysis(data, mode) {
         if (!isConnected) {
            analysisText.innerHTML = "無法連接到後端伺服器。請部署 Python 爬蟲程式，然後刷新此頁面。";
            return;
        }
        if (!data || data.length === 0) {
            analysisText.innerHTML = "正在等待從後端接收即時數據...";
            return;
        }
        const lastPoint = data[data.length - 1];
        const peakPoint = data.reduce((max, p) => p.y > max.y ? p : max, data[0]);
        
        let analysis = `與基準日 ${baselineDateEl.value} (PNI: ${baselinePni.toFixed(1)}%) 相比，`;
        const timeRanges = {
            'realtime': '最近一小時',
            '30m': '過去24小時',
            '1h': '過去3天'
        };
        analysis += `${timeRanges[mode]}的數據顯示，情緒高峰趨勢為 **${peakPoint.y > 0 ? '+' : ''}${peakPoint.y.toFixed(1)}%**。`;
        analysis += ` 目前最新的趨勢指數為 **${lastPoint.y > 0 ? '+' : ''}${lastPoint.y.toFixed(1)}%**。`;
        analysisText.innerHTML = analysis;
    }

    function generateBaselinePni(dateString) {
        let hash = 0;
        if (!dateString) dateString = new Date().toISOString();
        for (let i = 0; i < dateString.length; i++) {
            const char = dateString.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash |= 0;
        }
        const pseudoRandom = Math.abs(hash / 2147483647);
        return 15 + pseudoRandom * 15;
    }

    baselineDateEl.addEventListener('change', () => {
        baselinePni = generateBaselinePni(baselineDateEl.value);
        baselineValueEl.textContent = `${baselinePni.toFixed(1)} %`;
        updateChart();
    });
    timeUnitEl.addEventListener('change', updateChart);

    function initialize() {
        const today = new Date();
        const yesterday = new Date();
        yesterday.setDate(today.getDate() - 1);
        baselineDateEl.value = yesterday.toISOString().split('T')[0];
        baselinePni = generateBaselinePni(baselineDateEl.value);
        baselineValueEl.textContent = `${baselinePni.toFixed(1)} %`;
        
        connectWebSocket();
    }

    initialize();
});
</script>
</body>
</html>
