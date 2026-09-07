# course-custom-ner retraining pipeline

Rebuilds the NER model's training data and produces a fine-tuned checkpoint,
targeting two failure modes: entity boundary errors and label(type)
misclassification. See `docs/superpowers/specs/2026-09-07-ner-retraining-design.md`
for the full design rationale.

## Prerequisites

- `DATABASE_URL` reachable (same as the main app's `backend/.env`).
- For `train.py` specifically: a machine with the training-only dependencies
  installed (`pip install -r requirements-training.txt`) and, ideally, a GPU.
  `infer_abbreviations.py` and `generate_ner_dataset.py` only need `psycopg2`
  and `python-dotenv` (already in the main app's `backend/requirements.txt`).

All commands below assume `cd backend/course_custom_ner_model/scripts` first.

## 1. Infer abbreviation candidates

```bash
python infer_abbreviations.py --output ../data/abbreviation_candidates.json
```

Then hand-review the output and save the curated subset to
`../metadata/abbreviation_candidates.reviewed.json` (same JSON shape). See
Task 7 in the implementation plan for the review criteria.

This was already run once against the live DB for Task 7: of the DEPARTMENT
candidates, 88 plausible abbreviations across 63 departments were kept (noise
such as single meaningless characters, algorithm artifacts with stray spaces,
candidates colliding with a different department's abbreviation, and
candidates that happened to collide with an unrelated real Korean word were
discarded). All 7 CATEGORY candidates produced by the live run already exactly
matched the hand-curated `COMMON_ALIASES["CATEGORY"]` entries in
`backend/keyword_extract.py`, so no new CATEGORY entries were added and that
label's reviewed dict is empty. COURSE_NAME candidates are intentionally not
merged into `COMMON_ALIASES` at all (see step 2 below) and that label's
reviewed dict is also empty for now — regenerate it (following the same
per-value review) if you want abbreviated COURSE_NAME values to show up in
the `abbrev_course_only`/`abbrev_dept_category` synthetic templates.

## 2. Generate the synthetic dataset

```bash
python generate_ner_dataset.py \
  --abbreviations-file ../metadata/abbreviation_candidates.reviewed.json \
  --output-dir ../data \
  --seed 42
```

Writes `../data/ner_train.jsonl`, `ner_valid.jsonl`, `ner_test.jsonl`. Re-run
any time to regenerate — nothing under `../data/` is committed to git.

## 3. Train

On a machine with `requirements-training.txt` installed:

```bash
pip install -r requirements-training.txt
python train.py \
  --train-file ../data/ner_train.jsonl \
  --valid-file ../data/ner_valid.jsonl \
  --holdout-file ../metadata/ner_holdout_real.jsonl \
  --labels-file ../models/course-custom-ner/labels.json \
  --output-dir ../trained_model_output
```

Watch the printed "Validation", "Test", and "Holdout (real queries)" seqeval
reports and "confusion counts" at the end. The holdout numbers matter most,
since they're measured on real historical queries the model never trained
on, but the validation/test confusion counts (drawn from `ner_valid.jsonl`
and `ner_test.jsonl`) give a much larger sample to spot systematic
label-pair confusions in. If specific label pairs show up repeatedly in any
of the confusion counts, go back to `generate_ner_dataset.py`'s
`TEMPLATE_CATALOG` and increase the `weight` of the relevant `confusable_*`
templates, then repeat from step 2.

## 4. Swap in the new model

**Back up the current model first:**

```bash
cp -r ../models/course-custom-ner ../models/course-custom-ner.bak-$(date +%Y%m%d)
```

Then copy the new checkpoint over it:

```bash
cp -r ../trained_model_output/final/* ../models/course-custom-ner/
```

Restart the backend (`keyword_extract.py` loads the model once per process
via `get_predictor()`) and spot-check with:

```bash
python predict_ner.py --query "컴퓨터융합학부 3학년 대상 전공(핵심) 과목 알려줘"
```

## 5. (Optional) Re-run the full text-to-sql eval set

If you want to see whether the NER improvement moved the needle on overall
pipeline accuracy, from the repo root:

```bash
python -m backend.eval.run_eval
```

Compare the new overall/category accuracy against the baseline run recorded
in `backend/eval/reports/20260907T073756Z.json` (27.9% / 12 of 43 at the time
this pipeline was built).
