# Frontend Dashboard (React + TypeScript + Vite)

Frontend dashboard for the Smart Traffic System.

## 1) Installation

```bash
cd frontend
npm install
```

## 2) Configure Backend URL

Create a `.env` file inside `frontend/`:

```env
VITE_BACKEND_URL=http://127.0.0.1:5000
```

If `.env` is not created, the app defaults to calling `http://127.0.0.1:5000`.

## 3) Run Development Server

```bash
npm run dev
```

## 4) Production Build

```bash
npm run build
npm run preview
```

## 5) Current Features

- Upload 4 intersection images (north / south / east / west)
- Call the backend decision API
- Display the winning phase result (NS / EW)
- Display annotated images with AI bounding boxes
- Display sensor history (latest 20 records) fetched from the MongoDB API
- Manual traffic light control override

## 6) API Endpoints Used by the Frontend

| Method | Endpoint |
|--------|----------|
| POST | `/api/run_decision_with_images` |
| GET | `/api/traffic` |
| POST | `/api/manual_control` |
| GET | `/api/system_params` |
| PUT | `/api/system_params` |
| GET | `/api/sensor_history?limit=20` |
