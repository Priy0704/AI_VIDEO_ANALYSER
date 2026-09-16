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
        alert("Please enter a valid video, meeting, or camera stream URL.");
        input.focus();
        return;
    }

    const urlLower = url.toLowerCase();
    if (!urlLower.startsWith("http://") && !urlLower.startsWith("https://") && !urlLower.startsWith("rtsp://") && !urlLower.startsWith("rtmp://")) {
        alert("URL must begin with http://, https://, or rtsp:// (for camera streams)");
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
            let errorMsg = `Unable to process video (HTTP ${res.status})`;
            try {
                const err = await res.json();
                errorMsg = err.detail || JSON.stringify(err);
            } catch {
                try {
                    const text = await res.text();
                    if (text) errorMsg = text;
                } catch {}
            }
            alert(`Fetch failed: ${errorMsg}`);
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
            let errorMsg = `Server error (HTTP ${res.status})`;
            try {
                const err = await res.json();
                errorMsg = err.detail || JSON.stringify(err);
            } catch {
                try {
                    const text = await res.text();
                    if (text) errorMsg = text;
                } catch {}
            }
            alert(`Upload failed: ${errorMsg}`);
            progressBox.style.display = "none";
            return;
        }

        const data = await res.json();
        fileInput.value = "";
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
                const paneTranscript = document.getElementById("paneTranscript");
                if (paneTranscript) {
                    paneTranscript.innerHTML = `
                        <div class="empty-state">
                            <i class="fa-solid fa-microphone-lines fa-2x"></i>
                            <p>Select a video to view synchronized lyrics and speech accordion.</p>
                        </div>
                    `;
                }
                const paneVisuals = document.getElementById("paneVisuals");
                if (paneVisuals) {
                    paneVisuals.innerHTML = `
                        <div class="empty-state">
                            <i class="fa-solid fa-camera fa-2x"></i>
                            <p>Select a video to inspect visual scenes and keyframe headlines.</p>
                        </div>
                    `;
                }
                const paneOverview = document.getElementById("paneOverview");
                if (paneOverview) {
                    paneOverview.innerHTML = `
                        <div class="empty-state">
                            <i class="fa-solid fa-file-lines fa-2x"></i>
                            <p>Select a video to view the executive summary.</p>
                        </div>
                    `;
                }
                document.getElementById("chatMessages").innerHTML = '<div class="message assistant">Select or upload a video to begin analysis.</div>';
            }
            loadVideoList();
        } else {
            let errorMsg = "Failed to delete video.";
            try {
                const err = await res.json();
                errorMsg = err.detail || errorMsg;
            } catch {}
            alert(errorMsg);
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

        renderTabContent();
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

    // Display appropriate independent scroller pane
    const paneTranscript = document.getElementById("paneTranscript");
    const paneVisuals = document.getElementById("paneVisuals");
    const paneOverview = document.getElementById("paneOverview");

    if (paneTranscript) paneTranscript.style.display = (tabName === 'transcript' ? 'flex' : 'none');
    if (paneVisuals) paneVisuals.style.display = (tabName === 'visuals' ? 'flex' : 'none');
    if (paneOverview) paneOverview.style.display = (tabName === 'overview' ? 'flex' : 'none');
}

function renderTabContent() {
    const paneTranscript = document.getElementById("paneTranscript");
    const paneVisuals = document.getElementById("paneVisuals");
    const paneOverview = document.getElementById("paneOverview");

    if (!currentVideoData) {
        if (paneTranscript) {
            paneTranscript.innerHTML = `
                <div class="empty-state">
                    <i class="fa-solid fa-microphone-lines fa-2x"></i>
                    <p>Select an uploaded video to view synchronized transcript and lyrics.</p>
                </div>
            `;
        }
        if (paneVisuals) {
            paneVisuals.innerHTML = `
                <div class="empty-state">
                    <i class="fa-solid fa-camera fa-2x"></i>
                    <p>Select an uploaded video to view visual scenes and keyframes.</p>
                </div>
            `;
        }
        if (paneOverview) {
            paneOverview.innerHTML = `
                <div class="empty-state">
                    <i class="fa-solid fa-file-lines fa-2x"></i>
                    <p>Select an uploaded video to view executive summary.</p>
                </div>
            `;
        }
        return;
    }

    const segments = currentVideoData.segments || [];

    // 1. RENDER TRANSCRIPT ACCORDION (Separate Scroller)
    if (paneTranscript) {
        const transcriptSegments = segments.filter(s => s.transcript_text && s.transcript_text.trim().length > 0);

        if (transcriptSegments.length === 0) {
            paneTranscript.innerHTML = `
                <div class="empty-state">
                    <i class="fa-solid fa-microphone-slash fa-2x" style="color: var(--text-dark);"></i>
                    <p>No spoken dialogue or lyrics detected in this video.<br>
                    <a href="javascript:void(0)" onclick="switchTab('visuals')" style="color: var(--primary); text-decoration: none; font-weight: 600;">View Visual Scenes Tab &rarr;</a></p>
                </div>
            `;
        } else {
            // Group consecutive identical segments
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

            paneTranscript.innerHTML = grouped.map((g, idx) => {
                const firstLine = (g.text || "").split("\n")[0].trim();
                const preview = firstLine.length > 70 ? firstLine.substring(0, 67) + "..." : firstLine;
                return `
                    <div class="transcript-card" id="transcript-card-${idx}" data-start="${g.start_time}" data-end="${g.end_time}" onclick="toggleTranscriptAccordion(${idx}, ${g.start_time})">
                        <div class="transcript-header">
                            <button class="pill-time" title="Jump to ${formatSeconds(g.start_time)}" onclick="event.stopPropagation(); seekVideo(${g.start_time});">
                                <i class="fa-solid fa-microphone-lines" style="font-size: 0.55rem;"></i> ${formatSeconds(g.start_time)} - ${formatSeconds(g.end_time)}
                            </button>
                            <div class="transcript-headline" title="${escapeHtml(g.text)}">
                                <span style="color: var(--primary); font-weight: 600;">#${idx + 1}:</span> ${escapeHtml(preview)}
                            </div>
                            <i class="fa-solid fa-chevron-down transcript-chevron" id="transcript-chevron-${idx}"></i>
                        </div>
                        <div class="transcript-body" id="transcript-body-${idx}">
                            <div class="scene-badge-label">
                                <i class="fa-solid fa-quote-left"></i> Spoken Lyrics & Dialogue
                            </div>
                            <p style="margin: 0; color: #cbd5e1; font-size: 0.83rem; line-height: 1.55; white-space: pre-wrap;">${escapeHtml(g.text)}</p>
                        </div>
                    </div>
                `;
            }).join("");
        }
    }

    // 2. RENDER VISUAL SCENES ACCORDION (Separate Scroller)
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
                let raw = s.visual_description.replace(/^At\s+\d+(\.\d+)?s\s+in\s+video:\s*/i, "").trim();
                
                let headline = "";
                let details = "";
                let onScreenText = "";

                const textMatch = raw.match(/On-Screen Text & Names:\s*([\s\S]+)$/i);
                if (textMatch) {
                    onScreenText = textMatch[1].trim();
                    raw = raw.replace(/On-Screen Text & Names:\s*[\s\S]+$/i, "").trim();
                }
                
                const headMatch = raw.match(/^(?:Headline:\s*)?(.+?)(?:\n\s*(?:Details:\s*)?([\s\S]+))?$/i);
                if (headMatch && headMatch[2]) {
                    headline = headMatch[1].trim();
                    details = headMatch[2].trim();
                } else {
                    const dotIdx = raw.indexOf(". ");
                    if (dotIdx > 8 && dotIdx < 110) {
                        headline = raw.substring(0, dotIdx + 1).trim();
                        details = raw.substring(dotIdx + 2).trim();
                    } else if (raw.length > 80) {
                        headline = raw.substring(0, 75).trim() + "...";
                        details = raw;
                    } else {
                        headline = raw;
                        details = raw;
                    }
                }

                headline = headline.replace(/^Headline:\s*/i, "").trim();
                details = details.replace(/^Details:\s*/i, "").trim();

                let onScreenBadge = "";
                if (onScreenText && onScreenText.toLowerCase() !== "none") {
                    onScreenBadge = `
                        <div style="margin-top: 0.6rem; padding: 0.5rem 0.65rem; background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 4px;">
                            <div style="font-size: 0.68rem; font-weight: 600; color: var(--primary); text-transform: uppercase; margin-bottom: 0.25rem; display: flex; align-items: center; gap: 0.35rem;">
                                <i class="fa-solid fa-font"></i> Visible On-Screen Text & Names
                            </div>
                            <p style="margin: 0; color: #f1f5f9; font-size: 0.8rem; line-height: 1.45; white-space: pre-wrap;">${escapeHtml(onScreenText)}</p>
                        </div>
                    `;
                }

                return `
                    <div class="scene-card" id="scene-card-${idx}" onclick="toggleSceneAccordion(${idx}, ${s.start_time})">
                        <div class="scene-header">
                            <button class="pill-time" title="Jump to ${formatSeconds(s.start_time)}" onclick="event.stopPropagation(); seekVideo(${s.start_time});">
                                <i class="fa-solid fa-camera" style="font-size: 0.55rem;"></i> ${formatSeconds(s.start_time)} - ${formatSeconds(s.end_time)}
                            </button>
                            <div class="scene-headline" title="${escapeHtml(headline)}">
                                <span style="color: var(--primary); font-weight: 600;">Scene ${idx + 1}:</span> ${escapeHtml(headline)}
                            </div>
                            <i class="fa-solid fa-chevron-down scene-chevron" id="scene-chevron-${idx}"></i>
                        </div>
                        <div class="scene-body" id="scene-body-${idx}">
                            <div class="scene-badge-label">
                                <i class="fa-solid fa-eye"></i> Visual Context & Setting
                            </div>
                            <p style="margin: 0; color: #cbd5e1; font-size: 0.81rem; line-height: 1.5;">${escapeHtml(details || headline)}</p>
                            ${onScreenBadge}
                        </div>
                    </div>
                `;
            }).join("");
        }
    }

    // 3. RENDER OVERVIEW (Separate Scroller)
    if (paneOverview) {
        paneOverview.innerHTML = `
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
    const items = document.querySelectorAll(".transcript-card");

    items.forEach(item => {
        const start = parseFloat(item.getAttribute("data-start"));
        const end = parseFloat(item.getAttribute("data-end"));

        if (currentTime >= start && currentTime <= end) {
            if (!item.classList.contains("active-speech")) {
                items.forEach(i => i.classList.remove("active-speech"));
                item.classList.add("active-speech");
            }
        }
    });
}

function seekVideo(seconds) {
    const player = document.getElementById("videoPlayer");
    if (!player) return;

    const targetTime = Math.max(0, parseFloat(seconds) || 0);

    const applySeek = () => {
        player.currentTime = targetTime;
        const playPromise = player.play();
        if (playPromise !== undefined) {
            playPromise.catch(err => {
                console.debug("Autoplay prevented or interrupted:", err);
            });
        }
    };

    if (player.readyState >= 1) { // HAVE_METADATA or higher
        applySeek();
    } else {
        const onLoaded = () => {
            applySeek();
            player.removeEventListener('loadedmetadata', onLoaded);
        };
        player.addEventListener('loadedmetadata', onLoaded);
        player.load();
    }
}

function toggleTranscriptAccordion(idx, seconds) {
    seekVideo(seconds);
    const card = document.getElementById(`transcript-card-${idx}`);
    if (card) {
        card.classList.toggle("expanded");
    }
}

function toggleSceneAccordion(idx, seconds) {
    seekVideo(seconds);
    const card = document.getElementById(`scene-card-${idx}`);
    if (card) {
        card.classList.toggle("expanded");
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

        const msgId = `asst-msg-${Date.now()}`;
        const firstLine = data.answer.split('\n')[0].replace(/^Answer:\s*/i, '').trim();
        const previewSnippet = firstLine.length > 75 ? firstLine.substring(0, 72) + "..." : firstLine;

        chatMessages.innerHTML += `
            <div class="message assistant" id="${msgId}">
                <div class="message-top-bar">
                    <div style="display: flex; align-items: center; gap: 0.4rem;">
                        <i class="fa-solid fa-robot" style="color: var(--primary);"></i>
                        <span style="font-weight: 600; color: #f1f5f9;">AI Assistant</span>
                    </div>
                    <button class="btn-toggle-answer" onclick="toggleMessageCollapse(this)" title="Hide or show answer">
                        <i class="fa-solid fa-chevron-up"></i> <span>Hide</span>
                    </button>
                </div>
                <div class="message-collapsed-preview" onclick="toggleMessageCollapse(this)" title="Click to view full answer">
                    <span>${escapeHtml(previewSnippet || "Answer hidden (click to expand)")}</span>
                    <i class="fa-solid fa-chevron-down" style="font-size: 0.65rem;"></i>
                </div>
                <div class="message-answer-body">
                    <div style="white-space: pre-wrap;">${escapeHtml(data.answer)}</div>
                </div>
                <div class="message-meta">
                    ${citationsHtml}
                    <span style="color: ${confColor}; font-weight: 600; font-size: 0.72rem; margin-left: auto;">
                        ${confPct}% Confidence
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
            <div class="message assistant" style="color: var(--accent-red);">
                <i class="fa-solid fa-triangle-exclamation"></i> Network error. Please retry.
            </div>
        `;
    }
}

function toggleMessageCollapse(elem) {
    const card = elem.closest(".message.assistant");
    if (!card) return;
    card.classList.toggle("collapsed");
    const btn = card.querySelector(".btn-toggle-answer");
    if (btn) {
        if (card.classList.contains("collapsed")) {
            btn.innerHTML = `<i class="fa-solid fa-chevron-down"></i> <span>Show</span>`;
        } else {
            btn.innerHTML = `<i class="fa-solid fa-chevron-up"></i> <span>Hide</span>`;
        }
    }
}

let allAnswersCollapsed = false;
function toggleAllAnswers() {
    const messages = document.querySelectorAll(".message.assistant");
    const toggleBtn = document.getElementById("btnToggleAllAnswers");
    
    allAnswersCollapsed = !allAnswersCollapsed;
    messages.forEach(card => {
        if (allAnswersCollapsed) {
            card.classList.add("collapsed");
            const btn = card.querySelector(".btn-toggle-answer");
            if (btn) btn.innerHTML = `<i class="fa-solid fa-chevron-down"></i> <span>Show</span>`;
        } else {
            card.classList.remove("collapsed");
            const btn = card.querySelector(".btn-toggle-answer");
            if (btn) btn.innerHTML = `<i class="fa-solid fa-chevron-up"></i> <span>Hide</span>`;
        }
    });

    if (toggleBtn) {
        if (allAnswersCollapsed) {
            toggleBtn.innerHTML = `<i class="fa-solid fa-expand"></i> <span>Show All</span>`;
        } else {
            toggleBtn.innerHTML = `<i class="fa-solid fa-compress"></i> <span>Hide All</span>`;
        }
    }
}

function clearChatMessages() {
    const chatMessages = document.getElementById("chatMessages");
    if (chatMessages) {
        chatMessages.innerHTML = `
            <div class="message assistant">
                Hello! Ask any question about the selected video: actions, spoken dialogue, people, visible items, or timestamps (e.g. <i>"What is being explained?"</i> or <i>"What happened around 0:10?"</i>).
            </div>
        `;
    }
    currentSessionId = null;
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
