"""Измерение RSS процесса, включая native-память torch/lxml."""

from threading import Event, Thread
from time import perf_counter


class RuntimeMeasurement:
    """RSS с шагом 10ms; Windows peak_wset дополнительно даёт OS high-water mark."""

    def __enter__(self):
        import psutil

        self.process = psutil.Process()
        self.start = perf_counter()
        self.rss_start = self.process.memory_info().rss
        self.sampled_peak = self.rss_start
        self.stop = Event()
        self.thread = Thread(target=self._sample, daemon=True)
        self.thread.start()
        return self

    def _sample(self):
        while not self.stop.wait(0.01):
            self.sampled_peak = max(self.sampled_peak, self.process.memory_info().rss)

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        info = self.process.memory_info()
        self.result = {
            "seconds": perf_counter() - self.start,
            "rss_start_bytes": self.rss_start,
            "sampled_peak_rss_bytes": max(self.sampled_peak, info.rss),
            "process_peak_rss_bytes": getattr(info, "peak_wset", None),
            "measurement": "psutil RSS every 10ms; peak_wset is lifetime OS peak on Windows",
        }
