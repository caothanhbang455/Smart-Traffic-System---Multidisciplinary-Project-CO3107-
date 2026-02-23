# Project Architecture

## 1. Overall Folder Structure

```
art-traffic-system/
├── backend/ # FastAPI server (Python)
├── frontend/ # ReactJS dashboard (JavaScript/TypeScript)
├── iot/ # ESP32/Gateway firmware (C++/Python)
├── ai_module/ # YOLO model and image processing scripts
├── data/ # Sample dataset and documentation
└── docker-compose.yml # Optional: run the entire system with Docker
```
---

## 2. Backend Module (FastAPI + MongoDB)

The backend acts as the central controller of the system, coordinating data flow between AI, IoT devices, and the frontend dashboard.

### Core Files

- **main.py**  
  Initializes the FastAPI application, connects to the database, and defines primary API routes.

- **config.py**  
  Stores environment-based configuration values (.env), such as:
  - MongoDB URI  
  - Adafruit IO key  
  - YOLO model path  

- **database.py**  
  Configures the Motor client (MongoDB async driver for Python).

### Folder Structure

- **models/**  
  Defines Pydantic schemas for data validation and serialization.  
  Examples:
  - `TrafficLog`
  - `SensorData`

- **services/**  
  Contains business logic and system integration modules:

  - `ai_service.py`  
    Receives images from the frontend and invokes the YOLO model for vehicle detection and counting.

  - `iot_service.py`  
    Implements the MQTT client to send and receive data from Adafruit IO.

  - `decision_maker.py`  
    Contains the traffic light timing algorithm based on:
    - AI vehicle counts
    - Sensor data (e.g., temperature, light)

- **routes/**  
  Modular API endpoints, for example:
  - `/camera`
  - `/sensors`
  - `/control`

---

## 3. Frontend Module (ReactJS)

The frontend provides real-time monitoring and manual control capabilities.

### API Layer

- **src/api/**  
  Contains Axios or Fetch configurations for communicating with the FastAPI backend.

### Components

- **CameraView.js**  
  Displays image or video streams with AI-generated bounding boxes.

- **TrafficChart.js**  
  Visualizes vehicle density using Chart.js or Recharts.

- **SensorPanel.js**  
  Displays real-time sensor data such as temperature and light intensity.

- **ManualControl.js**  
  Provides manual override buttons for traffic light states.

### State Management

- **src/hooks/**  
  Custom React hooks for managing:
  - WebSocket connections  
  - Long polling  
  - Real-time state synchronization  

---

## 4. AI Module (`ai_module/`)

Responsible for vehicle detection and traffic analysis.

### Structure

- **models/**  
  Stores trained YOLO model files, such as:
  - `yolov8n.pt`
  - `best.pt`

- **detector.py**  
  Contains the `TrafficDetector` class.  
  - **Input:** Image  
  - **Output:** JSON containing vehicle count and detection metadata  

- **test_ai.py**  
  Standalone script to test the AI model on a local image before integrating with the backend API.

---

## 5. Data Folder (`data/`)

Used for storing sample datasets and intermediate outputs.

- **raw/**  
  Raw traffic images (e.g., collected from Kaggle) for testing.

- **processed/**  
  Images after drawing bounding boxes for frontend visualization.

- **traffic_log.csv**  
  Temporary storage for vehicle count results when MongoDB is not yet configured.

---

## 6. IoT Module (`iot/`)

Contains firmware and configuration for hardware devices.

### firmware/

- **main.ino**  
  Main firmware code for ESP32.

- **config.h**  
  Stores sensitive configuration:
  - WiFi credentials  
  - Adafruit IO key  

  This file should be added to `.gitignore` to ensure security.