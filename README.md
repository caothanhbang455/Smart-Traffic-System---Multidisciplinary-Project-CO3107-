# Smart Traffic System (CO3107)

A smart traffic light control system that combines:

- AI vehicle detection (YOLOv8)
- Traffic phase decision making (NS/EW)
- IoT sensors and light control (Adafruit IO + MQTT)
- Frontend dashboard (React + Vite)
- MongoDB Atlas for sensor history storage

## 1. Directory Structure

```text
Smart-Traffic-System---Multidisciplinary-Project-CO3107-/
|- backend/        # Flask API + MQTT + MongoDB
|- frontend/       # React + TypeScript + Vite dashboard
|- ai_module/      # Detector and AI logic
|- data/           # Test images, log data
|- iot/            # ESP32 firmware
|- yolov8m.pt      # Model used by the detector
```

## 2. Main Technologies

- **Backend:** Flask, PyMongo, OpenCV, Ultralytics
- **Frontend:** React 19, TypeScript, Vite, Axios
- **Database:** MongoDB Atlas
- **IoT:** Adafruit IO (MQTT)

## 3. Prerequisites

- Python 3.10+
- Node.js 18+
- npm
- MongoDB Atlas account
- Adafruit IO account

### 3.1 Requirements Convention

A single `requirements.txt` file is used at the project root.

Recommended installation:

- Running the backend: `pip install -r requirements.txt` from root, or `pip install -r ../requirements.txt` inside `backend/`
- Running standalone AI scripts: same `pip install -r requirements.txt` from root

## 4. Backend Setup

Navigate to the backend directory:

```bash
cd backend
```

Install dependencies:

```bash
pip install -r ../requirements.txt
```

### 4.1 Create the .env file

Create `backend/.env` with the following content:

```env
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster-url>/traffic_system?retryWrites=true&w=majority&appName=Cluster0
MONGODB_DB=traffic_system
MONGODB_SENSOR_COLLECTION=sensor_history

ADAFRUIT_AIO_USERNAME=<your_adafruit_username>
ADAFRUIT_AIO_KEY=<your_adafruit_key>
```

Notes:

- Do not commit `.env` to the repository
- If the MongoDB password contains special characters, URL-encode them

### 4.2 Verify MongoDB Atlas Connection

```bash
python -c "from app.database import check_mongodb_connection; ok, err = check_mongodb_connection(); print('MongoDB OK' if ok else f'MongoDB FAIL: {err}')"
```

### 4.3 Run the Backend

```bash
python -m app.main
```

The backend runs at:

```
http://127.0.0.1:5000
```

## 5. Frontend Setup

Navigate to the frontend directory:

```bash
cd frontend
```

Install packages:

```bash
npm install
```

Create `frontend/.env` (if you need to change the backend URL):

```env
VITE_BACKEND_URL=http://127.0.0.1:5000
```

Start the frontend:

```bash
npm run dev
```

## 6. Main Flow

1. Upload 4 images (north / south / east / west) from the frontend
2. Backend calls the AI detector
3. AI returns vehicle metrics and annotated images (with bounding boxes)
4. Backend retrieves IoT sensor data (with fallback if IoT data is unavailable)
5. Backend runs the decision maker and sends light commands via MQTT to Adafruit IO
6. Backend saves sensor history to MongoDB Atlas
7. Frontend displays the decision result, bounding boxes, and the 20 most recent sensor records

## 7. API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/traffic` | Current traffic light state |
| GET | `/api/system_params` | Read system parameters |
| PUT | `/api/system_params` | Update system parameters |
| POST | `/api/control` | Manually set a single intersection light |
| POST | `/api/manual_control` | Manual override for both intersections |
| POST | `/api/analyze_images` | AI analysis only (no decision) |
| POST | `/api/run_decision_with_images` | Full pipeline: AI → decision → IoT |
| GET | `/api/sensor_history?limit=20` | Recent sensor history records |

## 8. Quick API Test (PowerShell)

**Decision pipeline:**

```powershell
$uri = "http://127.0.0.1:5000/api/run_decision_with_images"

$form = @{
  north = Get-Item "D:\path\to\north.jpg"
  south = Get-Item "D:\path\to\south.jpg"
  east  = Get-Item "D:\path\to\east.jpg"
  west  = Get-Item "D:\path\to\west.jpg"
}

$res = Invoke-RestMethod -Method Post -Uri $uri -Form $form
$res | ConvertTo-Json -Depth 10
```

**Sensor history:**

```powershell
$uri = "http://127.0.0.1:5000/api/sensor_history?limit=20"
$res = Invoke-RestMethod -Method Get -Uri $uri
$res | ConvertTo-Json -Depth 10
```

## 9. Security Notes

- If MongoDB credentials were ever exposed in a terminal or chat, rotate the Atlas password immediately.
- Restrict IP whitelisting in MongoDB Atlas to specific addresses for dev/test; avoid leaving `0.0.0.0/0` open when not needed.
- Never commit sensitive information to the repository (`.env` files, API keys).
