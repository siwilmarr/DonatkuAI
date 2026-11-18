# 02 — Konfigurasi

## ⚙️ Environment Variables

| Variable | Default (lokal) | Nilai di Docker | Keterangan |
|---|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | `http://ollama:11434` | URL service Ollama |
| `OLLAMA_MODEL` | `llama3.2:3b` | `llama3.2:3b` | Nama model LLM yang dipakai |

Variabel dibaca di `app/main.py`:
```python
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
```

---

## 🐳 Docker Compose (`docker-compose.yml`)

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama    # Model tersimpan persisten

  api:
    build: .                         # Pakai Dockerfile di root
    ports:
      - "8000:8000"
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
      - OLLAMA_MODEL=llama3.2:3b
    depends_on:
      - ollama                       # API tunggu Ollama dulu

volumes:
  ollama_data:
```

### Port Summary
| Service | Port Host | Port Container | Akses dari |
|---|---|---|---|
| `api` (FastAPI) | `8000` | `8000` | Luar Docker (client) |
| `ollama` | `11434` | `11434` | Luar Docker + internal service `api` |

---

## 🐋 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 🐍 Dependensi Python (`requirements.txt`)

| Package | Versi | Kegunaan |
|---|---|---|
| `fastapi` | 0.141.1 | Framework REST API |
| `uvicorn[standard]` | 0.53.0 | ASGI web server |
| `httpx` | 0.28.1 | Async HTTP client → panggil Ollama |
| `starlette` | 1.6.0 | Core framework (dependency FastAPI) |
| `jinja2` | 3.1.4 | Template HTML (siap untuk web UI) |
| `pypdf` | 5.1.0 | Parser PDF (siap untuk fitur RAG) |
| `python-multipart` | 0.0.12 | Handle file upload (form-data) |

> **Catatan:** `pypdf`, `python-multipart`, dan `jinja2` sudah ada meski belum digunakan —
> artinya fitur **upload PDF** dan **web UI** sudah direncanakan sejak awal.

---

## 🔧 Cara Mengubah Konfigurasi

### Ganti model LLM
```yaml
# docker-compose.yml
- OLLAMA_MODEL=nama_model_baru
```
```bash
docker exec -it <ollama_container> ollama pull nama_model_baru
docker-compose restart api
```

### Ganti port API
```yaml
# docker-compose.yml
ports:
  - "9000:8000"   # akses via localhost:9000
```

### Jalankan tanpa Docker (lokal)
```bash
# Pastikan Ollama sudah running di localhost:11434
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
