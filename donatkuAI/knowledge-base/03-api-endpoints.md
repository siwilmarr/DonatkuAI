# 03 — API Endpoints

Base URL: `http://localhost:8000`

---

## `GET /donatku`

Health check — cek apakah API berjalan normal.

**Request:**
```http
GET http://localhost:8000/donatku
```

**Response (200 OK):**
```json
{ "status": "ok" }
```

---

## `POST /chat`

Endpoint utama untuk berkomunikasi dengan AI chatbot donatkuAI.

**Request:**
```http
POST http://localhost:8000/chat
Content-Type: application/json

{
  "message": "Donat apa yang paling enak?"
}
```

**Schema Request Body:**
| Field | Tipe | Wajib | Keterangan |
|---|---|---|---|
| `message` | `string` | ✅ | Pesan dari user ke AI |

**Response sukses (200 OK):**
```json
{
  "reply": "Woi, nanya soal donat?! Coba yang glazed, empuk banget sumpah..."
}
```

**Response error (502 Bad Gateway):**
```json
{
  "detail": "Gagal menghubungi Ollama: ..."
}
```
> Terjadi ketika service Ollama tidak bisa dijangkau.

---

## ⚙️ Detail Implementasi `/chat`

```python
@app.post("/chat")
async def chat(req: ChatRequest):
    payload = {
        "model": OLLAMA_MODEL,           # dari env var
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},  # inject persona
            {"role": "user",   "content": req.message},
        ],
        "stream": False,                 # response sekaligus, bukan streaming
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
        r.raise_for_status()

    return {"reply": r.json()["message"]["content"]}
```

**Poin penting:**
- `stream: False` → response diterima sekaligus (bukan SSE/streaming)
- Timeout: **120 detik** (LLM bisa lambat saat inference)
- Error handling: `httpx.HTTPError` → raise `HTTPException(502)`

---

## 🧪 Contoh Test dengan cURL

```bash
# Health check
curl http://localhost:8000/donatku

# Chat
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Rekomendasi kue yang enak dong"}'

# Chat — pertanyaan di luar topik (AI akan alihkan ke kuliner)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Siapa presiden Indonesia?"}'
```

---

## 🧪 Postman Collection

Import [`ollama_collection.json`](../ollama_collection.json) ke Postman untuk test **Ollama API secara langsung** (bypass FastAPI):

| # | Nama | Method | Endpoint |
|---|---|---|---|
| 1 | Cek Status Ollama | `GET` | `{{base_url}}` |
| 2 | Lihat Daftar Model | `GET` | `{{base_url}}/api/tags` |
| 3 | Chat dengan AI | `POST` | `{{base_url}}/api/chat` |
| 4 | Generate Teks | `POST` | `{{base_url}}/api/generate` |
| 5 | Chat Multi-Turn | `POST` | `{{base_url}}/api/chat` |
| 6 | Info Detail Model | `POST` | `{{base_url}}/api/show` |

**Variables:** `base_url = http://localhost:11434` · `model = llama3.2:3b`

---

## 📋 FastAPI Auto Docs

Setelah service berjalan, dokumentasi interaktif tersedia di:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
