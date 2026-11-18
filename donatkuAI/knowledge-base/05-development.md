# 05 — Development & Troubleshooting

## 🚀 Cara Menjalankan Proyek

```bash
# 1. Build & jalankan semua service
docker-compose up --build

# 2. Pull model Ollama (WAJIB pertama kali)
docker exec -it <nama_container_ollama> ollama pull llama3.2:3b

# 3. Cek container yang berjalan
docker ps

# 4. Health check
curl http://localhost:8000/donatku
```

> Nama container bisa dicek dengan `docker ps`. Biasanya `donatkuai-ollama-1`.

---

## 🛠️ Panduan Modifikasi

### Menambah Endpoint Baru
Edit [`app/main.py`](../app/main.py):
```python
@app.get("/endpoint-baru")
def endpoint_baru():
    return {"data": "isi response"}
```
Rebuild container:
```bash
docker-compose up --build api
```

### Mengubah System Prompt / Persona
Edit [`app/system_prompt.py`](../app/system_prompt.py):
```python
SYSTEM_PROMPT = """Persona baru di sini..."""
```
Rebuild:
```bash
docker-compose up --build api
```

### Mengganti Model LLM
```yaml
# docker-compose.yml
- OLLAMA_MODEL=mistral:7b   # atau model lain
```
```bash
docker exec -it <ollama_container> ollama pull mistral:7b
docker-compose restart api
```

### Lihat Semua Model Tersedia di Ollama
```bash
docker exec -it <ollama_container> ollama list
```

---

## 🔮 Roadmap Fitur (Dependencies Sudah Siap)

| Dependensi | Fitur yang Bisa Dibangun |
|---|---|
| `pypdf` | Upload & parsing dokumen PDF → RAG |
| `python-multipart` | Form upload file dari web UI |
| `jinja2` | Web UI chatbot (serve HTML dari FastAPI) |

### Draft — Endpoint Upload PDF
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

## ⚠️ Troubleshooting

| Masalah | Penyebab | Solusi |
|---|---|---|
| Error `502` dari `/chat` | Ollama belum ready / model belum di-pull | Tunggu startup, lalu `ollama pull llama3.2:3b` |
| Container `api` crash saat start | Ollama belum siap saat `api` mulai | Tambah `healthcheck` ke service `ollama` di docker-compose |
| Response AI sangat lambat | LLM berjalan di CPU tanpa GPU | Wajar — coba model lebih kecil atau tambahkan GPU support |
| `model not found` di Ollama | Model belum di-pull | `docker exec <ollama> ollama pull llama3.2:3b` |
| Port conflict `8000` / `11434` | Port dipakai proses lain | Ubah port mapping di `docker-compose.yml` |
| AI menjawab di luar topik kuliner | System prompt tidak diterapkan | Pastikan `SYSTEM_PROMPT` di-inject pada payload di `main.py` |
| Perubahan kode tidak berlaku | Container tidak direbuild | `docker-compose up --build api` |

---

## 💡 Tips Docker

```bash
# Lihat log real-time
docker-compose logs -f

# Lihat log service tertentu
docker-compose logs -f api
docker-compose logs -f ollama

# Restart satu service saja
docker-compose restart api

# Stop semua service
docker-compose down

# Stop + hapus volume (HATI-HATI: model Ollama ikut terhapus)
docker-compose down -v

# Masuk ke dalam container
docker exec -it <container_id> bash
```

---

## 🔗 Referensi

- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Ollama API Reference](https://github.com/ollama/ollama/blob/main/docs/api.md)
- [httpx Async Client](https://www.python-httpx.org/async/)
- [Ollama Model Library](https://ollama.com/library)
