# Backend Guide (Flask + AI + IoT + MongoDB)

## 1) Installation

```bash
cd backend
pip install -r ../requirements.txt
```

Notes:

- There is a single dependency file: `requirements.txt` at the project root.
- When inside `backend/`, install with `pip install -r ../requirements.txt`.

## 2) Configure .env

Create `backend/.env`:

```env
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster-url>/traffic_system?retryWrites=true&w=majority&appName=Cluster0
MONGODB_DB=traffic_system
MONGODB_SENSOR_COLLECTION=sensor_history

ADAFRUIT_AIO_USERNAME=<your_adafruit_username>
ADAFRUIT_AIO_KEY=<your_adafruit_key>
```

## 3) Verify MongoDB Atlas Connection

```bash
python -c "from app.database import check_mongodb_connection; ok, err = check_mongodb_connection(); print('MongoDB OK' if ok else f'MongoDB FAIL: {err}')"
```

## 4) Verify Sensor History Saving

```bash
python -c "from app.services.history_service import save_sensor_history; print(save_sensor_history(123.4, 29.1, 'manual-test'))"
```

## 5) Run the Backend

```bash
python -m app.main
```

Default server address: `http://127.0.0.1:5000`

## 6) API Endpoints

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

## 7) Test Decision API

PowerShell:

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

## 8) Test Sensor History API

```powershell
$uri = "http://127.0.0.1:5000/api/sensor_history?limit=20"
$res = Invoke-RestMethod -Method Get -Uri $uri
$res | ConvertTo-Json -Depth 10
```

## 9) Operational Notes

- `run_decision_with_images` has a sensor fallback mechanism when IoT data is not yet available.
- Sensor history is saved to MongoDB with a source identifier that reflects the data flow path.
- Never commit the `.env` file to the repository.
