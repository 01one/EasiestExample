import tornado.ioloop
import tornado.web
from scheduler_script import TaskScheduler
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_usage = {}
scheduler = TaskScheduler(db_path='tornado_limit.db', timezone='UTC')

def reset_daily_limits():
    logger.info("RESETTING daily limits for all users")
    for username in user_usage:
        user_usage[username]['requests_today'] = 0
    logger.info(f" Reset complete. {len(user_usage)} users reset.")


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.write('''
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
''')


class APICallHandler(tornado.web.RequestHandler):    
    def post(self):
        data = json.loads(self.request.body)
        username = data.get('username')
        
        if not username:
            self.set_status(400)
            self.write({"error": "Username required"})
            return
        
        if username not in user_usage:
            user_usage[username] = {'requests_today': 0, 'limit': 10}
        
        # Check limit
        if user_usage[username]['requests_today'] >= user_usage[username]['limit']:
            self.set_status(429)
            self.write({
                "error": "Daily limit exceeded",
                "limit": user_usage[username]['limit'],
                "used": user_usage[username]['requests_today']
            })
            return
        
        # Increment usage
        user_usage[username]['requests_today'] += 1
        
        self.write({
            "message": "API call successful",
            "requests_remaining": user_usage[username]['limit'] - user_usage[username]['requests_today'],
            "used": user_usage[username]['requests_today'],
            "limit": user_usage[username]['limit']
        })

class UsageHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(user_usage)

def make_app():
    return tornado.web.Application([
		(r"/", MainHandler),
        (r"/api/call", APICallHandler),
        (r"/usage", UsageHandler),
    ])

if __name__ == "__main__":
    app = make_app()
    scheduler.start()
    
    #scheduler.schedule(func=reset_daily_limits,job_id='daily_limit_reset',trigger='daily',hour=0,minute=0) #reset every day
    scheduler.schedule(func=reset_daily_limits, job_id='dynamic_task', trigger='interval', seconds=10) #reset in every 10 seconds
    
    logger.info("=" * 60)
    logger.info("Tornado Scheduler Demo - Daily API Limit Reset")
    logger.info("=" * 60)
    logger.info("POST /api/call  - Make API call (limit: 10/Every_10_seconds)")
    logger.info("GET  /usage     - Check usage stats")
    logger.info("Server running on http://localhost:5000")
    logger.info("=" * 60)
    
    app.listen(5000)
    
    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info("Scheduler shut down")
