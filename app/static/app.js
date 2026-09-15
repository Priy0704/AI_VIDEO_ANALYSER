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
                <div class="video-name">${v.filename}</div>
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
        document.getElementById("summaryText").innerHTML = `
            <strong>Overview:</strong> ${details.summary || "Summary processing..."}<br>
            <span style="color: var(--primary); font-size: 0.75rem;">${details.segments_count} time-indexed multimodal segments</span>
        `;

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
