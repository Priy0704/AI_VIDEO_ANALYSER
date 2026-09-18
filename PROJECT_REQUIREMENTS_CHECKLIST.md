# AI Video Analyser & Chat — Project Requirement Analysis & Status Report

> **Document Type**: Comprehensive Requirements Verification, Tech Stack Breakdown, Delivery Audit & Gap Analysis  
> **Target Project**: AI Video Analyser & Chat Microservice  
> **Date**: September 18, 2026  

---

## 1. Executive Summary

This document provides an line-by-line verification of the **AI Video Analyser & Chat** project against the official requirement specification (*Assignment 01 · AI-Native Build Track*).

Our engineering effort has delivered a **production-grade, containerized microservice** that exceeds the core requirements. Beyond multi-video ingestion, ASR audio transcription, visual temporal sampling, vector search fusion, grounded multi-turn Q&A, and anti-hallucination guardrails, we have implemented **high-value extensions** including a Human-in-the-Loop (HITL) audit workflow, automatic video domain classification, grounded quiz generation, PDF exporting, and YouTube URL ingestion.

---

## 2. Tech Stack Used & Architecture Decisions

| Component / Layer | Technology / Library | Purpose & Engineering Rationale |
| :--- | :--- | :--- |
| **Web Framework & API Gate** | **Python 3.11** + **FastAPI** | High-performance asynchronous non-blocking I/O for API endpoints and background processing. |
| **ASGI Server** | **Uvicorn** | Production ASGI server supporting async concurrency and WebSocket compatibility. |
| **Database & Relational Model** | **PostgreSQL 16** + **SQLAlchemy 2.0 (Async)** | ACID transactional storage for videos, temporal segments, chat history, HITL logs, and quizzes. |
| **Vector Search Engine** | **`pgvector`** | 768-dimensional normalized vector cosine similarity search embedded directly inside PostgreSQL (avoiding dual DB sync issues). |
| **Multimodal AI Models** | **Google Gemini API** (`google-generativeai`) | Multimodal keyframe visual perception, ASR speech transcription, 768-dim embeddings (`text-embedding-004`), and grounded chat generation. |
| **Audio Processing** | **FFmpeg** (`imageio-ffmpeg`) | Demuxing 16kHz mono WAV audio streams from arbitrary video formats (`.mp4`, `.mov`, `.mkv`, `.avi`). |
| **Video Frame Analysis** | **OpenCV** (`opencv-python-headless`) + **NumPy** | Deterministic temporal sampling (1 frame per $N$ seconds) for predictable $O(T)$ runtime. |
| **URL / Stream Ingestion** | **`yt-dlp`** | Downloading and processing YouTube / web video URLs asynchronously without blocking HTTP requests. |
| **Document Exporting** | **ReportLab** | Dynamically generating formatted, printable PDF quizzes with answer keys for educational videos. |
| **Containerization** | **Docker** & **Docker Compose** | Multi-container setup (PostgreSQL + FastAPI microservice) deployable with `docker compose up`. |
| **Automated Test Suite** | **Pytest** + **Pytest-Asyncio** + **HTTPX** | Full coverage unit and integration test suite (19 test suites covering liveness, upload, chat, HITL, quizzes, URL ingestion). |
| **Frontend Web UI** | **Vanilla HTML5 / CSS3 / JavaScript (ES6)** | Embedded single-page interactive dashboard with synchronized video player, progress tracking, chat UI, HITL queue, and quiz generator. |

---

## 3. What They Wanted vs What We Are Giving

| Requirement Category | What They Wanted (PDF Spec) | What We Are Giving (Delivered Solution) | Alignment Status |
| :--- | :--- | :--- | :--- |
| **Video Ingestion** | Accept video via API (MP4/MOV, up to ~30 mins without falling over). | Accepts `.mp4`, `.mov`, `.mkv`, `.avi` up to 500MB (~30 mins). Fast `202 Accepted` response with pollable job ID. **Bonus**: Direct YouTube/Web URL downloading via `yt-dlp`. | **EXCEEDED** 🚀 |
| **Audio Understanding (ASR)** | Transcribe speech with timestamps using ASR model or API with correct timestamp alignment. | Demuxes audio to 16kHz mono, extracts full speech transcripts with exact start/end timestamp intervals using Whisper/Gemini ASR. | **FULLY MET** ✅ |
| **Visual Understanding** | Extract scenes, objects, on-screen text, actions using frame sampling + captioning/embedding. | Deterministic temporal sampling (1 frame every 3s) analyzed by Gemini Multimodal to perceive visual scene, actors, actions, and on-screen OCR text. | **FULLY MET** ✅ |
| **Unified Representation** | Fuse audio + visual into a single time-indexed index (embeddings + metadata per segment). | Time-aligned fusion layer combining audio transcripts and visual descriptions into segment windows stored with 768-dim `pgvector` embeddings in PostgreSQL. | **FULLY MET** ✅ |
| **Chat Interface & Grounding** | Multi-turn Q&A citing approximate timestamps `[MM:SS - MM:SS]`. Grounded answers to "what happened", "summarize", etc. | Grounded conversational Q&A endpoint supporting single and multi-turn sessions with formatted timestamp citations. Interactive UI jumps video player directly to cited timestamp. | **FULLY MET** ✅ |
| **Long-Video Handling** | Chunking / summarization strategy so system doesn't hallucinate or crash on long videos. | Controlled temporal segment chunking, windowed vector retrieval, top-K similarity filtering, and strict grounding system prompt. | **FULLY MET** ✅ |
| **Multi-Video Support** | Hold state for multiple videos/sessions concurrently in memory/database. | Fully supported in PostgreSQL database schema (`videos`, `video_segments`, `chat_sessions`). Includes cross-video multi-search Q&A. | **EXCEEDED** 🚀 |
| **Microservice & Deployment** | Containerized, independently deployable, versioned REST API, Docker deployment (`docker compose up`). | Clean `/api/v1` REST API microservice, fully containerized with `Dockerfile` and `docker-compose.yml` (PostgreSQL + API). | **FULLY MET** ✅ |
| **Production Posture** | Structured logging, health checks, config via environment, async workers, error handling. | `structlog`-style JSON structured logging, `/health` and `/ready` probes, `.env` config, async semaphore worker queue (`MAX_CONCURRENT_WORKERS=2`). | **FULLY MET** ✅ |
| **Automated Testing** | Unit tests for core logic, integration tests for API surface. | Comprehensive test suite (19 test modules) covering uploads, ASR/Visual fusion, chat grounding, HITL workflows, URL ingestion, and quizzes. | **FULLY MET** ✅ |
| **Deliverables & Docs** | Clean Git history, `README.md`, `ARCHITECTURE.md`, OpenAPI spec, screen recording demo. | Complete `README.md`, 1-page `ARCHITECTURE.md`, automatic OpenAPI docs at `/docs`. *(Screen recording demo is pending user recording)*. | **90% MET** (Demo video remaining) |

---

## 4. Completed Features ("Things We Have Done")

Here is the complete inventory of features implemented across the codebase:

### 1. Asynchronous Video Processing Pipeline (`app/services/task_queue.py`, `video_processor.py`)
- Immediate `202 Accepted` response on upload with unique `video_id`.
- Controlled worker queue using `asyncio.Semaphore` to manage system CPU/RAM load under concurrent uploads.
- Real-time job status polling endpoint (`/api/v1/videos/{id}/status`) tracking lifecycle states: `queued` $\rightarrow$ `processing` $\rightarrow$ `completed` / `failed`.

### 2. Audio & Visual Multimodal Perception (`app/services/audio_transcriber.py`, `vision_describer.py`)
- **Audio Stream Demuxing**: Automatic FFmpeg extraction to 16kHz WAV mono format. Graceful handling of silent videos (no audio track).
- **Speech Transcription**: Timestamped ASR transcript segment generation.
- **Visual Temporal Keyframe Sampling**: Uniform frame extraction (1 frame per 3s) analyzed with multimodal AI to extract scene context, participant clothing/actions, and on-screen text (OCR).

### 3. Unified Temporal Indexing with `pgvector` (`app/services/fusion_indexer.py`)
- Fuses audio speech and visual keyframe perceptions into normalized continuous time segments.
- Computes 768-dimensional vector embeddings for each segment stored directly in PostgreSQL with `pgvector` HNSW / Cosine indexing.

### 4. Grounded Multi-Turn Conversational Q&A (`app/services/chat_service.py`, `app/api/v1/chat.py`)
- Natural language Q&A supporting single video context or multi-video cross-search.
- Strict grounding instructions forcing responses to cite precise timestamp ranges `[MM:SS - MM:SS]`.
- Temporal query parser handling phrases like *"around minute 5"* or *"in the first half"*.

### 5. Anti-Hallucination Guardrails (`app/services/chat_service.py`)
- Explicit "Not Observed" detection: If query topics do not exist in the video footage, the system returns a clear declaration without hallucinating timestamps.
- Explicit `0.70` confidence thresholding.

### 6. Interactive Web Dashboard UI (`app/static/index.html`)
- Single-page responsive dark-mode dashboard.
- File drag-and-drop & YouTube URL ingestion forms.
- Synchronized HTML5 video player: clicking a timestamp citation in chat automatically seeks the video to that exact second.
- Interactive HITL audit queue and Quiz assessment tab.

---

## 5. Remaining / Pending Deliverables ("Which Are Remaining")

The codebase implementation is **100% complete**. The following items are non-code operational deliverables required before final assignment submission:

| Remaining Item | Category | Action Required | Responsibility |
| :--- | :--- | :--- | :--- |
| **3–5 Minute Screen Demo Video** | Requirement Deliverable | Record a 3–5 minute video walking through: 1) Video upload & status polling, 2) Grounded Q&A with timestamp citations, 3) Anti-hallucination handling, 4) Edge case (e.g. silent video or low-confidence query triggering HITL). | **USER ACTION** 📹 |
| **Git Commit History Verification** | Repository Requirement | Ensure git commit history reflects incremental progress (not a single squashed commit) before submitting repository link. | **VERIFIED / USER** 🐙 |
| **Public Hosting / Deployment (Optional)** | Deployment | If submitting a live link, deploy container via Docker Compose to AWS EC2, GCP Compute Engine, Railway, or Render. | **OPTIONAL** ☁️ |

---

## 6. Extra Value Added ("Any Value We Added or Not")

We have added **significant engineering value** far beyond the original project specification:

### 🌟 Value-Add 1: Confidence-Driven Human-in-the-Loop (HITL) Workflow
- **What was asked**: Standard AI responses.
- **What we added**: Queries with confidence scores below `0.70` or containing ambiguous intent are automatically flagged and queued in a dedicated HITL review portal (`/api/v1/hitl/reviews`). Human supervisors can inspect, approve, or correct answers, providing an enterprise governance loop.

### 🌟 Value-Add 2: Automatic Video Domain Classification
- **What was asked**: Generic video handling.
- **What we added**: An automated video domain classifier (`app/services/video_classifier.py`) that categorizes videos into **Knowledge / Educational** vs **Observational / Surveillance** upon ingestion. This tailors the Q&A prompting strategy dynamically.

### 🌟 Value-Add 3: Grounded Assessment Quiz & Self-Test Generation
- **What was asked**: Q&A Chat only.
- **What we added**: Automatic generation of grounded Multiple Choice (MCQ) and True/False quizzes for educational videos (`app/api/v1/quiz.py`). Students can attempt quizzes, receive immediate grading, view grounded answer rationale with timestamps, and take self-tests.

### 🌟 Value-Add 4: Dynamic PDF Quiz Exporting
- **What was asked**: Not specified.
- **What we added**: Integrated `ReportLab` PDF generation engine (`app/services/pdf_generator.py`) allowing users to download generated quizzes as styled, printable PDF documents complete with answer keys.

### 🌟 Value-Add 5: Direct YouTube / Web URL Ingestion
- **What was asked**: Local file uploads only.
- **What we added**: Integrated `yt-dlp` pipeline (`app/services/url_downloader.py`) allowing users to paste YouTube or web video links for direct background downloading and ingestion.

### 🌟 Value-Add 6: Embedded Interactive Web Dashboard
- **What was asked**: *"Minimal UI is fine... explicitly out of scope: a polished end-user video player UI"*.
- **What we added**: A full-featured single-page Web UI (`app/static/index.html`) with drag-and-drop uploads, real-time progress bars, synced video player timestamp seek, interactive chat, HITL management, and quiz tabs.

---

## 7. Summary & Final Checklist for Submission

- [x] Microservice architecture & FastAPI REST endpoints implemented.
- [x] Docker & Docker Compose setup verified (`docker-compose.yml`).
- [x] Unified vector search in PostgreSQL + `pgvector` complete.
- [x] Grounded Q&A with precise timestamp citations functional.
- [x] Anti-hallucination & low-confidence HITL review operational.
- [x] Unit & Integration tests passing.
- [x] `README.md` and `ARCHITECTURE.md` documented.
- [ ] **Pending User Action**: Record 3–5 minute screen recording demo.
- [ ] **Pending User Action**: Push repository to private Git and share access link.
