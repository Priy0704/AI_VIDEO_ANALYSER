// =========================================================================
// VideoIntel AI - Workspace State & Initialization
// =========================================================================
let currentVideoId = null;
let currentSessionId = null;
let currentVideoData = null;
let currentActiveTab = 'transcript';
let pollTimer = null;
let libraryVideosCache = [];
let libraryFilter = 'all';
let isTimelineScrubbing = false;
let chatScope = 'all';

document.addEventListener("DOMContentLoaded", () => {
    loadVideoList();
    loadHITLReviews();
    initTimelineScrubbing();

    const fileInput = document.getElementById("fileInput");
    if (fileInput) {
        fileInput.addEventListener("change", handleFileSelect);
    }

    const dropzone = document.getElementById("dropzone");
    if (dropzone) {
        dropzone.addEventListener("dragover", (e) => {
            e.preventDefault();
            dropzone.classList.add("dragover");
        });
        dropzone.addEventListener("dragleave", () => {
            dropzone.classList.remove("dragover");
        });
        dropzone.addEventListener("drop", async (e) => {
            e.preventDefault();
            dropzone.classList.remove("dragover");
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                await handleMultipleFiles(Array.from(e.dataTransfer.files));
            }
        });
    }

    // Video Player Playback Listeners for Multimodal Sync
    const player = document.getElementById("videoPlayer");
    if (player) {
        player.addEventListener("timeupdate", handleVideoTimeUpdate);
        player.addEventListener("seeked", handleVideoTimeUpdate);
        player.addEventListener("play", handleVideoTimeUpdate);
        player.addEventListener("loadedmetadata", () => {
            if (currentVideoData) {
                updateTimelineRuler(currentVideoData.duration_seconds || player.duration || 0);
            }
            handleVideoTimeUpdate();
        });
    }

    // Close popovers on click outside
    document.addEventListener("click", (e) => {
        const engineBtn = document.getElementById("btnEngineStatus");
        const enginePop = document.getElementById("enginePopover");
        if (enginePop && engineBtn && !engineBtn.contains(e.target) && !enginePop.contains(e.target)) {
            enginePop.style.display = "none";
        }

        const settingsBtn = document.getElementById("btnSettings");
        const settingsPop = document.getElementById("settingsPopover");
        if (settingsPop && settingsBtn && !settingsBtn.contains(e.target) && !settingsPop.contains(e.target)) {
            settingsPop.style.display = "none";
        }

        const layersBtn = document.getElementById("btnAiLayers");
        const layersDrop = document.getElementById("layersDropdown");
        if (layersDrop && layersBtn && !layersBtn.contains(e.target) && !layersDrop.contains(e.target)) {
            layersDrop.style.display = "none";
        }
    });
});

// =========================================================================
// Header Popovers & Actions
// =========================================================================
function toggleEnginePopover() {
    const pop = document.getElementById("enginePopover");
    if (!pop) return;
    pop.style.display = (pop.style.display === "block" ? "none" : "block");
}

function toggleSettingsPopover() {
    const pop = document.getElementById("settingsPopover");
    if (!pop) return;
    pop.style.display = (pop.style.display === "block" ? "none" : "block");
}

function quickJumpToSearch() {
    switchTab("search");
    const input = document.getElementById("videoSearchQueryInput");
    if (input) {
        input.focus();
    }
}

function toggleLayersMenu() {
    const menu = document.getElementById("layersDropdown");
    if (!menu) return;
    menu.style.display = (menu.style.display === "flex" ? "none" : "flex");
}

function toggleTrackVisibility(trackName) {
    const checkboxMap = {
        'scenes': { id: 'layerScenesToggle', row: 'trackScenesRow' },
        'speech': { id: 'layerSpeechToggle', row: 'trackSpeechRow' },
        'ocr': { id: 'layerOcrToggle', row: 'trackOcrRow' },
        'people': { id: 'layerPeopleToggle', row: 'trackPeopleRow' }
    };
    const item = checkboxMap[trackName];
    if (!item) return;
    const cb = document.getElementById(item.id);
    const row = document.getElementById(item.row);
    if (cb && row) {
        row.style.display = cb.checked ? "flex" : "none";
    }
}

// =========================================================================
// Helpers: Formatting & Escaping
// =========================================================================
function decodeUnicodeEscapes(str) {
    if (!str) return "";
    return String(str).replace(/\\u([0-9a-fA-F]{4})/g, (match, grp) => {
        try {
            return String.fromCharCode(parseInt(grp, 16));
        } catch {
            return match;
        }
    });
}

function escapeHtml(text) {
    if (!text) return "";
    const clean = decodeUnicodeEscapes(text);
    return String(clean)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

function formatSeconds(sec) {
    if (isNaN(sec) || sec === null || sec === undefined) return "00:00";
    const totalSec = Math.floor(Math.max(0, sec));
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60).toString().padStart(2, '0');
    const s = (totalSec % 60).toString().padStart(2, '0');
    if (h > 0) {
        return `${h}:${m}:${s}`;
    }
    return `${m}:${s}`;
}

function parseTimeToSeconds(timeStr) {
    if (!timeStr) return 0;
    const parts = timeStr.trim().split(':').map(Number);
    if (parts.length === 2) {
        return parts[0] * 60 + parts[1];
    } else if (parts.length === 3) {
        return parts[0] * 3600 + parts[1] * 60 + parts[2];
    }
    return parseFloat(timeStr) || 0;
}

// =========================================================================
// Video Ingestion & Transfers
// =========================================================================
function switchUploadMode(mode) {
    const btnFile = document.getElementById("btnModeFile");
    const btnUrl = document.getElementById("btnModeUrl");
    const dropzone = document.getElementById("dropzone");
    const paneUrl = document.getElementById("paneUrl");

    if (mode === 'file') {
        btnFile.classList.add("active");
        btnUrl.classList.remove("active");
        dropzone.style.display = "block";
        paneUrl.style.display = "none";
    } else {
        btnUrl.classList.add("active");
        btnFile.classList.remove("active");
        dropzone.style.display = "none";
        paneUrl.style.display = "block";
    }
}

function handleUrlKeyPress(e) {
    if (e.key === "Enter") {
        importFromUrl();
    }
}

let activeTransfers = [];

function updateActiveTransfer(id, updates) {
    const item = activeTransfers.find(t => t.id === id);
    if (item) {
        Object.assign(item, updates);
        renderActiveTransfers();
    }
}

function removeActiveTransfer(id) {
    activeTransfers = activeTransfers.filter(t => t.id !== id);
    renderActiveTransfers();
}

function renderActiveTransfers() {
    const container = document.getElementById("activeUploadsContainer");
    if (!container) return;
    if (activeTransfers.length === 0) {
        container.style.display = "none";
        container.innerHTML = "";
        return;
    }
    container.style.display = "flex";
    container.innerHTML = activeTransfers.map(t => `
        <div class="video-card" style="margin-bottom: 0.35rem; border-color: rgba(56,189,248,0.4);">
            <div class="video-thumb-wrap">
                <i class="${t.type === 'url' ? 'fa-solid fa-link' : 'fa-solid fa-cloud-arrow-up'}"></i>
            </div>
            <div class="video-card-info">
                <div class="video-card-title">${escapeHtml(t.name)}</div>
                <div class="progress-bar-bg" style="margin: 3px 0; height: 4px;">
                    <div class="progress-bar-fill" style="width: ${t.progressPct}%;"></div>
                </div>
                <div class="video-card-meta">
                    <span>${escapeHtml(t.stage || 'Uploading')}</span>
                    <span style="color: var(--primary); font-weight: 700;">${t.progressPct}%</span>
                </div>
            </div>
        </div>
    `).join("");
}

async function handleFileSelect(e) {
    if (e.target.files && e.target.files.length > 0) {
        await handleMultipleFiles(Array.from(e.target.files));
    }
}

async function handleMultipleFiles(files) {
    const validFiles = files.filter(f => /\.(mp4|mov|mkv|avi)$/i.test(f.name));
    if (validFiles.length === 0) {
        alert("Please select valid video files (.mp4, .mov, .mkv, .avi)");
        return;
    }
    for (const f of validFiles) {
        uploadVideoFile(f);
    }
}

function uploadVideoFile(file) {
    const transferId = 'transfer_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5);
    activeTransfers.push({
        id: transferId,
        name: file.name,
        type: 'file',
        progressPct: 0,
        speed: '0 MB/s',
        stage: `Uploading 0 / ${formatBytes(file.size)}`,
        status: 'uploading'
    });
    renderActiveTransfers();

    const formData = new FormData();
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    const startTime = Date.now();

    xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
            const percent = Math.min(99, Math.round((e.loaded / e.total) * 100));
            const elapsedSec = (Date.now() - startTime) / 1000;
            const speed = elapsedSec > 0 ? (e.loaded / (1024 * 1024) / elapsedSec).toFixed(1) : 0;
            updateActiveTransfer(transferId, {
                progressPct: percent,
                speed: `${speed} MB/s`,
                stage: `Uploading: ${formatBytes(e.loaded)} / ${formatBytes(e.total)}`
            });
        }
    };

    xhr.onload = async () => {
        const fileInput = document.getElementById("fileInput");
        if (fileInput) fileInput.value = "";

        if (xhr.status >= 200 && xhr.status < 300) {
            try {
                const data = JSON.parse(xhr.responseText);
                currentVideoId = data.video_id;
                updateActiveTransfer(transferId, {
                    progressPct: 100,
                    stage: "Uploaded! Multimodal indexing active...",
                    speed: ""
                });
                setTimeout(() => removeActiveTransfer(transferId), 2500);

                await loadVideoList();
                selectVideo(currentVideoId, true);
                pollVideoStatus(currentVideoId);
            } catch (err) {
                console.error("Parse error:", err);
                removeActiveTransfer(transferId);
            }
        } else {
            let errorMsg = `Upload failed (HTTP ${xhr.status})`;
            try {
                const err = JSON.parse(xhr.responseText);
                errorMsg = err.detail || JSON.stringify(err);
            } catch {}
            alert(errorMsg);
            removeActiveTransfer(transferId);
        }
    };

    xhr.onerror = () => {
        alert(`Network error uploading ${file.name}`);
        removeActiveTransfer(transferId);
    };

    xhr.open("POST", "/api/v1/videos/upload", true);
    xhr.send(formData);
}

async function importFromUrl() {
    const input = document.getElementById("videoUrlInput");
    const url = (input.value || "").trim();
    if (!url) {
        alert("Please enter a valid video stream or recording URL.");
        return;
    }

    const btn = document.getElementById("btnFetchUrl");
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> <span>Connecting...</span>`;

    const transferId = 'url_' + Date.now();
    activeTransfers.push({
        id: transferId,
        name: url.length > 35 ? url.substring(0, 32) + '...' : url,
        type: 'url',
        progressPct: 15,
        speed: '',
        stage: 'Establishing stream connection...',
        status: 'connecting'
    });
    renderActiveTransfers();

    try {
        const res = await fetch("/api/v1/videos/from-url", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url })
        });

        if (!res.ok) {
            let errorMsg = `Unable to process video (HTTP ${res.status})`;
            try {
                const err = await res.json();
                errorMsg = err.detail || JSON.stringify(err);
            } catch {}
            alert(`Fetch failed: ${errorMsg}`);
            removeActiveTransfer(transferId);
            return;
        }

        const data = await res.json();
        input.value = "";
        currentVideoId = data.video_id;
        updateActiveTransfer(transferId, {
            progressPct: 100,
            stage: "Stream accepted! Processing pipeline active...",
            speed: ""
        });
        setTimeout(() => removeActiveTransfer(transferId), 2500);

        await loadVideoList();
        selectVideo(currentVideoId, true);
        pollVideoStatus(currentVideoId);
    } catch (e) {
        alert(`Network error fetching video: ${e.message}`);
        removeActiveTransfer(transferId);
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-bolt"></i> <span>Fetch & Analyze</span>`;
    }
}

// =========================================================================
// Processing Experience & Stepper Pipeline
// =========================================================================
function pollVideoStatus(videoId) {
    if (pollTimer) clearInterval(pollTimer);

    const progressBox = document.getElementById("progressBox");
    const stageLabel = document.getElementById("stageLabel");
    const percentLabel = document.getElementById("percentLabel");
    const progressBar = document.getElementById("progressBar");

    if (progressBox) progressBox.style.display = "block";

    pollTimer = setInterval(async () => {
        try {
            const res = await fetch(`/api/v1/videos/${videoId}/status`);
            if (!res.ok) return;

            const data = await res.json();
            const pct = data.progress_pct || 0;
            const stage = data.current_stage || "Processing...";

            if (stageLabel) stageLabel.innerText = stage;
            if (percentLabel) percentLabel.innerText = `${pct}%`;
            if (progressBar) progressBar.style.width = `${pct}%`;

            updateProcessingStepper(pct, stage);

            if (data.status === "completed") {
                clearInterval(pollTimer);
                setTimeout(() => {
                    if (progressBox) progressBox.style.display = "none";
                    loadVideoList();
                    selectVideo(videoId, true);
                }, 800);
            } else if (data.status === "failed") {
                clearInterval(pollTimer);
                if (stageLabel) {
                    stageLabel.innerText = `Failed: ${data.error_message || "Unknown error"}`;
                    stageLabel.style.color = "var(--accent-rose)";
                }
                loadVideoList();
                if (currentVideoId === videoId) {
                    selectVideo(videoId, true);
                }
            }
        } catch (e) {
            console.error("Status polling error:", e);
        }
    }, 1500);
}

function updateProcessingStepper(pct, stage) {
    const stepUpload = document.getElementById("stepUpload");
    const stepAudio = document.getElementById("stepAudio");
    const stepVisual = document.getElementById("stepVisual");
    const stepIndex = document.getElementById("stepIndex");

    if (!stepUpload || !stepAudio || !stepVisual || !stepIndex) return;

    if (pct >= 10) {
        stepUpload.className = "stepper-step completed";
        stepUpload.innerHTML = `<i class="fa-solid fa-circle-check"></i> <span>Video Uploaded</span>`;
    }
    if (pct >= 35) {
        stepAudio.className = "stepper-step completed";
        stepAudio.innerHTML = `<i class="fa-solid fa-circle-check"></i> <span>Audio Normalization & ASR</span>`;
        stepVisual.className = "stepper-step active";
        stepVisual.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> <span>Multimodal Visual Sampling</span>`;
    } else {
        stepAudio.className = "stepper-step active";
        stepAudio.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> <span>Audio Normalization & ASR</span>`;
    }
    if (pct >= 70) {
        stepVisual.className = "stepper-step completed";
        stepVisual.innerHTML = `<i class="fa-solid fa-circle-check"></i> <span>Multimodal Visual Sampling</span>`;
        stepIndex.className = "stepper-step active";
        stepIndex.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> <span>Temporal pgvector Indexing</span>`;
    }
    if (pct >= 98) {
        stepIndex.className = "stepper-step completed";
        stepIndex.innerHTML = `<i class="fa-solid fa-circle-check"></i> <span>Temporal pgvector Indexing</span>`;
    }
}

// =========================================================================
// Video Library Management & Real-time Filter
// =========================================================================
function setLibraryFilter(filterName) {
    libraryFilter = filterName;
    document.getElementById("filterAll").classList.toggle("active", filterName === 'all');
    document.getElementById("filterCompleted").classList.toggle("active", filterName === 'completed');
    document.getElementById("filterProcessing").classList.toggle("active", filterName === 'processing');
    renderLibraryList();
}

function filterLibraryVideos() {
    renderLibraryList();
}

async function loadVideoList() {
    try {
        const res = await fetch("/api/v1/videos");
        if (!res.ok) return;
        libraryVideosCache = await res.json();
        renderLibraryList();

        // Check if currently selected video was processing and now completed
        if (currentVideoId && currentVideoData && (currentVideoData.status === 'processing' || currentVideoData.status === 'queued')) {
            const currentInLib = libraryVideosCache.find(v => v.video_id === currentVideoId);
            if (currentInLib && currentInLib.status === 'completed') {
                selectVideo(currentVideoId, true);
            }
        }

        // Keep background polling alive while any video is queued or processing
        const hasActive = libraryVideosCache.some(v => v.status === 'queued' || v.status === 'processing');
        if (hasActive && !window.libraryPollInterval) {
            window.libraryPollInterval = setInterval(async () => {
                await loadVideoList();
            }, 2500);
        } else if (!hasActive && window.libraryPollInterval) {
            clearInterval(window.libraryPollInterval);
            window.libraryPollInterval = null;
        }

        // Auto-select first completed if none active
        if (!currentVideoId && libraryVideosCache.length > 0) {
            const firstCompleted = libraryVideosCache.find(v => v.status === "completed") || libraryVideosCache[0];
            selectVideo(firstCompleted.video_id);
        }

        // Update All Videos scope badge count
        const completedCount = libraryVideosCache.filter(v => v.status === 'completed').length;
        const scopeBadge = document.getElementById("scopeAllCountBadge");
        if (scopeBadge) scopeBadge.innerText = completedCount;
        const scopePill = document.getElementById("scopeAllCountPill");
        if (scopePill) scopePill.innerText = completedCount;
    } catch (e) {
        console.error("Error loading videos:", e);
    }
}

function renderLibraryList() {
    const listContainer = document.getElementById("videoList");
    if (!listContainer) return;

    const query = (document.getElementById("videoLibrarySearch")?.value || "").toLowerCase().trim();

    let filtered = libraryVideosCache.filter(v => {
        if (libraryFilter === 'completed' && v.status !== 'completed') return false;
        if (libraryFilter === 'processing' && (v.status !== 'processing' && v.status !== 'queued')) return false;
        if (query && !v.filename.toLowerCase().includes(query)) return false;
        return true;
    });

    if (filtered.length === 0) {
        listContainer.innerHTML = '<p style="font-size: 0.76rem; color: var(--text-dark); text-align: center; padding-top: 1rem;">No matching videos.</p>';
        return;
    }

    listContainer.innerHTML = filtered.map(v => {
        const isSelected = (v.video_id === currentVideoId);
        let statusBadge = '';
        if (v.status === 'completed') {
            statusBadge = `<span style="color: #34d399;"><i class="fa-solid fa-circle-check"></i> Analyzed</span>`;
        } else if (v.status === 'failed') {
            statusBadge = `<span style="color: #f87171;"><i class="fa-solid fa-circle-exclamation"></i> Failed</span>`;
        } else {
            statusBadge = `<span style="color: #38bdf8;"><i class="fa-solid fa-spinner fa-spin"></i> ${v.progress_pct || 0}%</span>`;
        }

        return `
            <div class="video-card ${isSelected ? 'active' : ''}" onclick="selectVideo('${v.video_id}')">
                <div class="video-thumb-wrap">
                    <i class="fa-solid fa-film"></i>
                </div>
                <div class="video-card-info">
                    <div class="video-card-title" title="${escapeHtml(v.filename)}">${escapeHtml(v.filename)}</div>
                    <div class="video-card-meta">
                        <span><i class="fa-regular fa-clock"></i> ${v.duration_seconds ? formatSeconds(v.duration_seconds) : 'N/A'}</span>
                        <span class="video-card-status">${statusBadge}</span>
                    </div>
                </div>
                <button class="btn-delete-card" title="Delete video" onclick="deleteVideo(event, '${v.video_id}')">
                    <i class="fa-solid fa-trash-can"></i>
                </button>
            </div>
        `;
    }).join("");
}

async function clearFailedVideos() {
    if (!confirm("Clean up all failed video entries from the library?")) return;
    try {
        const res = await fetch("/api/v1/videos/clear-failed", { method: "POST" });
        if (res.ok) {
            await loadVideoList();
        }
    } catch (e) {
        console.error("Error clearing failed videos:", e);
    }
}

async function deleteVideo(event, videoId) {
    event.stopPropagation();
    if (!confirm("Are you sure you want to delete this video?")) return;

    try {
        const res = await fetch(`/api/v1/videos/${videoId}`, { method: "DELETE" });
        if (res.ok) {
            if (currentVideoId === videoId) {
                currentVideoId = null;
                currentVideoData = null;
                if (pollTimer) {
                    clearInterval(pollTimer);
                    pollTimer = null;
                }
                const player = document.getElementById("videoPlayer");
                if (player) {
                    player.src = "";
                    player.load();
                }
                document.getElementById("playerTitle").innerText = "Select a video from library";
                document.getElementById("playerMetaBadge").style.display = "none";
                renderTabContent();
                clearTimelineTracks();
            }
            loadVideoList();
        } else {
            alert("Failed to delete video.");
        }
    } catch (e) {
        console.error("Error deleting video:", e);
    }
}

// =========================================================================
// Video Selection & Seamless Loading
// =========================================================================
async function selectVideo(videoId, forceRefresh = false) {
    if (!forceRefresh && videoId === currentVideoId && currentVideoData && currentVideoData.status === 'completed') {
        return; // Prevent unnecessary reload and playhead interruption
    }

    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }

    currentVideoId = videoId;
    currentSessionId = null;
    renderLibraryList();
    loadHITLReviews();

    const player = document.getElementById("videoPlayer");
    const streamUrl = `/api/v1/videos/${videoId}/stream`;
    if (player.src !== window.location.origin + streamUrl) {
        player.src = streamUrl;
    }

    try {
        const res = await fetch(`/api/v1/videos/${videoId}`);
        if (!res.ok) return;
        currentVideoData = await res.json();

        // If video is still processing or queued, resume polling
        if (currentVideoData.status === 'processing' || currentVideoData.status === 'queued') {
            pollVideoStatus(videoId);
        }

        // Update active dot in This Video scope button
        const activeDot = document.getElementById("currentVideoActiveDot");
        if (activeDot) activeDot.style.display = "inline-block";

        // If in individual scope, update copilot focus subtitle and placeholder
        if (chatScope === 'current') {
            const shortName = currentVideoData.filename.length > 28 
                ? currentVideoData.filename.substring(0, 26) + '..' 
                : currentVideoData.filename;
            const subtitle = document.getElementById("copilotSubtitle");
            if (subtitle) {
                subtitle.innerHTML = `<span class="pulse-dot-emerald" id="copilotPulseDot"></span> <span id="copilotScopeText">Focused on: <strong style="color: #34d399;">${escapeHtml(shortName)}</strong></span>`;
            }
            const input = document.getElementById("queryInput");
            if (input) input.placeholder = `Ask anything about ${shortName}...`;
        }

        // Update Tab Badges
        const segments = currentVideoData.segments || [];
        const rawTranscripts = currentVideoData.raw_transcripts || [];
        const transcriptCount = rawTranscripts.length > 0 
            ? rawTranscripts.length 
            : segments.filter(s => s.transcript_text && s.transcript_text.trim().length > 0).length;
        const visualSegments = segments.filter(s => s.visual_description && s.visual_description.trim().length > 0);

        document.getElementById("tabTranscriptBadge").innerText = transcriptCount;
        document.getElementById("tabVisualsBadge").innerText = visualSegments.length;

        // Auto select tab
        if (transcriptCount > 0) {
            currentActiveTab = 'transcript';
        } else {
            currentActiveTab = 'visuals';
        }

        renderTabContent();
        switchTab(currentActiveTab);

        // Build Multimodal Timeline Tracks
        renderMultimodalTimeline(currentVideoData);
    } catch (e) {
        console.error("Error fetching video details:", e);
    }
}

function switchTab(tabName) {
    currentActiveTab = tabName;

    const btnTranscript = document.getElementById("tabBtnTranscript");
    const btnVisuals = document.getElementById("tabBtnVisuals");
    const btnOverview = document.getElementById("tabBtnOverview");

    if (btnTranscript) btnTranscript.classList.toggle("active", tabName === 'transcript');
    if (btnVisuals) btnVisuals.classList.toggle("active", tabName === 'visuals');
    if (btnOverview) btnOverview.classList.toggle("active", tabName === 'overview');

    const paneTranscript = document.getElementById("paneTranscript");
    const paneVisuals = document.getElementById("paneVisuals");
    const paneOverview = document.getElementById("paneOverview");

    if (paneTranscript) paneTranscript.style.display = (tabName === 'transcript' ? 'flex' : 'none');
    if (paneVisuals) paneVisuals.style.display = (tabName === 'visuals' ? 'flex' : 'none');
    if (paneOverview) paneOverview.style.display = (tabName === 'overview' ? 'flex' : 'none');

    setTimeout(() => {
        handleVideoTimeUpdate();
    }, 40);
}

// =========================================================================
// Interactive Multimodal Timeline System & Scrubbing
// =========================================================================
function clearTimelineTracks() {
    const sc = document.getElementById("trackScenesBlocks");
    const sp = document.getElementById("trackSpeechBlocks");
    const oc = document.getElementById("trackOcrBlocks");
    const pe = document.getElementById("trackPeopleBlocks");
    const ph = document.getElementById("timelinePlayhead");
    const td = document.getElementById("timelineTimeDisplay");
    if (sc) sc.innerHTML = "";
    if (sp) sp.innerHTML = "";
    if (oc) oc.innerHTML = "";
    if (pe) pe.innerHTML = "";
    if (ph) ph.style.left = "0%";
    if (td) td.innerText = "00:00 / 00:00";
}

function updateTimelineRuler(totalDuration) {
    const ruler = document.getElementById("timelineRuler");
    if (!ruler || totalDuration <= 0) return;
    const t0 = "00:00";
    const t25 = formatSeconds(totalDuration * 0.25);
    const t50 = formatSeconds(totalDuration * 0.50);
    const t75 = formatSeconds(totalDuration * 0.75);
    const t100 = formatSeconds(totalDuration);
    ruler.innerHTML = `
        <span>${t0}</span>
        <span>${t25}</span>
        <span>${t50}</span>
        <span>${t75}</span>
        <span>${t100}</span>
    `;
}

function initTimelineScrubbing() {
    const area = document.getElementById("timelineTrackArea");
    if (!area) return;

    const scrub = (e) => {
        if (!currentVideoData) return;
        const rect = area.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const ratio = Math.max(0, Math.min(1, clickX / rect.width));
        const duration = currentVideoData.duration_seconds || document.getElementById("videoPlayer")?.duration || 1.0;
        const targetSeconds = ratio * duration;
        seekVideo(targetSeconds);
    };

    area.addEventListener("mousedown", (e) => {
        isTimelineScrubbing = true;
        scrub(e);
    });

    window.addEventListener("mousemove", (e) => {
        if (isTimelineScrubbing) {
            scrub(e);
        }
    });

    window.addEventListener("mouseup", () => {
        isTimelineScrubbing = false;
    });
}

function renderMultimodalTimeline(videoData) {
    clearTimelineTracks();
    const duration = videoData.duration_seconds || 1.0;
    updateTimelineRuler(duration);

    const segments = videoData.segments || [];
    const rawTranscripts = videoData.raw_transcripts || [];

    // 1. SCENES TRACK
    const scenesContainer = document.getElementById("trackScenesBlocks");
    if (scenesContainer && segments.length > 0) {
        scenesContainer.innerHTML = segments.map((seg, idx) => {
            const left = (seg.start_time / duration) * 100;
            const width = Math.max(0.6, ((seg.end_time - seg.start_time) / duration) * 100);
            return `
                <div class="track-segment-block track-scene-block" 
                     style="left: ${left.toFixed(2)}%; width: ${width.toFixed(2)}%;"
                     title="Scene ${idx + 1}: ${formatSeconds(seg.start_time)} - ${formatSeconds(seg.end_time)}"
                     onclick="event.stopPropagation(); seekVideo(${seg.start_time});">
                </div>
            `;
        }).join("");
    }

    // 2. SPEECH TRACK
    const speechContainer = document.getElementById("trackSpeechBlocks");
    if (speechContainer) {
        let speechItems = [];
        if (rawTranscripts.length > 0) {
            speechItems = rawTranscripts;
        } else {
            speechItems = segments.filter(s => s.transcript_text && s.transcript_text.trim().length > 0);
        }

        speechContainer.innerHTML = speechItems.map(item => {
            const st = item.start !== undefined ? item.start : item.start_time;
            const et = item.end !== undefined ? item.end : item.end_time;
            const txt = item.text || item.transcript_text || "";
            const left = (st / duration) * 100;
            const width = Math.max(0.4, ((et - st) / duration) * 100);
            return `
                <div class="track-segment-block track-speech-block"
                     style="left: ${left.toFixed(2)}%; width: ${width.toFixed(2)}%;"
                     title="Speech [${formatSeconds(st)} - ${formatSeconds(et)}]: ${escapeHtml(txt.substring(0, 50))}"
                     onclick="event.stopPropagation(); seekVideo(${st});">
                </div>
            `;
        }).join("");
    }

    // 3. OCR TRACK
    const ocrContainer = document.getElementById("trackOcrBlocks");
    if (ocrContainer) {
        const ocrSegments = segments.filter(s => {
            const v = (s.visual_description || "").toLowerCase();
            return v.includes("ocr") || v.includes("visible text") || v.includes("on-screen text");
        });
        ocrContainer.innerHTML = ocrSegments.map(seg => {
            const left = (seg.start_time / duration) * 100;
            const width = Math.max(0.8, ((seg.end_time - seg.start_time) / duration) * 100);
            return `
                <div class="track-segment-block track-ocr-block"
                     style="left: ${left.toFixed(2)}%; width: ${width.toFixed(2)}%;"
                     title="OCR Text Detected [${formatSeconds(seg.start_time)}]"
                     onclick="event.stopPropagation(); seekVideo(${seg.start_time});">
                </div>
            `;
        }).join("");
    }

    // 4. PEOPLE TRACK
    const peopleContainer = document.getElementById("trackPeopleBlocks");
    if (peopleContainer) {
        const peopleSegments = segments.filter(s => {
            const v = (s.visual_description || "").toLowerCase();
            return v.includes("person") || v.includes("people") || v.includes("presenter") || v.includes("speaker") || v.includes("audience");
        });
        peopleContainer.innerHTML = peopleSegments.map(seg => {
            const left = (seg.start_time / duration) * 100;
            const width = Math.max(0.8, ((seg.end_time - seg.start_time) / duration) * 100);
            return `
                <div class="track-segment-block track-people-block"
                     style="left: ${left.toFixed(2)}%; width: ${width.toFixed(2)}%;"
                     title="People Detected [${formatSeconds(seg.start_time)}]"
                     onclick="event.stopPropagation(); seekVideo(${seg.start_time});">
                </div>
            `;
        }).join("");
    }
}

function handleTimelineClick(event) {
    const area = document.getElementById("timelineTrackArea");
    const player = document.getElementById("videoPlayer");
    if (!area || !player || !currentVideoData) return;

    const rect = area.getBoundingClientRect();
    const clickX = event.clientX - rect.left;
    const ratio = Math.max(0, Math.min(1, clickX / rect.width));
    const duration = currentVideoData.duration_seconds || player.duration || 0;
    const targetSeconds = ratio * duration;
    seekVideo(targetSeconds);
}



// =========================================================================
// Video Playback & Synchronized Highlighting
// =========================================================================
function handleVideoTimeUpdate() {
    const player = document.getElementById("videoPlayer");
    if (!player || !currentVideoData) return;

    const currentTime = player.currentTime;
    const duration = currentVideoData.duration_seconds || player.duration || 1.0;

    // 1. Move Timeline Playhead
    const playhead = document.getElementById("timelinePlayhead");
    if (playhead) {
        const pct = Math.max(0, Math.min(100, (currentTime / duration) * 100));
        playhead.style.left = `${pct.toFixed(2)}%`;
    }

    // 2. Update Timeline Digital Clock
    const timeDisplay = document.getElementById("timelineTimeDisplay");
    if (timeDisplay) {
        timeDisplay.innerText = `${formatSeconds(currentTime)} / ${formatSeconds(duration)}`;
    }

    // 3. Highlight Active Spoken Utterance in Transcript Tab
    if (currentActiveTab === 'transcript') {
        const paneTranscript = document.getElementById("paneTranscript");
        const items = document.querySelectorAll(".transcript-card");
        if (items.length > 0 && paneTranscript) {
            let activeItem = null;
            items.forEach(item => {
                const start = parseFloat(item.getAttribute("data-start")) || 0;
                const end = parseFloat(item.getAttribute("data-end")) || 0;
                if (!activeItem && currentTime >= start && currentTime <= (end + 0.35)) {
                    activeItem = item;
                }
            });

            // If at the start before the first utterance, align to first item
            if (!activeItem && items.length > 0) {
                const firstStart = parseFloat(items[0].getAttribute("data-start")) || 0;
                if (currentTime <= firstStart + 0.3) {
                    activeItem = items[0];
                }
            }

            items.forEach(item => {
                if (item === activeItem) {
                    if (!item.classList.contains("active-speech")) {
                        item.classList.add("active-speech");
                        const parentRect = paneTranscript.getBoundingClientRect();
                        const itemRect = item.getBoundingClientRect();
                        if (itemRect.top < parentRect.top || itemRect.bottom > parentRect.bottom) {
                            paneTranscript.scrollTo({
                                top: Math.max(0, item.offsetTop - paneTranscript.offsetTop - 20),
                                behavior: 'smooth'
                            });
                        }
                    }
                } else {
                    item.classList.remove("active-speech");
                }
            });
        }
    }

    // 4. Highlight Active Scene Card in Visual Scenes Tab
    if (currentActiveTab === 'visuals') {
        const paneVisuals = document.getElementById("paneVisuals");
        const sceneCards = document.querySelectorAll(".scene-card");
        if (sceneCards.length > 0 && paneVisuals) {
            let activeScene = null;
            sceneCards.forEach(card => {
                const start = parseFloat(card.getAttribute("data-start")) || 0;
                const end = parseFloat(card.getAttribute("data-end")) || 0;
                if (!activeScene && currentTime >= start && currentTime <= (end + 0.35)) {
                    activeScene = card;
                }
            });

            if (!activeScene && sceneCards.length > 0) {
                const firstStart = parseFloat(sceneCards[0].getAttribute("data-start")) || 0;
                if (currentTime <= firstStart + 0.3) {
                    activeScene = sceneCards[0];
                }
            }

            sceneCards.forEach(card => {
                if (card === activeScene) {
                    if (!card.classList.contains("active-scene")) {
                        card.classList.add("active-scene");
                        const parentRect = paneVisuals.getBoundingClientRect();
                        const cardRect = card.getBoundingClientRect();
                        if (cardRect.top < parentRect.top || cardRect.bottom > parentRect.bottom) {
                            paneVisuals.scrollTo({
                                top: Math.max(0, card.offsetTop - paneVisuals.offsetTop - 20),
                                behavior: 'smooth'
                            });
                        }
                    }
                } else {
                    card.classList.remove("active-scene");
                }
            });
        }
    }
}

function seekVideo(seconds) {
    const player = document.getElementById("videoPlayer");
    if (!player) return;

    let targetTime = Math.max(0, parseFloat(seconds) || 0);
    if (player.duration && !isNaN(player.duration)) {
        targetTime = Math.min(targetTime, player.duration);
    } else if (currentVideoData && currentVideoData.duration_seconds) {
        targetTime = Math.min(targetTime, currentVideoData.duration_seconds);
    }

    try {
        player.currentTime = targetTime;
    } catch (e) {
        player.addEventListener('loadedmetadata', () => {
            try { player.currentTime = targetTime; } catch {}
        }, { once: true });
    }

    const playPromise = player.play();
    if (playPromise !== undefined) {
        playPromise.catch(err => {
            console.debug("Autoplay prevented or deferred:", err);
        });
    }
}

// =========================================================================
// Visual Observation Parsing
// =========================================================================
function parseVisualObservations(rawText) {
    if (!rawText) return [];
    let clean = rawText.replace(/^At\s+\d+(\.\d+)?s\s+in\s+video:\s*/gi, "").trim();

    const blockSplitRegex = /(?=(?:\[FRAME:\s*[\d\.]+s?\])|(?:(?:^|\n)Headline:))/gi;
    let rawBlocks = clean.split(blockSplitRegex).map(b => b.trim()).filter(b => b.length > 0);

    if (rawBlocks.length === 0) {
        rawBlocks = [clean];
    }

    const observations = [];

    for (const block of rawBlocks) {
        let text = block;
        let frameTimestamp = null;
        const frameMatch = text.match(/\[FRAME:\s*([\d\.]+)s?\]/i);
        if (frameMatch) {
            frameTimestamp = parseFloat(frameMatch[1]);
            text = text.replace(/\[FRAME:\s*[\d\.]+s?\]/gi, "").trim();
        }

        let headline = "";
        let details = "";
        let visibleText = "";
        let objects = "";
        let actions = "";

        const onScreenMatch = text.match(/(?:Visible\s+Text\s*(?:&|and)?\s*Names|On-Screen\s+Text\s*(?:&|and)?\s*Names):\s*([\s\S]+?)(?=(?:(?:^|\n)(?:Headline|Details|Objects|Actions|\[FRAME)):|$)/i);
        if (onScreenMatch) visibleText = onScreenMatch[1].trim();

        const headMatch = text.match(/Headline:\s*([^\n]+)/i);
        if (headMatch) headline = headMatch[1].trim();

        const detMatch = text.match(/Details:\s*([\s\S]+?)(?=(?:(?:^|\n)(?:Visible\s+Text|Objects|Actions|Headline|\[FRAME)):|$)/i);
        if (detMatch) details = detMatch[1].trim();

        const objMatch = text.match(/Objects:\s*([^\n]+)/i);
        if (objMatch) objects = objMatch[1].trim();

        const actMatch = text.match(/Actions:\s*([^\n]+)/i);
        if (actMatch) actions = actMatch[1].trim();

        if (!headline && !details) {
            const firstDot = text.indexOf(". ");
            if (firstDot > 8 && firstDot < 120) {
                headline = text.substring(0, firstDot + 1).trim();
                details = text.substring(firstDot + 2).trim();
            } else if (text.length > 80) {
                headline = text.substring(0, 75).trim() + "...";
                details = text;
            } else {
                headline = text;
                details = text;
            }
        }

        if (visibleText && visibleText.toLowerCase() === "none") visibleText = "";

        observations.push({
            frameTimestamp,
            headline: headline || "Visual Scene Observation",
            details: details || headline,
            visibleText,
            objects,
            actions
        });
    }

    return observations;
}

// =========================================================================
// Render Inspector Tab Content (Transcript, Visuals, Overview)
// =========================================================================
function renderTabContent() {
    const paneTranscript = document.getElementById("paneTranscript");
    const paneVisuals = document.getElementById("paneVisuals");
    const paneOverview = document.getElementById("paneOverview");

    if (!currentVideoData) {
        if (paneTranscript) paneTranscript.innerHTML = `<div class="empty-state"><i class="fa-solid fa-microphone-lines fa-2x"></i><p>Select a video to view synchronized speech.</p></div>`;
        if (paneVisuals) paneVisuals.innerHTML = `<div class="empty-state"><i class="fa-solid fa-camera fa-2x"></i><p>Select a video to view visual scenes.</p></div>`;
        if (paneOverview) paneOverview.innerHTML = `<div class="empty-state"><i class="fa-solid fa-file-lines fa-2x"></i><p>Select a video to view executive summary.</p></div>`;
        return;
    }

    // Check Processing State
    if (currentVideoData.status === 'processing' || currentVideoData.status === 'queued') {
        const pct = currentVideoData.progress_pct || 0;
        const stage = currentVideoData.current_stage || "Processing Multimodal Pipeline...";
        const processingHtml = `
            <div class="empty-state">
                <i class="fa-solid fa-circle-notch fa-spin fa-2x" style="color: var(--primary);"></i>
                <p style="font-weight: 700; color: #f1f5f9; margin-top: 0.6rem; font-size: 0.9rem;">Your video is being analyzed (${pct}%)</p>
                <p style="font-size: 0.74rem; color: var(--text-muted); max-width: 320px; line-height: 1.45;">
                    Current stage: <strong style="color: var(--primary);">${escapeHtml(stage)}</strong>.<br>
                    Speech recognition, visual sampling, and pgvector embeddings will load automatically once complete.
                </p>
            </div>
        `;
        if (paneTranscript) paneTranscript.innerHTML = processingHtml;
        if (paneVisuals) paneVisuals.innerHTML = processingHtml;
        if (paneOverview) paneOverview.innerHTML = processingHtml;
        return;
    }

    // Check Error State
    if (currentVideoData.status === 'failed') {
        const failedHtml = `
            <div class="empty-state">
                <i class="fa-solid fa-triangle-exclamation fa-2x" style="color: var(--accent-rose);"></i>
                <p style="font-weight: 700; color: #f87171; margin-top: 0.6rem; font-size: 0.9rem;">Analysis Failed</p>
                <p style="font-size: 0.74rem; color: var(--text-muted); max-width: 320px; line-height: 1.45;">
                    ${escapeHtml(currentVideoData.error_message || "Video processing could not be completed.")}
                </p>
            </div>
        `;
        if (paneTranscript) paneTranscript.innerHTML = failedHtml;
        if (paneVisuals) paneVisuals.innerHTML = failedHtml;
        if (paneOverview) paneOverview.innerHTML = failedHtml;
        return;
    }

    const segments = currentVideoData.segments || [];

    // 1. TRANSCRIPT TAB
    if (paneTranscript) {
        const rawTranscripts = currentVideoData.raw_transcripts || [];
        let transcriptList = [];

        if (rawTranscripts.length > 0) {
            transcriptList = rawTranscripts.map(t => ({
                start_time: t.start,
                end_time: t.end,
                text: t.text
            }));
        } else {
            const transcriptSegments = segments.filter(s => s.transcript_text && s.transcript_text.trim().length > 0);
            transcriptSegments.forEach(s => {
                const text = s.transcript_text.trim();
                const last = transcriptList[transcriptList.length - 1];
                if (last && last.text === text) {
                    last.end_time = s.end_time;
                } else {
                    transcriptList.push({
                        start_time: s.start_time,
                        end_time: s.end_time,
                        text: text
                    });
                }
            });
        }

        if (transcriptList.length === 0) {
            paneTranscript.innerHTML = `
                <div class="empty-state">
                    <i class="fa-solid fa-microphone-slash fa-2x"></i>
                    <p>No spoken dialogue detected.<br>
                    <a href="javascript:void(0)" onclick="switchTab('visuals')" style="color: var(--primary); text-decoration: none; font-weight: 600;">View Visual Scenes Tab &rarr;</a></p>
                </div>
            `;
        } else {
            paneTranscript.innerHTML = transcriptList.map((g, idx) => {
                return `
                    <div class="transcript-card" id="transcript-card-${idx}" data-start="${g.start_time}" data-end="${g.end_time}" onclick="seekVideo(${g.start_time})">
                        <div class="transcript-header">
                            <button class="pill-time" title="Jump to ${formatSeconds(g.start_time)}" onclick="event.stopPropagation(); seekVideo(${g.start_time});">
                                <i class="fa-solid fa-microphone-lines" style="font-size: 0.55rem;"></i> ${formatSeconds(g.start_time)} - ${formatSeconds(g.end_time)}
                            </button>
                            <div style="flex: 1; min-width: 0;">
                                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 2px;">
                                    <span style="color: var(--primary); font-size: 0.72rem; font-weight: 700;">#${idx + 1}</span>
                                    <div class="transcript-hover-actions">
                                        <button class="btn-transcript-action" onclick="event.stopPropagation(); seekVideo(${g.start_time});">
                                            <i class="fa-solid fa-play"></i> Play
                                        </button>
                                        <button class="btn-transcript-action" onclick="event.stopPropagation(); askAiAboutTranscriptByIndex(${idx});">
                                            <i class="fa-solid fa-question"></i> Ask AI
                                        </button>
                                    </div>
                                </div>
                                <div style="color: #f1f5f9; font-size: 0.83rem; line-height: 1.55; font-weight: 400; word-break: break-word;">
                                    ${escapeHtml(g.text)}
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }).join("");
        }
    }

    // 2. VISUAL SCENES TAB
    if (paneVisuals) {
        const visualSegments = segments.filter(s => s.visual_description && s.visual_description.trim().length > 0);

        if (visualSegments.length === 0) {
            paneVisuals.innerHTML = `
                <div class="empty-state">
                    <i class="fa-solid fa-camera fa-2x"></i>
                    <p>No visual scenes indexed for this clip.</p>
                </div>
            `;
        } else {
            paneVisuals.innerHTML = visualSegments.map((s, idx) => {
                const observations = parseVisualObservations(s.visual_description);
                const firstObs = observations[0] || { headline: `Scene ${idx + 1}`, details: s.visual_description, visibleText: "" };
                const mainHeadline = firstObs.headline || `Scene ${idx + 1}`;

                // Meta attribute badges
                const descLower = (s.visual_description || "").toLowerCase();
                const hasPeople = descLower.includes("person") || descLower.includes("people") || descLower.includes("speaker") || descLower.includes("audience");
                const hasScreen = descLower.includes("slide") || descLower.includes("presentation") || descLower.includes("screen") || descLower.includes("display");
                const hasOcr = firstObs.visibleText && firstObs.visibleText.length > 0;

                return `
                    <div class="scene-card" id="scene-card-${idx}" data-start="${s.start_time}" data-end="${s.end_time}">
                        <div class="scene-card-header">
                            <button class="pill-time" title="Jump to ${formatSeconds(s.start_time)}" onclick="seekVideo(${s.start_time})">
                                <i class="fa-solid fa-camera" style="font-size: 0.55rem;"></i> ${formatSeconds(s.start_time)} - ${formatSeconds(s.end_time)}
                            </button>
                            <span style="font-size: 0.72rem; font-weight: 700; color: var(--primary);">Scene #${idx + 1}</span>
                        </div>

                        <div style="font-weight: 700; color: #f8fafc; font-size: 0.85rem; margin-top: 2px;">
                            ${escapeHtml(mainHeadline)}
                        </div>

                        <div class="scene-badges-row">
                            ${hasPeople ? '<span class="scene-meta-badge"><i class="fa-solid fa-users" style="color: #ec4899;"></i> People Detected</span>' : ''}
                            ${hasScreen ? '<span class="scene-meta-badge"><i class="fa-solid fa-tv" style="color: #38bdf8;"></i> Screen/Presentation</span>' : ''}
                            ${hasOcr ? '<span class="scene-meta-badge"><i class="fa-solid fa-font" style="color: #f59e0b;"></i> OCR Detected</span>' : ''}
                        </div>

                        <p style="margin: 0; color: #cbd5e1; font-size: 0.8rem; line-height: 1.5; white-space: pre-wrap;">
                            ${escapeHtml(firstObs.details)}
                        </p>

                        ${firstObs.visibleText ? `
                            <div style="padding: 0.4rem 0.55rem; background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.25); border-radius: 4px; font-size: 0.74rem;">
                                <span style="font-weight: 700; color: #f59e0b;"><i class="fa-solid fa-quote-left"></i> Visible Text:</span>
                                <span style="color: #f1f5f9;">${escapeHtml(firstObs.visibleText)}</span>
                            </div>
                        ` : ''}

                        <div class="scene-actions-row">
                            <button class="btn-scene-action" onclick="seekVideo(${s.start_time})">
                                <i class="fa-solid fa-play"></i> Play Scene
                            </button>
                            <button class="btn-scene-action" style="background: rgba(255,255,255,0.06); color: var(--text-secondary);" onclick="askAiAboutSceneByIndex(${idx})">
                                <i class="fa-solid fa-robot"></i> Ask Copilot
                            </button>
                        </div>
                    </div>
                `;
            }).join("");
        }
    }

    // 3. OVERVIEW TAB
    if (paneOverview) {
        paneOverview.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 0.75rem;">
                <div style="background: rgba(30, 41, 59, 0.4); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 0.85rem;">
                    <div style="font-weight: 700; color: #f8fafc; font-size: 0.85rem; margin-bottom: 0.4rem; display: flex; align-items: center; gap: 0.4rem;">
                        <i class="fa-solid fa-wand-magic-sparkles" style="color: var(--primary);"></i>
                        <span>AI Executive Summary</span>
                    </div>
                    <p style="color: #cbd5e1; font-size: 0.82rem; line-height: 1.6; margin: 0;">
                        ${escapeHtml(currentVideoData.summary || "Summary generation in progress...")}
                    </p>
                </div>


                <!-- Interactive Multimodal Timeline -->
                <div class="timeline-container" id="multimodalTimeline">
                    <div class="timeline-header">
                        <span>Multimodal Temporal Alignment</span>
                        <span class="timeline-time-display" id="timelineTimeDisplay">00:00 / 00:00</span>
                    </div>

                    <div class="timeline-track-area" id="timelineTrackArea" onclick="handleTimelineClick(event)">
                        <div class="timeline-ruler" id="timelineRuler">
                            <span>00:00</span>
                            <span>--:--</span>
                            <span>--:--</span>
                            <span>--:--</span>
                        </div>

                        <div class="timeline-tracks-stack" id="timelineTracksStack">
                            <div class="timeline-track-row" id="trackScenesRow">
                                <span class="track-label">Scenes</span>
                                <div class="track-blocks-container" id="trackScenesBlocks" style="width: 100%; height: 100%; position: relative;"></div>
                            </div>
                            <div class="timeline-track-row" id="trackSpeechRow">
                                <span class="track-label">Speech</span>
                                <div class="track-blocks-container" id="trackSpeechBlocks" style="width: 100%; height: 100%; position: relative;"></div>
                            </div>
                            <div class="timeline-track-row" id="trackOcrRow">
                                <span class="track-label">OCR</span>
                                <div class="track-blocks-container" id="trackOcrBlocks" style="width: 100%; height: 100%; position: relative;"></div>
                            </div>
                            <div class="timeline-track-row" id="trackPeopleRow">
                                <span class="track-label">People</span>
                                <div class="track-blocks-container" id="trackPeopleBlocks" style="width: 100%; height: 100%; position: relative;"></div>
                            </div>
                        </div>

                        <div class="timeline-playhead" id="timelinePlayhead"></div>
                    </div>
                </div>

                <div style="background: rgba(15, 23, 42, 0.5); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 0.75rem;">
                    <div style="font-size: 0.76rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; margin-bottom: 0.45rem;">
                        Technical Grounding Specification
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; font-size: 0.74rem;">
                        <div><span style="color: var(--text-dark);">Vector DB:</span> <strong style="color: var(--primary);">PostgreSQL + pgvector</strong></div>
                        <div><span style="color: var(--text-dark);">Audio Filter:</span> <strong style="color: #34d399;">Broadcast loudnorm</strong></div>
                        <div><span style="color: var(--text-dark);">Multimodal Model:</span> <strong style="color: #f1f5f9;">Gemini 3.6 Flash</strong></div>
                        <div><span style="color: var(--text-dark);">Temporal Fusion:</span> <strong style="color: #f1f5f9;">Midpoint Windowing</strong></div>
                    </div>
                </div>
            </div>
        `;
    }
}

// =========================================================================
// Search Inside Video Tab
// =========================================================================
function handleVideoSearchInput() {
    const query = (document.getElementById("videoSearchQueryInput")?.value || "").toLowerCase().trim();
    const resultsContainer = document.getElementById("videoSearchResults");
    const badge = document.getElementById("tabSearchBadge");
    if (!resultsContainer) return;

    if (!currentVideoData) {
        resultsContainer.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-film fa-2x"></i>
                <p>Please select a video from the library to search its dialogue and scenes.</p>
            </div>
        `;
        if (badge) badge.style.display = "none";
        return;
    }

    if (!query) {
        resultsContainer.innerHTML = `
            <p style="font-size: 0.78rem; color: var(--text-dark); text-align: center; padding-top: 1rem;">
                Type keywords above to find exact moments in dialogue or visual scenes.
            </p>
        `;
        if (badge) badge.style.display = "none";
        return;
    }

    const matches = [];

    // Search Dialogue
    const rawTranscripts = currentVideoData.raw_transcripts || [];
    rawTranscripts.forEach(t => {
        if (t.text && t.text.toLowerCase().includes(query)) {
            matches.push({
                type: 'Dialogue',
                timestamp: t.start,
                snippet: t.text
            });
        }
    });

    // Search Visual Descriptions & OCR
    const segments = currentVideoData.segments || [];
    segments.forEach((seg) => {
        const v = (seg.visual_description || "");
        if (v.toLowerCase().includes(query)) {
            matches.push({
                type: 'Visual Scene',
                timestamp: seg.start_time,
                snippet: v
            });
        }
    });

    if (badge) {
        badge.innerText = matches.length;
        badge.style.display = "inline-block";
    }

    if (matches.length === 0) {
        resultsContainer.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-magnifying-glass fa-2x"></i>
                <p>No occurrences of "<strong>${escapeHtml(query)}</strong>" found in this video.</p>
            </div>
        `;
        return;
    }

    const topMatches = matches.slice(0, 30);

    resultsContainer.innerHTML = `
        <div style="font-size: 0.72rem; color: var(--text-muted); margin-bottom: 0.35rem; font-weight: 600;">
            ${matches.length} matches found ${matches.length > 30 ? '(showing top 30)' : ''}:
        </div>
        ${topMatches.map(m => {
            const escaped = escapeHtml(m.snippet);
            const regex = new RegExp(`(${query.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&')})`, 'gi');
            const highlighted = escaped.replace(
                regex,
                '<mark style="background: rgba(56, 189, 248, 0.35); color: #fff; border-radius: 2px; padding: 0 2px;">$1</mark>'
            );
            return `
                <div class="scene-card" style="padding: 0.55rem; cursor: pointer;" onclick="seekVideo(${m.timestamp})">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.25rem;">
                        <button class="pill-time" onclick="event.stopPropagation(); seekVideo(${m.timestamp});">
                            <i class="fa-solid fa-play" style="font-size: 0.55rem;"></i> ${formatSeconds(m.timestamp)}
                        </button>
                        <span class="scene-meta-badge" style="font-size: 0.68rem;">
                            ${m.type === 'Dialogue' ? '<i class="fa-solid fa-microphone-lines" style="color: #34d399;"></i> Spoken Dialogue' : '<i class="fa-solid fa-eye" style="color: #38bdf8;"></i> Visual Scene'}
                        </span>
                    </div>
                    <p style="margin: 0; font-size: 0.78rem; line-height: 1.45; color: #cbd5e1;">
                        ${highlighted}
                    </p>
                </div>
            `;
        }).join("")}
    `;
}

// =========================================================================
// AI Copilot Actions & Interactive Timestamp Grounding
// =========================================================================
function askAiAboutSceneByIndex(idx) {
    if (!currentVideoData || !currentVideoData.segments || !currentVideoData.segments[idx]) return;
    const seg = currentVideoData.segments[idx];
    const obs = parseVisualObservations(seg.visual_description);
    const title = (obs[0] && obs[0].headline) || `Scene ${idx + 1}`;
    const prompt = `What is happening at ${formatSeconds(seg.start_time)} (${title})?`;
    sendQuickPrompt(prompt);
}

function askAiAboutTranscriptByIndex(idx) {
    if (!currentVideoData) return;
    const rawTranscripts = currentVideoData.raw_transcripts || [];
    let text = "";
    let time = 0;
    if (rawTranscripts.length > 0 && rawTranscripts[idx]) {
        text = rawTranscripts[idx].text;
        time = rawTranscripts[idx].start;
    } else if (currentVideoData.segments && currentVideoData.segments[idx]) {
        text = currentVideoData.segments[idx].transcript_text;
        time = currentVideoData.segments[idx].start_time;
    }
    const snippet = text.length > 60 ? text.substring(0, 57) + "..." : text;
    const prompt = `Explain what is being said around ${formatSeconds(time)}: "${snippet}"`;
    sendQuickPrompt(prompt);
}

function sendQuickPrompt(promptText) {
    const input = document.getElementById("queryInput");
    if (input) {
        input.value = promptText;
        sendChatMessage();
    }
}

function handleKeyPress(e) {
    if (e.key === "Enter") {
        sendChatMessage();
    }
}

function setChatScope(scope) {
    chatScope = scope;
    const btnAll = document.getElementById("scopeBtnAll");
    const btnCur = document.getElementById("scopeBtnCurrent");
    const input = document.getElementById("queryInput");
    const subtitle = document.getElementById("copilotSubtitle");
    const suggestionsBar = document.getElementById("chatSuggestionsBar");

    if (btnAll) btnAll.classList.toggle("active", scope === 'all');
    if (btnCur) {
        btnCur.classList.toggle("active", scope === 'current');
        btnCur.classList.toggle("individual-mode", scope === 'current');
    }

    if (scope === 'all') {
        if (input) input.placeholder = "Ask anything across all videos (e.g. trace persons, count people)...";
        if (subtitle) {
            const completedCount = libraryVideosCache.filter(v => v.status === 'completed').length;
            subtitle.innerHTML = `<span class="pulse-dot-cyan" id="copilotPulseDot"></span> <span id="copilotScopeText">Unified search across all <strong id="scopeAllCountBadge" style="color: #38bdf8;">${completedCount}</strong> videos</span>`;
        }
        if (suggestionsBar) {
            suggestionsBar.innerHTML = `
                <button class="suggestion-chip" onclick="sendQuickPrompt('Trace persons across all cameras')">✦ Trace persons across cameras</button>
                <button class="suggestion-chip" onclick="sendQuickPrompt('Total person count across all videos')">✦ Person count across videos</button>
                <button class="suggestion-chip" onclick="sendQuickPrompt('Summarize key activities across all videos')">✦ Summarize all videos</button>
                <button class="suggestion-chip" onclick="sendQuickPrompt('Find any suspicious activity')">✦ Suspicious activity</button>
            `;
        }
    } else {
        if (currentVideoData) {
            const shortName = currentVideoData.filename.length > 28 
                ? currentVideoData.filename.substring(0, 26) + '..' 
                : currentVideoData.filename;
            if (input) input.placeholder = `Ask anything about ${shortName}...`;
            if (subtitle) {
                subtitle.innerHTML = `<span class="pulse-dot-emerald" id="copilotPulseDot"></span> <span id="copilotScopeText">Focused on: <strong style="color: #34d399;">${escapeHtml(shortName)}</strong></span>`;
            }
        } else {
            if (input) input.placeholder = "Select a video from library to ask questions...";
            if (subtitle) {
                subtitle.innerHTML = `<span class="pulse-dot-emerald" id="copilotPulseDot"></span> <span id="copilotScopeText" style="color: #f59e0b;">Select a video from library to focus</span>`;
            }
        }
        if (suggestionsBar) {
            suggestionsBar.innerHTML = `
                <button class="suggestion-chip" onclick="sendQuickPrompt('Summarize this video')">✦ Summarize this video</button>
                <button class="suggestion-chip" onclick="sendQuickPrompt('Who is speaking?')">✦ Who is speaking?</button>
                <button class="suggestion-chip" onclick="sendQuickPrompt('What is shown on screen?')">✦ What is on screen?</button>
                <button class="suggestion-chip" onclick="sendQuickPrompt('Find key moments in this video')">✦ Key moments</button>
            `;
        }
    }
}

function jumpToVideoAndTimestamp(videoId, seconds) {
    const sec = Math.max(0, parseFloat(seconds) || 0);
    if (videoId && videoId !== currentVideoId) {
        selectVideo(videoId).then(() => {
            setTimeout(() => {
                seekVideo(sec);
            }, 350);
        });
    } else {
        seekVideo(sec);
    }
}

function jumpToVideoByFilenameAndTimestamp(filename, seconds) {
    const sec = Math.max(0, parseFloat(seconds) || 0);
    const clean = (filename || '').trim().toLowerCase();
    const matched = libraryVideosCache.find(v => {
        const fn = v.filename.toLowerCase();
        return fn === clean || fn.includes(clean) || clean.includes(fn);
    });
    if (matched) {
        jumpToVideoAndTimestamp(matched.video_id, sec);
    } else {
        seekVideo(sec);
    }
}

// Automatically detect any timestamps and cross-video references in AI answer and make them clickable
function makeTimestampsClickable(htmlText) {
    // 1. Convert markdown bold and italic
    let formatted = htmlText
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // 2. Convert [Video: filename | MM:SS–MM:SS] or [Video: filename | MM:SS]
    const videoTimelineRegex = /\[Video:\s*([^|\]]+)\s*\|\s*(\d{1,2}:\d{2})(?:[–-](\d{1,2}:\d{2}))?\]/g;
    formatted = formatted.replace(videoTimelineRegex, (match, vName, tStart, tEnd) => {
        const sec = parseTimeToSeconds(tStart);
        const cleanName = vName.trim();
        const shortName = cleanName.length > 20 ? cleanName.substring(0, 18) + '..' : cleanName;
        return `<button class="ai-time-jump" onclick="jumpToVideoByFilenameAndTimestamp('${escapeHtml(cleanName)}', ${sec})" title="Jump to ${escapeHtml(cleanName)} at ${tStart}"><i class="fa-solid fa-film" style="font-size:0.55rem"></i> ${escapeHtml(shortName)} ${tStart}</button>`;
    });

    // 3. Convert standard timestamps [MM:SS] or MM:SS
    const timestampRegex = /(?:\[)?\b(\d{1,2}:\d{2}(?::\d{2})?)\b(?:\])?/g;
    formatted = formatted.replace(timestampRegex, (match, timeStr) => {
        const sec = parseTimeToSeconds(timeStr);
        return `<button class="ai-time-jump" onclick="seekVideo(${sec})" title="Jump video to ${timeStr}"><i class="fa-solid fa-play" style="font-size:0.5rem"></i> ${timeStr}</button>`;
    });

    // 4. Convert "at X seconds" or "around X seconds"
    const secondsRegex = /\b(?:at|around|timestamp)\s+(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b/gi;
    formatted = formatted.replace(secondsRegex, (match, secStr) => {
        const sec = parseFloat(secStr);
        return `<button class="ai-time-jump" onclick="seekVideo(${sec})" title="Jump video to ${formatSeconds(sec)}"><i class="fa-solid fa-play" style="font-size:0.5rem"></i> ${formatSeconds(sec)}</button>`;
    });

    return formatted;
}

async function sendChatMessage() {
    const input = document.getElementById("queryInput");
    const query = input.value.trim();
    if (!query) return;

    if (chatScope === 'current' && !currentVideoId) {
        alert("Please select a video from the library to ask about, or switch to 'All Videos' mode.");
        return;
    }

    input.value = "";
    const chatMessages = document.getElementById("chatMessages");

    const scopeBadgeHtml = (chatScope === 'current' && currentVideoData)
        ? `<div style="font-size: 0.65rem; color: #34d399; margin-bottom: 0.25rem; display: flex; align-items: center; gap: 0.3rem;"><i class="fa-solid fa-film"></i> ${escapeHtml(currentVideoData.filename.length > 30 ? currentVideoData.filename.substring(0, 28) + '..' : currentVideoData.filename)}</div>`
        : `<div style="font-size: 0.65rem; color: #38bdf8; margin-bottom: 0.25rem; display: flex; align-items: center; gap: 0.3rem;"><i class="fa-solid fa-earth-americas"></i> All Videos</div>`;

    chatMessages.innerHTML += `
        <div class="message user">
            ${scopeBadgeHtml}
            ${escapeHtml(query)}
        </div>
    `;
    chatMessages.scrollTop = chatMessages.scrollHeight;

    // Show typing spinner
    const typingId = `typing-${Date.now()}`;
    const typingText = (chatScope === 'current')
        ? 'Analyzing multimodal context for this video...'
        : 'Analyzing multimodal evidence across all videos...';

    chatMessages.innerHTML += `
        <div class="message assistant" id="${typingId}">
            <i class="fa-solid fa-circle-notch fa-spin" style="color: var(--primary);"></i> ${typingText}
        </div>
    `;
    chatMessages.scrollTop = chatMessages.scrollHeight;

    try {
        const isSingle = (chatScope === 'current' && currentVideoId);
        const endpoint = isSingle ? `/api/v1/videos/${currentVideoId}/chat` : `/api/v1/chat`;
        const payload = isSingle
            ? { query: query, session_id: currentSessionId }
            : { query: query, session_id: currentSessionId, scope: "all", video_id: currentVideoId || null };

        const res = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const typingElem = document.getElementById(typingId);
        if (typingElem) typingElem.remove();

        if (!res.ok) {
            chatMessages.innerHTML += `
                <div class="message assistant" style="color: var(--accent-rose);">
                    <i class="fa-solid fa-triangle-exclamation"></i> Error communicating with AI Copilot service.
                </div>
            `;
            return;
        }

        const data = await res.json();
        currentSessionId = data.session_id;

        const confPct = Math.round((data.confidence_score || 0) * 100);
        let confColor = confPct >= 75 ? "#34d399" : confPct >= 50 ? "#f59e0b" : "#ef4444";

        let citationsHtml = "";
        if (data.citations && data.citations.length > 0) {
            citationsHtml = `
                <div style="display: flex; align-items: center; gap: 0.35rem; flex-wrap: wrap;">
                    <span style="font-size: 0.68rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Evidence:</span>
                    ${data.citations.map(c => {
                        const vName = c.video_filename ? (c.video_filename.length > 16 ? c.video_filename.substring(0, 14) + '..' : c.video_filename) : '';
                        const vBadge = vName ? `<span class="citation-tag-video"><i class="fa-solid fa-film"></i> ${escapeHtml(vName)}</span>` : '';
                        return `
                            <button class="citation-tag" onclick="jumpToVideoAndTimestamp('${c.video_id || ''}', ${c.start_time})" title="${escapeHtml(c.snippet || '')} (${escapeHtml(c.video_filename || '')})">
                                ${vBadge}
                                <i class="fa-solid fa-play" style="font-size: 0.5rem;"></i> ${c.timestamp_formatted}
                            </button>
                        `;
                    }).join("")}
                </div>
            `;
        }

        const formattedAnswer = makeTimestampsClickable(escapeHtml(data.answer));
        const msgId = `asst-msg-${Date.now()}`;
        const videosTag = (data.videos_analyzed && data.videos_analyzed.length > 1) 
            ? `<span style="font-size: 0.68rem; color: #38bdf8; margin-left: 0.4rem;"><i class="fa-solid fa-layer-group"></i> ${data.videos_analyzed.length} Videos</span>`
            : '';

        chatMessages.innerHTML += `
            <div class="message assistant" id="${msgId}">
                <div class="message-top-bar">
                    <div style="display: flex; align-items: center; gap: 0.45rem;">
                        <i class="fa-solid fa-robot" style="color: var(--primary);"></i>
                        <span style="font-weight: 700; color: #f1f5f9;">VideoIntel Copilot</span>
                        ${videosTag}
                    </div>
                    <button class="btn-chat-action" onclick="toggleMessageCollapse(this)" title="Toggle message visibility">
                        <i class="fa-solid fa-chevron-up"></i>
                    </button>
                </div>
                <div class="message-answer-body" style="white-space: pre-wrap; line-height: 1.55;">${formattedAnswer}</div>
                <div class="message-meta">
                    ${citationsHtml}
                    <span style="color: ${confColor}; font-weight: 700; font-size: 0.72rem; margin-left: auto;">
                        <i class="fa-solid fa-shield-halved"></i> ${confPct}% Grounded
                    </span>
                </div>
            </div>
        `;
        setTimeout(() => {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }, 50);

        if (data.requires_hitl) {
            loadHITLReviews();
        }

    } catch (e) {
        console.error("Chat error:", e);
        const typingElem = document.getElementById(typingId);
        if (typingElem) typingElem.remove();

        chatMessages.innerHTML += `
            <div class="message assistant" style="color: var(--accent-rose);">
                <i class="fa-solid fa-triangle-exclamation"></i> Network error connecting to chat service.
            </div>
        `;
    }
}

function toggleMessageCollapse(elem) {
    const card = elem.closest(".message.assistant");
    if (!card) return;
    const body = card.querySelector(".message-answer-body");
    const meta = card.querySelector(".message-meta");
    if (body) {
        const isHidden = body.style.display === "none";
        body.style.display = isHidden ? "block" : "none";
        if (meta) meta.style.display = isHidden ? "flex" : "none";
        elem.innerHTML = isHidden ? `<i class="fa-solid fa-chevron-up"></i>` : `<i class="fa-solid fa-chevron-down"></i>`;
    }
}

let allAnswersCollapsed = false;
function toggleAllAnswers() {
    allAnswersCollapsed = !allAnswersCollapsed;
    const messages = document.querySelectorAll(".message.assistant");
    const btn = document.getElementById("btnToggleAllAnswers");
    if (btn) {
        btn.innerHTML = allAnswersCollapsed 
            ? `<i class="fa-solid fa-expand"></i> <span>Show All</span>` 
            : `<i class="fa-solid fa-compress"></i> <span>Hide All</span>`;
    }

    messages.forEach(card => {
        const body = card.querySelector(".message-answer-body");
        const meta = card.querySelector(".message-meta");
        const toggleBtn = card.querySelector(".btn-chat-action");
        if (body) {
            body.style.display = allAnswersCollapsed ? "none" : "block";
            if (meta) meta.style.display = allAnswersCollapsed ? "none" : "flex";
            if (toggleBtn) {
                toggleBtn.innerHTML = allAnswersCollapsed ? `<i class="fa-solid fa-chevron-down"></i>` : `<i class="fa-solid fa-chevron-up"></i>`;
            }
        }
    });
}

function clearChatMessages() {
    const chatMessages = document.getElementById("chatMessages");
    if (chatMessages) {
        chatMessages.innerHTML = `
            <div class="message assistant">
                <div style="font-weight: 600; color: #38bdf8; margin-bottom: 0.35rem; display: flex; align-items: center; gap: 0.45rem;">
                    <i class="fa-solid fa-shield-halved"></i> Cross-Video Intelligence Active
                </div>
                Chat cleared. Ask anything across all uploaded videos, trace persons across camera feeds, or search dialogue and visual scenes.
            </div>
        `;
    }
}

// =========================================================================
// Human-in-the-Loop (HITL) Queue
// =========================================================================
async function loadHITLReviews() {
    const container = document.getElementById("hitlContainer");
    if (!container) return;

    try {
        const res = await fetch("/api/v1/hitl/reviews?status_filter=pending");
        if (!res.ok) return;
        const reviews = await res.json();

        if (reviews.length === 0) {
            container.innerHTML = '<p style="font-size: 0.72rem; color: var(--text-dark);">No pending reviews.</p>';
            return;
        }

        container.innerHTML = reviews.map(r => `
            <div class="hitl-item" id="hitl-${r.id}">
                <div style="font-weight: 600; color: #f1f5f9; margin-bottom: 0.2rem;">${escapeHtml(r.query)}</div>
                <div style="color: var(--text-muted); font-size: 0.7rem; margin-bottom: 0.35rem;">Confidence: ${Math.round(r.confidence_score * 100)}%</div>
                <div style="display: flex; gap: 0.3rem;">
                    <button class="btn-chat-action" style="background: rgba(16,185,129,0.15); color: #34d399;" onclick="resolveHITL('${r.id}', true)">
                        <i class="fa-solid fa-check"></i> Approve
                    </button>
                    <button class="btn-chat-action" style="background: rgba(239,68,68,0.15); color: #f87171;" onclick="resolveHITL('${r.id}', false)">
                        <i class="fa-solid fa-xmark"></i> Reject
                    </button>
                </div>
            </div>
        `).join("");
    } catch (e) {
        console.error("Error loading HITL reviews:", e);
    }
}

async function resolveHITL(id, approved) {
    try {
        const res = await fetch(`/api/v1/hitl/reviews/${id}/resolve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: approved ? "approve" : "reject" })
        });
        if (res.ok) {
            loadHITLReviews();
        }
    } catch (e) {
        console.error("Error resolving HITL:", e);
    }
}
