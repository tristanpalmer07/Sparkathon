import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from converter import to_nv_frame  # noqa: E402
from shared.schemas import AlphaChimpEvent  # noqa: E402


def make_event(track_id, t=1000.0, bbox=(10.0, 20.0, 30.0, 40.0), det_conf=0.9, behaviors=None):
    return AlphaChimpEvent(
        camera_id="enc_a",
        track_id=track_id,
        t=t,
        bbox=bbox,
        det_conf=det_conf,
        behaviors=behaviors or {"aggression": 0.81},
    )


def test_frame_carries_sensor_and_timestamp():
    frame = to_nv_frame("enc_a", 1000.0, [make_event(1)])
    assert frame.sensorId == "enc_a"
    assert frame.timestamp.ToNanoseconds() == int(1000.0 * 1e9)


def test_multiple_events_become_multiple_objects_in_one_frame():
    events = [make_event(1), make_event(2)]
    frame = to_nv_frame("enc_a", 1000.0, events)
    assert len(frame.objects) == 2
    assert {o.id for o in frame.objects} == {"1", "2"}


def test_bbox_converted_from_xywh_to_ltrb():
    frame = to_nv_frame("enc_a", 1000.0, [make_event(1, bbox=(10.0, 20.0, 30.0, 40.0))])
    obj = frame.objects[0]
    assert obj.bbox.leftX == 10.0
    assert obj.bbox.topY == 20.0
    assert obj.bbox.rightX == 40.0  # x + w
    assert obj.bbox.bottomY == 60.0  # y + h


def test_behaviors_land_in_object_info_map():
    frame = to_nv_frame("enc_a", 1000.0, [make_event(1, behaviors={"aggression": 0.812345})])
    obj = frame.objects[0]
    assert obj.info["aggression"] == "0.8123"


def test_serializes_round_trips():
    import schema_pb2 as nv

    frame = to_nv_frame("enc_a", 1000.0, [make_event(1)])
    raw = frame.SerializeToString()
    parsed = nv.Frame()
    parsed.ParseFromString(raw)
    assert parsed.sensorId == "enc_a"
    assert len(parsed.objects) == 1
