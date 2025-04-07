# 📸 MQTT Image Publisher for Raspberry Pi

This Python script captures images using a camera connected to a Raspberry Pi and publishes them via MQTT to a specified topic. It is useful for scenarios such as surveillance, posture analysis, or any edge AI application where images need to be sent to a local MQTT broker.

---

## 🧠 How It Works

1. Captures an image using `fswebcam`.
2. Encodes the image to Base64.
3. Publishes the image to a local MQTT topic (`images/pi1` by default).
4. Moves the image to a `received_images` folder after sending.
5. Logs each event and tracks image count using a counter file.

---

## ⚙️ Configuration

Open the script and configure:

```python
broker = '192.168.1.79'  # IP of your local MQTT broker
port = 1883              # Default MQTT port
topic = 'images/pi1'     # Unique topic name per Pi


To use on Pi2, just set:

python
Copy
Edit
topic = 'images/pi2'


For Pi3:

python
Copy
Edit
topic = 'images/pi3'
