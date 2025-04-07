
# 📷 MQTT Image Publisher for Raspberry Pi

This Python script captures images using a webcam on a Raspberry Pi and publishes them over MQTT to a specified topic. The images are base64-encoded and sent to a local MQTT broker for further processing, such as image analysis or posture detection.

---

## 🧠 Overview

- Captures images using `fswebcam`
- Publishes base64-encoded image data to an MQTT topic
- Organizes sent images into a `received_images` folder
- Tracks the image count with a local counter file
- Includes error logging and MQTT connection handling

---

## 📦 Requirements

### 📌 Python Libraries

- `paho-mqtt`
- `base64`
- `os`, `logging`, `time` (standard libraries)

Install `paho-mqtt` with:

```bash
pip install paho-mqtt
```

### 📷 Webcam Support

Install `fswebcam`:

```bash
sudo apt-get update
sudo apt-get install fswebcam
```

---

## ⚙️ Configuration

Edit these variables in the script to match your setup:

```python
broker = '192.168.1.79'     # IP of your MQTT broker
port = 1883                 # MQTT port
topic = 'images/pi1'        # MQTT topic to publish to
image_counter_file = 'image_counter.txt'
image_directory = './'
processed_folder = 'received_images'
```

To use this script for **other Raspberry Pis**, just change the topic:

```python
topic = 'images/pi2'   # For Pi2
topic = 'images/pi3'   # For Pi3
```

This ensures each Pi sends its images to a unique topic for easy identification by the receiver/server.

---

## 🚀 How to Run

1. Connect a camera to your Raspberry Pi.
2. Make the script executable:

```bash
chmod +x mqtt_image_publisher.py
```

3. Run the script:

```bash
python mqtt_image_publisher.py
```

Stop it with `Ctrl + C`.

---

## 📁 Output

- **Logs:** `image_capture_mqtt.log`  
- **Sent images:** stored in `received_images/` after publishing  
- **Image counter:** saved in `image_counter.txt`

---

## 🔧 Troubleshooting

- Ensure your MQTT broker is running and reachable from the Raspberry Pi.
- Use `mosquitto_sub` or a dashboard like **MQTT Explorer** to monitor incoming messages.
- Check `image_capture_mqtt.log` for detailed error logs.

---

## 👨‍💻 Author

**Muhammad Shahroz Abbas**  
Doctoral Researcher, M3S, University of Oulu

---

## 📜 License

This project is intended for educational and research purposes.
