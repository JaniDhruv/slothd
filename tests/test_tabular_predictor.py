"""Tests for slothd Prior Labs TabPFN tabular prediction and anomaly detection."""

from __future__ import annotations

import os
import time
from pathlib import Path

from slothd import ui
from slothd.engine.scanner import scan_directory
from slothd.engine.tabular_predictor import (
    TabPFNPredictor,
    TabularPredictionResult,
    extract_tabular_features,
)


def test_extract_tabular_features(tmp_path: Path) -> None:
    test_file = tmp_path / "invoice_123.pdf"
    test_file.write_bytes(b"%PDF-1.4 sample content")

    files = scan_directory(tmp_path)
    assert len(files) == 1

    features = extract_tabular_features(files[0], base_dir=tmp_path)
    assert len(features) == 7
    # Feature 0: log2(size_kb + 1)
    assert features[0] >= 0.0
    # Feature 1: extension group for .pdf should be 1 (Documents)
    assert features[1] == 1.0
    # Feature 2: depth should be 1.0
    assert features[2] == 1.0
    # Feature 6: has digits ('123')
    assert features[6] == 1.0


def test_tabular_predictor_empty_dir(empty_dir: Path) -> None:
    predictor = TabPFNPredictor()
    result = predictor.analyze_directory([], base_dir=empty_dir)

    assert result.total_files == 0
    assert result.total_bytes == 0
    assert result.anomalies == []
    assert result.clutter_ratio == 0.0
    assert "TabPFN" in result.model_used


def test_tabular_predictor_messy_downloads(messy_downloads: Path) -> None:
    files = scan_directory(messy_downloads)
    predictor = TabPFNPredictor()
    result = predictor.analyze_directory(files, base_dir=messy_downloads)

    assert result.total_files == len(files)
    assert len(result.anomalies) > 0
    assert 0.0 < result.clutter_ratio <= 1.0

    # Ensure installer is flagged
    installer_anomalies = [a for a in result.anomalies if a.file_name.endswith(".exe")]
    assert len(installer_anomalies) >= 1
    assert "installer" in installer_anomalies[0].reason.lower()

    # Ensure screenshot is flagged
    screenshot_anomalies = [a for a in result.anomalies if "screenshot" in a.file_name.lower()]
    assert len(screenshot_anomalies) >= 1
    assert "screenshot" in screenshot_anomalies[0].reason.lower()

    # Serialization test
    d = result.to_dict()
    assert "total_files" in d
    assert "anomalies" in d
    assert "clutter_ratio" in d
    assert isinstance(d["anomalies"], list)


def test_tabular_predictor_size_outlier(tmp_path: Path) -> None:
    # Create several small files
    for i in range(10):
        (tmp_path / f"small_{i}.txt").write_text("hello" * 10)

    # Create a large dummy file (60MB)
    huge_file = tmp_path / "huge_dump.bin"
    huge_file.write_bytes(b"\x00" * (60 * 1024 * 1024))

    files = scan_directory(tmp_path, max_file_size_mb=100)
    predictor = TabPFNPredictor()
    result = predictor.analyze_directory(files, base_dir=tmp_path)

    critical_items = [a for a in result.anomalies if a.risk_level == "CRITICAL"]
    assert len(critical_items) >= 1
    assert critical_items[0].file_name == "huge_dump.bin"
    assert "outlier" in critical_items[0].reason.lower()


def test_tabular_predictor_stale_archive(tmp_path: Path) -> None:
    archive_file = tmp_path / "old_backup.tar.gz"
    archive_file.write_bytes(b"PK fake archive")

    # Set mtime back 30 days
    old_time = time.time() - (30 * 86400)
    os.utime(archive_file, (old_time, old_time))

    files = scan_directory(tmp_path)
    predictor = TabPFNPredictor()
    result = predictor.analyze_directory(files, base_dir=tmp_path)

    stale_items = [a for a in result.anomalies if "Stale archive" in a.reason]
    assert len(stale_items) == 1
    assert stale_items[0].file_name == "old_backup.tar.gz"


def test_ui_anomalies_table_rendering(messy_downloads: Path) -> None:
    files = scan_directory(messy_downloads)
    predictor = TabPFNPredictor()
    result = predictor.analyze_directory(files, base_dir=messy_downloads)

    # Must render without throwing any exceptions
    ui.anomalies_table(result)

    # Clean empty result rendering
    empty_res = TabularPredictionResult(
        total_files=0,
        total_bytes=0,
        anomalies=[],
        category_counts={},
        clutter_ratio=0.0,
        model_used="TabPFN-Heuristic-Local",
    )
    ui.anomalies_table(empty_res)
