# System Architecture & Technical Design

## 1. Overview & Core Philosophy

**AI Video Analyser & Chat** is an independently deployable Python microservice built for high-throughput, multi-user video ingestion, multimodal perception, and grounded conversational question answering. 

Engineering Posture:
- **Frontend**: HTML5 / Vanilla JavaScript Single Page Application (SPA) with no heavy framework dependencies.
- **Backend**: Async non-blocking FastAPI (Python 3.10+).
- **Storage**: ACID transactional storage in **PostgreSQL 16** with vector similarity indexing (`pgvector`).
- **Processing**: Async worker queue with FFmpeg audio demuxing, Faster-Whisper ASR, Gemini Flash Vision & OCR, and 768-dim normalized embedding vectors (`text-embedding-004`).
- **RAG Engine**: Grounded retrieval with timestamp citations ($MM:SS$) and anti-hallucination guardrails.

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
        QuizUI["AI Quiz Generator & PDF Export"]
    end

    subgraph GatewayLayer["🚪 API Gateway & Control Layer (FastAPI Python)"]
        Router["FastAPI Router (/api/v1)"]
        VideoAPI["Video Management API"]
        ChatAPI["Grounded RAG Chat API"]
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

    subgraph CoreEngineLayer["🧠 Hybrid Retrieval & RAG Engine"]
        Parser["Temporal Query Parser (HH:MM:SS)"]
        pgVectorEngine["pgvector Cosine Search"]
        GroundingGuard["Gemini Strict Anti-Hallucination Prompt"]
        ConfidenceEval["Confidence Evaluator (< 0.70 Warning)"]
    end

    subgraph StorageLayer["🗄️ Database Layer (PostgreSQL 16 + pgvector)"]
        DB[(PostgreSQL 16 Database)]
        tbl_videos["videos (Metadata, Status, Summary)"]
        tbl_segments["video_segments (768-dim Vectors & Transcripts)"]
        tbl_chat["chat_sessions & chat_messages"]
        tbl_quiz["quizzes & quiz_questions"]
    end

    %% Client to Gateway Connections
    UI --> Router
    IngestUI --> VideoAPI
    PlayerUI --> VideoAPI
    ChatUI --> ChatAPI
    QuizUI --> QuizAPI

    %% Gateway Routing
    Router --> VideoAPI
    Router --> ChatAPI
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
    ConfidenceEval -->|Response + Citations| ChatAPI

    %% Database Entities
    DB --- tbl_videos
    DB --- tbl_segments
    DB --- tbl_chat
    DB --- tbl_quiz

    style ClientLayer fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#fff
    style GatewayLayer fill:#0f172a,stroke:#10b981,stroke-width:2px,color:#fff
    style AsyncWorkerLayer fill:#1e1b4b,stroke:#8b5cf6,stroke-width:2px,color:#fff
    style CoreEngineLayer fill:#312e81,stroke:#ec4899,stroke-width:2px,color:#fff
    style StorageLayer fill:#064e3b,stroke:#14b8a6,stroke-width:2px,color:#fff
```

### 2.2 Multimodal Ingestion & Indexing Pipeline (Sequence Diagram)

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Client
    participant API as FastAPI Gateway (/videos/upload)
    participant Queue as Async Task Queue (Semaphore)
    participant Media as FFmpeg / yt-dlp
    participant ASR as Faster-Whisper ASR
    participant Vision as Gemini Flash Vision & OCR
    participant Fusion as Multimodal Fusion Indexer
    participant DB as PostgreSQL 16 + pgvector

    User->>API: POST /api/v1/videos/upload (File or YouTube URL)
    API-->>User: HTTP 202 Accepted (Job ID, Status: PENDING)
    
    API->>Queue: Dispatch Processing Job
    Queue->>Media: Extract 16kHz Audio Track & Keyframe Images (3.0s)
    Media-->>Queue: Audio File & Keyframe Frames
    
    par Audio Processing
        Queue->>ASR: Transcribe Audio Track
        ASR-->>Queue: Word-level Timed Transcript Segments
    and Visual Processing
        Queue->>Vision: Describe Frames & Extract OCR Text
        Vision-->>Queue: Visual Descriptions & On-screen Text
    end

    Queue->>Fusion: Temporal Fusion (Audio Transcript + Visual OCR)
    Fusion->>Fusion: Compute 768-dim Embeddings (text-embedding-004)
    Fusion->>DB: Save Video Metadata & 768-dim Segment Vectors
    DB-->>Queue: Transaction Committed
    Queue-->>API: Status: COMPLETED
```

### 2.3 Grounded RAG Chat Engine (Sequence Diagram)

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Client
    participant API as Chat Endpoint (/videos/:id/chat)
    participant Parser as Temporal Query Parser
    participant DB as PostgreSQL 16 (pgvector)
    participant LLM as Gemini Pro (Grounded Prompt)
    participant Evaluator as Grounding & Confidence Evaluator

    User->>API: POST Question ("What happens at 02:15?")
    API->>Parser: Parse Timestamps & Query Keywords
    Parser-->>API: Target Time Window (135s +- 30s)
    
    API->>DB: Hybrid Vector Cosine Search (768-dim distance)
    DB-->>API: Top-K Context Segments + Similarity Scores

    API->>LLM: Generate Grounded Answer (Strict Context Rules)
    LLM-->>API: Answer Text + Cited Timestamps
    
    API->>Evaluator: Compute Confidence Score

    alt Similarity Score >= 0.70 (High Confidence)
        Evaluator-->>API: Answer Verified & Grounded
        API-->>User: HTTP 200 (Answer, Citations, Score: High)
    else Similarity Score < 0.70 (Low Confidence / Unobserved)
        Evaluator-->>API: Return "Not Observed" Warning Badge
        API-->>User: HTTP 200 (Answer + Warning Badge)
    end
```

### 2.4 Enterprise Database ER Schema (PostgreSQL 16 + pgvector)

```mermaid
erDiagram
    videos ||--o{ video_segments : "contains"
    videos ||--o{ chat_sessions : "has"
    videos ||--o{ quizzes : "generates"
    chat_sessions ||--o{ chat_messages : "contains"
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

### 3.1 PostgreSQL + Unified Vector Index vs. Dual Database (SQLite + ChromaDB)
- Standardized on **PostgreSQL 16**. A single database handles relational metadata, job states, session history, and 768-dimensional normalized embeddings via `pgvector` with cosine distance matching.

### 3.2 Intelligent Temporal Sampling (3.0s Interval)
- Implemented deterministic **temporal sampling** (1 frame every 3.0s). Constant-time complexity $O(T)$, predictable memory footprint, and uniform coverage across arbitrary videos.

### 3.3 Grounding & Anti-Hallucination Strategy
- Low-confidence responses ($< 0.70$) display a visual warning badge in the chat UI and trigger fallback messages to prevent hallucinations.
