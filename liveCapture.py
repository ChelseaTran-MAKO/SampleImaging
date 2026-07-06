import io
import os
import json
import socketserver
from http import server
from threading import Condition
from datetime import datetime

from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

# Where captured stills land on the Pi. You move these to the Mako Drive
# by hand later. Created automatically if it doesn't exist.
SAVE_DIR = os.path.expanduser("~/captures")

PAGE = """\
<html>
<head><title>SIS Live View</title></head>
<body style="margin:0;background:#000;color:#eee;font-family:sans-serif;text-align:center;">
<img src="stream.mjpg" width="640" height="360" style="display:block;margin:0 auto;" />
<div style="padding:12px;">
  <button id="cap" onclick="capture()"
          style="font-size:18px;padding:10px 28px;cursor:pointer;">Capture</button>
  <div id="status" style="margin-top:10px;min-height:1.2em;"></div>
</div>
<script>
async function capture() {
  const s = document.getElementById('status');
  const b = document.getElementById('cap');
  b.disabled = true; s.textContent = 'Capturing…';
  try {
    const r = await fetch('/capture');
    const j = await r.json();
    s.textContent = j.ok ? ('Saved: ' + j.file) : ('Error: ' + j.error);
  } catch (e) {
    s.textContent = 'Error: ' + e;
  }
  b.disabled = false;
}
</script>
</body>
</html>
"""


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


def capture_still():
    """Grab the current high-res 'main' frame and save it, timestamped.
    The low-res preview stream keeps running throughout."""
    os.makedirs(SAVE_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"SIS_{timestamp}.jpg"
    filepath = os.path.join(SAVE_DIR, filename)
    request = picam2.capture_request()
    try:
        request.save("main", filepath)   # saves the full-res main stream
    finally:
        request.release()                # always release, or the camera stalls
    print(f"Captured {filepath}")
    return filename


class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/capture':
            try:
                filename = capture_still()
                body = json.dumps({"ok": True, "file": filename}).encode('utf-8')
                self.send_response(200)
            except Exception as e:
                body = json.dumps({"ok": False, "error": str(e)}).encode('utf-8')
                self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Content-Type',
                             'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception:
                pass  # client disconnected
        else:
            self.send_error(404)
            self.end_headers()


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


picam2 = Picamera2()
# Two streams at once:
#   main  = high-res, full field of view -> what a Capture saves
#   lores = small, cheap -> what streams to your browser
config = picam2.create_video_configuration(
    main={"size": (2304, 1296)},
    lores={"size": (640, 360), "format": "YUV420"},
    display=None,
)
picam2.configure(config)
output = StreamingOutput()
# Encode the lores stream for the browser; main is left free for stills.
picam2.start_recording(MJPEGEncoder(), FileOutput(output), name="lores")

try:
    print("Streaming on port 8000. Ctrl+C to stop.")
    address = ('', 8000)
    server_obj = StreamingServer(address, StreamingHandler)
    server_obj.serve_forever()
finally:
    picam2.stop_recording()
