import os
import glob
import logging
import httpx
from app.embeddings import aembed_text, aembed_texts
from app.ingest import extract_text

logger = logging.getLogger("donatku_vector_db")

OPENSEARCH_BASE_URL = os.getenv("OPENSEARCH_BASE_URL", "http://opensearch:9200")
INDEX_NAME = "donatku_knowledge_base"
VECTOR_DIM = 768  # Dimensi nomic-embed-text
EMBED_MODEL = "nomic-embed-text"


def chunk_text(text: str, max_chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    Memecah dokumen teks menjadi potongan-potongan (chunks) yang lebih kecil
    berdasarkan paragraf atau batas kata agar maknanya tetap utuh.
    """
    if not text or not text.strip():
        return []

    # Pisahkan berdasarkan paragraf kosong terlebih dahulu
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current_chunk = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len > max_chunk_size and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = [para]
            current_len = para_len
        else:
            current_chunk.append(para)
            current_len += para_len + 2

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks


async def init_vector_index(base_url: str = OPENSEARCH_BASE_URL) -> bool:
    """
    Membuat index di OpenSearch dengan dukungan k-NN (k-Nearest Neighbors) vector search.
    Jika index sudah ada, fungsi tidak akan menimpa.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # 1. Cek apakah index sudah ada
            res = await client.head(f"{base_url}/{INDEX_NAME}")
            if res.status_code == 200:
                logger.info(f"Index OpenSearch '{INDEX_NAME}' sudah aktif ✅")
                return True

            # 2. Skema konfigurasi Vector Search (HNSW + Cosine Similarity)
            mapping = {
                "settings": {
                    "index": {
                        "knn": True,
                        "number_of_shards": 1,
                        "number_of_replicas": 0
                    }
                },
                "mappings": {
                    "properties": {
                        "vector": {
                            "type": "knn_vector",
                            "dimension": VECTOR_DIM,
                            "method": {
                                "name": "hnsw",
                                "space_type": "cosinesimil",
                                "engine": "nmslib"
                            }
                        },
                        "text": {"type": "text"},
                        "filename": {"type": "keyword"},
                        "chunk_id": {"type": "integer"}
                    }
                }
            }

            resp = await client.put(f"{base_url}/{INDEX_NAME}", json=mapping)
            resp.raise_for_status()
            logger.info(f"Berhasil membuat k-NN vector index '{INDEX_NAME}' di OpenSearch ✅")
            return True
        except Exception as e:
            logger.error(f"Gagal inisialisasi vector index OpenSearch: {e}")
            return False


async def index_document_chunks(
    filename: str,
    text: str,
    ollama_base_url: str,
    opensearch_base_url: str = OPENSEARCH_BASE_URL
) -> int:
    """
    Memecah teks dokumen jadi chunks, menghitung vektor tiap chunk via Ollama,
    lalu menyimpannya ke OpenSearch Vector Database.
    """
    chunks = chunk_text(text)
    if not chunks:
        return 0

    # Dapatkan embedding untuk semua chunk sekaligus (batch)
    embeddings = await aembed_texts(chunks, ollama_base_url, model=EMBED_MODEL)

    async with httpx.AsyncClient(timeout=60.0) as client:
        indexed_count = 0
        for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
            doc_id = f"{filename}_chunk_{i}"
            body = {
                "filename": filename,
                "chunk_id": i,
                "text": chunk,
                "vector": vector
            }
            res = await client.put(
                f"{opensearch_base_url}/{INDEX_NAME}/_doc/{doc_id}",
                json=body
            )
            if res.status_code in [200, 201]:
                indexed_count += 1

        # Refresh index agar dokumen segera bisa di-search
        await client.post(f"{opensearch_base_url}/{INDEX_NAME}/_refresh")

    return indexed_count


async def sync_knowledge_base_to_vector_db(
    kb_path: str,
    ollama_base_url: str,
    opensearch_base_url: str = OPENSEARCH_BASE_URL
) -> dict:
    """
    Membaca semua file (.md, .pdf, .txt) dari folder knowledge-base,
    membuat embedding, dan menyimpannya ke dalam Vector Database OpenSearch.
    """
    await init_vector_index(opensearch_base_url)

    if not os.path.isdir(kb_path):
        return {"status": "error", "message": f"Folder {kb_path} tidak ditemukan"}

    total_files = 0
    total_chunks = 0
    patterns = ["*.md", "*.pdf", "*.txt"]

    for pattern in patterns:
        for file_path in glob.glob(os.path.join(kb_path, pattern)):
            try:
                filename = os.path.basename(file_path)
                content = extract_text(file_path)
                if content and content.strip():
                    count = await index_document_chunks(
                        filename, content, ollama_base_url, opensearch_base_url
                    )
                    total_chunks += count
                    total_files += 1
            except Exception as e:
                logger.error(f"Gagal memproses file {file_path}: {e}")

    return {
        "status": "success",
        "total_files": total_files,
        "total_chunks_indexed": total_chunks
    }


async def search_similar_chunks(
    query: str,
    ollama_base_url: str,
    opensearch_base_url: str = OPENSEARCH_BASE_URL,
    top_k: int = 3
) -> list[dict]:
    """
    Mencari potongan dokumen yang maknanya paling relevan dengan query user
    menggunakan Cosine Similarity Vector Search di OpenSearch.
    """
    try:
        # 1. Ubah pertanyaan user jadi vektor
        query_vector = await aembed_text(query, ollama_base_url, model=EMBED_MODEL)

        # 2. Kirim k-NN query ke OpenSearch
        knn_query = {
            "size": top_k,
            "query": {
                "knn": {
                    "vector": {
                        "vector": query_vector,
                        "k": top_k
                    }
                }
            }
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{opensearch_base_url}/{INDEX_NAME}/_search",
                json=knn_query
            )
            if resp.status_code != 200:
                logger.warning(f"OpenSearch search returned {resp.status_code}: {resp.text}")
                return []

            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])

            results = []
            for hit in hits:
                source = hit.get("_source", {})
                score = hit.get("_score", 0.0)
                results.append({
                    "filename": source.get("filename", "unknown"),
                    "chunk_id": source.get("chunk_id", 0),
                    "text": source.get("text", ""),
                    "score": round(float(score), 4)
                })

            return results
    except Exception as e:
        logger.error(f"Gagal melakukan vector search: {e}")
        return []


async def get_vector_db_stats(opensearch_base_url: str = OPENSEARCH_BASE_URL) -> dict:
    """Mendapatkan informasi status dan jumlah vektor di OpenSearch."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(f"{opensearch_base_url}/{INDEX_NAME}/_count")
            if res.status_code == 200:
                count = res.json().get("count", 0)
                return {
                    "status": "connected",
                    "index": INDEX_NAME,
                    "total_vectors": count,
                    "model": EMBED_MODEL
                }
            return {"status": "index_not_found", "total_vectors": 0}
        except Exception as e:
            return {"status": "error", "error": str(e), "total_vectors": 0}
