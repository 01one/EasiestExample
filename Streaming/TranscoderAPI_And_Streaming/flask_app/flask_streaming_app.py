import os
import shutil
import requests
import zipfile

from flask import Flask, request, render_template, send_from_directory

app = Flask(__name__)

FASTAPI_URL = "http://127.0.0.1:8000/process/"
DASH_ROOT = os.path.join(os.path.dirname(__file__), "dash")
os.makedirs(DASH_ROOT, exist_ok=True)

def get_media_list():
    media_list = []
    if os.path.exists(DASH_ROOT):
        for item in os.listdir(DASH_ROOT):
            item_path = os.path.join(DASH_ROOT, item)
            if os.path.isdir(item_path):
                manifest_path = os.path.join(item_path, "manifest.mpd")
                if os.path.exists(manifest_path):
                    media_list.append(item)
    return sorted(media_list)

@app.route("/", methods=["GET", "POST"])
def index():
    message = None
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            message = "No file selected"
        else:
            print(f"Processing file: {file.filename}")
            try:
                files = {"file": (file.filename, file.stream, file.mimetype)}
                print("Sending file to FastAPI...")
                r = requests.post(FASTAPI_URL, files=files, stream=True, timeout=300)
                r.raise_for_status()
                
                base_name, _ = os.path.splitext(file.filename)
                dest_dir = os.path.join(DASH_ROOT, base_name)

                if os.path.exists(dest_dir):
                    shutil.rmtree(dest_dir)
                os.makedirs(dest_dir)

                zip_path = os.path.join(DASH_ROOT, f"{base_name}.zip")
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    zip_ref.extractall(dest_dir)
                
                os.remove(zip_path)
                
                manifest_path = os.path.join(dest_dir, "manifest.mpd")
                if os.path.exists(manifest_path):
                    message = f"Successfully uploaded and processed: {file.filename}"
                else:
                    message = "Error: Processing failed - no manifest created"
            except requests.RequestException as e:
                message = f"Error processing file: {e}"
            except Exception as e:
                message = f"Error: {e}"
    
    media_list = get_media_list()
    return render_template("index.html", media_list=media_list, message=message)

@app.route("/watch/<media_name>")
def watch(media_name):
    media_dir = os.path.join(DASH_ROOT, media_name)
    manifest_path = os.path.join(media_dir, "manifest.mpd")
    
    if not os.path.exists(manifest_path):
        return f"Media '{media_name}' not found", 404
    return render_template("watch.html", media_name=media_name)

@app.route("/dash/<media_name>/<path:filename>")
def serve_dash(media_name, filename):
    media_dir = os.path.join(DASH_ROOT, media_name)
    return send_from_directory(media_dir, filename)

if __name__ == "__main__":
    app.run(port=5000, debug=True)