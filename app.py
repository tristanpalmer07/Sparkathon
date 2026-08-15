"""
ZooSentry — Streamlit dashboard.

Run:
    streamlit run app.py

No auth, no user accounts, no design system — matches the "must work by
end of day" scope. Reads whatever is currently in observations.db.
"""

import json
import tempfile
from pathlib import Path

import streamlit as st

import db
import ingest

st.set_page_config(page_title="ZooSentry", layout="wide")

st.title("ZooSentry — Shift Review")
st.caption(
    "Turns passive CCTV into a review queue and shift brief. "
    "Reports visible behavior only — not a medical diagnosis."
)

UPLOAD_DIR = Path(tempfile.gettempdir()) / "zoosentry_uploads"

with st.sidebar:
    st.header("Run a shift")

    source = st.radio(
        "Clip source",
        ["Upload files", "Folder path on this machine"],
        label_visibility="collapsed",
    )

    uploaded_files = None
    folder = None

    if source == "Upload files":
        uploaded_files = st.file_uploader(
            "Drop any .mp4 clips here",
            type=["mp4"],
            accept_multiple_files=True,
        )
    else:
        folder = st.text_input("Clips folder (leave blank for demo data)", "")

    if st.button("Analyze shift", type="primary"):
        target_folder = None

        if source == "Upload files":
            if not uploaded_files:
                st.warning("Upload at least one .mp4 file first.")
                st.stop()

            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            for f in UPLOAD_DIR.glob("*.mp4"):
                f.unlink()  # clear out any previous shift's clips
            for f in uploaded_files:
                (UPLOAD_DIR / f.name).write_bytes(f.getbuffer())
            target_folder = str(UPLOAD_DIR)
        else:
            target_folder = folder or None

        with st.spinner("Uploading clips to VSS and analyzing..."):
            packet, brief = ingest.run(target_folder, reset=True)
        st.success("Done.")

observations = db.all_observations()
videos = db.all_videos()
brief_row = db.latest_shift_brief()

if not observations:
    st.info("No data yet. Click **Analyze shift** in the sidebar to run the pipeline on demo data.")
    st.stop()

# --- Top metrics ---------------------------------------------------------
n_clips = len(videos)
n_flagged = len({o["video_id"] for o in observations if o["priority"] > 0})
n_high = sum(1 for o in observations if o["priority"] == 3)
n_med = sum(1 for o in observations if o["priority"] == 2)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Clips reviewed", n_clips)
c2.metric("Clips needing review", n_flagged)
c3.metric("High priority events", n_high)
c4.metric("Medium priority events", n_med)

st.divider()

# --- Shift brief -----------------------------------------------------------
st.subheader("Shift Brief")
if brief_row:
    brief = json.loads(brief_row["brief_json"])
    st.markdown(f"**{brief['headline']}**")
    st.write(brief["shift_summary"])

    if brief.get("review_first"):
        st.markdown("**Review first:**")
        for item in brief["review_first"]:
            st.markdown(f"- `{item['video_id']}` @ {item['timestamp']} — {item['reason']}")

    col_a, col_b, col_c = st.columns(3)
    col_a.markdown(f"**Social:** {brief.get('social_activity_summary', '')}")
    col_b.markdown(f"**Feeding:** {brief.get('feeding_activity_summary', '')}")
    col_c.markdown(f"**Activity:** {brief.get('activity_summary', '')}")
else:
    st.write("No brief generated yet.")

st.divider()

# --- Priority queue --------------------------------------------------------
st.subheader("Review Queue")
LABELS = {3: "🔴 HIGH", 2: "🟠 MEDIUM", 1: "🟡 REVIEW", 0: "⚪ INFO"}

flagged = [o for o in observations if o["priority"] > 0]
if not flagged:
    st.write("Nothing flagged for review this shift.")
for obs in flagged:
    with st.container(border=True):
        st.markdown(f"**{LABELS[obs['priority']]} — {obs['behavior']}**  "
                     f"({obs['video_id']}, {obs['start_s']:.0f}s–{obs['end_s']:.0f}s)")
        st.write(obs["description"])
        st.caption(f"Animals visible: {obs['animals_visible']} · "
                     f"Model confidence: {obs['model_confidence']}")

st.divider()

# --- Full event table --------------------------------------------------------
st.subheader("All Observations")
st.dataframe(
    [
        {
            "video_id": o["video_id"],
            "behavior": o["behavior"],
            "start_s": o["start_s"],
            "end_s": o["end_s"],
            "priority": LABELS[o["priority"]],
            "animals_visible": o["animals_visible"],
            "confidence": o["model_confidence"],
            "description": o["description"],
        }
        for o in observations
    ],
    use_container_width=True,
    hide_index=True,
)

st.caption("ZooSentry reports visible behavior only. It does not make a medical diagnosis.")