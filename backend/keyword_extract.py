import argparse
import json
import os
import re
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg2
import torch
from dotenv import load_dotenv
from psycopg2 import sql
from rapidfuzz import fuzz, process as fuzz_process
from transformers import AutoModelForTokenClassification, AutoTokenizer


BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "course_custom_ner_model" / "models" / "course-custom-ner"
REFERENCE_LIMIT = int(os.getenv("KEYWORD_REFERENCE_LIMIT", "20000"))
DEFAULT_MIN_SCORE = float(os.getenv("KEYWORD_CORRECTION_MIN_SCORE", "78"))
MASKABLE_ENTITY_LABELS = {
    "CATEGORY",
    "COURSE_NAME",
    "DAY",
    "DEPARTMENT",
    "TIME",
}

## NER label이 DB의 어느 테이블, 컬럼과 매핑되는지 정의.
## 교정된 값이 DB에 존재하는지 확인하기 위함.
## 예) "COURSE_NAME" 엔티티는 "subject" 테이블의 "subject_name" 컬럼과 매핑되어, 교정된 과목명이 실제로 존재하는지 확인할 때 참조됨.
ENTITY_REFERENCE_MAP = {
    "CATEGORY": ("v_course_info", "category"),
    "COURSE_NAME": ("v_course_info", "subject_name"),
    "DEPARTMENT": ("v_course_info", "dept_name"),
    "CLASS_MODE": ("v_course_info", "class_mode"),
    "EVAL_TYPE": ("v_course_info", "eval_type"),
    "GRADE_METHOD": ("v_course_info", "grading_method"),
    "PROFESSOR": ("v_course_info", "professor"),
}

## 최소 유사도 기준. 라벨별로 다르게 적용하여 과도한 교정을 방지.
## (예: 교수명은 유사도가 높아야 교정, 과목명은 조금 낮아도 교정)
## DEFAULT 값은 78
LABEL_MIN_SCORES = {
    "COURSE_NAME": 70.0,
    "DEPARTMENT": 74.0,
    "CATEGORY": 74.0,
    "PROFESSOR": 82.0,
}

## fuzzy matching만으로는 교정이 부적절한 경우가 많아, 자주 발생하는 오탈자나 약어에 대해서는 별도의 허용값을 정의하여 교정 정확도를 높임.
## 일종의 사전을 정의하는 것
COMMON_ALIASES = {
    "DEPARTMENT": {
        "컴공": ["컴퓨터공학과"],
        "컴융": ["컴퓨터융합학부", "공과대학 컴퓨터융합학부"],
        "컴융부": ["컴퓨터융합학부", "공과대학 컴퓨터융합학부"],
        "인공지능": ["컴퓨터인공지능학부"],
        ## Task 7: reviewed candidates from infer_abbreviations.py against the live DB
        ## (see backend/course_custom_ner_model/metadata/abbreviation_candidates.reviewed.json)
        "컴퓨터인공지": ["공과대학 컴퓨터인공지능학부"],
        "컴퓨터인공지학": ["공과대학 컴퓨터인공지능학부"],
        "지역환토": ["농업생명과학대학 지역환경토목학과"],
        "지역환토학": ["농업생명과학대학 지역환경토목학과"],
        "천문우주과": ["자연과학대학 천문우주과학과"],
        "무역": ["경상대학 무역학과"],
        "무역학": ["경상대학 무역학과"],
        "화공과": ["공과대학 응용화학공학과"],
        "국어교": ["사범대학 국어교육과"],
        "국사": ["인문대학 국사학과"],
        "국사학": ["인문대학 국사학과"],
        "사복지": ["사회과학대학 사회복지학과"],
        "사복지학": ["사회과학대학 사회복지학과"],
        "농생융": ["농업생명과학대학 농생명융합학부"],
        "신소공": ["공과대학 신소재공학과"],
        "식물": ["농업생명과학대학 식물자원학과"],
        "식물학": ["농업생명과학대학 식물자원학과"],
        "소비자": ["생활과학대학 소비자학과"],
        "소비자학": ["생활과학대학 소비자학과"],
        "기교": ["사범대학 기술교육과"],
        "유기재료공": ["공과대학 유기재료공학과"],
        "항공우주공": ["공과대학 항공우주공학과"],
        "지질환과": ["자연과학대학 지질환경과학과"],
        "한문": ["인문대학 한문학과"],
        "중어중문": ["인문대학 중어중문학과"],
        "고고": ["인문대학 고고학과"],
        "고고학": ["인문대학 고고학과"],
        "메카트로닉스공": ["공과대학 메카트로닉스공학과"],
        "영어영문": ["인문대학 영어영문학과"],
        "생환화": ["농업생명과학대학 생물환경화학과"],
        "전자공": ["공과대학 전자공학과"],
        "독어독문": ["인문대학 독어독문학과"],
        "바시기": ["농업생명과학대학 바이오시스템기계공학과"],
        "바시기과": ["농업생명과학대학 바이오시스템기계공학과"],
        "환공": ["공과대학 환경공학과"],
        "산림환자": ["농업생명과학대학 산림환경자원학과"],
        "산림환자학": ["농업생명과학대학 산림환경자원학과"],
        "건공과": ["공과대학 토목공학과"],
        "식품영양": ["생활과학대학 식품영양학과"],
        "식품영양학": ["생활과학대학 식품영양학과"],
        "반도체융": ["자연과학대학 반도체융합학과"],
        "원예": ["농업생명과학대학 원예학과"],
        "원예학": ["농업생명과학대학 원예학과"],
        "일어일문": ["인문대학 일어일문학과"],
        "동자생": ["농업생명과학대학 동물자원생명과학과"],
        "동자생과": ["농업생명과학대학 동물자원생명과학과"],
        "농경제": ["농업생명과학대학 농업경제학과"],
        "농경제과": ["농업생명과학대학 농업경제학과"],
        "에너지공": ["공과대학 에너지공학과"],
        "불어불문": ["인문대학 불어불문학과"],
        "컴퓨터융": ["공과대학 컴퓨터융합학부"],
        "언론정": ["사회과학대학 언론정보학과"],
        "동바시": ["농업생명과학대학 동물바이오시스템과학과"],
        "환소공": ["농업생명과학대학 환경소재공학과"],
        "물리": ["자연과학대학 물리학과"],
        "물리학": ["자연과학대학 물리학과"],
        "언어": ["인문대학 언어학과"],
        "언어학": ["인문대학 언어학과"],
        "응화공": ["공과대학 응용화학공학과"],
        "심리": ["사회과학대학 심리학과"],
        "심리학": ["사회과학대학 심리학과"],
        "스농시기": ["농업생명과학대학 스마트농업시스템기계공학과"],
        "스농시기과": ["농업생명과학대학 스마트농업시스템기계공학과"],
        "생정융": ["생명시스템과학대학 생명정보융합학과"],
        "스포츠과": ["자연과학대학 스포츠과학과"],
        "정치외교": ["사회과학대학 정치외교학과"],
        "정치외교학": ["사회과학대학 정치외교학과"],
        "국어국문": ["인문대학 국어국문학과"],
        "해양환과": ["자연과학대학 해양환경과학과"],
        "자율운항시공": ["공과대학 자율운항시스템공학과"],
        "간호": ["간호대학 간호학과"],
        "간호학": ["간호대학 간호학과"],
        "생화": ["자연과학대학 생화학과"],
        "응생": ["농업생명과학대학 응용생물학과"],
        "응생학": ["농업생명과학대학 응용생물학과"],
        "동자과": ["농업생명과학대학 동물자원과학부"],
        "동자과부": ["농업생명과학대학 동물자원과학부"],
        "경제": ["경상대학 경제학과"],
        "경제과": ["경상대학 경제학과"],
        "의류": ["생활과학대학 의류학과"],
        "의류학": ["생활과학대학 의류학과"],
        "토공": ["공과대학 토목공학과"],
        "식품공": ["농업생명과학대학 식품공학과"],
        "체육교": ["사범대학 체육교육과"],
        "의예과": ["의과대학 의예과"],
        "조소과": ["예술대학 조소과"],
        "행정": ["사회과학대학 행정학부"],
        "행정학": ["사회과학대학 행정학부"],
    },
    "CATEGORY": {
        "전기": ["전공(기초)"],
        "전핵": ["전공(핵심)"],
        "전심": ["전공(심화)"],
        "교소": ["교양(소양)"],
        "교소필": ["교양(소양필수)"],
        "일선": ["일반(선택)"],
        "교균": ["교양(균형)"],
        "교기": ["교양(기초)"],
        "교직": ["교직"]
    },
}

## 한국어 조사 제거를 시도하여 매칭 정확도를 높임. (예: "컴퓨터공학과에서" -> "컴퓨터공학과")
KOREAN_PARTICLES = (
    "으로부터",
    "로부터",
    "에서는",
    "에게서",
    "까지",
    "부터",
    "에서",
    "에게",
    "으로",
    "로",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "와",
    "과",
    "도",
    "만",
)

# Particles that are safe to trim off the END OF A PREDICTED SPAN. This is a
# deliberately smaller list than KOREAN_PARTICLES above, which is only used to
# build fuzzy-match variants and can afford false positives. Two filters
# produced it:
#   1. It must never end a real entity. 과(160 labeled entities), 는(28),
#      가(23), 은(10) and 의(1) all do — trimming those would corrupt 학과
#      names, VACANCY phrases and EVAL_TYPE values.
#   2. It must not be mistakable for a word's final syllable. That rules out
#      the remaining single-character particles (이/을/를/와/랑/로/도/만):
#      trimming 이 turned the span '3시 사이' into '3시 사'. Telling those
#      apart from word endings needs morphological analysis we don't have
#      here, and on the holdout they fixed nothing that 에/에서 didn't.
# Ordered longest-first so 에서 wins over 에.
SPAN_TRIM_PARTICLES = (
    "이랑",
    "으로",
    "부터",
    "까지",
    "에서",
    "에",
)

# Trailing junk the tokenizer tends to pull into a span. ')' is deliberately
# absent: 152 labeled entities end with it (e.g. 전공(핵심)).
SPAN_TRIM_CHARS = " \t~,./;:!?-"

# The only legitimately single-character entities in the labeled data are
# weekday abbreviations, all of them DAY.
WEEKDAY_CHARS = frozenset("월화수목금토일")

_predictor_lock = threading.Lock()
_predictor: "CourseNERPredictor | None" = None
_references_lock = threading.Lock()
_references: dict[str, list[str]] | None = None


def _load_env() -> None:
    load_dotenv()
    load_dotenv(BASE_DIR / ".env", override=False)


def build_postgres_dsn() -> str:
    _load_env()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url

    user = os.getenv("POSTGRES_USER", )
    password = os.getenv("POSTGRES_PASSWORD", )
    host = os.getenv("POSTGRES_HOST", )
    port = os.getenv("POSTGRES_PORT", )
    database = os.getenv("POSTGRES_DB", )
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def fetch_distinct_values(conn, table: str, column: str) -> list[str]:
    stmt = sql.SQL(
        """
        SELECT DISTINCT {column}
        FROM {table}
        WHERE {column} IS NOT NULL AND TRIM(CAST({column} AS TEXT)) <> ''
        ORDER BY {column}
        LIMIT %s
        """
    ).format(
        table=sql.Identifier(table),
        column=sql.Identifier(column),
    )
    with conn.cursor() as cur:
        cur.execute(stmt, (REFERENCE_LIMIT,))
        return [str(row[0]).strip() for row in cur.fetchall() if row[0]]


def load_reference_values(force: bool = False) -> dict[str, list[str]]:
    global _references

    with _references_lock:
        if _references is not None and not force:
            return _references

        references: dict[str, list[str]] = {}
        try:
            with psycopg2.connect(build_postgres_dsn()) as conn:
                for label, (table, column) in ENTITY_REFERENCE_MAP.items():
                    try:
                        values = fetch_distinct_values(conn, table, column)
                    except Exception:
                        values = []
                    
                    if label == "CATEGORY":
                        for gen_cat in ["전공", "교양"]:
                            if gen_cat not in values:
                                values.append(gen_cat)
                    
                    references[label] = _dedupe(values)
        except Exception:
            references = {label: [] for label in ENTITY_REFERENCE_MAP}

        _references = references
        return _references


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = normalize_for_match(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def slot_key(label: str) -> str:
    return label.lower()


class CourseNERPredictor:
    def __init__(self, model_dir: str | Path = MODEL_DIR, max_length: int = 128):
        self.model_dir = Path(model_dir)
        self.max_length = max_length
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir)
        self.model = AutoModelForTokenClassification.from_pretrained(self.model_dir).to(self.device)
        self.model.eval()

        with open(self.model_dir / "labels.json", "r", encoding="utf-8") as file:
            label_data = json.load(file)

        self.id_to_label = {
            int(key): value
            for key, value in label_data["id_to_label"].items()
        }

    @torch.no_grad()
    def extract(self, text: str) -> list[dict[str, Any]]:
        encoded = self.tokenizer(
            text,
            return_tensors="pt",
            return_offsets_mapping=True,
            truncation=True,
            max_length=self.max_length,
        )

        offsets = encoded.pop("offset_mapping")[0].tolist()
        encoded = {key: value.to(self.device) for key, value in encoded.items()}

        outputs = self.model(**encoded)
        probs = torch.softmax(outputs.logits[0], dim=-1)
        pred_ids = torch.argmax(probs, dim=-1).tolist()
        pred_scores = torch.max(probs, dim=-1).values.tolist()

        token_predictions = []
        for pred_id, score, (start, end) in zip(pred_ids, pred_scores, offsets):
            if start == end:
                continue
            token_predictions.append(
                {
                    "start": start,
                    "end": end,
                    "label": self.id_to_label[pred_id],
                    "score": float(score),
                }
            )

        return self._merge_bio(text, token_predictions)

    def _merge_bio(self, text: str, token_predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        entities = []
        current = None

        for token in token_predictions:
            label = token["label"]
            if label == "O":
                if current:
                    entities.append(current)
                    current = None
                continue

            if "-" not in label:
                continue

            prefix, entity_type = label.split("-", 1)
            if prefix == "B" or current is None or current["label"] != entity_type:
                if current:
                    entities.append(current)
                current = {
                    "label": entity_type,
                    "start": token["start"],
                    "end": token["end"],
                    "scores": [token["score"]],
                }
                continue

            current["end"] = token["end"]
            current["scores"].append(token["score"])

        if current:
            entities.append(current)

        result = []
        for entity in entities:
            start = entity["start"]
            end = entity["end"]
            avg_score = sum(entity["scores"]) / len(entity["scores"])
            result.append(
                {
                    "text": text[start:end],
                    "label": entity["label"],
                    "start": start,
                    "end": end,
                    "score": round(avg_score, 4),
                }
            )

        return result


def get_predictor(model_dir: str | Path = MODEL_DIR, max_length: int = 128) -> CourseNERPredictor:
    global _predictor

    with _predictor_lock:
        if _predictor is None:
            _predictor = CourseNERPredictor(model_dir=model_dir, max_length=max_length)
        return _predictor


def build_slots(entities: list[dict[str, Any]], text_key: str = "text") -> dict[str, list[str]]:
    slots: OrderedDict[str, list[str]] = OrderedDict()
    for entity in entities:
        key = slot_key(entity["label"])
        slots.setdefault(key, [])

        value = entity.get(text_key) or entity["text"]
        if value not in slots[key]:
            slots[key].append(value)

    return dict(slots)


def normalize_for_match(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[\s\-_./(){}\[\],:;\"'`~!?]+", "", normalized)
    return normalized


def strip_korean_particle(value: str) -> str:
    stripped = value.strip()
    for particle in KOREAN_PARTICLES:
        if stripped.endswith(particle) and len(stripped) > len(particle) + 1:
            return stripped[: -len(particle)]
    return stripped


def trim_entity_span(text: str, start: int, end: int) -> tuple[int, int]:
    while end > start and text[end - 1] in SPAN_TRIM_CHARS:
        end -= 1
    while start < end and text[start] in SPAN_TRIM_CHARS:
        start += 1

    span = text[start:end]
    for particle in SPAN_TRIM_PARTICLES:
        if span.endswith(particle) and len(span) - len(particle) >= 2:
            end -= len(particle)
            break

    while end > start and text[end - 1] in SPAN_TRIM_CHARS:
        end -= 1

    return start, end


def is_noise_span(span: str, label: str) -> bool:
    if not span:
        return True
    if span in SPAN_TRIM_PARTICLES:
        return True
    if len(span) == 1:
        return not (label == "DAY" and span in WEEKDAY_CHARS)
    return False


def postprocess_entities(entities: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Drop tokenizer artifacts and trailing particles from predicted spans.

    The model over-predicts: on the real-query holdout its recall (0.83) runs
    well ahead of its precision (0.68), and most of the gap is single-character
    fragments and particles tagged as entities. Left in place they become bogus
    SQL filters, since correct_ner_entities() never drops an entity.
    """
    cleaned: list[dict[str, Any]] = []

    for entity in entities:
        start, end = trim_entity_span(text, int(entity["start"]), int(entity["end"]))
        span = text[start:end]

        if is_noise_span(span, entity["label"]):
            continue

        cleaned.append({**entity, "text": span, "start": start, "end": end})

    return cleaned


def _squeeze_whitespace(value: str) -> str:
    return re.sub(r"\s+", "", value)


def locate_normalized_span(text: str, target: str) -> tuple[int, int] | None:
    """Shortest character range in `text` that normalizes to `target`.

    Used to replace only the part of an over-wide entity span that the DB value
    actually accounts for. Returns None when no range matches.
    """
    needle = normalize_for_match(target)
    if not needle:
        return None

    best: tuple[int, int] | None = None
    for start in range(len(text)):
        for end in range(start + 1, len(text) + 1):
            if normalize_for_match(text[start:end]) != needle:
                continue
            if best is None or (end - start) < (best[1] - best[0]):
                best = (start, end)
            break

    return best


def is_sequential_match(query: str, target: str) -> bool:
    """
    Checks if query characters appear in target in the same order.
    Example: '컴공' matches '컴퓨터공학과'
    """
    if not query:
        return True
    
    it = iter(target)
    return all(c in it for c in query)


def make_match_queries(entity_text: str, label: str) -> list[str]:
    raw = entity_text.strip()
    compact = normalize_for_match(raw)
    particle_stripped = strip_korean_particle(raw)

    variants = [raw, particle_stripped, compact]
    
    # 강의/과목 등의 접미사가 붙은 경우를 제거하여 추가 변형 생성
    if label == "CATEGORY":
        for suffix in ["과목", "강의", "수업"]:
            if raw.endswith(suffix) and len(raw) > len(suffix):
                stripped = raw[:-len(suffix)].strip()
                variants.extend([stripped, normalize_for_match(stripped)])

    aliases = COMMON_ALIASES.get(label, {})
    
    alias_values = []
    for variant in variants:
        if variant in aliases:
            alias_values.extend(aliases[variant])
        elif variant.lower() in aliases:
            alias_values.extend(aliases[variant.lower()])

    variants.extend(alias_values)

    cleaned: list[str] = []
    for variant in variants:
        variant = variant.strip()
        if variant and variant not in cleaned:
            cleaned.append(variant)
    return cleaned


@dataclass
class MatchResult:
    text: str | None
    score: float
    query: str


def find_best_db_match(entity_text: str, candidates: list[str], label: str) -> MatchResult:
    if not entity_text or not candidates:
        return MatchResult(None, 0.0, entity_text)

    candidate_by_key = {normalize_for_match(candidate): candidate for candidate in candidates}
    best = MatchResult(None, 0.0, entity_text)

    for query in make_match_queries(entity_text, label):
        norm_query = normalize_for_match(query)
        
        # 1. Exact Match
        exact = candidate_by_key.get(norm_query)
        if exact:
            return MatchResult(exact, 100.0, query)

        # 2. Sequential Match check (especially for short abbreviations)
        # We check candidates to see if they contain the query characters in sequence.
        if len(norm_query) >= 2:
            seq_matches = []
            for norm_cand, original_cand in candidate_by_key.items():
                if is_sequential_match(norm_query, norm_cand):
                    fuzz_score = fuzz.WRatio(norm_query, norm_cand)
                    seq_matches.append((original_cand, fuzz_score, len(norm_cand)))
            
            if seq_matches:
                # Sort by fuzz score desc, then by length asc
                seq_matches.sort(key=lambda x: (-x[1], x[2]))
                best_cand, best_fuzz, _ = seq_matches[0]
                seq_score = max(best_fuzz, 80.0)
                if seq_score > best.score:
                    best = MatchResult(best_cand, seq_score, query)

        # 3. Standard Fuzzy Matching
        match = fuzz_process.extractOne(
            query,
            candidates,
            scorer=fuzz.WRatio,
            processor=normalize_for_match,
        )
        if match:
            matched_text, score, _ = match
            if float(score) > best.score:
                best = MatchResult(matched_text, float(score), query)

    return best


def should_apply_match(entity: dict[str, Any], match: MatchResult) -> bool:
    if not match.text:
        return False

    label = entity["label"]
    min_score = LABEL_MIN_SCORES.get(label, DEFAULT_MIN_SCORE)
    if match.score < min_score:
        return False

    source = normalize_for_match(entity["text"])
    target = normalize_for_match(match.text)
    if not source or not target:
        return False

    if source == target:
        # Normalising already made these equal, so they differ only in
        # whitespace, punctuation or case. A punctuation or case difference is
        # worth fixing ('전공핵심' -> '전공(핵심)', 'grade' -> 'GRADE'), but
        # rewriting purely for spacing ('컴퓨터프로그래밍3' ->
        # '컴퓨터프로그래밍 3') tells the DB nothing new while changing what
        # the LLM sees, which cost a prerequisite case in the eval set.
        return _squeeze_whitespace(entity["text"]) != _squeeze_whitespace(match.text)

    # Very short spans are easy to over-correct unless they are aliases or strong matches.
    if len(source) <= 2 and match.score < 95:
        aliases = COMMON_ALIASES.get(label, {})
        return source in aliases

    return True


def correct_ner_entities(
    entities: list[dict[str, Any]],
    references: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    references = references if references is not None else load_reference_values()
    corrected_entities = []

    for entity in entities:
        label = entity["label"]
        candidates = references.get(label, [])
        match = find_best_db_match(entity["text"], candidates, label)
        apply_match = should_apply_match(entity, match)
        corrected_text = match.text if apply_match and match.text else entity["text"]

        # Replace only the slice of the span the matched value accounts for.
        # A boundary error like '데이터베이스 관련' used to have '관련' deleted
        # along with the rest of the span. Offsets are optional: this is also
        # called with bare {text, label} dicts.
        span_offsets: dict[str, int] = {}
        if apply_match and entity.get("start") is not None:
            covered = locate_normalized_span(entity["text"], corrected_text)
            if covered:
                span_offsets = {
                    "corrected_start": int(entity["start"]) + covered[0],
                    "corrected_end": int(entity["start"]) + covered[1],
                }

        corrected_entities.append(
            {
                **entity,
                **span_offsets,
                "corrected_text": corrected_text,
                "matched_table": ENTITY_REFERENCE_MAP.get(label, (None, None))[0],
                "matched_column": ENTITY_REFERENCE_MAP.get(label, (None, None))[1],
                "similarity": round(match.score, 2) if match.text else None,
                "correction_applied": corrected_text != entity["text"],
            }
        )

    return corrected_entities


def build_corrected_query(query: str, corrected_entities: list[dict[str, Any]]) -> str:
    corrected_query = query
    used_ranges: list[tuple[int, int]] = []

    for entity in sorted(corrected_entities, key=lambda item: item["start"], reverse=True):
        start = int(entity["start"])
        end = int(entity["end"])
        if any(not (end <= used_start or start >= used_end) for used_start, used_end in used_ranges):
            continue

        replace_start = int(entity.get("corrected_start", start))
        replace_end = int(entity.get("corrected_end", end))
        corrected_text = entity.get("corrected_text", entity["text"])
        corrected_query = corrected_query[:replace_start] + corrected_text + corrected_query[replace_end:]
        used_ranges.append((start, end))

    return corrected_query


def build_masked_query(query: str, entities: list[dict[str, Any]]) -> str:
    masked_query = query
    used_ranges: list[tuple[int, int]] = []

    for entity in sorted(entities, key=lambda item: item["start"], reverse=True):
        label = entity.get("label")
        if label not in MASKABLE_ENTITY_LABELS:
            continue

        start = int(entity["start"])
        end = int(entity["end"])
        if any(not (end <= used_start or start >= used_end) for used_start, used_end in used_ranges):
            continue

        masked_query = masked_query[:start] + f"<{label}>" + masked_query[end:]
        used_ranges.append((start, end))

    return masked_query


def _ensure_utf8_console() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if not stream or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def log_ner_masking(query: str, entities: list[dict[str, Any]], masked_query: str) -> None:
    _ensure_utf8_console()
    payload = {
        "query": query,
        "entities": [
            {
                "text": entity.get("text"),
                "label": entity.get("label"),
                "start": entity.get("start"),
                "end": entity.get("end"),
                "score": entity.get("score"),
            }
            for entity in entities
        ],
        "masked_query": masked_query,
    }
    print(f"NER masking: {json.dumps(payload, ensure_ascii=False)}", flush=True)


def preprocess_query(
    query: str,
    model_dir: str | Path = MODEL_DIR,
    max_length: int = 128,
    fail_open: bool = False,
) -> dict[str, Any]:
    try:
        predictor = get_predictor(model_dir=model_dir, max_length=max_length)
        references = load_reference_values()
        entities = postprocess_entities(predictor.extract(query), query)
        corrected_entities = correct_ner_entities(entities, references)
        corrected_query = build_corrected_query(query, corrected_entities)
        masked_query = build_masked_query(query, entities)
        log_ner_masking(query, entities, masked_query)
        return {
            "query": query,
            "corrected_query": corrected_query,
            "masked_query": masked_query,
            "changed": corrected_query != query,
            "entities": entities,
            "slots": build_slots(entities),
            "corrected_entities": corrected_entities,
            "corrected_slots": build_slots(corrected_entities, text_key="corrected_text"),
            "error": None,
        }
    except Exception as exc:
        if not fail_open:
            raise
        return {
            "query": query,
            "corrected_query": query,
            "masked_query": query,
            "changed": False,
            "entities": [],
            "slots": {},
            "corrected_entities": [],
            "corrected_slots": {},
            "error": str(exc),
        }


def extract_keywords(query: str, model_dir: str | Path = MODEL_DIR, max_length: int = 128) -> dict[str, Any]:
    return preprocess_query(query=query, model_dir=model_dir, max_length=max_length, fail_open=False)


def warmup_keyword_normalizer() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        predictor = get_predictor()
        references = load_reference_values()
        predictor.extract("컴융 데이터베이스 과목 보여줘")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": True,
            "elapsed_ms": elapsed_ms,
            "device": predictor.device,
            "reference_counts": {
                label: len(values)
                for label, values in references.items()
            },
        }
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "elapsed_ms": elapsed_ms,
            "error": str(exc),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True, help="Natural language query to normalize")
    parser.add_argument("--model_dir", default=str(MODEL_DIR))
    parser.add_argument("--max_length", type=int, default=128)
    parser.add_argument("--json", action="store_true", help="Print full preprocessing result as JSON")
    parser.add_argument("--refresh-references", action="store_true", help="Reload DB reference values")
    args = parser.parse_args()

    if args.refresh_references:
        load_reference_values(force=True)

    result = extract_keywords(
        query=args.query,
        model_dir=args.model_dir,
        max_length=args.max_length,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["corrected_query"])


if __name__ == "__main__":
    main()
