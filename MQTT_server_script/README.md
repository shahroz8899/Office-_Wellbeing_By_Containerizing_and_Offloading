
# 📡 MQTT Image Receiver & Forwarder (Jetson Orin Integration)

This Python script listens to MQTT topics from multiple Raspberry Pi devices (`pi1`, `pi2`, `pi3`), receives base64-encoded image data, saves them into device-specific folders, and then **forwards each image to a Jetson Orin** via another MQTT topic. It acts as a central message router and pre-processor in a distributed containerized AI pipeline.

---

## 🧠 Key Features

- ✅ Subscribes to image topics from `pi1`, `pi2`, and `pi3`
- ✅ Saves incoming images in organized, device-specific folders
- ✅ Forwards every image to Jetson Orin using an MQTT topic
- ✅ Maintains proper image naming with counters per device
- ✅ Uses `base64` encoding for MQTT-safe image transmission
- ✅ Logs all events and errors into `logs/image_receiver.log`

---

## 🧰 Folder Structure

By default, received images are saved into:

```
./images_from_pi1/
./images_from_pi2/
./images_from_pi3/
```

Each image is named like:  
`p1_01.jpg`, `p2_03.jpg`, etc., based on device and sequence.

Logs are written to:  
```
logs/image_receiver.log
```

---

## ⚙️ Configuration

You can modify these settings at the top of the script:

```python
broker = 'localhost'  # IP or hostname of MQTT broker (Jetson Orin)
port = 1883           # MQTT port
image_topic_pi1 = 'images/pi1'
image_topic_pi2 = 'images/pi2'
image_topic_pi3 = 'images/pi3'
image_publish_topic_jetson = 'images/jetson_orin'
```

Make sure the IP address of the broker is accessible from where the script is running.

---

## 📦 Dependencies

Make sure you have the following Python packages:

```bash
pip install paho-mqtt
```

This script also uses built-in libraries:
- `os`
- `logging`
- `base64`
- `warnings`

---

## 🚀 How to Run

1. **Ensure your MQTT broker is running** (e.g., `mosquitto` on Jetson Orin)
2. Start the script:

```bash
python mqtt_image_receiver.py
```

3. It will begin listening for images from the Pi devices and forwarding them to Jetson Orin.

---

## 🔁 Workflow Diagram

```text
+-------------+        +-------------------------+        +--------------+
| RaspberryPi | -----> | MQTT Receiver (This Script) | --> | Jetson Orin |
|    (pi1)    |        |    (Image Forwarder)    |        |    (AI/ML)   |
+-------------+        +-------------------------+        +--------------+
                            |      |      |
                            |      |      +---> ./images_from_pi3/
                            |      +----------> ./images_from_pi2/
                            +-----------------> ./images_from_pi1/
```

---

## 🧪 Testing Tips

- Use [MQTT Explorer](https://mqtt-explorer.com/) to visualize published and received messages
- Simulate image sending using `mosquitto_pub` with base64-encoded image strings
- Monitor `logs/image_receiver.log` to debug or trace errors

---

## 🧑‍💻 Author

**Muhammad Shahroz Abbas**  
Doctoral Researcher – M3S, University of Oulu  
Specializing in Edge AI, DevOps, and Container-based IoT Architectures

---

## 📜 License

This code is intended for research and academic purposes in intelligent containerized edge computing environments.
