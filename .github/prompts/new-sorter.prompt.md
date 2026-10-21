---
name: new-sorter
description: "Implement a new custom folder sorting rule and category mapping for slothd"
---

# Add a New Organization Rule to slothd

You are helping a developer add a new file category, destination directory structure, or custom sorting rule to `slothd`.

## Context & Architecture
In `slothd`, file moves are calculated in `slothd/engine/organizer.py` via `compute_destination(scanned_file, base_dir)`.

## Requirements
1. **Date-Hierarchy**: Default structure is `{base_dir}/{Category}/{YYYY}/{MonthName}/{Filename}`.
2. **AI Classification Priority**: If `scanned_file.ai_category` is populated by Gemma 3, it must take precedence over `scanned_file.basic_category`.
3. **Clean Filename Generation**: If `scanned_file.ai_proposed_name` is present, rename the file using `{ai_proposed_name}{extension}`.
4. **Collision Safety**: Always pass the computed destination through `resolve_collision(dest_path)` to append `_1`, `_2` instead of overwriting existing files.
5. **Reversibility**: Ensure the planned move works with `PlannedMove` so it is logged in SQLite `OperationLog` for `slothd undo`.

## Example Implementation Pattern
```python
if scanned_file.ai_category == "MyCategory" or scanned_file.extension in (".myext",):
    category_folder = base_dir / "MyCategory" / year_str / month_str
    target_name = f"{scanned_file.ai_proposed_name}{scanned_file.extension}" if scanned_file.ai_proposed_name else scanned_file.name
    return resolve_collision(category_folder / target_name)
```

Now, ask the user what category or file extensions they want to sort, and generate the corresponding code changes and unit test!
