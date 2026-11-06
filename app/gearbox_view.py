"""Local pilot replay view. Requires the publisher recordings in data/mcc5."""
import pandas as pd
import streamlit as st

from pufusion.gearbox import SENSORS, condition_split, discover, extract, fit_records, replay
from pufusion.sensor_faults import SCENARIOS


@st.cache_resource(max_entries=4, show_spinner="Training on the selected training profiles")
def _train(records, fingerprints):
    # File size and modification time invalidate the cache if local recordings change.
    return fit_records(records, {record.id: extract(record) for record in records})


def view_gearbox(data):
    st.title("Gearbox pilot")
    st.caption("MCC5-THU v2 laboratory recordings. Any injected sensor fault is simulated.")
    st.markdown("[Publisher dataset and attribution](https://data.mendeley.com/datasets/p92gj2732w/2)")
    try:
        recordings = discover(data)
        conditions = sorted({r.condition for r in recordings})
        complete = []
        for condition in conditions:
            try:
                condition_split(recordings, condition)
            except ValueError:
                continue
            complete.append(condition)
        if not complete:
            st.info("Add MCC5-THU v2 pilot recordings under data/mcc5. See docs/GEARBOX_INTERIM.md.")
            return
        condition = st.selectbox("Held-out operating profile", complete, key="gearbox_condition")
        train, test = condition_split(recordings, condition)
        record = st.selectbox("Held-out recording", test, format_func=lambda r: r.id, key="gearbox_record")
        family = st.selectbox("Sensor fault injection", ["clean", *SCENARIOS], key="gearbox_family")
        target = None if family == "clean" else st.selectbox(
            "Affected sensor", [*SENSORS, "both"], key="gearbox_target"
        )
        st.caption(f"{len(train)} training recordings across {len({r.condition for r in train})} other profiles. "
                   "The gearbox and bearing views use the same health-state rules with separate models.")
        key = (record, tuple(train), family, target)
        if st.button("Run held-out replay", key="gearbox_run"):
            st.session_state.pop("gearbox_trace", None)
            fingerprints = tuple((stat.st_size, stat.st_mtime_ns) for stat in (r.path.stat() for r in train))
            model = _train(tuple(train), fingerprints)
            with st.spinner("Replaying the held-out recording"):
                x, q = extract(record, family if target else None, target, seed=42 + recordings.index(record))
                frame = pd.DataFrame(replay(model, x, q))
            st.session_state["gearbox_trace"] = (key, frame)
        result = st.session_state.get("gearbox_trace")
        if result and result[0] == key:
            frame = result[1]
            st.metric("Final health state", frame["state"].iloc[-1])
            st.metric("Windows with diagnosis", f"{frame['prediction'].notna().mean():.0%}")
            st.line_chart(frame.set_index("window")[["motor_weight", "gearbox_weight"]])
            st.dataframe(frame, hide_index=True)
            st.download_button("Download replay trace", frame.to_csv(index=False), "gearbox_replay.csv", "text/csv")
    except (OSError, ValueError) as exc:
        st.error(f"Could not run the local gearbox pilot: {exc}")
