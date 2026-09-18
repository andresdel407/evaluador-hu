"""
Gate 2 — semantic evaluation.

Every model interaction goes through litellm, which normalizes the interfaces of
OpenAI, Anthropic, Google, Mistral, Groq, Ollama and others. The provider is
chosen by environment variable; the rest of the code neither knows nor cares.

temperature=0 answers the between-run inconsistency reported by Ronanki et al.
(2024) when using LLMs as quality evaluators.

Evaluation and complementation are two separate calls:

    # OURS: splitting diagnosis from proposal keeps the
    # model from fitting the verdict to the rewrite

It also lets us measure evaluation accuracy and complementation quality apart
from each other, which are two distinct variables of specific objective 2.

Diagnostic messages stay in Spanish: they surface in the Spanish UI and are
quoted verbatim by the troubleshooting section of ARRANQUE.md.
"""

import json
import os
import time

import litellm

from .smells import rewritten_text
from .rubric import (
    build_complementation_prompt,
    build_coupled_prompt,
    build_evaluation_prompt,
)

MODEL = os.getenv("LLM_MODEL", "gemini/gemini-3.5-flash")
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1600"))
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "90"))

# Reasoning models (Gemini 3.x onward, among others) charge reasoning tokens to
# the same MAX_TOKENS budget. With the "minimal" default the model does not
# reason and the whole budget is left for the JSON. Empty = the parameter is not
# sent, so providers with no notion of reasoning never receive it. Env-driven,
# not hardcoded: comparing models under one rubric must cost an env variable.
REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "minimal").strip()

# Alternative endpoint speaking the provider's API: an Ollama on the host, an LM
# Studio, a corporate proxy or a litellm gateway. Empty = not sent, and each
# cloud provider resolves its URL as usual. Env-driven for the same reason as
# MODEL: pointing at another endpoint must cost an env variable, not an edit.
API_BASE = os.getenv("LLM_API_BASE", "").strip()

# Experiment config, not dead code. True = the original prompt, which evaluates
# and complements in a single call. Decoupled by default.
# OURS: coupled vs decoupled is an experiment setting
COUPLED_MODE = os.getenv("MODO_ACOPLADO", "false").strip().lower() in {
    "1",
    "true",
    "si",
    "sí",
    "yes",
}

# Re-runs the evaluation over the rewritten version, to show which criterion
# actually moved. Off by default because it costs an extra model call.
# OURS: shows WHICH criterion changed, not by how much;
# costs one extra model call, hence off by default
REEVALUATE_COMPLEMENTATION = os.getenv(
    "REEVALUAR_COMPLEMENTACION", "false"
).strip().lower() in {"1", "true", "si", "sí", "yes"}

# Sampling seed. Does not guarantee determinism, but with temperature=0 it cuts
# between-run variance on providers that honor it (Ollama, OpenAI); the rest
# discard it via drop_params. Empty = not sent.
SEED = os.getenv("LLM_SEED", "").strip()

litellm.drop_params = True  # tolerate params some provider may not support


class EvaluationError(Exception):
    pass


# Env variable each provider family expects. Used to give a useful diagnosis
# before spending a call that is going to fail anyway.
API_KEY_BY_PROVIDER = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

# Local providers: they do not authenticate, so a missing key is not a problem.
# ollama_chat is the litellm variant hitting /api/chat instead of /api/generate,
# and the one recommended for conversations.
PROVIDERS_WITHOUT_KEY = {"ollama", "ollama_chat"}


# Pre-flight check; saves a call that would fail anyway
def check_configuration() -> str | None:
    """Return a problem message, or None when everything is in order."""
    if "/" not in MODEL:
        return (
            f"LLM_MODEL='{MODEL}' no tiene el formato 'proveedor/modelo' que espera "
            "litellm. Ejemplo válido: gemini/gemini-3.5-flash"
        )

    provider = MODEL.split("/", 1)[0]

    # Ollama runs locally and does not authenticate: no key to check. What can
    # be missing is the endpoint, and that is the likely failure here.
    if provider in PROVIDERS_WITHOUT_KEY:
        if not API_BASE:
            return (
                f"El proveedor '{provider}' es local y no necesita clave, pero sí "
                "necesita saber dónde está el servidor. Define LLM_API_BASE en el "
                ".env; desde un contenedor, el Ollama del host se alcanza en "
                "http://host.docker.internal:11434"
            )
        return None

    env_var = API_KEY_BY_PROVIDER.get(provider)
    if env_var and not os.getenv(env_var):
        return (
            f"Falta la variable {env_var} en el archivo .env, que es la que "
            f"requiere el proveedor '{provider}'. Copia .env.example a .env y "
            "pon tu clave ahí."
        )
    return None


def _object_close_index(text: str, start: int) -> int:
    """Index of the brace closing the object opened at `start`, or -1 if never.

    Counts braces ignoring those inside strings. This used to be an rfind("}"),
    which on a truncated response returns an inner object's brace: the resulting
    slice *looks* complete and json.loads reports it as a syntax error
    ("Expecting ',' delimiter"), hiding that the response was actually cut off.
    """
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of the reply, tolerating markdown fencing."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.lstrip().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    start = cleaned.find("{")
    if start == -1:
        raise EvaluationError("La respuesta del modelo no contiene JSON.")
    end = _object_close_index(cleaned, start)
    if end == -1:
        raise EvaluationError(
            "La respuesta del modelo trae un JSON incompleto: abre el objeto pero "
            f"nunca lo cierra ({len(cleaned)} caracteres recibidos). Casi siempre "
            "significa que la respuesta se cortó antes de terminar; revisa "
            f"LLM_MAX_TOKENS (actual: {MAX_TOKENS})."
        )
    return json.loads(cleaned[start : end + 1])


def _truncation_message(response) -> str:
    """Explain a finish_reason='length' with the numbers needed to act on it."""
    details = getattr(getattr(response, "usage", None), "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None)
    visible = getattr(details, "text_tokens", None)
    parts = []
    if reasoning is not None:
        parts.append(f"{reasoning} tokens de razonamiento")
    if visible is not None:
        parts.append(f"{visible} tokens de texto visible")
    spent = (
        "Gastó " + " y ".join(parts)
        if parts
        else "El proveedor no informó el desglose de tokens"
    )
    effort = REASONING_EFFORT or "(no se envía)"
    return (
        "La respuesta se truncó: el modelo agotó el presupuesto de salida antes de "
        f"cerrar el JSON (finish_reason='length'). {spent}, con "
        f"LLM_MAX_TOKENS={MAX_TOKENS} y LLM_REASONING_EFFORT={effort}. "
        "Los modelos con razonamiento descuentan el razonamiento de ese mismo "
        "presupuesto: sube LLM_MAX_TOKENS o baja LLM_REASONING_EFFORT."
    )


# The single point where the model is actually called
def _invoke_model(content: str) -> tuple[dict, float]:
    """One model invocation. Returns (parsed json, latency in milliseconds)."""
    # Each optional parameter is sent only when it has a value: a provider with
    # no notion of reasoning has no business receiving reasoning_effort, and an
    # empty api_base would break URL resolution for cloud providers.
    extra = {}
    if REASONING_EFFORT:
        extra["reasoning_effort"] = REASONING_EFFORT
    if API_BASE:
        extra["api_base"] = API_BASE
    if SEED:
        extra["seed"] = int(SEED)

    started = time.perf_counter()
    try:
        response = litellm.completion(
            model=MODEL,
            messages=[{"role": "user", "content": content}],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            # The schema is a structural constraint of the gate, not a polite
            # request inside the prompt.
            response_format={"type": "json_object"},
            timeout=TIMEOUT,
            **extra,
        )
    except Exception as exc:  # noqa: BLE001
        raise EvaluationError(
            f"Fallo al invocar '{MODEL}'. {_hint_from_error(str(exc))}"
        ) from exc
    latency_ms = (time.perf_counter() - started) * 1000

    choice = response.choices[0]
    if choice.finish_reason == "length":
        raise EvaluationError(_truncation_message(response))

    text = choice.message.content or ""
    try:
        return _extract_json(text), latency_ms
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"El modelo no devolvió JSON válido: {exc}") from exc


# Turns a provider error into something the user can act on
def _hint_from_error(detail: str) -> str:
    """Translate the provider error into an actionable message."""
    lowered = detail.lower()
    if "rate" in lowered and "limit" in lowered:
        return (
            "Se agotó el cupo de solicitudes del proveedor. En el nivel gratuito "
            "de Gemini los límites son bajos: espera un minuto y reintenta."
        )
    if any(t in lowered for t in ("api key", "authentication", "unauthorized", "401", "403")):
        return (
            "El proveedor rechazó la credencial. Revisa que la clave del .env "
            "esté vigente y corresponda al proveedor de LLM_MODEL."
        )
    if "timeout" in lowered or "timed out" in lowered:
        return (
            f"El proveedor no respondió en {TIMEOUT:g} s. Ajusta LLM_TIMEOUT si "
            "el modelo es lento, o reintenta: suele ser saturación pasajera."
        )
    if API_BASE and any(
        t in lowered
        for t in ("connection", "refused", "unreachable", "name resolution", "no route")
    ):
        return (
            f"No se pudo abrir conexión con LLM_API_BASE={API_BASE}. Verifica que "
            "el servidor esté corriendo y que el contenedor lo alcance: "
            "docker compose exec evaluador python -c "
            f"\"import urllib.request;print(urllib.request.urlopen('{API_BASE}/api/tags')"
            '.status)"'
        )
    if "not found" in lowered or "404" in lowered:
        return (
            f"El proveedor no reconoce el modelo '{MODEL}'. Verifica el nombre "
            "exacto en la documentación de litellm."
        )
    return detail


def _format_input(story: str, criteria: str) -> str:
    """The user-supplied part appended to every prompt. Spanish, like the prompt."""
    return (
        f"HISTORIA DE USUARIO:\n{story}\n\n"
        f"CRITERIOS DE ACEPTACIÓN:\n{criteria.strip() or '(no se proporcionaron)'}"
    )


def _failed_criteria(evaluation: dict) -> list[dict]:
    """Criteria marked fail in either of the rubric's two blocks."""
    failures = []
    # API contract stays in Spanish: consumed by the frontend
    for block in ("gate2_historia", "gate2_criterios"):
        for item in evaluation.get(block) or []:
            if isinstance(item, dict) and item.get("estado") == "fail":
                failures.append(item)
    return failures


# OURS: deterministic priority rule, not the model's
def derive_verdict_from_failures(evaluation: dict) -> str:
    """The model reports state and type per criterion; Python derives the verdict.

    While the model emitted the verdict, nothing stopped it from returning every
    failure typed "redaccion" and still rejecting for missing information.

    Verdict values stay Spanish: they are prompt and API payload.
    """
    failures = _failed_criteria(evaluation)
    if not failures:
        return "aprobado"
    if any(f.get("tipo") == "informacion" for f in failures):
        return "rechazo_informacion"
    return "rechazo_redaccion"


def _summarize_failures(evaluation: dict) -> str:
    """Compact failure list, injected into the complementation prompt."""
    lines = []
    for f in _failed_criteria(evaluation):
        kind = f.get("tipo") or "sin tipo"
        evidence = f.get("evidencia") or ""
        lines.append(f"- {f.get('id', '?')} [{kind}]: {evidence}".rstrip(": "))
    return "\n".join(lines)


# Call 1: diagnoses only, proposes nothing
def evaluate_quality(
    story: str, criteria: str, gate1_summary: str, smells_summary: str = ""
) -> tuple[dict, float]:
    """Run the evaluation call against the rubric."""
    prompt = build_evaluation_prompt(gate1_summary, smells_summary)
    return _invoke_model(f"{prompt}\n\n{_format_input(story, criteria)}")


# Call 2: proposes only, never re-diagnoses
def propose_complementation(
    story: str, criteria: str, evaluation: dict, verdict: str
) -> tuple[dict, float]:
    """Run the complementation call on an already-closed diagnosis.

    Deliberately does not receive the smells: they would anchor the rewrite.
    """
    prompt = build_complementation_prompt(verdict, _summarize_failures(evaluation))
    return _invoke_model(f"{prompt}\n\n{_format_input(story, criteria)}")


# Experiment config, not dead code (MODO_ACOPLADO)
def run_coupled_call(
    story: str, criteria: str, gate1_summary: str, smells_summary: str = ""
) -> tuple[dict, float]:
    """Coupled experiment mode: the original prompt, one single call."""
    prompt = build_coupled_prompt(gate1_summary, smells_summary)
    return _invoke_model(f"{prompt}\n\n{_format_input(story, criteria)}")


# OURS: constraint enforced in code, not asked for in
# the prompt. Drops, never repairs.
def _drop_output_not_matching_verdict(proposal: dict, verdict: str) -> dict:
    """Keep the field the verdict authorizes and drop the other one.

    Under rechazo_informacion, handing back a rewrite would be exactly the
    over-generation this gate exists to prevent. The prompt already forbids it;
    the model produces it anyway, so the exclusion is enforced here.

    Also reports whether anything had to be dropped, because how often the model
    ignores the prompt's prohibition is an experiment datum.
    """
    # API contract stays in Spanish: consumed by the frontend
    rewrite = proposal.get("complementacion")
    questions = proposal.get("preguntas_po") or []
    if verdict == "rechazo_informacion":
        return {
            "complementacion": None,
            "preguntas_po": questions,
            "modelo_desobedecio": bool(rewrite),
        }
    return {
        "complementacion": rewrite,
        "preguntas_po": [],
        "modelo_desobedecio": bool(questions),
    }


# Orchestrates the 2 calls; decides nothing itself
def run_gate2(
    story: str, criteria: str, gate1_summary: str, smells_summary: str = ""
) -> dict:
    """Entry point of gate 2. Returns one single response.

    Internally this is one or two model calls depending on the verdict; from the
    outside the contract is unchanged. Adds traceability: how many calls were
    made and how long each one took.
    """
    problem = check_configuration()
    if problem:
        raise EvaluationError(problem)

    # API contract stays in Spanish: consumed by the frontend
    if COUPLED_MODE:
        result, ms = run_coupled_call(story, criteria, gate1_summary, smells_summary)
        result.setdefault("veredicto", derive_verdict_from_failures(result))
        result["modo"] = "acoplado"
        result["llamadas_modelo"] = 1
        result["latencias_ms"] = [{"fase": "acoplada", "ms": round(ms, 1)}]
        result["modelo_desobedecio"] = False
        return result

    result, eval_ms = evaluate_quality(story, criteria, gate1_summary, smells_summary)
    result["veredicto"] = derive_verdict_from_failures(result)
    result["modo"] = "desacoplado"
    latencies = [{"fase": "evaluacion", "ms": round(eval_ms, 1)}]
    result.setdefault("complementacion", None)
    result.setdefault("preguntas_po", [])
    result["modelo_desobedecio"] = False

    # An approved story spends no second call: there is nothing to complement.
    if result["veredicto"] != "aprobado":
        proposal, comp_ms = propose_complementation(
            story, criteria, result, result["veredicto"]
        )
        result.update(_drop_output_not_matching_verdict(proposal, result["veredicto"]))
        latencies.append({"fase": "complementacion", "ms": round(comp_ms, 1)})

        # Measurement only: no verdict is derived from it and the flow is
        # unchanged. It just re-scores the rewrite on the same seven criteria.
        if REEVALUATE_COMPLEMENTATION:
            new_story, new_criteria = rewritten_text(result.get("complementacion"))
            if new_story or new_criteria:
                second, reeval_ms = evaluate_quality(new_story, new_criteria, "")
                # API contract stays in Spanish: consumed by the frontend
                result["reevaluacion"] = {
                    "gate2_historia": second.get("gate2_historia") or [],
                    "gate2_criterios": second.get("gate2_criterios") or [],
                    "resumen": second.get("resumen"),
                }
                latencies.append({"fase": "reevaluacion", "ms": round(reeval_ms, 1)})

    result["llamadas_modelo"] = len(latencies)
    result["latencias_ms"] = latencies
    return result
