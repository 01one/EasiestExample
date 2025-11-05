import time
import logging
from datetime import datetime, timedelta
from scheduler_script import TaskScheduler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def daily_report():
    logger.info("EXECUTING: Generating daily report...")

def weekly_cleanup():
    logger.info("EXECUTING: Cleaning up temporary files...")

def frequent_check():
    logger.info("EXECUTING: Checking for new data every 15 seconds...")

def one_time_alert():
    logger.warning("EXECUTING: ALERT! This is a one-time scheduled message!")

def monthly_backup():
    logger.info("EXECUTING: Performing monthly database backup...")

def custom_cron_job():
    logger.info("EXECUTING: Running a custom cron job every minute.")

def dynamic_task_to_manage():
    logger.info("EXECUTING: This is a dynamic task that will be paused and resumed.")


if __name__ == '__main__':
    scheduler = TaskScheduler(db_path='test_scheduler.db', timezone='UTC')

    scheduler.start()
    
    logger.info("--- Scheduling All Initial Tasks ---")
    
    scheduler.schedule(func=daily_report, job_id='daily_report_job', trigger='daily', hour=9, minute=0)
    scheduler.schedule(func=weekly_cleanup, job_id='weekly_cleanup_job', trigger='weekly', day_of_week='sun', hour=2, minute=0)
    scheduler.schedule(func=frequent_check, job_id='frequent_check_job', trigger='interval', seconds=15)
    scheduler.schedule(func=one_time_alert, job_id='one_time_alert_job', trigger='date', run_date=datetime.now() + timedelta(seconds=5))
    scheduler.schedule(func=monthly_backup, job_id='monthly_backup_job', trigger='monthly', day=1, hour=3)
    scheduler.schedule(func=custom_cron_job, job_id='custom_cron_job', trigger='cron', minute='*')
    scheduler.schedule(func=dynamic_task_to_manage, job_id='dynamic_task', trigger='interval', seconds=5)

    logger.info("--- All Jobs Currently Scheduled ---")
    all_jobs = scheduler.get_all_jobs()
    for job in all_jobs:
        logger.info(f"Job ID: {job.id}, Next Run Time: {job.next_run_time}")

    #time.sleep(6) 
    
    #logger.info("--- Pausing 'dynamic_task' for 12 seconds ---")
    #scheduler.pause_job('dynamic_task')
    
    #paused_job = scheduler.get_job('dynamic_task')
    #if paused_job:
    #   logger.info(f"Job '{paused_job.id}' next run time after pausing: {paused_job.next_run_time}")
    
    #time.sleep(12)
    
    #logger.info("--- Resuming 'dynamic_task' ---")
    #scheduler.resume_job('dynamic_task')
    #resumed_job = scheduler.get_job('dynamic_task')
    #if resumed_job:
    #    logger.info(f"Job '{resumed_job.id}' next run time after resuming: {resumed_job.next_run_time}")
    
    #time.sleep(6)

    #logger.info("--- Removing 'frequent_check_job' ---")
    #scheduler.remove_job('frequent_check_job')
    
    job_after_removal = scheduler.get_job('frequent_check_job')
    logger.info(f"Verified that 'frequent_check_job' has been removed: {job_after_removal is None}")
    
    logger.info("--- Final List of Active Jobs ---")
    final_jobs = scheduler.get_all_jobs()
    for job in final_jobs:
        logger.info(f"Job ID: {job.id}, Next Run Time: {job.next_run_time}")

    logger.info("Application is running. Scheduled tasks will execute in the background.")
    logger.info("Press Ctrl+C to exit.")
    
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down scheduler...")
        scheduler.shutdown()
        logger.info("Scheduler has been shut down.")








# --- SCHEDULING EXAMPLES ---

# --- Interval ---
# scheduler.schedule(func=frequent_check, job_id='interval_alt_1', trigger='interval', minutes=5) # Runs every 5 minutes
# scheduler.schedule(func=frequent_check, job_id='interval_alt_2', trigger='interval', hours=1, minutes=30) # Runs every 1 hour and 30 minutes

# --- Daily ---
# scheduler.schedule(func=daily_report, job_id='daily_alt_1', trigger='daily', hour=23, minute=30) # Runs daily at 11:30 PM

# --- Weekly ---
# scheduler.schedule(func=weekly_cleanup, job_id='weekly_alt_1', trigger='weekly', day_of_week='mon-fri', hour=17, minute=0) # Runs every weekday at 5:00 PM

# --- Monthly ---
# scheduler.schedule(func=monthly_backup, job_id='monthly_alt_1', trigger='monthly', day='last', hour=1) # Runs on the last day of the month at 1:00 AM

# --- Date ---
# specific_future_time = datetime(2025, 12, 31, 23, 59, 55) # A specific timestamp for New Year's Eve
# scheduler.schedule(func=one_time_alert, job_id='date_alt_1', trigger='date', run_date=specific_future_time)

# --- Cron (very flexible) ---
# scheduler.schedule(func=custom_cron_job, job_id='cron_alt_1', trigger='cron', hour='*', minute='0,30') # Runs at the top and bottom of every hour (e.g., 1:00, 1:30, 2:00)
# scheduler.schedule(func=custom_cron_job, job_id='cron_alt_2', trigger='cron', day_of_week='sat', hour='12-14') # Runs every hour from 12 PM to 2 PM on Saturdays (i.e., 12:00, 13:00, 14:00)
# scheduler.schedule(func=custom_cron_job, job_id='cron_alt_3', trigger='cron', month='6-8', day_of_week='mon', hour='9') # Runs at 9 AM every Monday during the summer months (June-August)
# scheduler.schedule(func=custom_cron_job, job_id='cron_alt_4', trigger='cron', minute='*/15', hour='8-17', day_of_week='mon-fri') # Runs every 15 minutes during business hours (8 AM - 5 PM) on weekdays
# scheduler.schedule(func=custom_cron_job, job_id='cron_alt_5', trigger='cron', month='1,4,7,10', day='1', hour='0', minute='5') # Runs a "quarterly" job at 5 minutes past midnight on the first day of Jan, Apr, Jul, and Oct
# scheduler.schedule(func=custom_cron_job, job_id='cron_alt_6', trigger='cron', day='1-7', day_of_week='sun', hour='4') # Runs at 4 AM on the first Sunday of every month
# scheduler.schedule(func=custom_cron_job, job_id='cron_alt_7', trigger='cron', hour='0', minute='0', day='15', month='6,12') # Runs a "bi-annual" job at midnight on June 15th and December 15th
