"""RAG 서비스: 법령/규칙 벡터 검색 + LLM 응답 생성"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from openai import OpenAI

from app.config import Settings, API_PACKAGE_ROOT

EMBED_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4o-mini"


class RAGService:
    def __init__(self) -> None:
        self._client: OpenAI | None = None
        self._dbs: list[tuple[faiss.Index, list[dict[str, Any]], str]] = []
        self._default_db_dirs: list[str] = []

    def initialize(self, settings: Settings) -> None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
        self._client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.OPENAI_TIMEOUT,
        )
        raw = settings.EHS_DB_DIRS.strip()
        self._default_db_dirs = (
            [p.strip() for p in raw.split(",") if p.strip()] if raw else ["vector_db"]
        )
        self._dbs = self._load_dbs(self._default_db_dirs)

    # ── DB 로딩 ──

    @staticmethod
    def _load_db_one(db_dir: Path) -> tuple[faiss.Index, list[dict[str, Any]], str]:
        idx_path = db_dir / "laws.index"
        meta_path = db_dir / "laws_meta.json"
        if not idx_path.exists() or not meta_path.exists():
            raise FileNotFoundError(f"벡터DB 파일 없음: {idx_path}, {meta_path}")
        index = faiss.read_index(str(idx_path))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return index, meta, db_dir.name

    def _load_dbs(
        self, paths: list[str]
    ) -> list[tuple[faiss.Index, list[dict[str, Any]], str]]:
        out = []
        for p in paths:
            resolved = (API_PACKAGE_ROOT / p).resolve()
            out.append(self._load_db_one(resolved))
        if not out:
            raise RuntimeError("로드할 DB가 없습니다.")
        return out

    # ── 임베딩 ──

    def _embed(self, texts: list[str]) -> np.ndarray:
        if self._client is None:
            raise RuntimeError("OpenAI client not initialized")
        resp = self._client.embeddings.create(model=EMBED_MODEL, input=texts)
        vecs = [d.embedding for d in resp.data]
        return np.array(vecs, dtype="float32")

    # ── 검색 헬퍼 ──

    @staticmethod
    def _guess_level(
        law_name: str | None, article_id: str | None, src_type: str | None
    ) -> str:
        ln = law_name or ""
        aid = article_id or ""
        t = (src_type or "").lower()
        if "별표" in aid or "annex" in t or "table" in t or "ocr" in t:
            return "별표"
        if "규칙" in ln or "기준" in ln:
            return "시행규칙"
        if "시행령" in ln:
            return "시행령"
        if "법" in ln:
            return "법률"
        return "기타"

    @staticmethod
    def _ref_label(h: dict[str, Any]) -> str:
        ln = h.get("law_name") or "법령/규칙"
        aid = h.get("article_id") or "-"
        typ = h.get("type")
        lvl = h.get("level")
        parts = [ln, aid]
        if typ:
            parts.append(typ)
        if lvl:
            parts.append(lvl)
        return " · ".join(p for p in parts if p and p != "-")

    @staticmethod
    def _meta_image_to_url(m: dict[str, Any], static_base: str) -> str | None:
        url = m.get("image_url")
        if isinstance(url, str) and url.strip():
            if url.startswith(("http://", "https://")):
                return url
            return f"{static_base.rstrip('/')}/{url.lstrip('/')}"

        p = m.get("image_path") or m.get("image_rel")
        if not p:
            return None

        raw = Path(p)
        abs_path = raw if raw.is_absolute() else (API_PACKAGE_ROOT / raw).resolve()
        try:
            rel = abs_path.resolve().relative_to(API_PACKAGE_ROOT.resolve())
            return f"{static_base.rstrip('/')}/static/{rel.as_posix()}"
        except Exception:
            p_norm = str(raw).replace("\\", "/").lstrip("./")
            return f"{static_base.rstrip('/')}/static/{p_norm}"

    # ── 검색 ──

    def _search_many(
        self,
        dbs: list[tuple[faiss.Index, list[dict[str, Any]], str]],
        qvec: np.ndarray,
        topk: int,
        static_base: str,
    ) -> list[dict[str, Any]]:
        all_hits: list[dict[str, Any]] = []
        per_k = max(topk, 5)
        for index, meta, label in dbs:
            k = min(per_k, len(meta))
            D, I = index.search(qvec, k)
            seen: set = set()
            for idx, dist in zip(I[0], D[0]):
                if 0 <= idx < len(meta):
                    m = meta[idx]
                    key = (
                        m.get("law_name"),
                        m.get("article_id"),
                        hash((m.get("content") or "")[:256]),
                    )
                    if key in seen:
                        continue
                    seen.add(key)

                    hit: dict[str, Any] = {
                        "law_name": m.get("law_name"),
                        "article_id": m.get("article_id"),
                        "content": m.get("content", ""),
                        "type": m.get("type") or m.get("source_type"),
                        "db": label,
                        "distance": float(dist),
                        "content_format": m.get("content_format"),
                    }
                    hit["level"] = self._guess_level(
                        hit["law_name"], hit["article_id"], hit["type"]
                    )
                    hit["label"] = self._ref_label(hit)

                    img_url = self._meta_image_to_url(m, static_base)
                    if img_url:
                        hit["image_url"] = img_url

                    all_hits.append(hit)

        all_hits.sort(key=lambda x: x["distance"])
        return all_hits[:topk]

    @staticmethod
    def _prioritize_hits(
        hits: list[dict[str, Any]], question: str
    ) -> list[dict[str, Any]]:
        q = question or ""
        q_bias = 0.0
        if any(k in q for k in ["밀폐공간", "별표", "표", "그림"]):
            q_bias = 0.05

        def score(h: dict[str, Any]) -> float:
            s = h["distance"]
            if h.get("level") == "별표":
                s -= 0.15
            elif h.get("level") == "시행규칙":
                s -= 0.06
            if "별표" in (h.get("article_id") or ""):
                s -= 0.05
            return s - q_bias

        return sorted(hits, key=score)

    @staticmethod
    def _build_context(hits: list[dict[str, Any]], max_chars: int) -> str:
        parts: list[str] = []
        total = 0
        for h in hits:
            head = f"[{h['label']}]"
            body = (h.get("content") or "").strip()
            block = f"{head}\n{body}"
            if total + len(block) + 4 > max_chars:
                break
            parts.append(block)
            total += len(block) + 4
        return "\n\n---\n\n".join(parts)

    @staticmethod
    def _choose_mode(user_mode: str, hits: list[dict[str, Any]]) -> str:
        if user_mode != "auto":
            return user_mode
        for h in hits:
            if h.get("level") in ("시행규칙", "별표"):
                return "rule"
        return "law"

    # ── LLM ──

    def _ask_llm(self, question: str, context: str, mode: str) -> str:
        if self._client is None:
            raise RuntimeError("OpenAI client not initialized")

        if mode == "rule":
            system = (
                "당신은 대한민국 최고의 EHS(환경·안전·보건) 규제 전문가다.\n"
                "반드시 제공된 컨텍스트의 근거만 사용해 답하라.\n"
                "근거 우선순위: 법률 > 시행령 > 시행규칙 > 고시/별표(표/그림/OCR).\n"
                "별표·표·그림(OCR)은 수치·치수·한계를 정확히 요약하고, OCR 특성상 오탈자 가능성은 '추가 확인사항'에 명시하라.\n"
                "형식:\n"
                "1) 요약(1~2줄)\n"
                "2) 핵심 근거(각 항목 끝에 [법령명 · 조문]만 표기)\n"
                "3) 해설(현장 적용 팁, 허용기준·치수 등 구체화)\n"
                "4) 추가 확인사항(해석상 주의, 별표/OCR 원문 재확인 포인트).\n"
                "규칙: 컨텍스트에 별표/표/그림 근거가 1개 이상 있으면 '내용이 제공되지 않았다'라고 쓰지 말고, 제공된 범위 안에서 반드시 요약하라."
            )
        else:
            system = (
                "당신은 대한민국 최고의 EHS(환경·안전·보건) 규제 전문가다.\n"
                "반드시 제공된 컨텍스트의 근거만 사용해 답하라.\n"
                "형식: 1) 요약  2) 핵심 근거(법률명·조문·핵심문구)  3) 해설  4) 추가 확인사항.\n"
                "각 근거 끝에는 [법령명 · 조문]만 표기하라."
            )

        user = (
            f"[질문]\n{question}\n\n"
            f"[검색된 근거]\n{context}\n\n"
            "위 근거만을 사용해 답하라. 근거가 부족하면 부족하다고 명시하라."
        )
        resp = self._client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()

    # ── Public API ──

    def health(self) -> dict[str, Any]:
        if self._client is None:
            return {"status": "not-ready", "dbs": []}
        info = [{"label": lbl, "size": len(meta)} for _, meta, lbl in self._dbs]
        return {"status": "ok" if self._dbs else "not-ready", "dbs": info}

    def ask(
        self,
        question: str,
        topk: int,
        mode: str,
        ctx_chars: int,
        dbs: list[str] | None,
        static_base: str,
    ) -> dict[str, Any]:
        used_dbs = self._dbs
        used_labels = [lbl for _, _, lbl in self._dbs]
        if dbs:
            used_dbs = self._load_dbs(dbs)
            used_labels = [lbl for _, _, lbl in used_dbs]

        qvec = self._embed([question])
        hits = self._search_many(used_dbs, qvec, topk=topk, static_base=static_base)
        hits = self._prioritize_hits(hits, question)
        if not hits:
            return {
                "question": question,
                "answer": "검색 결과가 없습니다.",
                "mode": mode,
                "hits": [],
                "used_dbs": used_labels,
            }

        final_mode = self._choose_mode(mode, hits)
        context = self._build_context(hits, max_chars=ctx_chars)
        answer = self._ask_llm(question, context, final_mode)
        return {
            "question": question,
            "answer": answer,
            "mode": final_mode,
            "hits": hits,
            "used_dbs": used_labels,
        }

    def reload(self, dbs: list[str] | None = None) -> dict[str, Any]:
        paths = dbs if dbs else self._default_db_dirs
        self._dbs = self._load_dbs(paths)
        info = [{"label": lbl, "size": len(meta)} for _, meta, lbl in self._dbs]
        return {"status": "reloaded", "dbs": info}


# 싱글톤 인스턴스
rag_service = RAGService()
