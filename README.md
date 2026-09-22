To run the entire Sentinel Surveillance System, you have two approaches: a one-click launcher (recommended) or running each component individually.

Option 1: One-Click Launcher (Recommended)
In the root directory, run the interactive launcher script 

run.bat
 from PowerShell or Command Prompt:

powershell
.\run.bat
(Or simply double-click run.bat in Windows File Explorer.)

You will see the interactive menu:

text
  [1] Launch Complete System (Backend API + Command Center Web UI + Edge AI)
  [2] Launch Backend API and Open Web Dashboard only
  [3] Launch Edge AI Vision Pipeline only
  [4] Run Full Test Suite (210 Tests)
  [5] Exit
Press 1 (or hit Enter) to:

Start the FastAPI Backend Server in a new terminal window.
Open the Command Center Web Dashboard automatically in your browser at http://localhost:8000/dashboard/.
Start the Edge AI Perception Pipeline in a separate terminal window.
Option 2: Step-by-Step Manual Execution
If you prefer to start each component in separate terminal windows:

1. (Optional) Start Database & Redis Services
If you have Docker installed and want full PostgreSQL & Redis persistence:

powershell
docker compose up -d
NOTE

If Docker is not running, the backend will automatically run in standalone/proxy mode without crashing.

2. Start the Backend API & Web Dashboard
The backend serves both the REST/WebSocket APIs and the pre-built React Command Center UI.

Using the batch file:

powershell
.\start_backend.bat
Or directly with the project virtual environment:

powershell
myenv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
Web Dashboard: Open http://localhost:8000/dashboard/
Swagger API Docs: Open http://localhost:8000/docs
3. Start the Edge AI Vision Engine
The edge engine runs the YOLOv8 object detector, ByteTrack, ALPR, behavior engine, and offload scheduler, pushing events to the backend.

Using the batch file:

powershell
.\start_edge.bat
Or directly:

powershell
cd edge
..\myenv\Scripts\python.exe sentinel_edge/main.py
4. (Optional) Run Frontend in Live Dev Mode
The backend already serves the pre-built UI at /dashboard/. However, if you are actively editing frontend code and want hot-reloading:

powershell
cd frontend
npm install
npm run dev
Then open http://localhost:5173.

5. (Optional) Run Test Suite
To verify the complete test suite (210 tests across ingestion, tracking, ALPR, behavior, etc.):

powershell
.\run_tests.bat
# or:
myenv\Scripts\python.exe -m pytest edge/tests
⚠️ Important Port Configuration Note
In 

edge/config/node.yaml
, check the api.base_url setting:

If the backend is running on port 8000 (the default in run.bat and start_backend.bat), make sure base_url in 

node.yaml
 is set to:
yaml
api:
  base_url: http://127.0.0.1:8000
If your backend is running on port 8001 (per 

.env
), ensure both the backend start command and node.yaml use port 8001.
