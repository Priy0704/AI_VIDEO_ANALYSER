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

// Independent chat histories for All Videos vs each individual video (no mixing!)
const chatStorage = {
    all: {
        sessionId: null,
        messagesHtml: []
    },
    videos: {} // videoId -> { sessionId: null, messagesHtml: [] }
};

document.addEventListener("DOMContentLoaded", () => {
    loadVideoList();
    loadHITLReviews();
    initTimelineScrubbing();
    renderChatMessagesForCurrentScope();

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
            } catch { }
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
            } catch { }
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

        let typeBadge = '';
        if (v.video_type === 'observational') {
            typeBadge = `<span class="badge-type-observational" style="font-size:0.62rem; padding: 0.1rem 0.4rem; border-radius: 9999px;"><i class="fa-solid fa-video"></i> Observational</span>`;
        } else if (v.video_type === 'knowledge') {
            typeBadge = `<span class="badge-type-knowledge" style="font-size:0.62rem; padding: 0.1rem 0.4rem; border-radius: 9999px;"><i class="fa-solid fa-graduation-cap"></i> Learning</span>`;
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
                        ${typeBadge}
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
    if (!chatStorage.videos[videoId]) {
        chatStorage.videos[videoId] = { sessionId: null, messagesHtml: [] };
    }
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

        // If in individual scope, update copilot focus subtitle, placeholder, and render its separate chat
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

            renderChatMessagesForCurrentScope();
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

        // Update Classification Badge and Learning Tabs
        updateVideoTypeBadge(currentVideoData);
        updateLearningTabsVisibility(currentVideoData);
        if (currentVideoData.video_type !== 'observational') {
            loadPastQuizzes(videoId);
            loadSelfTestPromptQuestion();
        }

        // Auto select tab
        if (currentActiveTab === 'quiz' || currentActiveTab === 'selfTest') {
            if (currentVideoData.video_type === 'observational') {
                currentActiveTab = transcriptCount > 0 ? 'transcript' : 'visuals';
            }
        } else if (transcriptCount > 0) {
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
    const btnQuiz = document.getElementById("tabBtnQuiz");
    const btnSelfTest = document.getElementById("tabBtnSelfTest");

    if (btnTranscript) btnTranscript.classList.toggle("active", tabName === 'transcript');
    if (btnVisuals) btnVisuals.classList.toggle("active", tabName === 'visuals');
    if (btnOverview) btnOverview.classList.toggle("active", tabName === 'overview');
    if (btnQuiz) btnQuiz.classList.toggle("active", tabName === 'quiz');
    if (btnSelfTest) btnSelfTest.classList.toggle("active", tabName === 'selfTest' || tabName === 'selftest');

    const paneTranscript = document.getElementById("paneTranscript");
    const paneVisuals = document.getElementById("paneVisuals");
    const paneOverview = document.getElementById("paneOverview");
    const paneQuiz = document.getElementById("paneQuiz");
    const paneSelfTest = document.getElementById("paneSelfTest");

    if (paneTranscript) paneTranscript.style.display = (tabName === 'transcript' ? 'flex' : 'none');
    if (paneVisuals) paneVisuals.style.display = (tabName === 'visuals' ? 'flex' : 'none');
    if (paneOverview) paneOverview.style.display = (tabName === 'overview' ? 'flex' : 'none');
    if (paneQuiz) paneQuiz.style.display = (tabName === 'quiz' ? 'flex' : 'none');
    if (paneSelfTest) paneSelfTest.style.display = (tabName === 'selfTest' ? 'flex' : 'none');

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
            try { player.currentTime = targetTime; } catch { }
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

function renderChatMessagesForCurrentScope() {
    const chatMessages = document.getElementById("chatMessages");
    if (!chatMessages) return;

    if (chatScope === 'all') {
        if (chatStorage.all.messagesHtml.length === 0) {
            chatMessages.innerHTML = `
                <div class="message assistant">
                    <div style="font-weight: 600; color: #38bdf8; margin-bottom: 0.35rem; display: flex; align-items: center; gap: 0.45rem;">
                        <i class="fa-solid fa-earth-americas"></i> All-Videos Intelligence Chat
                    </div>
                    Ask any question across all uploaded videos in your library (e.g. <i>"Trace the person across cameras"</i> or <i>"Total person count across all videos"</i>).
                </div>
            `;
        } else {
            chatMessages.innerHTML = chatStorage.all.messagesHtml.join("");
        }
    } else {
        // Individual Video Chat ('current')
        if (!currentVideoId) {
            chatMessages.innerHTML = `
                <div class="message assistant" style="color: var(--accent-amber);">
                    <div style="font-weight: 600; margin-bottom: 0.35rem;"><i class="fa-solid fa-circle-info"></i> No Video Selected</div>
                    Please select a video from the library on the left to start an individual video chat.
                </div>
            `;
        } else {
            const vStore = chatStorage.videos[currentVideoId] || { sessionId: null, messagesHtml: [] };
            if (vStore.messagesHtml.length === 0) {
                const vName = currentVideoData ? currentVideoData.filename : 'Current Video';
                chatMessages.innerHTML = `
                    <div class="message assistant">
                        <div style="font-weight: 600; color: #34d399; margin-bottom: 0.35rem; display: flex; align-items: center; gap: 0.45rem;">
                            <i class="fa-solid fa-film"></i> Single Video Chat
                        </div>
                        Focused on <strong>${escapeHtml(vName)}</strong>. Ask about spoken dialogue, visual scenes, or key moments in this video.
                    </div>
                `;
            } else {
                chatMessages.innerHTML = vStore.messagesHtml.join("");
            }
        }
    }

    setTimeout(() => {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }, 40);
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
                <button class="suggestion-chip" onclick="sendQuickPrompt('Summarize key activities across all videos')">✦ Summarize all videos</button>
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

    // Switch view to the separated chat messages!
    renderChatMessagesForCurrentScope();
}

async function jumpToVideoAndTimestamp(videoId, seconds, autoplay = true) {
    if (typeof closeContextModal === "function") {
        closeContextModal();
    }
    const sec = Math.max(0, parseFloat(seconds) || 0);
    const player = document.getElementById("videoPlayer");
    if (!player) return;

    if (videoId && videoId !== currentVideoId) {
        // Load target video without disrupting All Videos chat view
        await selectVideo(videoId);

        const applySeekAndPlay = () => {
            player.currentTime = sec;
            if (autoplay) {
                const p = player.play();
                if (p !== undefined) p.catch(err => console.debug("Autoplay defer:", err));
            }
            player.scrollIntoView({ behavior: 'smooth', block: 'center' });
        };

        if (player.readyState >= 1) {
            applySeekAndPlay();
        } else {
            player.addEventListener("loadedmetadata", applySeekAndPlay, { once: true });
            setTimeout(applySeekAndPlay, 500);
        }
    } else {
        player.currentTime = sec;
        if (autoplay) {
            const p = player.play();
            if (p !== undefined) p.catch(err => console.debug("Autoplay defer:", err));
        }
        player.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

async function jumpToVideoByFilenameAndTimestamp(filename, seconds, autoplay = true) {
    const sec = Math.max(0, parseFloat(seconds) || 0);
    const clean = (filename || '').trim().toLowerCase();
    const matched = libraryVideosCache.find(v => {
        const fn = (v.filename || '').toLowerCase();
        return fn === clean || fn.includes(clean) || clean.includes(fn);
    });
    if (matched) {
        await jumpToVideoAndTimestamp(matched.video_id, sec, autoplay);
    } else {
        seekVideo(sec);
        const player = document.getElementById("videoPlayer");
        if (player && autoplay) player.play().catch(e => console.debug(e));
    }
}

// Automatically detect status badges, section labels, timestamps, and video references in AI answer
function makeTimestampsClickable(htmlText, citations = []) {
    let formatted = htmlText;

    // 1. Status badges (Found, Uncertain, Not found)
    formatted = formatted
        .replace(/(?:^|\n)\s*✅\s*Found\b/gi, '\n<div class="status-badge status-badge-found"><i class="fa-solid fa-circle-check"></i> Found</div>')
        .replace(/(?:^|\n)\s*⚠️\s*Uncertain\b/gi, '\n<div class="status-badge status-badge-uncertain"><i class="fa-solid fa-triangle-exclamation"></i> Uncertain</div>')
        .replace(/(?:^|\n)\s*❌\s*Not found\b/gi, '\n<div class="status-badge status-badge-notfound"><i class="fa-solid fa-circle-xmark"></i> Not Found</div>');

    // 2. Modality types in Evidence block (Transcript, Visual, OCR, Event)
    formatted = formatted.replace(/(?:^|\n)\s*Type:\s*(Transcript|Visual|OCR|Event)\b/gi, (match, mType) => {
        const lower = mType.toLowerCase();
        let icon = 'fa-eye';
        if (lower === 'transcript') icon = 'fa-microphone-lines';
        else if (lower === 'ocr') icon = 'fa-font';
        else if (lower === 'event') icon = 'fa-bolt';
        return `\n<strong class="ai-section-label" style="display:inline-block; margin-right:4px;">Type:</strong> <span class="modality-pill modality-pill-${lower}"><i class="fa-solid ${icon}"></i> ${mType}</span>`;
    });

    // 3. Confidence level (High, Medium, Low)
    formatted = formatted.replace(/(?:^|\n)\s*(?:<strong class="ai-section-label">)?Confidence:(?:<\/strong>)?\s*(High|Medium|Low)\b/gi, (match, level) => {
        const lower = level.toLowerCase();
        let icon = lower === 'high' ? 'fa-circle-check' : lower === 'medium' ? 'fa-triangle-exclamation' : 'fa-circle-xmark';
        return `\n<strong class="ai-section-label">Confidence:</strong> <span class="confidence-pill confidence-pill-${lower}"><i class="fa-solid ${icon}"></i> ${level}</span>`;
    });

    // 4. Convert markdown bold and italic
    formatted = formatted
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // 5. Convert Section Labels
    const labels = [
        "Answer:",
        "Possible Result:",
        "Confidence & Limitation:",
        "Evidence:",
        "Supporting Evidence:",
        "Reason:",
        "Key Points:",
        "Chronological Video Timeline:",
        "Status:",
        "Timestamp:",
        "Video:"
    ];
    labels.forEach(label => {
        const regex = new RegExp(`(?:^|<br>|\\n)\\s*(${label.replace('&', '&amp;')}|${label})`, 'gi');
        formatted = formatted.replace(regex, (m, lbl) => `\n<strong class="ai-section-label">${lbl}</strong>`);
    });

    // 6. Convert [Video: filename | MM:SS–MM:SS] or [Video: filename | MM:SS]
    const videoTimelineRegex = /\[Video:\s*([^|\]]+)\s*\|\s*(\d{1,2}:\d{2})(?:[–-](\d{1,2}:\d{2}))?\]/g;
    formatted = formatted.replace(videoTimelineRegex, (match, vName, tStart, tEnd) => {
        const sec = parseTimeToSeconds(tStart);
        const cleanName = vName.trim();
        const shortName = cleanName.length > 20 ? cleanName.substring(0, 18) + '..' : cleanName;
        return `<button class="ai-time-jump" onclick="jumpToVideoByFilenameAndTimestamp('${escapeHtml(cleanName)}', ${sec})" title="Play ${escapeHtml(cleanName)} at ${tStart}"><i class="fa-solid fa-play" style="font-size:0.5rem"></i> <i class="fa-solid fa-film" style="font-size:0.5rem"></i> ${escapeHtml(shortName)} ${tStart}</button>`;
    });

    // 7. Convert numbered video lines like: 1. [cctv_entrance_gate.mp4] or 1. [Video Name]
    formatted = formatted.replace(/(?:^|\n)\s*(\d+)\.\s*\[([^\]]+)\]/g, (match, num, vName) => {
        const cleanName = vName.trim();
        return `\n<div style="margin-top:0.4rem; font-weight:700;"><span style="color:var(--primary);">${num}.</span> <span class="ai-video-tag" onclick="jumpToVideoByFilenameAndTimestamp('${escapeHtml(cleanName)}', 0)" title="Switch to ${escapeHtml(cleanName)}"><i class="fa-solid fa-film"></i> ${escapeHtml(cleanName)}</span></div>`;
    });

    // 8. Convert Video: <filename> lines to clickable video tags if matching
    const videoLineRegex = /(<strong class="ai-section-label">Video:<\/strong>\s*)([^\n<]+)/gi;
    formatted = formatted.replace(videoLineRegex, (match, prefix, vList) => {
        const vNames = vList.split(',').map(s => s.trim()).filter(Boolean);
        const tags = vNames.map(name => {
            const clean = name.replace(/^["'\[]|["'\]]$/g, '');
            return `<span class="ai-video-tag" onclick="jumpToVideoByFilenameAndTimestamp('${escapeHtml(clean)}', 0)" title="Switch video to ${escapeHtml(clean)}"><i class="fa-solid fa-film"></i> ${escapeHtml(clean)}</span>`;
        });
        return `${prefix}${tags.join(' ')}`;
    });

    // 9. Convert standard timestamps [MM:SS] or MM:SS
    const timestampRegex = /(?:\[)?\b(\d{1,2}:\d{2}(?::\d{2})?)\b(?:\])?/g;
    formatted = formatted.replace(timestampRegex, (match, timeStr) => {
        const sec = parseTimeToSeconds(timeStr);
        let matchedVidId = (chatScope === 'current' ? currentVideoId : null);
        let matchedVidName = (chatScope === 'current' && currentVideoData ? currentVideoData.filename : '');

        if (citations && citations.length > 0) {
            const found = citations.find(c => Math.abs(c.start_time - sec) <= 35 || (c.timestamp_formatted && c.timestamp_formatted.includes(timeStr)));
            if (found) {
                matchedVidId = found.video_id;
                matchedVidName = found.video_filename;
            } else if (citations.length === 1) {
                matchedVidId = citations[0].video_id;
                matchedVidName = citations[0].video_filename;
            }
        }

        if (matchedVidId) {
            const shortName = matchedVidName ? (matchedVidName.length > 16 ? matchedVidName.substring(0, 14) + '..' : matchedVidName) : '';
            return `<button class="ai-time-jump" onclick="jumpToVideoAndTimestamp('${matchedVidId}', ${sec})" title="Play ${escapeHtml(matchedVidName || '')} at ${timeStr}"><i class="fa-solid fa-play" style="font-size:0.5rem"></i> ${shortName ? `<span style="opacity:0.8; margin-right:2px;">${escapeHtml(shortName)}</span>` : ''}${timeStr}</button>`;
        }

        return `<button class="ai-time-jump" onclick="seekVideo(${sec})" title="Jump video to ${timeStr}"><i class="fa-solid fa-play" style="font-size:0.5rem"></i> ${timeStr}</button>`;
    });

    // 10. Convert "at X seconds" or "around X seconds"
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
    const isAll = (chatScope === 'all');

    // Create user message HTML
    const scopeBadgeHtml = (chatScope === 'current' && currentVideoData)
        ? `<div style="font-size: 0.65rem; color: #34d399; margin-bottom: 0.25rem; display: flex; align-items: center; gap: 0.3rem;"><i class="fa-solid fa-film"></i> ${escapeHtml(currentVideoData.filename.length > 30 ? currentVideoData.filename.substring(0, 28) + '..' : currentVideoData.filename)}</div>`
        : `<div style="font-size: 0.65rem; color: #38bdf8; margin-bottom: 0.25rem; display: flex; align-items: center; gap: 0.3rem;"><i class="fa-solid fa-earth-americas"></i> All Videos</div>`;

    const userMsgHtml = `
        <div class="message user">
            ${scopeBadgeHtml}
            ${escapeHtml(query)}
        </div>
    `;

    // Save to separate in-memory storage
    if (isAll) {
        chatStorage.all.messagesHtml.push(userMsgHtml);
    } else {
        if (!chatStorage.videos[currentVideoId]) {
            chatStorage.videos[currentVideoId] = { sessionId: null, messagesHtml: [] };
        }
        chatStorage.videos[currentVideoId].messagesHtml.push(userMsgHtml);
    }

    // Render current scope messages
    renderChatMessagesForCurrentScope();

    // Show typing spinner in chat container
    const chatMessages = document.getElementById("chatMessages");
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
        const activeSessionId = isSingle
            ? (chatStorage.videos[currentVideoId]?.sessionId || null)
            : chatStorage.all.sessionId;

        const payload = isSingle
            ? { query: query, session_id: activeSessionId }
            : { query: query, session_id: activeSessionId, scope: "all", video_id: currentVideoId || null };

        const res = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const typingElem = document.getElementById(typingId);
        if (typingElem) typingElem.remove();

        if (!res.ok) {
            const errHtml = `
                <div class="message assistant" style="color: var(--accent-rose);">
                    <i class="fa-solid fa-triangle-exclamation"></i> Error communicating with AI Copilot service.
                </div>
            `;
            if (isAll) chatStorage.all.messagesHtml.push(errHtml);
            else if (currentVideoId) chatStorage.videos[currentVideoId].messagesHtml.push(errHtml);
            renderChatMessagesForCurrentScope();
            return;
        }

        const data = await res.json();

        // Update independent session ID
        if (isAll) {
            chatStorage.all.sessionId = data.session_id;
        } else if (currentVideoId) {
            chatStorage.videos[currentVideoId].sessionId = data.session_id;
        }

        const confPct = Math.round((data.confidence_score || 0) * 100);
        let confColor = confPct >= 75 ? "#34d399" : confPct >= 50 ? "#f59e0b" : "#ef4444";
        let confLevel = data.confidence_level || (confPct >= 75 ? "High" : confPct >= 50 ? "Medium" : "Low");

        let citationsHtml = "";
        if (data.citations && data.citations.length > 0) {
            // Deduplicate citations by (video_filename || video_id, timestamp_formatted)
            const uniqueCitations = [];
            const seenKeys = new Set();
            for (const c of data.citations) {
                const key = `${c.video_filename || c.video_id || ''}_${c.timestamp_formatted || c.start_time}`;
                if (!seenKeys.has(key)) {
                    seenKeys.add(key);
                    uniqueCitations.push(c);
                }
            }

            citationsHtml = `
                <div style="display: flex; align-items: center; gap: 0.35rem; flex-wrap: wrap;">
                    <span style="font-size: 0.68rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Timestamps:</span>
                    ${uniqueCitations.slice(0, 4).map(c => {
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

        // Clean raw section headers from answer body for direct grounded answer output
        let cleanText = (data.answer || "").trim();
        cleanText = cleanText.replace(/^(?:✅ Found|⚠️ Uncertain|❌ Not found)\s*/i, '');
        cleanText = cleanText.replace(/^(?:Answer|ANSWER):\s*/i, '');
        if (cleanText.includes("\nEvidence:\n")) cleanText = cleanText.split("\nEvidence:\n")[0];
        else if (cleanText.includes("Evidence:\n")) cleanText = cleanText.split("Evidence:\n")[0];
        if (cleanText.includes("\nConfidence:\n")) cleanText = cleanText.split("\nConfidence:\n")[0];
        if (cleanText.includes("\nReason:\n")) cleanText = cleanText.split("\nReason:\n")[0];
        if (cleanText.includes("\nTimestamp:\n")) cleanText = cleanText.split("\nTimestamp:\n")[0];
        if (cleanText.includes("Timestamps:\n")) cleanText = cleanText.split("Timestamps:\n")[0];
        if (cleanText.includes("Timestamp:\n")) cleanText = cleanText.split("Timestamp:\n")[0];
        cleanText = cleanText.replace(/KEY POINTS:\s*/gi, '').trim();

        const formattedAnswer = makeTimestampsClickable(escapeHtml(cleanText), data.citations || []);
        const msgId = `asst-msg-${Date.now()}`;
        const videosTag = (data.videos_analyzed && data.videos_analyzed.length > 1)
            ? `<span style="font-size: 0.68rem; color: #38bdf8; margin-left: 0.4rem;"><i class="fa-solid fa-layer-group"></i> ${data.videos_analyzed.length} Videos</span>`
            : '';

        const asstMsgHtml = `
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

        // Save to separate in-memory storage
        if (isAll) {
            chatStorage.all.messagesHtml.push(asstMsgHtml);
        } else if (currentVideoId) {
            chatStorage.videos[currentVideoId].messagesHtml.push(asstMsgHtml);
        }

        renderChatMessagesForCurrentScope();

        if (data.requires_hitl) {
            loadHITLReviews();
        }

    } catch (e) {
        console.error("Chat error:", e);
        const typingElem = document.getElementById(typingId);
        if (typingElem) typingElem.remove();

        const netErrHtml = `
            <div class="message assistant" style="color: var(--accent-rose);">
                <i class="fa-solid fa-triangle-exclamation"></i> Network error connecting to chat service.
            </div>
        `;
        if (isAll) chatStorage.all.messagesHtml.push(netErrHtml);
        else if (currentVideoId) chatStorage.videos[currentVideoId].messagesHtml.push(netErrHtml);
        renderChatMessagesForCurrentScope();
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

function clearChatMessages() {
    if (chatScope === 'all') {
        chatStorage.all.sessionId = null;
        chatStorage.all.messagesHtml = [];
    } else if (chatScope === 'current' && currentVideoId) {
        chatStorage.videos[currentVideoId] = { sessionId: null, messagesHtml: [] };
    }
    renderChatMessagesForCurrentScope();
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

// =========================================================================
// Video Classification & Learning Gate
// =========================================================================
function updateVideoTypeBadge(video) {
    const badge = document.getElementById("playerVideoTypeBadge");
    if (!badge) return;

    if (!video || !video.video_type) {
        badge.className = "video-type-badge";
        badge.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Analyzing Video Type...`;
        badge.title = "Multimodal classification in progress...";
        return;
    }

    if (video.video_type === 'knowledge') {
        badge.className = "video-type-badge badge-type-knowledge";
        const label = video.video_type_label || 'Knowledge / Content-based';
        badge.innerHTML = `<i class="fa-solid fa-graduation-cap"></i> ${escapeHtml(label)}`;
        badge.title = video.video_type_reason || 'Educational, training, presentation, or meeting content with structured learning features enabled.';
    } else if (video.video_type === 'observational') {
        badge.className = "video-type-badge badge-type-observational";
        const label = video.video_type_label || 'Observational / Surveillance';
        badge.innerHTML = `<i class="fa-solid fa-video"></i> ${escapeHtml(label)}`;
        badge.title = video.video_type_reason || 'CCTV, traffic, security, or dashcam observational footage. Assessment quizzes are disabled.';
    } else {
        badge.className = "video-type-badge";
        badge.innerHTML = `<i class="fa-solid fa-film"></i> General Video`;
        badge.title = "Standard video stream.";
    }
}

function updateLearningTabsVisibility(video) {
    const tabQuiz = document.getElementById("tabBtnQuiz");
    const tabSelfTest = document.getElementById("tabBtnSelfTest");
    const mTabQuiz = document.getElementById("mTabQuiz");
    const mTabSelfTest = document.getElementById("mTabSelfTest");

    const isObservational = (video && video.video_type === 'observational');
    if (isObservational) {
        if (tabQuiz) tabQuiz.style.display = "none";
        if (tabSelfTest) tabSelfTest.style.display = "none";
        if (mTabQuiz) mTabQuiz.style.display = "none";
        if (mTabSelfTest) mTabSelfTest.style.display = "none";
        // If user was on quiz or self-test pane, switch away
        if (currentActiveTab === 'quiz' || currentActiveTab === 'selfTest') {
            switchTab('transcript');
        }
    } else {
        if (tabQuiz) tabQuiz.style.display = "inline-flex";
        if (tabSelfTest) tabSelfTest.style.display = "inline-flex";
        if (mTabQuiz) mTabQuiz.style.display = "inline-flex";
        if (mTabSelfTest) mTabSelfTest.style.display = "inline-flex";
    }
}

// =========================================================================
// Interactive Quiz & Assessment System
// =========================================================================
let activeQuiz = null;
let activeQuestions = [];
let currentQuestionIndex = 0;
let userQuizAnswers = {};
let lastQuizAttempt = null;

async function loadPastQuizzes(videoId) {
    const section = document.getElementById("pastQuizzesSection");
    const list = document.getElementById("pastQuizzesList");
    if (!section || !list || !videoId) return;

    try {
        const res = await fetch(`/api/v1/videos/${videoId}/quizzes`);
        if (!res.ok) return;
        const quizzes = await res.json();
        if (quizzes.length === 0) {
            section.style.display = "none";
            return;
        }

        section.style.display = "block";
        list.innerHTML = quizzes.map(q => {
            let scoreBadgeHtml = '';
            if (q.latest_score !== null && q.latest_score !== undefined) {
                const maxS = q.latest_max_score || q.total_questions;
                const pct = Math.round(q.latest_percentage || ((q.latest_score / maxS) * 100));
                let color = pct >= 75 ? '#34d399' : pct >= 50 ? '#f59e0b' : '#f87171';
                scoreBadgeHtml = `
                    <span style="font-size: 0.68rem; font-weight: 700; color: ${color}; background: rgba(255,255,255,0.05); border: 1px solid ${color}40; padding: 0.15rem 0.45rem; border-radius: var(--radius-xs); display: inline-flex; align-items: center; gap: 0.3rem;">
                        <i class="fa-solid fa-trophy" style="font-size: 0.65rem;"></i> Score: ${q.latest_score}/${maxS} (${pct}%)
                    </span>
                `;
            } else {
                scoreBadgeHtml = `<span style="font-size: 0.68rem; color: var(--text-dark);">(Not attempted yet)</span>`;
            }

            return `
                <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.03); border: 1px solid var(--border); padding: 0.5rem 0.75rem; border-radius: var(--radius-xs); gap: 0.5rem; flex-wrap: wrap;">
                    <div style="display: flex; flex-direction: column; gap: 0.2rem; min-width: 250px;">
                        <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                            <span class="quiz-title-link" onclick="loadAndStartQuiz('${q.id}')" style="cursor: pointer; font-weight: 700; color: #f8fafc; font-size: 0.82rem;" title="Click to start taking this quiz">
                                <i class="fa-solid fa-graduation-cap" style="color: #818cf8; font-size: 0.8rem; margin-right: 0.25rem;"></i>
                                ${escapeHtml(q.title || 'Knowledge Assessment')}
                            </span>
                            ${scoreBadgeHtml}
                        </div>
                        <div style="font-size: 0.7rem; color: var(--text-muted);">
                            ${q.total_questions} questions · ${q.difficulty} · ${q.question_type}
                        </div>
                    </div>
                    <div style="display: flex; gap: 0.4rem; align-items: center; flex-shrink: 0;">
                        <button class="filter-pill" style="font-size: 0.68rem; padding: 0.2rem 0.5rem;" onclick="downloadQuestionPaperPdf('${q.id}')" title="Download Clean Question Paper PDF">
                            <i class="fa-solid fa-file-lines"></i> Questions PDF
                        </button>
                        <button class="filter-pill" style="font-size: 0.68rem; padding: 0.2rem 0.5rem;" onclick="downloadAnswerKeyPdf('${q.id}')" title="Download Questions & Answer Key PDF">
                            <i class="fa-solid fa-file-pdf"></i> Q&amp;A PDF
                        </button>
                        <button class="filter-pill btn-delete-quiz" style="font-size: 0.68rem; padding: 0.2rem 0.5rem; color: #f87171;" onclick="deleteQuiz('${q.id}')" title="Delete Quiz">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                    </div>
                </div>
            `;
        }).join("");
    } catch (e) {
        console.error("Error loading past quizzes:", e);
    }
}

async function deleteQuiz(quizId) {
    if (!quizId) return;
    if (!confirm("Are you sure you want to delete this quiz?")) return;

    try {
        const res = await fetch(`/api/v1/quizzes/${quizId}`, { method: "DELETE" });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || "Failed to delete quiz.");
        }
        if (currentVideoId) {
            loadPastQuizzes(currentVideoId);
        }
    } catch (e) {
        console.error("Error deleting quiz:", e);
        alert(e.message || "Could not delete quiz.");
    }
}

async function generateQuizForActiveVideo() {
    if (!currentVideoId) {
        alert("Please select a video first.");
        return;
    }

    if (currentVideoData && currentVideoData.video_type === 'observational') {
        alert("Quizzes are disabled for observational / surveillance footage.");
        return;
    }

    const numQuestions = parseInt(document.getElementById("quizNumQuestions")?.value || "5", 10);
    const difficulty = document.getElementById("quizDifficulty")?.value || "medium";
    const questionType = document.getElementById("quizQuestionType")?.value || "mixed";

    const btn = document.getElementById("btnStartGenerateQuiz");
    const status = document.getElementById("quizGenStatus");

    if (btn) btn.disabled = true;
    if (status) status.style.display = "inline-flex";

    try {
        const res = await fetch(`/api/v1/videos/${currentVideoId}/quiz/generate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                num_questions: numQuestions,
                difficulty: difficulty,
                question_type: questionType
            })
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || "Failed to generate quiz.");
        }

        const quizData = await res.json();
        startQuizTaking(quizData);
    } catch (e) {
        console.error("Error generating quiz:", e);
        alert(e.message || "Could not generate quiz. Ensure video analysis is complete.");
    } finally {
        if (btn) btn.disabled = false;
        if (status) status.style.display = "none";
    }
}

async function loadAndStartQuiz(quizId) {
    try {
        const res = await fetch(`/api/v1/quizzes/${quizId}`);
        if (!res.ok) throw new Error("Quiz not found.");
        const quizData = await res.json();
        startQuizTaking(quizData);
    } catch (e) {
        console.error("Error loading quiz:", e);
        alert("Could not load quiz.");
    }
}

function startQuizTaking(quizData) {
    activeQuiz = quizData;
    activeQuestions = quizData.questions || [];
    currentQuestionIndex = 0;
    userQuizAnswers = {};
    lastQuizAttempt = null;

    if (activeQuestions.length === 0) {
        alert("Quiz contains no questions.");
        return;
    }

    document.getElementById("quizConfigCard").style.display = "none";
    document.getElementById("quizEvaluationWrap").style.display = "none";
    document.getElementById("quizTakingWrap").style.display = "block";

    renderQuizQuestion(0);
}

function cleanQuestionText(qText, topic) {
    if (!qText) return `What primary concept or capability is demonstrated regarding ${topic || 'this video'}?`;
    let q = qText;
    q = q.replace(/according to the video (?:at [^,\.\?\n]+)?/gi, '');
    q = q.replace(/highlighted in the video (?:at [^,\.\?\n]+)?/gi, '');
    q = q.replace(/based on the video (?:at [^,\.\?\n]+)?/gi, '');
    q = q.replace(/(?:at|in|between|during)?\s*\b\d{1,2}:\d{2}\s*(?:–|-|to)\s*\d{1,2}:\d{2}\b/gi, '');
    q = q.replace(/the footage is unrelated to [^\.\?\n]+/gi, 'the video presents core concepts');
    q = q.replace(/\s+/g, ' ').trim();
    if (q.startsWith(',') || q.startsWith(':') || q.startsWith('-')) {
        q = q.substring(1).trim();
    }
    if (!q || q.length < 10 || q.toLowerCase().startsWith('what key information is') || q.toLowerCase().startsWith('what key concept is')) {
        q = `What primary concept or capability is demonstrated regarding ${topic || 'this video'}?`;
    }
    if (!q.endsWith('?') && !q.endsWith('.')) {
        q += '?';
    }
    return q;
}

function renderQuizQuestion(index) {
    if (!activeQuestions || index < 0 || index >= activeQuestions.length) return;
    currentQuestionIndex = index;

    const q = activeQuestions[index];
    const total = activeQuestions.length;

    // Progress
    const progText = document.getElementById("quizTakingProgressText");
    if (progText) progText.innerText = `Question ${index + 1} of ${total}`;

    const progBar = document.getElementById("quizTakingProgressBar");
    if (progBar) progBar.style.width = `${Math.round(((index + 1) / total) * 100)}%`;

    const topicBadge = document.getElementById("quizTakingTopicBadge");
    if (topicBadge) topicBadge.innerText = q.topic || "General";

    // Question Text
    const qText = document.getElementById("quizQuestionText");
    if (qText) qText.innerText = cleanQuestionText(q.question || q.question_text, q.topic);

    // Options or Text Area
    const container = document.getElementById("quizOptionsContainer");
    if (!container) return;
    container.innerHTML = "";

    const userAns = userQuizAnswers[q.id] || "";

    if (q.question_type === 'short_answer') {
        container.innerHTML = `
            <div style="margin-top: 0.5rem;">
                <textarea 
                    class="config-select" 
                    rows="3" 
                    placeholder="Type your answer here..."
                    oninput="handleShortAnswerChange('${q.id}', this.value)"
                    style="width: 100%; font-size: 0.82rem; resize: vertical;"
                >${escapeHtml(userAns)}</textarea>
            </div>
        `;
    } else {
        // MCQ or True/False
        let options = q.options;
        if (typeof options === "string") {
            try { options = JSON.parse(options); } catch { options = []; }
        }

        let html = "";
        if (Array.isArray(options)) {
            html = options.map((optText, idx) => {
                const letter = String.fromCharCode(65 + idx); // A, B, C, D
                const isSelected = (userAns === optText || userAns === letter || userAns === String(idx));
                return `
                    <div class="quiz-option-item ${isSelected ? 'selected' : ''}" onclick="selectQuizOption('${q.id}', '${escapeHtml(optText)}')">
                        <span class="quiz-option-indicator">${letter}</span>
                        <div class="quiz-option-text">${escapeHtml(optText)}</div>
                        <i class="fa-regular ${isSelected ? 'fa-circle-dot' : 'fa-circle'}" style="margin-left: auto; color: ${isSelected ? '#38bdf8' : 'var(--text-dark)'};"></i>
                    </div>
                `;
            }).join("");
        } else if (options && typeof options === "object") {
            const optionKeys = Object.keys(options).sort();
            html = optionKeys.map((k, idx) => {
                const valText = options[k];
                const displayKey = k.length === 1 ? k.toUpperCase() : String.fromCharCode(65 + idx);
                const isSelected = (userAns === valText || userAns === k);
                return `
                    <div class="quiz-option-item ${isSelected ? 'selected' : ''}" onclick="selectQuizOption('${q.id}', '${escapeHtml(valText)}')">
                        <span class="quiz-option-indicator">${escapeHtml(displayKey)}</span>
                        <div class="quiz-option-text">${escapeHtml(valText)}</div>
                        <i class="fa-regular ${isSelected ? 'fa-circle-dot' : 'fa-circle'}" style="margin-left: auto; color: ${isSelected ? '#38bdf8' : 'var(--text-dark)'};"></i>
                    </div>
                `;
            }).join("");
        }
        container.innerHTML = html;
    }

    // Navigation buttons
    const btnPrev = document.getElementById("btnQuizPrev");
    const btnNext = document.getElementById("btnQuizNext");
    const btnSubmit = document.getElementById("btnQuizSubmit");

    if (btnPrev) btnPrev.disabled = (index === 0);
    if (index === total - 1) {
        if (btnNext) btnNext.style.display = "none";
        if (btnSubmit) btnSubmit.style.display = "inline-flex";
    } else {
        if (btnNext) btnNext.style.display = "inline-flex";
        if (btnSubmit) btnSubmit.style.display = "none";
    }
}

function selectQuizOption(questionId, optionKey) {
    userQuizAnswers[questionId] = optionKey;
    renderQuizQuestion(currentQuestionIndex);
}

function handleShortAnswerChange(questionId, val) {
    userQuizAnswers[questionId] = val.trim();
}

function navQuizQuestion(delta) {
    const newIdx = currentQuestionIndex + delta;
    if (newIdx >= 0 && newIdx < activeQuestions.length) {
        renderQuizQuestion(newIdx);
    }
}

function cancelQuizTaking() {
    if (confirm("Exit quiz? Your current answers will be discarded.")) {
        resetQuizToConfig();
    }
}

function resetQuizToConfig() {
    activeQuiz = null;
    activeQuestions = [];
    userQuizAnswers = {};
    currentQuestionIndex = 0;

    document.getElementById("quizTakingWrap").style.display = "none";
    document.getElementById("quizEvaluationWrap").style.display = "none";
    document.getElementById("quizConfigCard").style.display = "block";

    if (currentVideoId) {
        loadPastQuizzes(currentVideoId);
    }
}

async function submitQuizAnswers() {
    if (!activeQuiz) return;

    const btnSubmit = document.getElementById("btnQuizSubmit");
    if (btnSubmit) {
        btnSubmit.disabled = true;
        btnSubmit.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Evaluating...`;
    }

    try {
        const res = await fetch(`/api/v1/quizzes/${activeQuiz.id}/submit`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                answers: userQuizAnswers
            })
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || "Submission failed.");
        }

        const report = await res.json();
        lastQuizAttempt = report;
        renderQuizEvaluation(report);
    } catch (e) {
        console.error("Error submitting quiz:", e);
        alert(e.message || "Failed to submit quiz.");
    } finally {
        if (btnSubmit) {
            btnSubmit.disabled = false;
            btnSubmit.innerHTML = `<i class="fa-solid fa-check-circle"></i> Submit Quiz`;
        }
    }
}

function renderQuizEvaluation(report) {
    document.getElementById("quizTakingWrap").style.display = "none";
    document.getElementById("quizConfigCard").style.display = "none";
    const evalWrap = document.getElementById("quizEvaluationWrap");
    evalWrap.style.display = "flex";

    const pct = report.percentage || 0;
    const isPassed = pct >= 70;

    const strongAreas = report.strong_areas || [];
    const needsImprovement = report.needs_improvement || [];
    const questionResults = report.question_results || [];

    const strongHtml = strongAreas.length > 0
        ? strongAreas.map(t => `<span class="topic-tag strong"><i class="fa-solid fa-circle-check"></i> ${escapeHtml(t)}</span>`).join("")
        : `<span style="font-size: 0.74rem; color: var(--text-dark);">No topics identified yet.</span>`;

    const weakHtml = needsImprovement.length > 0
        ? needsImprovement.map(t => `<span class="topic-tag weak"><i class="fa-solid fa-triangle-exclamation"></i> ${escapeHtml(t)}</span>`).join("")
        : `<span style="font-size: 0.74rem; color: #34d399;"><i class="fa-solid fa-trophy"></i> Outstanding! No weak areas.</span>`;

    const questionsHtml = questionResults.map((qr, idx) => {
        const isCorrect = qr.is_correct;
        const isUnanswered = qr.status === 'unanswered';
        const cardClass = isCorrect ? 'correct' : (isUnanswered ? 'unanswered' : 'incorrect');

        let statusBadge = '';
        if (isCorrect) {
            statusBadge = `<span style="color: #34d399; font-weight: 700; font-size: 0.74rem;"><i class="fa-solid fa-check-circle"></i> Correct (+1)</span>`;
        } else if (isUnanswered) {
            statusBadge = `<span style="color: #94a3b8; font-weight: 700; font-size: 0.74rem;"><i class="fa-solid fa-circle-minus"></i> Unanswered (0)</span>`;
        } else {
            statusBadge = `<span style="color: #f87171; font-weight: 700; font-size: 0.74rem;"><i class="fa-solid fa-circle-xmark"></i> Incorrect (0)</span>`;
        }

        // Smart Relearn button for incorrect or unanswered questions
        let relearnBtn = '';
        if (!isCorrect && qr.timestamp_start !== null && qr.timestamp_start !== undefined) {
            const timeFormatted = formatSeconds(qr.timestamp_start);
            relearnBtn = `
                <div class="relearn-callout">
                    <div class="relearn-callout-title">
                        <i class="fa-solid fa-compass" style="color: #38bdf8;"></i>
                        <span>Targeted Video Relearn Segment</span>
                    </div>
                    <div style="font-size: 0.74rem; color: var(--text-muted); margin-bottom: 0.4rem;">
                        Watch the exact lesson segment where this concept is demonstrated in the video.
                    </div>
                    <div style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
                        <button class="btn-watch-relearn" onclick="seekAndPlayVideo(${qr.timestamp_start})">
                            <i class="fa-solid fa-play"></i>
                            <span>Watch &amp; Learn Again at ${timeFormatted}</span>
                        </button>
                        <button class="filter-pill" style="font-size: 0.72rem; padding: 0.3rem 0.65rem;" onclick="retrySingleQuestion(${idx})">
                            <i class="fa-solid fa-rotate-right"></i> Try Again
                        </button>
                    </div>
                </div>
            `;
        }

        return `
            <div class="eval-question-card ${cardClass}">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.4rem;">
                    <div style="font-size: 0.72rem; font-weight: 700; color: #818cf8; text-transform: uppercase;">
                        Question ${idx + 1} · <span style="color: var(--text-muted);">${escapeHtml(qr.topic || 'General')}</span>
                    </div>
                    ${statusBadge}
                </div>
                <div style="font-size: 0.88rem; font-weight: 700; color: #f8fafc; margin-bottom: 0.5rem;">
                    ${escapeHtml(qr.question || qr.question_text || '')}
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; font-size: 0.75rem; margin-bottom: 0.5rem;">
                    <div style="background: rgba(255,255,255,0.02); padding: 0.35rem 0.5rem; border-radius: var(--radius-xs);">
                        <strong style="color: var(--text-muted);">Your Answer:</strong> 
                        <span style="color: ${isCorrect ? '#34d399' : '#f87171'}; font-weight: 600;">${escapeHtml(qr.user_answer || '(None)')}</span>
                    </div>
                    <div style="background: rgba(255,255,255,0.02); padding: 0.35rem 0.5rem; border-radius: var(--radius-xs);">
                        <strong style="color: var(--text-muted);">Correct Answer:</strong> 
                        <span style="color: #34d399; font-weight: 600;">${escapeHtml(qr.correct_answer || 'N/A')}</span>
                    </div>
                </div>
                <div style="font-size: 0.74rem; color: #cbd5e1; line-height: 1.45; background: rgba(0,0,0,0.2); padding: 0.45rem 0.6rem; border-radius: var(--radius-xs);">
                    <strong style="color: #93c5fd;">Explanation:</strong> ${escapeHtml(qr.explanation || 'No explanation provided.')}
                </div>
                ${relearnBtn}
            </div>
        `;
    }).join("");

    evalWrap.innerHTML = `
        <div class="scorecard-container">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; gap: 0.5rem;">
                <div>
                    <div style="font-size: 1.1rem; font-weight: 800; color: #f8fafc;">Knowledge Evaluation Report</div>
                    <div style="font-size: 0.74rem; color: var(--text-muted);">Strictly grounded against analyzed video segments and timestamps</div>
                </div>
                <div class="scorecard-metric" style="min-width: 140px;">
                    <div class="scorecard-value ${isPassed ? 'good' : 'warning'}">${report.score} / ${report.total_questions}</div>
                    <div class="scorecard-label">${pct}% Overall Accuracy</div>
                </div>
            </div>

            <div class="scorecard-grid">
                <div class="scorecard-metric">
                    <div class="scorecard-value good">${report.correct_count}</div>
                    <div class="scorecard-label">Correct</div>
                </div>
                <div class="scorecard-metric">
                    <div class="scorecard-value bad">${report.incorrect_count}</div>
                    <div class="scorecard-label">Incorrect</div>
                </div>
                <div class="scorecard-metric">
                    <div class="scorecard-value neutral">${report.unanswered_count}</div>
                    <div class="scorecard-label">Unanswered</div>
                </div>
            </div>

            <div class="topic-diagnostic-card">
                <div style="font-size: 0.76rem; font-weight: 800; color: #f8fafc; text-transform: uppercase; margin-bottom: 0.5rem;">
                    Topic-Wise Diagnostics
                </div>
                <div style="display: flex; flex-direction: column; gap: 0.5rem;">
                    <div>
                        <div style="font-size: 0.7rem; font-weight: 700; color: #34d399; margin-bottom: 0.25rem;">STRONG AREAS (&gt;= 75%)</div>
                        <div class="topic-tag-list">${strongHtml}</div>
                    </div>
                    <div>
                        <div style="font-size: 0.7rem; font-weight: 700; color: #f59e0b; margin-bottom: 0.25rem;">NEEDS IMPROVEMENT (&lt; 75%)</div>
                        <div class="topic-tag-list">${weakHtml}</div>
                    </div>
                </div>
            </div>

            <div class="quiz-export-actions">
                <button class="filter-pill" onclick="resetQuizToConfig()" style="font-weight: 700; background: rgba(56, 189, 248, 0.15); border-color: var(--primary); color: #f8fafc;">
                    <i class="fa-solid fa-arrow-left"></i> Back to Quizzes
                </button>
                <button class="btn-pdf-export btn-pdf-paper" onclick="downloadQuestionPaperPdf('${report.quiz_id}')" title="Download Printable Question Paper PDF">
                    <i class="fa-solid fa-file-lines"></i>
                    <span>Download Questions PDF</span>
                </button>
                <button class="btn-pdf-export btn-pdf-answers" onclick="downloadAnswerKeyPdf('${report.quiz_id}')" title="Download Questions + Answer Key PDF">
                    <i class="fa-solid fa-key"></i>
                    <span>Download Q&amp;A Answer Key PDF</span>
                </button>
                <button class="filter-pill" onclick="retakeCurrentQuiz()">
                    <i class="fa-solid fa-rotate-left"></i> Retake Quiz
                </button>
            </div>
        </div>

        <div style="display: flex; flex-direction: column; gap: 0.75rem;">
            <div style="font-size: 0.8rem; font-weight: 800; color: #f8fafc; text-transform: uppercase;">
                Question-by-Question Detailed Review &amp; Grounding
            </div>
            ${questionsHtml}
        </div>
    `;
}

function retrySingleQuestion(idx) {
    document.getElementById("quizEvaluationWrap").style.display = "none";
    document.getElementById("quizTakingWrap").style.display = "block";
    renderQuizQuestion(idx);
}

function retakeCurrentQuiz() {
    userQuizAnswers = {};
    document.getElementById("quizEvaluationWrap").style.display = "none";
    document.getElementById("quizTakingWrap").style.display = "block";
    renderQuizQuestion(0);
}

function downloadQuestionPaperPdf(quizId) {
    if (!quizId) return;
    const url = `/api/v1/quizzes/${quizId}/pdf/questions`;
    window.open(url, "_blank");
}

function downloadAnswerKeyPdf(quizId) {
    if (!quizId) return;
    const url = `/api/v1/quizzes/${quizId}/pdf/answers`;
    window.open(url, "_blank");
}

function downloadEvaluationReportPdf(quizId, attemptId) {
    if (!quizId || !attemptId) return;
    const url = `/api/v1/quizzes/${quizId}/attempts/${attemptId}/pdf/report`;
    window.open(url, "_blank");
}

// =========================================================================
// Written Self-Test ("Test My Understanding") - AI Model Question Prompt
// =========================================================================
async function loadSelfTestPromptQuestion() {
    if (!currentVideoId) {
        return;
    }

    const questionTextEl = document.getElementById("selfTestModelQuestionText");
    const questionInputEl = document.getElementById("selfTestQuestionInput");
    const answerInputEl = document.getElementById("selfTestAnswerInput");
    const resultCardEl = document.getElementById("selfTestResultCard");

    // Clear previous user answer and hide evaluation card
    if (answerInputEl) answerInputEl.value = "";
    if (resultCardEl) resultCardEl.style.display = "none";

    if (questionTextEl) {
        questionTextEl.innerHTML = `<i class="fa-solid fa-spinner fa-spin" style="color: #fbbf24;"></i> <span style="color: var(--text-muted); font-size: 0.85rem;">Generating AI concept question from video...</span>`;
    }

    try {
        const res = await fetch(`/api/v1/videos/${currentVideoId}/self-test/prompt`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || "Failed to generate AI question.");
        }

        const data = await res.json();
        const qText = data.question || "Explain the core concepts presented in this video.";

        let questionMarkup = `
            <div style="font-size: 0.95rem; font-weight: 700; color: #f8fafc; line-height: 1.45;">
                ${escapeHtml(qText)}
            </div>
        `;

        if (questionTextEl) questionTextEl.innerHTML = questionMarkup;
        if (questionInputEl) questionInputEl.value = qText;
    } catch (e) {
        console.error("Error loading self-test prompt question:", e);
        const fallbackQ = "Explain the key concepts and evidence presented in this video in your own words.";
        if (questionTextEl) questionTextEl.innerText = fallbackQ;
        if (questionInputEl) questionInputEl.value = fallbackQ;
    }
}

// =========================================================================
// Written Self-Test ("Test My Understanding")
// =========================================================================
async function submitSelfTest() {
    if (!currentVideoId) {
        alert("Please select a video first.");
        return;
    }

    if (currentVideoData && currentVideoData.video_type === 'observational') {
        alert("Self-test is disabled for observational footage.");
        return;
    }

    const question = document.getElementById("selfTestQuestionInput")?.value || "";
    const answer = document.getElementById("selfTestAnswerInput")?.value || "";

    if (!answer.trim()) {
        alert("Please write your explanation first.");
        return;
    }

    const btn = document.getElementById("btnSubmitSelfTest");
    const spinner = document.getElementById("selfTestSpinner");
    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = "inline-flex";

    try {
        const res = await fetch(`/api/v1/videos/${currentVideoId}/self-test`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_question: question,
                user_answer: answer
            })
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || "Evaluation failed.");
        }

        const data = await res.json();
        renderSelfTestResult(data);
    } catch (e) {
        console.error("Error evaluating self-test:", e);
        alert(e.message || "Could not evaluate understanding.");
    } finally {
        if (btn) btn.disabled = false;
        if (spinner) spinner.style.display = "none";
    }
}

function renderSelfTestResult(res) {
    const card = document.getElementById("selfTestResultCard");
    if (!card) return;

    card.style.display = "block";

    const score = res.score ?? res.rubric_score ?? 0;
    let scoreColor = '#34d399';
    let statusText = res.status || 'Mastered';

    if (score >= 8 || statusText.toLowerCase().includes('mastered')) {
        scoreColor = '#34d399';
        statusText = 'Mastered (Excellent Understanding)';
    } else if (score >= 6 || statusText.toLowerCase().includes('good')) {
        scoreColor = '#38bdf8';
        statusText = 'Good Understanding';
    } else if (score >= 4 || statusText.toLowerCase().includes('partial')) {
        scoreColor = '#f59e0b';
        statusText = 'Partial Understanding (Weak)';
    } else {
        scoreColor = '#f87171';
        statusText = 'Needs Review';
    }

    let missingPointsHtml = '';
    const missing = res.missing_points || [];
    if (missing.length > 0) {
        missingPointsHtml = `
            <div style="margin-top: 0.6rem; background: rgba(239,68,68,0.08); border-left: 3px solid #f87171; padding: 0.5rem 0.65rem; border-radius: var(--radius-xs);">
                <div style="font-size: 0.72rem; font-weight: 700; color: #f87171; margin-bottom: 0.2rem;">KEY POINTS MISSED:</div>
                <ul style="margin: 0; padding-left: 1.1rem; font-size: 0.74rem; color: #fecaca; line-height: 1.4;">
                    ${missing.map(p => `<li>${escapeHtml(p)}</li>`).join("")}
                </ul>
            </div>
        `;
    }

    // Only show targeted video relearn button IF the answer is weak / incomplete (score < 8 or status is not Mastered)
    let relearnBtn = '';
    const tStart = res.relevant_timestamp_start ?? res.timestamp_start;
    const tFmt = res.relevant_timestamp_formatted || (tStart !== null && tStart !== undefined ? formatSeconds(tStart) : '');
    const isWeakAnswer = (score < 8) || (res.status && !res.status.toLowerCase().includes('mastered'));

    if (isWeakAnswer && tStart !== null && tStart !== undefined) {
        relearnBtn = `
            <div class="relearn-callout" style="margin-top: 0.75rem; background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.25); border-radius: var(--radius-sm); padding: 0.75rem 0.9rem;">
                <div class="relearn-callout-title" style="font-size: 0.82rem; font-weight: 700; color: #fbbf24; margin-bottom: 0.3rem; display: flex; align-items: center; gap: 0.4rem;">
                    <i class="fa-solid fa-graduation-cap" style="color: #fbbf24;"></i>
                    <span>Weak / Incomplete Explanation – Target Re-learn</span>
                </div>
                <div style="font-size: 0.76rem; color: var(--text-muted); margin-bottom: 0.4rem;">
                    Your explanation needs improvement. Watch the video lesson segment at <strong>${escapeHtml(tFmt)}</strong> to re-learn this concept:
                </div>
                <button class="btn-watch-relearn" onclick="seekAndPlayVideo(${tStart})" style="background: linear-gradient(135deg, #f59e0b, #d97706); color: #ffffff; font-weight: 600; font-size: 0.78rem; padding: 0.35rem 0.85rem; border-radius: 6px; border: none; cursor: pointer; display: inline-flex; align-items: center; gap: 0.4rem;">
                    <i class="fa-solid fa-play"></i>
                    <span>Watch &amp; Learn Again at ${escapeHtml(tFmt)}</span>
                </button>
            </div>
        `;
    }

    card.innerHTML = `
        <div class="scorecard-container">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; gap: 0.5rem;">
                <div>
                    <div style="font-size: 1rem; font-weight: 800; color: #f8fafc;">Understanding Evaluation</div>
                    <div style="font-size: 0.74rem; color: ${scoreColor}; font-weight: 700;">${statusText}</div>
                </div>
                <div class="scorecard-metric" style="min-width: 120px;">
                    <div class="scorecard-value" style="color: ${scoreColor};">${score} / 10</div>
                    <div class="scorecard-label">Rubric Score</div>
                </div>
            </div>

            <div style="display: flex; flex-direction: column; gap: 0.6rem; font-size: 0.76rem;">
                <div style="background: rgba(255,255,255,0.02); padding: 0.5rem 0.75rem; border-radius: var(--radius-xs); line-height: 1.45;">
                    <strong style="color: #38bdf8;">Diagnostic Feedback:</strong>
                    <p style="margin: 0.25rem 0 0 0; color: #e2e8f0;">${escapeHtml(res.feedback || 'No feedback provided.')}</p>
                </div>

                <div style="background: rgba(255,255,255,0.02); padding: 0.5rem 0.75rem; border-radius: var(--radius-xs); line-height: 1.45;">
                    <strong style="color: #34d399;">Expected Core Concept:</strong>
                    <p style="margin: 0.25rem 0 0 0; color: #cbd5e1;">${escapeHtml(res.correct_concept || 'N/A')}</p>
                </div>

                ${missingPointsHtml}
                ${relearnBtn}
            </div>

            <div style="margin-top: 0.75rem; display: flex; gap: 0.5rem;">
                <button class="filter-pill" onclick="clearSelfTest()">
                    <i class="fa-solid fa-pen"></i> Write Another
                </button>
            </div>
        </div>
    `;
}

function clearSelfTest() {
    const qIn = document.getElementById("selfTestQuestionInput");
    const aIn = document.getElementById("selfTestAnswerInput");
    const card = document.getElementById("selfTestResultCard");
    if (qIn) qIn.value = "";
    if (aIn) aIn.value = "";
    if (card) card.style.display = "none";
}

function seekAndPlayVideo(seconds) {
    if (typeof closeContextModal === "function") {
        closeContextModal();
    }
    if (currentVideoId) {
        jumpToVideoAndTimestamp(currentVideoId, seconds, true);
    } else {
        const player = document.getElementById("videoPlayer");
        if (player) {
            player.currentTime = Math.max(0, parseFloat(seconds) || 0);
            player.play().catch(() => { });
            player.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }
}

// Workspace Layout View Switcher (De-cluttered Multi-Screen Workspace)
function setWorkspaceViewMode(mode) {
    const container = document.getElementById("mainContainer");
    if (!container) return;

    container.classList.remove("view-mode-grid", "view-mode-player", "view-mode-learning", "view-mode-chat");

    const btnGrid = document.getElementById("viewModeBtnGrid");
    const btnPlayer = document.getElementById("viewModeBtnPlayer");
    const btnLearning = document.getElementById("viewModeBtnLearning");
    const btnChat = document.getElementById("viewModeBtnChat");

    if (btnGrid) btnGrid.classList.toggle("active", mode === 'grid');
    if (btnPlayer) btnPlayer.classList.toggle("active", mode === 'player');
    if (btnLearning) btnLearning.classList.toggle("active", mode === 'learning');
    if (btnChat) btnChat.classList.toggle("active", mode === 'chat');

    if (mode === 'player') {
        container.classList.add("view-mode-player");
    } else if (mode === 'learning') {
        container.classList.add("view-mode-learning");
        if (currentVideoData && currentVideoData.video_type !== 'observational') {
            switchTab('quiz');
        }
    } else if (mode === 'chat') {
        container.classList.add("view-mode-chat");
    } else {
        container.classList.add("view-mode-grid");
    }
}

// =========================================================================
// Left Panel Upload Section Collapse Toggle
// =========================================================================
function toggleUploadSection() {
    const section = document.querySelector(".upload-section");
    const icon = document.getElementById("uploadToggleIcon");
    if (!section) return;

    const isCollapsed = section.classList.toggle("collapsed");
    if (icon) {
        icon.className = isCollapsed ? "fa-solid fa-chevron-down" : "fa-solid fa-chevron-up";
    }
}

// =========================================================================
// Full Context Inspection Modal Popup Screen
// =========================================================================
let activeModalTab = 'summary';

function openContextModal(tabName) {
    const modal = document.getElementById("contextModal");
    if (!modal) return;

    if (!currentVideoData) {
        alert("Please select a video from the library first.");
        return;
    }

    modal.style.display = "flex";

    // Header info
    const titleElem = document.getElementById("modalVideoTitle");
    const subElem = document.getElementById("modalVideoSub");
    if (titleElem) titleElem.innerText = currentVideoData.filename;
    if (subElem) subElem.innerText = `Type: ${currentVideoData.video_type_label || 'Observational / General'} · Duration: ${formatSeconds(currentVideoData.duration_seconds || 0)}`;

    // Badges
    const rawTranscripts = currentVideoData.raw_transcripts || [];
    const segments = currentVideoData.segments || [];
    const transcriptCount = rawTranscripts.length > 0 ? rawTranscripts.length : segments.filter(s => s.transcript_text && s.transcript_text.trim().length > 0).length;
    const visualCount = segments.filter(s => s.visual_description && s.visual_description.trim().length > 0).length;

    const tBadge = document.getElementById("modalTranscriptBadge");
    const vBadge = document.getElementById("modalVisualsBadge");
    if (tBadge) tBadge.innerText = transcriptCount;
    if (vBadge) vBadge.innerText = visualCount;

    let targetTab = tabName || (currentActiveTab === 'transcript' || currentActiveTab === 'visuals' ? currentActiveTab : 'summary');
    if (targetTab === 'overview') targetTab = 'summary';
    switchModalTab(targetTab);
}

function closeContextModal() {
    const modal = document.getElementById("contextModal");
    if (modal) modal.style.display = "none";

    // Restore moved elements to main pane containers
    const quizContainer = document.getElementById("quizContainer");
    const paneQuiz = document.getElementById("paneQuiz");
    if (quizContainer && paneQuiz && quizContainer.parentElement !== paneQuiz) {
        paneQuiz.appendChild(quizContainer);
    }
    const selfTestWrap = document.getElementById("selfTestWrap");
    const paneSelfTest = document.getElementById("paneSelfTest");
    if (selfTestWrap && paneSelfTest && selfTestWrap.parentElement !== paneSelfTest) {
        paneSelfTest.appendChild(selfTestWrap);
    }
}

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        closeContextModal();
    }
});

function switchModalTab(tabName) {
    activeModalTab = tabName;

    const btnSummary = document.getElementById("mTabSummary");
    const btnTranscript = document.getElementById("mTabTranscript");
    const btnVisuals = document.getElementById("mTabVisuals");
    const btnQuiz = document.getElementById("mTabQuiz");
    const btnSelfTest = document.getElementById("mTabSelfTest");

    if (btnSummary) btnSummary.classList.toggle("active", tabName === 'summary');
    if (btnTranscript) btnTranscript.classList.toggle("active", tabName === 'transcript');
    if (btnVisuals) btnVisuals.classList.toggle("active", tabName === 'visuals');
    if (btnQuiz) btnQuiz.classList.toggle("active", tabName === 'quiz');
    if (btnSelfTest) btnSelfTest.classList.toggle("active", tabName === 'selfTest' || tabName === 'selftest');

    renderModalBody();
}

function renderModalBody() {
    const body = document.getElementById("modalBody");
    if (!body || !currentVideoData) return;

    // Restore moved elements if tab switched away from quiz / selftest
    const quizContainer = document.getElementById("quizContainer");
    const paneQuiz = document.getElementById("paneQuiz");
    if (quizContainer && paneQuiz && activeModalTab !== 'quiz' && quizContainer.parentElement !== paneQuiz) {
        paneQuiz.appendChild(quizContainer);
    }
    const selfTestWrap = document.getElementById("selfTestWrap");
    const paneSelfTest = document.getElementById("paneSelfTest");
    if (selfTestWrap && paneSelfTest && (activeModalTab !== 'selftest' && activeModalTab !== 'selfTest') && selfTestWrap.parentElement !== paneSelfTest) {
        paneSelfTest.appendChild(selfTestWrap);
    }

    // Always clear modal body immediately to prevent previous tab content from sticking
    body.innerHTML = "";

    if (activeModalTab === 'quiz') {
        if (quizContainer) {
            quizContainer.style.display = "block";
            const quizTakingWrap = document.getElementById("quizTakingWrap");
            const quizResultsWrap = document.getElementById("quizResultsWrap");
            const quizConfigCard = document.getElementById("quizConfigCard");

            if (quizConfigCard && (!quizTakingWrap || quizTakingWrap.style.display === "none") && (!quizResultsWrap || quizResultsWrap.style.display === "none")) {
                quizConfigCard.style.display = "block";
            }
            body.appendChild(quizContainer);
            if (currentVideoData && currentVideoData.id) {
                loadPastQuizzes(currentVideoData.id);
            }
        } else {
            body.innerHTML = `<div style="padding: 2rem; text-align: center; color: var(--text-muted);">Quiz feature loading...</div>`;
        }
        return;
    }

    if (activeModalTab === 'selftest' || activeModalTab === 'selfTest') {
        if (selfTestWrap) {
            selfTestWrap.style.display = "block";
            body.appendChild(selfTestWrap);
            const qVal = document.getElementById("selfTestQuestionInput")?.value;
            if (!qVal || qVal.trim() === "" || qVal.includes("Loading AI concept")) {
                loadSelfTestPromptQuestion();
            }
        } else {
            body.innerHTML = `<div style="padding: 2rem; text-align: center; color: var(--text-muted);">Self-test feature loading...</div>`;
        }
        return;
    }

    const query = (document.getElementById("modalSearchInput")?.value || "").toLowerCase().trim();
    const segments = currentVideoData.segments || [];
    const rawTranscripts = currentVideoData.raw_transcripts || [];

    if (activeModalTab === 'summary') {
        const summaryText = currentVideoData.summary || "No executive summary generated for this video.";
        body.innerHTML = `
            <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 1.25rem;">
                <div style="font-size: 0.82rem; font-weight: 700; color: var(--primary); text-transform: uppercase; margin-bottom: 0.75rem; display: flex; align-items: center; gap: 0.5rem;">
                    <i class="fa-solid fa-file-lines"></i> Executive Video Overview
                </div>
                <div style="font-size: 0.95rem; color: #f8fafc; line-height: 1.65; white-space: pre-wrap;">${escapeHtml(summaryText)}</div>
            </div>

            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.85rem; margin-top: 0.5rem;">
                <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border); padding: 0.85rem; border-radius: var(--radius-sm);">
                    <div style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">Video Type</div>
                    <div style="font-size: 0.92rem; font-weight: 700; color: #34d399; margin-top: 0.2rem;">${escapeHtml(currentVideoData.video_type_label || 'Observational')}</div>
                </div>
                <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border); padding: 0.85rem; border-radius: var(--radius-sm);">
                    <div style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">Duration</div>
                    <div style="font-size: 0.92rem; font-weight: 700; color: #38bdf8; margin-top: 0.2rem;">${formatSeconds(currentVideoData.duration_seconds || 0)}</div>
                </div>
                <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border); padding: 0.85rem; border-radius: var(--radius-sm);">
                    <div style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">Classification Reason</div>
                    <div style="font-size: 0.78rem; color: #cbd5e1; margin-top: 0.2rem;">${escapeHtml(currentVideoData.video_type_reason || 'Classified by perception engine.')}</div>
                </div>
            </div>
        `;
    } else if (activeModalTab === 'transcript') {
        let items = [];
        if (rawTranscripts.length > 0) {
            items = rawTranscripts;
        } else {
            items = segments.filter(s => s.transcript_text && s.transcript_text.trim().length > 0);
        }

        if (query) {
            items = items.filter(item => {
                const txt = (item.text || item.transcript_text || "").toLowerCase();
                return txt.includes(query);
            });
        }

        if (items.length === 0) {
            body.innerHTML = `<p style="color: var(--text-dark); text-align: center; padding: 2rem;">No speech or audio transcript matching query.</p>`;
            return;
        }

        body.innerHTML = items.map((item, idx) => {
            const st = item.start !== undefined ? item.start : item.start_time;
            const et = item.end !== undefined ? item.end : item.end_time;
            const txt = item.text || item.transcript_text || "";
            const timeFmt = `${formatSeconds(st)} - ${formatSeconds(et)}`;

            return `
                <div style="display: flex; gap: 0.85rem; align-items: flex-start; background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border); padding: 0.75rem 1rem; border-radius: var(--radius-sm);">
                    <button class="ai-time-jump" onclick="seekAndPlayVideo(${st}); closeContextModal();" style="padding: 0.25rem 0.65rem; font-size: 0.78rem;">
                        <i class="fa-solid fa-play"></i> ${timeFmt}
                    </button>
                    <div style="flex: 1; font-size: 0.88rem; color: #f1f5f9; line-height: 1.5;">${escapeHtml(txt)}</div>
                </div>
            `;
        }).join("");
    } else if (activeModalTab === 'visuals') {
        let items = segments.filter(s => (s.visual_description && s.visual_description.trim().length > 0) || (s.ocr_text && s.ocr_text.trim().length > 0));

        if (query) {
            items = items.filter(s => {
                const text = `${s.visual_description || ''} ${s.ocr_text || ''}`.toLowerCase();
                return text.includes(query);
            });
        }

        if (items.length === 0) {
            body.innerHTML = `<p style="color: var(--text-dark); text-align: center; padding: 2rem;">No visual scene logs matching query.</p>`;
            return;
        }

        body.innerHTML = items.map((seg, idx) => {
            const timeFmt = `${formatSeconds(seg.start_time)} - ${formatSeconds(seg.end_time)}`;
            return `
                <div style="display: flex; flex-direction: column; gap: 0.5rem; background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border); padding: 0.85rem 1rem; border-radius: var(--radius-sm);">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <button class="ai-time-jump" onclick="seekAndPlayVideo(${seg.start_time}); closeContextModal();" style="padding: 0.25rem 0.65rem; font-size: 0.78rem;">
                            <i class="fa-solid fa-camera"></i> Scene ${idx + 1} (${timeFmt})
                        </button>
                        ${seg.ocr_text ? `<span class="modality-pill modality-pill-ocr"><i class="fa-solid fa-font"></i> OCR Detected</span>` : ''}
                    </div>
                    ${seg.visual_description ? `<div style="font-size: 0.86rem; color: #f1f5f9; line-height: 1.45;"><strong style="color: #38bdf8;">Visual Observation:</strong> ${escapeHtml(seg.visual_description)}</div>` : ''}
                    ${seg.ocr_text ? `<div style="font-size: 0.82rem; color: #fbbf24; background: rgba(245, 158, 11, 0.1); padding: 0.4rem 0.65rem; border-radius: 4px;"><strong style="color: #f59e0b;">On-Screen OCR:</strong> ${escapeHtml(seg.ocr_text)}</div>` : ''}
                </div>
            `;
        }).join("");
    }
}

function filterModalContext() {
    renderModalBody();
}
