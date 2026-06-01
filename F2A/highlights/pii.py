"""PII 마스킹.

LLM 호출 전/DB 저장 전에 리뷰 본문을 마스킹한다.
한국어 사용자 베이스 기준으로 한국 전화번호/주민번호 + 일반 이메일을 우선 처리.

마스킹 토큰:
  - 전화번호  → [PHONE]
  - 이메일    → [EMAIL]
  - 주민번호  → [RRN]
"""
from __future__ import annotations

import re

# 한국 휴대전화: 010/011/016/017/018/019 + 7~8자리 (구분자 -, 공백, 없음)
_PHONE_RE = re.compile(r"\b01[016789](?:[-\s]?\d{3,4}){1}[-\s]?\d{4}\b")

# 일반 이메일 (RFC 단순화)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# 주민등록번호: 6자리-7자리 (뒷자리 첫숫자 1~4)
_RRN_RE = re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b")


def mask_pii(text: str) -> str:
    """본문에서 전화/이메일/주민번호를 토큰으로 치환.

    순서: RRN → PHONE → EMAIL.
    (RRN을 먼저 처리해야 전화번호 패턴과 혼동하지 않음)
    """
    if not text:
        return text
    text = _RRN_RE.sub("[RRN]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    text = _EMAIL_RE.sub("[EMAIL]", text)
    return text
