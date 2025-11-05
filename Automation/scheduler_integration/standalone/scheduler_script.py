from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TaskScheduler:
    
    def __init__(self, db_path='scheduler.db', timezone='UTC'):
        jobstores = {
            'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')
        }
        
        self.scheduler = BackgroundScheduler(
            jobstores=jobstores,
            timezone=timezone
        )
        self.timezone = timezone
        
    def start(self):
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler started successfully")
    
    def shutdown(self, wait=True):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            logger.info("Scheduler stopped")
    
    def schedule(self, func, job_id, trigger='interval', **kwargs):
        
        try:
            if self.get_job(job_id):
                self.remove_job(job_id)
            
            job_kwargs = {
                'id': job_id,
                'func': func,
                'replace_existing': True,
                'max_instances': 1,
                'coalesce': True
            }
            
            if 'args' in kwargs:
                job_kwargs['args'] = kwargs.pop('args')
            if 'kwargs_func' in kwargs:
                job_kwargs['kwargs'] = kwargs.pop('kwargs_func')
            
            if trigger == 'interval':
                trigger_obj = IntervalTrigger(
                    seconds=kwargs.get('seconds', 0),
                    minutes=kwargs.get('minutes', 0),
                    hours=kwargs.get('hours', 0),
                    days=kwargs.get('days', 0),
                    weeks=kwargs.get('weeks', 0),
                    timezone=self.timezone
                )
                
            elif trigger == 'daily':
                trigger_obj = CronTrigger(
                    hour=kwargs.get('hour', 0),
                    minute=kwargs.get('minute', 0),
                    timezone=self.timezone
                )
                
            elif trigger == 'weekly':
                trigger_obj = CronTrigger(
                    day_of_week=kwargs.get('day_of_week', 0),
                    hour=kwargs.get('hour', 0),
                    minute=kwargs.get('minute', 0),
                    timezone=self.timezone
                )
                
            elif trigger == 'monthly':
                trigger_obj = CronTrigger(
                    day=kwargs.get('day', 1),
                    hour=kwargs.get('hour', 0),
                    minute=kwargs.get('minute', 0),
                    timezone=self.timezone
                )
                
            elif trigger == 'cron':
                trigger_obj = CronTrigger(
                    minute=kwargs.get('minute', '*'),
                    hour=kwargs.get('hour', '*'),
                    day=kwargs.get('day', '*'),
                    month=kwargs.get('month', '*'),
                    day_of_week=kwargs.get('day_of_week', '*'),
                    timezone=self.timezone
                )
                
            elif trigger == 'date':
                run_date = kwargs.get('run_date', datetime.now() + timedelta(seconds=10))
                trigger_obj = DateTrigger(run_date=run_date, timezone=self.timezone)
                
            else:
                raise ValueError(f"Invalid trigger: {trigger}")
            
            job_kwargs['trigger'] = trigger_obj
            self.scheduler.add_job(**job_kwargs)
            
            logger.info(f"Task '{job_id}' scheduled successfully with trigger '{trigger}'")
            return True
            
        except Exception as e:
            logger.error(f"Error scheduling task '{job_id}': {e}")
            raise
    
    def remove_job(self, job_id):
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Task '{job_id}' removed successfully")
            return True
        except Exception as e:
            logger.error(f"Error removing task '{job_id}': {e}")
            return False
    
    def pause_job(self, job_id):
        try:
            self.scheduler.pause_job(job_id)
            logger.info(f"Task '{job_id}' paused")
            return True
        except Exception as e:
            logger.error(f"Error pausing task '{job_id}': {e}")
            return False
    
    def resume_job(self, job_id):
        try:
            self.scheduler.resume_job(job_id)
            logger.info(f"Task '{job_id}' resumed")
            return True
        except Exception as e:
            logger.error(f"Error resuming task '{job_id}': {e}")
            return False
    
    def get_job(self, job_id):
        return self.scheduler.get_job(job_id)
    
    def get_all_jobs(self):
        return self.scheduler.get_jobs()
