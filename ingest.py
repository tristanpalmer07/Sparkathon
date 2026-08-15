"""
ZooSentry — batch ingestion worker.

This is "piece 1" of the architecture from the design doc (section 6):
    MP4 clips -> VSS upload -> VSS analyze -> normalize -> SQLite

Run directly:
    python ingest.py path/to/clips_folder

If no folder is given, it generates a handful of fake filenames so the
whole pipeline can be exercised without any real video files yet.
"""

import sys
import os
import glob
import datetime
import json

import db
import vss_client
import alphachimp_client
import priority
import nemotron_client

# Set to "1" once your teammate's AlphaChimp wrapper is producing real
# detection files (see alphachimp_client.py's documented contract).
# Runs alongside VSS, not instead of it — both sources land in the same
# observations table, tagged by `source`.
USE_ALPHACHIMP = os.environ.get("USE_ALPHACHIMP", "0") == "1"


def discover_clips(folder: str | None) -> list[str]:
    if folder and os.path.isdir(folder):
        clips = sorted(glob.glob(os.path.join(folder, "*.mp4")))
        if clips:
            return clips
        print(f"No .mp4 files found in {folder}, falling back to demo filenames.")

    # Fallback: fake filenames so the pipeline is testable with USE_MOCK=True
    # even before real clips exist.
    return [f"clip_{i:03d}.mp4" for i in range(1, 13)]


def ingest_clip(filepath: str) -> dict:
    """Upload one clip to VSS, analyze it (VSS + optionally AlphaChimp), score events, store everything."""
    upload_result = vss_client.upload_video(filepath)
    video_id = upload_result["video_id"]

    db.upsert_video(
        video_id=video_id,
        filename=upload_result["filename"],
        vss_sensor_id=upload_result.get("vss_sensor_id"),
        upload_status=upload_result["status"],
    )

    analysis = vss_client.analyze_clip(video_id)
    scored_events = priority.score_clip_events(analysis["events"])

    db.upsert_video(
        video_id=video_id,
        filename=upload_result["filename"],
        vss_sensor_id=upload_result.get("vss_sensor_id"),
        upload_status="analyzed",
        clip_summary=analysis["clip_summary"],
    )

    for e in scored_events:
        db.insert_observation(
            video_id=video_id,
            start_s=e["start_s"],
            end_s=e["end_s"],
            behavior=e["behavior"],
            animals_visible=e["animals_visible"],
            description=e["description"],
            model_confidence=e["confidence"],
            priority=e["priority"],
            raw_response=e,
            source="vss",
        )

    all_events = list(scored_events)

    if USE_ALPHACHIMP:
        ac_analysis = alphachimp_client.analyze_clip(video_id)
        ac_scored_events = priority.score_clip_events(ac_analysis["events"])

        for e in ac_scored_events:
            vlm_description = None
            corroborated = False
            final_priority = e["priority"]

            # The gate: only events AlphaChimp already flagged (priority > 0)
            # get an enrichment call. Routine behavior never reaches Cosmos.
            if e["priority"] > 0:
                vlm_description = vss_client.enrich_event(
                    video_id=video_id,
                    start_s=e["start_s"],
                    end_s=e["end_s"],
                    behavior=e["behavior"],
                    track_id=e.get("track_id"),
                )
                corroborated = priority.check_corroboration(vlm_description, e["behavior"])
                if corroborated:
                    final_priority = min(3, e["priority"] + 1)

            db.insert_observation(
                video_id=video_id,
                start_s=e["start_s"],
                end_s=e["end_s"],
                behavior=e["behavior"],
                animals_visible=e["animals_visible"],
                description=e["description"],
                model_confidence=e["confidence"],
                priority=final_priority,
                raw_response=e,
                source="alphachimp",
                track_id=str(e.get("track_id", "")),
                vlm_description=vlm_description,
                corroborated=corroborated,
            )

        all_events.extend(ac_scored_events)

    return {"video_id": video_id, "events": all_events}


def build_event_packet(clips_processed: int) -> dict:
    """Aggregate stored observations into the packet Nemotron consumes."""
    observations = db.all_observations()

    metrics = {
        "aggression_events": 0,
        "grooming_events": 0,
        "playing_events": 0,
        "feeding_events": 0,
        "resting_events": 0,
        "movement_events": 0,
        "display_events": 0,
    }
    behavior_to_metric = {
        "aggression": "aggression_events",
        "aggressing": "aggression_events",
        "grooming": "grooming_events",
        "being_groomed": "grooming_events",
        "playing": "playing_events",
        "feeding": "feeding_events",
        "eating": "feeding_events",
        "resting": "resting_events",
        "sleeping": "resting_events",
        "travel_or_movement": "movement_events",
        "moving": "movement_events",
        "climbing": "movement_events",
        "display": "display_events",
        "displaying": "display_events",
    }
    # Every behavior gets tallied here too, regardless of whether it maps to
    # one of the legacy metrics above — keeps ethogram-only behaviors
    # (nursing, carrying, begging, etc.) visible without hardcoding each one.
    all_behavior_counts = {}

    for obs in observations:
        key = behavior_to_metric.get(obs["behavior"])
        if key:
            metrics[key] += 1
        all_behavior_counts[obs["behavior"]] = all_behavior_counts.get(obs["behavior"], 0) + 1

    priority_events = [
        {
            "video_id": obs["video_id"],
            "start_s": obs["start_s"],
            "end_s": obs["end_s"],
            "behavior": obs["behavior"],
            "priority": obs["priority"],
            "description": obs.get("vlm_description") or obs["description"],
            "source": obs.get("source", "vss"),
            "corroborated": bool(obs.get("corroborated")),
        }
        for obs in observations
        if obs["priority"] > 0
    ]

    return {
        "shift_id": f"demo-{datetime.date.today().isoformat()}",
        "clips_processed": clips_processed,
        "metrics": metrics,
        "all_behavior_counts": all_behavior_counts,
        "priority_events": priority_events,
    }


def run(folder: str | None = None, reset: bool = True):
    db.init_db(reset=reset)

    clips = discover_clips(folder)
    print(f"Ingesting {len(clips)} clip(s)...")

    for filepath in clips:
        result = ingest_clip(filepath)
        n_flagged = sum(1 for e in result["events"] if e["priority"] > 0)
        print(f"  {result['video_id']}: {len(result['events'])} event(s), "
              f"{n_flagged} flagged for review")

    packet = build_event_packet(clips_processed=len(clips))
    brief = nemotron_client.generate_shift_brief(packet)
    db.save_shift_brief(datetime.datetime.now().isoformat(), brief)

    print("\n=== SHIFT BRIEF ===")
    print(json.dumps(brief, indent=2))

    return packet, brief


if __name__ == "__main__":
    folder_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(folder_arg)