# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Quality gate that runs *before* automated Gherkin scenario generation. It evaluates whether a user story + acceptance criteria are good enough to derive a correct, executable Given-When-Then scenario. Specific objective 2 of a Master's thesis (Ingeniería, Universidad del Valle).

## Language split — this is a rule, not a style preference

**Code is English.** Function, variable, constant and class names, comments,
docstrings and test names. Write new code in English.

**These four stay in Spanish. Do not translate them:**

1. **Prompt text** — `EVALUATION_PROMPT_TEMPLATE`, `COMPLEMENTATION_PROMPT_TEMPLATE`,
   `COUPLED_PROMPT_TEMPLATE` and their fragments. The `{placeholders}` inside them
   are part of the prompt, so the matching `.format()` keywords are Spanish too.
2. **Rubric content** — the `definicion`, `label` and `fuente` of every `Criterion`.
   It is prompt payload, not code.
3. **Verdict values** — `"aprobado"`, `"rechazo_redaccion"`, `"rechazo_informacion"`.
   They appear both in the prompt and in the API response. English code comparing
   against Spanish strings is intentional.
4. **The API contract** — paths (`/api/evaluar`), request fields (`historia`,
   `criterios`) and every response field (`veredicto`, `resumen`, `complementacion`,
   `preguntas_po`, `gate2_historia`, `gate2_criterios`, `detenido_en`, `modo`,
   `llamadas_modelo`, `latencias_ms`, `modelo_desobedecio`, and the `label`/`passed`/
   `evidencia`/`estado`/`tipo` keys inside them). `app/static/index.html` consumes
   them.

User-facing diagnostic messages also stay in Spanish: they render in the Spanish
UI and `ARRANQUE.md` quotes them verbatim in its troubleshooting section.

Where English code builds the Spanish response, leave the marker comment
`# API contract stays in Spanish: consumed by the frontend`.

## Traceability comments

Every rule, criterion, threshold or non-obvious decision carries a one-line
comment, 60 characters max, label style, saying where it comes from. Two marks
are not direct citations and go in capitals:

```
# QUS (Lucassen 2016), as-is
# QUS ADAPTED: cross-story in QUS, internal here
# OURS: no source; comes from the pytest-bdd target
```

## Commands

```bash
# Run (Docker, hot-reloads app/ without rebuild)
cp .env.example .env      # then put your key in it
docker compose up --build         # http://localhost:8000  ·  interactive docs at /docs

# Run (local, no Docker)
pip install -r requirements.txt
uvicorn app.main:app --reload

# Tests (the deterministic parts only, no model needed)
python -m pytest tests/ -q
python -m pytest tests/test_gate1.py::test_detects_missing_role -q   # single test
docker compose run --rm evaluador python -m pytest tests/ -q

# Pre-demo smoke check: gate 1 + config + one real model call
docker compose exec evaluador python check.py
```

## Architecture

Two gates in series; a request is `POST /api/evaluar {"historia": "...", "criterios": "..."}`:

```
input ─▶ Gate 1 (deterministic, regex) ─▶ Gate 2 (LLM over rubric) ─▶ verdict
      └▶ smells.py (deterministic, spaCy POS) ─▶ signal only, never blocks
```

- **`app/gate1.py`** — structural regex checks, no model, always runs, costs nothing. Only `well_formed` and `ac_present` are *hard* fails that block (`blocks()`); everything else (e.g. `atomic_hint`) passes through to Gate 2 as a signal instead of stopping the flow. Follows Perfect Recall Condition: when in doubt, report. Patterns cover Spanish *and* English.
- **`app/gate2.py`** — semantic evaluation, **two model calls**. `evaluate_quality()` diagnoses only; `propose_complementation()` proposes only, and runs only when the verdict calls for it. `run_gate2()` orchestrates them and decides nothing itself. All model calls go through **litellm** (`temperature=0`) via `_invoke_model()`; the app never knows which provider it's talking to. Returns strict JSON parsed by `_extract_json`.
- **`app/rubric.py`** — the single source of truth for the rubric. The three Gate 2 prompts (`build_evaluation_prompt`, `build_complementation_prompt`, `build_coupled_prompt`) are built from the `Criterion` dataclasses here. **Change rubric criteria here, not in prompt strings elsewhere.**
- **`app/main.py`** — HTTP layer + FastAPI. If Gate 1 blocks, it short-circuits to `rechazo_redaccion` and the model is never invoked.
- **`app/smells.py`** — deterministic requirement-smell detector (Zakeri-Nasrabadi & Parsa, 2024), spaCy `es_core_news_sm`, no model and no network. One unit per sentence (story + each criterion), never averaged. Clarity is eq. 3 of the paper; T(R) and alpha do not apply to one-sentence units. Findings are **signal, never a gate** — the paper reports precision 0.42. Also holds `content_diff()`, the deterministic check of the non-over-generation rule.
- **`app/static/index.html`** — UI, no build step.

### Five things that are load-bearing, not incidental

1. **Provider is swapped via `.env`, not code** — this is a *methodological* requirement of the thesis (same rubric across models), not a convenience. Set `LLM_MODEL=proveedor/modelo` (e.g. `gemini/gemini-2.5-flash`, `anthropic/claude-sonnet-4-5`, `ollama/llama3.1`) plus the matching `*_API_KEY`. `API_KEY_BY_PROVIDER` in `gate2.py` maps provider→env var for pre-flight diagnostics.
2. **The verdict is derived in Python, never by the model** — `derive_verdict_from_failures()` applies the priority rule (any `informacion` failure wins), and `_drop_output_not_matching_verdict()` enforces the exclusion between a rewrite and questions for the PO. Both were the model's job before and it got them wrong; `modelo_desobedecio` in the response counts how often it still tries.
3. **`MODO_ACOPLADO` is an experiment setting, not dead code** — `false` (default) runs the two separate calls. `true` restores the original single-call prompt so both designs stay comparable under the same rubric. The env var name stays Spanish because it is documented in `.env.example` and `ARRANQUE.md`.
4. **Smells never decide anything** — they are reported next to the verdict, never folded into it, and no threshold anywhere reads them. `SMELLS_EN_PROMPT` (default `false`) controls whether they reach the *evaluation* prompt; they never reach the complementation one. `REEVALUAR_COMPLEMENTACION` (default `false`) re-scores the rewrite for measurement and costs one extra model call.

5. **The `redaccion` vs `informacion` verdict split is the core design.** `rechazo_redaccion` = info is present but poorly written → rewrite using *only* existing text (no over-generation). `rechazo_informacion` = business knowledge is missing → **stop**, return questions for the Product Owner, never invent. The JSON schema in the prompt structurally forbids the model from returning a well-formed answer while inventing an acceptance criterion. Preserve this constraint when editing the prompt.

## Notes

- Unit tests cover the deterministic parts only: Gate 1 (`tests/test_gate1.py`), the verdict/exclusion rules (`tests/test_verdict.py`), and the smell detector (`tests/test_smells.py`, `tests/test_content_diff.py`). Gate 2's model behavior is exercised manually via `check.py`.
- `docker-compose.yml` mounts only `./app`, so `docker compose exec … pytest` or `… check.py` runs the copy baked into the image. Rebuild, or mount `tests/` explicitly, after editing them.
- `app/smells.py` needs the spaCy model `es_core_news_sm`; the Dockerfile downloads it at build time. Outside Docker: `python -m spacy download es_core_news_sm`.
- No persistence — each evaluation is independent.
- Server resolves human-readable `label`s from `rubric.LABELS` so the rubric stays the single source of truth.
