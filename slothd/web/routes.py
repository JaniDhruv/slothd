"""API route definitions for slothd web dashboard."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from slothd.config import SlothdConfig
from slothd.daemon.idle_detector import get_idle_ms, is_idle
from slothd.engine.classifier import classify_batch
from slothd.engine.organizer import (
    OperationLog,
    execute_moves,
    plan_moves,
    undo_last_batch,
)
from slothd.engine.scanner import group_by_category, scan_directory
from slothd.engine.search import SearchEngine
from slothd.integrations.elevenlabs import (
    ElevenLabsClient,
    generate_briefing_script,
)
from slothd.integrations.sentry_tracing import trace_span

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------- #
#  Request / Response Models                                                 #
# --------------------------------------------------------------------------- #


class ScanRequest(BaseModel):
    path: str | None = Field(default=None, description="Directory path to scan")


class PreviewRequest(BaseModel):
    path: str | None = Field(default=None, description="Directory path to preview")
    batch_size: int = Field(default=20, ge=1, le=100)


class ExecuteRequest(BaseModel):
    path: str | None = Field(default=None, description="Directory path to organize")
    batch_size: int = Field(default=20, ge=1, le=100)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, description="Natural language search query")
    limit: int = Field(default=5, ge=1, le=20)


# --------------------------------------------------------------------------- #
#  Endpoints                                                                 #
# --------------------------------------------------------------------------- #


@router.get("/status")
def get_status() -> dict[str, Any]:
    """Get system and daemon status."""
    idle_ms = get_idle_ms()
    idle_sec = round(idle_ms / 1000, 1)
    cfg = SlothdConfig.from_env()

    return {
        "status": "healthy",
        "idle_ms": idle_ms,
        "idle_seconds": idle_sec,
        "is_idle": is_idle(threshold_seconds=cfg.idle_threshold_seconds),
        "idle_threshold_seconds": cfg.idle_threshold_seconds,
        "target_dirs": [str(p) for p in cfg.target_dirs],
        "ollama_host": cfg.ollama_host,
        "ollama_model": cfg.ollama_model,
        "version": "0.1.0",
    }


@router.get("/stats")
def get_stats() -> dict[str, Any]:
    """Get overall workspace and operation stats."""
    cfg = SlothdConfig.from_env()
    ops_log = OperationLog(cfg.ops_db_path)
    stats = ops_log.get_stats()
    ops_log.close()

    # Quick top-level check of primary target dir
    primary_dir = cfg.target_dirs[0] if cfg.target_dirs else Path.home() / "Downloads"
    category_counts: dict[str, int] = {}
    total_files = 0
    total_size_mb = 0.0

    if primary_dir.exists():
        files = scan_directory(primary_dir, recursive=False)
        total_files = len(files)
        total_size_mb = round(sum(f.size_mb for f in files), 2)
        grouped = group_by_category(files)
        category_counts = {cat: len(flist) for cat, flist in grouped.items()}

    return {
        **stats,
        "target_dir": str(primary_dir),
        "target_files_count": total_files,
        "target_size_mb": total_size_mb,
        "categories": category_counts,
    }


@router.post("/scan")
def trigger_scan(req: ScanRequest) -> dict[str, Any]:
    """Scan a directory and return file overview."""
    cfg = SlothdConfig.from_env()
    target_path = Path(req.path) if req.path else cfg.target_dirs[0]

    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"Directory '{target_path}' does not exist")

    with trace_span(op="scanner.scan_directory", description=str(target_path)):
        files = scan_directory(target_path)

    grouped = group_by_category(files)

    return {
        "scanned_path": str(target_path),
        "total_files": len(files),
        "categories": {cat: len(flist) for cat, flist in grouped.items()},
        "sample_files": [f.to_dict() for f in files[:15]],
    }


@router.post("/preview")
def preview_organization(req: PreviewRequest) -> dict[str, Any]:
    """Simulate Gemma 3 classification and file moves (dry run)."""
    cfg = SlothdConfig.from_env()
    target_path = Path(req.path) if req.path else cfg.target_dirs[0]

    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"Directory '{target_path}' does not exist")

    with trace_span(op="organizer.preview", description=f"Preview {target_path}"):
        files = scan_directory(target_path)
        batch = files[: req.batch_size]

        # Classify batch with Gemma 3
        classify_batch(
            batch,
            ollama_host=cfg.ollama_host,
            model=cfg.ollama_model,
            batch_size=req.batch_size,
        )

        # Plan moves
        moves = plan_moves(batch, base_dir=cfg.output_dir or target_path)

    return {
        "target_path": str(target_path),
        "planned_moves": [m.to_dict() for m in moves],
        "total_planned": len(moves),
    }


@router.post("/execute")
def execute_organization(req: ExecuteRequest) -> dict[str, Any]:
    """Execute AI classification and file reorganization."""
    cfg = SlothdConfig.from_env()
    target_path = Path(req.path) if req.path else cfg.target_dirs[0]

    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"Directory '{target_path}' does not exist")

    ops_log = OperationLog(cfg.ops_db_path)
    search_engine = SearchEngine(
        db_url=cfg.db_url,
        ollama_host=cfg.ollama_host,
        embed_model=cfg.embed_model,
    )

    batch_id = f"batch_{uuid.uuid4().hex[:8]}"

    with trace_span(op="organizer.execute", description=f"Batch {batch_id}"):
        files = scan_directory(target_path)
        batch = files[: req.batch_size]

        # 1. Classify
        classify_batch(
            batch,
            ollama_host=cfg.ollama_host,
            model=cfg.ollama_model,
            batch_size=req.batch_size,
        )

        # 2. Plan
        moves = plan_moves(batch, base_dir=cfg.output_dir or target_path)

        # 3. Execute
        executed = execute_moves(moves, ops_log, batch_id)

        # 4. Index in search engine
        for f in batch:
            try:
                search_engine.index_scanned_file(f)
            except Exception as e:
                logger.debug("Indexing failed for %s: %s", f.name, e)

    ops_log.close()

    return {
        "batch_id": batch_id,
        "executed_count": len(executed),
        "moves": [m.to_dict() for m in executed],
    }


@router.post("/undo")
def undo_batch() -> dict[str, Any]:
    """Undo the most recent batch of file moves."""
    cfg = SlothdConfig.from_env()
    ops_log = OperationLog(cfg.ops_db_path)

    with trace_span(op="organizer.undo", description="Undo last batch"):
        restored = undo_last_batch(ops_log)

    ops_log.close()

    return {
        "restored_count": restored,
        "message": f"Successfully reversed moves for {restored} files."
        if restored > 0
        else "No operations to undo.",
    }


@router.get("/recent")
def get_recent_history(limit: int = Query(default=10, ge=1, le=50)) -> dict[str, Any]:
    """Get recent operation batches from SQLite."""
    cfg = SlothdConfig.from_env()
    ops_log = OperationLog(cfg.ops_db_path)
    batches = ops_log.get_recent_batches(limit=limit)
    ops_log.close()

    return {"recent_batches": batches}


@router.post("/search")
def search_files(req: SearchRequest) -> dict[str, Any]:
    """Semantic query search across all indexed files."""
    cfg = SlothdConfig.from_env()
    engine = SearchEngine(
        db_url=cfg.db_url,
        ollama_host=cfg.ollama_host,
        embed_model=cfg.embed_model,
    )

    with trace_span(op="search.query", description=req.query):
        hits = engine.search(req.query, limit=req.limit)

    return {
        "query": req.query,
        "total_hits": len(hits),
        "results": [h.to_dict() for h in hits],
    }


@router.get("/briefing")
def get_audio_briefing() -> dict[str, Any]:
    """Generate audio briefing text and metadata."""
    cfg = SlothdConfig.from_env()
    ops_log = OperationLog(cfg.ops_db_path)
    stats = ops_log.get_stats()
    ops_log.close()

    total_ops = stats.get("total_operations", 0)
    script = generate_briefing_script(
        total_files=total_ops,
        categories={"Documents": total_ops} if total_ops > 0 else {},
    )

    return {
        "script": script,
        "audio_url": "/api/briefing/audio",
    }


@router.get("/briefing/audio")
def stream_audio_briefing() -> Response:
    """Stream synthesized audio briefing (WAV or MP3)."""
    cfg = SlothdConfig.from_env()
    ops_log = OperationLog(cfg.ops_db_path)
    stats = ops_log.get_stats()
    ops_log.close()

    total_ops = stats.get("total_operations", 0)
    script = generate_briefing_script(
        total_files=total_ops,
        categories={"Documents": total_ops} if total_ops > 0 else {},
    )

    client = ElevenLabsClient()
    audio_bytes = client.text_to_speech(script)

    media_type = "audio/mpeg" if client.is_available() else "audio/wav"
    return Response(content=audio_bytes, media_type=media_type)
