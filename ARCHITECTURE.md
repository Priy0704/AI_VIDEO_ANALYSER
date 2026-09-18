# System Architecture & Technical Design

## 1. Overview & Core Philosophy

**AI Video Analyser & Chat** is an independently deployable Python microservice built for high-throughput, multi-user video ingestion, multimodal perception, grounded conversational question answering, and **Human-in-the-Loop (HITL)** quality control.

Engineering Posture:
- **Frontend**: HTML5 / Vanilla JavaScript Single Page Application (SPA) featuring a 3-column workspace (Video Library, Synced Video Player & Quiz Generator, Multi-turn Chat & **HITL Review Queue**).
- **Backend**: Async non-blocking FastAPI (Python 3.10+).
- **Storage**: ACID transactional storage in **PostgreSQL 16** with vector similarity indexing (`pgvector`).
- **Processing**: Async worker queue with FFmpeg audio demuxing, Faster-Whisper ASR, Gemini Flash Vision & OCR, and 768-dim normalized embedding vectors (`text-embedding-004`).
- **RAG & HITL Engine**: Grounded retrieval with timestamp citations ($MM:SS$), anti-hallucination guardrails, and automated low-confidence ($< 0.70$) routing to the **HITL Review Queue**.

---

## 2. System Architecture Diagrams

### 2.1 System Component & Data Flow Architecture (C4 Model Level 2)

```mermaid
graph TB
    subgraph ClientLayer["🖥️ Client Layer (Vanilla JS Single Page Application)"]
        UI["HTML5 / Vanilla JS SPA<br/>(Port 8090)"]
        IngestUI["Video & YouTube Ingestion"]
        PlayerUI["Video Player & Timestamps"]
        ChatUI["Single & Global Video Chat"]
        HITLUI["HITL Review Queue Component"]
        QuizUI["AI Quiz Generator & PDF Export"]
    end

    subgraph GatewayLayer["🚪 API Gateway & Control Layer (FastAPI Python)"]
        Router["FastAPI Router (/api/v1)"]
        VideoAPI["Video Management API"]
        ChatAPI["Grounded RAG Chat API"]
        HITLAPI["HITL Review API (/api/v1/hitl)"]
        QuizAPI["Quiz & PDF Export API"]
        HealthAPI["Health & Readiness Probes"]
    end

    subgraph AsyncWorkerLayer["⚙️ Async Processing Layer (Semaphore Queue: Max=2 Workers)"]
        Queue["Async Task Queue (Semaphore)"]
        YTDL["YouTube Downloader (yt-dlp)"]
        AudioDemux["FFmpeg Audio Demuxer (16kHz WAV)"]
        ASR["Faster-Whisper ASR (Word Timestamps)"]
        Sampler["Temporal Frame Sampler (3.0s)"]
        VisionOCR["Gemini Flash Multimodal Vision & OCR"]
        Fusion["Multimodal Fusion & 768-dim Embedder"]
    end

    subgraph CoreEngineLayer["🧠 Hybrid Retrieval & Anti-Hallucination RAG Engine"]
        Parser["Temporal Query Parser (HH:MM:SS)"]
        pgVectorEngine["pgvector Cosine Search"]
        GroundingGuard["Gemini Strict Anti-Hallucination Prompt"]
        ConfidenceEval["Confidence Evaluator (< 0.70 Threshold)"]
    end

    subgraph StorageLayer["🗄️ Database Layer (PostgreSQL 16 + pgvector)"]
        DB[(PostgreSQL 16 Database)]
        tbl_videos["videos (Metadata, Status, Summary)"]
        tbl_segments["video_segments (768-dim Vectors & Transcripts)"]
        tbl_chat["chat_sessions & chat_messages"]
        tbl_hitl["hitl_reviews (Pending Review Queue)"]
        tbl_quiz["quizzes & quiz_questions"]
    end

    %% Client to Gateway Connections
    UI --> Router
    IngestUI --> VideoAPI
    PlayerUI --> VideoAPI
    ChatUI --> ChatAPI
    HITLUI --> HITLAPI
    QuizUI --> QuizAPI

    %% Gateway Routing
    Router --> VideoAPI
    Router --> ChatAPI
    Router --> HITLAPI
    Router --> QuizAPI
    Router --> HealthAPI

    %% Ingestion Workflow
    VideoAPI -->|202 Accepted| Queue
    Queue --> YTDL
    Queue --> AudioDemux
    AudioDemux --> ASR
    Queue --> Sampler
    Sampler --> VisionOCR
    ASR & VisionOCR --> Fusion
    Fusion -->|Save Segments & Embeddings| DB

    %% Chat & RAG Workflow
    ChatAPI --> Parser
    Parser --> pgVectorEngine
    pgVectorEngine -->|Retrieve Vector Context| DB
    pgVectorEngine --> GroundingGuard
    GroundingGuard --> ConfidenceEval
    ConfidenceEval -->|Score >= 0.70: Validated Answer| ChatAPI
    ConfidenceEval -->|Score < 0.70: Flag & Enqueue| tbl_hitl
    tbl_hitl --> HITLUI

    %% Database Entities
    DB --- tbl_videos
    DB --- tbl_segments
    DB --- tbl_chat
    DB --- tbl_hitl
    DB --- tbl_quiz

    style ClientLayer fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#fff
    style GatewayLayer fill:#0f172a,stroke:#10b981,stroke-width:2px,color:#fff
    style AsyncWorkerLayer fill:#1e1b4b,stroke:#8b5cf6,stroke-width:2px,color:#fff
    style CoreEngineLayer fill:#312e81,stroke:#ec4899,stroke-width:2px,color:#fff
    style StorageLayer fill:#064e3b,stroke:#14b8a6,stroke-width:2px,color:#fff
```

### 2.2 Grounded RAG & Confidence-Driven HITL Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User as Chat User / Human Reviewer
    participant API as Chat Endpoint (/videos/:id/chat)
    participant Parser as Temporal Query Parser
    participant DB as PostgreSQL 16 (pgvector)
    participant LLM as Gemini Pro (Grounded Prompt)
    participant Evaluator as Grounding & Confidence Evaluator
    participant HITLQueue as HITL Review Queue (/api/v1/hitl)

    User->>API: POST Question ("Was the person angry?")
    API->>Parser: Parse Keywords & Visual Context Intent
    Parser->>DB: Vector Cosine Search (pgvector 768-dim distance <->)
    DB-->>API: Candidate Segments + Similarity Scores

    API->>LLM: Generate Grounded Answer
    LLM-->>API: Generated Answer + Candidate Timestamps
    
    API->>Evaluator: Compute Grounding Confidence Score

    alt Similarity Score >= 0.70 (High Confidence)
        Evaluator-->>API: High Confidence Answer
        API-->>User: HTTP 200 (Answer, Citations, High Confidence)
    else Similarity Score < 0.70 (Ambiguous / Low Confidence)
        Evaluator->>HITLQueue: INSERT INTO hitl_reviews (Status: PENDING)
        Evaluator-->>API: Flag "Requires Human Review"
        API-->>User: HTTP 200 (Answer + Candidate Timestamps + Warning Badge)
        
        note over User, HITLQueue: Human Reviewer Inspection Step
        HITLQueue-->>User: Display Pending Item in HITL Queue Box
        User->>HITLQueue: Click Approve or Reject (/hitl/reviews/:id/resolve)
        HITLQueue->>DB: Update Chat Message to "100% (Human Verified)"
    end
```

### 2.3 Enterprise Database ER Schema (PostgreSQL 16 + pgvector)

```mermaid
erDiagram
    videos ||--o{ video_segments : "contains"
    videos ||--o{ chat_sessions : "has"
    videos ||--o{ quizzes : "generates"
    chat_sessions ||--o{ chat_messages : "contains"
    chat_messages ||--o{ hitl_reviews : "flags for review"
    quizzes ||--o{ quiz_questions : "includes"

    videos {
        uuid id PK
        string title
        string file_path
        string youtube_url
        float duration_seconds
        string status
        string overall_summary
        string category
        timestamp created_at
    }

    video_segments {
        uuid id PK
        uuid video_id FK
        float start_time
        float end_time
        text transcript_text
        text visual_description
        text ocr_text
        vector_768 embedding
    }

    chat_sessions {
        uuid id PK
        uuid video_id FK
        string session_name
        timestamp created_at
    }

    chat_messages {
        uuid id PK
        uuid session_id FK
        string sender
        text message_text
        jsonb citations
        float confidence_score
        timestamp created_at
    }

    hitl_reviews {
        uuid id PK
        uuid message_id FK
        uuid video_id FK
        text user_query
        text original_answer
        float confidence_score
        string status
        text reviewer_notes
        text corrected_answer
        timestamp created_at
    }

    quizzes {
        uuid id PK
        uuid video_id FK
        string title
        int total_questions
        timestamp created_at
    }

    quiz_questions {
        uuid id PK
        uuid quiz_id FK
        text question_text
        jsonb options
        string correct_answer
        text explanation
    }
```

---

## 3. Key Design Decisions & Trade-Offs

### 3.1 PostgreSQL + Unified Vector Index vs. Dual Database
- Standardized on **PostgreSQL 16**. A single database handles relational metadata, job states, session history, HITL reviews, and 768-dimensional normalized embeddings via `pgvector`.

### 3.2 Confidence-Driven HITL (Human-in-the-Loop) Architecture
- Queries scoring below `0.70` confidence or identified as ambiguous/subjective (e.g. emotion detection) display candidate timestamps so the user can verify the video footage, while simultaneously populating the **HITL Review Queue** at the bottom of the Chat interface.
- When a human clicks **Approve** or **Reject**, the system updates the review status and converts the chat confidence score to `100% (Human Verified)`.
