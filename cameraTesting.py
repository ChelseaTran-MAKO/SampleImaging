from picamzero import Camera
from datetime import datetime

cam = Camera()

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
cam.take_photo(f"sample_{timestamp}.jpg")
