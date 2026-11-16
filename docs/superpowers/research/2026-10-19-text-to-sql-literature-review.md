# Text-to-SQL Accuracy: Literature & Practice Review (as of 2026-10-19)

Scope: techniques applicable to a single-domain Korean course-registration schema (`v_course_info` + 5 tables), local open-weight models only (7B–32B, single 12–24 GB GPU), current pipeline = NER → fuzzy value correction → masked-SQL vector cache → fine-tuned Qwen2.5-Coder-7B (Q4_K_M) → sqlglot → execute → 1 self-fix retry. Bracketed numbers [n] refer to the reference list. Items marked **(unverified)** could not be confirmed against a primary source.

---

## 1. Schema linking, schema representation, value retrieval

- **Schema linking matters less when the schema fits in context.** Maamari et al. ("The Death of Schema Linking?") skip schema linking whenever the full schema fits the context window and reached 71.83% on BIRD; they explicitly say schema linking remains useful for smaller/older models and huge warehouses [1]. Google's "Is Long Context All You Need?" shows long-context models are robust to extra context (example values, hints, docs) and reach 67.41% BIRD-dev with no fine-tuning and no self-consistency [2]. Contextual AI's open local system deliberately avoids schema linking and value retrieval because recall errors propagate, and instead feeds the full mSchema with FK relations and per-column example values [3].
- **Classical schema linking.** RESDSQL ranks schema items with a cross-encoder then decodes an SQL skeleton first (AAAI 2023) [4]. CodeS (1B–15B, SQL-focused continued pre-training) uses schema filtering and value retrieval in the prompt plus bi-directional data augmentation for fast domain adaptation [5]. CHESS uses LSH + keyword extraction to retrieve DB values from millions of rows and prunes schemas to typically <10 columns; works with open models like Llama-3-70B [6]. LitE-SQL (EACL 2026 Findings) trains a contrastive vector-based schema retriever and a small generator with SFT + execution-guided RL, reporting 72.10% BIRD with 2–30x fewer parameters than LLM pipelines [7].
- **Schema representation.** XiYan's **M-Schema** (semi-structured; types, PK/FK, example values) [8]. On the XiYanSQL-QwenCoder-32B-2504 card, M-Schema vs DDL is 67.14% vs 62.26% on BIRD-dev — a ~5-point prompt-format effect on the same weights [9]. Snowflake's Arctic-Text2SQL-R1 team reports switching to the refined OmniSQL prompt alone raised BIRD-dev from 67.9% to 70.5% [10].
- **Value grounding in production.** Snowflake Cortex Analyst runs a semantic search over stored literal values to map user wording to DB values and credits it with a large accuracy gain; it also relies on a curated semantic model and a "Verified Query Repository" of checked question→SQL pairs, claiming >90% SQL accuracy on real use cases (vendor claim) [11][12].

**Takeaway for us:** with ~20 columns + 5 tables the full schema fits easily; schema *filtering* is unnecessary. What matters is (a) M-Schema-style rendering with Korean column descriptions and example values, and (b) value grounding — which our NER + rapidfuzz step already does (CHESS/Cortex-style).

## 2. Candidate generation + selection

- **CHASE-SQL** (Google/Stanford, ICLR 2025): three diverse generators (divide-and-conquer CoT, query-execution-plan CoT, online synthetic few-shot) + a fine-tuned pairwise selector; 73.0% BIRD test [13].
- **XiYan-SQL** (Alibaba): multi-generator ensemble (ICL + SFT generators), refiner, then a fine-tuned selection model; 75.63% BIRD, 89.65% Spider test [8].
- **Contextual AI** (Jul 2025): sample many candidates (temperature 1, varied one-shot examples; up to 1,024), drop failing ones, rank with a Qwen2.5-32B reward model trained on BIRD train (1 positive + 15 hard negatives) combined with Qwen2.5-Coder-32B log-probs; ~73% BIRD-dev; majority vote > random, RM > majority vote; thinking models did not beat non-thinking ones [3].
- **Execution-based self-consistency (majority vote over result sets):** for OmniSQL-7B, voting adds ~1–3 points (BIRD-dev greedy 63.9 → maj@8 66.1, as reported by OmniSQL and reproduced) [14][15]. **GradeSQL** trains outcome reward models (ORMs) on execution-labeled candidates; ORM best-of-N beats majority voting by +2.91 (BIRD) / +0.93 (Spider), best when the ORM is fine-tuned from a SQL-aligned model such as OmniSQL [16]. A 2026 follow-up by the same group exists [15].
- **CSC-SQL** (Findings IJCNLP-AACL 2025): take the two most frequent sampled outputs and feed both to a small *merge-revision* model; generator and reviser both GRPO-trained; 71.72% (7B) / 73.67% (32B) BIRD test; +0.7–5.5 over plain self-consistency on BIRD-dev; 3B/7B checkpoints on HF [17].
- **Alpha-SQL** (ICML 2025): zero-shot MCTS over partial SQL with an LLM action model and self-supervised reward; 69.7% BIRD-dev using a 32B open model, no fine-tuning [18].
- **Agentar-Scale-SQL** (Ant Group, 2025): "orchestrated test-time scaling" = RL-enhanced reasoning + iterative refinement + parallel diverse synthesis with tournament selection; 81.67% BIRD test [19].
- **DIN-SQL** (NeurIPS 2023): decompose into schema linking → query classification → class-specific generation → self-correction; ~+10% over few-shot [20].

Current BIRD leaderboard (fetched 2026-10-19): overall top ≈ 82–83% (GrainSQL, Huawei DataGallery, Tencent SiriusAI-SQL); single-model track led by Google Gemini-SQL2 80.04%; entries at 9B–32B with self-consistency now reach 74–78% (e.g., SiriusAI-SQL-9B 77.08, -27B 77.70, ReToolSQL-31B 78.14) — open-weight status of these entries **(unverified)** [21].

## 3. Self-correction / refinement with execution feedback

- **MAC-SQL** Refiner executes SQL and repairs it using the error; 59.59% BIRD test; also released a 7B SQL-Llama [22]. **ReFoRCE** (Spider 2.0 agent): self-refinement for syntax/dialect errors + majority-vote consensus + iterative column exploration; 35.83 Spider2.0-Snow [23]. **SQL-PaLM** used execution-based self-consistency and cross-paradigm selection by execution feedback (77.3% Spider test-suite) [24].
- **Effect on small models is limited unless trained for it.** LG AI Research's **ReSQL** (Findings ACL 2026) states lightweight models "suffer from frequent execution errors and limited self-correction"; training on self-generated *error-reasoning* data (LoRA) plus retrieving the 3 most similar past error analyses at inference raised 7B–9B models to 81.29% Spider / 53.78% BIRD, above GPT-4 + self-correction; retrieval cost ~100 tokens and <1.2 s [25]. **RetrySQL** (Allegro, AAAI 2026): training on corrupted-then-corrected reasoning steps gives up to +4 overall / +9 on hard queries, but only with full-parameter training — LoRA SFT did not learn from retry data [26]. **SHARE** (ACL 2025) notes execution errors are often too unspecific to localize errors and can induce hallucinated fixes [27].

**Takeaway:** one generic "fix this error" retry on a 7B model mostly fixes syntax/column-name errors; it rarely fixes *semantic* errors (wrong filter, wrong join) because those execute fine. Better: (a) treat "empty result" and "suspicious row count" as soft errors, (b) retrieve similar past failures as in ReSQL, (c) include failure→fix pairs in fine-tuning data.

## 4. Fine-tuning recipes and strongest open checkpoints

**Data synthesis**
- **OmniSQL / SynSQL-2.5M** (Renmin U. + ByteDance, PVLDB 18, 2025): 2.54M samples over 16,583 synthetic DBs, each with CoT; pipeline = synthesize DB → SQL of varying complexity → back-translate to NL in multiple styles → CoT; models at 7B/14B/32B, Apache-2.0 [14].
- **SENSE** (ACL 2024): strong-LLM synthetic data + weak-LLM *error* data used for preference learning (DPO) [28].
- Arctic-Text2SQL-R1: unfiltered synthetic data *hurt*; execution-filtered synthetic data helped [10].

**RL with execution reward (GRPO)**
- **Arctic-Text2SQL-R1** (Snowflake, Findings ACL 2026): GRPO with a reward that is only "does it execute / is the result correct"; finer-grained rewards encouraged shortcuts; best result from starting at OmniSQL-32B; BIRD test 68.47% (7B), 70.04% (14B), 71.83% (32B) [10][29].
- **Reasoning-SQL** (Google/Stanford, COLM 2025): GRPO with partial rewards (schema-linking, n-gram, syntax, AI feedback); 14B beats o3-mini by ~4% on BIRD [30].
- **SQL-R1** (IDEA, NeurIPS 2025): RL with composite reward, studies cold-start and synthetic data; 88.6% Spider / 67.1% BIRD (7B released) [31].
- **Databricks RLVR** (Sept 2025): prompt/model selection → TAO offline-RL warm start → online RLVR; BIRD private test 73.56% single / 75.68% with self-consistency using only BIRD train data [32][33].

**Strongest open checkpoints at 7B–32B (author-reported)**

| Model | BIRD | Spider test | Notes |
|---|---|---|---|
| OmniSQL-7B / 32B [14][15] | dev 63.9 greedy, 66.1 maj (7B) | 87.9 / 88.9 (7B greedy/maj) | SQLite-centric training; Apache-2.0 |
| XiYanSQL-QwenCoder-7B/14B/32B-2504 [9][34] | dev 62.13 / 65.32 / 67.14 (M-Schema) | 85.97 / 86.82 / 89.20 | Trained for SQLite, PostgreSQL, MySQL |
| Arctic-Text2SQL-R1-7B/14B/32B [10] | test 68.47 / 70.04 / 71.83 | ~88 (ablations) | GRPO on OmniSQL/Qwen2.5-Coder |
| CSC-SQL 7B / 32B [17] | test 71.72 / 73.67 (with sampling + merge) | – | Uses XiYanSQL/Qwen2.5-Coder bases |
| SQL-R1-7B [31] | 67.1 | 88.6 | – |

Qwen3/Qwen3-Coder: no same-protocol comparison with these SQL-specialized checkpoints was found; leaderboard entries now use Qwen3.x-based 27B models (e.g., "EGV-SQL + Qwen3.6-27B" 72.16%) [21] — specifics **(unverified)**.

## 5. Few-shot retrieval and caching

- **DAIL-SQL** (Alibaba, PVLDB 17): select examples by *both* question similarity and SQL-skeleton similarity (mask table/column names and values, Jaccard over skeletons from a preliminary predicted SQL); keep question-SQL pairs, drop example schemas to save tokens; 86.6% Spider test with GPT-4 + voting [35]. This is essentially what our masked-query/masked-SQL cache already stores — we can reuse it as a few-shot pool, not only as a cache.
- **Uber QueryGPT** (Sept 2024): k-NN retrieval of SQL samples + tables within curated "workspaces", intent agent, table agent, column-prune agent; lesson: LLMs are good narrow classifiers; hallucinated columns remain the main failure [36]. **Pinterest** used embeddings of table summaries and *summarized historical queries* for retrieval; first-shot acceptance reportedly 20% → 40% **(primary blog not retrieved; secondary sources only)** [37]. **Snowflake Verified Query Repository**: verified question→SQL pairs retrieved for similar questions [12].
- Contextual AI found that varying the one-shot example across samples is a cheap way to create candidate diversity [3].

## 6. Enterprise / domain practice and non-English

- **Spider 2.0** (ICLR 2025 oral): 632 enterprise workflows, >1,000-column schemas; o1-preview agent solves 21.3% vs 91.2% Spider 1.0 — difficulty is dominated by schema size, dialects, metadata [38]. Our narrow schema is closer to Spider 1.0 / BIRD single-DB difficulty; domain semantics (Korean terms → codes) is our real bottleneck.
- **LinkedIn SQL Bot**: knowledge graph of tables built from metadata, query logs, wikis, code; ranking + generation + automatic error correction; expert review: 53% correct or close on an internal benchmark [39]; Trino Summit 2024 talk lists quality metadata, query validation, chat UX, self-serve customization, ongoing benchmarking [40]. Primary LinkedIn blog **(not retrieved)**.
- **Google Cloud** "Getting AI to write good SQL" (May 2025): context building/table retrieval, LLM-as-judge evaluation, disambiguation, post-processing [41]. **AWS** best-practices post on Text2SQL for enterprise data [42]. **Databricks** RLVR blog: BIRD under-represents real product complexity [33].
- **Korean / non-English:** no 2024–2026 Korean text-to-SQL benchmark was found. Existing resources: LG AI Research's 2023 HCLT paper translating English benchmarks into Korean and evaluating few-shot GPT-3 [43]; a community Llama-3.1-8B fine-tuned on Korean-translated Spider (65.47 EX on Korean Spider) [44]; a small HF dataset `won75/text_to_sql_ko` [45]. FLEX (Ajou University) is Korean-authored but English-benchmark [46]. Implication: Korean-specific gains must come from our own synthetic data and value/terminology grounding, not from public data.

## 7. Evaluation practice

- **Execution accuracy (EX)** has false positives (e.g., empty result = empty result) and false negatives (column order, annotation errors). FLEX (NAACL 2025) re-scored Spider/BIRD leaders and found average −3.15 from false positives and +6.07 from false negatives (v1 figures) [46].
- **Test-suite accuracy** (Zhong, Yu, Klein, EMNLP 2020): run gold vs predicted on a *distilled suite of randomized DBs* covering the gold query's branches; catches coincidental matches; Spider EM-style metrics had 2.5% avg false negatives [47]. LLM-free and cheap for a fixed schema: we can generate a few perturbed copies of our DB.
- **BIRD Mini-Dev** offers PostgreSQL versions plus Soft-F1 (column-order/missing-value tolerant) and R-VES (efficiency) [48].
- **Uber's eval design** is directly reusable: a "vanilla" end-to-end flow and a "decoupled" flow that injects gold intent/tables to isolate generation errors; track per-stage metrics; ignore ~5% run-to-run noise [36].
- With 43 queries, one question = 2.3 points; differences < ~7 points are within noise. Expand to 200–500 by (a) templated paraphrases per intent, (b) LLM back-translation of sampled SQL (OmniSQL-style) with human spot-check, (c) logging real user queries.

---

## Applicability to our setting

Assumptions on VRAM (llama.cpp/Ollama Q4_K_M, approx.): 7B ≈ 5 GB, 14B ≈ 9 GB, 32B ≈ 19–20 GB weights + KV cache; LoRA fine-tuning 7B with QLoRA ≈ 10–16 GB; GRPO RL on 7B realistically needs ≥24 GB with LoRA + vLLM, more for full-parameter.

| # | Technique | Expected benefit (1 Korean domain, local 7–32B) | Impl. cost | VRAM / latency cost |
|---|---|---|---|---|
| 1 | **Bigger eval set + test-suite/Soft-F1 + decoupled eval** [36][46][47][48] | Not accuracy itself, but required to measure anything below ~7 pts; reveals which stage fails | Low–medium (scripts + labeling) | None at runtime |
| 2 | **M-Schema-style prompt: full schema, Korean column descriptions, example/enum values, domain hints** [1][2][3][9][10] | High: 2.5–5 pt prompt-only gains reported; our narrow schema makes full-context free | Low | Few hundred extra tokens; negligible |
| 3 | **Dynamic few-shot from the existing masked cache (DAIL-SQL question + skeleton similarity)** [35][36][12] | High for a narrow domain where most queries are variants of known intents; turns cache misses into near-hits | Low (reuse Redis/KURE index) | +200–600 tokens; ms retrieval |
| 4 | **Execution-based self-consistency (N=4–8, vote on result sets; treat errors/empty results as losers)** [14][15][16][13] | Medium: +1–3 pts on BIRD for 7B; larger on ambiguous queries | Low | N× generation; with Ollama parallel/batched sampling ~1.5–3× latency; no extra VRAM beyond KV |
| 5 | **Upgrade base checkpoint before fine-tuning: XiYanSQL-QwenCoder-7B/14B-2504 (supports PostgreSQL) or Arctic-Text2SQL-R1-7B/14B, then our domain LoRA** [9][10][14] | Medium–high: these beat raw Qwen2.5-Coder-7B by several points on BIRD; 14B fits 12 GB at Q4 | Medium (re-run fine-tune, re-quantize, re-eval) | 7B ≈ 5 GB; 14B ≈ 9 GB; 14B ~2× latency |
| 6 | **Domain synthetic data with execution filtering (OmniSQL-style back-translation from sampled SQL; Korean paraphrase styles; include error→fix pairs)** [14][10][28][25][26] | High for robustness to unseen phrasings; execution filter is essential (unfiltered hurt) | Medium–high (generator + local LLM paraphrasing + filter) | Offline only |
| 7 | Smarter retry: soft errors (empty/huge result), error-specific hints, retrieved past failure analyses (ReSQL) [25][27] | Medium for runtime failures; small models self-correct poorly without it | Low–medium | +1 call only on failure |
| 8 | Selector/ORM or merge-reviser (GradeSQL, CSC-SQL 3B/7B) [16][17] | +1–3 pts over majority vote; needs candidate pool | Medium–high (train ORM on our labeled candidates) | +3–7B model ≈ 2–5 GB, extra pass |
| 9 | GRPO with execution reward (Arctic-R1 recipe) on domain data [10][30][31][32] | Potentially +2–5 pts over SFT, but needs a sizeable, execution-verifiable training set | High (RL infra, ≥24 GB, days) | Offline; runtime unchanged |
| 10 | Schema linking / LSH value retrieval / MCTS (CHESS, RESDSQL, Alpha-SQL) [4][6][18] | Low: schema already tiny; value retrieval already done by NER + rapidfuzz; MCTS too slow | Medium–high | MCTS = many LLM calls |

### Top ~6 by benefit/cost (recommended order)

1. **Grow the eval set to 200+ and add test-suite / decoupled-stage metrics** — prerequisite for trusting any other gain [36][47][48].
2. **M-Schema-style full-schema prompt with Korean descriptions, enum/example values, and domain rules** (prompt-only, both in training and inference) [3][9][10].
3. **DAIL-SQL-style dynamic few-shot from the existing masked cache** (top-k by question + skeleton similarity, instead of only exact-hit caching) [35][12].
4. **Execution-based self-consistency, N≈5, result-set voting** — cheapest test-time scaling; well-documented +1–3 pts [14][15][16].
5. **Swap base to a SQL-specialized checkpoint (XiYanSQL-QwenCoder-14B-2504 for PostgreSQL, or Arctic-Text2SQL-R1-7B/14B) and re-apply domain LoRA** [9][10].
6. **Execution-filtered domain synthetic data incl. Korean paraphrase styles and error→fix pairs** (later, optional GRPO with plain execution reward once data is large enough) [14][10][25].

---

## References

[1] K. Maamari, F. Abubaker, D. Jaroslawicz, A. Mhedhbi. "The Death of Schema Linking? Text-to-SQL in the Age of Well-Reasoned Language Models." NeurIPS 2024 Workshop (TRL). https://arxiv.org/abs/2408.07702
[2] Y. Chung, G. T. Kakkar, Y. Gan, B. Milne, F. Özcan (Google). "Is Long Context All You Need? Leveraging LLM's Extended Context for NL2SQL." PVLDB 18, 2025. https://arxiv.org/abs/2501.12372
[3] S. Agrawal, T. Nguyen (Contextual AI). "Open-Sourcing the Best Local Text-to-SQL System." Blog, 2 Jul 2025. https://contextual.ai/blog/open-sourcing-the-best-local-text-to-sql-system
[4] H. Li, J. Zhang, C. Li, H. Chen. "RESDSQL: Decoupling Schema Linking and Skeleton Parsing for Text-to-SQL." AAAI 2023. https://arxiv.org/abs/2302.05965
[5] H. Li et al. (Renmin U.). "CodeS: Towards Building Open-source Language Models for Text-to-SQL." SIGMOD 2024 / arXiv 2024. https://arxiv.org/abs/2402.16347
[6] S. Talaei, M. Pourreza, Y.-C. Chang, A. Mirhoseini, A. Saberi. "CHESS: Contextual Harnessing for Efficient SQL Synthesis." arXiv 2024. https://arxiv.org/abs/2405.16755
[7] S. Piao, J. Lee, S. Park. "LitE-SQL: A Lightweight and Efficient Text-to-SQL Framework with Vector-based Schema Linking and Execution-Guided Self-Correction." EACL 2026 Findings. https://arxiv.org/abs/2510.09014
[8] Y. Gao, Y. Liu et al. (Alibaba). "XiYan-SQL: A Multi-Generator Ensemble Framework for Text-to-SQL." arXiv 2024. https://arxiv.org/abs/2411.08599
[9] XGenerationLab (Alibaba). XiYanSQL-QwenCoder-32B-2504 model card, Apr 2025. https://huggingface.co/XGenerationLab/XiYanSQL-QwenCoder-32B-2504
[10] Z. Yao, Y. He et al. (Snowflake AI Research). "Smaller Models, Smarter SQL: Arctic-Text2SQL-R1 Tops BIRD and Wins Broadly." Snowflake blog, 29 May 2025. https://www.snowflake.com/en/blog/engineering/arctic-text2sql-r1-sql-generation-benchmark/
[11] Snowflake. "Snowflake Cortex Analyst: Behind the Scenes." Engineering blog. https://www.snowflake.com/en/blog/engineering/snowflake-cortex-analyst-behind-the-scenes/
[12] Snowflake docs. "Cortex Analyst Verified Query Repository." https://docs.snowflake.com/en/user-guide/views-semantic/verified-query-repository
[13] M. Pourreza et al. (Google Cloud, Stanford). "CHASE-SQL: Multi-Path Reasoning and Preference Optimized Candidate Selection in Text-to-SQL." ICLR 2025. https://arxiv.org/abs/2410.01943
[14] H. Li et al. (Renmin U., ByteDance). "OmniSQL: Synthesizing High-quality Text-to-SQL Data at Scale." PVLDB 18, 2025. https://arxiv.org/abs/2503.02240 ; models: https://huggingface.co/seeklhy/OmniSQL-32B
[15] M. Tritto et al. "Test-Time Verification for Text-to-SQL via Outcome Reward Models." arXiv 2026 (reproduces OmniSQL-7B greedy/maj numbers). https://arxiv.org/abs/2606.30851
[16] M. Tritto, G. Farano, D. Di Palma et al. "GradeSQL: Test-Time Inference with Outcome Reward Models for Text-to-SQL Generation from LLMs." arXiv 2025. https://arxiv.org/abs/2509.01308
[17] L. Sheng, S.-S. Xu. "CSC-SQL: Corrective Self-Consistency in Text-to-SQL via Reinforcement Learning." Findings 2025. https://arxiv.org/abs/2505.13271 ; code https://github.com/CycloneBoy/csc_sql
[18] B. Li et al. "Alpha-SQL: Zero-Shot Text-to-SQL using Monte Carlo Tree Search." ICML 2025. https://arxiv.org/abs/2502.17248
[19] P. Wang et al. (Ant Group). "Agentar-Scale-SQL: Advancing Text-to-SQL through Orchestrated Test-Time Scaling." arXiv 2025. https://arxiv.org/abs/2509.24403
[20] M. Pourreza, D. Rafiei. "DIN-SQL: Decomposed In-Context Learning of Text-to-SQL with Self-Correction." NeurIPS 2023. https://arxiv.org/abs/2304.11015
[21] BIRD-bench leaderboard (fetched 2026-10-19). https://bird-bench.github.io/
[22] B. Wang et al. (Beihang, Tencent). "MAC-SQL: A Multi-Agent Collaborative Framework for Text-to-SQL." COLING 2025. https://arxiv.org/abs/2312.11242
[23] M. Deng et al. "ReFoRCE: A Text-to-SQL Agent with Self-Refinement, Consensus Enforcement, and Column Exploration." arXiv 2025. https://arxiv.org/abs/2502.00675
[24] R. Sun, S. Arik et al. (Google). "SQL-PaLM: Improved Large Language Model Adaptation for Text-to-SQL." TMLR 2024. https://arxiv.org/abs/2306.00739
[25] M. Park et al. (LG AI Research). "ReSQL: A Self-Improving Text-to-SQL Framework through Retrieval-Augmented Error Reasoning." Findings ACL 2026; blog 27 Aug 2026. https://www.lgresearch.ai/blog/view?seq=676 ; code https://github.com/minjunp/ReSQL (arXiv ID not found)
[26] A. Rączkowska et al. (Allegro). "RetrySQL: Text-to-SQL Training with Retry Data for Self-Correcting Query Generation." AAAI 2026. https://arxiv.org/abs/2507.02529
[27] "SHARE: An SLM-based Hierarchical Action CorREction Assistant for Text-to-SQL." ACL 2025. https://arxiv.org/abs/2506.00391
[28] J. Yang, B. Hui, M. Yang, J. Yang, J. Lin, C. Zhou. "Synthesizing Text-to-SQL Data from Weak and Strong LLMs" (SENSE). ACL 2024. https://aclanthology.org/2024.acl-long.425
[29] Z. Yao et al. "Arctic-Text2SQL-R1: Simple Rewards, Strong Reasoning in Text-to-SQL." Findings ACL 2026. https://arxiv.org/abs/2505.20315
[30] M. Pourreza et al. "Reasoning-SQL: Reinforcement Learning with SQL Tailored Partial Rewards for Reasoning-Enhanced Text-to-SQL." COLM 2025. https://arxiv.org/abs/2503.23157
[31] P. Ma et al. (IDEA). "SQL-R1: Training Natural Language to SQL Reasoning Model By Reinforcement Learning." NeurIPS 2025. https://arxiv.org/abs/2504.08600
[32] A. Ali, …, J. Frankle, M. Zaharia et al. "A State-of-the-Art SQL Reasoning Model using RLVR." arXiv 2025. https://arxiv.org/abs/2509.21459
[33] Databricks. "The Power of RLVR: Training a Leading SQL Reasoning Model on Databricks." Blog 2025. https://www.databricks.com/blog/power-rlvr-training-leading-sql-reasoning-model-databricks
[34] Modal. "Best Open Source Models for SQL-Generating AI Agents in 2026." Jul 2026 (secondary compilation of model-card numbers). https://modal.com/resources/best-open-source-models-sql-generating-ai-agents
[35] D. Gao et al. (Alibaba). "Text-to-SQL Empowered by Large Language Models: A Benchmark Evaluation" (DAIL-SQL). PVLDB 17, 2024. https://arxiv.org/abs/2308.15363
[36] J. Johnson, C. Busch, A. Khune (Uber). "QueryGPT – Natural Language to SQL Using Generative AI." Uber Engineering blog, 19 Sep 2024. https://www.uber.com/blog/query-gpt/
[37] Pinterest text-to-SQL (secondary summaries; primary Pinterest Engineering post not retrieved): https://www.zenml.io/llmops-database/text-to-sql-system-with-rag-enhanced-table-selection
[38] F. Lei, J. Chen et al. "Spider 2.0: Evaluating Language Models on Real-World Enterprise Text-to-SQL Workflows." ICLR 2025. https://arxiv.org/abs/2411.07763
[39] LinkedIn. "Text-to-SQL for Enterprise Data Analytics." arXiv 2025. https://arxiv.org/abs/2507.14372
[40] LinkedIn, Trino Summit 2024 slides. https://trino.io/assets/blog/trino-summit-2024/trino-summit-2024-linkedin-ai.pdf
[41] P. Jacobsson (Google Cloud). "Getting AI to write good SQL: Text-to-SQL techniques explained." Google Cloud blog, May 2025. https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql
[42] AWS. "Generating value from enterprise data: Best practices for Text2SQL and generative AI." AWS ML Blog. https://aws.amazon.com/blogs/machine-learning/generating-value-from-enterprise-data-best-practices-for-text2sql-and-generative-ai (content not fully read)
[43] LG AI Research, Korean text-to-SQL with GPT-3 few-shot, HCLT 2023 (Korean). https://www.koreascience.kr/article/CFKO202306643316111.pdf
[44] huggingface-KREW. Llama-3.1-8B-Spider-SQL-Ko model card. https://huggingface.co/huggingface-KREW/Llama-3.1-8B-Spider-SQL-Ko
[45] won75/text_to_sql_ko dataset. https://huggingface.co/datasets/won75/text_to_sql_ko
[46] H. Kim et al. (Ajou U.). "FLEX: Expert-level False-Less EXecution Metric for Reliable Text-to-SQL Benchmark." NAACL 2025. https://arxiv.org/abs/2409.19014
[47] R. Zhong, T. Yu, D. Klein. "Semantic Evaluation for Text-to-SQL with Distilled Test Suites." EMNLP 2020. https://arxiv.org/abs/2010.02840
[48] BIRD Mini-Dev (MySQL/PostgreSQL, Soft-F1, R-VES). https://github.com/bird-bench/mini_dev

Unverified / caveats: open-weight status of 2026 leaderboard entries (SiriusAI-SQL, ReToolSQL, EGV-SQL); Pinterest and LinkedIn primary blog posts not retrieved; ReSQL has no confirmed arXiv ID; VRAM figures are standard Q4_K_M estimates, not measured on our hardware.
