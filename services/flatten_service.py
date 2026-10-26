import importlib.util
import sys
from pathlib import Path


_ENGINE = None


def load_engine():
    global _ENGINE

    if _ENGINE is not None:
        return _ENGINE

    engine_path = (
        Path(__file__).resolve().parent.parent
        / "flattening"
        / "flatten_semi_structured_data_v2.py"
    )

    if not engine_path.exists():
        raise FileNotFoundError(
            f"Flattening engine not found: {engine_path}"
        )

    spec = importlib.util.spec_from_file_location(
        "flatten_semi_structured_data_v2",
        engine_path
    )

    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {engine_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["flatten_semi_structured_data_v2"] = module
    spec.loader.exec_module(module)
    _ENGINE = module
    return _ENGINE


class FlattenRun:
    def __init__(self):
        self.events = []
        self.cache_hits = 0
        self.cache_misses = 0
        self.cortex_calls = 0
        self.repair_calls = 0
        self.successful_targets = 0
        self.failed_targets = 0
        self.structures_started = 0
        self.structures_completed = 0
        self.structures_failed = 0
        self.records_processed = 0

    def add_event(self, event):
        self.events.append(event)
        event_type = event.get("event_type")

        if event_type == "CACHE_HIT":
            self.cache_hits += 1
        elif event_type == "CACHE_MISS":
            self.cache_misses += 1
        elif event_type == "CORTEX_CALL":
            self.cortex_calls += 1
        elif event_type == "CORTEX_REPAIR":
            self.repair_calls += 1
        elif event_type == "EXECUTION_SUCCESS":
            self.successful_targets += 1
        elif event_type == "EXECUTION_ERROR":
            self.failed_targets += 1
        elif event_type == "STRUCTURE_START":
            self.structures_started += 1
        elif event_type == "STRUCTURE_SUCCESS":
            self.structures_completed += 1
        elif event_type == "STRUCTURE_ERROR":
            self.structures_failed += 1


def run_source(session, source_type, config, progress_callback=None):
    engine = load_engine()
    engine.configure(config)

    run = FlattenRun()

    def callback(event):
        run.add_event(event)
        if progress_callback:
            progress_callback(event, run)

    engine.set_progress_callback(callback)

    raw_table = config["sources"][source_type]["raw_table"]

    try:
        records_processed = engine.process_source_table(
            session,
            source_type,
            raw_table
        )
        run.records_processed = records_processed
        return {
            "success": True,
            "records_processed": records_processed,
            "run": run,
            "error": None
        }
    except Exception as exc:
        return {
            "success": False,
            "records_processed": run.records_processed,
            "run": run,
            "error": str(exc)
        }
    finally:
        engine.set_progress_callback(None)
