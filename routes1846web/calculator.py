import json
import multiprocessing
import os
import time
import traceback

import redis
from rq import Worker, Queue, Connection, get_current_connection, job as rq_job
from rq.compat import as_text
from rq.utils import enum as rq_enum

from routes1846web.logger import get_logger


listen = ['high', 'default', 'low']
redis_url = os.getenv('REDISTOGO_URL', 'redis://localhost:6379')
redis_conn = redis.from_url(redis_url)

CANCELLED_JOBS_KEY = "rq:jobs:cancelled"
JOB_START_TIMEOUT = 15

LOG = get_logger("routes1846web.calculator")

JobFailedReason = rq_enum(
    "JobFailedReason",
    CANCELLED="cancelled",
    TIMEOUT="timeout"
)

class CancellableWorker(Worker):
    def monitor_work_horse(self, job):
        cancel_loop = multiprocessing.Process(target=self.look_for_cancel, args=(job,))
        cancel_loop.start()

        super().monitor_work_horse(job)

        cancel_loop.join()

        if job.is_cancelled:
            LOG.info(f"Job cancelled: {job.id}")
        elif job.is_timeout:
            LOG.info(f"Job timed out: {job.id}")

    def look_for_cancel(self, job):
        start_time = time.time()
        while not job.is_started:
            time.sleep(0.1)

            if (time.time() - start_time) >= JOB_START_TIMEOUT:
                LOG.error("Job (%s) took too long to start. Terminating...", job.id)
                job.set_failed(JobFailedReason.TIMEOUT)
                self.kill_horse()
                os._exit(1)

        start_time = time.time()
        while job.is_started:
            time.sleep(0.1)

            cancelling_job = self.connection.hget(CANCELLED_JOBS_KEY, job.id)
            self.connection.hdel(CANCELLED_JOBS_KEY, job.id)
            if cancelling_job and cancelling_job.decode("utf-8") == "true":
                LOG.debug("Found cancellation request for job (%s). Terminating...", job.id)
                job.set_failed(JobFailedReason.CANCELLED)
                self.kill_horse()
                os._exit(1)

            if (time.time() - start_time) >= job.timeout:
                LOG.error("Job (%s) took too long to run. Terminating...", job.id)
                job.set_failed(JobFailedReason.TIMEOUT)
                self.kill_horse()
                os._exit(1)

    def handle_job_failure(self, job, *args, **kwargs):
        original_status = job.get_status()

        super().handle_job_failure(job, *args, **kwargs)

        job.set_status(original_status)
        self.failed_job_count -= 1

class CancellableJob(rq_job.Job):
    FAILED_REASON_KEY = "failed_reason"

    @property
    def is_cancelled(self):
        return self.is_failed and self.get_failed_reason() == JobFailedReason.CANCELLED

    @property
    def is_timeout(self):
        return self.is_failed and self.get_failed_reason() == JobFailedReason.TIMEOUT

    def set_failed(self, failed_reason):
        super().set_status(rq_job.JobStatus.FAILED)

        self.connection.hset(self.key, CancellableJob.FAILED_REASON_KEY, failed_reason)

    def get_failed_reason(self):
        return as_text(self.connection.hget(self.key, CancellableJob.FAILED_REASON_KEY))

def handle_exception(job, exc_type, exc_value, tb_obj):
    exc_info_str = json.dumps({
        "message": str(exc_value),
        "traceback": CancellableWorker._get_safe_exception_string(traceback.format_exception(exc_type, exc_value, tb_obj))
    })

    job.failed_job_registry.add(job, exc_string=exc_info_str)

    return False

def start():
    with Connection(redis_conn):
        worker = CancellableWorker(
            map(Queue, listen), exception_handlers=[handle_exception],
            disable_default_exception_handler=True, job_class=CancellableJob)
        worker.work()

def cancel_job(job_id):
    queue = Queue(connection=redis_conn)
    job = queue.fetch_job(job_id)
    if job:
        job.cancel()

        with Connection(redis_conn):
            get_current_connection().hset(CANCELLED_JOBS_KEY, job_id, "true".encode("utf-8"))