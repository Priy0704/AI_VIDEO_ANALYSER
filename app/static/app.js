let currentVideoId = null;
let currentSessionId = null;
let pollTimer = null;

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
    loadVideoList();
    loadHITLReviews();

    const fileInput = document.getElementById("fileInput");
    fileInput.addEventListener("change", handleFileSelect);

    const dropzone = document.getElementById("dropzone");
    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.style.borderColor = "#38bdf8";
    });
    dropzone.addEventListener("dragleave", () => {
        dropzone.style.borderColor = "#334155";
    });
    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.style.borderColor = "#334155";
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            uploadVideoFile(e.dataTransfer.files[0]);
        }
    });
});

function handleFileSelect(e) {
    if (e.target.files && e.target.files[0]) {
        uploadVideoFile(e.target.files[0]);
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
            stageLabel.innerText = data.current_stage || data.status;
            percentLabel.innerText = `${data.progress_pct}%`;
            progressBar.style.width = `${data.progress_pct}%`;

            if (data.status === "completed") {
                clearInterval(pollTimer);
                setTimeout(() => { progressBox.style.display = "none"; }, 1500);
                loadVideoList();
                selectVideo(videoId);
            } else if (data.status === "failed") {
                clearInterval(pollTimer);
                stageLabel.innerText = `Failed: ${data.error_message || "Processing error"}`;
                progressBar.style.backgroundColor = "#ef4444";
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
            listContainer.innerHTML = '<p style="font-size: 0.8rem; color: var(--text-muted);">No videos processed yet.</p>';
            return;
        }

        listContainer.innerHTML = videos.map(v => `
            <div class="video-item ${v.video_id === currentVideoId ? 'active' : ''}" onclick="selectVideo('${v.video_id}')">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem;">
                    <div class="video-name" style="flex: 1; word-break: break-all;">${v.filename}</div>
                    <button class="btn-delete-video" title="Delete video" onclick="deleteVideo(event, '${v.video_id}')">✕</button>
                </div>
                <div class="video-meta">
                    <span>${v.duration_seconds ? v.duration_seconds.toFixed(1) + 's' : 'N/A'}</span>
                    <span style="color: ${v.status === 'completed' ? '#22c55e' : v.status === 'failed' ? '#ef4444' : '#38bdf8'}">${v.status}</span>
                </div>
            </div>
        `).join("");

        // If no video is selected yet, select the first completed one
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
                document.getElementById("videoPlayer").src = "";
                document.getElementById("playerTitle").innerText = "Select a video";
                const panel = document.getElementById("summaryPanel");
                if (panel) {
                    panel.innerHTML = `
                        <p style="font-weight: 600; margin-bottom: 0.3rem;">Video Summary & Transcript</p>
                        <p id="summaryText" style="color: var(--text-muted);">Select or upload a video to inspect audio transcripts, visual perception, and timestamped segments.</p>
                    `;
                }
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
    currentSessionId = null; // Reset chat session for new video
    loadVideoList();

    const player = document.getElementById("videoPlayer");
    player.src = `/api/v1/videos/${videoId}/stream`;

    try {
        const res = await fetch(`/api/v1/videos/${videoId}`);
        if (!res.ok) return;
        const details = await res.json();

        document.getElementById("playerTitle").innerText = details.filename;
        const summaryPanel = document.getElementById("summaryPanel");

        const segments = details.segments || [];
        const transcriptSegments = segments.filter(
            s => s.transcript_text && s.transcript_text.trim().length > 0
        );

        if (transcriptSegments.length > 0) {
            // Group consecutive segments with identical transcript text for clean readability
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

            const transcriptHtml = grouped.map(g => `
                <div class="transcript-row">
                    <button class="transcript-time" onclick="seekVideo(${g.start_time})" title="Jump video to ${formatSeconds(g.start_time)}">
                        <i class="fa-solid fa-play" style="font-size: 0.55rem;"></i> ${formatSeconds(g.start_time)} - ${formatSeconds(g.end_time)}
                    </button>
                    <span class="transcript-text">${escapeHtml(g.text)}</span>
                </div>
            `).join("");

            summaryPanel.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.35rem;">
                    <div style="font-weight: 600; color: #38bdf8; display: flex; align-items: center; gap: 0.4rem;">
                        <i class="fa-solid fa-microphone-lines"></i>
                        <span>Video Transcript (Audio to Text)</span>
                    </div>
                    <span class="badge badge-completed" style="font-size: 0.7rem;">
                        <i class="fa-solid fa-check"></i> Audio Available
                    </span>
                </div>
                <div class="transcript-list">
                    ${transcriptHtml}
                </div>
                <details style="margin-top: 0.6rem; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 0.45rem; font-size: 0.8rem;">
                    <summary style="cursor: pointer; font-weight: 500; color: #94a3b8;">
                        <i class="fa-solid fa-video"></i> About Video (Visual Overview)
                    </summary>
                    <p style="margin-top: 0.35rem; line-height: 1.4; color: #cbd5e1;">${escapeHtml(details.summary || "Visual scene description available.")}</p>
                    <span style="color: var(--primary); font-size: 0.72rem; margin-top: 0.2rem; display: block;">${details.segments_count} time-indexed multimodal segments</span>
                </details>
            `;
        } else {
            // No audio speech transcript available (silent video / image progression)
            // Describe images with timestamps in story / event progression
            const visualSegments = segments.filter(
                s => s.visual_description && s.visual_description.trim().length > 0
            );

            let visualEventsHtml = "";
            if (visualSegments.length > 0) {
                visualEventsHtml = visualSegments.map((s, idx) => {
                    const desc = s.visual_description.replace(/^At\s+\d+(\.\d+)?s\s+in\s+video:\s*/i, "");
                    return `
                        <div class="transcript-row">
                            <button class="transcript-time" onclick="seekVideo(${s.start_time})" title="Jump to ${formatSeconds(s.start_time)}">
                                <i class="fa-solid fa-film" style="font-size: 0.55rem;"></i> ${formatSeconds(s.start_time)} - ${formatSeconds(s.end_time)}
                            </button>
                            <span class="transcript-text"><strong>Scene ${idx + 1}:</strong> ${escapeHtml(desc)}</span>
                        </div>
                    `;
                }).join("");
            } else {
                visualEventsHtml = `<p style="font-size: 0.8rem; color: var(--text-muted);">Visual keyframes analyzed.</p>`;
            }

            summaryPanel.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.35rem;">
                    <div style="font-weight: 600; color: #38bdf8; display: flex; align-items: center; gap: 0.4rem;">
                        <i class="fa-solid fa-film"></i>
                        <span>Visual Story & Events (Image Progression)</span>
                    </div>
                    <span class="badge badge-queued" style="font-size: 0.7rem;">
                        <i class="fa-solid fa-video-slash"></i> Silent Video (No Audio)
                    </span>
                </div>
                <div class="transcript-list">
                    ${visualEventsHtml}
                </div>
                <div style="margin-top: 0.5rem; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 0.4rem; font-size: 0.8rem; color: var(--text-muted);">
                    <strong style="color: var(--text-main);">Story Overview:</strong> ${escapeHtml(details.summary || "Visual event progression.")}
                </div>
            `;
        }

        // Clear chat
        const chatMessages = document.getElementById("chatMessages");
        chatMessages.innerHTML = `
            <div class="message assistant">
                Loaded <strong>${details.filename}</strong>. Ask anything about actions, objects, visible text, or specific timestamps!
            </div>
        `;
    } catch (e) {
        console.error("Error fetching video details:", e);
    }
}

function seekVideo(seconds) {
    const player = document.getElementById("videoPlayer");
    player.currentTime = seconds;
    player.play();
}

function handleKeyPress(e) {
    if (e.key === "Enter") {
        sendChatMessage();
    }
}

async function sendChatMessage() {
    if (!currentVideoId) {
        alert("Please select or upload a completed video first.");
        return;
    }

    const input = document.getElementById("queryInput");
    const query = input.value.trim();
    if (!query) return;

    input.value = "";
    const chatContainer = document.getElementById("chatMessages");

    // Append user message
    chatContainer.innerHTML += `
        <div class="message user">${escapeHtml(query)}</div>
    `;
    chatContainer.scrollTop = chatContainer.scrollHeight;

    // Show loading state
    const loadingId = "loading_" + Date.now();
    chatContainer.innerHTML += `
        <div class="message assistant" id="${loadingId}">
            <i class="fa-solid fa-spinner fa-spin"></i> Retrieving grounded video evidence...
        </div>
    `;
    chatContainer.scrollTop = chatContainer.scrollHeight;

    try {
        const res = await fetch(`/api/v1/videos/${currentVideoId}/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: query, session_id: currentSessionId })
        });

        const loadingElem = document.getElementById(loadingId);
        if (loadingElem) loadingElem.remove();

        if (!res.ok) {
            const err = await res.json();
            chatContainer.innerHTML += `
                <div class="message assistant" style="color: #ef4444;">
                    Error: ${err.detail || "Failed to process chat query."}
                </div>
            `;
            return;
        }

        const data = await res.json();
        currentSessionId = data.session_id;

        // Render citations
        let citationsHtml = "";
        if (data.citations && data.citations.length > 0) {
            citationsHtml = `
                <div class="citation-list">
                    ${data.citations.map(c => `
                        <span class="citation-chip" onclick="seekVideo(${c.start_time})">
                            <i class="fa-solid fa-clock"></i> ${c.timestamp_formatted}
                        </span>
                    `).join("")}
                </div>
            `;
        }

        // Confidence pill
        let confClass = "confidence-high";
        let confLabel = `Confidence: ${(data.confidence_score * 100).toFixed(0)}%`;
        if (data.confidence_score < 0.5) {
            confClass = "confidence-low";
            confLabel += " (Low / Uncertain)";
        } else if (data.confidence_score < 0.7) {
            confClass = "confidence-med";
            confLabel += " (Moderate)";
        }

        if (data.requires_hitl) {
            confLabel += " • Flagged for Human Review";
        }

        chatContainer.innerHTML += `
            <div class="message assistant">
                <div>${escapeHtml(data.answer)}</div>
                ${citationsHtml}
                <div class="confidence-tag ${confClass}">${confLabel}</div>
            </div>
        `;
        chatContainer.scrollTop = chatContainer.scrollHeight;

        if (data.requires_hitl) {
            loadHITLReviews();
        }

    } catch (e) {
        const loadingElem = document.getElementById(loadingId);
        if (loadingElem) loadingElem.remove();
        alert(`Error sending query: ${e.message}`);
    }
}

async function loadHITLReviews() {
    const container = document.getElementById("hitlContainer");
    try {
        const res = await fetch("/api/v1/hitl/reviews?status_filter=pending");
        if (!res.ok) return;
        const reviews = await res.json();

        if (reviews.length === 0) {
            container.innerHTML = '<p style="font-size: 0.75rem; color: var(--text-muted);">No pending reviews.</p>';
            return;
        }

        container.innerHTML = reviews.map(r => `
            <div class="hitl-item" id="hitl_${r.id}">
                <div style="font-weight: 600; color: #f8fafc;">Q: "${escapeHtml(r.query)}"</div>
                <div style="font-size: 0.7rem; color: var(--text-muted); margin: 0.2rem 0;">AI: ${escapeHtml(r.ai_answer.substring(0, 80))}...</div>
                <div style="display: flex; gap: 0.4rem; margin-top: 0.3rem;">
                    <button class="btn" style="padding: 0.2rem 0.5rem; font-size: 0.7rem;" onclick="submitHITL('${r.id}', 'approved')">
                        <i class="fa-solid fa-check"></i> Approve
                    </button>
                    <button class="btn btn-outline" style="padding: 0.2rem 0.5rem; font-size: 0.7rem;" onclick="promptHITLCorrection('${r.id}')">
                        <i class="fa-solid fa-pen"></i> Correct
                    </button>
                </div>
            </div>
        `).join("");
    } catch (e) {
        console.error("Error loading HITL reviews:", e);
    }
}

async function submitHITL(reviewId, status, notes = "", correction = "") {
    try {
        const res = await fetch(`/api/v1/hitl/reviews/${reviewId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                status: status,
                reviewer_notes: notes,
                corrected_answer: correction
            })
        });
        if (res.ok) {
            loadHITLReviews();
        }
    } catch (e) {
        alert("Failed to submit review decision.");
    }
}

function promptHITLCorrection(reviewId) {
    const correction = prompt("Enter corrected ground truth answer for this video moment:");
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
