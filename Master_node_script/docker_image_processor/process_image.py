from PIL import Image
import os

def process_image(image_path):
    try:
        img = Image.open(image_path)
        img = img.resize((1280, 720))
        # Extract the filename from the image path and create the new filename
        filename = os.path.basename(image_path)
        new_filename = f"processed_{filename}"
        save_path = os.path.join("/images", new_filename)
        # Save the processed image back to the same directory as the original
        img.save(save_path)
        print(f"Processed {image_path} and saved as {save_path}")
    except Exception as e:
        print(f"Error processing {image_path}: {e}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: process_image.py <image_path>")
        sys.exit(1)
    process_image(sys.argv[1])

