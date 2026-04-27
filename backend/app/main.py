# backend\app\main.py

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_mqtt import Mqtt
import json
import os
import time
from datetime import datetime, timezone
from .services.ai_service import AIService
from .services.iot_service import IOTService
from .services.decision_maker import DecisionMaker
from .models.traffic_state import TrafficState, DirectionState

# Database, history service
from .database import init_mongodb, check_mongodb_connection
from .services.history_service import save_sensor_history, get_sensor_collection

app = Flask(__name__)
CORS(app)

# Khởi tạo IOTService và kết nối Adafruit IO
iot_service = IOTService()
iot_service.start()

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
    "base_green_time": 15.0,
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
    """Kiểm tra tính hợp lệ - alpha/beta >= 0,
    base_green_time trong [5, 180], weights trong [0, 20]
    => trả về danh sách lỗi."""
    errors = []
    alpha   = float(params.get("alpha", 0))
    beta    = float(params.get("beta", 0))
    base    = float(params.get("base_green_time", 0))
    weights = params.get("vehicle_weights", {})

    if alpha < 0 or beta < 0:
        errors.append("alpha, beta must be >= 0")
    if (alpha + beta) <= 0:
        errors.append("alpha + beta must be > 0")
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


# Module-level singleton – persists smoothing state across requests.
# Rebuilt when system params change via PUT /api/system_params.
_engine = _build_engine()


def _run_decision(traffic_state : TrafficState) -> dict :
    """
    Run decide() for both phases, publish light states via MQTT,
    and return the response. Both phases always alternate – decide()
    only controls duration, not which phase runs.
    """

    global _engine

    ns_result = _engine.decide(traffic_state, "NS")
    ew_result = _engine.decide(traffic_state, "EW")

    ns_dur = ns_result["green_duration"]
    ew_dur = ew_result["green_duration"]

    # Winner = phase with longer green duration this cycle.
    winner       = "NS" if ns_dur >= ew_dur else "EW"
    light_states = _get_light_states(winner)
    _publish_light_states(light_states)

    return {
        "phase"          : winner,
        "green_duration" : ns_dur if winner == "NS" else ew_dur,
        "light_states"   : light_states,
        "details" : {
            "NS" : {
                "color"    : "green" if winner == "NS" else "red",
                "duration" : ns_dur,
            },
            "EW" : {
                "color"    : "green" if winner == "EW" else "red",
                "duration" : ew_dur,
            },
        },
    }

def _get_light_states(winner_phase: str) -> dict:
    """Trả về trạng thái đèn cho 4 hướng dựa trên pha thắng."""
    if winner_phase == "NS":
        return {"north": "green", "south": "green", "east": "red",   "west": "red"}
    else:
        return {"north": "red",   "south": "red",   "east": "green", "west": "green"}

# ==================== MQTT CALLBACKS ====================

@mqtt.on_connect()
def handle_connect(client, userdata, flags, rc):
    print("Connected to MQTT!")
    mqtt.subscribe('traffic/#')


@mqtt.on_message()
def handle_mqtt_message(client, userdata, message):
    if 'command' in message.topic:
        return
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
    """Đọc hoặc cập nhật tham số hệ thống (alpha, beta, base_green_time, vehicle_weights)."""
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
    
    # Rebuild singleton so new alpha/beta/base_time take effect immediately.
    global _engine
    _engine = _build_engine()

    return jsonify({"status": "success", "data": saved})


@app.route('/api/control', methods=['POST'])
def control_light():
    """[IoT] Thủ công đổi màu đèn 1 giao lộ, gửi lệnh MQTT ngay lập tức."""
    data = request.json or {}
    inter = data.get("intersection")
    new_light = data.get("light")

    if inter not in traffic_data:
        return jsonify({"status": "error", "message": "Intersection not found"}), 400

    traffic_data[inter]["light"] = new_light
    mqtt.publish(f'traffic/{inter}/command', json.dumps({"light": new_light}))
    return jsonify({"status": "success", "message": f"Light at {inter} changed to {new_light}"})


@app.route('/api/analyze_images', methods=['POST'])
def analyze_images():
    """Upload 4 ảnh => AI phân tích => trả metrics (không ra quyết định). Chưa xài trong frontend"""
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

        # Lấy dữ liệu môi trường từ IoT trong thời gian giới hạn.
        # Nếu IoT chưa có dữ liệu, dùng fallback để API không bị treo vô hạn.
        light_value, temperature_value = None, None
        sensor_source = "run_decision_with_images_iot"
        wait_timeout_seconds = 10
        poll_interval_seconds = 1
        started_at = time.time()

        while (time.time() - started_at) < wait_timeout_seconds:
            light_value, temperature_value = iot_service.get_sensor_data()
            if light_value is not None and temperature_value is not None:
                break
            time.sleep(poll_interval_seconds)

        if light_value is None or temperature_value is None:
            sensor_source = "run_decision_with_images_fallback"
            try:
                light_value = float(request.form.get("light_intensity", 0.0))
            except (TypeError, ValueError):
                light_value = 0.0
            try:
                temperature_value = float(request.form.get("temperature", 30.0))
            except (TypeError, ValueError):
                temperature_value = 30.0
            print(
                f"IoT sensor data unavailable after {wait_timeout_seconds}s. "
                f"Using fallback values: light={light_value}, temp={temperature_value}"
            )

        temperature = float(temperature_value)
        light_intensity = float(light_value)
    
        traffic_state = TrafficState(
            north=_direction_from_ai(ai_results.get("north", {})),
            south=_direction_from_ai(ai_results.get("south", {})),
            east =_direction_from_ai(ai_results.get("east",  {})),
            west =_direction_from_ai(ai_results.get("west",  {})),
            temperature = temperature,
            light_intensity = light_intensity,
        )

        # Save sensor history
        sensor_history = None
        try:
            sensor_history = save_sensor_history(
                light_intensity = light_intensity, 
                temperature = temperature, 
                source=sensor_source)
            print("sensor_history saved:", sensor_history)
        except Exception as db_exc:
            print("Error saving sensor history:", db_exc)

        response = _run_decision(traffic_state)
        response["ai_results"] = ai_results
        response["sensor_history"] = sensor_history

        if response['phase'] == "NS":
            states = {
                "A_RED": 1,
                "A_GREEN": 0,
                "B_RED": 1,
                "B_GREEN": 0
            }
        else:
            states = {
                "A_RED": 0,
                "A_GREEN": 1,
                "B_RED": 0,
                "B_GREEN": 1
            }

        iot_service.send_light_states(states)

        # In kết quả ra terminal
        print("\n============================== DECISION RESULT ==============================")
        print(f"Phase winner     : {response['phase']}")
        print(f"Green duration   : {response['green_duration']}s")
        print(f"Light states     : {response['light_states']}")
        print(f"NS duration      : {response['details']['NS']['duration']}s ({response['details']['NS']['color']})")
        print(f"EW duration      : {response['details']['EW']['duration']}s ({response['details']['EW']['color']})")
        print(f"Temperature      : {temperature}°C")
        print(f"Light intensity  : {light_intensity} lux")
        print("--- AI Results per direction ---")
        for direction, result in ai_results.items():
            print(f"  {direction.upper():5s} | vehicles: {result.get('vehicle_count', 0):3d} | "
                  f"weighted_score: {result.get('weighted_vehicle_score', 0):6.1f} | "
                  f"density: {result.get('density_ratio', 0):.3f}")
        print("=============================================================================\n")

        return jsonify({"status": "success", "data": response})

    except Exception as exc:
        print("run_decision_with_images error:", exc)
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route('/api/manual_control', methods=['POST'])
def manual_control():
    """
    Nhận lệnh manual control từ frontend.
    FE gửi trạng thái đèn của 2 intersection.
    Backend chỉ validate + trả response.
    """
    try:
        data = request.get_json()

        override = data.get("override", False)
        intersection_1 = data.get("intersection_1")
        intersection_2 = data.get("intersection_2")

        if intersection_1 not in ["green", "red"] or intersection_2 not in ["green", "red"]:
            return jsonify({
                "status": "error",
                "message": "Invalid light state"
            }), 400

        # Log để bạn debug
        print("\n===== MANUAL CONTROL RECEIVED =====")
        print("Override:", override)
        print("Intersection 1:", intersection_1)
        print("Intersection 2:", intersection_2)
        print("===================================\n")

        # Sau này bạn xử lý IoT tại đây
        response_data = {
            "override": override,
            "intersection_1": intersection_1,
            "intersection_2": intersection_2
        }

        if intersection_1 == 'green':
            states = {
                "A_RED": 1,
                "A_GREEN": 0,
                "B_RED": 1,
                "B_GREEN": 0
            }
        else:
            states = {
                "A_RED": 0,
                "A_GREEN": 1,
                "B_RED": 0,
                "B_GREEN": 1
            }
        iot_service.send_light_states(states)

        return jsonify({
            "status": "success",
            "data": response_data
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


@app.route('/api/sensor_history', methods=['GET'])
def get_sensor_history():
    try:
        limit = request.args.get('limit', default=20, type=int)
        if limit <= 0:
            limit = 20
        if limit > 100:
            limit = 100

        collection = get_sensor_collection()
        docs = list(
            collection.find({})
            .sort("created_at", -1)
            .limit(limit)
        )

        items = []
        for d in docs:
            created_at = d.get("created_at")
            if created_at and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            items.append({
                "id": str(d.get("_id")),
                "light_intensity": float(d.get("light_intensity", 0)),
                "temperature": float(d.get("temperature", 0)),
                "source": d.get("source", "unknown"),
                "created_at": created_at.isoformat() if created_at else None,
            })

        return jsonify({"status": "success", "data": items})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)