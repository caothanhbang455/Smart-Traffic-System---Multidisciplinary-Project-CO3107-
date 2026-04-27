from datetime import datetime, timezone
from app.database import get_sensor_collection


def save_sensor_history(light_intensity: int, temperature: float, source = "iot"):
    """
    INPUT:
        - light_intensity: số (int/float/string có thể convert) → độ sáng
        - temperature: số -> nhiệt độ
        - source: string (mặc định = "iot") → nguồn dữ liệu

    OUTPUT:
        dict {
            "inserted_id": string (id document trong MongoDB),
            "created_at": string (ISO datetime)
        }

    SIDE-EFFECT:
        - Lưu 1 document mới vào MongoDB collection
    """

    # create document
    doc = {
        "light_intensity": float(light_intensity),
        "temperature": float(temperature),
        "source": source,
        "created_at": datetime.now(timezone.utc),
    }


    collection = get_sensor_collection()
    result = collection.insert_one(doc)

    return {
        # ObjectId có thể convert sang string để dễ sử dụng ở frontend
        "inserted_id": str(result.inserted_id),
        #datetime có thể convert sang ISO format để dễ sử dụng ở frontend
        "created_at": doc["created_at"].isoformat(),
    }
