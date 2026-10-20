/**
 * slothd — Web Dashboard Client Application
 * Vanilla ES6 JavaScript for optimal speed and responsiveness.
 */

document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    initIdlePolling();
    fetchStats();
    initScanner();
    initPreviewAndApprove();
    initSemanticSearch();
    initHistoryAndUndo();
    initAudioBriefing();
});

// ---------------------------------------------------------------------------
// Toast Notifications
// ---------------------------------------------------------------------------
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ---------------------------------------------------------------------------
// Tab Switching
// ---------------------------------------------------------------------------
function initTabs() {
    const tabButtons = document.querySelectorAll(".tab-btn");
    const tabPanes = document.querySelectorAll(".tab-pane");

    tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetId = btn.getAttribute("data-tab");

            tabButtons.forEach(b => b.classList.remove("active"));
            tabPanes.forEach(p => p.classList.remove("active"));

            btn.classList.add("active");
            const targetPane = document.getElementById(targetId);
            if (targetPane) {
                targetPane.classList.add("active");
            }
        });
    });
}

// ---------------------------------------------------------------------------
// Live Idle Polling
// ---------------------------------------------------------------------------
function initIdlePolling() {
    const idleBadge = document.getElementById("idle-status-badge");
    const idleText = document.getElementById("idle-status-text");

    async function checkIdle() {
        try {
            const res = await fetch("/api/status");
            if (!res.ok) return;
            const data = await res.json();

            if (data.is_idle) {
                idleBadge.className = "status-pill status-idle";
                idleText.textContent = `🦥 System Idle (${data.idle_seconds}s) — Daemon Active`;
            } else {
                idleBadge.className = "status-pill status-active";
                idleText.textContent = `User Active (${data.idle_seconds}s idle)`;
            }

            // Update header model label if available
            if (data.ollama_model) {
                const modelEl = document.getElementById("stat-model-name");
                if (modelEl) modelEl.textContent = data.ollama_model;
            }
        } catch (err) {
            console.debug("Idle check error:", err);
        }
    }

    checkIdle();
    setInterval(checkIdle, 5000);
}

// ---------------------------------------------------------------------------
// Overview Statistics
// ---------------------------------------------------------------------------
async function fetchStats() {
    try {
        const res = await fetch("/api/stats");
        if (!res.ok) return;
        const data = await res.json();

        const filesCount = document.getElementById("stat-files-count");
        const filesSize = document.getElementById("stat-files-size");
        const opsCount = document.getElementById("stat-ops-count");
        const batchesCount = document.getElementById("stat-batches-count");

        if (filesCount) filesCount.textContent = (data.target_files_count || 0).toLocaleString();
        if (filesSize) filesSize.textContent = `${data.target_size_mb || 0} MB across monitored dir`;
        if (opsCount) opsCount.textContent = (data.total_operations || 0).toLocaleString();
        if (batchesCount) batchesCount.textContent = `${data.total_batches || 0} batches (${data.undone_batches || 0} undone)`;

        // Render category chips in scanner tab
        renderCategoryChips(data.categories || {});
    } catch (err) {
        console.error("Error fetching stats:", err);
    }
}

function renderCategoryChips(categories) {
    const container = document.getElementById("category-chips-container");
    if (!container) return;

    container.innerHTML = "";
    const entries = Object.entries(categories);
    if (entries.length === 0) {
        container.innerHTML = `<span class="text-secondary" style="font-size: 13px;">No files found in monitored directory.</span>`;
        return;
    }

    entries.forEach(([cat, count]) => {
        const chip = document.createElement("div");
        chip.className = "chip";
        chip.innerHTML = `<span>${cat}</span><span class="chip-count">${count}</span>`;
        container.appendChild(chip);
    });
}

// ---------------------------------------------------------------------------
// Workspace Scanner Tab
// ---------------------------------------------------------------------------
function initScanner() {
    const scanBtn = document.getElementById("btn-run-scan");
    const scanInput = document.getElementById("scan-path-input");
    const tbody = document.getElementById("scanned-files-tbody");

    scanBtn.addEventListener("click", async () => {
        scanBtn.disabled = true;
        scanBtn.textContent = "Scanning...";

        try {
            const pathVal = scanInput.value.trim() || null;
            const res = await fetch("/api/scan", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: pathVal }),
            });

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || "Scan failed");
            }

            const data = await res.json();
            renderCategoryChips(data.categories || {});

            tbody.innerHTML = "";
            if (!data.sample_files || data.sample_files.length === 0) {
                tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No files found in directory.</td></tr>`;
                return;
            }

            data.sample_files.forEach(f => {
                const tr = document.createElement("tr");
                const hashPreview = f.sha256_hash ? f.sha256_hash.substring(0, 10) + "..." : "—";
                tr.innerHTML = `
                    <td><strong>${escapeHtml(f.name)}</strong></td>
                    <td><span class="badge badge-primary">${escapeHtml(f.basic_category)}</span></td>
                    <td>${f.size_mb.toFixed(2)} MB</td>
                    <td>${escapeHtml(f.modified_at || "—")}</td>
                    <td><span class="mono-path">${hashPreview}</span></td>
                `;
                tbody.appendChild(tr);
            });

            showToast(`Scanned ${data.total_files} files successfully!`, "success");
            fetchStats();
        } catch (err) {
            showToast(err.message, "error");
        } finally {
            scanBtn.disabled = false;
            scanBtn.textContent = "Scan Now";
        }
    });
}

// ---------------------------------------------------------------------------
// AI Preview & Approve Tab
// ---------------------------------------------------------------------------
function initPreviewAndApprove() {
    const genBtn = document.getElementById("btn-generate-preview");
    const approveBtn = document.getElementById("btn-approve-moves");
    const quickOrganizeBtn = document.getElementById("btn-quick-organize");
    const tbody = document.getElementById("preview-moves-tbody");
    const banner = document.getElementById("preview-banner");
    const bannerText = document.getElementById("preview-banner-text");
    const previewPathInput = document.getElementById("preview-path-input");
    const batchSizeSelect = document.getElementById("preview-batch-size");
    const scanPathInput = document.getElementById("scan-path-input");

    // Automatically sync path from scanner tab if empty
    if (previewPathInput && scanPathInput) {
        scanPathInput.addEventListener("input", () => {
            if (!previewPathInput.value || previewPathInput.value === "test_workspace/messy_inbox") {
                previewPathInput.value = scanPathInput.value;
            }
        });
    }

    let currentPlannedMoves = [];
    let lastTargetPath = null;

    async function generatePlan() {
        const rawPath = (previewPathInput && previewPathInput.value.trim()) ||
                        (scanPathInput && scanPathInput.value.trim()) ||
                        "test_workspace/messy_inbox";
        const batchSize = batchSizeSelect ? parseInt(batchSizeSelect.value, 10) : 5;
        lastTargetPath = rawPath;

        genBtn.disabled = true;
        genBtn.innerHTML = `<span>⏳</span> Analyzing with Local AI...`;
        approveBtn.disabled = true;

        try {
            const res = await fetch("/api/preview", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: rawPath, batch_size: batchSize }),
            });

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || "Preview failed");
            }

            const data = await res.json();
            currentPlannedMoves = data.planned_moves || [];

            tbody.innerHTML = "";
            if (currentPlannedMoves.length === 0) {
                tbody.innerHTML = `<tr><td colspan="4" class="empty-state">No files require moving. Workspace is already tidy!</td></tr>`;
                banner.style.display = "none";
                approveBtn.disabled = true;
                return;
            }

            currentPlannedMoves.forEach(m => {
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td><span class="mono-path">${escapeHtml(m.file_name)}</span></td>
                    <td><span class="badge badge-violet">${escapeHtml(m.category)}</span></td>
                    <td><span class="text-secondary">${escapeHtml(m.reason)}</span></td>
                    <td><span class="mono-path">${escapeHtml(m.destination)}</span></td>
                `;
                tbody.appendChild(tr);
            });

            banner.style.display = "flex";
            bannerText.textContent = `Local AI planned ${currentPlannedMoves.length} moves. Review the destinations below and click "Approve & Move Files".`;
            approveBtn.disabled = false;
            showToast(`Generated AI plan for ${currentPlannedMoves.length} files`, "success");
        } catch (err) {
            showToast(err.message, "error");
        } finally {
            genBtn.disabled = false;
            genBtn.innerHTML = `<span>✨</span> Generate AI Plan`;
        }
    }

    genBtn.addEventListener("click", generatePlan);

    if (quickOrganizeBtn) {
        quickOrganizeBtn.addEventListener("click", () => {
            const previewTab = document.querySelector('[data-tab="tab-preview"]');
            if (previewTab) previewTab.click();
            generatePlan();
        });
    }

    approveBtn.addEventListener("click", async () => {
        if (!currentPlannedMoves || currentPlannedMoves.length === 0) {
            showToast("No planned moves to execute. Generate a plan first.", "warning");
            return;
        }

        approveBtn.disabled = true;
        approveBtn.innerHTML = `<span>⏳</span> Moving files...`;
        const batchSize = batchSizeSelect ? parseInt(batchSizeSelect.value, 10) : 5;

        try {
            const res = await fetch("/api/execute", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    path: lastTargetPath,
                    batch_size: batchSize,
                    moves: currentPlannedMoves,
                }),
            });

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || "Execution failed");
            }

            const data = await res.json();
            showToast(`Organized ${data.executed_count} files! Batch ID: ${data.batch_id}`, "success");

            // Clear table and update stats
            tbody.innerHTML = `<tr><td colspan="4" class="empty-state">Batch completed! All ${data.executed_count} files moved to destination folders.</td></tr>`;
            banner.style.display = "none";
            currentPlannedMoves = [];
            fetchStats();
            loadHistory();
        } catch (err) {
            showToast(err.message, "error");
        } finally {
            approveBtn.disabled = true;
            approveBtn.innerHTML = `<span>✓</span> Approve & Move Files`;
        }
    });
}

// ---------------------------------------------------------------------------
// Semantic Search Tab
// ---------------------------------------------------------------------------
function initSemanticSearch() {
    const input = document.getElementById("search-query-input");
    const btn = document.getElementById("btn-search-exec");
    const container = document.getElementById("search-results-container");
    const suggestions = document.querySelectorAll(".suggestion-tag");

    async function executeSearch(query) {
        if (!query.trim()) return;

        btn.disabled = true;
        btn.textContent = "Searching...";
        container.innerHTML = `<div class="empty-state">Computing embeddings and searching vector index...</div>`;

        try {
            const res = await fetch("/api/search", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query: query.trim(), limit: 5 }),
            });

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || "Search failed");
            }

            const data = await res.json();
            container.innerHTML = "";

            if (!data.results || data.results.length === 0) {
                container.innerHTML = `<div class="empty-state">No matching files found for "${escapeHtml(query)}". Try organizing some files first.</div>`;
                return;
            }

            data.results.forEach(r => {
                const card = document.createElement("div");
                card.className = "search-result-card";
                const simPct = Math.round((r.similarity_score || 0) * 100);
                const sourceBadge = r.source === "tiger_data" ? "Tiger Data pgvector" : "Local SQLite";

                card.innerHTML = `
                    <div class="search-result-header">
                        <span class="search-result-title">📄 ${escapeHtml(r.file_name)}</span>
                        <div style="display: flex; gap: 6px; align-items: center;">
                            <span class="badge badge-cyan">${sourceBadge}</span>
                            <span class="similarity-badge">${simPct}% match</span>
                        </div>
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center; margin: 4px 0;">
                        <span class="badge badge-primary">${escapeHtml(r.category || "General")}</span>
                        ${r.vendor ? `<span class="badge badge-emerald">Vendor: ${escapeHtml(r.vendor)}</span>` : ""}
                        ${r.file_date ? `<span class="badge badge-violet">Date: ${escapeHtml(r.file_date)}</span>` : ""}
                    </div>
                    <p class="text-secondary" style="font-size: 13px;">${escapeHtml(r.description || "No description available")}</p>
                    <div style="margin-top: 4px;">
                        <span class="mono-path">${escapeHtml(r.file_path)}</span>
                    </div>
                `;
                container.appendChild(card);
            });
        } catch (err) {
            showToast(err.message, "error");
            container.innerHTML = `<div class="empty-state" style="color: var(--rose-error);">Error: ${escapeHtml(err.message)}</div>`;
        } finally {
            btn.disabled = false;
            btn.textContent = "Search";
        }
    }

    btn.addEventListener("click", () => executeSearch(input.value));
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") executeSearch(input.value);
    });

    suggestions.forEach(s => {
        s.addEventListener("click", () => {
            const q = s.getAttribute("data-query");
            input.value = q;
            executeSearch(q);
        });
    });
}

// ---------------------------------------------------------------------------
// History & Undo Tab
// ---------------------------------------------------------------------------
function initHistoryAndUndo() {
    const undoBtn = document.getElementById("btn-undo-history");
    const quickUndoBtn = document.getElementById("btn-quick-undo");

    async function triggerUndo() {
        if (!confirm("Are you sure you want to reverse the most recent organize batch? Files will be moved back to their original locations.")) {
            return;
        }

        try {
            const res = await fetch("/api/undo", { method: "POST" });
            const data = await res.json();

            if (data.restored_count > 0) {
                showToast(`Restored ${data.restored_count} files!`, "success");
            } else {
                showToast("No operations to undo.", "info");
            }

            fetchStats();
            loadHistory();
        } catch (err) {
            showToast("Undo failed: " + err.message, "error");
        }
    }

    if (undoBtn) undoBtn.addEventListener("click", triggerUndo);
    if (quickUndoBtn) quickUndoBtn.addEventListener("click", triggerUndo);

    loadHistory();
}

async function loadHistory() {
    const tbody = document.getElementById("history-batches-tbody");
    const timelineEl = document.getElementById("activity-timeline");
    const modal = document.getElementById("batch-details-modal");
    const closeModalBtn = document.getElementById("btn-close-batch-modal");

    if (closeModalBtn && modal) {
        closeModalBtn.onclick = () => modal.classList.add("hidden");
        modal.onclick = (e) => {
            if (e.target === modal) modal.classList.add("hidden");
        };
    }

    try {
        const res = await fetch("/api/recent");
        if (!res.ok) return;
        const data = await res.json();

        const batches = data.recent_batches || [];

        // 1. Render Table
        if (tbody) {
            tbody.innerHTML = "";
            if (batches.length === 0) {
                tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No batches recorded in SQLite log yet.</td></tr>`;
            } else {
                batches.forEach(b => {
                    const tr = document.createElement("tr");
                    const statusBadge = b.undone
                        ? `<span class="badge" style="background: rgba(244, 63, 94, 0.15); color: var(--rose-error);">Undone</span>`
                        : `<span class="badge badge-emerald">Active</span>`;

                    tr.innerHTML = `
                        <td><span class="mono-path">${escapeHtml(b.batch_id)}</span></td>
                        <td><strong>${b.file_count}</strong> files</td>
                        <td>${escapeHtml(b.created_at)}</td>
                        <td>${statusBadge}</td>
                        <td>
                            <button class="btn btn-outline btn-sm btn-inspect" data-batch="${escapeHtml(b.batch_id)}">Inspect</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });

                tbody.querySelectorAll(".btn-inspect").forEach(btn => {
                    btn.addEventListener("click", () => inspectBatch(btn.getAttribute("data-batch")));
                });
            }
        }

        // 2. Render Timeline Cards
        if (timelineEl) {
            timelineEl.innerHTML = "";
            if (batches.length === 0) {
                timelineEl.innerHTML = `<div class="empty-state">No operations in timeline yet. Run an organize job to see history!</div>`;
            } else {
                batches.forEach(b => {
                    const card = document.createElement("div");
                    card.className = `timeline-card ${b.undone ? "undone" : ""}`;

                    const statusBadge = b.undone
                        ? `<span class="badge" style="background: rgba(244, 63, 94, 0.15); color: var(--rose-error);">Undone</span>`
                        : `<span class="badge badge-emerald">Active</span>`;

                    card.innerHTML = `
                        <div class="timeline-card-header">
                            <span class="timeline-batch-id">${escapeHtml(b.batch_id.slice(0, 16))}...</span>
                            ${statusBadge}
                        </div>
                        <div class="timeline-card-body">
                            <span class="timeline-file-count">${b.file_count}</span>
                            <span class="timeline-file-label">files organized</span>
                        </div>
                        <div class="timeline-card-footer">
                            <span class="timeline-time">${escapeHtml(b.created_at.split("T")[0] || b.created_at)}</span>
                            <button class="btn btn-outline btn-inspect-batch" data-batch="${escapeHtml(b.batch_id)}">Inspect</button>
                        </div>
                    `;
                    timelineEl.appendChild(card);
                });

                timelineEl.querySelectorAll(".btn-inspect-batch").forEach(btn => {
                    btn.addEventListener("click", () => inspectBatch(btn.getAttribute("data-batch")));
                });
            }
        }
    } catch (err) {
        console.error("Error loading history:", err);
    }
}

async function inspectBatch(batchId) {
    const modal = document.getElementById("batch-details-modal");
    const titleEl = document.getElementById("modal-batch-title");
    const subEl = document.getElementById("modal-batch-subtitle");
    const tbody = document.getElementById("modal-batch-tbody");

    if (!modal || !tbody) return;

    titleEl.textContent = `Batch Manifest`;
    subEl.textContent = `Batch ID: ${batchId}`;
    tbody.innerHTML = `<tr><td colspan="2" class="empty-state">Loading moves...</td></tr>`;
    modal.classList.remove("hidden");

    try {
        const res = await fetch(`/api/batch/${encodeURIComponent(batchId)}`);
        if (!res.ok) throw new Error("Failed to load batch details");
        const data = await res.json();
        const ops = data.operations || [];

        tbody.innerHTML = "";
        if (ops.length === 0) {
            tbody.innerHTML = `<tr><td colspan="2" class="empty-state">No file moves logged for this batch.</td></tr>`;
            return;
        }

        ops.forEach(op => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><span class="mono-path">${escapeHtml(op.source)}</span></td>
                <td><span class="mono-path" style="color: var(--sloth-emerald);">${escapeHtml(op.destination)}</span></td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="2" class="empty-state" style="color: var(--rose-error);">Error: ${escapeHtml(err.message)}</td></tr>`;
    }
}

// ---------------------------------------------------------------------------
// Audio Briefing Tab
// ---------------------------------------------------------------------------
function initAudioBriefing() {
    const refreshBtn = document.getElementById("btn-refresh-briefing");
    const scriptEl = document.getElementById("briefing-transcript-text");
    const audioEl = document.getElementById("sloth-audio-player");

    async function loadBriefing() {
        try {
            const res = await fetch("/api/briefing");
            if (!res.ok) return;
            const data = await res.json();

            if (scriptEl && data.script) {
                scriptEl.textContent = `"${data.script}"`;
            }

            if (audioEl && data.audio_url) {
                audioEl.src = `${data.audio_url}?t=${Date.now()}`;
            }
        } catch (err) {
            console.error("Error loading briefing:", err);
        }
    }

    if (refreshBtn) {
        refreshBtn.addEventListener("click", () => {
            showToast("Synthesizing fresh audio briefing...", "info");
            loadBriefing();
        });
    }

    loadBriefing();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
