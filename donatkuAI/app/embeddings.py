import httpx


def embed_text(text: str, base_url: str, model: str = "nomic-embed-text") -> list[float]:
    """Mengubah teks menjadi vektor embedding (synchronous)."""
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f"{base_url}/api/embed",
            json={"model": model, "input": text},
        )
        response.raise_for_status()
        return response.json()["embeddings"][0]


async def aembed_text(text: str, base_url: str, model: str = "nomic-embed-text") -> list[float]:
    """Mengubah teks menjadi vektor embedding (asynchronous)."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{base_url}/api/embed",
            json={"model": model, "input": text},
        )
        response.raise_for_status()
        return response.json()["embeddings"][0]


async def aembed_texts(texts: list[str], base_url: str, model: str = "nomic-embed-text") -> list[list[float]]:
    """Mengubah list teks menjadi list vektor embedding sekaligus (batch asynchronous)."""
    if not texts:
        return []
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{base_url}/api/embed",
            json={"model": model, "input": texts},
        )
        response.raise_for_status()
        return response.json()["embeddings"]
