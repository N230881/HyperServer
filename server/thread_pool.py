"""
thread_pool.py
---------------
A hand-rolled thread pool (no concurrent.futures) so the DSA mapping
(Queue + worker threads + synchronization) is explicit and visible,
exactly as described in the handbook.
"""

import threading
import queue
import time


class ThreadPool:
    """
    A fixed-size pool of worker threads that pull jobs off a shared
    thread-safe Queue. This is the classic producer/consumer pattern.

    - Producer: the socket listener, which pushes (conn, addr) tuples
    - Consumers: N worker threads that pop jobs and execute a handler
    """

    def __init__(self, num_threads: int, handler_fn):
        self.num_threads = num_threads
        self.handler_fn = handler_fn
        self.job_queue: "queue.Queue" = queue.Queue()
        self.workers = []
        self._shutdown = threading.Event()

        # stats, protected by a lock since multiple threads mutate them
        self._stats_lock = threading.Lock()
        self.active_workers = 0
        self.total_jobs_processed = 0
        self.total_wait_time = 0.0

        for i in range(num_threads):
            t = threading.Thread(target=self._worker_loop, name=f"Worker-{i}", daemon=True)
            self.workers.append(t)
            t.start()

    def _worker_loop(self):
        while not self._shutdown.is_set():
            try:
                job, enqueued_at = self.job_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            wait_time = time.time() - enqueued_at
            with self._stats_lock:
                self.active_workers += 1
                self.total_wait_time += wait_time

            try:
                self.handler_fn(*job)
            except Exception as exc:  # never let a worker die silently
                print(f"[ThreadPool] worker error: {exc}")
            finally:
                with self._stats_lock:
                    self.active_workers -= 1
                    self.total_jobs_processed += 1
                self.job_queue.task_done()

    def submit(self, *job_args):
        """Enqueue a job (e.g. a client connection) for a worker to process."""
        self.job_queue.put((job_args, time.time()))

    def stats(self):
        with self._stats_lock:
            return {
                "num_threads": self.num_threads,
                "active_workers": self.active_workers,
                "queue_size": self.job_queue.qsize(),
                "total_jobs_processed": self.total_jobs_processed,
                "avg_wait_time_ms": round(
                    (self.total_wait_time / self.total_jobs_processed) * 1000, 3
                )
                if self.total_jobs_processed
                else 0.0,
            }

    def shutdown(self):
        self._shutdown.set()
        for t in self.workers:
            t.join(timeout=1)
