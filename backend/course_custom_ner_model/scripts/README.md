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
  --seed 42 \
  --scale 5
```

Writes `../data/ner_train.jsonl`, `ner_valid.jsonl`, `ner_test.jsonl`. Re-run
any time to regenerate — nothing under `../data/` is committed to git.

`--scale` multiplies every template's record count; the weights in
`TEMPLATE_CATALOG` are per-scale-unit. `--scale 1` produces ~800 records,
which is not enough to train on (see step 3). `--scale 5` gives roughly
2,800 / 700 / 545.

The split is per template, never per record: a template lands wholly in one
split so the model cannot memorise it and inflate the eval scores. Templates
are picked for valid and test by label coverage first — rarest label first —
so all three splits exercise all 16 labels. One gap remains: the entity-free
templates carry no label, so the coverage pass never selects them and they
all end up in train. False positives on entity-free queries are therefore
only measurable on the real-query holdout, not on valid/test.

## 3. Train

On a machine with `requirements-training.txt` installed:

```bash
pip install -r requirements-training.txt
python train.py \
  --train-file ../data/ner_train.jsonl \
  --valid-file ../data/ner_valid.jsonl \
  --holdout-file ../metadata/ner_holdout_real.jsonl \
  --labels-file ../models/course-custom-ner/labels.json \
  --output-dir ../trained_model_output \
  --num-train-epochs 15 \
  --per-device-train-batch-size 8
```

**Watch the step count, not the epoch count.** The label schema has 33
classes and the classifier head starts from random weights, so a few hundred
optimizer steps are not enough: the first run of this pipeline used 391
sentences at batch 32 for 8 epochs — about 104 steps — and the model
collapsed to predicting DEPARTMENT for every entity, scoring 0.00 F1 on
every other label. Aim for a few thousand steps
(`len(train) / batch_size * epochs`).

If you run this on Colab, pass `WANDB_DISABLED=true WANDB_MODE=disabled`.
`TrainingArguments` leaves `report_to` at its default of `"all"`, so a
Colab image that ships wandb will block forever waiting for an API key that
`!python` cannot supply.

Watch the printed "Validation", "Test", and "Holdout (real queries)" seqeval
reports and "confusion counts" at the end. The holdout numbers matter most,
since they're measured on real historical queries the model never trained
on, but the validation/test confusion counts (drawn from `ner_valid.jsonl`
and `ner_test.jsonl`) give a much larger sample to spot systematic
label-pair confusions in. If specific label pairs show up repeatedly in any
of the confusion counts, go back to `generate_ner_dataset.py`'s
`TEMPLATE_CATALOG` and increase the `weight` of the relevant `confusable_*`
templates, then repeat from step 2.

## 3b. Compare the candidate against the deployed model

`train.py` only reports metrics as part of a training run, so use
`eval_checkpoint.py` to score any checkpoint directory on any labeled jsonl
without retraining. Run it on both models before deciding to swap:

```bash
python eval_checkpoint.py --model-dir ../models/course-custom-ner
python eval_checkpoint.py --model-dir ../trained_model_output/final
```

It defaults to the real-query holdout; pass `--data-file` (repeatable) for
other sets. The label schema comes from `<model-dir>/labels.json`.

A raw model score is not the whole picture: `keyword_extract.py` runs
`postprocess_entities()` over the predictions before they reach the SQL
layer, which strips trailing particles and single-character fragments. On
the holdout that moved span-exact F1 from 0.748 to 0.857, so a candidate
whose errors are mostly particle noise will look worse here than it behaves
in production.

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
