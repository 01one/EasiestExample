# pip install opencv-python mediapipe pyautogui rich
import argparse
import os
import sys
import threading
import time
import urllib.request
from collections import deque
from contextlib import contextmanager

import cv2
import mediapipe as mp
import pyautogui

try:
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
        TransferSpeedColumn,
    )
except ImportError:
    print("Install 'rich' library: pip install rich")
    sys.exit(1)

console = Console()
STARTUP_START = time.perf_counter()

_BACKEND_NAME_MAP = {
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "any": cv2.CAP_ANY,
}

if sys.platform.startswith("win"):
    CAM_BACKEND = cv2.CAP_DSHOW
    CAM_BACKEND_FALLBACK = cv2.CAP_MSMF
else:
    CAM_BACKEND = cv2.CAP_ANY
    CAM_BACKEND_FALLBACK = cv2.CAP_ANY

BLACK_FRAME_MEAN_THRESHOLD = 10.0

def _frame_looks_black(frame, threshold=BLACK_FRAME_MEAN_THRESHOLD):
    if frame is None:
        return True
    return float(frame.mean()) < threshold

@contextmanager
def timed_step(status_message, done_message=None):
    start = time.perf_counter()
    with console.status(f"[cyan]{status_message}"):
        yield
    elapsed = time.perf_counter() - start
    label = done_message or status_message
    console.print(f"[green]:heavy_check_mark: {label}[/green] [dim]({elapsed:.2f}s)[/dim]")

pyautogui.PAUSE = 0.05
pyautogui.FAILSAFE = False

MODEL_PATH = "hand_landmarker.task"
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"

console.rule("[bold cyan]Hand Gesture Controller")

if not os.path.exists(MODEL_PATH):
    _dl_start = time.perf_counter()
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold yellow]Downloading model..."),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("download", total=None)

        def _report(block_num, block_size, total_size):
            if total_size > 0 and progress.tasks[task].total is None:
                progress.update(task, total=total_size)
            progress.update(task, completed=block_num * block_size)

        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH, reporthook=_report)
    _dl_elapsed = time.perf_counter() - _dl_start
    console.print(f"[green]:heavy_check_mark: Downloaded.[/green] [dim]({_dl_elapsed:.2f}s)[/dim]")
else:
    console.print("[green]:heavy_check_mark: Model found.[/green]")

BaseOptions = mp.tasks.BaseOptions
HandLandmarker = mp.tasks.vision.HandLandmarker
HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
VisionRunningMode = mp.tasks.vision.RunningMode

PALM_IDS = [0, 5, 9, 13, 17]
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]

latest_result = None

def on_result(result, output_image, timestamp_ms):
    global latest_result
    latest_result = result

def list_available_cameras(max_index=10, backend=None):
    backend = CAM_BACKEND if backend is None else backend
    available = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Scanning cameras...", total=max_index)
        for idx in range(max_index):
            progress.update(task, description=f"Checking index {idx}...")
            cap_test = cv2.VideoCapture(idx, backend)
            if cap_test.isOpened():
                ok, frame = cap_test.read()
                if ok and frame is not None:
                    w = int(cap_test.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap_test.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    available.append((idx, w, h))
            cap_test.release()
            progress.advance(task)
    return available

def choose_camera(requested_index=None, max_index=10):
    if requested_index is not None:
        with timed_step(f"Checking camera {requested_index}..."):
            cap_test = cv2.VideoCapture(requested_index, CAM_BACKEND)
            opened = cap_test.isOpened()
            if opened:
                ok, _ = cap_test.read()
                opened = ok
            cap_test.release()
        if not opened:
            console.print(f"[bold red]Error:[/bold red] Camera {requested_index} failed.")
            sys.exit(1)
        return requested_index

    cameras = list_available_cameras(max_index=max_index)
    if not cameras:
        console.print("[bold red]Error: No camera detected.[/bold red]")
        sys.exit(1)
    if len(cameras) == 1:
        return cameras[0][0]

    console.print("[bold]Multiple cameras found:[/bold]")
    for idx, w, h in cameras:
        console.print(f"  [{idx}] {w}x{h}")
    while True:
        choice = console.input("Select camera index: ").strip()
        if choice.isdigit() and int(choice) in [c[0] for c in cameras]:
            return int(choice)

parser = argparse.ArgumentParser()
parser.add_argument("--camera", type=int, default=None)
parser.add_argument("--list-cameras", action="store_true")
parser.add_argument("--width", type=int, default=None)
parser.add_argument("--height", type=int, default=None)
parser.add_argument("--fps", type=int, default=None)
parser.add_argument("--backend", choices=sorted(_BACKEND_NAME_MAP.keys()), default=None)
args = parser.parse_args()

if args.list_cameras:
    found = list_available_cameras()
    if not found:
        console.print("[yellow]No cameras detected.[/yellow]")
    else:
        console.print("[bold]Available cameras:[/bold]")
        for idx, w, h in found:
            console.print(f"  [{idx}] {w}x{h}")
    sys.exit(0)

CAMERA_INDEX = choose_camera(requested_index=args.camera)

options = HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=VisionRunningMode.LIVE_STREAM,
    num_hands=2,
    min_hand_detection_confidence=0.6,
    min_hand_presence_confidence=0.6,
    min_tracking_confidence=0.6,
    result_callback=on_result,
)

EMA_ALPHA = 0.45
WINDOW_SEC = 0.45
MIN_SPAN_SEC = 0.15
STALE_SEC = 0.35
SWIPE_DISTANCE = 0.18
MIN_VELOCITY = 0.55
HORIZONTAL_DOMINANCE = 1.6
COOLDOWN_SEC = 0.9
SWAP_HANDEDNESS = False

class HandState:
    __slots__ = ("buffer", "smoothed_x", "smoothed_y", "last_seen")
    def __init__(self):
        self.buffer = deque()
        self.smoothed_x = None
        self.smoothed_y = None
        self.last_seen = 0.0

hands_state = {"Left": HandState(), "Right": HandState()}
last_trigger_time = 0.0
display_text = ""
display_text_expiry = 0.0
debug_overlay = True
WINDOW_NAME = "Hand Gesture Controller"

def _heartbeat(status_obj, start_time, stop_event, base_msg):
    while not stop_event.is_set():
        elapsed = time.perf_counter() - start_time
        status_obj.update(f"[cyan]{base_msg} — {elapsed:.1f}s elapsed")
        stop_event.wait(0.5)

def initialize_camera(index, backend, max_attempts=3, retry_delay=1.5):
    for attempt in range(1, max_attempts + 1):
        attempt_start = time.perf_counter()
        status_label = f"Initializing camera {index}"

        with console.status(f"[cyan]{status_label}...") as status:
            stop_hb = threading.Event()
            hb_thread = threading.Thread(
                target=_heartbeat, args=(status, attempt_start, stop_hb, status_label), daemon=True
            )
            hb_thread.start()

            cap = cv2.VideoCapture(index, backend)
            if args.width is not None: cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
            if args.height is not None: cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
            if args.fps is not None: cap.set(cv2.CAP_PROP_FPS, args.fps)

            opened = cap.isOpened()
            warmup_frames = 0
            got_usable_frame = False

            if opened:
                warmup_deadline = time.perf_counter() + 3.0
                consecutive_good = 0
                while time.perf_counter() < warmup_deadline:
                    ok, frame = cap.read()
                    if ok:
                        warmup_frames += 1
                        if not _frame_looks_black(frame):
                            consecutive_good += 1
                            if consecutive_good >= 2:
                                got_usable_frame = True
                                break
                        else:
                            consecutive_good = 0
                    if warmup_frames >= 30:
                        break

            stop_hb.set()
            hb_thread.join(timeout=1)

        elapsed = time.perf_counter() - attempt_start
        if opened and warmup_frames > 0 and got_usable_frame:
            return cap, elapsed, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), cap.get(cv2.CAP_PROP_FPS)

        cap.release()
        if attempt < max_attempts:
            time.sleep(retry_delay)

    return None, 0.0, 0, 0, 0.0

if args.backend is not None:
    _backend_plan = [(_BACKEND_NAME_MAP[args.backend], args.backend)]
else:
    _backend_plan = [(CAM_BACKEND, "primary")]
    if CAM_BACKEND_FALLBACK != CAM_BACKEND:
        _backend_plan.append((CAM_BACKEND_FALLBACK, "fallback"))

cap = None
for _backend, _backend_label in _backend_plan:
    cap, _cam_init_elapsed, _actual_w, _actual_h, _actual_fps = initialize_camera(CAMERA_INDEX, backend=_backend)
    if cap is not None:
        break

if cap is None:
    console.print(f"[bold red]Error:[/bold red] Camera {CAMERA_INDEX} failed.")
    sys.exit(1)

console.print(f"[green]:heavy_check_mark: Camera initialized.[/green] [dim]({_actual_w}x{_actual_h} @ {_actual_fps:.0f}fps)[/dim]")

def trigger(direction, frame_w):
    global last_trigger_time, display_text, display_text_expiry
    if direction == "next":
        pyautogui.press("right")
        display_text = "NEXT  [ ---> ]"
    else:
        pyautogui.press("left")
        display_text = "[ <--- ]  PREVIOUS"
    last_trigger_time = time.time()
    display_text_expiry = last_trigger_time + 1.0
    for st in hands_state.values():
        st.buffer.clear()

def cleanup_and_exit(code=0):
    if cap:
        cap.release()
    cv2.destroyAllWindows()
    sys.exit(code)

with console.status("[cyan]Loading hand detection model..."):
    landmarker_cm = HandLandmarker.create_from_options(options)
    landmarker = landmarker_cm.__enter__()

console.rule("[bold green]Ready — launching preview")
cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

try:
    while cap.isOpened():
        success, raw_frame = cap.read()
        if not success:
            continue

        rgb_frame = cv2.cvtColor(raw_frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        frame_timestamp_ms = int(time.time() * 1000)
        landmarker.detect_async(mp_image, frame_timestamp_ms)

        now = time.time()
        h, w, _ = raw_frame.shape
        frame = cv2.flip(raw_frame, 1)
        seen_labels = set()

        if latest_result and latest_result.hand_landmarks and latest_result.handedness:
            for hand_landmarks, handedness in zip(latest_result.hand_landmarks, latest_result.handedness):
                raw_label = handedness[0].category_name
                score = handedness[0].score
                if score < 0.6 or raw_label not in hands_state:
                    continue
                label = {"Left": "Right", "Right": "Left"}[raw_label] if SWAP_HANDEDNESS else raw_label
                seen_labels.add(label)
                st = hands_state[label]

                px = sum(hand_landmarks[i].x for i in PALM_IDS) / len(PALM_IDS)
                py = sum(hand_landmarks[i].y for i in PALM_IDS) / len(PALM_IDS)

                if now - st.last_seen > STALE_SEC:
                    st.buffer.clear()
                    st.smoothed_x, st.smoothed_y = px, py
                st.last_seen = now

                st.smoothed_x = EMA_ALPHA * px + (1 - EMA_ALPHA) * (st.smoothed_x or px)
                st.smoothed_y = EMA_ALPHA * py + (1 - EMA_ALPHA) * (st.smoothed_y or py)
                st.buffer.append((now, st.smoothed_x, st.smoothed_y))
                
                while st.buffer and now - st.buffer[0][0] > WINDOW_SEC:
                    st.buffer.popleft()

                if debug_overlay:
                    pts = [(w - int(lm.x * w), int(lm.y * h)) for lm in hand_landmarks]
                    for a, b in HAND_CONNECTIONS:
                        cv2.line(frame, pts[a], pts[b], (80, 220, 80), 2)
                    for p in pts:
                        cv2.circle(frame, p, 3, (60, 180, 255), -1)

                disp_x = w - int(st.smoothed_x * w)
                disp_y = int(st.smoothed_y * h)
                cv2.circle(frame, (disp_x, disp_y), 9, (0, 0, 255), -1)

                label_color = (0, 200, 255) if label == "Right" else (255, 180, 0)
                cv2.putText(frame, label.upper() + " HAND", (max(0, disp_x - 60), max(20, disp_y - 25)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, label_color, 2, cv2.LINE_AA)

                if now - last_trigger_time > COOLDOWN_SEC and len(st.buffer) >= 2 and (st.buffer[-1][0] - st.buffer[0][0]) >= MIN_SPAN_SEC:
                    t0, x0, y0 = st.buffer[0]
                    t1, x1, y1 = st.buffer[-1]
                    dt = t1 - t0
                    dx = x1 - x0
                    dy = y1 - y0
                    vel = dx / dt if dt > 0 else 0.0

                    if debug_overlay:
                        cv2.putText(frame, f"{label}: dx={dx:+.2f} vel={vel:+.2f}", (10, 30 if label == "Left" else 55), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

                    if abs(dx) > SWIPE_DISTANCE and abs(vel) > MIN_VELOCITY and abs(dx) > HORIZONTAL_DOMINANCE * abs(dy):
                        trigger("next" if label == "Right" else "prev", w)
                        break

        for label, st in hands_state.items():
            if label not in seen_labels and now - st.last_seen > STALE_SEC:
                st.buffer.clear()

        if now < display_text_expiry:
            cv2.putText(frame, display_text, (40, h - 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 0), 3, cv2.LINE_AA)

        cv2.putText(frame, f"q: quit   d: debug overlay   s: swap L/R", (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.imshow(WINDOW_NAME, frame)
        
        key = cv2.waitKey(5) & 0xFF
        if key in (ord("q"), 27):
            cleanup_and_exit(0)
        elif key == ord("d"):
            debug_overlay = not debug_overlay
        elif key == ord("s"):
            SWAP_HANDEDNESS = not SWAP_HANDEDNESS
            for st in hands_state.values():
                st.buffer.clear()

        if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
            cleanup_and_exit(0)
finally:
    landmarker_cm.__exit__(None, None, None)

cleanup_and_exit(0)
