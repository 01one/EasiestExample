import os
import shutil
import subprocess
import zipfile
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import Response
import asyncio

app = FastAPI()

@app.post("/process/")
async def process_media(file: UploadFile = File(...)):
    temp_dir = tempfile.mkdtemp()
    try:
        print(f"Processing {file.filename} in temporary directory: {temp_dir}")

        input_path = os.path.join(temp_dir, file.filename)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        base_name, _ = os.path.splitext(file.filename)
        dash_dir = os.path.join(temp_dir, "dash_output")
        os.makedirs(dash_dir, exist_ok=True)
        manifest_path = os.path.join(dash_dir, "manifest.mpd")

        has_video = False
        source_height = 0
        try:
            probe_command = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=height",
                "-of", "default=nw=1:nk=1",
                input_path,
            ]
            probe_result = subprocess.run(probe_command, capture_output=True, text=True, check=True)
            if probe_result.stdout.strip():
                has_video = True
                source_height = int(probe_result.stdout.strip())
                print(f"Video detected. Source height: {source_height}p")

        except (subprocess.CalledProcessError, FileNotFoundError):
            print("No video stream found or ffprobe failed. Assuming audio-only.")
            has_video = False

        try:
            if has_video:
                ffmpeg_command = ["ffmpeg", "-y", "-i", input_path]
                
                qualities = [
                    {"height": 360, "width": 640, "bitrate": "800k"},
                    {"height": 720, "width": 1280, "bitrate": "2000k"}
                ]

                video_maps = []
                video_stream_index = 0
                
                for q in qualities:
                    if source_height >= q["height"]:
                        video_maps.extend(["-map", "0:v:0"])
                        ffmpeg_command.extend([
                            f"-c:v:{video_stream_index}", "libx264",
                            f"-b:v:{video_stream_index}", q["bitrate"],
                            f"-s:v:{video_stream_index}", f"{q['width']}x{q['height']}"
                        ])
                        video_stream_index += 1
                
                if not video_maps:
                    q = qualities[0] 
                    video_maps.extend(["-map", "0:v:0"])
                    ffmpeg_command.extend([
                        f"-c:v:0", "libx264",
                        f"-b:v:0", q["bitrate"],
                        f"-s:v:0", f"{q['width']}x{q['height']}"
                    ])
                    print(f"Warning: Source height ({source_height}p) is low. Defaulting to one output stream at {q['height']}p.")

                ffmpeg_command.extend(video_maps)

                ffmpeg_command.extend([
                    "-map", "0:a:0?",
                    "-c:a:0", "aac",
                    "-b:a:0", "128k"
                ])
                
                adaptation_sets = "id=0,streams=v id=1,streams=a"
                ffmpeg_command.extend([
                    "-f", "dash",
                    "-seg_duration", "4",
                    "-use_template", "1",
                    "-use_timeline", "1",
                    "-adaptation_sets", adaptation_sets,
                    "-init_seg_name", "init-stream$RepresentationID$.m4s",
                    "-media_seg_name", "chunk-stream$RepresentationID$-$Number%05d$.m4s",
                    manifest_path,
                ])

            else:
                ffmpeg_command = [
                    "ffmpeg", "-y",
                    "-i", input_path,
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-vn",
                    "-f", "dash",
                    "-seg_duration", "4",
                    "-use_template", "1",
                    "-use_timeline", "1",
                    "-init_seg_name", "init-stream$RepresentationID$.m4s",
                    "-media_seg_name", "chunk-stream$RepresentationID$-$Number%05d$.m4s",
                    manifest_path,
                ]

            print(f"Running FFmpeg command: {' '.join(ffmpeg_command)}")
            result = subprocess.run(ffmpeg_command, capture_output=True, text=True, check=True, cwd=dash_dir)
            print("FFmpeg completed successfully")

            if result.stderr:
                print(f"FFmpeg warnings/info: {result.stderr}")

        except subprocess.CalledProcessError as e:
            print(f"FFmpeg error: {e}")
            print(f"FFmpeg stderr: {e.stderr}")
            print(f"FFmpeg stdout: {e.stdout}")
            raise HTTPException(status_code=500, detail=f"Video processing failed: {e.stderr}")
        
        if not os.path.exists(manifest_path):
            raise HTTPException(status_code=500, detail="Manifest file was not created")
        
        created_files = []
        for root, dirs, files in os.walk(dash_dir):
            for f in files:
                file_path = os.path.join(root, f)
                rel_path = os.path.relpath(file_path, dash_dir)
                created_files.append(rel_path)
        
        print(f"Created DASH files: {created_files}")
        
        if len(created_files) <= 1:
            raise HTTPException(status_code=500, detail="No DASH segments were created")
        
        zip_path = os.path.join(temp_dir, f"{base_name}.zip")
        
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(dash_dir):
                    for f in files:
                        file_to_zip = os.path.join(root, f)
                        arc_path = os.path.relpath(file_to_zip, dash_dir)
                        zipf.write(file_to_zip, arc_path)
            
            print(f"Created zip file: {zip_path} ({os.path.getsize(zip_path)} bytes)")
            
        except Exception as e:
            print(f"Error creating zip: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create zip file: {e}")
        
        with open(zip_path, "rb") as zip_file:
            zip_content = zip_file.read()
        
        print(f"Read {len(zip_content)} bytes from zip file")
        
        return Response(
            content=zip_content,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={base_name}.zip"}
        )
        
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        try:
            shutil.rmtree(temp_dir)
            print(f"Cleaned up temporary directory: {temp_dir}")
        except Exception as e:
            print(f"Error cleaning up temp directory: {e}")

@app.get("/")
async def root():
    return {"message": "DASH Media Processor - POST files to /process/"}

@app.get("/api-status")
async def health():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
        return {"status": "healthy", "ffmpeg": "available"}
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"status": "unhealthy", "ffmpeg": "not available"}

if __name__ == "__main__":
    import uvicorn
    print("Starting DASH Media Processor...")
    print("Send POST requests with media files to http://127.0.0.1:8000/process/")
    uvicorn.run(app, host="127.0.0.1", port=8000)