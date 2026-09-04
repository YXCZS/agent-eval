from celery import Celery  # type: ignore[import-untyped]

from agent_eval_api.settings import get_settings

settings = get_settings()
celery_app = Celery("agent_eval", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_default_queue="evaluation",
    worker_concurrency=settings.worker_max_concurrency,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)
