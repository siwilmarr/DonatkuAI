# 🍩 donatkuAI — Knowledge Base

> Chatbot AI kuliner berbasis FastAPI + Ollama (LLM lokal), di-deploy dengan Docker Compose.

## 📚 Daftar Dokumen

| File | Isi |
|---|---|
| [01-arsitektur.md](./01-arsitektur.md) | Arsitektur sistem, alur request, dan struktur proyek |
| [02-konfigurasi.md](./02-konfigurasi.md) | Environment variables, Docker Compose, dan Dockerfile |
| [03-api-endpoints.md](./03-api-endpoints.md) | Dokumentasi semua endpoint FastAPI |
| [04-ai-persona.md](./04-ai-persona.md) | System prompt, Modelfile, dan persona AI |
| [05-development.md](./05-development.md) | Panduan development, cara modifikasi, dan troubleshooting |

---

## ⚡ Quick Start

```bash
# 1. Jalankan semua service
docker-compose up --build

# 2. Pull model (pertama kali)
docker exec -it <ollama_container> ollama pull llama3.2:3b

# 3. Test API
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Donat apa yang enak?"}'
```

---

**Stack:** Python 3.11 · FastAPI · Ollama (llama3.2:3b) · Docker Compose
