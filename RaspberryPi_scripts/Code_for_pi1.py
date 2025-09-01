import os
import logging
import paho.mqtt.client as mqtt
import time
import base64
import cv2
import datetime

# Configuration
broker = '192.168.1.79'
port = 1883
topic = 'images/pi1'
image_counter_file = 'image_counter.txt'
image_directory = './'
processed_folder = 'received_images'

# Set up logging
logging.basicConfig(filename='image_capture_mqtt.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s:%(message)s')

# MQTT callbacks
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info(f"Connected to broker {broker}:{port} with result code {rc}")
        print(f"Connected to broker {broker}:{port} with result code {rc}")
    else:
        logging.error(f"Failed to connect to broker {broker}:{port} with result code {rc}")
        print(f"Failed to connect to broker {broker}:{port} with result code {rc}")

def on_publish(client, userdata, mid):
    logging.info(f"Message published with mid {mid}")

# Publish image
def publish_image(client, image_path):
    try:
        with open(image_path, 'rb') as file:
            image_data = base64.b64encode(file.read()).decode()

        result = client.publish(topic, image_data, qos=1)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logging.info(f"Image {image_path} published successfully.")
        else:
            logging.error(f"Failed to publish image {image_path}. Error code: {result.rc}")

        os.makedirs(processed_folder, exist_ok=True)
        os.rename(image_path, os.path.join(processed_folder, os.path.basename(image_path)))

    except Exception as e:
        logging.error(f"Failed to publish image: {e}")

# Get next image number
def get_next_image_number(counter_file):
    try:
        with open(counter_file, 'r') as file:
            number = int(file.read().strip())
    except FileNotFoundError:
        number = 1
    return number

# Update image number
def update_image_number(counter_file, number):
    with open(counter_file, 'w') as file:
        file.write(str(number))

# Main function
def main():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_publish = on_publish

    logging.info(f"Connecting to broker {broker}:{port}")
    try:
        client.connect(broker, port, 60)
    except Exception as e:
        logging.error(f"Connection failed: {e}")
        print(f"Connection failed: {e}")
        return

    client.loop_start()

    # Initialize camera once
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    time.sleep(0.1)  # Allow camera to warm up

    while True:
        try:
            loop_start_time = time.time()

            image_number = get_next_image_number(image_counter_file)
            image_path = os.path.join(image_directory, f"image_{image_number:04d}.jpg")

            # 1. Capture image
            t1 = time.time()
            ret, frame = cap.read()
            if ret:
                cv2.imwrite(image_path, frame)
                logging.info(f"Image captured and saved to {image_path}")
            else:
                logging.error("Failed to read from camera")
            t2 = time.time()
            logging.info(f"Capture time: {t2 - t1:.4f} seconds")

            # 2. Publish image
            t3 = time.time()
            publish_image(client, image_path)
            t4 = time.time()
            logging.info(f"Publish + Move time: {t4 - t3:.4f} seconds")

            # 3. Update counter
            image_number += 1
            update_image_number(image_counter_file, image_number)

            loop_end_time = time.time()
            logging.info(f"Total loop time: {loop_end_time - loop_start_time:.4f} seconds")

            time.sleep(0.5)

        except KeyboardInterrupt:
            logging.info("Keyboard interrupt detected. Stopping the script.")
            break
        except Exception as e:
            logging.error(f"Unexpected error occurred: {e}")
            print(f"Unexpected error occurred: {e}")
            time.sleep(60)

    cap.release()
    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()
     
