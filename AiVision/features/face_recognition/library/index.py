"""特征字节格式与只在刷新时访问数据库的 NumPy 人员索引。"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass

import numpy as np

from .constants import EMBEDDING_DIM, MODEL_NAME


def photo_signature(pic_uri: str, server_index_code: str) -> str:
    payload = json.dumps([pic_uri, server_index_code], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def encode_embedding(embedding: np.ndarray) -> bytes:
    vector = np.asarray(embedding, dtype="<f4")
    if vector.shape != (EMBEDDING_DIM,) or not np.isfinite(vector).all() or np.linalg.norm(vector) <= 0:
        raise ValueError("人脸特征必须是非零、有限的 512 维向量")
    return vector.tobytes()


def decode_embedding(data: bytes, dimension: int) -> np.ndarray:
    if dimension != EMBEDDING_DIM or len(data) != dimension * 4:
        raise ValueError("人脸特征维度或字节长度错误")
    vector = np.frombuffer(data, dtype="<f4").copy()
    encode_embedding(vector)
    return vector


@dataclass(frozen=True)
class IndexedPerson:
    person_id: int
    person_name: str | None
    job_no: str | None
    person_code: str | None
    org_index_code: str | None


class FaceIndex:
    """一次刷新整体替换索引；实时比对只读取内存。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._people: tuple[IndexedPerson, ...] = ()
        self._matrix = np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    def refresh(self) -> int:
        from AiVision.core.db import get_session
        from .orm import FaceEmbedding, FacePerson

        people, vectors = [], []
        with get_session() as session:
            rows = session.query(FacePerson, FaceEmbedding).join(
                FaceEmbedding, FaceEmbedding.person_id == FacePerson.id,
            ).filter(FacePerson.is_active.is_(True), FaceEmbedding.model_name == MODEL_NAME).order_by(FacePerson.id).all()
            for person, embedding in rows:
                if not person.pic_uri or not person.server_index_code:
                    continue
                if embedding.photo_signature != photo_signature(person.pic_uri, person.server_index_code):
                    continue
                vector = decode_embedding(embedding.embedding, embedding.embedding_dim)
                people.append(IndexedPerson(
                    person.id, person.person_name, person.job_no, person.person_code, person.org_index_code,
                ))
                vectors.append(vector / np.linalg.norm(vector))
        matrix = np.asarray(vectors, dtype=np.float32).reshape(-1, EMBEDDING_DIM)
        matrix.setflags(write=False)
        with self._lock:
            self._people, self._matrix = tuple(people), matrix
        return len(people)

    def match(self, embedding: np.ndarray, threshold: float) -> dict:
        if not np.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("相似度阈值必须在 0 到 1 之间")
        vector = decode_embedding(encode_embedding(embedding), EMBEDDING_DIM)
        vector /= np.linalg.norm(vector)
        with self._lock:
            people, matrix = self._people, self._matrix
        if not people:
            return {
                "matched": False, "person_id": None, "person_name": "未知人员", "similarity": 0.0,
                "job_no": None, "person_code": None, "org_index_code": None,
            }
        scores = matrix @ vector
        position = int(np.argmax(scores))
        similarity = float(np.clip(scores[position], -1.0, 1.0))
        matched = similarity >= threshold
        person = people[position]
        return {
            "matched": matched,
            "person_id": person.person_id if matched else None,
            "person_name": (person.person_name or "未命名人员") if matched else "未知人员",
            "job_no": person.job_no if matched else None,
            "person_code": person.person_code if matched else None,
            "org_index_code": person.org_index_code if matched else None,
            "similarity": similarity,
        }
