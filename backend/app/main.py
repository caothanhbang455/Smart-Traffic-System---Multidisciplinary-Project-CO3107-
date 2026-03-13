# backend/app.py
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_mqtt import Mqtt
import json
from datetime import datetime

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

if __name__ == '__main__':
    app.run(debug=True, port=5000)