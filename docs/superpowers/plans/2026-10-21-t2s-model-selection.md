# Text-to-SQL 모델 선정 (1단계 계획 C/3)

**Goal:** v2 파이프라인(HEAD 687adcb, 후보 1개)을 고정하고 SQL 생성 모델만 바꿔 같은 평가셋(243건)으로 비교해 서비스 모델을 고른다.

**Spec:** `docs/superpowers/specs/2026-10-19-text-to-sql-accuracy-design.md` 2장(모델 선정). 근거: 조사 보고서의 XiYanSQL[9], OmniSQL[14].

## 후보 (원격 Ollama, P100 16GB, Q4_K_M)

| 모델 | Ollama 이름 | 크기 | 출처 |
|---|---|---|---|
| Qwen2.5-Coder-7B-Instruct (현재 기준) | `qwen2.5-coder:7b-instruct` | 4.7GB | Ollama 공식 |
| Qwen2.5-Coder-14B-Instruct | `qwen2.5-coder:14b-instruct` | 약 9GB | Ollama 공식 |
| XiYanSQL-QwenCoder-7B-2504 | `hf.co/mradermacher/XiYanSQL-QwenCoder-7B-2504-GGUF:Q4_K_M` | 4.68GB | HF 커뮤니티 GGUF |
| XiYanSQL-QwenCoder-14B-2504 | `hf.co/mradermacher/XiYanSQL-QwenCoder-14B-2504-GGUF:Q4_K_M` | 8.99GB | HF 커뮤니티 GGUF |
| OmniSQL-7B | `hf.co/mradermacher/OmniSQL-7B-GGUF:Q4_K_M` | 4.68GB | HF 커뮤니티 GGUF |
| text2sql-local (기존 미세조정) | `text2sql-local` | — | 기존 |

## 절차
1. 원격 Ollama에 후보를 pull한다(사용자 승인: 2026-10-21 "다음 순서로 가").
2. 모델별로 4문항 스모크(강의 검색·최다 분반·본인 이력·거부)로 출력 형식(stop, SQL 추출)을 확인한다. 문제가 있으면 모델별 `T2S_STOP` 조정만 허용한다(프롬프트는 고정).
3. `T2S_MODEL=<모델> python -m backend.eval.run_eval --pipeline v2`로 전체 평가. 지표: 실행 정확도, 카테고리별, p50/p95, 거부 정확도.
4. 선정 기준: 실행 정확도 최우선, 동률(±1%p)이면 p95 지연이 짧은 쪽, 거부 정확도 90% 미만은 탈락.
5. 결과를 이 문서 끝에 표로 기록하고 `.env.example`/README에 권장 `T2S_MODEL`을 적는다.

## 주의
- 커뮤니티 GGUF는 원 모델 제작자가 올린 것이 아니다(양자화·채팅 템플릿 차이 가능). 결과에 출처를 함께 적는다.
- 프롬프트·예시는 qwen2.5-coder-7B 기준으로 다듬어졌으므로 다른 모델에 불리할 수 있다.
