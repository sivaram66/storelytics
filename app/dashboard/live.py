"""
Live Storelytics Dashboard
Run: python -m dashboard.live

Shows real-time metrics updating as events flow in from the detection pipeline.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

print("ROUTER CREATED ID:" ,id(router))
STORE_ID  = "STORE_PURPLLE_001"
REFRESH_S = 3
print("Dashboard ROUTER LOADED")

@router.get("/dashboard/live", response_class=HTMLResponse)
def dashboard():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Storelytic Dashboard</title>

    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">

    <script src="https://cdn.tailwindcss.com"></script>

    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

    <style>
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: #fafafb; 
            color: #1e293b;
        }

        .premium-card {
            background: #ffffff;
            border: 1px solid rgba(251, 146, 60, 0.15);
            border-radius: 16px;
            box-shadow: 0 4px 24px -8px rgba(251, 146, 60, 0.08);
            transition: all 0.3s ease;
        }

        .premium-card:hover {
            box-shadow: 0 12px 32px -8px rgba(251, 146, 60, 0.12);
            border-color: rgba(251, 146, 60, 0.3);
        }

        .value-text {
            background: linear-gradient(135deg, #ea580c 0%, #fb923c 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        /* Smooth Accordion Transition */
        .accordion-content {
            transition: max-height 0.3s ease-out, padding 0.3s ease;
            max-height: 0;
            overflow: hidden;
        }
        
        .accordion-content.expanded {
            max-height: 150px; /* Arbitrary large enough height */
            padding-top: 1rem;
            padding-bottom: 1rem;
        }

        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #fed7aa; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #fb923c; }
    </style>
</head>

<body class="antialiased min-h-screen pb-12">

<div class="max-w-7xl mx-auto px-6 pt-12">

    <div class="flex flex-col items-center mb-10">
        <h1 class="text-4xl md:text-5xl font-extrabold text-gray-900 tracking-tight mb-4">
            <span class="text-orange-500"> Storelytic</span>
        </h1>
        <div class="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-orange-50 border border-orange-100 text-orange-600 text-xs font-bold tracking-widest uppercase shadow-sm">
            <span class="relative flex h-2 w-2">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-orange-400 opacity-75"></span>
              <span class="relative inline-flex rounded-full h-2 w-2 bg-orange-500"></span>
            </span>
            Live Dashboard
        </div>
        <div class="text-sm text-gray-400 font-medium mt-3" id="store-id-display"></div>
    </div>

    <div class="grid grid-cols-2 lg:grid-cols-5 gap-5 mb-8">
        <div class="premium-card p-6 flex flex-col items-center justify-center text-center">
            <div class="text-gray-400 text-xs font-bold uppercase tracking-wider mb-2">Unique Visitors</div>
            <div id="visitors" class="text-3xl font-extrabold value-text">0</div>
        </div>

        <div class="premium-card p-6 flex flex-col items-center justify-center text-center">
            <div class="text-gray-400 text-xs font-bold uppercase tracking-wider mb-2">Conversion</div>
            <div id="conversion" class="text-3xl font-extrabold value-text">0%</div>
        </div>

        <div class="premium-card p-6 flex flex-col items-center justify-center text-center">
            <div class="text-gray-400 text-xs font-bold uppercase tracking-wider mb-2">Avg Dwell</div>
            <div id="dwell" class="text-3xl font-extrabold value-text">0s</div>
        </div>

        <div class="premium-card p-6 flex flex-col items-center justify-center text-center">
            <div class="text-gray-400 text-xs font-bold uppercase tracking-wider mb-2">Queue Depth</div>
            <div id="queue" class="text-3xl font-extrabold value-text">0</div>
        </div>
        
        <div class="premium-card p-6 flex flex-col items-center justify-center text-center">
            <div class="text-gray-400 text-xs font-bold uppercase tracking-wider mb-2">Abandonment</div>
            <div id="abandonment" class="text-3xl font-extrabold value-text">0%</div>
        </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        <div class="premium-card p-8 lg:col-span-2 flex flex-col">
            <h2 class="text-lg font-bold text-gray-800 mb-6 tracking-tight">
                Conversion Funnel
            </h2>
            <div class="relative flex-1 w-full min-h-[300px]">
                <canvas id="funnelChart"></canvas>
            </div>
        </div>

        <div class="flex flex-col gap-6">
            
            <div class="premium-card p-6 flex-1 flex flex-col">
                <div class="flex justify-between items-center mb-5">
                    <h2 class="text-lg font-bold text-gray-800 tracking-tight">Anomalies</h2>
                </div>
                <div id="anomalies" class="space-y-3 overflow-y-auto pr-1">
                    </div>
            </div>

            <div class="premium-card p-6 flex-1 flex flex-col">
                <h2 class="text-lg font-bold text-gray-800 mb-5 tracking-tight">Feed Health</h2>
                <div id="health" class="space-y-3 overflow-y-auto pr-1">
                    </div>
            </div>

        </div>
    </div>

</div>

<script>
const STORE_ID = "STORE_PURPLLE_001";
document.getElementById('store-id-display').innerText = STORE_ID;

// Toggle Anomaly Accordion
function toggleAnomaly(id) {
    const content = document.getElementById(`anomaly-content-${id}`);
    const icon = document.getElementById(`anomaly-icon-${id}`);
    
    if (content.classList.contains('expanded')) {
        content.classList.remove('expanded');
        icon.style.transform = 'rotate(0deg)';
    } else {
        content.classList.add('expanded');
        icon.style.transform = 'rotate(180deg)';
    }
}

// Counter animation
function animateValue(id, newValue, suffix="") {
    const el = document.getElementById(id);
    const start = parseFloat(el.innerText) || 0;
    const duration = 500;
    const startTime = performance.now();

    function update(now) {
        const progress = Math.min((now - startTime) / duration, 1);
        const value = start + (newValue - start) * progress;
        el.innerText = Math.round(value) + suffix;
        if (progress < 1) requestAnimationFrame(update);
    }

    requestAnimationFrame(update);
}

// Initialize Chart
let funnelChart;

function initChart() {
    const ctx = document.getElementById('funnelChart').getContext('2d');
    
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(249, 115, 22, 0.85)');
    gradient.addColorStop(1, 'rgba(253, 186, 116, 0.1)');

    funnelChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: [],
            datasets: [{
                label: 'Count',
                data: [],
                backgroundColor: gradient,
                borderColor: '#f97316',
                borderWidth: 2,
                borderRadius: 6,
                barPercentage: 0.5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { 
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#ffffff',
                    titleColor: '#1e293b',
                    bodyColor: '#475569',
                    borderColor: '#fed7aa',
                    borderWidth: 1,
                    padding: 12,
                    boxPadding: 4,
                    displayColors: false,
                    titleFont: { family: 'Plus Jakarta Sans', size: 14, weight: 'bold' },
                    bodyFont: { family: 'Plus Jakarta Sans', size: 13 },
                    callbacks: {
                        label: function(context) {
                            // Extract dropoff custom property from the dataset array if available
                            const dropoff = funnelChart.data.datasets[0].dropoffs[context.dataIndex];
                            let label = `Count: ${context.raw}`;
                            if (dropoff && dropoff > 0) {
                                label += `  |  Drop-off: ${dropoff}%`;
                            }
                            return label;
                        }
                    }
                }
            },
            scales: {
                y: { 
                    beginAtZero: true,
                    grid: { color: '#f8fafc', drawBorder: false },
                    ticks: { color: '#94a3b8', font: { family: 'Plus Jakarta Sans', weight: '500' } }
                },
                x: { 
                    grid: { display: false, drawBorder: false },
                    ticks: { color: '#64748b', font: { family: 'Plus Jakarta Sans', weight: '600' } }
                }
            },
            animation: { duration: 600, easing: 'easeOutQuad' }
        }
    });
}

// Load Data
async function load() {
    try {
        const [metrics, funnel, anomalies, health] = await Promise.all([
            fetch(`/stores/${STORE_ID}/metrics`).then(r => r.json()).catch(() => ({})),
            fetch(`/stores/${STORE_ID}/funnel`).then(r => r.json()).catch(() => ({})),
            fetch(`/stores/${STORE_ID}/anomalies`).then(r => r.json()).catch(() => ({})),
            fetch(`/health`).then(r => r.json()).catch(() => ({}))
        ]);

        // Metrics
        animateValue("visitors", metrics.unique_visitors || 0);
        animateValue("queue", metrics.queue_depth || 0);
        animateValue("dwell", Math.round((metrics.avg_dwell_ms || 0) / 1000), "s");

        document.getElementById("conversion").innerText = ((metrics.conversion_rate || 0) * 100).toFixed(1) + "%";
        document.getElementById("abandonment").innerText = ((metrics.abandonment_rate || 0) * 100).toFixed(1) + "%";

        // Funnel
        const stages = funnel.stages || [];
        funnelChart.data.labels = stages.map(s => s.stage);
        funnelChart.data.datasets[0].data = stages.map(s => s.count);
        funnelChart.data.datasets[0].dropoffs = stages.map(s => (s.dropoff_pct || 0).toFixed(1));
        funnelChart.update();

        // Anomalies (Clickable Accordion)
        let aHTML = "";
        const anomalyList = anomalies.anomalies || [];
        
        if (anomalyList.length === 0) {
            aHTML = `<div class="text-sm text-gray-400 italic text-center py-6">Store operating normally</div>`;
        } else {
            anomalyList.slice(0, 5).forEach((a, i) => {
                let colorClass = "blue";
                let bgClass = "bg-blue-50";
                
                if (a.severity === "CRITICAL") { colorClass = "red"; bgClass = "bg-red-50"; }
                else if (a.severity === "WARN") { colorClass = "orange"; bgClass = "bg-orange-50"; }

                const typeFmt = a.anomaly_type ? a.anomaly_type.replace(/_/g, " ") : "Unknown Anomaly";
                const actionText = a.suggested_action || "No action specified.";

                aHTML += `
                <div class="border border-gray-100 rounded-xl overflow-hidden bg-white shadow-sm hover:border-orange-200 transition-colors">
                    <div class="px-4 py-3 cursor-pointer flex justify-between items-center bg-white hover:bg-gray-50 transition-colors" onclick="toggleAnomaly(${i})">
                        <div class="flex items-center gap-3">
                            <div class="px-2 py-0.5 rounded text-[10px] font-bold tracking-wider ${bgClass} text-${colorClass}-600 border border-${colorClass}-100">
                                ${a.severity}
                            </div>
                            <div class="text-sm font-semibold text-gray-700">${typeFmt}</div>
                        </div>
                        <svg id="anomaly-icon-${i}" class="w-4 h-4 text-gray-400 transition-transform duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                        </svg>
                    </div>
                    <div id="anomaly-content-${i}" class="accordion-content bg-gray-50/50 px-4 text-sm text-gray-600 border-t border-gray-50">
                        <span class="font-bold text-gray-700 block mb-1">Suggested Action:</span>
                        ${actionText}
                    </div>
                </div>`;
            });
        }
        document.getElementById("anomalies").innerHTML = aHTML;

        // Health Feeds
        let hHTML = "";
        const feedList = health.store_feeds || [];
        
        if (feedList.length === 0) {
            hHTML = `<div class="text-sm text-gray-400 italic text-center py-6">Waiting for feed data...</div>`;
        } else {
            feedList.forEach(f => {
                const isStale = f.stale;
                const statusColor = isStale ? "red" : "emerald";
                const statusText = isStale ? "STALE" : "LIVE";
                const lastEvent = f.minutes_since_last !== undefined ? `${Math.round(f.minutes_since_last)}m ago` : "never";
                
                hHTML += `
                <div class="flex items-center justify-between border border-gray-100 bg-white px-4 py-3.5 rounded-xl shadow-sm">
                    <div>
                        <div class="text-sm font-bold text-gray-800">${f.store_id}</div>
                        <div class="text-xs text-gray-400 font-medium mt-0.5">Last event: ${lastEvent}</div>
                    </div>
                    <div class="flex items-center gap-2 bg-${statusColor}-50 px-2.5 py-1 rounded-md border border-${statusColor}-100">
                        <div class="h-2 w-2 rounded-full bg-${statusColor}-500 ${!isStale ? 'animate-pulse' : ''}"></div>
                        <span class="text-[11px] font-extrabold tracking-wider text-${statusColor}-600">${statusText}</span>
                    </div>
                </div>`;
            });
        }
        document.getElementById("health").innerHTML = hHTML;

    } catch (e) {
        console.error("Dashboard update failed:", e);
    }
}

// Init & Start Polling
initChart();
setInterval(load, 3000);
load();

</script>

</body>
</html>
"""