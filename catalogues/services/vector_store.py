"""
ChromaDB persistent vector store. One collection per Catalogue (collection_name = slug).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from django.conf import settings
from django.utils import timezone

from .chunking import chunk_text, document_text
from .embeddings import embed_query, embed_texts, embedding_model_name

log = logging.getLogger("irri")

_client = None


def get_client():
    global _client
    if _client is None:
        import chromadb
        Path(settings.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(settings.CHROMA_PERSIST_DIR))
    return _client


def get_or_create_collection(catalogue):
    client = get_client()
    return client.get_or_create_collection(
        name=catalogue.vector_store_collection_name or catalogue.slug,
        metadata={"catalogue_id": catalogue.id, "catalogue_name": catalogue.name},
    )


def build_catalogue_vector_db(catalogue) -> dict:
    """
    Rebuild the Chroma collection for one catalogue.
    Returns stats: {"documents": int, "chunks": int}.
    """
    from catalogues.models import Catalogue

    catalogue.vector_db_status = Catalogue.VDB_BUILDING
    catalogue.vector_db_error = ""
    catalogue.save(update_fields=["vector_db_status", "vector_db_error"])

    client = get_client()
    coll_name = catalogue.vector_store_collection_name or catalogue.slug
    # Reset collection for a clean rebuild
    try:
        client.delete_collection(coll_name)
    except Exception:
        pass
    collection = client.get_or_create_collection(
        name=coll_name,
        metadata={"catalogue_id": catalogue.id, "catalogue_name": catalogue.name},
    )

    total_chunks = 0
    docs = list(catalogue.documents.all().prefetch_related("keywords"))
    for doc in docs:
        text = document_text(doc)
        chunks: List[str] = chunk_text(text)
        if not chunks:
            continue
        ids = [f"{doc.id}:{i}" for i in range(len(chunks))]
        metadatas = [{
            "document_id": doc.id,
            "document_title": doc.title,
            "chunk_index": i,
            "category": doc.category.name if doc.category else "",
            "subcategory": doc.subcategory.name if doc.subcategory else "",
            "crop": doc.crop or "",
            "year": doc.year or 0,
            "source_url": doc.source_url or "",
            "doc_type": doc.doc_type or "",
            "content_type": doc.content_type or "",
        } for i in range(len(chunks))]
        try:
            vecs = embed_texts(chunks)
        except Exception as exc:
            log.exception("Embedding failed for doc %s", doc.id)
            catalogue.vector_db_status = Catalogue.VDB_FAILED
            catalogue.vector_db_error = str(exc)
            catalogue.save(update_fields=["vector_db_status", "vector_db_error"])
            raise
        # Chroma caps upserts at ~166 per call; send in safe 150-row batches.
        CHROMA_BATCH = 150
        for start in range(0, len(chunks), CHROMA_BATCH):
            end = start + CHROMA_BATCH
            collection.upsert(
                ids=ids[start:end],
                documents=chunks[start:end],
                metadatas=metadatas[start:end],
                embeddings=vecs[start:end],
            )
        total_chunks += len(chunks)

    catalogue.vector_db_status = Catalogue.VDB_READY
    catalogue.vector_db_generated_at = timezone.now()
    catalogue.vector_db_chunks_count = total_chunks
    catalogue.embedding_model = embedding_model_name()
    catalogue.save(update_fields=[
        "vector_db_status", "vector_db_generated_at",
        "vector_db_chunks_count", "embedding_model",
    ])
    return {"documents": len(docs), "chunks": total_chunks}


def search_catalogue(catalogue, query_text: str, n_results: int = 6):
    collection = get_or_create_collection(catalogue)
    vec = embed_query(query_text)
    if not vec:
        return []
    res = collection.query(query_embeddings=[vec], n_results=n_results)
    hits = []
    for i, doc_chunk in enumerate((res.get("documents") or [[]])[0]):
        meta = (res.get("metadatas") or [[{}]])[0][i]
        dist = (res.get("distances") or [[0]])[0][i] if res.get("distances") else None
        hits.append({
            "chunk": doc_chunk,
            "metadata": meta,
            "distance": dist,
            "score": round(1 - dist, 4) if dist is not None else None,
        })
    return hits
