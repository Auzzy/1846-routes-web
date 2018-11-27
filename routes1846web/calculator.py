import os

import redis
from rq import Worker, Queue, Connection

listen = ['high', 'default', 'low']

redis_url = os.getenv('REDISTOGO_URL', 'redis://localhost:6379')

redis_conn = redis.from_url(redis_url)

def start():
    with Connection(redis_conn):
        worker = Worker(map(Queue, listen))
        worker.work()