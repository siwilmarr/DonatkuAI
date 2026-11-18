# 01 — Arsitektur Sistem

## 🗂️ Struktur Proyek

```
donatkuAI/
├── Dockerfile                  # Build image Python 3.11-slim untuk service API
├── Modelfile                   # Custom model Ollama (persona + system prompt)
├── docker-compose.yml          # Orkestrasi 2 service: ollama & api
├── requirements.txt            # Dependensi Python
├── ollama_collection.json      # Koleksi Postman untuk test Ollama API
├── knowledge-base/             # Folder dokumentasi ini
└── app/
    ├── main.py                 # FastAPI entry point
    └── system_prompt.py        # Definisi SYSTEM_PROMPT
```

---

## 🏗️ Diagram Arsitektur

```
[Client / Postman / Browser]
          │
          │  HTTP POST /chat  (port 8000)
          ▼
  ┌────────────────────┐
  │    FastAPI API     │  ← service: api  (Dockerfile)
  │    app/main.py     │
  └────────┬───────────┘
           │
           │  HTTP POST /api/chat  (port 11434, internal Docker network)
           ▼
  ┌────────────────────┐
  │      Ollama        │  ← service: ollama  (ollama/ollama:latest)
  │   llama3.2:3b      │
  └────────┬───────────┘
           │
           ▼
  [Volume: ollama_data]   ← model tersimpan persisten
```

---

## 🔄 Alur Request (Step-by-step)

```
1. Client  ──POST /chat {"message":"..."}──▶  FastAPI
2. FastAPI ── inject SYSTEM_PROMPT + message ──▶ payload
3. FastAPI ──POST /api/chat (timeout 120s)──▶  Ollama
4. Ollama  ── proses dengan llama3.2:3b ──▶  JSON response
5. FastAPI ── ekstrak message.content ──▶  {"reply":"..."}
6. FastAPI ──▶ Client
```

---

## 🧩 Komponen Utama

| Komponen | File | Peran |
|---|---|---|
| FastAPI App | `app/main.py` | Terima request, format payload, panggil Ollama |
| System Prompt | `app/system_prompt.py` | Definisi persona & batasan AI |
| Ollama Service | Docker image | Menjalankan model LLM secara lokal |
| Custom Modelfile | `Modelfile` | Alternatif persona langsung di level model |
| Docker Compose | `docker-compose.yml` | Orkestrasi semua service |
