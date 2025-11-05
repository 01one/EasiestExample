from flask import Flask, jsonify, request
from scheduler_script import TaskScheduler
import logging
import atexit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
scheduler = TaskScheduler(db_path='flask_limit.db', timezone='UTC')

user_usage = {}

def reset_daily_limits():
    logger.info("RESETTING daily limits for all users")
    for username in user_usage:
        user_usage[username]['requests_today'] = 0
    logger.info(f" Reset complete. {len(user_usage)} users reset.")

@app.route('/')
def index():
    return '''
    <input id="u" value="username">
    <button onclick="call()">Call</button>
    <button onclick="usage()">Usage</button>
    <pre id="o"></pre>
    <script>
    async function call(){
      let r=await fetch('/api/call',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u.value})});
      o.textContent=JSON.stringify(await r.json(),null,2);
    }
    async function usage(){
      let r=await fetch('/usage');
      o.textContent=JSON.stringify(await r.json(),null,2);
    }
    </script>
    '''


@app.route('/api/call', methods=['POST'])
def api_call():
    username = request.json.get('username')
    if not username:
        return jsonify({"error": "Username required"}), 400
    if username not in user_usage:
        user_usage[username] = {'requests_today': 0, 'limit': 10}
    if user_usage[username]['requests_today'] >= user_usage[username]['limit']:
        return jsonify({
            "error": "Daily limit exceeded",
            "limit": user_usage[username]['limit'],
            "used": user_usage[username]['requests_today']
        }), 429
    user_usage[username]['requests_today'] += 1
    return jsonify({
        "message": "API call successful",
        "requests_remaining": user_usage[username]['limit'] - user_usage[username]['requests_today'],
        "used": user_usage[username]['requests_today'],
        "limit": user_usage[username]['limit']
    })

@app.route('/usage', methods=['GET'])
def check_usage():
    return jsonify(user_usage)


def init_scheduler():
    scheduler.start()
    #scheduler.schedule(func=reset_daily_limits, job_id='daily_limit_reset',trigger='daily',hour=0,minute=0)
    #logger.info("Scheduler started - Daily reset scheduled for midnight")
    scheduler.schedule(func=reset_daily_limits, job_id='dynamic_task', trigger='interval', seconds=10)
    logger.info("Scheduler started - reset scheduled for 10 seconds")



init_scheduler()
atexit.register(lambda: scheduler.shutdown())

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("Flask Scheduler Demo - Daily API Limit Reset")
    logger.info("=" * 60)
    logger.info("POST /api/call  - Make API call (limit: 10/every 10 seconds)")
    logger.info("GET  /usage     - Check usage stats")
    logger.info("Limits reset daily at midnight")
    logger.info("=" * 60)
    app.run(debug=True, use_reloader=False, port=5000)
