"""
Rubric for specific objective 2.

Single place where the criteria live. The prompts are built from here, so
changing the rubric never means editing loose text inside a string.

Composite rubric: QUS (story level) + our own extension (acceptance criteria).

The rubric CONTENT stays in Spanish on purpose: `definicion`, `label` and
`fuente` are prompt payload and API payload, not code. Only the identifiers
around them are English.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Criterion:
    id: str
    label: str
    definicion: str
    fuente: str


# ---------------------------------------------------------------------------
# Gate 2 — story level. QUS subset, narrowed to what affects derivability.
# ---------------------------------------------------------------------------
# QUS (Lucassen 2016), subset bounded by derivability
STORY_CRITERIA: list[Criterion] = [
    # QUS (Lucassen 2016), as-is
    Criterion(
        id="atomic",
        label="Atómica",
        definicion="Expresa exactamente una funcionalidad. Si expresa dos, el escenario mezcla comportamientos.",
        fuente="QUS (Lucassen et al., 2016)",
    ),
    # QUS (Lucassen 2016), as-is
    Criterion(
        id="unambiguous",
        label="No ambigua",
        definicion="No admite dos lecturas que produzcan escenarios distintos o contradictorios.",
        fuente="QUS (Lucassen et al., 2016)",
    ),
    # QUS (Lucassen 2016), as-is
    Criterion(
        id="conceptually_sound",
        label="Conceptualmente sólida",
        definicion="El 'para' expresa una razón, no una segunda funcionalidad encubierta.",
        fuente="QUS (Lucassen et al., 2016)",
    ),
    # QUS ADAPTED: cross-story in QUS, internal here.
    # Renamed from conflict_free to free that name for the
    # backlog-level criterion (pending)
    Criterion(
        id="internally_consistent",
        label="Internamente consistente",
        definicion="No se contradice internamente ni contradice lo que sus propios criterios afirman.",
        fuente="QUS (Lucassen et al., 2016)",
    ),
    # OURS: detects disconnection, not contradiction.
    # No source yet; candidate contribution
    Criterion(
        id="aligned",
        label="Criterios alineados con la historia",
        definicion=(
            "Los criterios de aceptación describen la funcionalidad que la historia "
            "enuncia, y no otra. Un criterio que hable de algo ajeno a la historia es "
            "una falla, aunque no la contradiga."
        ),
        fuente="Aporte propio · sin fuente en la literatura revisada",
    ),
]

# ---------------------------------------------------------------------------
# Gate 2 — acceptance-criteria level. Our own extension, inherited from
# ISO/IEC/IEEE 29148, the G.AC guidelines of Ferreira et al. (2022) and BDD
# writing guidance.
# ---------------------------------------------------------------------------
# OURS: QUS does not cover acceptance criteria
AC_CRITERIA: list[Criterion] = [
    # ISO 29148 + G.AC.5 (Ferreira 2022), as-is
    Criterion(
        id="verifiable",
        label="Verificables",
        definicion=(
            "Cada criterio afirma algo observable y comprobable. Se rechazan los "
            "criterios generales y vagos que serían difíciles de probar."
        ),
        fuente="ISO/IEC/IEEE 29148 · G.AC.5 (Ferreira et al., 2022)",
    ),
    # G.AC.7 and G.AC.8 (Ferreira 2022), as-is
    Criterion(
        id="path_coverage",
        label="Cobertura de caminos",
        definicion=(
            "Cubren el camino de éxito y los caminos de falla relevantes. Si todos "
            "los criterios son de éxito, hay insuficiencia detectable."
        ),
        fuente="G.AC.7 y G.AC.8 (Ferreira et al., 2022)",
    ),
    # OURS: no source; comes from the pytest-bdd target
    # OURS: parametrizable value != missing business rule
    Criterion(
        id="gwt_translatable",
        label="Traducibles a Given-When-Then",
        definicion=(
            "Cada criterio se puede mapear a un escenario Given-When-Then sin "
            "inventar la regla de negocio: cómo se calcula algo, qué condiciones "
            "lo habilitan o qué ocurre ante el error. Un valor parametrizable "
            "—un porcentaje, un umbral, un identificador— no es información "
            "faltante: el escenario se escribe igual, con un marcador."
        ),
        fuente="BDD · destino del pipeline",
    ),
]


# ---------------------------------------------------------------------------
# Prompt templates. Their text stays in Spanish, word for word.
#   EVALUATION_PROMPT_TEMPLATE      -> call 1, diagnoses only
#   COMPLEMENTATION_PROMPT_TEMPLATE -> call 2, proposes only
#   COUPLED_PROMPT_TEMPLATE         -> the original prompt, both in one call
# The {placeholders} are part of the prompt text, so the .format() keywords
# below stay Spanish too. Renaming them would edit the prompt.
# ---------------------------------------------------------------------------

_HEADER = """Eres el agente evaluador de un sistema que genera pruebas de aceptación ejecutables a partir de historias de usuario. Tu trabajo NO es juzgar calidad en abstracto: es determinar si a partir de esta historia y sus criterios de aceptación se puede derivar un escenario Given-When-Then correcto y ejecutable."""

_CLASSIFICATION = """CLASIFICACIÓN DE CADA FALLA (esto es lo más importante):
- "redaccion": la información necesaria SÍ está presente en el texto, solo está mal expresada, desordenada o mezclada. Es corregible reescribiendo.
- "informacion": falta conocimiento de negocio que NO aparece en ningún lugar del texto (umbrales, reglas, mensajes, valores concretos, casos de error). NO es corregible reescribiendo: completarlo sería inventar."""


EVALUATION_PROMPT_TEMPLATE = """{encabezado}

En esta llamada SOLO diagnosticas. No propongas reescrituras, no redactes criterios nuevos, no formules preguntas: eso ocurre en un paso posterior y separado.

REGLA DE DECISIÓN para cada criterio: si se viola, ¿todavía puedo derivar el escenario? Si no se puede, es falla.

RÚBRICA — NIVEL HISTORIA
{historia}

RÚBRICA — NIVEL CRITERIOS DE ACEPTACIÓN
{criterios_ac}

{clasificacion}

No emitas veredicto global: lo deriva el sistema a partir del tipo de cada falla.

RESULTADO DE LA COMPUERTA 1 (chequeos estructurales deterministas ya ejecutados, no los repitas):
{gate1}
{smells}
Responde ÚNICAMENTE con JSON válido. Sin markdown, sin backticks, sin texto antes ni después. Cada "evidencia" debe tener máximo 15 palabras.

{{
  "gate2_historia": [{{"id": "atomic", "estado": "pass|fail", "tipo": "redaccion|informacion|null", "evidencia": ""}}],
  "gate2_criterios": [{{"id": "verifiable", "estado": "pass|fail", "tipo": "redaccion|informacion|null", "evidencia": ""}}],
  "resumen": "una frase"
}}"""


COMPLEMENTATION_PROMPT_TEMPLATE = """{encabezado}

La evaluación ya ocurrió y no se discute. En esta llamada SOLO complementas: no reabras el diagnóstico, no cambies el veredicto, no evalúes de nuevo.

{clasificacion}

VEREDICTO YA DETERMINADO: {veredicto}

FALLAS DETECTADAS EN LA EVALUACIÓN:
{fallas}

QUÉ DEBES PRODUCIR:
{instruccion}

Responde ÚNICAMENTE con JSON válido. Sin markdown, sin backticks, sin texto antes ni después.

{{
  "complementacion": {{"historia": "", "criterios": [""], "cambios": [""]}},
  "preguntas_po": [""]
}}"""

# Zhang et al. (2024, ALAS/XP): scope creep when improving stories
_WORDING_INSTRUCTION = """Propón la versión reescrita usando ÚNICAMENTE información ya presente en el original. Prohibido agregar funcionalidad, reglas, mensajes o valores que no estuvieran. Este es el criterio de no-sobre-generación.
Llena "complementacion" con la historia reescrita, los criterios reescritos y la lista de qué cambió. Deja "preguntas_po" como lista vacía."""

_MISSING_INFO_INSTRUCTION = """Falta conocimiento de negocio que no está escrito en ninguna parte. NO lo inventes: completarlo sería fabricar requisitos.
Deja "complementacion" en null y llena "preguntas_po" con lo que el Product Owner debe responder para que la historia sea derivable."""


COUPLED_PROMPT_TEMPLATE = """{encabezado}

REGLA DE DECISIÓN para cada criterio: si se viola, ¿todavía puedo derivar el escenario? Si no se puede, es falla.

RÚBRICA — NIVEL HISTORIA
{historia}

RÚBRICA — NIVEL CRITERIOS DE ACEPTACIÓN
{criterios_ac}

{clasificacion}

VEREDICTO:
- "rechazo_informacion" si al menos una falla es de tipo informacion. Tiene prioridad sobre lo demás.
- "rechazo_redaccion" si hay fallas y todas son de tipo redaccion.
- "aprobado" si no hay fallas.

COMPLEMENTACIÓN:
- Si el veredicto es rechazo_redaccion, propón la versión reescrita usando ÚNICAMENTE información ya presente en el original. Prohibido agregar funcionalidad, reglas, mensajes o valores que no estuvieran. Este es el criterio de no-sobre-generación.
- Si el veredicto es rechazo_informacion, deja "complementacion" en null y llena "preguntas_po" con lo que el Product Owner debe responder.
- Si el veredicto es aprobado, deja "complementacion" en null y "preguntas_po" como lista vacía.

RESULTADO DE LA COMPUERTA 1 (chequeos estructurales deterministas ya ejecutados, no los repitas):
{gate1}
{smells}
Responde ÚNICAMENTE con JSON válido. Sin markdown, sin backticks, sin texto antes ni después. Cada "evidencia" debe tener máximo 15 palabras.

{{
  "gate2_historia": [{{"id": "atomic", "estado": "pass|fail", "tipo": "redaccion|informacion|null", "evidencia": ""}}],
  "gate2_criterios": [{{"id": "verifiable", "estado": "pass|fail", "tipo": "redaccion|informacion|null", "evidencia": ""}}],
  "veredicto": "aprobado|rechazo_redaccion|rechazo_informacion",
  "resumen": "una frase",
  "complementacion": {{"historia": "", "criterios": [""], "cambios": [""]}},
  "preguntas_po": [""]
}}"""


def _format_criteria(criteria: list[Criterion]) -> str:
    return "\n".join(f"- {c.id} ({c.label}): {c.definicion}" for c in criteria)


def _smells_section(smells_summary: str) -> str:
    """Optional prompt section; empty when SMELLS_EN_PROMPT is off."""
    if not smells_summary:
        return ""
    return (
        "\nHALLAZGOS DE LAS REGLAS DE REQUIREMENT SMELLS (señal, no veredicto; "
        "la precisión reportada de estas reglas es baja, contrástalos con el texto):\n"
        f"{smells_summary}\n"
    )


# Call 1 prompt: diagnoses only, emits no verdict
def build_evaluation_prompt(gate1_summary: str, smells_summary: str = "") -> str:
    """Prompt for the evaluation call. Asks for per-criterion state and type."""
    return EVALUATION_PROMPT_TEMPLATE.format(
        encabezado=_HEADER,
        clasificacion=_CLASSIFICATION,
        historia=_format_criteria(STORY_CRITERIA),
        criterios_ac=_format_criteria(AC_CRITERIA),
        gate1=gate1_summary,
        smells=_smells_section(smells_summary),
    )


# Call 2 prompt: proposes only, never re-diagnoses
def build_complementation_prompt(verdict: str, failures_summary: str) -> str:
    """Prompt for the complementation call. The verdict is already settled."""
    instruction = (
        _MISSING_INFO_INSTRUCTION
        if verdict == "rechazo_informacion"
        else _WORDING_INSTRUCTION
    )
    return COMPLEMENTATION_PROMPT_TEMPLATE.format(
        encabezado=_HEADER,
        clasificacion=_CLASSIFICATION,
        veredicto=verdict,
        fallas=failures_summary or "(ninguna registrada)",
        instruccion=instruction,
    )


# Experiment config, not dead code (MODO_ACOPLADO)
def build_coupled_prompt(gate1_summary: str, smells_summary: str = "") -> str:
    """The original single-call prompt, kept so both designs stay comparable."""
    return COUPLED_PROMPT_TEMPLATE.format(
        encabezado=_HEADER,
        clasificacion=_CLASSIFICATION,
        historia=_format_criteria(STORY_CRITERIA),
        criterios_ac=_format_criteria(AC_CRITERIA),
        gate1=gate1_summary,
        smells=_smells_section(smells_summary),
    )


# Readable names, resolved server-side so the rubric stays the source of truth
LABELS: dict[str, str] = {c.id: c.label for c in STORY_CRITERIA + AC_CRITERIA}
