# SENTINEL - Quick Start Guide

There are two ways to run the Sentinel Surveillance System:

1. One-Click Launcher (Recommended)
2. Manual Execution

---

# Option 1: One-Click Launcher (Recommended)

Run the interactive launcher from the project root directory:

```powershell
.\run.bat
```

Or simply double-click `run.bat` in Windows File Explorer.

You will see:

```text
[1] Launch Complete System (Backend API + Command Center Web UI + Edge AI)
[2] Launch Backend API and Open Web Dashboard only
[3] Launch Edge AI Vision Pipeline only
[4] Run Full Test Suite (210 Tests)
[5] Exit
```

## Launch Complete System

Select:

```text
1
```

This will:

- Start the FastAPI Backend Server
- Open the Command Center Dashboard
- Start the Edge AI Vision Pipeline

Dashboard:

```text
http://localhost:8000/dashboard/
```

---

## Launch Backend + Dashboard Only

Select:

```text
2
```

This starts:

- Backend API
- Command Center Dashboard

Dashboard:

```text
http://localhost:8000/dashboard/
```

API Documentation:

```text
http://localhost:8000/docs
```

---

## Launch Edge AI Vision Pipeline Only

Select:

```text
3
```

This starts only the Edge AI engine.

Modules include:

- YOLO Object Detection
- ByteTrack Tracking
- Automatic License Plate Recognition (ALPR)
- Behavior Engine
- Event Scheduler

---

## Run Full Test Suite

Select:

```text
4
```

This runs the complete test suite (~210 tests).

---

# Option 2: Manual Execution

Run each component separately using different terminal windows.

---

## 1. Start Database & Redis (Optional)

If Docker is installed:

```powershell
docker compose up -d
```

This starts:

- PostgreSQL
- Redis

If Docker is unavailable, the backend can run in standalone/proxy mode.

---

## 2. Start Backend API & Dashboard

Using the launcher:

```powershell
.\start_backend.bat
```

Or manually:

```powershell
myenv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Dashboard:

```text
http://localhost:8000/dashboard/
```

Swagger API Docs:

```text
http://localhost:8000/docs
```

---

## 3. Start Edge AI Vision Engine

Using the launcher:

```powershell
.\start_edge.bat
```

Or manually:

```powershell
cd edge
..\myenv\Scripts\python.exe sentinel_edge/main.py
```

The Edge AI engine performs:

- Object Detection
- Multi-Object Tracking
- ALPR
- Behavior Analysis
- Event Generation

---

## 4. Frontend Development Mode (Optional)

The backend already serves the production dashboard.

For frontend development with hot reloading:

```powershell
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

---

## 5. Run Test Suite

Using the launcher:

```powershell
.\run_tests.bat
```

Or directly:

```powershell
myenv\Scripts\python.exe -m pytest edge/tests
```

---

# Port Configuration

Verify the backend URL configured in:

```text
edge/config/node.yaml
```

Default configuration:

```yaml
api:
  base_url: http://127.0.0.1:8000
```

If the backend runs on another port (e.g., 8001), update both:

### Backend

```powershell
myenv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
```

### node.yaml

```yaml
api:
  base_url: http://127.0.0.1:8001
```

Both values must match.

---

# Quick Reference

| Component | Command |
|------------|----------|
| Complete System | `.\run.bat` → Option 1 |
| Backend + Dashboard | `.\run.bat` → Option 2 |
| Edge AI Only | `.\run.bat` → Option 3 |
| Run Tests | `.\run.bat` → Option 4 |
| Backend API | `.\start_backend.bat` |
| Edge AI Engine | `.\start_edge.bat` |
| Docker Services | `docker compose up -d` |
| Frontend Dev Mode | `cd frontend && npm run dev` |

---

## URLs

### Dashboard

```text
http://localhost:8000/dashboard/
```

### API Documentation

```text
http://localhost:8000/docs
```
