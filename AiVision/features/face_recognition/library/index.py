"""特征字节格式与只在刷新时访问数据库的 NumPy 人员索引。"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass

import numpy as np

from .constants import EMBEDDING_DIM, MODEL_NAME


def photo_signature(pic_uri: str, server_index_code: str) -> str:
    """对照片地址与服务器标识生成稳定签名，用于判定注册资料是否变化。"""
    payload = json.dumps([pic_uri, server_index_code], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def encode_embedding(embedding: np.ndarray) -> bytes:
    """校验有限非零特征向量，并以小端 float32 字节格式持久化。"""
    vector = np.asarray(embedding, dtype="<f4")
    if vector.shape != (EMBEDDING_DIM,) or not np.isfinite(vector).all() or np.linalg.norm(vector) <= 0:
        raise ValueError("人脸特征必须是非零、有限的 512 维向量")
    return vector.tobytes()


def decode_embedding(data: bytes, dimension: int) -> np.ndarray:
    """核对维度和字节长度后解码为独立数组，同时验证向量有效性。"""
    if dimension != EMBEDDING_DIM or len(data) != dimension * 4:
        raise ValueError("人脸特征维度或字节长度错误")
    vector = np.frombuffer(data, dtype="<f4").copy()
    encode_embedding(vector)
    return vector


@dataclass(frozen=True)
class IndexedPerson:
    """与索引矩阵行一一对应的人员资料快照。"""
    person_id: int
    person_name: str | None
    job_no: str | None
    person_code: str | None
    org_index_code: str | None


class FaceIndex:
    """一次刷新整体替换索引；实时比对只读取内存。"""

    def __init__(self):
        """创建空索引和替换锁，使首次刷新前的匹配也有明确结果。"""
        self._lock = threading.Lock()
        self._people: tuple[IndexedPerson, ...] = ()
        self._matrix = np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    def refresh(self) -> int:
        """加载有效模型及照片签名匹配的在用人员，归一化后整体替换只读索引。"""
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

    def require_people(self, person_ids: list[int]) -> None:
        """所选白名单必须具有有效特征；正常加载的空库可以识别为未知人员。"""
        with self._lock:
            available = {person.person_id for person in self._people}
        missing = sorted(set(person_ids) - available)
        if missing:
            identifiers = ",".join(str(person_id) for person_id in missing[:20])
            raise RuntimeError(f"白名单缺少有效人脸特征，共 {len(missing)} 人，人员编号（最多20项）：{identifiers}")

    def match(self, embedding: np.ndarray, threshold: float) -> dict:
        """以归一化向量的余弦相似度选取最佳候选，达到阈值才返回其身份。

        空索引返回未知人员；未达到阈值时仍保留最佳相似度供监控展示，
        但不暴露候选身份字段。输入向量或阈值不合法时抛出 ValueError。
        """
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
