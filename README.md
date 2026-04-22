# 🧠 Storelytics — Real-Time Retail Insights

Storelytics is a simple system that converts store activity data into useful insights such as:
- Number of visitors
- Conversion rate
- Queue and dwell time
- Anomalies
- Live dashboard

---

## 🚀 Quick Start (Very Simple)

### Step 1 — Download the Project

Open your terminal and run:

git clone https://github.com/sivaram66/storelytics.git

cd storelytics

---

### Step 2 — Start the Application

Run:

docker compose up

👉 This will:
- Start backend server
- Start PostgreSQL database
- Automatically create tables

⏳ Wait ~10–20 seconds

---

## 🌐 Open the Application

After startup, open:

API Docs:
http://127.0.0.1:8000/docs

Live Dashboard:
http://127.0.0.1:8000/dashboard/live

---

## 📥 Add Data (Important Step)

Initially, no data is present.  
You need to add data to see results.

---

### ✅ Easiest Way (Recommended)

1. Open:
http://127.0.0.1:8000/docs

2. Find:
POST /events/ingest

3. Click "Try it out"

4. Paste data or upload file

5. Click Execute

---

### 💻 Using Sample Data

**File**:

data/events/sample_events.jsonl

---

### 🪟 Windows (PowerShell)

```powershell
$body = Get-Content "data/events/sample_events.jsonl" -Raw Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/events/ingest" `
  -Method POST `
  -Body $body `
  -ContentType "application/json"

### Mac / Linux

curl -X POST "http://127.0.0.1:8000/events/ingest" -H "Content-Type: application/json" --data-binary @data/events/sample_events.jsonl
```
---

## 📊 View Results

Metrics:
http://127.0.0.1:8000/stores/STORE_PURPLLE_001/metrics

Funnel:
http://127.0.0.1:8000/stores/STORE_PURPLLE_001/funnel

Anomalies:
http://127.0.0.1:8000/stores/STORE_PURPLLE_001/anomalies

---

## 📺 Live Dashboard

http://127.0.0.1:8000/dashboard/live

👉 Shows real-time updates

---

## ⚙️ Important Notes

- No manual setup required
- Database and tables are auto-created
- Works on Windows, Mac, and Linux
- Uses Docker for setup

---

## 🔁 Reset (Optional)

docker compose down -v
docker compose up

---

## 🧠 Workflow

1. Run app  
2. Add data  
3. Open dashboard  
4. View insights  

---

## 🎯 Done!

Your system is ready 🚀
