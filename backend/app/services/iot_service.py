# backend/app/services/iot_service.py
import paho.mqtt.client as mqtt
import json
#from app.config import ADAFRUIT_IO_USERNAME, ADAFRUIT_IO_KEY
# from app.config import *
# Cấu hình các Feed
import os
from pathlib import Path
from dotenv import load_dotenv


env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path)

ADAFRUIT_AIO_USERNAME = os.getenv("ADAFRUIT_AIO_USERNAME")
ADAFRUIT_AIO_KEY = os.getenv("ADAFRUIT_AIO_KEY")

FEED_CONTROL = f"{ADAFRUIT_AIO_USERNAME}/feeds/dadn.light-sensor"
# FEED_CONTROL = f"{ADAFRUIT_AIO_USERNAME}/feeds/dadn.humid-sensor"
FEED_A_RED = f"{ADAFRUIT_AIO_USERNAME}/feeds/dadn.led-1"
FEED_A_GREEN = f"{ADAFRUIT_AIO_USERNAME}/feeds/dadn.led-2"
FEED_B_RED = f"{ADAFRUIT_AIO_USERNAME}/feeds/dadn.led-3"
FEED_B_GREEN = f"{ADAFRUIT_AIO_USERNAME}/feeds/dadn.led-4"


class IOTService:
    def __init__(self):
        self.client = mqtt.Client()
        self.client.username_pw_set(ADAFRUIT_AIO_USERNAME, ADAFRUIT_AIO_KEY)
        
        # Callback khi kết nối thành công
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, rc):
        print(f"Connected to Adafruit IO with result code {rc}")
        # Subscribe để theo dõi trạng thái hiện tại nếu cần
        self.client.subscribe(FEED_CONTROL)

    def on_message(self, client, userdata, msg):
        print(f"Topic: {msg.topic} - Message: {msg.payload.decode()}")

    def start(self):
        self.client.connect("io.adafruit.com", 1883, 60)
        self.client.loop_start()

    def send_traffic_command(self, state):
        """
        Gửi lệnh trạng thái đèn (0, 1, 2, 3) xuống Adafruit
        """
        self.client.publish(FEED_CONTROL, str(state))
        print(f"Sent state {state} to Adafruit IO")
    
    def send_humid_sensor(self, state):
        """
        Gửi lệnh trạng thái đèn (0, 1, 2, 3) xuống Adafruit
        """
        self.client.publish(FEED_CONTROL, str(state))
        print(f"Sent state {state} to Adafruit IO")
    
    def send_light_states(self, states):
        redA, greenA, redB, greenB = states

        self.client.publish(FEED_A_RED, str(redA))
        self.client.publish(FEED_A_GREEN, str(greenA))
        self.client.publish(FEED_B_RED, str(redB))
        self.client.publish(FEED_B_GREEN, str(greenB))

        print("Sent traffic light states:", states)

# Khởi tạo instance
iot_service = IOTService()
# print()

# Giả lập logic từ Decision Maker để bạn test
# def mock_decision_logic(vehicle_count):
#     """
#     Giả lập: Nếu xe > 10 thì bật trạng thái 0 (Đường A xanh), 
#     ngược lại bật trạng thái 2 (Đường B xanh)
#     """
#     if vehicle_count > 10:
#         return 0 # State 0
#     else:
#         return 1 # State 2

def mock_decision_logic(vehicle_a, vehicle_b):
    if vehicle_a > vehicle_b:
        # Road A xanh
        return (0,1,1,0)
    else:
        # Road B xanh
        return (1,0,0,1)
    

# import time

# if __name__ == "__main__":
#     print("username use os",os.getenv("ADAFRUIT_AIO_USERNAME"))
#     print("pass use os",os.getenv("ADAFRUIT_AIO_KEY"))
#     iot_service.start()

#     time.sleep(2)  # chờ MQTT connect

#     vehicle_count = 15
#     state = mock_decision_logic(25, 20)
#     #iot_service.send_humid_sensor(23)

#     iot_service.send_light_states(state)

#     time.sleep(2)  # giữ chương trình sống để nhận message