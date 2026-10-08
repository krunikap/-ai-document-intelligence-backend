from celery import Celery

from myproject.config import REDIS_URL

celery_app = Celery(
    "ai_document_intelligence",
    broker=REDIS_URL,
    include=["myproject.tasks.documents"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
)
