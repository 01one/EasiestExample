import os
import shutil
import requests
import zipfile
from flask import Flask, request, render_template_string, send_from_directory

app = Flask(__name__)

FASTAPI_URL = "http://127.0.0.1:8000/process/"

# DASH storage folder
DASH_ROOT = os.path.join(os.path.dirname(__file__), "dash")
os.makedirs(DASH_ROOT, exist_ok=True)


HTML_INDEX = """
<!doctype html>
<title>Media Library</title>
<h1>Upload New Media</h1>
<form method=post enctype=multipart/form-data>
  <input type=file name=file accept="video/*,audio/*">
  <input type=submit value=Upload>
</form>
<hr>
<h2>Available Media</h2>
<ul>
{% for media in media_list %}
  <li>{{ media }} – <a href="/watch/{{ media }}">Watch</a></li>
{% endfor %}
</ul>
"""

HTML_WATCH = """
<!doctype html>
<title>Watch {{ media_name }}</title>
<h1>{{ media_name }}</h1>
<video id="videoPlayer" controls width="720" height="405"></video>
<div id="qualityControls" style="padding-top: 10px;">
    <label for="qualitySelector">Quality:</label>
    <select id="qualitySelector" style="display: none;"></select>
</div>
<!-- 
  FIX 1: Use a specific, stable version of dash.js instead of 'latest' 
  to prevent breaking changes. 
-->
<script src="https://cdn.dashjs.org/v4.7.4/dash.all.min.js"></script>
<script>
    var url = "/dash/{{ media_name }}/manifest.mpd";
    var video = document.getElementById("videoPlayer");
    var player = dashjs.MediaPlayer().create();
    
    player.on(dashjs.MediaPlayer.events.ERROR, function(e) {
        console.error('DASH Player Error:', e);
    });
    
    /*
      FIX 2: Use the STREAM_INITIALIZED event. This ensures that the
      stream and all its quality levels are ready and parsed.
    */
    player.on(dashjs.MediaPlayer.events.STREAM_INITIALIZED, function () {
        console.log('Stream initialized.');
        const qualitySelector = document.getElementById('qualitySelector');

        /*
          FIX 3: Use player.getBitrateInfoListFor('video') which is the correct
          and modern way to get the list of available qualities.
        */
        const bitrates = player.getBitrateInfoListFor('video');
        
        // Only show the selector if there are multiple quality options
        if (bitrates && bitrates.length > 1) {
            qualitySelector.style.display = 'inline-block';
            
            // Add Auto option (default behavior)
            const autoOption = document.createElement('option');
            autoOption.value = -1; // Use a value to indicate 'auto'
            autoOption.innerText = 'Auto (default)';
            qualitySelector.appendChild(autoOption);

            // Populate with available quality levels
            bitrates.forEach((bitrate, index) => {
                const option = document.createElement('option');
                option.value = index;
                // Display the height and bitrate for clarity
                option.innerText = `${bitrate.height}p (${(bitrate.bitrate / 1000).toFixed(0)} kbps)`;
                qualitySelector.appendChild(option);
            });

            // Listen for user selection
            qualitySelector.addEventListener('change', function() {
                const selectedQualityIndex = parseInt(this.value);
                
                if (selectedQualityIndex === -1) {
                    // Re-enable adaptive bitrate switching for "Auto"
                    console.log('Setting quality to AUTO');
                    player.updateSettings({
                        'streaming': { 'abr': { 'autoSwitchBitrate': { 'video': true } } }
                    });
                } else {
                    // Disable adaptive bitrate and set a specific quality
                    console.log(`Setting quality to index: ${selectedQualityIndex}`);
                    player.updateSettings({
                        'streaming': { 'abr': { 'autoSwitchBitrate': { 'video': false } } }
                    });
                    player.setQualityFor('video', selectedQualityIndex, true);
                }
            });
        }
    });
    
    player.initialize(video, url, true);
</script>
<br>
<a href="/">Back to Library</a>
"""

def get_media_list():
    media_list = []
    if os.path.exists(DASH_ROOT):
        for item in os.listdir(DASH_ROOT):
            item_path = os.path.join(DASH_ROOT, item)
            # Check if it's a directory and contains manifest.mpd
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
                    print(f"Removing existing directory: {dest_dir}")
                    shutil.rmtree(dest_dir)
                os.makedirs(dest_dir)

                zip_path = os.path.join(DASH_ROOT, f"{base_name}.zip")
                print(f"Saving zip to: {zip_path}")
                
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

                print(f"Extracting zip to: {dest_dir}")
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    zip_ref.extractall(dest_dir)
                    print(f"Extracted files: {zip_ref.namelist()}")

                os.remove(zip_path)
                
                manifest_path = os.path.join(dest_dir, "manifest.mpd")
                if os.path.exists(manifest_path):
                    print(f"✓ Successfully processed: {base_name}")
                    message = f"Successfully uploaded and processed: {file.filename}"
                else:
                    print(f"✗ ERROR: Manifest not found at {manifest_path}")
                    message = "Error: Processing failed - no manifest created"
                
            except requests.RequestException as e:
                print(f"Error communicating with FastAPI: {e}")
                message = f"Error processing file: {e}"
            except Exception as e:
                print(f"Unexpected error: {e}")
                message = f"Error: {e}"
    
    media_list = get_media_list()
    return render_template_string(HTML_INDEX, media_list=media_list, message=message)

@app.route("/watch/<media_name>")
def watch(media_name):
    media_dir = os.path.join(DASH_ROOT, media_name)
    manifest_path = os.path.join(media_dir, "manifest.mpd")
    
    if not os.path.exists(manifest_path):
        return f"Media '{media_name}' not found", 404
    
    return render_template_string(HTML_WATCH, media_name=media_name)

@app.route("/dash/<media_name>/<path:filename>")
def serve_dash(media_name, filename):
    media_dir = os.path.join(DASH_ROOT, media_name)
    file_path = os.path.join(media_dir, filename)
    
    print(f"Serving: {filename} from {media_name}")
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        if os.path.exists(media_dir):
            available_files = os.listdir(media_dir)
            print(f"Available files in {media_name}: {available_files}")
        return f"File not found: {filename}", 404
    
    response = send_from_directory(media_dir, filename)
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Range'
    
    return response

@app.route("/debug")
def debug():
    """Debug route to see what's in the DASH directory"""
    debug_info = []
    
    if os.path.exists(DASH_ROOT):
        for item in os.listdir(DASH_ROOT):
            item_path = os.path.join(DASH_ROOT, item)
            if os.path.isdir(item_path):
                files = os.listdir(item_path)
                debug_info.append(f"{item}/: {files}")
    
    return f"<h2>Debug Info</h2><pre>{'<br>'.join(debug_info) if debug_info else 'No media directories found'}</pre><a href='/'>Back</a>"

if __name__ == "__main__":
    app.run(port=5000, debug=True)