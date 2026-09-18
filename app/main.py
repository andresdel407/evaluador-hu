"""
User story and acceptance criteria evaluator.
Specific objective 2 — Master's thesis, Universidad del Valle.

The HTTP surface stays in Spanish: paths, request fields and response fields are
consumed by app/static/index.html, which is not touched in this pass.
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import gate1, gate2, smells
from .rubric import AC_CRITERIA, LABELS, STORY_CRITERIA

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Evaluador de historias de usuario",
    description="Compuerta de calidad previa a la generación de escenarios Gherkin.",
    version="0.1.0",
)


class EvaluationRequest(BaseModel):
    # API contract stays in Spanish: consumed by the frontend
    historia: str = Field(..., min_length=1)
    criterios: str = ""


@app.get("/api/salud")
def health():
    """Provider configuration state, so the UI can warn before the first call."""
    problem = gate2.check_configuration()
    # API contract stays in Spanish: consumed by the frontend
    return {
        "estado": "ok" if problem is None else "sin_configurar",
        "modelo": os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash"),
        "temperatura": os.getenv("LLM_TEMPERATURE", "0"),
        "problema": problem,
    }


@app.get("/api/rubrica")
def rubric():
    """The rubric itself, so the UI can show each criterion's definition."""
    # API contract stays in Spanish: consumed by the frontend
    return {
        "historia": [c.__dict__ for c in STORY_CRITERIA],
        "criterios_aceptacion": [c.__dict__ for c in AC_CRITERIA],
    }


# Runs the two gates in series; gate 1 can short-circuit
@app.post("/api/evaluar")
def evaluate(request: EvaluationRequest):
    """Evaluate one story. One response, whatever happened underneath."""
    # --- Gate 1: deterministic -------------------------------------------
    checks = gate1.run_gate1(request.historia, request.criterios)
    gate1_payload = gate1.to_dicts(checks)

    # API contract stays in Spanish: consumed by the frontend
    if gate1.blocks(checks):
        return {
            "gate1": gate1_payload,
            "gate2_historia": [],
            "gate2_criterios": [],
            "veredicto": "rechazo_redaccion",
            "resumen": (
                "El insumo no supera los chequeos estructurales mínimos. "
                "No se invoca el modelo hasta corregirlos."
            ),
            "complementacion": None,
            "preguntas_po": [],
            "detenido_en": "compuerta_1",
            "llamadas_modelo": 0,
            "latencias_ms": [],
            "smells": smells.build_report(request.historia, request.criterios, None),
        }

    # --- Requirement smells: deterministic signal, never a gate -----------
    # Computed before gate 2 because the evaluation prompt may want them.
    original_units = smells.analyze_input(request.historia, request.criterios)
    smells_summary = (
        smells.summarize_for_prompt(original_units) if smells.SMELLS_IN_PROMPT else ""
    )

    # --- Gate 2: semantic -------------------------------------------------
    try:
        result = gate2.run_gate2(
            request.historia,
            request.criterios,
            gate1.summarize_for_prompt(checks),
            smells_summary,
        )
    except gate2.EvaluationError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})

    # Readable labels resolved server-side so the rubric stays the single
    # source of truth.
    for block in ("gate2_historia", "gate2_criterios"):
        for item in result.get(block, []):
            item["label"] = LABELS.get(item.get("id", ""), item.get("id", ""))

    # Before/after measurement. Deterministic and free; the optional second
    # model call already happened inside gate 2.
    report = smells.build_report(
        request.historia, request.criterios, result.get("complementacion")
    )
    report["reevaluacion"] = result.pop("reevaluacion", None)
    result["smells"] = report

    result["gate1"] = gate1_payload
    result["detenido_en"] = None
    return result


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
