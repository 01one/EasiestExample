import os
import subprocess
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_apscheduler import APScheduler
from werkzeug.utils import secure_filename
from datetime import datetime
import sqlite3
import secrets
import logging


class Config:
    SCHEDULER_API_ENABLED = True
    SCHEDULER_JOBSTORES = {
        'default': {'type': 'sqlalchemy', 'url': 'sqlite:///instance/scheduler.db'}
    }

    UPLOAD_FOLDER = 'scripts'
    ALLOWED_EXTENSIONS = {'py'}


app = Flask(__name__)
app.config.from_object(Config())
app.secret_key = secrets.token_urlsafe(64)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
if not os.path.exists('instance'):
    os.makedirs('instance')


scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()


ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password"
def is_logged_in():
    return session.get('logged_in')

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def validate_cron_expression(minute, hour, day, month, day_of_week):
    def validate_field(value, min_val, max_val, allow_special=True):
        if value == '*':
            return True
        if allow_special and ('/' in value or ',' in value or '-' in value):
            return True
        try:
            val = int(value)
            return min_val <= val <= max_val
        except ValueError:
            return False
    
    return (validate_field(minute, 0, 59) and
            validate_field(hour, 0, 23) and
            validate_field(day, 1, 31) and
            validate_field(month, 1, 12) and
            validate_field(day_of_week, 0, 6))

def run_script_job(script_name, chain_scripts=None, chain_mode='sequential'):
    with app.app_context():
        def execute_script(script):
            script_path = os.path.join(app.config['UPLOAD_FOLDER'], script)
            log_file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{script}.log")

            logger.info(f"Running script: {script_path}")
            try:
                result = subprocess.run(
                    ['python', script_path],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=300
                )
                output = f"SUCCESS: {script} completed successfully\n{result.stdout}"
                if result.stderr:
                    output += f"\nWARNINGS:\n{result.stderr}"
            except subprocess.CalledProcessError as e:
                output = f"ERROR: Script '{script}' failed with exit code {e.returncode}\nSTDERR:\n{e.stderr}\nSTDOUT:\n{e.stdout}"
                logger.error(f"Script {script} failed: {e}")
            except subprocess.TimeoutExpired:
                output = f"ERROR: Script '{script}' timed out after 5 minutes"
                logger.error(f"Script {script} timed out")
            except FileNotFoundError:
                output = f"ERROR: Script '{script}' not found at path: {script_path}"
                logger.error(f"Script {script} not found")
            except Exception as e:
                output = f"ERROR: Unexpected error running script '{script}': {str(e)}"
                logger.error(f"Unexpected error running {script}: {e}")

            try:
                with open(log_file_path, "a", encoding='utf-8') as log_file:
                    log_file.write(f"--- Execution started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                    log_file.write(output)
                    log_file.write(f"\n--- Execution completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n\n")
            except Exception as e:
                logger.error(f"Failed to write log for {script}: {e}")

        execute_script(script_name)
        
        if chain_scripts:
            if chain_mode == 'parallel':
                import threading
                threads = []
                for script in chain_scripts:
                    thread = threading.Thread(target=execute_script, args=(script,))
                    thread.start()
                    threads.append(thread)
                
                for thread in threads:
                    thread.join()
            else:
                for script in chain_scripts:
                    execute_script(script)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles the login process."""
    if request.method == 'POST':
        if request.form['username'] == ADMIN_USERNAME and request.form['password'] == ADMIN_PASSWORD:
            session['logged_in'] = True
            flash('You were successfully logged in', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('You were logged out', 'success')
    return redirect(url_for('login'))

@app.route('/')
def index():
    if not is_logged_in():
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    if not is_logged_in():
        return redirect(url_for('login'))
    jobs = []
    for job in scheduler.get_jobs():
        job_info = {
            'id': job.id,
            'script': job.args[0] if job.args else 'Unknown',
            'trigger': str(job.trigger),
            'next_run_time': job.next_run_time,
            'chain_scripts': job.args[1] if len(job.args) > 1 and job.args[1] else None,
            'chain_mode': job.args[2] if len(job.args) > 2 else None
        }
        jobs.append(job_info)

    scripts = []
    if os.path.exists(app.config['UPLOAD_FOLDER']):
        for f in os.listdir(app.config['UPLOAD_FOLDER']):
            if f.endswith('.py'):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], f)
                try:
                    file_size = os.path.getsize(file_path)
                    file_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
                    scripts.append({
                        'name': f,
                        'size': file_size,
                        'modified': file_modified
                    })
                except OSError:
                    scripts.append({
                        'name': f,
                        'size': 0,
                        'modified': datetime.now()
                    })

    return render_template('dashboard.html', jobs=jobs, scripts=scripts)

@app.route('/upload', methods=['POST'])
def upload_script():
    if not is_logged_in():
        return redirect(url_for('login'))

    if 'file' not in request.files:
        flash('No file part', 'danger')
        return redirect(url_for('dashboard'))

    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'danger')
        return redirect(url_for('dashboard'))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        if os.path.exists(file_path):
            flash(f'Script "{filename}" already exists and will be overwritten.', 'warning')
        
        try:
            file.save(file_path)
            flash(f'Script "{filename}" uploaded successfully', 'success')
            logger.info(f"Script uploaded: {filename}")
        except Exception as e:
            flash(f'Error uploading script: {str(e)}', 'danger')
            logger.error(f"Error uploading {filename}: {e}")
    else:
        flash('Invalid file type. Only .py files are allowed.', 'danger')

    return redirect(url_for('dashboard'))

@app.route('/schedule', methods=['POST'])
def schedule_job():
    if not is_logged_in():
        return redirect(url_for('login'))

    job_name = request.form.get('job_name', '').strip()
    if not job_name:
        flash('Job name is required.', 'danger')
        return redirect(url_for('dashboard'))
    
    existing_ids = [job.id for job in scheduler.get_jobs()]
    if job_name in existing_ids:
        flash('Job name must be unique. Please choose a different name.', 'danger')
        return redirect(url_for('dashboard'))

    script_name = request.form.get('script_name')
    if not script_name:
        flash('Please select a script to schedule.', 'danger')
        return redirect(url_for('dashboard'))

    schedule_option = request.form.get('schedule_option')
    chain_scripts = request.form.getlist('chain_scripts')
    chain_mode = request.form.get('chain_mode', 'sequential') if chain_scripts else None
    job_id = job_name

    chain_scripts = [s for s in chain_scripts if s and s != script_name]
    chain_scripts = list(dict.fromkeys(chain_scripts))

    cron_settings = {
        'every_5_min':   {'minute': '*/5', 'hour': '*', 'day': '*', 'month': '*', 'day_of_week': '*'},
        'every_15_min':  {'minute': '*/15', 'hour': '*', 'day': '*', 'month': '*', 'day_of_week': '*'},
        'every_30_min':  {'minute': '*/30', 'hour': '*', 'day': '*', 'month': '*', 'day_of_week': '*'},
        'hourly':        {'minute': '0', 'hour': '*', 'day': '*', 'month': '*', 'day_of_week': '*'},
        'every_2_hour':  {'minute': '0', 'hour': '*/2', 'day': '*', 'month': '*', 'day_of_week': '*'},
        'daily':         {'minute': '0', 'hour': '0', 'day': '*', 'month': '*', 'day_of_week': '*'},
        'weekly':        {'minute': '0', 'hour': '0', 'day': '*', 'month': '*', 'day_of_week': '0'},
        'monthly':       {'minute': '0', 'hour': '0', 'day': '1', 'month': '*', 'day_of_week': '*'},
    }

    try:
        if schedule_option == 'daily_time':
            time_str = request.form.get('daily_time', '00:00')
            hour, minute = map(int, time_str.split(':'))
            cron = {'minute': str(minute), 'hour': str(hour), 'day': '*', 'month': '*', 'day_of_week': '*'}
        elif schedule_option == 'multi_time':
            times = request.form.get('multi_times', '').split(',')
            minutes = []
            hours = []
            for t in times:
                t = t.strip()
                if ':' in t:
                    h, m = map(int, t.split(':'))
                    hours.append(str(h))
                    minutes.append(str(m))
            if not minutes or not hours:
                raise ValueError("Invalid time format")
            cron = {'minute': ','.join(minutes), 'hour': ','.join(hours), 'day': '*', 'month': '*', 'day_of_week': '*'}
        elif schedule_option == 'weekly_day_time':
            day_of_week = request.form.get('weekly_day', '0')
            time_str = request.form.get('weekly_time', '00:00')
            hour, minute = map(int, time_str.split(':'))
            cron = {'minute': str(minute), 'hour': str(hour), 'day': '*', 'month': '*', 'day_of_week': day_of_week}
        elif schedule_option == 'monthly_date_time':
            day = request.form.get('monthly_date', '1')
            time_str = request.form.get('monthly_time', '00:00')
            hour, minute = map(int, time_str.split(':'))
            cron = {'minute': str(minute), 'hour': str(hour), 'day': day, 'month': '*', 'day_of_week': '*'}
        elif schedule_option == 'custom':
            cron = {
                'minute': request.form.get('cron_minute', '*').strip(),
                'hour': request.form.get('cron_hour', '*').strip(),
                'day': request.form.get('cron_day', '*').strip(),
                'month': request.form.get('cron_month', '*').strip(),
                'day_of_week': request.form.get('cron_day_of_week', '*').strip(),
            }
            if not validate_cron_expression(cron['minute'], cron['hour'], cron['day'], cron['month'], cron['day_of_week']):
                flash('Invalid cron expression. Please check your values.', 'danger')
                return redirect(url_for('dashboard'))
        else:
            cron = cron_settings.get(schedule_option)
            if not cron:
                flash('Invalid schedule option selected.', 'danger')
                return redirect(url_for('dashboard'))


        scheduler.add_job(
            id=job_id,
            func=run_script_job,
            args=[script_name, chain_scripts if chain_scripts else None, chain_mode],
            trigger='cron',
            minute=cron['minute'],
            hour=cron['hour'],
            day=cron['day'],
            month=cron['month'],
            day_of_week=cron['day_of_week'],
            max_instances=1,
            coalesce=True
        )
        
        flash(f'Job "{job_id}" for script "{script_name}" scheduled successfully!', 'success')
        if chain_scripts:
            chain_info = f"Chain: {' → '.join(chain_scripts)}" if chain_mode == 'sequential' else f"Chain: {' + '.join(chain_scripts)} (parallel)"
            flash(f'{chain_info}', 'info')
        
        logger.info(f"Job scheduled: {job_id} - {script_name} - {cron}")
        
    except ValueError as e:
        flash(f'Invalid input format: {str(e)}', 'danger')
    except Exception as e:
        flash(f'Error scheduling job: {str(e)}', 'danger')
        logger.error(f"Error scheduling job {job_id}: {e}")

    return redirect(url_for('dashboard'))

@app.route('/delete_job/<job_id>')
def delete_job(job_id):
    if not is_logged_in():
        return redirect(url_for('login'))
    try:
        scheduler.remove_job(job_id)
        flash(f'Job "{job_id}" deleted successfully.', 'success')
        logger.info(f"Job deleted: {job_id}")
    except Exception as e:
        flash(f'Error deleting job: {str(e)}', 'danger')
        logger.error(f"Error deleting job {job_id}: {e}")
    return redirect(url_for('dashboard'))

@app.route('/run_now/<script_name>')
def run_now(script_name):
    if not is_logged_in():
        return redirect(url_for('login'))
    
    job_id = f"manual_run_{script_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        scheduler.add_job(
            id=job_id,
            func=run_script_job,
            args=[script_name],
            trigger='date',
            max_instances=1
        )
        flash(f'Script "{script_name}" is running now. Check the logs for results.', 'success')
        logger.info(f"Manual execution started: {script_name}")
    except Exception as e:
        flash(f'Error running script: {str(e)}', 'danger')
        logger.error(f"Error running script {script_name}: {e}")
    return redirect(url_for('dashboard'))

@app.route('/view_log/<script_name>')
def view_log(script_name):
    if not is_logged_in():
        return redirect(url_for('login'))
    
    script_name = secure_filename(script_name)
    log_file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{script_name}.log")
    
    try:
        with open(log_file_path, "r", encoding='utf-8') as f:
            log_content = f.read()
        if not log_content.strip():
            log_content = f"Log file for '{script_name}' is empty. The script hasn't been executed yet or produced no output."
    except FileNotFoundError:
        log_content = f"Log file for '{script_name}' not found. Run the script to generate logs."
    except Exception as e:
        log_content = f"Error reading log file for '{script_name}': {str(e)}"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Log: {script_name}</title>
        <style>
            body {{ font-family: monospace; margin: 20px; background: #f5f5f5; }}
            .header {{ background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
            .log-content {{ background: #1e1e1e; color: #f0f0f0; padding: 20px; border-radius: 8px; overflow-x: auto; }}
            .back-btn {{ background: #007bff; color: white; padding: 10px 15px; text-decoration: none; border-radius: 4px; }}
            .back-btn:hover {{ background: #0056b3; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>📋 Log for: {script_name}</h1>
            <a href="{url_for('dashboard')}" class="back-btn">← Back to Dashboard</a>
        </div>
        <div class="log-content">
            <pre>{log_content}</pre>
        </div>
    </body>
    </html>
    """
    return html_content

@app.route('/delete_script/<script_name>')
def delete_script(script_name):
    if not is_logged_in():
        return redirect(url_for('login'))

    script_name = secure_filename(script_name)
    script_path = os.path.join(app.config['UPLOAD_FOLDER'], script_name)
    log_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{script_name}.log")

    try:
        jobs_removed = 0
        for job in scheduler.get_jobs():
            if (len(job.args) > 0 and job.args[0] == script_name) or \
               (len(job.args) > 1 and job.args[1] and script_name in job.args[1]):
                scheduler.remove_job(job.id)
                jobs_removed += 1

        if jobs_removed > 0:
            flash(f'Removed {jobs_removed} associated job(s).', 'info')

        if os.path.exists(script_path):
            os.remove(script_path)

        if os.path.exists(log_path):
            os.remove(log_path)

        flash(f'Script "{script_name}" and its logs have been deleted successfully.', 'success')
        logger.info(f"Script deleted: {script_name}")
    except Exception as e:
        flash(f'Error deleting script: {str(e)}', 'danger')
        logger.error(f"Error deleting script {script_name}: {e}")

    return redirect(url_for('dashboard'))

@app.route('/validate_cron', methods=['POST'])
def validate_cron():
    if not is_logged_in():
        return jsonify({'valid': False, 'error': 'Not logged in'})
    
    data = request.get_json()
    try:
        minute = data.get('minute', '*')
        hour = data.get('hour', '*')
        day = data.get('day', '*')
        month = data.get('month', '*')
        day_of_week = data.get('day_of_week', '*')
        
        is_valid = validate_cron_expression(minute, hour, day, month, day_of_week)
        
        if is_valid:
            from apscheduler.triggers.cron import CronTrigger
            trigger = CronTrigger(
                minute=minute, hour=hour, day=day, 
                month=month, day_of_week=day_of_week
            )
            next_run = trigger.get_next_fire_time(None, datetime.now())
            return jsonify({
                'valid': True, 
                'next_run': next_run.strftime('%Y-%m-%d %H:%M:%S') if next_run else None
            })
        else:
            return jsonify({'valid': False, 'error': 'Invalid cron expression format'})
    except Exception as e:
        return jsonify({'valid': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
