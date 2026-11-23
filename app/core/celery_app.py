from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "ai_document_intelligence",
    broker=settings.REDIS_URL,
    include=["app.tasks.documents"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
)
