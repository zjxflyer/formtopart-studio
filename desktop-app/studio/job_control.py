"""Cooperative task checkpoints; a pause never blocks an in-flight API stream."""
from functools import wraps
from threading import Event,Lock

from .repository import JobInterrupted


class JobControl:
    def __init__(self,repo,job_id,stopping_event=None):
        self.repo=repo;self.job_id=job_id
        self.stopping_event=stopping_event if stopping_event is not None else Event()
        self.inflight=Event();self._inflight_count=0;self._lock=Lock()

    def check(self):
        while True:
            if self.stopping_event.is_set():
                raise JobInterrupted('Application is stopping; saved design retained / 应用正在停止，已保存设计保留')
            job=self.repo.require_job_active(self.job_id)
            if job['status'] not in ('pausing','paused'):return job
            # Streaming progress invokes the same check. Finish that already
            # dispatched response instead of deadlocking its reader mid-stream.
            if self.inflight.is_set():return job
            if job['status']=='pausing':job=self.repo.pause_at_checkpoint(self.job_id)
            if job['status']!='paused':continue
            self.stopping_event.wait(.25)

    def wrap_request(self,original_request):
        @wraps(original_request)
        def request(*args,**kwargs):
            self.check()
            with self._lock:
                self._inflight_count+=1;self.inflight.set()
            try:return original_request(*args,**kwargs)
            finally:
                with self._lock:
                    self._inflight_count-=1
                    if not self._inflight_count:self.inflight.clear()
        return request
