import os
import glob
import json
import httpx
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel
from app.system_prompt import SYSTEM_PROMPT
from app.ingest import extract_text
from app.vector_db import (
    OPENSEARCH_BASE_URL,
    init_vector_index,
    sync_knowledge_base_to_vector_db,
    search_similar_chunks,
    get_vector_db_stats,
    index_document_chunks,
)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
KNOWLEDGE_BASE_PATH = os.environ.get("KNOWLEDGE_BASE_PATH", "/app/knowledge-base")

# ── Cache knowledge base (di-load sekali, bukan tiap request) ─────────────────
_kb_cache: str = ""
_kb_mtime: float = 0.0


def load_knowledge_base() -> str:
    """Baca semua file .md dan .pdf dari folder knowledge-base.
    Gunakan cache agar tidak baca disk tiap request."""
    global _kb_cache, _kb_mtime

    if not os.path.isdir(KNOWLEDGE_BASE_PATH):
        return ""

    # Cek apakah ada file yang berubah sejak cache terakhir
    latest_mtime = 0.0
    patterns = ["*.md", "*.pdf", "*.txt"]
    all_paths = []
    for pattern in patterns:
        all_paths.extend(glob.glob(os.path.join(KNOWLEDGE_BASE_PATH, pattern)))

    for path in all_paths:
        try:
            mtime = os.path.getmtime(path)
            if mtime > latest_mtime:
                latest_mtime = mtime
        except Exception:
            pass

    # Return cache kalau tidak ada perubahan
    if latest_mtime <= _kb_mtime and _kb_cache:
        return _kb_cache

    # Reload dari disk
    docs = []
    for path in all_paths:
        try:
            text = extract_text(path)
            if text.strip():
                docs.append(f"[{os.path.basename(path)}]\n{text}")
        except Exception:
            pass

    _kb_cache = "\n\n---\n\n".join(docs)
    _kb_mtime = latest_mtime
    return _kb_cache


async def warmup_model():
    """Kirim request ringan ke Ollama saat startup agar model di-load ke VRAM/RAM.
    Ini menghilangkan cold-start delay pada pertanyaan pertama user."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            await client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                    "options": {"num_predict": 1},  # Jawab 1 token saja, cepat
                },
            )
        print(f"[DonatkuAI] Model '{OLLAMA_MODEL}' warm-up selesai ✅")
    except Exception as e:
        print(f"[DonatkuAI] Model warm-up gagal (tidak masalah, lanjut): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Jalankan warm-up model dan sinkronisasi Vector Database saat aplikasi start."""
    load_knowledge_base()
    print("[DonatkuAI] Knowledge base di-cache ✅")
    asyncio.create_task(warmup_model())

    # Inisialisasi dan sinkronisasi Vector Database di OpenSearch secara background
    async def init_vdb():
        try:
            print("[DonatkuAI] Menginisialisasi OpenSearch Vector Database...")
            await init_vector_index(OPENSEARCH_BASE_URL)
            res = await sync_knowledge_base_to_vector_db(
                KNOWLEDGE_BASE_PATH, OLLAMA_BASE_URL, OPENSEARCH_BASE_URL
            )
            print(
                f"[DonatkuAI] Vector Database siap! {res.get('total_chunks_indexed', 0)} chunks terindeks ✅"
            )
        except Exception as e:
            print(f"[DonatkuAI] Vector DB sync notice (fallback aktif): {e}")

    asyncio.create_task(init_vdb())
    yield
    # Cleanup saat shutdown (opsional)


app = FastAPI(title="DonatkuAI", lifespan=lifespan)


# ── Models ────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


class Message(BaseModel):
    role: str
    content: str


class ChatStreamRequest(BaseModel):
    messages: list[Message]


class VectorSearchRequest(BaseModel):
    query: str
    top_k: int = 3


# ── Frontend Web UI ───────────────────────────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>DonatkuAI — Asisten Ahli Donat</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    
    :root {
      --bg-main: #fbf7f4;
      --bg-sidebar: #f4eae2;
      --bg-sidebar-hover: #e9ded5;
      --bg-sidebar-active: #dfd1c5;
      --border-color: #e8dbd1;
      --border-dark: #d8c5b7;
      --text-main: #2b1810;
      --text-muted: #7d655a;
      --brand-orange: #d9531e;
      --brand-orange-hover: #b83e10;
      --brand-light: #faeee7;
      --card-bg: #ffffff;
      --user-bubble: linear-gradient(135deg, #d9531e, #e86e2d);
    }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg-main);
      color: var(--text-main);
      height: 100vh;
      display: flex;
      overflow: hidden;
    }

    /* ── SIDEBAR (Mirip ChatGPT) ── */
    #sidebar {
      width: 260px;
      background: var(--bg-sidebar);
      border-right: 1px solid var(--border-color);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
      transition: transform 0.25s ease, margin-left 0.25s ease;
      z-index: 100;
      height: 100%;
    }

    #sidebar.collapsed {
      margin-left: -260px;
    }

    .sidebar-header {
      padding: 14px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid var(--border-color);
    }

    .brand-group {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .brand-logo {
      font-size: 26px;
      line-height: 1;
      filter: drop-shadow(0 2px 4px rgba(217, 83, 30, 0.2));
    }

    .brand-name {
      font-weight: 700;
      font-size: 16px;
      color: var(--brand-orange);
      letter-spacing: -0.2px;
    }

    .sidebar-close-btn {
      display: none;
      background: transparent;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      padding: 4px;
      border-radius: 6px;
    }

    .sidebar-actions {
      padding: 12px 14px;
    }

    .new-chat-btn {
      width: 100%;
      background: var(--card-bg);
      border: 1.5px solid var(--border-color);
      color: var(--brand-orange);
      padding: 10px 14px;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 10px;
      transition: all 0.2s ease;
      box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    }

    .new-chat-btn:hover {
      background: var(--brand-light);
      border-color: var(--brand-orange);
      transform: translateY(-1px);
    }

    .history-title {
      padding: 10px 16px 4px 16px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
    }

    .history-list {
      flex: 1;
      overflow-y: auto;
      padding: 6px 10px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .history-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 9px 12px;
      border-radius: 8px;
      font-size: 13.5px;
      color: var(--text-main);
      cursor: pointer;
      transition: background 0.15s ease;
      text-decoration: none;
      position: relative;
      group: relative;
    }

    .history-item:hover {
      background: var(--bg-sidebar-hover);
    }

    .history-item.active {
      background: var(--bg-sidebar-active);
      font-weight: 600;
      color: var(--brand-orange);
    }

    .history-label {
      display: flex;
      align-items: center;
      gap: 8px;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      flex: 1;
    }

    .history-icon {
      font-size: 14px;
      flex-shrink: 0;
      opacity: 0.8;
    }

    .history-text {
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }

    .delete-chat-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      padding: 2px 4px;
      border-radius: 4px;
      display: none;
      opacity: 0.7;
      transition: opacity 0.2s;
    }

    .history-item:hover .delete-chat-btn {
      display: block;
    }

    .delete-chat-btn:hover {
      opacity: 1;
      color: #dc2626;
    }

    .sidebar-footer {
      padding: 12px 14px;
      border-top: 1px solid var(--border-color);
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .clear-all-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 12.5px;
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 8px;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s;
      width: 100%;
      text-align: left;
    }

    .clear-all-btn:hover {
      background: var(--bg-sidebar-hover);
      color: #dc2626;
    }

    /* ── MAIN CONTENT AREA ── */
    #main-wrapper {
      flex: 1;
      display: flex;
      flex-direction: column;
      height: 100%;
      overflow: hidden;
      position: relative;
    }

    /* Top Navigation bar */
    .chat-header {
      height: 52px;
      border-bottom: 1px solid var(--border-color);
      background: rgba(251, 247, 244, 0.85);
      backdrop-filter: blur(8px);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 16px;
      flex-shrink: 0;
      z-index: 10;
    }

    .header-left {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .toggle-sidebar-btn {
      background: transparent;
      border: 1px solid var(--border-color);
      color: var(--text-muted);
      width: 32px;
      height: 32px;
      border-radius: 8px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.2s;
    }

    .toggle-sidebar-btn:hover {
      background: var(--bg-sidebar);
      color: var(--text-main);
    }

    .model-badge {
      display: flex;
      align-items: center;
      gap: 6px;
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      padding: 5px 12px;
      border-radius: 20px;
      font-size: 12.5px;
      font-weight: 600;
      color: var(--text-main);
      box-shadow: 0 1px 3px rgba(0,0,0,0.02);
    }

    .status-dot {
      width: 7px;
      height: 7px;
      background: #10b981;
      border-radius: 50%;
      display: inline-block;
      box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
    }

    /* Scrollable chat body */
    #chat-scroll-area {
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
    }

    #chat-content {
      max-width: 800px;
      width: 100%;
      margin: 0 auto;
      padding: 24px 20px 40px 20px;
      display: flex;
      flex-direction: column;
      gap: 22px;
      flex: 1;
    }

    /* Welcome / Hero screen (saat chat baru) */
    .welcome-container {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      margin: auto 0;
      text-align: center;
      padding: 20px 0;
    }

    .welcome-donut {
      font-size: 64px;
      line-height: 1;
      margin-bottom: 16px;
      animation: floatDonut 3s ease-in-out infinite;
      filter: drop-shadow(0 6px 12px rgba(217, 83, 30, 0.25));
    }

    @keyframes floatDonut {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-8px); }
    }

    .welcome-title {
      font-size: 24px;
      font-weight: 700;
      color: var(--text-main);
      margin-bottom: 8px;
      letter-spacing: -0.3px;
    }

    .welcome-subtitle {
      font-size: 14px;
      color: var(--text-muted);
      max-width: 480px;
      line-height: 1.5;
      margin-bottom: 26px;
    }

    .suggestions-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(220px, 1fr));
      gap: 10px;
      width: 100%;
      max-width: 620px;
    }

    .suggestion-card {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 14px 16px;
      text-align: left;
      cursor: pointer;
      transition: all 0.2s ease;
      box-shadow: 0 2px 6px rgba(0,0,0,0.02);
      display: flex;
      align-items: flex-start;
      gap: 10px;
    }

    .suggestion-card:hover {
      border-color: var(--brand-orange);
      background: var(--brand-light);
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(217, 83, 30, 0.08);
    }

    .sug-icon {
      font-size: 18px;
      line-height: 1.3;
    }

    .sug-title {
      font-size: 13.5px;
      font-weight: 600;
      color: var(--text-main);
      margin-bottom: 2px;
    }

    .sug-desc {
      font-size: 12px;
      color: var(--text-muted);
    }

    /* Message Bubbles (Mirip ChatGPT) */
    .message-row {
      display: flex;
      gap: 14px;
      width: 100%;
      animation: fadeIn 0.2s ease;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .message-row.user {
      justify-content: flex-end;
    }

    .message-row.bot {
      justify-content: flex-start;
    }

    .msg-avatar {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      flex-shrink: 0;
      box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }

    .message-row.user .msg-avatar {
      background: #a33810;
      color: #fff;
      display: none; /* Modern chatgpt style: hide user avatar or keep simple */
    }

    .message-row.bot .msg-avatar {
      background: #fff;
      border: 1px solid var(--border-color);
    }

    .msg-content-wrapper {
      max-width: 82%;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .message-row.user .msg-content-wrapper {
      align-items: flex-end;
    }

    .msg-bubble {
      padding: 12px 18px;
      border-radius: 18px;
      font-size: 14.5px;
      line-height: 1.65;
      word-break: break-word;
    }

    .message-row.user .msg-bubble {
      background: var(--user-bubble);
      color: #fff;
      border-bottom-right-radius: 5px;
      box-shadow: 0 2px 8px rgba(217, 83, 30, 0.25);
    }

    .message-row.bot .msg-bubble {
      background: var(--card-bg);
      color: var(--text-main);
      border: 1px solid var(--border-color);
      border-top-left-radius: 5px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.02);
    }

    .msg-bubble p:not(:last-child) {
      margin-bottom: 10px;
    }

    .msg-bubble ul, .msg-bubble ol {
      margin-left: 22px;
      margin-bottom: 10px;
    }

    .msg-bubble li {
      margin-bottom: 4px;
    }

    .msg-bubble strong {
      color: var(--brand-orange);
    }

    .message-row.user .msg-bubble strong {
      color: #fff;
      text-decoration: underline;
    }

    .msg-bubble code {
      background: rgba(0,0,0,0.05);
      padding: 2px 6px;
      border-radius: 5px;
      font-family: monospace;
      font-size: 13px;
    }

    .msg-actions {
      display: flex;
      gap: 8px;
      margin-top: 4px;
      opacity: 0;
      transition: opacity 0.2s;
    }

    .message-row.bot:hover .msg-actions {
      opacity: 1;
    }

    .copy-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      font-size: 12px;
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 2px 6px;
      border-radius: 4px;
    }

    .copy-btn:hover {
      background: var(--bg-sidebar);
      color: var(--text-main);
    }

    /* Thinking / loading state */
    .thinking-indicator {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--text-muted);
      font-size: 14px;
      font-style: italic;
      padding: 2px 0;
    }

    .thinking-dots {
      display: flex;
      gap: 4px;
      align-items: center;
    }

    .thinking-dots span {
      width: 6px;
      height: 6px;
      background: var(--brand-orange);
      border-radius: 50%;
      animation: thinkBounce 1.2s ease-in-out infinite;
    }

    .thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
    .thinking-dots span:nth-child(3) { animation-delay: 0.4s; }

    @keyframes thinkBounce {
      0%, 100% { transform: translateY(0); opacity: 0.4; }
      50% { transform: translateY(-5px); opacity: 1; }
    }

    /* Blinking cursor — inline di akhir teks */
    .cursor {
      display: inline-block;
      width: 2px;
      height: 1em;
      background: var(--brand-orange);
      margin-left: 2px;
      vertical-align: text-bottom;
      animation: blink 0.8s infinite;
      border-radius: 1px;
    }

    @keyframes blink {
      0%, 100% { opacity: 1; }
      50% { opacity: 0; }
    }

    /* ── BOTTOM INPUT BAR (Mirip ChatGPT) ── */
    .input-zone {
      padding: 12px 20px 18px 20px;
      background: linear-gradient(180deg, rgba(251, 247, 244, 0) 0%, rgba(251, 247, 244, 1) 35%);
      position: relative;
      z-index: 5;
    }

    .input-container {
      max-width: 800px;
      margin: 0 auto;
      background: var(--card-bg);
      border: 1.5px solid var(--border-color);
      border-radius: 20px;
      padding: 8px 16px;
      display: flex;
      align-items: center; /* Teks dan tombol pas di tengah vertikal */
      gap: 10px;
      box-shadow: 0 4px 16px rgba(43, 24, 16, 0.05);
      transition: border-color 0.2s, box-shadow 0.2s;
      min-height: 52px;
    }

    .input-container:focus-within {
      border-color: var(--brand-orange);
      box-shadow: 0 4px 20px rgba(217, 83, 30, 0.12);
    }

    textarea#prompt-input {
      flex: 1;
      border: none;
      outline: none;
      background: transparent;
      resize: none;
      font-size: 14.5px;
      font-family: inherit;
      color: var(--text-main);
      max-height: 140px;
      height: 24px;
      line-height: 24px; /* Vertikal center di dalam textarea */
      padding: 0;
      margin: 0;
      -webkit-appearance: none;
      appearance: none;
      pointer-events: auto;
      cursor: text;
      user-select: text;
      -webkit-user-select: text;
      overflow: hidden; /* Hilangkan panah atas-bawah dan scrollbar */
      scrollbar-width: none; /* Firefox */
      -ms-overflow-style: none; /* IE/Edge */
    }

    /* Hilangkan panah scrollbar atas/bawah pada Chrome, Edge, Safari */
    textarea#prompt-input::-webkit-scrollbar {
      display: none !important;
      width: 0 !important;
      height: 0 !important;
    }

    textarea#prompt-input::-webkit-inner-spin-button,
    textarea#prompt-input::-webkit-outer-spin-button {
      -webkit-appearance: none !important;
      margin: 0 !important;
    }

    button#send-btn {
      background: var(--brand-orange);
      color: #fff;
      border: none;
      width: 34px;
      height: 34px;
      border-radius: 10px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s ease;
      flex-shrink: 0;
    }

    button#send-btn:hover:not(:disabled) {
      background: var(--brand-orange-hover);
      transform: scale(1.05);
    }

    button#send-btn:disabled {
      background: #e2d1c6;
      cursor: not-allowed;
      transform: none;
    }

    .disclaimer-text {
      font-size: 11.5px;
      color: var(--text-muted);
      text-align: center;
      margin-top: 8px;
    }

    /* Mobile backdrop */
    #sidebar-overlay {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.3);
      z-index: 90;
    }

    @media (max-width: 768px) {
      #sidebar {
        position: fixed;
        left: 0;
        top: 0;
        bottom: 0;
        transform: translateX(-100%);
        margin-left: 0 !important;
      }

      #sidebar.mobile-open {
        transform: translateX(0);
      }

      #sidebar-overlay.active {
        display: block;
      }

      .sidebar-close-btn {
        display: block;
      }

      .suggestions-grid {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>

  <!-- Backdrop untuk mobile saat sidebar terbuka -->
  <div id="sidebar-overlay" onclick="toggleSidebar()"></div>

  <!-- ── SIDEBAR HISTORY (ChatGPT style) ── -->
  <aside id="sidebar">
    <div class="sidebar-header">
      <div class="brand-group">
        <span class="brand-logo">🍩</span>
        <span class="brand-name">DonatkuAI</span>
      </div>
      <button class="sidebar-close-btn" onclick="toggleSidebar()" title="Tutup menu">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      </button>
    </div>

    <div class="sidebar-actions">
      <button class="new-chat-btn" onclick="createNewChat()">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <line x1="12" y1="5" x2="12" y2="19"></line>
          <line x1="5" y1="12" x2="19" y2="12"></line>
        </svg>
        <span>Obrolan Baru</span>
      </button>
    </div>

    <div class="history-title">Riwayat Chat</div>
    <div class="history-list" id="history-list">
      <!-- Chat history items will be rendered dynamically here -->
    </div>

    <div class="sidebar-footer">
      <button class="clear-all-btn" onclick="clearAllChats()">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"></polyline>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>
        <span>Hapus Semua Riwayat</span>
      </button>
    </div>
  </aside>

  <!-- ── MAIN CONTENT AREA ── -->
  <main id="main-wrapper">
    <header class="chat-header">
      <div class="header-left">
        <button class="toggle-sidebar-btn" onclick="toggleSidebar()" title="Buka/Tutup Sidebar">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
            <line x1="9" y1="3" x2="9" y2="21"></line>
          </svg>
        </button>
        <div class="model-badge">
          <span class="status-dot"></span>
          <span>DonatkuAI &bull; Llama 3.2:3b</span>
        </div>
      </div>
      <div>
        <!-- Right side empty for clean aesthetic -->
      </div>
    </header>

    <div id="chat-scroll-area">
      <div id="chat-content">
        <!-- Hero Welcome (Ditampilkan saat chat kosong) -->
        <div class="welcome-container" id="welcome-container">
          <div class="welcome-donut">🍩</div>
          <h2 class="welcome-title">Halo! Mau Bikin Donat Apa Hari Ini?</h2>
          <p class="welcome-subtitle">Tanyakan seputar resep, teknik proofing, rahasia white ring, troubleshooting donat bantat, hingga kreasi glaze kekinian.</p>
          <div class="suggestions-grid">
            <div class="suggestion-card" onclick="askQuestion('Bagaimana resep donat kentang yang super empuk dan tahan 3 hari?')">
              <span class="sug-icon">🥔</span>
              <div>
                <div class="sug-title">Resep Donat Kentang</div>
                <div class="sug-desc">Empuk, lembut tahan lama</div>
              </div>
            </div>
            <div class="suggestion-card" onclick="askQuestion('Bagaimana rahasia memunculkan white ring yang tegas dan tinggi pada donat?')">
              <span class="sug-icon">👑</span>
              <div>
                <div class="sug-title">Rahasia White Ring</div>
                <div class="sug-desc">Teknik proofing & suhu minyak</div>
              </div>
            </div>
            <div class="suggestion-card" onclick="askQuestion('Kenapa donat saya menyerap banyak minyak saat digoreng dan bagaimana solusinya?')">
              <span class="sug-icon">⚠️</span>
              <div>
                <div class="sug-title">Donat Berminyak</div>
                <div class="sug-desc">Penyebab dan pencegahannya</div>
              </div>
            </div>
            <div class="suggestion-card" onclick="askQuestion('Bagi resep glaze cokelat mengkilap yang kokoh dan tidak meleleh di suhu ruang!')">
              <span class="sug-icon">🍫</span>
              <div>
                <div class="sug-title">Glaze Cokelat Mengkilap</div>
                <div class="sug-desc">Topping lezat dan stabil</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Input Bar -->
    <div class="input-zone">
      <div class="input-container">
        <textarea id="prompt-input" placeholder="Tanya apa saja seputar donat... (Enter untuk kirim)" rows="1" onkeydown="handleKeyDown(event)" oninput="autoResize(this)"></textarea>
        <button id="send-btn" onclick="sendMessage()" title="Kirim pesan">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </div>
      <div class="disclaimer-text">DonatkuAI dirancang untuk konsultasi kuliner & resep donat. Pastikan selalu menguji takaran bahan Anda.</div>
    </div>
  </main>

  <script>
    const STORAGE_KEY = 'donatku_chats_v1';
    let chats = [];
    let currentChatId = null;

    /**
     * Map untuk melacak stream yang sedang aktif.
     * Key: chatId, Value: { row (DOM Element), bubble (DOM Element) }
     * Ini memastikan streaming tetap berjalan di background walau user pindah chat.
     */
    const activeStreams = new Map();

    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    const historyList = document.getElementById('history-list');
    const chatScrollArea = document.getElementById('chat-scroll-area');
    const chatContent = document.getElementById('chat-content');
    const welcomeContainer = document.getElementById('welcome-container');
    const promptInput = document.getElementById('prompt-input');
    const sendBtn = document.getElementById('send-btn');

    // Load state from localStorage on init
    function init() {
      try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored) {
          chats = JSON.parse(stored);
        }
      } catch (e) {
        console.error('Failed to load chats from localStorage:', e);
        chats = [];
      }

      if (chats.length > 0) {
        loadChat(chats[0].id);
      } else {
        createNewChat();
      }
      renderHistory();
    }

    function saveChats() {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(chats));
      } catch (e) {
        console.error('Failed to save chats:', e);
      }
    }

    function toggleSidebar() {
      if (window.innerWidth <= 768) {
        sidebar.classList.toggle('mobile-open');
        overlay.classList.toggle('active');
      } else {
        sidebar.classList.toggle('collapsed');
      }
    }

    function resetInputBox() {
      promptInput.value = '';
      promptInput.style.height = '24px';
      promptInput.style.lineHeight = '24px';
      promptInput.style.overflowY = 'hidden';
      const container = promptInput.closest('.input-container');
      if (container) container.style.alignItems = 'center';
    }

    function autoResize(el) {
      el.style.height = 'auto';
      const newHeight = Math.min(el.scrollHeight, 140);
      el.style.height = newHeight + 'px';

      const container = el.closest('.input-container');
      if (newHeight > 32) {
        el.style.lineHeight = '1.5';
        el.style.overflowY = el.scrollHeight > 140 ? 'auto' : 'hidden';
        if (container) container.style.alignItems = 'flex-end';
      } else {
        el.style.lineHeight = '24px';
        el.style.overflowY = 'hidden';
        if (container) container.style.alignItems = 'center';
      }
    }

    function handleKeyDown(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    }

    function askQuestion(text) {
      promptInput.value = text;
      autoResize(promptInput);
      sendMessage();
    }

    function createNewChat() {
      // Reset input state dulu — pastikan textarea tidak terkunci dari sesi sebelumnya
      promptInput.disabled = false;
      sendBtn.disabled = false;

      currentChatId = 'chat_' + Date.now();
      const newChat = {
        id: currentChatId,
        title: 'Obrolan Baru',
        messages: [],
        createdAt: Date.now()
      };
      chats.unshift(newChat);
      saveChats();
      renderHistory();
      renderChatMessages();
      resetInputBox();
      promptInput.focus();
    }

    function loadChat(chatId) {
      // Reset input state saat pindah chat
      promptInput.disabled = false;
      sendBtn.disabled = false;

      currentChatId = chatId;
      renderHistory();
      renderChatMessages();
      resetInputBox();
      if (window.innerWidth <= 768) {
        sidebar.classList.remove('mobile-open');
        overlay.classList.remove('active');
      }
    }

    function deleteChat(chatId, event) {
      if (event) event.stopPropagation();
      chats = chats.filter(c => c.id !== chatId);
      saveChats();
      if (currentChatId === chatId) {
        if (chats.length > 0) {
          loadChat(chats[0].id);
        } else {
          createNewChat();
        }
      } else {
        renderHistory();
      }
    }

    function clearAllChats() {
      if (!confirm('Hapus semua riwayat percakapan?')) return;
      chats = [];
      saveChats();
      createNewChat();
    }

    function renderHistory() {
      historyList.innerHTML = '';
      chats.forEach(chat => {
        const isStreaming = activeStreams.has(chat.id);
        const item = document.createElement('div');
        item.className = 'history-item' + (chat.id === currentChatId ? ' active' : '');
        item.onclick = () => loadChat(chat.id);

        item.innerHTML = `
          <div class="history-label">
            <span class="history-icon">${isStreaming ? '⏳' : '💬'}</span>
            <span class="history-text">${escapeHtml(chat.title || 'Obrolan')}</span>
          </div>
          <button class="delete-chat-btn" onclick="deleteChat('${chat.id}', event)" title="Hapus chat">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
          </button>
        `;
        historyList.appendChild(item);
      });
    }

    function getCurrentChat() {
      return chats.find(c => c.id === currentChatId);
    }

    function renderChatMessages() {
      // ── Sebelum hapus DOM, cabut semua streaming row agar tidak ikut terhapus
      for (const [, entry] of activeStreams) {
        if (entry.row.parentNode === chatContent) {
          chatContent.removeChild(entry.row);
        }
      }

      chatContent.innerHTML = '';
      const current = getCurrentChat();

      if (!current || current.messages.length === 0) {
        chatContent.appendChild(welcomeContainer);
        welcomeContainer.style.display = 'flex';
      } else {
        welcomeContainer.style.display = 'none';
        current.messages.forEach(msg => {
          appendMessageElement(msg.role, msg.content);
        });
      }

      // ── Kalau chat ini sedang ada stream aktif, re-attach row-nya
      if (activeStreams.has(currentChatId)) {
        const { row } = activeStreams.get(currentChatId);
        chatContent.appendChild(row);
      }

      scrollChatToBottom();
    }

    function appendMessageElement(role, text) {
      welcomeContainer.style.display = 'none';

      const row = document.createElement('div');
      row.className = `message-row ${role === 'user' ? 'user' : 'bot'}`;

      const avatar = document.createElement('div');
      avatar.className = 'msg-avatar';
      avatar.textContent = role === 'user' ? '👤' : '🍩';

      const contentWrapper = document.createElement('div');
      contentWrapper.className = 'msg-content-wrapper';

      const bubble = document.createElement('div');
      bubble.className = 'msg-bubble';

      if (role === 'user') {
        bubble.textContent = text;
      } else {
        bubble.innerHTML = marked.parse(text);
      }

      contentWrapper.appendChild(bubble);

      // Copy button for bot
      if (role !== 'user') {
        const actions = document.createElement('div');
        actions.className = 'msg-actions';
        actions.innerHTML = `
          <button class="copy-btn" onclick="copyText(this)">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
            <span>Salin</span>
          </button>
        `;
        contentWrapper.appendChild(actions);
      }

      if (role !== 'user') {
        row.appendChild(avatar);
      }
      row.appendChild(contentWrapper);

      chatContent.appendChild(row);
      scrollChatToBottom();
      return bubble;
    }

    function scrollChatToBottom() {
      chatScrollArea.scrollTop = chatScrollArea.scrollHeight;
    }

    /**
     * Smart scroll: hanya auto-scroll ke bawah jika user sudah berada
     * dekat bagian bawah (dalam 120px). Kalau user scroll ke atas untuk
     * membaca, tidak dipaksa kembali ke bawah.
     */
    function smartScroll() {
      const el = chatScrollArea;
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      if (distanceFromBottom < 120) {
        el.scrollTop = el.scrollHeight;
      }
    }

    function copyText(btn) {
      const bubble = btn.closest('.msg-content-wrapper').querySelector('.msg-bubble');
      if (!bubble) return;
      navigator.clipboard.writeText(bubble.innerText).then(() => {
        const originalText = btn.querySelector('span').textContent;
        btn.querySelector('span').textContent = 'Disalin!';
        setTimeout(() => {
          btn.querySelector('span').textContent = originalText;
        }, 1500);
      });
    }

    function escapeHtml(str) {
      return str.replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
    }

    /**
     * Sisipkan <span class="cursor"> persis di samping teks terakhir yang sedang diketik,
     * menggunakan TreeWalker untuk menemukan Text Node paling akhir.
     */
    function injectInlineCursor(bubble) {
      // Hapus cursor lama kalau ada
      const old = bubble.querySelector('.cursor');
      if (old) old.remove();

      const cursor = document.createElement('span');
      cursor.className = 'cursor';

      // Cari Text Node paling akhir yang berisi teks (bukan hanya spasi/newline)
      const walker = document.createTreeWalker(
        bubble,
        NodeFilter.SHOW_TEXT,
        {
          acceptNode: function(node) {
            return node.nodeValue && node.nodeValue.trim().length > 0
              ? NodeFilter.FILTER_ACCEPT
              : NodeFilter.FILTER_SKIP;
          }
        }
      );

      let lastTextNode = null;
      while (walker.nextNode()) {
        lastTextNode = walker.currentNode;
      }

      if (lastTextNode && lastTextNode.parentNode) {
        // Sisipkan cursor persis setelah text node terakhir
        lastTextNode.parentNode.insertBefore(cursor, lastTextNode.nextSibling);
      } else {
        // Fallback jika belum ada teks sama sekali
        bubble.appendChild(cursor);
      }
    }

    async function sendMessage() {
      const text = promptInput.value.trim();
      if (!text) return;

      const current = getCurrentChat();
      if (!current) return;

      // Simpan referensi chatId saat ini — agar response tetap tersimpan
      // ke chat yang benar walau user pindah ke chat lain di tengah streaming
      const targetChatId = current.id;

      // Update chat title on first message
      if (current.messages.length === 0) {
        current.title = text.length > 28 ? text.slice(0, 28) + '...' : text;
        renderHistory();
      }

      // Add user message to state and render
      current.messages.push({ role: 'user', content: text });
      appendMessageElement('user', text);
      saveChats();

      resetInputBox();
      promptInput.disabled = true;
      sendBtn.disabled = true;

      // Tampilkan "Sedang berpikir..." di bubble bot
      const botBubble = appendMessageElement('bot', '');
      botBubble.innerHTML = `
        <div class="thinking-indicator">
          <div class="thinking-dots"><span></span><span></span><span></span></div>
          <span>Sedang berpikir...</span>
        </div>
      `;

      // ── Daftarkan ke activeStreams agar row tidak terhapus saat user pindah chat
      const botRow = botBubble.closest('.message-row');
      activeStreams.set(targetChatId, { row: botRow, bubble: botBubble });
      renderHistory(); // Update sidebar: tampilkan ikon ⏳

      let fullResponse = '';

      try {
        const response = await fetch('/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages: current.messages })
        });

        if (!response.ok) {
          throw new Error('Gagal menghubungi server (Status: ' + response.status + ')');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          fullResponse += chunk;

          // Render markdown + sisipkan cursor inline di akhir elemen terakhir
          botBubble.innerHTML = marked.parse(fullResponse);
          injectInlineCursor(botBubble);
          if (currentChatId === targetChatId) {
            smartScroll();
          }
        }

        // Selesai — hapus cursor, tampilkan teks final
        botBubble.innerHTML = marked.parse(fullResponse);
        if (currentChatId === targetChatId) {
          smartScroll();
        }

        // Simpan response ke chat yang BENAR (berdasarkan targetChatId)
        // bukan currentChatId yang mungkin sudah berubah
        const targetChat = chats.find(c => c.id === targetChatId);
        if (targetChat && fullResponse) {
          targetChat.messages.push({ role: 'assistant', content: fullResponse });
          saveChats();
        }

      } catch (err) {
        botBubble.innerHTML = '<span style="color:#dc2626;">Maaf, terjadi kesalahan: ' + err.message + '</span>';
        // Simpan respons parsial kalau ada
        if (fullResponse) {
          const targetChat = chats.find(c => c.id === targetChatId);
          if (targetChat) {
            targetChat.messages.push({ role: 'assistant', content: fullResponse });
            saveChats();
          }
        }

      } finally {
        // ── Hapus dari activeStreams & update sidebar (hilangkan ikon ⏳)
        activeStreams.delete(targetChatId);
        renderHistory();

        // Re-enable input hanya kalau user masih di chat yang sama
        if (currentChatId === targetChatId) {
          promptInput.disabled = false;
          sendBtn.disabled = false;
          promptInput.focus();
          scrollChatToBottom();
        }
      }
    }

    // Start on DOM ready
    window.addEventListener('DOMContentLoaded', init);
  </script>
</body>
</html>
"""



# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index_page():
    """Halaman web chat visual DonatkuAI."""
    return HTML_PAGE


@app.get("/donatku")
def donatku_check():
    return {"status": "ok"}


@app.post("/chat/stream")
async def chat_stream(req: ChatStreamRequest):
    # Validasi harus dilakukan SEBELUM StreamingResponse dibuat
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages tidak boleh kosong")

    system_content = SYSTEM_PROMPT
    user_query = req.messages[-1].content

    # 1. Semantic Vector Search via OpenSearch k-NN
    relevant_chunks = []
    try:
        relevant_chunks = await search_similar_chunks(
            query=user_query,
            ollama_base_url=OLLAMA_BASE_URL,
            opensearch_base_url=OPENSEARCH_BASE_URL,
            top_k=3,
        )
    except Exception as e:
        print(f"[Vector Search Warning] {e}")

    # 2. Sisipkan referensi: gunakan hasil vector search, atau fallback ke full KB
    if relevant_chunks:
        kb_text = "\n\n---\n\n".join([
            f"[{c['filename']} (Relevansi: {c['score']})]\n{c['text']}"
            for c in relevant_chunks
        ])
        system_content += (
            f"\n\nBerikut adalah referensi knowledge base yang relevan dari Vector Database:\n\n{kb_text}"
        )
    else:
        knowledge = load_knowledge_base()
        if knowledge:
            system_content += (
                f"\n\nBerikut adalah knowledge base yang bisa kamu gunakan:\n\n{knowledge}"
            )

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system_content}]
        + [m.model_dump() for m in req.messages],
        "stream": True,
    }

    async def event_generator():
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload
                ) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        chunk = data.get("message", {}).get("content", "")
                        if chunk:
                            yield chunk
                        if data.get("done"):
                            break
        except httpx.HTTPError as e:
            yield f"\n[error] Gagal menghubungi Ollama: {e}"

    return StreamingResponse(event_generator(), media_type="text/plain")


@app.get("/knowledge-base")
def list_knowledge_base():
    """Lihat daftar file yang ada di knowledge base."""
    if not os.path.isdir(KNOWLEDGE_BASE_PATH):
        return {"files": [], "message": "Folder knowledge-base tidak ditemukan"}

    files = []
    for pattern in ["*.md", "*.pdf", "*.txt"]:
        for path in glob.glob(os.path.join(KNOWLEDGE_BASE_PATH, pattern)):
            files.append({
                "name": os.path.basename(path),
                "size_bytes": os.path.getsize(path),
            })
    return {"files": files, "total": len(files)}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload file (.md, .txt, .pdf) ke knowledge base dan langsung indeks ke Vector Database."""
    allowed_ext = {".md", ".txt", ".pdf"}
    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in allowed_ext:
        raise HTTPException(
            status_code=400,
            detail=f"Format tidak didukung: {ext}. Gunakan .md, .txt, atau .pdf",
        )

    os.makedirs(KNOWLEDGE_BASE_PATH, exist_ok=True)
    dest = os.path.join(KNOWLEDGE_BASE_PATH, file.filename)

    contents = await file.read()
    with open(dest, "wb") as f:
        f.write(contents)

    # Otomatis embed & simpan ke OpenSearch Vector DB
    indexed_chunks = 0
    try:
        text = extract_text(dest)
        if text.strip():
            indexed_chunks = await index_document_chunks(
                file.filename, text, OLLAMA_BASE_URL, OPENSEARCH_BASE_URL
            )
    except Exception as e:
        print(f"[Upload Vector Indexing Warning] {e}")

    return {
        "message": f"File '{file.filename}' berhasil diupload dan diindeks ke Vector Database",
        "chunks_indexed": indexed_chunks,
    }


# ── Vector Database Specific Endpoints ────────────────────────────────────────

@app.get("/vector-db/stats")
async def vector_db_stats():
    """Lihat statistik dan jumlah vektor di OpenSearch."""
    return await get_vector_db_stats(OPENSEARCH_BASE_URL)


@app.post("/vector-db/sync")
async def vector_db_sync():
    """Trigger sinkronisasi ulang semua file knowledge base ke OpenSearch Vector Database."""
    result = await sync_knowledge_base_to_vector_db(
        KNOWLEDGE_BASE_PATH, OLLAMA_BASE_URL, OPENSEARCH_BASE_URL
    )
    return result


@app.post("/vector-db/search")
async def vector_db_search(req: VectorSearchRequest):
    """Testing pencarian kemiripan vektor (semantic vector search) langsung."""
    results = await search_similar_chunks(
        query=req.query,
        ollama_base_url=OLLAMA_BASE_URL,
        opensearch_base_url=OPENSEARCH_BASE_URL,
        top_k=req.top_k,
    )
    return {"query": req.query, "total_hits": len(results), "results": results}

