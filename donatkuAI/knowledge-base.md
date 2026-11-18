# 🍩 donatkuAI — Knowledge Base

> **Proyek:** Chatbot AI berbasis kuliner menggunakan FastAPI + Ollama (LLM lokal)
> **Stack:** Python 3.11, FastAPI, Uvicorn, Ollama (llama3.2:3b), Docker Compose
> **Bahasa AI:** Bahasa Indonesia informal/kasar, khusus topik kuliner
> **Dibuat:** 2026-10-27

---

## 📁 Struktur Proyek

```
donatkuAI/
├── Dockerfile                  # Build image Python 3.11-slim untuk service API
├── Modelfile                   # Custom model Ollama (persona + system prompt)
├── docker-compose.yml          # Orkestrasi 2 service: ollama & api
├── requirements.txt            # Dependensi Python
├── ollama_collection.json      # Koleksi Postman untuk test Ollama API langsung
├── knowledge-base.md           # File ini
└── app/
    ├── main.py                 # FastAPI entry point, endpoint /donatku & /chat
    └── system_prompt.py        # Definisi SYSTEM_PROMPT untuk AI
```

---

## 🏗️ Arsitektur Sistem

```
[Client / Postman / Browser]
          │
          │  HTTP POST /chat  (port 8000)
          ▼
  ┌────────────────┐
  │   FastAPI API  │  ← service: api (Dockerfile)
  │   app/main.py  │
  └───────┬────────┘
          │
          │  HTTP POST /api/chat  (port 11434, internal Docker network)
          ▼
  ┌────────────────┐
  │     Ollama     │  ← service: ollama (image: ollama/ollama:latest)
  │  llama3.2:3b   │
  └───────┬────────┘
          │
          ▼
  [Volume: ollama_data]  ← model tersimpan secara persisten
```

### Alur Request
1. Client kirim `POST /chat` dengan body `{"message": "..."}`
2. FastAPI inject **SYSTEM_PROMPT** + pesan user ke dalam payload
3. FastAPI kirim payload ke Ollama endpoint `/api/chat` (timeout: 120 detik)
4. Ollama proses dengan model `llama3.2:3b` → kembalikan respons JSON
5. FastAPI ekstrak `message.content` → kembalikan `{"reply": "..."}` ke client

---

## ⚙️ Konfigurasi Environment Variables

| Variable | Default (lokal) | Nilai di Docker | Keterangan |
|---|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | `http://ollama:11434` | URL service Ollama |
| `OLLAMA_MODEL` | `llama3.2:3b` | `llama3.2:3b` | Nama model yang dipakai |

Konfigurasi ini ada di [`docker-compose.yml`](./docker-compose.yml):
```yaml
environment:
  - OLLAMA_BASE_URL=http://ollama:11434
  - OLLAMA_MODEL=llama3.2:3b
```

---

## 🐳 Docker Compose — Detail Services

### Service `ollama`
```yaml
image: ollama/ollama:latest
ports:
  - "11434:11434"
volumes:
  - ollama_data:/root/.ollama   # Model tetap tersimpan meski container restart
```

### Service `api`
```yaml
build: .                        # Menggunakan Dockerfile di root
ports:
  - "8000:8000"
depends_on:
  - ollama                      # Tunggu ollama siap dulu
```

### Volume
```yaml
volumes:
  ollama_data:                  # Named volume, managed by Docker
```

---

## 🐍 Dependensi Python

File: [`requirements.txt`](./requirements.txt)

| Package | Versi | Kegunaan |
|---|---|---|
| `fastapi` | 0.141.1 | Framework REST API |
| `uvicorn[standard]` | 0.53.0 | ASGI web server |
| `httpx` | 0.28.1 | Async HTTP client untuk panggil Ollama |
| `starlette` | 1.6.0 | Core framework (dependency FastAPI) |
| `jinja2` | 3.1.4 | Template HTML (siap untuk web UI) |
| `pypdf` | 5.1.0 | Parser PDF (siap untuk fitur RAG/upload dokumen) |
| `python-multipart` | 0.0.12 | Handle file upload (form-data) |

> **Catatan:** `pypdf` dan `python-multipart` sudah ada di dependencies,
> artinya fitur **upload PDF** dan **web UI** sudah direncanakan.

---

## 🤖 Custom Ollama Model (Modelfile)

File: [`Modelfile`](./Modelfile)

```
FROM llama3.2:3b
SYSTEM """Kamu adalah asisten donat bolong. Kamu harus menggunakan bahasa indonesia
yang kasar. Tugas kamu adalah hanya menjawab terkait dengan topik kuliner. Tidak boleh
menjawab selain dari topik kuliner, jika ada pertanyaan diluar topik alihkan.
Maksimal output tidak lebih dari 50 kata."""
```

### Cara Membuat Custom Model dari Modelfile
```bash
# 1. Copy Modelfile ke dalam container Ollama
docker cp Modelfile <ollama_container_id>:/Modelfile

# 2. Buat model custom
docker exec -it <ollama_container_id> ollama create donatku -f /Modelfile

# 3. Verifikasi
docker exec -it <ollama_container_id> ollama list

# 4. Ganti di docker-compose.yml
# OLLAMA_MODEL=donatku
```

---

## 🌐 API Endpoints

### `GET /donatku`
Health check — cek apakah API berjalan.

**Response:**
```json
{ "status": "ok" }
```

---

### `POST /chat`
Endpoint utama untuk chat dengan AI.

**Request:**
```http
POST http://localhost:8000/chat
Content-Type: application/json

{
  "message": "Donat apa yang paling enak?"
}
```

**Response sukses (200):**
```json
{
  "reply": "Woi, mau tau donat enak?! Coba glazed donat, empuk dan manisnya pas..."
}
```

**Response error (502) — Ollama tidak bisa dihubungi:**
```json
{
  "detail": "Gagal menghubungi Ollama: ..."
}
```

**Timeout:** 120 detik (dikonfigurasi di `httpx.AsyncClient`)

---

## 📝 System Prompt

File: [`app/system_prompt.py`](./app/system_prompt.py)

```python
SYSTEM_PROMPT = """Kamu adalah asisten donat bolong. Kamu harus menggunakan bahasa
indonesia yang kasar. Tugas kamu hanya menjawab topik kuliner. Jika ada pertanyaan
di luar topik, alihkan kembali ke kuliner. Maksimal output 50 kata."""
```

### Karakteristik Persona AI
| Aspek | Detail |
|---|---|
| Nama Persona | Asisten Donat Bolong |
| Bahasa | Bahasa Indonesia informal / kasar |
| Topik | **Kuliner saja** — pertanyaan lain dialihkan |
| Panjang Jawaban | Maksimal 50 kata |

---

## 🧪 Testing dengan Postman

Import file [`ollama_collection.json`](./ollama_collection.json) ke Postman.

### Daftar Request di Koleksi

| # | Nama Request | Method | Endpoint |
|---|---|---|---|
| 1 | Cek Status Ollama | `GET` | `{{base_url}}` |
| 2 | Lihat Daftar Model | `GET` | `{{base_url}}/api/tags` |
| 3 | Chat dengan AI | `POST` | `{{base_url}}/api/chat` |
| 4 | Generate Teks | `POST` | `{{base_url}}/api/generate` |
| 5 | Chat Multi-Turn | `POST` | `{{base_url}}/api/chat` |
| 6 | Info Detail Model | `POST` | `{{base_url}}/api/show` |

### Variables Koleksi
| Variable | Value |
|---|---|
| `base_url` | `http://localhost:11434` |
| `model` | `llama3.2:3b` |

---

## 🚀 Cara Menjalankan

### Langkah 1 — Build & jalankan semua service
```bash
docker-compose up --build
```

### Langkah 2 — Pull model Ollama (wajib dilakukan pertama kali)
```bash
docker exec -it <nama_container_ollama> ollama pull llama3.2:3b
```

> Nama container bisa dicek dengan `docker ps`

### Langkah 3 — Test health check API
```bash
curl http://localhost:8000/donatku
# Expected: {"status":"ok"}
```

### Langkah 4 — Test chat AI
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Rekomendasi donat enak dong"}'
```

### Langkah 5 — Test Ollama langsung
```bash
curl http://localhost:11434
# Expected: "Ollama is running"
```

---

## 🛠️ Panduan Development

### Menambah Endpoint Baru
Edit [`app/main.py`](./app/main.py):
```python
@app.get("/endpoint-baru")
def endpoint_baru():
    return {"data": "isi response"}
```

### Mengubah Persona / System Prompt
Edit [`app/system_prompt.py`](./app/system_prompt.py), lalu rebuild:
```bash
docker-compose up --build api
```

### Mengganti Model LLM
1. Edit `docker-compose.yml`:
   ```yaml
   - OLLAMA_MODEL=nama_model_baru
   ```
2. Pull model baru:
   ```bash
   docker exec -it <ollama_container> ollama pull nama_model_baru
   ```
3. Restart service api:
   ```bash
   docker-compose restart api
   ```

---

## ⚠️ Troubleshooting

| Masalah | Penyebab | Solusi |
|---|---|---|
| Error `502` dari `/chat` | Ollama belum ready atau model belum di-pull | Tunggu startup, lalu `ollama pull llama3.2:3b` |
| Container `api` crash | Ollama belum siap saat `api` start | Tambah `healthcheck` di service `ollama` pada docker-compose |
| Response AI sangat lambat | LLM berjalan di CPU (tanpa GPU) | Wajar — pertimbangkan model lebih kecil atau tambah GPU |
| `model not found` | Model belum di-pull | `docker exec ollama ollama pull llama3.2:3b` |
| Port conflict 8000 / 11434 | Port sudah dipakai proses lain | Ubah port mapping di `docker-compose.yml` |
| AI menjawab di luar kuliner | System prompt tidak diterapkan | Pastikan `SYSTEM_PROMPT` di-inject dengan benar di payload |

---

## 🔮 Roadmap Fitur (Berdasarkan Dependencies)

Dependensi berikut sudah ada di `requirements.txt`, siap untuk dikembangkan:

| Dependensi | Fitur yang Bisa Dibangun |
|---|---|
| `pypdf` | Upload & parsing dokumen PDF → RAG (tanya jawab berbasis dokumen) |
| `python-multipart` | Form upload file dari web UI atau Postman |
| `jinja2` | Halaman web UI chatbot (serve HTML template dari FastAPI) |

### Contoh implementasi upload PDF (draft):
```python
from fastapi import UploadFile, File
from pypdf import PdfReader
import io

@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    contents = await file.read()
    reader = PdfReader(io.BytesIO(contents))
    text = "\n".join(page.extract_text() for page in reader.pages)
    return {"pages": len(reader.pages), "preview": text[:500]}
```

---

*Knowledge base ini dibuat berdasarkan analisis kode sumber proyek donatkuAI.*
*Update file ini setiap kali ada perubahan signifikan pada arsitektur atau fitur.*
