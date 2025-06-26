import os
from celery import Celery

# set default Django settings module for 'celery' 
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'esim_project.settings')

app = Celery('esim_project')

# read broker & backend from Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# auto-discover tasks.py in installed apps
app.autodiscover_tasks()
