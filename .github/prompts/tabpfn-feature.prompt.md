---
name: tabpfn-feature
description: "Engineer a new tabular filesystem metadata feature for Prior Labs TabPFN anomaly detection"
---

# Add a Tabular Feature for Prior Labs TabPFN in slothd

You are helping extend the **Stage 1 Tabular Anomaly Engine** in `slothd/engine/tabular_predictor.py`.

## Context
`slothd` uses Prior Labs' TabPFN to spot disk clutter, size outliers, and leftover installers in ~1ms without loading a multi-gigabyte vision model.

Tabular features are extracted from `ScannedFile` in `extract_tabular_features(files, base_dir)`.

## Current 7-Feature Vector:
1. `size_mb`: File size in megabytes.
2. `age_days`: Days since last modification.
3. `name_len`: Filename character length.
4. `depth`: Directory depth relative to scan root.
5. `is_installer`: Binary flag (1 if `.exe`, `.dmg`, `.pkg`, `.iso`, else 0).
6. `is_archive`: Binary flag (1 if `.zip`, `.tar`, `.gz`, `.7z`, else 0).
7. `is_screenshot`: Binary flag (1 if filename matches screenshot timestamp pattern, else 0).

## Instructions for Adding a New Feature:
1. Identify a new numerical or boolean filesystem signal (e.g. `is_nested_duplicate`, `is_hidden`, `character_entropy`).
2. Add the feature extraction logic in `extract_tabular_features()`.
3. Update `FEATURE_NAMES` list.
4. Add anomaly rule logic in `_heuristic_anomaly_detection()` and update prompt tests in `tests/test_tabular_predictor.py`.
5. Ensure the feature extraction operates in $< 5\mu s$ per file so directory scans remain lightning fast.
