# API Reference: AI Video Analyser & Chat Microservice

Base URL: `http://localhost:8090/api/v1`

---

## 1. Video Ingestion

### `POST /videos/upload`
Uploads an arbitrary video file for asynchronous processing.

**Request:**
- Content-Type: `multipart/form-data`
- Body: `file` (binary video file: `.mp4`, `.mov`, `.mkv`, `.avi` up to 500MB)

**Response (`202 Accepted`):**
```json
{
  "video_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "filename": "classroom_lecture.mp4",
  "status": "queued",
  "message": "Video accepted and queued for multimodal processing."
}
```

**cURL Example:**
```bash
curl -X POST "http://localhost:8090/api/v1/videos/upload" \
  -F "file=@/path/to/lecture.mp4"
```

---

### `GET /videos/{video_id}/status`
Polls processing progress and active pipeline stage.

**Response (`200 OK`):**
```json
{
  "video_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "filename": "classroom_lecture.mp4",
  "status": "processing",
  "progress_pct": 70,
  "current_stage": "Analyzing Visual Perception",
  "error_message": null,
  "duration_seconds": 180.5,
  "created_at": "2026-09-15T12:00:00Z",
  "updated_at": "2026-09-15T12:00:15Z"
}
```

---

### `GET /videos`
Lists all processed and in-progress videos.

**Response (`200 OK`):**
```json
[
  {
    "video_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "filename": "classroom_lecture.mp4",
    "status": "completed",
    "progress_pct": 100,
    "current_stage": "Completed",
    "duration_seconds": 180.5,
    "created_at": "2026-09-15T12:00:00Z",
    "updated_at": "2026-09-15T12:00:25Z"
  }
]
```

---

### `GET /videos/{video_id}`
Returns video summary and all indexed multimodal time segments.

**Response (`200 OK`):**
```json
{
  "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "filename": "classroom_lecture.mp4",
  "duration_seconds": 180.5,
  "status": "completed",
  "progress_pct": 100,
  "summary": "The instructor explains machine learning fundamentals with diagram illustrations.",
  "created_at": "2026-09-15T12:00:00Z",
  "segments_count": 18,
  "segments": [
    {
      "id": "seg-1",
      "start_time": 0.0,
      "end_time": 10.0,
      "transcript_text": "Good morning everyone. Today we discuss deep learning.",
      "visual_description": "Speaker stands beside whiteboard pointing at neural network diagram.",
      "combined_text": "Audio/Dialogue: Good morning everyone... Visual Scene: Speaker stands beside..."
    }
  ]
}
```

---

### `GET /videos/{video_id}/stream`
Streams video content with HTTP 206 partial content support for synced browser seeking.

---

## 2. Conversational Chat & Grounding

### `POST /videos/{video_id}/chat`
Submits a free-form question about the video and returns a grounded answer with timestamp citations.

**Request:**
- Content-Type: `application/json`
```json
{
  "query": "what did the speaker explain around minute 1?",
  "session_id": "optional-uuid"
}
```

**Response (`200 OK`):**
```json
{
  "session_id": "4e1a6c11-9e77-4b82-8c90-992255d11234",
  "video_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "query": "what did the speaker explain around minute 1?",
  "answer": "Around [01:00 - 01:20], the speaker introduces backpropagation and demonstrates gradient descent on the blackboard.",
  "citations": [
    {
      "start_time": 60.0,
      "end_time": 80.0,
      "timestamp_formatted": "01:00 - 01:20",
      "snippet": "Audio/Dialogue: Backpropagation computes partial derivatives... Visual: Speaker draws arrows.",
      "relevance_score": 0.92
    }
  ],
  "confidence_score": 0.92,
  "requires_hitl": false,
  "hitl_review_id": null
}
```

---

### `GET /videos/{video_id}/chat/{session_id}/history`
Fetches multi-turn conversation history.

---

## 3. Human-in-the-Loop (HITL) Review

### `GET /hitl/reviews`
Fetches queries flagged for human review due to low confidence (< 0.70).

**Query Parameters:**
- `status_filter`: `pending` | `approved` | `corrected` | `rejected`
- `video_id`: Optional UUID filter

**Response (`200 OK`):**
```json
[
  {
    "id": "hitl-99",
    "video_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "query": "was there an argument between two students?",
    "ai_answer": "No visual or audio evidence of conflict observed.",
    "confidence_score": 0.48,
    "status": "pending",
    "reviewer_notes": null,
    "corrected_answer": null,
    "created_at": "2026-09-15T12:05:00Z",
    "reviewed_at": null
  }
]
```

---

### `POST /hitl/reviews/{review_id}`
Submits a human review decision.

**Request:**
```json
{
  "status": "approved",
  "reviewer_notes": "Verified by human auditor that scene was quiet."
}
```

---

## 4. Health & Observability

### `GET /health`
Liveness probe.
```json
{ "status": "healthy", "service": "AI Video Analyser & Chat" }
```

### `GET /ready`
Readiness probe testing PostgreSQL connection.
```json
{ "status": "ready", "database": "connected" }
```
