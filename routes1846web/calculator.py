import json
import multiprocessing
import os
import signal
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

        print(f"HORSE PID: {self.horse_pid}")

        super().monitor_work_horse(job)

        print("EXIT WORK HORSE")

        cancel_loop.join()

        print("EXIT CANCEL LOOP")

        if job.is_cancelled:
            LOG.info(f"Job cancelled: {job.id}")
        elif job.is_timeout:
            LOG.info(f"Job timed out: {job.id}")

    def _install_signal_handlers(self):
        pass

    def look_for_cancel(self, job):
        start_time = time.time()
        while not job.is_started:
            time.sleep(0.1)

            if (time.time() - start_time) >= JOB_START_TIMEOUT:
                LOG.error("Job (%s) took too long to start. Terminating...", job.id)
                job.set_failed(JobFailedReason.TIMEOUT)
                self.kill_horse(signal.SIGTERM)
                os._exit(1)

        start_time = time.time()
        while job.is_started:
            time.sleep(0.1)

            cancelling_job = self.connection.hget(CANCELLED_JOBS_KEY, job.id)
            self.connection.hdel(CANCELLED_JOBS_KEY, job.id)
            if cancelling_job and cancelling_job.decode("utf-8") == "true":
                LOG.debug("Found cancellation request for job (%s). Terminating...", job.id)
                job.set_failed(JobFailedReason.CANCELLED)
                self.kill_horse(signal.SIGTERM)
                os._exit(1)

            if (time.time() - start_time) >= job.timeout:
                LOG.error("Job (%s) took too long to run. Terminating...", job.id)
                job.set_failed(JobFailedReason.TIMEOUT)
                self.kill_horse(signal.SIGTERM)
                os._exit(1)

        print(f"POLLING EXIT: {job.id}")

    def handle_job_failure(self, job, *args, **kwargs):
        original_status = job.get_status()

        super().handle_job_failure(job, *args, **kwargs)

        job.set_status(original_status)
        self.failed_job_count -= 1

    def handle_exception(self, job, *exc_info):
        if not isinstance(exc_info[0], ConnectionError):
            super().handle_exception(job, *exc_info)

class CancellableJob(rq_job.Job):
    FAILED_REASON_KEY = "failed_reason"

    '''
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._job_exec = None

    @classmethod
    def create(cls, func, *args, **kwargs):
        import concurrent.futures
        job_exec = concurrent.futures.ProcessPoolExecutor()
        def func_in_future(*func_args, **func_kwargs):
            promise = job_exec.submit(func, *func_args, **func_kwargs)
            return promise.result()
        job = super().create(func_in_future, *args, **kwargs)
        job._job_exec = job_exec
        return job
    '''

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
    
    '''
    def _execute(self):
        import concurrent.futures
        with concurrent.futures.ProcessPoolExecutor() as executor:
            self._job_exec = executor
            promise = self._job_exec.submit(self._execute, *self.args, **self.kwargs)
            return promise.result()
    '''

    '''
    def perform(self, *args, **kwargs):
        try:
            return super().perform(*args, **kwargs)
        except ConnectionError:
            print("CONN ERROR JOB")
            print(self.get_failed_reason())
    '''

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
            map(Queue, listen), disable_default_exception_handler=True,
            job_class=CancellableJob, job_monitoring_interval=1)
        worker.work()

def start_job(func, *args, **kwargs):
    queue = Queue(connection=redis_conn, job_class=CancellableJob)
    return queue.enqueue(func, *args, **kwargs)

def cancel_job(job_id):
    queue = Queue(connection=redis_conn, job_class=CancellableJob)
    job = queue.fetch_job(job_id)
    if job:
        job.cancel()
        job.set_failed(JobFailedReason.CANCELLED)

        with Connection(redis_conn):
            get_current_connection().hset(CANCELLED_JOBS_KEY, job_id, "true".encode("utf-8"))
