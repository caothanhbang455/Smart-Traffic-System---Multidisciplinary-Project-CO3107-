# backend/app.py
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_mqtt import Mqtt
import json
from datetime import datetime

# Decision engine
try:
    # khi chạy từ thư mục backend (python -m app.main)
    from .services.ai_service import AIService
    from .services.decision_maker import DecisionMaker
    from .models.traffic_state import TrafficState, DirectionState
except ImportError:
    # khi chạy từ project root (python -m backend.app.main)
    from backend.services.decision_maker import DecisionMaker  # type: ignore
    from backend.services.ai_service import AIService  # type: ignore
    from backend.models.traffic_state import TrafficState, DirectionState  # type: ignore

app = Flask(__name__)
CORS(app)  # cho phép React gọi API

# ==================== CẤU HÌNH MQTT ====================
app.config['MQTT_BROKER_URL'] = 'test.mosquitto.org'   # broker miễn phí để test
app.config['MQTT_BROKER_PORT'] = 1883
app.config['MQTT_USERNAME'] = ''   # để trống nếu public broker
app.config['MQTT_PASSWORD'] = ''
app.config['MQTT_KEEPALIVE'] = 60
app.config['MQTT_TLS_ENABLED'] = False

mqtt = Mqtt(app)

# ==================== DỮ LIỆU TẠM (sau này thay bằng Database) ====================
traffic_data = {
    "intersection_1": {"vehicles": 0, "light": "red", "last_update": ""},
    "intersection_2": {"vehicles": 0, "light": "green", "last_update": ""}
}


def _direction_from_payload(payload: dict) -> DirectionState:
    """
    Chuyển dữ liệu JSON thành DirectionState.

    Expected structure cho từng hướng:
    {
        "vehicle_count": 12,
        "vehicle_breakdown": {"car": 8, "bus": 2, "truck": 2},
        "weighted_vehicle_score": 85.0,
        "density_ratio": 0.65
    }
    """
    return DirectionState(
        vehicle_count=payload.get("vehicle_count", 0),
        vehicle_breakdown=payload.get("vehicle_breakdown", {}),
        weighted_vehicle_score=float(payload.get("weighted_vehicle_score", 0.0)),
        density_ratio=float(payload.get("density_ratio", 0.0)),
    )


def _state_from_current_traffic() -> TrafficState:
    """
    Tạo TrafficState đơn giản dựa trên biến traffic_data hiện có.

    Giả định:
    - intersection_1 đại diện cho lưu lượng theo pha NS (north/south)
    - intersection_2 đại diện cho lưu lượng theo pha EW (east/west)
    """
    inter1 = traffic_data.get("intersection_1", {})
    inter2 = traffic_data.get("intersection_2", {})

    def _mk_direction(vehicles: int) -> DirectionState:
        max_ref = 40 or 1
        density = min(1.0, float(vehicles) / max_ref)
        return DirectionState(
            vehicle_count=int(vehicles),
            vehicle_breakdown={"vehicle": int(vehicles)},
            weighted_vehicle_score=float(vehicles),
            density_ratio=density,
        )

    v1 = int(inter1.get("vehicles", 0))
    v2 = int(inter2.get("vehicles", 0))

    north = _mk_direction(v1)
    south = _mk_direction(v1)
    east = _mk_direction(v2)
    west = _mk_direction(v2)

    # dùng thông số môi trường mặc định; có thể nối với cảm biến sau
    return TrafficState(
        north=north,
        south=south,
        east=east,
        west=west,
        temperature=30.0,
        light_intensity=800.0,
    )

# ==================== MQTT CALLBACK ====================
@mqtt.on_connect()
def handle_connect(client, userdata, flags, rc):
    print("Connected to MQTT!")
    mqtt.subscribe('traffic/#')   # nghe tất cả topic bắt đầu bằng traffic/

@mqtt.on_message()
def handle_mqtt_message(client, userdata, message):
    global traffic_data
    topic = message.topic
    payload = message.payload.decode()
    
    print(f"Nhận MQTT: {topic} → {payload}")
    
    try:
        data = json.loads(payload)
        inter = data.get("intersection", "intersection_1")
        
        traffic_data[inter] = {
            "vehicles": data.get("vehicles", 0),
            "light": data.get("light", "red"),
            "last_update": datetime.now().strftime("%H:%M:%S")
        }
    except:
        pass

# ==================== API ROUTES ====================
@app.route('/')
def home():
    return "Smart Traffic System Backend is running!"

@app.route('/api/traffic')
def get_traffic():
    return jsonify(traffic_data)

@app.route('/api/control', methods=['POST'])
def control_light():
    data = request.json
    inter = data.get("intersection")
    new_light = data.get("light")
    
    if inter in traffic_data:
        traffic_data[inter]["light"] = new_light
        # Publish lệnh xuống IoT
        mqtt.publish(f'traffic/{inter}/command', json.dumps({"light": new_light}))
        return jsonify({"status": "success", "message": f"Light at {inter} has changed to {new_light}"})
    return jsonify({"status": "error"}), 400


@app.route('/api/decision', methods=['POST'])
def get_decision():
    """
    API lấy kết quả từ DecisionMaker.

    Body mẫu (JSON):
    {
      "phase": "NS",                 # hoặc "EW"
      "north": { ... },              # xem cấu trúc _direction_from_payload
      "south": { ... },
      "east":  { ... },
      "west":  { ... },
      "environment": {
        "temperature": 30.5,
        "light_intensity": 820.0
      }
    }
    """
    payload = request.json or {}

    try:
        phase = payload.get("phase", "NS")

        north = _direction_from_payload(payload.get("north", {}))
        south = _direction_from_payload(payload.get("south", {}))
        east = _direction_from_payload(payload.get("east", {}))
        west = _direction_from_payload(payload.get("west", {}))

        env = payload.get("environment", {})
        temperature = float(env.get("temperature", 30.0))
        light_intensity = float(env.get("light_intensity", 800.0))

        traffic_state = TrafficState(
            north=north,
            south=south,
            east=east,
            west=west,
            temperature=temperature,
            light_intensity=light_intensity,
        )

        engine = DecisionMaker()
        result = engine.decide(traffic_state, phase)

        return jsonify({"status": "success", "data": result})

    except Exception as exc:  # thu gọn lỗi cho client
        print("Decision API error:", exc)
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route('/api/run_decision', methods=['POST'])
def run_decision():
    """
    API đơn giản để frontend chỉ cần bấm nút "run".

    Sử dụng traffic_data hiện thời, xây TrafficState,
    tính duration cho cả hai pha NS và EW, sau đó chọn pha có
    green_duration cao hơn làm pha xanh tiếp theo.
    """
    try:
        traffic_state = _state_from_current_traffic()
        engine = DecisionMaker()

        ns = engine.decide(traffic_state, "NS")
        ew = engine.decide(traffic_state, "EW")

        winner = "NS" if ns["green_duration"] >= ew["green_duration"] else "EW"
        green_duration = ns["green_duration"] if winner == "NS" else ew["green_duration"]

        response = {
            "phase": winner,
            "green_duration": green_duration,
            "details": {
                "NS": {
                    "color": "green" if winner == "NS" else "red",
                    "duration": ns["green_duration"],
                },
                "EW": {
                    "color": "green" if winner == "EW" else "red",
                    "duration": ew["green_duration"],
                },
            },
        }

        return jsonify({"status": "success", "data": response})

    except Exception as exc:
        print("Run decision error:", exc)
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route('/api/analyze_images', methods=['POST'])
def analyze_images():
    """
    API để phân tích 4 ảnh từ camera.

    Body: multipart/form-data với 4 file:
    - north: ảnh hướng north
    - south: ảnh hướng south
    - east: ảnh hướng east
    - west: ảnh hướng west

    Returns: metrics cho từng hướng
    """
    try:
        if 'north' not in request.files or 'south' not in request.files or 'east' not in request.files or 'west' not in request.files:
            return jsonify({"status": "error", "message": "Thiếu ảnh cho một hoặc nhiều hướng"}), 400

        images = {}
        for direction in ['north', 'south', 'east', 'west']:
            file = request.files[direction]
            if file.filename == '':
                return jsonify({"status": "error", "message": f"Không có file cho hướng {direction}"}), 400
            images[direction] = file.read()

        ai_service = AIService()
        results = ai_service.analyze_multiple_images(images)

        return jsonify({"status": "success", "data": results})

    except Exception as exc:
        print("Analyze images error:", exc)
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route('/api/run_decision_with_images', methods=['POST'])
def run_decision_with_images():
    """
    API để upload 4 ảnh và chạy decision.

    Body: multipart/form-data với 4 file như trên.

    Returns: kết quả decision dựa trên AI analysis
    """
    try:
        if 'north' not in request.files or 'south' not in request.files or 'east' not in request.files or 'west' not in request.files:
            return jsonify({"status": "error", "message": "Thiếu ảnh cho một hoặc nhiều hướng"}), 400

        images = {}
        for direction in ['north', 'south', 'east', 'west']:
            file = request.files[direction]
            if file.filename == '':
                return jsonify({"status": "error", "message": f"Không có file cho hướng {direction}"}), 400
            images[direction] = file.read()

        ai_service = AIService()
        ai_results = ai_service.analyze_multiple_images(images)

        # Chuyển AI results thành DirectionState
        def _direction_from_ai(ai_data):
            return DirectionState(
                vehicle_count=ai_data.get("vehicle_count", 0),
                vehicle_breakdown=ai_data.get("vehicle_breakdown", {}),
                weighted_vehicle_score=float(ai_data.get("weighted_vehicle_score", 0.0)),
                density_ratio=float(ai_data.get("density_ratio", 0.0)),
            )

        north = _direction_from_ai(ai_results.get("north", {}))
        south = _direction_from_ai(ai_results.get("south", {}))
        east = _direction_from_ai(ai_results.get("east", {}))
        west = _direction_from_ai(ai_results.get("west", {}))

        # Tạo TrafficState với dữ liệu từ AI
        traffic_state = TrafficState(
            north=north,
            south=south,
            east=east,
            west=west,
            temperature=30.0,  # mặc định
            light_intensity=800.0,  # mặc định
        )

        # Chạy decision
        engine = DecisionMaker()
        ns = engine.decide(traffic_state, "NS")
        ew = engine.decide(traffic_state, "EW")

        winner = "NS" if ns["green_duration"] >= ew["green_duration"] else "EW"
        green_duration = ns["green_duration"] if winner == "NS" else ew["green_duration"]

        response = {
            "phase": winner,
            "green_duration": green_duration,
            "ai_results": ai_results,  # thêm kết quả AI
            "details": {
                "NS": {
                    "color": "green" if winner == "NS" else "red",
                    "duration": ns["green_duration"],
                },
                "EW": {
                    "color": "green" if winner == "EW" else "red",
                    "duration": ew["green_duration"],
                },
            },
        }

        return jsonify({"status": "success", "data": response})

    except Exception as exc:
        print("Run decision with images error:", exc)
        return jsonify({"status": "error", "message": str(exc)}), 400


if __name__ == '__main__':
    app.run(debug=True, port=5000)