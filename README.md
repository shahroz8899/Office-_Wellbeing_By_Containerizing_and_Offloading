
# 📦 Office Wellbeing System by Containerizing and Offloading Images from Raspberry Pi

This project implements a complete **edge-to-core image pipeline** for monitoring office posture or wellbeing using **Raspberry Pi devices, MQTT messaging, and Docker-based processing** on a master node (e.g., Jetson Orin or any local server).

It enables:
- Real-time image capture from Raspberry Pis
- Lightweight messaging using MQTT
- Intelligent offloading and containerized image processing
- Organized image storage and extensibility to AI-based posture analysis

---

## 🌐 System Architecture

```text
+-------------------+        +-------------------+         +--------------------+
| Raspberry Pi (piX)| -----> |   MQTT Broker     | <------ |   Jetson Orin or   |
|  - Captures image |        |  (192.168.1.79)   |         |   Master Node      |
|  - Sends via MQTT |        +-------------------+         +--------------------+
|  - Topic: images/piX                                     - Receives all MQTT msgs
|                                                       - Stores images by device
|                                                       - Launches Docker container
|                                                       - Resizes image using Pillow
|                                                       - Logs everything
```

---

## 🧱 Component Breakdown

### 🟩 1. Raspberry Pi – Image Capture & Publish

- Script: `mqtt_image_publisher.py`
- Captures an image every few seconds using `fswebcam`
- Encodes the image using `base64`
- Publishes to topic: `images/pi1`, `images/pi2`, etc.
- Easily extensible for multiple Pis by changing the topic name

📍 **Stored in**: `RaspberryPi_scripts/`

---

### 🟧 2. MQTT Broker – Messaging Backbone

- IP: `192.168.1.79`
- Port: `1883`
- Receives image payloads on `images/#` topics
- Routes to all subscribers, including the master node

🛠 Broker can be [Mosquitto](https://mosquitto.org/), hosted locally or on Jetson.

---

### 🟨 3. Master Node – Image Receiving & Containerized Processing

#### Script: `Image_get_and_containerizing.py`

- Subscribes to all MQTT image topics (`images/#`)
- Skips forwarded messages (e.g., `images/jetson_orin`)
- Saves incoming images to:
  - `received_images/images_from_pi1/pi1.jpg`
- Automatically rebuilds the Docker image (`image-processor`)
- Launches `poll_folders.py` as a subprocess

---

#### Script: `poll_folders.py`

- Continuously monitors the `received_images/` folder
- Detects newly added or updated images
- Launches Docker container to process each image:
  ```bash
  docker run --rm -v /folder:/images image-processor /images/<filename>
  ```

---

#### Script: `process_image.py` (inside Docker)

- Loads the image using Pillow
- Resizes it to `1280x720`
- Saves as `processed_<original>.jpg` inside the same mounted directory

---

### 🐳 Docker Image: `image-processor`

- Built using:
  ```Dockerfile
  FROM python:3.9-slim
  WORKDIR /images
  COPY process_image.py /images/
  RUN pip install pillow
  ENTRYPOINT ["python", "process_image.py"]
  ```

📍 **Stored in**: `docker_image_processor/`

---

## 🔁 Workflow Summary

### 1. Raspberry Pi:
```bash
python3 mqtt_image_publisher.py
```

### 2. Master Node:
```bash
python3 Image_get_and_containerizing.py
```

- Automatically builds Docker image
- Subscribes to MQTT
- Spawns folder poller in background

---

## 📁 Directory Overview

```
Office-_Wellbeing_By_Containerizing_and_Offloading/
├── RaspberryPi_scripts/
│   └── mqtt_image_publisher.py
├── MQTT_server_script/
│   └── mqtt_image_receiver.py (optional for direct storage or Jetson forward)
├── Master_node_script/
│   ├── Image_get_and_containerizing.py
│   ├── poll_folders.py
│   └── docker_image_processor/
│       ├── Dockerfile
│       └── process_image.py
└── received_images/
    ├── images_from_pi1/
    ├── images_from_pi2/
    └── images_from_pi3/
```

---

## 🧪 Testing

### Test MQTT from any device:
```bash
mosquitto_pub -h 192.168.1.79 -t images/pi1 -m "<base64 string>"
```

### View logs:
```bash
cat mqtt_image_receiver.log
```

---

## ✅ Requirements

- Python 3.7+
- Docker Engine (`docker.io`)
- Python packages:
  ```bash
  pip install paho-mqtt pillow
  sudo apt install fswebcam
  ```

---

## 👨‍💻 Author

**Muhammad Shahroz Abbas**  
Doctoral Researcher – M3S, University of Oulu  
Edge AI | Docker | IoT | DevOps

---

## 📜 License

This project is licensed under the MIT License.  
Designed for research, teaching, and smart space experimentation.
```

---

