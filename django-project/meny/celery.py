import os

from celery import Celery


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meny.settings')

app = Celery('meny')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
