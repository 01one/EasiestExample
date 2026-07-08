from flask import Flask, Response, render_template
import time
import random

app = Flask(__name__)

active_users = []

def update_active_users():
    while True:
        users_count = random.randint(500, 50000)
        current_time = time.strftime('%H:%M:%S')
        active_users.append((current_time, users_count))
        if len(active_users) > 30:
            active_users.pop(0)
        time.sleep(1)


def generate_data():
    for data_point in active_users:
        yield f"data: {data_point[0]},{data_point[1]}\n\n"
        time.sleep(1)


@app.route('/stats')
def stats():
    return Response(generate_data(), mimetype='text/event-stream')

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    import threading
    threading.Thread(target=update_active_users, daemon=True).start()
    app.run(debug=True)
