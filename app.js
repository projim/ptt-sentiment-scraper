document.addEventListener('DOMContentLoaded', () => {
    // 檢查函式庫是否已成功載入
    if (typeof Chart === 'undefined' || typeof window.dateFns === 'undefined') {
        console.error("Fatal Error: A required library failed to load correctly.");
        document.getElementById('loading-text').innerHTML = "關鍵函式庫載入失敗，請檢查 libs 資料夾或網路連線並刷新頁面。";
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
                x: { display: false },
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
            updateUI(data);
            startCountdown();

        } catch (error) {
            console.error('獲取折扣失敗:', error);
            connectionStatusEl.textContent = "獲取折扣失敗，請稍後重試。";
            discountDisplayEl.textContent = "---";
        }
    }

    function updateUI(data) {
        const { current_ppi, final_discount_percentage, settings } = data;
        
        // 更新折扣顯示
        const discountValue = (100 - final_discount_percentage) / 10;
        discountDisplayEl.textContent = `${discountValue.toFixed(1)} 折`;

        // 更新 PPI 顯示
        ppiDisplayEl.textContent = `${current_ppi.toFixed(2)} %`;

        // 更新公式顯示
        const { base_discount, ppi_threshold, conversion_factor } = settings;
        formulaDisplayEl.textContent = `${base_discount}% + (${current_ppi.toFixed(1)}% - ${ppi_threshold}%) * ${conversion_factor}`;

        // 更新圖表
        updateChart(current_ppi);
    }
    
    function updateChart(newPpi) {
        const now = new Date();
        const dataset = sentimentChart.data.datasets[0].data;
        
        // 新增數據點
        dataset.push({ x: now, y: newPpi });
        
        // 只保留最近一小時的數據
        if (dataset.length > 60) {
            dataset.shift();
        }

        sentimentChart.update('quiet');
    }

    function startCountdown() {
        clearInterval(countdownInterval);
        let seconds = 60;
        countdownTextEl.style.display = 'block';

        countdownInterval = setInterval(() => {
            seconds--;
            countdownTimerEl.textContent = `${seconds}`;
            if (seconds <= 0) {
                clearInterval(countdownInterval);
                countdownTextEl.style.display = 'none';
            }
        }, 1000);
    }

    function initialize() {
        // 初始化圖表
        sentimentChart = new Chart(ctx, chartConfig);
        
        // 立即獲取第一次折扣，然後設定每分鐘更新
        fetchDiscount();
        mainInterval = setInterval(fetchDiscount, 60000); // 60秒
    }

    initialize();
});

