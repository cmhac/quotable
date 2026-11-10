"""The review app renders one page at a time, because PyMuPDF is not thread-safe (spec 015)."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from quotable.review import sources
from quotable.steps import extract


class Renders:
    """Stands in for ``render_png``: counts renders that overlap, and can fail once."""

    def __init__(self) -> None:
        self.real = extract.render_png
        self.now = self.most = 0
        self.fail_next = False
        self._lock = threading.Lock()

    def __call__(self, page, *rest):
        with self._lock:
            self.now += 1
            self.most = max(self.most, self.now)
        try:
            time.sleep(0.02)  # long enough for the other requests to arrive
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("the library failed")
            return self.real(page, *rest)
        finally:
            with self._lock:
                self.now -= 1


def test_page_requests_six_at_a_time_never_render_at_the_same_time(app, monkeypatch):
    sources.clear_caches()
    renders = Renders()
    monkeypatch.setattr(extract, "render_png", renders)
    run = app.run("senate")
    with ThreadPoolExecutor(6) as pool:  # a browser opens six connections to one host
        answers = list(pool.map(lambda n: app.get(f"{run}/pages/{n % 2 + 1}.png"), range(20)))
    assert [status for status, _, _ in answers] == [200] * 20
    assert all(body.startswith(b"\x89PNG\r\n\x1a\n") for _, _, body in answers)
    assert renders.most == 1


def test_a_failed_render_does_not_block_the_next_one(app, monkeypatch):
    sources.clear_caches()
    renders = Renders()
    renders.fail_next = True
    monkeypatch.setattr(extract, "render_png", renders)
    path = f"{app.run('senate')}/pages/1.png"
    assert "cannot be read" in app.error(path)
    assert app.get(path)[0] == 200
