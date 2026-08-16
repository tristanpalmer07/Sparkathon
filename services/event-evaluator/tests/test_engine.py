import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from engine import EventEvaluator  # noqa: E402
from rules import RuleConfig  # noqa: E402
from shared.schemas import AlphaChimpEvent  # noqa: E402


def make_event(t, track_id=1, camera_id="enc_a", bbox=(0, 0, 10, 10), behaviors=None, det_conf=0.9):
    return AlphaChimpEvent(
        camera_id=camera_id,
        track_id=track_id,
        t=t,
        bbox=bbox,
        det_conf=det_conf,
        behaviors=behaviors or {},
    )


def test_sustained_aggression_fires_after_min_duration():
    cfg = RuleConfig(aggression_conf_threshold=0.70, aggression_min_duration_s=2.0)
    ev = EventEvaluator(cfg)

    # below duration threshold: no fire
    assert ev.process(make_event(0.0, behaviors={"aggressing": 0.81})) == []
    assert ev.process(make_event(1.0, behaviors={"aggressing": 0.81})) == []

    # crosses 2.0s sustained: fires exactly once
    fired = ev.process(make_event(2.1, behaviors={"aggressing": 0.81}))
    assert len(fired) == 1
    c = fired[0]
    assert c.trigger_rule == "sustained_aggression"
    assert c.camera_id == "enc_a"
    assert c.track_ids == [1]
    # padded by clip_pad_s (default 5.0) on both sides
    assert c.t_start == 0.0 - cfg.clip_pad_s
    assert c.t_end == 2.1 + cfg.clip_pad_s

    # still sustained: does not refire (debounced)
    assert ev.process(make_event(3.0, behaviors={"aggressing": 0.81})) == []


def test_aggression_run_resets_on_drop_below_threshold():
    ev = EventEvaluator(RuleConfig(aggression_conf_threshold=0.70, aggression_min_duration_s=2.0))
    ev.process(make_event(0.0, behaviors={"aggressing": 0.81}))
    # drops below threshold before sustaining long enough
    assert ev.process(make_event(1.0, behaviors={"aggressing": 0.40})) == []
    # starts a fresh run; not enough elapsed time since reset to fire yet
    assert ev.process(make_event(1.5, behaviors={"aggressing": 0.81})) == []
    fired = ev.process(make_event(3.6, behaviors={"aggressing": 0.81}))
    assert len(fired) == 1
    assert fired[0].t_start == 1.5 - 5.0


def test_close_proximity_fires_for_sustained_pair():
    cfg = RuleConfig(proximity_threshold_px=50.0, proximity_min_duration_s=3.0)
    ev = EventEvaluator(cfg)

    # two tracks close together for >= 3.0s — both tracks must be refreshed
    # often enough to stay within proximity_max_staleness_s of each other.
    fired = []
    for t in (0.0, 0.1, 1.0, 1.1, 2.0, 2.1, 3.0, 3.2):
        track_id, bbox = (1, (0, 0, 10, 10)) if t in (0.0, 1.0, 2.0, 3.2) else (2, (5, 5, 10, 10))
        fired += ev.process(make_event(t, track_id=track_id, bbox=bbox))
    assert any(c.trigger_rule == "close_proximity" for c in fired)
    prox = [c for c in fired if c.trigger_rule == "close_proximity"][0]
    assert prox.track_ids == [1, 2]


def test_close_proximity_ignores_stale_positions():
    cfg = RuleConfig(proximity_threshold_px=50.0, proximity_min_duration_s=1.0, proximity_max_staleness_s=1.0)
    ev = EventEvaluator(cfg)
    ev.process(make_event(0.0, track_id=1, bbox=(0, 0, 10, 10)))
    # track 2 seen far in the past relative to staleness window -> not compared
    ev.process(make_event(0.0, track_id=2, bbox=(5, 5, 10, 10)))
    fired = ev.process(make_event(10.0, track_id=1, bbox=(0, 0, 10, 10)))
    assert not any(c.trigger_rule == "close_proximity" for c in fired)


def test_sustained_target_behavior_watchlist():
    cfg = RuleConfig(watchlist_behaviors=("pacing",), watchlist_conf_threshold=0.6, watchlist_min_duration_s=5.0)
    ev = EventEvaluator(cfg)
    ev.process(make_event(0.0, behaviors={"pacing": 0.7}))
    assert ev.process(make_event(4.0, behaviors={"pacing": 0.7})) == []
    fired = ev.process(make_event(5.1, behaviors={"pacing": 0.7}))
    assert any(c.trigger_rule == "sustained_target_behavior" for c in fired)


def test_behaviors_not_in_watchlist_are_ignored():
    cfg = RuleConfig(watchlist_behaviors=("pacing",), watchlist_min_duration_s=1.0)
    ev = EventEvaluator(cfg)
    fired = ev.process(make_event(0.0, behaviors={"feeding": 0.99}))
    fired += ev.process(make_event(2.0, behaviors={"feeding": 0.99}))
    assert fired == []
