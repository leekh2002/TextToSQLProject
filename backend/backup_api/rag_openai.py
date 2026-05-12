import os
from functools import lru_cache

import numpy as np
from openai import OpenAI

schema_docs = [
    "course_offerings: 강의 개설 정보, 시간, 교수, 정원",
    "subject: 과목 정보, 학점, 이름",
    "department: 학과 정보",
    "enrollment: 수강 정보",
    "course_prerequisite: 선수과목",
]


def _get_client():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def embed(text):
    client = _get_client()
    if client is None:
        return None
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small").strip()
    res = client.embeddings.create(model=model, input=text)
    return res.data[0].embedding


@lru_cache(maxsize=1)
def _schema_embeddings():
    embs = []
    for doc in schema_docs:
        emb = embed(doc)
        if emb is None:
            return None
        embs.append(emb)
    return embs


def cosine(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def retrieve_schema(query, top_k=2):
    schema_embeddings = _schema_embeddings()
    q_emb = embed(query)
    if schema_embeddings is None or q_emb is None:
        return []

    scores = [(doc, cosine(q_emb, emb)) for doc, emb in zip(schema_docs, schema_embeddings)]
    scores.sort(key=lambda x: x[1], reverse=True)
    return [doc for doc, _ in scores[:top_k]]
