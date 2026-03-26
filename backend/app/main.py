# backend/app.py

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_mqtt import Mqtt
import json
import os
from datetime import datetime
from app.services.iot_service import *

from .services.ai_service import AIService
from .services.decision_maker import DecisionMaker
from .models.traffic_state import TrafficState, DirectionState

app = Flask(__name__)
CORS(app)

# ==================== CẤU HÌNH MQTT ====================
app.config['MQTT_BROKER_URL'] = 'test.mosquitto.org'
app.config['MQTT_BROKER_PORT'] = 1883
app.config['MQTT_USERNAME'] = ''
app.config['MQTT_PASSWORD'] = ''
app.config['MQTT_KEEPALIVE'] = 60
app.config['MQTT_TLS_ENABLED'] = False

mqtt = Mqtt(app)

# ==================== SYSTEM PARAMS ====================
SYSTEM_PARAMS_FILE       = os.path.join(os.path.dirname(__file__), "system_params.json")
SYSTEM_PARAMS_AUDIT_FILE = os.path.join(os.path.dirname(__file__), "system_params_audit.log")

DEFAULT_SYSTEM_PARAMS = {
    "alpha": 0.6,
    "beta": 0.4,
    "gamma": 0.2,
    "base_green_time": 10.0,
    "vehicle_weights": {
        "bicycle": 1.0, "motorcycle": 1.0,
        "car": 2.0, "bus": 4.0, "truck": 5.0,
    },
}

# ==================== DỮ LIỆU TẠM ====================
traffic_data = {
    "intersection_1": {"vehicles": 0, "light": "red",   "last_update": ""},
    "intersection_2": {"vehicles": 0, "light": "green", "last_update": ""},
}


# ==================== SYSTEM PARAMETERS MANAGEMENT ====================

def _merge_system_params(raw: dict | None) -> dict:
    """Đọc dict thô, điền giá trị mặc định vào chỗ nào bị thiếu, trả về dict hoàn chỉnh."""
    raw = raw or {}
    weights = raw.get("vehicle_weights", {})
    return {
        "alpha":          float(raw.get("alpha",          DEFAULT_SYSTEM_PARAMS["alpha"])),
        "beta":           float(raw.get("beta",           DEFAULT_SYSTEM_PARAMS["beta"])),
        "gamma":          float(raw.get("gamma",          DEFAULT_SYSTEM_PARAMS["gamma"])),
        "base_green_time": float(raw.get("base_green_time", DEFAULT_SYSTEM_PARAMS["base_green_time"])),
        "vehicle_weights": {
            k: float(weights.get(k, v))
            for k, v in DEFAULT_SYSTEM_PARAMS["vehicle_weights"].items()
        },
    }


def _load_system_params() -> dict:
    """Đọc system_params.json - nếu file không tồn tại thì tạo mới từ DEFAULT."""
    if not os.path.exists(SYSTEM_PARAMS_FILE):
        _save_system_params(DEFAULT_SYSTEM_PARAMS)
        return _merge_system_params(DEFAULT_SYSTEM_PARAMS)
    try:
        with open(SYSTEM_PARAMS_FILE, "r", encoding="utf-8") as f:
            return _merge_system_params(json.load(f))
    except Exception:
        _save_system_params(DEFAULT_SYSTEM_PARAMS)
        return _merge_system_params(DEFAULT_SYSTEM_PARAMS)


def _save_system_params(params: dict) -> dict:
    """Ghi dict params vào system_params.json."""
    merged = _merge_system_params(params)
    with open(SYSTEM_PARAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return merged


def _validate_system_params(params: dict) -> list[str]:
    """Kiểm tra tính hợp lệ - alpha/beta/gamma >= 0,
    base_green_time trong [5, 180], weights trong [0, 20]
    => trả về danh sách lỗi."""
    errors = []
    alpha   = float(params.get("alpha", 0))
    beta    = float(params.get("beta", 0))
    gamma   = float(params.get("gamma", 0))
    base    = float(params.get("base_green_time", 0))
    weights = params.get("vehicle_weights", {})

    if alpha < 0 or beta < 0 or gamma < 0:
        errors.append("alpha, beta, gamma must be >= 0")
    if (alpha + beta + gamma) <= 0:
        errors.append("alpha + beta + gamma must be > 0")
    if not (5 <= base <= 180):
        errors.append("base_green_time must be in range [5, 180] seconds")
    for key in DEFAULT_SYSTEM_PARAMS["vehicle_weights"]:
        v = float(weights.get(key, 0))
        if not (0 <= v <= 20):
            errors.append(f"vehicle_weights.{key} must be in range [0, 20]")
    return errors


def _write_audit(before: dict, after: dict, actor: str) -> None:
    """Ghi log mỗi lần tham số bị thay đổi - lưu vào system_params_audit.log."""
    record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "actor": actor,
        "before": before,
        "after": after,
    }
    with open(SYSTEM_PARAMS_AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ==================== HELPERS ====================

def _build_engine() -> DecisionMaker:
    """Đọc params từ JSON => tạo và trả về 1 instance DecisionMaker mới."""
    params = _load_system_params()
    return DecisionMaker(
        alpha=float(params["alpha"]),
        beta=float(params["beta"]),
        gamma=float(params["gamma"]),
        base_time=float(params["base_green_time"]),
    )


def _direction_from_ai(ai_data: dict) -> DirectionState:
    """Chuyển dict kết quả AI => DirectionState."""
    return DirectionState(
        vehicle_count=ai_data.get("vehicle_count", 0),
        vehicle_breakdown=ai_data.get("vehicle_breakdown", {}),
        weighted_vehicle_score=float(ai_data.get("weighted_vehicle_score", 0.0)),
        density_ratio=float(ai_data.get("density_ratio", 0.0)),
    )


def _publish_light_states(light_states: dict) -> None:
    """Cập nhật traffic_data và gửi lệnh MQTT cho IoT."""
    global traffic_data
    traffic_data["intersection_1"]["light"] = light_states["north"]
    traffic_data["intersection_2"]["light"] = light_states["east"]
    now = datetime.now().strftime("%H:%M:%S")
    traffic_data["intersection_1"]["last_update"] = now
    traffic_data["intersection_2"]["last_update"] = now
    mqtt.publish('traffic/intersection_1/command', json.dumps({"light": light_states["north"]}))
    mqtt.publish('traffic/intersection_2/command', json.dumps({"light": light_states["east"]}))


def _run_decision(traffic_state: TrafficState) -> dict:
    """Chạy DecisionMaker cho cả 2 pha NS và EW => chọn pha thắng => gửi MQTT => trả về response."""
    engine = _build_engine()
    ns = engine.decide(traffic_state, "NS")
    ew = engine.decide(traffic_state, "EW")

    winner       = "NS" if ns["green_duration"] >= ew["green_duration"] else "EW"
    light_states = engine.get_light_states(winner)
    _publish_light_states(light_states)

    return {
        "phase":          winner,
        "green_duration": ns["green_duration"] if winner == "NS" else ew["green_duration"],
        "light_states":   light_states,
        "details": {
            "NS": {"color": "green" if winner == "NS" else "red", "duration": ns["green_duration"]},
            "EW": {"color": "green" if winner == "EW" else "red", "duration": ew["green_duration"]},
        },
    }


# ==================== MQTT CALLBACKS ====================

@mqtt.on_connect()
def handle_connect(client, userdata, flags, rc):
    print("Connected to MQTT!")
    mqtt.subscribe('traffic/#')


@mqtt.on_message()
def handle_mqtt_message(client, userdata, message):
    try:
        data  = json.loads(message.payload.decode())
        inter = data.get("intersection", "intersection_1")
        traffic_data[inter] = {
            "vehicles":    data.get("vehicles", 0),
            "light":       data.get("light", "red"),
            "last_update": datetime.now().strftime("%H:%M:%S"),
        }
    except Exception:
        pass


# ==================== API ROUTES ====================

@app.route('/')
def home():
    return "Smart Traffic System Backend is running!"


@app.route('/api/traffic')
def get_traffic():
    """Trả về trạng thái hiện tại của 2 giao lộ."""
    return jsonify(traffic_data)


@app.route('/api/system_params', methods=['GET', 'PUT'])
def system_params():
    """Đọc hoặc cập nhật tham số hệ thống (alpha, beta, gamma, base_green_time, vehicle_weights)."""
    if request.method == 'GET':
        return jsonify({"status": "success", "data": _load_system_params()})

    current = _load_system_params()
    payload = request.json or {}
    updated = {**current, **payload}  # giữ giá trị cũ nếu không gửi lên

    merged = _merge_system_params(updated)
    errors = _validate_system_params(merged)
    if errors:
        return jsonify({"status": "error", "message": "Invalid parameters", "errors": errors}), 400

    saved = _save_system_params(merged)
    _write_audit(current, saved, request.headers.get("X-Actor", "admin"))
    return jsonify({"status": "success", "data": saved})


@app.route('/api/control', methods=['POST'])
def control_light():
    """[IoT] Thủ công đổi màu đèn 1 giao lộ, gửi lệnh MQTT ngay lập tức."""
    data      = request.json or {}
    inter     = data.get("intersection")
    new_light = data.get("light")

    if inter not in traffic_data:
        return jsonify({"status": "error", "message": "Intersection not found"}), 400

    traffic_data[inter]["light"] = new_light
    mqtt.publish(f'traffic/{inter}/command', json.dumps({"light": new_light}))
    return jsonify({"status": "success", "message": f"Light at {inter} changed to {new_light}"})


@app.route('/api/analyze_images', methods=['POST'])
def analyze_images():
    """Upload 4 ảnh => AI phân tích => trả metrics (không ra quyết định)."""
    for d in ['north', 'south', 'east', 'west']:
        if d not in request.files or request.files[d].filename == '':
            return jsonify({"status": "error", "message": f"Thiếu ảnh hướng {d}"}), 400

    images = {d: request.files[d].read() for d in ['north', 'south', 'east', 'west']}

    try:
        results = AIService().analyze_multiple_images(images)
        return jsonify({"status": "success", "data": results})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route('/api/run_decision_with_images', methods=['POST'])
def run_decision_with_images():
    """
    Luồng chính: Upload 4 ảnh => AI => DecisionMaker => IoT.

        4 ảnh (multipart/form-data: north, south, east, west)
            => AIService.analyze_multiple_images()
            => TrafficState
            => DecisionMaker.decide()
            => MQTT => IoT
    """
    for d in ['north', 'south', 'east', 'west']:
        if d not in request.files or request.files[d].filename == '':
            return jsonify({"status": "error", "message": f"Thiếu ảnh hướng {d}"}), 400

    images = {d: request.files[d].read() for d in ['north', 'south', 'east', 'west']}

    try:
        ai_results = AIService().analyze_multiple_images(images)

        traffic_state = TrafficState(
            north=_direction_from_ai(ai_results.get("north", {})),
            south=_direction_from_ai(ai_results.get("south", {})),
            east =_direction_from_ai(ai_results.get("east",  {})),
            west =_direction_from_ai(ai_results.get("west",  {})),
            temperature=30.0,       # lấy từ cảm biến IoT
            light_intensity=800.0,  # lấy từ cảm biến IoT
        )

        response = _run_decision(traffic_state)
        response["ai_results"] = ai_results
        return jsonify({"status": "success", "data": response})

    except Exception as exc:
        print("run_decision_with_images error:", exc)
        return jsonify({"status": "error", "message": str(exc)}), 400


# @app.route('/api/run_decision', methods=['POST'])
# def run_decision():
#     """
#     Test mode - dùng khi không có camera.
#     Dùng traffic_data hiện có thay vì ảnh thực.
#     """
#     inter1 = traffic_data.get("intersection_1", {})
#     inter2 = traffic_data.get("intersection_2", {})

#     def _mock_direction(vehicles: int) -> DirectionState:
#         return DirectionState(
#             vehicle_count=int(vehicles),
#             vehicle_breakdown={"vehicle": int(vehicles)},
#             weighted_vehicle_score=float(vehicles),
#             density_ratio=min(1.0, float(vehicles) / 40),
#         )

#     try:
#         traffic_state = TrafficState(
#             north=_mock_direction(int(inter1.get("vehicles", 0))),
#             south=_mock_direction(int(inter1.get("vehicles", 0))),
#             east =_mock_direction(int(inter2.get("vehicles", 0))),
#             west =_mock_direction(int(inter2.get("vehicles", 0))),
#             temperature=30.0,
#             light_intensity=800.0,
#         )

#         response = _run_decision(traffic_state)
#         return jsonify({"status": "success", "data": response})

#     except Exception as exc:
#         print("run_decision error:", exc)
#         return jsonify({"status": "error", "message": str(exc)}), 400


if __name__ == '__main__':
    app.run(debug=True, port=5000)