schema_docs = [
    "v_course_info: 통합된 강의 개설, 시간, 학과, 교수, 과목 상세 정보",
    "course_prerequisite: 선수과목",
    "enrollment: 수강 정보",
    "required_subject: 이수요건",
    "student: 학생 정보",
]

def _tokenize(text: str) -> set[str]:
    return {tok for tok in text.lower().replace(":", " ").replace(",", " ").split() if tok}


def retrieve_schema(query, top_k=2):
    q_tokens = _tokenize(query)
    if not q_tokens:
        return schema_docs[:top_k]

    scores = []
    for doc in schema_docs:
        d_tokens = _tokenize(doc)
        overlap = len(q_tokens.intersection(d_tokens))
        scores.append((doc, overlap))
    scores.sort(key=lambda x: x[1], reverse=True)
    selected = [doc for doc, score in scores[:top_k] if score > 0]
    return selected if selected else schema_docs[:top_k]
