"""Gunicorn configuration for production."""

import multiprocessing
import os

bind = "0.0.0.0:8000"
workers = int(os.getenv("WORKERS", str(multiprocessing.cpu_count() * 2 + 1)))
worker_class = "uvicorn.workers.UvicornWorker"
accesslog = "-"
errorlog = "-"
