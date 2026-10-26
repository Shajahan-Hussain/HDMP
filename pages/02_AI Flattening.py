import streamlit as st
from snowflake.snowpark.context import get_active_session

from utils.config_loader import load_config
from services.flatten_service import run_source


st.set_page_config(
    page_title="AI Flattening",
    page_icon="🤖",
    layout="wide"
)

config = load_config()
session = get_active_session()


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def event_icon(event_type):
    if event_type in {
        "CACHE_HIT", "EXECUTION_SUCCESS", "STRUCTURE_SUCCESS",
        "REPAIR_SUCCESS", "REGISTRY_SAVE", "SOURCE_COMPLETE"
    }:
        return "✓"
    if event_type in {"EXECUTION_ERROR", "STRUCTURE_ERROR"}:
        return "✗"
    if event_type in {"CORTEX_CALL", "CORTEX_REPAIR", "CACHE_MISS"}:
        return "AI"
    return "•"


def event_text(event):
    text = event.get("message", "")
    details = event.get("details") or {}
    hash_value = event.get("structure_hash")
    target = event.get("target_table")

    if target:
        text += f"  |  {target}"
    if hash_value:
        text += f"  |  hash: {hash_value[:16]}..."
    if details.get("record_count") is not None:
        text += f"  |  rows: {details['record_count']}"
    return text


# ------------------------------------------------------------
# Header
# ------------------------------------------------------------

st.title("🤖 AI Flattening")
st.caption(
    "Run the existing FHIR / JSON / XML flattening engine, "
    "reuse structure-specific SQL from the registry, and use "
    "Cortex only when a query is not already cached."
)


# ------------------------------------------------------------
# Configuration panel
# ------------------------------------------------------------

with st.container(border=True):
    st.subheader("Flattening Configuration")

    source_options = ["FHIR", "JSON", "XML", "ALL"]
    source_type = st.selectbox(
        "Source Type",
        source_options,
        help="Choose one source or run all configured sources sequentially."
    )

    if source_type in config.get("sources", {}):
        source_config = config["sources"][source_type]
        raw_table = source_config.get("raw_table", "Not configured")
        st.caption(f"Raw source: `{raw_table}`")

    ai_config = config.get("ai", config.get("cortex", {}))
    cortex_model = ai_config.get(
        "model",
        ai_config.get("cortex_model", "Not configured")
    )

    st.caption(f"AI model: `{cortex_model}`")


# ------------------------------------------------------------
# Run button
# ------------------------------------------------------------

run_button = st.button(
    "▶ Run AI Flattening",
    type="primary",
    use_container_width=True
)


if run_button:
    sources = ["FHIR", "JSON", "XML"] if source_type == "ALL" else [source_type]

    all_results = []

    for selected_source in sources:
        if selected_source not in config.get("sources", {}):
            st.error(f"{selected_source} is not configured.")
            continue

        st.divider()
        st.subheader(f"{selected_source} Pipeline")

        status_box = st.empty()
        progress_bar = st.progress(0, text="Starting...")
        event_box = st.empty()

        def on_progress(event, run):
            event_type = event.get("event_type")
            details = event.get("details") or {}

            if event_type == "STRUCTURE_PROGRESS":
                index = details.get("index", 0)
                total = details.get("total", 0)
                value = (index / total) if total else 0
                progress_bar.progress(
                    min(max(value, 0.0), 1.0),
                    text=f"Structure {index}/{total}"
                )
            elif event_type == "SOURCE_COMPLETE":
                progress_bar.progress(1.0, text="Completed")

            text = event_text(event)

            if event_type in {"EXECUTION_ERROR", "STRUCTURE_ERROR"}:
                status_box.error(f"✗ {text}")
            elif event_type in {
                "CACHE_HIT", "EXECUTION_SUCCESS", "STRUCTURE_SUCCESS",
                "REPAIR_SUCCESS", "REGISTRY_SAVE", "SOURCE_COMPLETE"
            }:
                status_box.success(f"✓ {text}")
            elif event_type in {"CORTEX_CALL", "CORTEX_REPAIR", "CACHE_MISS"}:
                status_box.warning(f"AI  {text}")
            else:
                status_box.info(f"• {text}")

            # Keep the latest activity visible without creating hundreds
            # of permanent Streamlit elements.
            recent = run.events[-8:]
            event_box.code(
                "\n".join(
                    f"{event_icon(e.get('event_type'))} {event_text(e)}"
                    for e in recent
                ),
                language="text"
            )

        result = run_source(
            session=session,
            source_type=selected_source,
            config=config,
            progress_callback=on_progress
        )

        all_results.append({
            "source_type": selected_source,
            "result": result
        })

        if result["success"]:
            progress_bar.progress(1.0, text="Completed")
            status_box.success(
                f"✓ {selected_source} completed — "
                f"{result['records_processed']:,} source record(s) handled."
            )
        else:
            status_box.error(
                f"✗ {selected_source} failed: {result['error']}"
            )

    st.session_state["last_flatten_results"] = all_results


# ------------------------------------------------------------
# Results from the current / last run
# ------------------------------------------------------------

results = st.session_state.get("last_flatten_results", [])

if results:
    st.divider()
    st.header("Run Summary")

    total_records = sum(x["result"]["run"].records_processed for x in results)
    total_structures = sum(x["result"]["run"].structures_started for x in results)
    total_completed = sum(x["result"]["run"].structures_completed for x in results)
    total_failed_structures = sum(x["result"]["run"].structures_failed for x in results)
    total_hits = sum(x["result"]["run"].cache_hits for x in results)
    total_misses = sum(x["result"]["run"].cache_misses for x in results)
    total_cortex = sum(x["result"]["run"].cortex_calls for x in results)
    total_repairs = sum(x["result"]["run"].repair_calls for x in results)
    total_targets = sum(x["result"]["run"].successful_targets for x in results)
    total_target_errors = sum(x["result"]["run"].failed_targets for x in results)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Records Processed", f"{total_records:,}")
    c2.metric("Structures", f"{total_structures:,}")
    c3.metric("Structures Completed", f"{total_completed:,}")
    c4.metric("Structure Failures", f"{total_failed_structures:,}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Registry Cache Hits", f"{total_hits:,}")
    c6.metric("Registry Cache Misses", f"{total_misses:,}")
    c7.metric("Cortex Calls", f"{total_cortex:,}")
    c8.metric("Cortex Repairs", f"{total_repairs:,}")

    c9, c10 = st.columns(2)
    c9.metric("Successful Target Loads", f"{total_targets:,}")
    c10.metric("Target Load Errors", f"{total_target_errors:,}")

    st.subheader("Source Results")

    rows = []
    for item in results:
        result = item["result"]
        run = result["run"]
        rows.append({
            "Source": item["source_type"],
            "Status": "SUCCESS" if result["success"] else "FAILED",
            "Records": run.records_processed,
            "Structures": run.structures_started,
            "Completed": run.structures_completed,
            "Failed": run.structures_failed,
            "Cache Hits": run.cache_hits,
            "Cache Misses": run.cache_misses,
            "Cortex Calls": run.cortex_calls,
            "Repairs": run.repair_calls,
            "Target Errors": run.failed_targets
        })

    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("Structure / Target Activity")

    for item in results:
        source = item["source_type"]
        run = item["result"]["run"]

        with st.expander(f"{source} — {len(run.events)} pipeline events"):
            for event in run.events:
                event_type = event.get("event_type")
                text = event_text(event)

                if event_type in {"EXECUTION_ERROR", "STRUCTURE_ERROR"}:
                    st.error(f"✗ {text}")
                elif event_type in {
                    "CACHE_HIT", "EXECUTION_SUCCESS", "STRUCTURE_SUCCESS",
                    "REPAIR_SUCCESS", "REGISTRY_SAVE", "SOURCE_COMPLETE"
                }:
                    st.success(f"✓ {text}")
                elif event_type in {"CORTEX_CALL", "CORTEX_REPAIR", "CACHE_MISS"}:
                    st.warning(f"AI  {text}")
                else:
                    st.write(f"• {text}")

    st.subheader("Errors")

    errors = []
    for item in results:
        for event in item["result"]["run"].events:
            if event.get("event_type") in {"EXECUTION_ERROR", "STRUCTURE_ERROR"}:
                errors.append({
                    "Source": event.get("source_type"),
                    "Structure Hash": event.get("structure_hash"),
                    "Target Table": event.get("target_table"),
                    "Error": event.get("message")
                })

    if errors:
        st.dataframe(errors, use_container_width=True, hide_index=True)
    else:
        st.success("No errors occurred during the last flattening run.")
