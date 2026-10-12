#!/usr/bin/env python3
"""Faithful mobile-touch regression QA for CineQueue swipe triage.

Uses Chromium CDP Input.dispatchTouchEvent against a temporary data copy. This
exercises browser touch-action arbitration and implicit capture; direct
`dispatchEvent(new PointerEvent(...))` does not. Requires Playwright Chromium.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    import pytest
    pytest.skip("Playwright is unavailable; run this gate in the configured browser venv", allow_module_level=True)

ROOT = Path(__file__).resolve().parents[1]
PORT = 8914
BASE = f"http://127.0.0.1:{PORT}/cq-touch/"


def wait_server():
    for _ in range(80):
        try:
            urllib.request.urlopen(BASE, timeout=1)
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("temporary CineQueue server did not start")


def touch_drag(page, cdp, dx, dy, steps=12, step_ms=30):
    row = page.locator(".movie").first
    row.scroll_into_view_if_needed()
    box = row.bounding_box()
    if not box:
        raise AssertionError("first list row has no box")
    x0 = box["x"] + box["width"] * 0.5
    y0 = box["y"] + box["height"] * 0.5

    def point(x, y):
        return {
            "x": x, "y": y, "radiusX": 1, "radiusY": 1,
            "rotationAngle": 0, "force": 0.8, "id": 1,
        }

    cdp.send("Input.dispatchTouchEvent", {
        "type": "touchStart", "touchPoints": [point(x0, y0)],
    })
    page.wait_for_timeout(step_ms)
    samples = []
    for i in range(1, steps + 1):
        x = x0 + dx * i / steps
        y = y0 + dy * i / steps
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchMove", "touchPoints": [point(x, y)],
        })
        page.wait_for_timeout(step_ms)
        samples.append(page.evaluate("""() => {
          const surface = document.querySelector('.movie .movie-surface');
          return { transform: surface?.style.transform || '', scrollY };
        }"""))
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    page.wait_for_timeout(700)
    return samples


def numeric_offsets(samples):
    values = []
    for sample in samples:
        transform = sample["transform"]
        if "translate3d(" not in transform:
            continue
        values.append(float(transform.split("translate3d(", 1)[1].split("px", 1)[0]))
    return values


def test_real_mobile_touch_swipe():
    tmp = Path(tempfile.mkdtemp(prefix="cq-touch-cdp-"))
    data = tmp / "movies.json"
    # Synthetic queue only: owner data never enters tests, images or CI.
    data.write_text(json.dumps([
        {"id": f"synthetic-{n}", "title": f"Synthetic Film {n}", "year": 1990 + n, "watched": False,
         "genres": ["Drama"], "runtime_minutes": 90 + n}
        for n in range(1, 13)
    ]))
    original = json.loads(data.read_text())
    original_order = [movie["id"] for movie in original]
    wrapper = tmp / "serve.py"
    wrapper.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import cinequeue.server as s\n"
        f"s.DATA = {str(data)!r}\n"
        f"s.run(port={PORT})\n"
    )
    server = subprocess.Popen(
        [sys.executable, str(wrapper)],
        env={**os.environ, "CINEQUEUE_BASE_PATH": "/cq-touch", "CINEQUEUE_DATA": str(tmp), "CINEQUEUE_WATCH_REGION": ""},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_server()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            device = playwright.devices.get("Pixel 5", {})
            context = browser.new_context(**device)
            page = context.new_page()
            errors = []
            page.on("console", lambda message: errors.append(message.text)
                    if message.type == "error" else None)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(BASE, wait_until="domcontentloaded")
            page.wait_for_selector(".movie")
            cdp = context.new_cdp_session(page)
            cdp.send("Emulation.setTouchEmulationEnabled", {
                "enabled": True, "maxTouchPoints": 1,
            })

            touch_actions = page.evaluate("""() => {
              const row = document.querySelector('.movie');
              const surface = row.querySelector('.movie-surface');
              return [getComputedStyle(row).touchAction, getComputedStyle(surface).touchAction];
            }""")
            assert touch_actions == ["pan-y", "pan-y"], touch_actions

            # Subthreshold drag must follow the finger monotonically, then cancel.
            before_id = page.locator(".movie").first.get_attribute("data-movie-id")
            samples = touch_drag(page, cdp, 60, 2, steps=8)
            offsets = numeric_offsets(samples)
            assert len(offsets) >= 6, offsets
            assert offsets == sorted(offsets) and offsets[-1] >= 55, offsets
            assert page.locator(f'.movie[data-movie-id="{before_id}"]').count() == 1
            state = next(movie for movie in json.loads(data.read_text()) if movie["id"] == before_id)
            assert not state.get("watched") and not state.get("archived")

            # Full right swipe commits watched and removes it from Unwatched.
            right_id = page.locator(".movie").first.get_attribute("data-movie-id")
            samples = touch_drag(page, cdp, 165, 3, steps=14)
            offsets = numeric_offsets(samples)
            assert len(offsets) >= 12 and offsets == sorted(offsets) and offsets[-1] >= 155, offsets
            state = next(movie for movie in json.loads(data.read_text()) if movie["id"] == right_id)
            assert state.get("watched") is True
            assert state.get("queued") is False
            assert len(state.get("watch_history", [])) == 1
            assert page.locator(f'.movie[data-movie-id="{right_id}"]').count() == 0

            # Watch is mutation-capable too: Undo removes only the new event and requeues.
            assert page.locator("#undoBar").is_visible()
            page.locator("#undoButton").click()
            page.wait_for_timeout(300)
            state = next(movie for movie in json.loads(data.read_text()) if movie["id"] == right_id)
            assert state.get("watched") is False
            assert state.get("queued") is True
            assert state.get("watch_history") == []
            assert page.locator(f'.movie[data-movie-id="{right_id}"]').count() == 1

            # Reapply the watch so the remaining gesture gates exercise the committed state.
            samples = touch_drag(page, cdp, 165, 3, steps=14)
            offsets = numeric_offsets(samples)
            assert len(offsets) >= 12 and offsets[-1] >= 155, offsets
            page.evaluate("dismissUndo()")

            # Full left swipe archives, shows Undo, then restores exact order.
            left_id = page.locator(".movie").first.get_attribute("data-movie-id")
            samples = touch_drag(page, cdp, -165, 3, steps=14)
            offsets = numeric_offsets(samples)
            assert len(offsets) >= 12 and offsets == sorted(offsets, reverse=True) and offsets[-1] <= -155, offsets
            state = next(movie for movie in json.loads(data.read_text()) if movie["id"] == left_id)
            assert state.get("archived") is True
            assert page.locator("#undoBar").is_visible()
            page.locator("#undoButton").click()
            page.wait_for_timeout(500)
            restored = json.loads(data.read_text())
            state = next(movie for movie in restored if movie["id"] == left_id)
            assert not state.get("archived")
            assert [movie["id"] for movie in restored] == original_order

            # Vertical touch stays native scrolling and causes no mutation.
            page.evaluate("window.scrollTo(0, 0)")
            vertical_id = page.locator(".movie").first.get_attribute("data-movie-id")
            before = data.read_bytes()
            touch_drag(page, cdp, 2, -220, steps=12)
            assert page.evaluate("scrollY") > 0
            assert data.read_bytes() == before
            assert page.locator(f'.movie[data-movie-id="{vertical_id}"]').count() == 1
            assert not errors, errors
            browser.close()
        print("PASS: CDP touch tracks finger, right-watches, left-archives/undoes, and preserves vertical scroll")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_real_mobile_touch_swipe()
