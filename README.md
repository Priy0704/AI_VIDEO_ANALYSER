# AI Video Analyser & Chat Microservice

> **Upload a video. Ask it anything.**  
> An independently deployable microservice that ingests arbitrary video files, extracts and fuses audio transcripts with visual frame perception into a unified time-indexed representation in **PostgreSQL + pgvector**, and exposes grounded conversational Q&A with approximate timestamp citations and confidence-driven Human-in-the-Loop (HITL) review.

---

## 🌟 Core Highlights

- **Asynchronous Ingestion**: Accepts arbitrary videos (`.mp4`, `.mov`, `.mkv`, `.avi` up to 500MB / ~30 minutes). Returns `202 Accepted` immediately with a pollable task ID.
- **Controlled Concurrency**: Internal worker queue with semaphore throttling to process multiple video uploads (e.g. 10 videos) without memory or CPU starvation.
- **Audio Understanding (ASR)**: 16kHz mono audio demuxing and speech transcription with exact start/end timestamps using Whisper / Gemini multimodal ASR.
- **Visual Perception**: Simple intelligent temporal sampling (1 frame every 3s) capturing environment, actors, actions, and on-screen text.
- **Unified Temporal Fusion**: Correlates audio dialogue and visual scenes along continuous temporal windows and stores 768-dimensional vector embeddings in PostgreSQL.
- **Grounded Multi-Turn Chat**: Free-form Q&A with structured timestamp citations `[MM:SS - MM:SS]`.
- **Anti-Hallucination & Confidence-Driven HITL**: Computes confidence scores (0.0 to 1.0). Queries with low confidence (< 0.70) are flagged for human auditor review, and unobserved events explicitly trigger "Not observed in video footage" notices.
- **Functional Web UI**: Integrated single-page dashboard with real-time progress tracking, synchronized HTML5 video player (clicking citations jumps directly to that second), and HITL review queue.

---

## 🚀 Quick Start (Docker Compose)

The fastest way to deploy the microservice and PostgreSQL:

```bash
# 1. Clone repository
git clone https://github.com/Priy0704/AI_VIDEO_ANALYSER.git
cd AI_VIDEO_ANALYSER

# 2. Copy environment template
cp .env.example .env

# 3. (Optional) Set your Gemini API key in .env
# GEMINI_API_KEY=your_key_here

# 4. Spin up PostgreSQL and API
docker compose up -d
```

- **Functional Web UI**: [http://localhost:8090](http://localhost:8090)
- **Interactive OpenAPI Documentation**: [http://localhost:8090/docs](http://localhost:8090/docs)
- **Readiness Probe**: [http://localhost:8090/ready](http://localhost:8090/ready)

---

## 💻 Local Development Setup (Without Docker API)

If you wish to run the FastAPI app locally against the Docker PostgreSQL database:

```bash
# 1. Start PostgreSQL container
docker compose up -d postgres

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Start the microservice with Uvicorn
python -m uvicorn app.main:app --host 0.0.0.0 --port 8090 --reload
```

---

## 🧪 Running Automated Tests

A comprehensive suite of unit and integration tests is included:

```bash
# Run all tests with pytest
python -m pytest -v
```

**Test Coverage:**
- `test_health_and_ready`: Liveness and readiness database probes.
- `test_upload_invalid_extension`: Rejection of malformed / unsupported file types.
- `test_upload_valid_mp4_and_poll_status`: End-to-end ingestion, keyframe sampling, and status polling on a real synthetic video.
- `test_chat_grounded_citations_and_antihallucination`: Grounded conversation, session persistence, and timestamp citations.
- `test_confidence_driven_hitl_workflow`: Auto-flagging of low-confidence queries and human audit review lifecycle.

---

## 📡 Key API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/videos/upload` | Ingest video file (returns `202 Accepted` with `video_id`) |
| `GET` | `/api/v1/videos/{id}/status` | Poll ingestion progress & current processing stage |
| `GET` | `/api/v1/videos` | List all ingested videos |
| `GET` | `/api/v1/videos/{id}` | Get video metadata, duration, summary, and segments |
| `GET` | `/api/v1/videos/{id}/stream` | Stream video with HTTP 206 range request support |
| `POST` | `/api/v1/videos/{id}/chat` | Grounded multi-turn conversational Q&A with citations |
| `GET` | `/api/v1/videos/{id}/chat/{session}/history` | Retrieve full multi-turn conversation history |
| `GET` | `/api/v1/hitl/reviews` | List queries flagged for human review |
| `POST` | `/api/v1/hitl/reviews/{id}` | Submit human review decision (approve / correct / notes) |
| `GET` | `/health` & `/ready` | Microservice liveness and database readiness probes |

Full schema details and request/response payloads are available at `/docs`.

---

## 🏗️ Architecture & Design Decisions

See [ARCHITECTURE.md](ARCHITECTURE.md) for an in-depth breakdown of:
- Unified PostgreSQL schema design.
- Why deterministic temporal sampling was chosen over brittle HSV/SSIM differencing.
- How concurrency (10 concurrent videos and 10 concurrent chat users) is managed safely.
- Confidence scoring and anti-hallucination guardrails.

---

## ⚠️ Known Limitations & Production Enhancements

1. **Audio in Silent Videos**: If an uploaded video has no audio track, the audio demuxer logs a warning and the system gracefully relies 100% on visual perception.
2. **Streaming Ingestion**: Currently, the video file must finish uploading to disk before processing starts. For ultra-large files (> 2GB), chunked streaming or RTSP real-time pipes could be added.
3. **GPU Acceleration**: Keyframe extraction and vector calculations run on CPU; configuring NVIDIA CUDA drivers enables sub-second processing for hours of video.
