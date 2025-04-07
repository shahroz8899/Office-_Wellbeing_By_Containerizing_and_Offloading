import os
import time
import subprocess

# Define the parent folder where images are located
BASE_DIR = "/home/shahroz/Project2.0/received_images"

# Poll every 1 second
POLLING_INTERVAL = 5

def process_image_with_docker(image_path, image_name):
    try:
        # Build the command to run the docker container to process the image
        command = [
            "docker", "run", "--rm",
            "-v", f"{os.path.dirname(image_path)}:/images",
            "image-processor",
            f"/images/{image_name}"
        ]
        # Run the command
        subprocess.run(command, check=True)
        print(f"Processed {image_path}")
    except subprocess.CalledProcessError as e:
        print(f"Error processing {image_path}: {e}")

def poll_folders():
    processed_images = {}

    while True:
        # Scan all folders within the base directory
        for folder in os.listdir(BASE_DIR):
            folder_path = os.path.join(BASE_DIR, folder)
            if os.path.isdir(folder_path):
                # Check for new or modified images in each folder
                for image_name in os.listdir(folder_path):
                    if image_name.endswith(".jpg") and not image_name.startswith("processed_"):
                        image_path = os.path.join(folder_path, image_name)
                        last_modified_time = os.path.getmtime(image_path)

                        # Check if the image is new or has been modified
                        if (image_path not in processed_images) or (processed_images[image_path] != last_modified_time):
                            # Process the image using Docker
                            process_image_with_docker(image_path, image_name)
                            # Update the last modified time in the processed_images dictionary
                            processed_images[image_path] = last_modified_time

        # Wait before polling again
        time.sleep(POLLING_INTERVAL)

if __name__ == "__main__":
    poll_folders()
