let currentVideoId = null;
let currentSessionId = null;
let currentVideoData = null;
let currentActiveTab = 'transcript';
let pollTimer = null;

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
    loadVideoList();
    loadHITLReviews();

    const fileInput = document.getElementById("fileInput");
    if (fileInput) {
        fileInput.addEventListener("change", handleFileSelect);
    }

    const dropzone = document.getElementById("dropzone");
    if (dropzone) {
        dropzone.addEventListener("dragover", (e) => {
            e.preventDefault();
            dropzone.style.borderColor = "#38bdf8";
        });
        dropzone.addEventListener("dragleave", () => {
            dropzone.style.borderColor = "rgba(56, 189, 248, 0.35)";
        });
        dropzone.addEventListener("drop", async (e) => {
            e.preventDefault();
            dropzone.style.borderColor = "rgba(56, 189, 248, 0.35)";
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                await handleMultipleFiles(Array.from(e.dataTransfer.files));
            }
        });
    }

    // Interactive synchronized video playback listener
    const player = document.getElementById("videoPlayer");
    if (player) {
        player.addEventListener("timeupdate", handleVideoTimeUpdate);
    }
});

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

    for (let i = 0; i < validFiles.length; i++) {
        const file = validFiles[i];
        const stageLabel = document.getElementById("stageLabel");
        if (stageLabel && validFiles.length > 1) {
            stageLabel.innerText = `Uploading [${i + 1}/${validFiles.length}]: ${file.name}...`;
        }
        await uploadVideoFile(file);
    }
}

function switchUploadMode(mode) {
    const btnFile = document.getElementById("btnModeFile");
    const btnUrl = document.getElementById("btnModeUrl");
    const dropzone = document.getElementById("dropzone");
    const paneUrl = document.getElementById("paneUrl");

    if (mode === "url") {
        btnFile.classList.remove("active");
        btnUrl.classList.add("active");
        dropzone.style.display = "none";
        paneUrl.style.display = "flex";
        setTimeout(() => document.getElementById("videoUrlInput").focus(), 50);
    } else {
        btnUrl.classList.remove("active");
        btnFile.classList.add("active");
        paneUrl.style.display = "none";
        dropzone.style.display = "block";
    }
}

function handleUrlKeyPress(e) {
    if (e.key === "Enter") {
        importFromUrl();
    }
}

async function importFromUrl() {
    const input = document.getElementById("videoUrlInput");
    const btn = document.getElementById("btnFetchUrl");
    const url = (input.value || "").trim();

    if (!url) {
        alert("Please enter a valid YouTube or video URL.");
        input.focus();
        return;
    }

    if (!url.startsWith("http://") && !url.startsWith("https://")) {
        alert("URL must begin with http:// or https://");
        input.focus();
        return;
    }

    const progressBox = document.getElementById("progressBox");
    const stageLabel = document.getElementById("stageLabel");
    const percentLabel = document.getElementById("percentLabel");
    const progressBar = document.getElementById("progressBar");

    progressBox.style.display = "block";
    stageLabel.innerText = "Connecting to video stream...";
    percentLabel.innerText = "...";
    progressBar.style.width = "15%";
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> <span>Fetching...</span>`;

    try {
        const res = await fetch("/api/v1/videos/from-url", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url })
        });

        if (!res.ok) {
            const err = await res.json();
            alert(`Fetch failed: ${err.detail || "Unable to download video from URL."}`);
            progressBox.style.display = "none";
            return;
        }

        const data = await res.json();
        input.value = "";
        currentVideoId = data.video_id;
        pollVideoStatus(currentVideoId);
    } catch (e) {
        alert(`Network error fetching video: ${e.message}`);
        progressBox.style.display = "none";
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-bolt"></i> <span>Fetch & Analyze</span>`;
    }
}

async function uploadVideoFile(file) {
    const formData = new FormData();
    formData.append("file", file);

    const progressBox = document.getElementById("progressBox");
    const stageLabel = document.getElementById("stageLabel");
    const percentLabel = document.getElementById("percentLabel");
    const progressBar = document.getElementById("progressBar");

    progressBox.style.display = "block";
    stageLabel.innerText = "Uploading...";
    percentLabel.innerText = "0%";
    progressBar.style.width = "0%";

    try {
        const res = await fetch("/api/v1/videos/upload", {
            method: "POST",
            body: formData
        });

        if (!res.ok) {
            const err = await res.json();
            alert(`Upload failed: ${err.detail || "Unknown error"}`);
            progressBox.style.display = "none";
            return;
        }

        const data = await res.json();
        currentVideoId = data.video_id;
        pollVideoStatus(currentVideoId);
    } catch (e) {
        alert(`Error uploading file: ${e.message}`);
        progressBox.style.display = "none";
    }
}

function pollVideoStatus(videoId) {
    if (pollTimer) clearInterval(pollTimer);

    const progressBox = document.getElementById("progressBox");
    const stageLabel = document.getElementById("stageLabel");
    const percentLabel = document.getElementById("percentLabel");
    const progressBar = document.getElementById("progressBar");

    pollTimer = setInterval(async () => {
        try {
            const res = await fetch(`/api/v1/videos/${videoId}/status`);
            if (!res.ok) return;

            const data = await res.json();
            stageLabel.innerText = data.current_stage || "Processing...";
            percentLabel.innerText = `${data.progress_pct}%`;
            progressBar.style.width = `${data.progress_pct}%`;

            if (data.status === "completed") {
                clearInterval(pollTimer);
                setTimeout(() => {
                    progressBox.style.display = "none";
                    loadVideoList();
                    selectVideo(videoId);
                }, 800);
            } else if (data.status === "failed") {
                clearInterval(pollTimer);
                stageLabel.innerText = `Failed: ${data.error_message || "Unknown error"}`;
                stageLabel.style.color = "var(--accent-red)";
            }
        } catch (e) {
            console.error("Status polling error:", e);
        }
    }, 1500);
}

async function loadVideoList() {
    const listContainer = document.getElementById("videoList");
    try {
        const res = await fetch("/api/v1/videos");
        if (!res.ok) return;
        const videos = await res.json();

        if (videos.length === 0) {
            listContainer.innerHTML = '<p style="font-size: 0.78rem; color: var(--text-dark); text-align: center; padding-top: 1rem;">No videos in library.</p>';
            return;
        }

        listContainer.innerHTML = videos.map(v => `
            <div class="video-item ${v.video_id === currentVideoId ? 'active' : ''}" onclick="selectVideo('${v.video_id}')">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem;">
                    <div class="video-name" title="${escapeHtml(v.filename)}">${escapeHtml(v.filename)}</div>
                    <button class="btn-delete-video" title="Delete video" onclick="deleteVideo(event, '${v.video_id}')">✕</button>
                </div>
                <div class="video-meta">
                    <span><i class="fa-regular fa-clock"></i> ${v.duration_seconds ? formatSeconds(v.duration_seconds) : 'N/A'}</span>
                    <span style="color: ${v.status === 'completed' ? '#34d399' : v.status === 'failed' ? '#ef4444' : '#38bdf8'}">${v.status}</span>
                </div>
            </div>
        `).join("");

        // Auto-select first completed if none active
        if (!currentVideoId && videos.length > 0) {
            const firstCompleted = videos.find(v => v.status === "completed") || videos[0];
            selectVideo(firstCompleted.video_id);
        }
    } catch (e) {
        console.error("Error loading videos:", e);
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
                const player = document.getElementById("videoPlayer");
                if (player) player.src = "";
                document.getElementById("playerTitle").innerText = "Select a video to begin";
                document.getElementById("playerMetaBadge").style.display = "none";
                document.getElementById("inspectorContent").innerHTML = `
                    <div class="empty-state">
                        <i class="fa-solid fa-play-circle fa-2x"></i>
                        <p>Select an uploaded video to view synchronized transcript, visual perception, and keyframe timeline.</p>
                    </div>
                `;
                document.getElementById("chatMessages").innerHTML = '<div class="message assistant">Select or upload a video to begin analysis.</div>';
            }
            loadVideoList();
        } else {
            alert("Failed to delete video.");
        }
    } catch (e) {
        console.error("Error deleting video:", e);
    }
}

function formatSeconds(sec) {
    if (isNaN(sec) || sec === null || sec === undefined) return "00:00";
    const totalSec = Math.floor(sec);
    const m = Math.floor(totalSec / 60).toString().padStart(2, '0');
    const s = (totalSec % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
}

async function selectVideo(videoId) {
    currentVideoId = videoId;
    currentSessionId = null;
    loadVideoList();
    loadHITLReviews();

    const player = document.getElementById("videoPlayer");
    player.src = `/api/v1/videos/${videoId}/stream`;

    try {
        const res = await fetch(`/api/v1/videos/${videoId}`);
        if (!res.ok) return;
        currentVideoData = await res.json();

        // Update header & badges
        document.getElementById("playerTitle").innerText = currentVideoData.filename;
        const metaBadge = document.getElementById("playerMetaBadge");
        metaBadge.style.display = "block";
        document.getElementById("playerDurationText").innerText = formatSeconds(currentVideoData.duration_seconds || 0);

        // Calculate counts
        const segments = currentVideoData.segments || [];
        const transcriptSegments = segments.filter(s => s.transcript_text && s.transcript_text.trim().length > 0);
        const visualSegments = segments.filter(s => s.visual_description && s.visual_description.trim().length > 0);

        document.getElementById("tabTranscriptBadge").innerText = transcriptSegments.length;
        document.getElementById("tabVisualsBadge").innerText = visualSegments.length;

        // Auto-select transcript tab if audio exists, otherwise visual tab
        if (transcriptSegments.length > 0) {
            currentActiveTab = 'transcript';
        } else {
            currentActiveTab = 'visuals';
        }

        switchTab(currentActiveTab);

        // Reset chat with contextual greeting
        const chatMessages = document.getElementById("chatMessages");
        chatMessages.innerHTML = `
            <div class="message assistant">
                Loaded <strong>${escapeHtml(currentVideoData.filename)}</strong> (${formatSeconds(currentVideoData.duration_seconds || 0)}). Ask anything about spoken dialogue, actions, people, objects, or specific timestamps!
            </div>
        `;
    } catch (e) {
        console.error("Error fetching video details:", e);
    }
}

function switchTab(tabName) {
    currentActiveTab = tabName;

    // Update active tab buttons
    document.getElementById("tabBtnTranscript").classList.toggle("active", tabName === 'transcript');
    document.getElementById("tabBtnVisuals").classList.toggle("active", tabName === 'visuals');
    document.getElementById("tabBtnOverview").classList.toggle("active", tabName === 'overview');

    // Show/hide sub-bar actions
    const actionsBar = document.getElementById("inspectorActionsBar");
    if (tabName === 'transcript') {
        actionsBar.style.display = "flex";
    } else {
        actionsBar.style.display = "none";
    }

    renderTabContent();
}

function renderTabContent() {
    const container = document.getElementById("inspectorContent");
    if (!currentVideoData) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-play-circle fa-2x"></i>
                <p>Select an uploaded video to view synchronized transcript, visual perception, and keyframe timeline.</p>
            </div>
        `;
        return;
    }

    const segments = currentVideoData.segments || [];

    if (currentActiveTab === 'transcript') {
        const transcriptSegments = segments.filter(s => s.transcript_text && s.transcript_text.trim().length > 0);

        if (transcriptSegments.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fa-solid fa-microphone-slash fa-2x" style="color: var(--text-dark);"></i>
                    <p>No spoken dialogue detected in this video.<br>
                    <a href="javascript:void(0)" onclick="switchTab('visuals')" style="color: var(--primary); text-decoration: none; font-weight: 600;">View Visual Scenes Tab &rarr;</a></p>
                </div>
            `;
            return;
        }

        // Group consecutive segments with identical transcript text
        const grouped = [];
        transcriptSegments.forEach(s => {
            const text = s.transcript_text.trim();
            const last = grouped[grouped.length - 1];
            if (last && last.text === text) {
                last.end_time = s.end_time;
            } else {
                grouped.push({
                    start_time: s.start_time,
                    end_time: s.end_time,
                    text: text
                });
            }
        });

        container.innerHTML = grouped.map((g, idx) => `
            <div class="transcript-item" id="transcript-item-${idx}" data-start="${g.start_time}" data-end="${g.end_time}" onclick="seekVideo(${g.start_time})">
                <button class="pill-time" title="Jump to ${formatSeconds(g.start_time)}">
                    <i class="fa-solid fa-play" style="font-size: 0.5rem;"></i> ${formatSeconds(g.start_time)} - ${formatSeconds(g.end_time)}
                </button>
                <div class="transcript-dialogue">${escapeHtml(g.text)}</div>
            </div>
        `).join("");

    } else if (currentActiveTab === 'visuals') {
        const visualSegments = segments.filter(s => s.visual_description && s.visual_description.trim().length > 0);

        if (visualSegments.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fa-solid fa-camera fa-2x"></i>
                    <p>No visual scenes indexed for this clip.</p>
                </div>
            `;
            return;
        }

        container.innerHTML = visualSegments.map((s, idx) => {
            const desc = s.visual_description.replace(/^At\s+\d+(\.\d+)?s\s+in\s+video:\s*/i, "");
            return `
                <div class="transcript-item" data-start="${s.start_time}" data-end="${s.end_time}" onclick="seekVideo(${s.start_time})">
                    <button class="pill-time" title="Jump to scene at ${formatSeconds(s.start_time)}">
                        <i class="fa-solid fa-camera" style="font-size: 0.55rem;"></i> ${formatSeconds(s.start_time)} - ${formatSeconds(s.end_time)}
                    </button>
                    <div class="transcript-dialogue">
                        <span style="color: var(--primary); font-weight: 600;">Scene ${idx + 1}:</span> ${escapeHtml(desc)}
                    </div>
                </div>
            `;
        }).join("");

    } else if (currentActiveTab === 'overview') {
        container.innerHTML = `
            <div class="overview-box">
                <div style="font-weight: 700; color: #f8fafc; margin-bottom: 0.4rem; display: flex; align-items: center; gap: 0.4rem;">
                    <i class="fa-solid fa-circle-nodes" style="color: var(--primary);"></i>
                    <span>Executive Summary</span>
                </div>
                <p style="line-height: 1.5; color: #cbd5e1;">${escapeHtml(currentVideoData.summary || "Summary processing...")}</p>
                
                <div class="overview-meta-grid">
                    <div class="meta-tile">
                        <div class="meta-tile-label">Duration</div>
                        <div class="meta-tile-val">${formatSeconds(currentVideoData.duration_seconds || 0)} (${(currentVideoData.duration_seconds || 0).toFixed(1)}s)</div>
                    </div>
                    <div class="meta-tile">
                        <div class="meta-tile-label">Indexed Segments</div>
                        <div class="meta-tile-val">${currentVideoData.segments_count || 0} Multimodal Slices</div>
                    </div>
                    <div class="meta-tile">
                        <div class="meta-tile-label">Audio Stream</div>
                        <div class="meta-tile-val" style="color: #34d399;">Processed (16kHz PCM)</div>
                    </div>
                    <div class="meta-tile">
                        <div class="meta-tile-label">Indexing Engine</div>
                        <div class="meta-tile-val" style="color: var(--primary);">PostgreSQL + pgvector</div>
                    </div>
                </div>
            </div>
        `;
    }
}

// Synchronized Playback: Highlight current spoken speech segment as video plays
function handleVideoTimeUpdate() {
    if (currentActiveTab !== 'transcript') return;

    const player = document.getElementById("videoPlayer");
    if (!player) return;

    const currentTime = player.currentTime;
    const items = document.querySelectorAll(".transcript-item");

    items.forEach(item => {
        const start = parseFloat(item.getAttribute("data-start"));
        const end = parseFloat(item.getAttribute("data-end"));

        if (currentTime >= start && currentTime <= end) {
            if (!item.classList.contains("active-speech")) {
                items.forEach(i => i.classList.remove("active-speech"));
                item.classList.add("active-speech");
                // Smooth scroll into view
                item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        }
    });
}

function filterTranscript(query) {
    const q = (query || "").trim().toLowerCase();
    const items = document.querySelectorAll(".transcript-item");

    items.forEach(item => {
        const text = item.textContent.toLowerCase();
        if (!q || text.includes(q)) {
            item.style.display = "flex";
        } else {
            item.style.display = "none";
        }
    });
}

function copyTranscript() {
    if (!currentVideoData || !currentVideoData.segments) return;

    const transcriptSegments = currentVideoData.segments.filter(s => s.transcript_text && s.transcript_text.trim());
    if (transcriptSegments.length === 0) {
        alert("No transcript available to copy.");
        return;
    }

    const fullText = transcriptSegments.map(s => `[${formatSeconds(s.start_time)} - ${formatSeconds(s.end_time)}] ${s.transcript_text.trim()}`).join("\n\n");
    navigator.clipboard.writeText(fullText).then(() => {
        const btn = document.getElementById("copyBtn");
        btn.innerHTML = `<i class="fa-solid fa-check" style="color: #34d399;"></i> <span style="color: #34d399;">Copied!</span>`;
        setTimeout(() => {
            btn.innerHTML = `<i class="fa-regular fa-copy"></i> <span>Copy</span>`;
        }, 2000);
    });
}

function seekVideo(seconds) {
    const player = document.getElementById("videoPlayer");
    if (player) {
        player.currentTime = seconds;
        player.play();
    }
}

function handleKeyPress(e) {
    if (e.key === "Enter") {
        sendChatMessage();
    }
}

function sendQuickPrompt(promptText) {
    const input = document.getElementById("queryInput");
    if (input) {
        input.value = promptText;
        sendChatMessage();
    }
}

async function sendChatMessage() {
    const input = document.getElementById("queryInput");
    const query = input.value.trim();
    if (!query) return;

    if (!currentVideoId) {
        alert("Please select an uploaded video first.");
        return;
    }

    input.value = "";
    const chatMessages = document.getElementById("chatMessages");

    // Append user message
    chatMessages.innerHTML += `
        <div class="message user">${escapeHtml(query)}</div>
    `;
    chatMessages.scrollTop = chatMessages.scrollHeight;

    // Show typing state
    const typingId = `typing-${Date.now()}`;
    chatMessages.innerHTML += `
        <div class="message assistant" id="${typingId}">
            <i class="fa-solid fa-spinner fa-spin"></i> Analyzing multimodal segments...
        </div>
    `;
    chatMessages.scrollTop = chatMessages.scrollHeight;

    try {
        const res = await fetch(`/api/v1/videos/${currentVideoId}/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                query: query,
                session_id: currentSessionId
            })
        });

        const typingElem = document.getElementById(typingId);
        if (typingElem) typingElem.remove();

        if (!res.ok) {
            chatMessages.innerHTML += `
                <div class="message assistant" style="color: var(--accent-red);">
                    <i class="fa-solid fa-triangle-exclamation"></i> Error communicating with chat service.
                </div>
            `;
            return;
        }

        const data = await res.json();
        currentSessionId = data.session_id;

        const confPct = Math.round(data.confidence_score * 100);
        let confColor = confPct >= 75 ? "#34d399" : confPct >= 50 ? "#f59e0b" : "#ef4444";

        let citationsHtml = "";
        if (data.citations && data.citations.length > 0) {
            citationsHtml = data.citations.map(c => `
                <button class="citation-tag" onclick="seekVideo(${c.start_time})" title="${escapeHtml(c.snippet)}">
                    <i class="fa-solid fa-play" style="font-size: 0.5rem;"></i> ${c.timestamp_formatted}
                </button>
            `).join("");
        }

        chatMessages.innerHTML += `
            <div class="message assistant">
                <div style="white-space: pre-wrap;">${escapeHtml(data.answer)}</div>
                <div class="message-meta">
                    ${citationsHtml}
                    <span style="color: ${confColor}; font-weight: 600; font-size: 0.72rem; margin-left: auto;">
                        ${confPct}% Confidence
                    </span>
                </div>
            </div>
        `;
        chatMessages.scrollTop = chatMessages.scrollHeight;

        if (data.requires_hitl) {
            loadHITLReviews();
        }

    } catch (e) {
        console.error("Chat error:", e);
        const typingElem = document.getElementById(typingId);
        if (typingElem) typingElem.remove();

        chatMessages.innerHTML += `
            <div class="message assistant" style="color: var(--accent-red);">
                <i class="fa-solid fa-triangle-exclamation"></i> Network error. Please retry.
            </div>
        `;
    }
}

async function loadHITLReviews() {
    const container = document.getElementById("hitlContainer");
    try {
        let url = "/api/v1/hitl/reviews?status_filter=pending";
        if (currentVideoId) {
            url += `&video_id=${currentVideoId}`;
        }
        const res = await fetch(url);
        if (!res.ok) return;
        const reviews = await res.json();

        if (reviews.length === 0) {
            container.innerHTML = '<p style="font-size: 0.72rem; color: var(--text-dark);">No pending reviews.</p>';
            return;
        }

        container.innerHTML = reviews.map(r => `
            <div class="hitl-item" id="hitl-${r.id}">
                <div style="font-weight: 600; color: #f8fafc;">Q: "${escapeHtml(r.query)}"</div>
                <div style="font-size: 0.72rem; color: var(--text-muted); margin: 0.2rem 0;">AI: ${escapeHtml(r.ai_answer.substring(0, 80))}...</div>
                <div style="display: flex; gap: 0.4rem; margin-top: 0.4rem;">
                    <button class="btn" style="padding: 0.2rem 0.6rem; font-size: 0.7rem; background: var(--accent-green); color: white;" onclick="submitHITL('${r.id}', 'approved')">
                        Approve
                    </button>
                    <button class="btn" style="padding: 0.2rem 0.6rem; font-size: 0.7rem; background: var(--primary); color: #090d16;" onclick="promptCorrection('${r.id}')">
                        Correct
                    </button>
                </div>
            </div>
        `).join("");
    } catch (e) {
        console.error("Error loading HITL reviews:", e);
    }
}

async function submitHITL(reviewId, action, reason = "Approved by reviewer", correction = null) {
    try {
        const res = await fetch(`/api/v1/hitl/reviews/${reviewId}/resolve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                action: action,
                review_reason: reason,
                reviewer_notes: reason,
                corrected_answer: correction
            })
        });

        if (res.ok) {
            const item = document.getElementById(`hitl-${reviewId}`);
            if (item) item.remove();
            loadHITLReviews();
        } else {
            alert("Failed to submit review.");
        }
    } catch (e) {
        console.error("Error submitting review:", e);
    }
}

function promptCorrection(reviewId) {
    const correction = prompt("Enter corrected answer for this query:");
    if (correction) {
        submitHITL(reviewId, "corrected", "Manual human reviewer correction", correction);
    }
}

function escapeHtml(text) {
    if (!text) return "";
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
