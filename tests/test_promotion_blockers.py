"""Regression tests for promotion and real-touch swipe blockers.

1. Normal-motion swipe-right: the finish callback must never invert history
   or queue state — the server projection is authoritative in both paths.
2. Keyboard/menu archive: the removed row's visible index must be captured
   BEFORE archiveMovie() re-renders, and focus helpers must target that
   captured index (next row, or previous when the removed row was last).
3. Real touch capture: keep the browser's implicit child capture instead of
   transferring it to the row and treating the resulting lostpointercapture
   as cancellation.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text()


def test_swipe_finish_callback_never_inverts_watched():
    # The old finishWatched flipped watched a second time client-side.
    assert "watched: !movies[i].watched" not in APP
    assert "finishWatched(" not in APP  # old buggy helper is gone
    # Both motion paths finish presentation after the server mutation.
    assert ".then(() => { row.remove(); finishWatchedRender(); })" in APP
    assert ".then(finishWatchedRender)" in APP


def test_watch_and_rewatch_actions_announce_for_screen_readers():
    # Swipe, keyboard W, and row-menu actions announce both lifecycle outcomes.
    assert APP.count("Marked ${movie.title} watched") >= 3
    assert APP.count("${movie.title} added to your watchlist again") >= 3
    assert "Marked ${movie.title} unwatched" not in APP


def test_archive_focus_captures_index_before_render():
    # Callers capture the row's visible index before archiveMovie() renders.
    assert "const domIndex = visibleRowIndex(row);" in APP
    assert "archiveMovie(movie).then((ok) => { if (ok) focusRowAtIndex(domIndex); });" in APP


def test_dead_and_misleading_focus_helpers_removed():
    assert "focusNextRowAfter" not in APP
    assert "focusNearestRow" not in APP


def test_focus_helper_clamps_to_last_row():
    # focusRowAtIndex focuses the row now occupying the captured index,
    # clamping to the new last row when the removed row was last.
    assert "rows[Math.min(index, rows.length - 1)]?.focus();" in APP


def test_client_model_exposed_read_only_for_qa_harness():
    assert "Object.defineProperty(window, '__cqMovies', { get: () => movies });" in APP
    assert "__cqMovies =" not in APP  # never assigned directly


def test_real_touch_keeps_implicit_capture_target():
    assert "hit.hasPointerCapture(event.pointerId)" in APP
    assert "state.captureTarget = hit;" in APP
    assert "state.captureTarget = row;" in APP
    assert "event.target === state.captureTarget" in APP
    assert "event.target === row" not in APP


def test_drag_surface_is_transition_free_and_owns_horizontal_touch():
    css = (ROOT / "web" / "styles.css").read_text()
    assert ".movie.swipe-dragging .movie-surface" in css
    assert "transition: none !important" in css
    surface = css.split("\n.movie-surface {", 1)[1].split("}", 1)[0]
    assert "touch-action: pan-y" in surface


def test_vertical_axis_requires_clear_ratio_before_abandoning():
    assert "absY > absX * AXIS_RATIO" in APP


def test_second_pointer_cannot_replace_active_swipe_state():
    assert "if (state || activeSwipe) return;" in APP
