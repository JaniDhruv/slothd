"""slothd.engine — Core engine modules."""

from slothd.engine.classifier import (
    FileClassification,
    apply_classification,
    classify_batch,
    classify_file,
)
from slothd.engine.enricher import enrich_file_metadata
from slothd.engine.organizer import (
    OperationLog,
    PlannedMove,
    compute_destination,
    execute_moves,
    plan_moves,
    resolve_collision,
    undo_last_batch,
)
from slothd.engine.scanner import (
    ScannedFile,
    compute_file_hash,
    find_duplicates,
    group_by_category,
    scan_directory,
    scan_file,
)
from slothd.engine.search import SearchEngine, SearchHit
from slothd.engine.tabular_predictor import (
    AnomalyItem,
    TabPFNPredictor,
    TabularPredictionResult,
    extract_tabular_features,
)

__all__ = [
    "ScannedFile",
    "scan_file",
    "scan_directory",
    "group_by_category",
    "compute_file_hash",
    "find_duplicates",
    "FileClassification",
    "classify_file",
    "classify_batch",
    "apply_classification",
    "OperationLog",
    "PlannedMove",
    "compute_destination",
    "resolve_collision",
    "plan_moves",
    "execute_moves",
    "undo_last_batch",
    "SearchEngine",
    "SearchHit",
    "enrich_file_metadata",
    "AnomalyItem",
    "TabularPredictionResult",
    "TabPFNPredictor",
    "extract_tabular_features",
]
