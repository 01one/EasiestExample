from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
from scheduler_script import TaskScheduler
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_usage = {}
scheduler = TaskScheduler(db_path='fastapi_limit.db', timezone='UTC')

def reset_daily_limits():
    logger.info("RESETTING daily limits for all users")
    for username in user_usage:
        user_usage[username]['requests_today'] = 0
    logger.info(f" Reset complete. {len(user_usage)} users reset.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    # Schedule daily reset at midnight
    #scheduler.schedule(func=reset_daily_limits,job_id='daily_limit_reset',trigger='daily',hour=0,minute=0)
    
    scheduler.schedule(func=reset_daily_limits, job_id='dynamic_task', trigger='interval', seconds=10) #reset in every 10 seconds
    logger.info("Scheduler started")
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

class APIRequest(BaseModel):
    username: str

@app.post("/api/call")
async def api_call(req: APIRequest):
    username = req.username
    
    if username not in user_usage:
        user_usage[username] = {'requests_today': 0, 'limit': 10}
    
    if user_usage[username]['requests_today'] >= user_usage[username]['limit']:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Daily limit exceeded",
                "limit": user_usage[username]['limit'],
                "used": user_usage[username]['requests_today']
            }
        )
    
    user_usage[username]['requests_today'] += 1
    
    return {
        "message": "API call successful",
        "requests_remaining": user_usage[username]['limit'] - user_usage[username]['requests_today'],
        "used": user_usage[username]['requests_today'],
        "limit": user_usage[username]['limit']
    }

@app.get("/usage")
async def check_usage():
    return user_usage



@app.get("/", response_class=HTMLResponse)
async def index():
    return """
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
"""





if __name__ == '__main__':
    import uvicorn
    logger.info("=" * 60)
    logger.info("FastAPI Scheduler Demo - Daily API Limit Reset")
    logger.info("=" * 60)
    logger.info("POST /api/call  - Make API call (limit: 10/Every_10_Seconds)")
    logger.info("GET  /usage     - Check usage stats")
    logger.info("Limits reset daily at midnight")
    logger.info("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=5000)
