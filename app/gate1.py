"""
Gate 1 — deterministic structural checks.

No language model involved. Reimplements the checks AQUSA resolves with rules
and classic NLP, narrowed to what applies to this pipeline.

Follows the Perfect Recall Condition of Lucassen et al. (2016): when in doubt,
report. A spare warning beats letting a structural defect through, because a
false alarm costs the reviewer seconds and a missed defect costs the whole
pipeline.

Check ids, labels and evidence stay in Spanish: they are API payload rendered
by app/static/index.html.
"""

import re
from dataclasses import dataclass, asdict

# ---------------------------------------------------------------------------
# Patterns. Spanish and English variants are both accepted because the
# published story sets are in English and the case study's are in Spanish.
# ---------------------------------------------------------------------------
# QUS "well-formed": the role part (Lucassen 2016)
ROLE = re.compile(r"\b(como|as an?|siendo)\b\s+\w+", re.IGNORECASE)

# QUS "well-formed": the means part (Lucassen 2016)
MEANS = re.compile(
    r"\b(quiero|deseo|necesito|i want|i need|i would like|me gustaría)\b",
    re.IGNORECASE,
)

# QUS "well-formed": the optional ends part (Lucassen 2016)
GOAL = re.compile(r"\b(para|so that|de modo que|con el fin de|a fin de)\b", re.IGNORECASE)

# OURS: conjunction as a proxy for a non-atomic means
CONJUNCTION = re.compile(
    r"\s+(y también|y ademas|y además|and also|,\s*y\s|\sy\s|\band\b|\bademás\b)\s+",
    re.IGNORECASE,
)

# QUS ADAPTED: "minimal" narrowed to embedded AC only
EMBEDDED_AC = re.compile(
    r"(^\s*[-*•]\s)|(\bcriterios? de aceptaci[oó]n\b)|"
    r"(\bdado que\b.*\bcuando\b)|(\bgiven\b.*\bwhen\b)|"
    r"(\bacceptance criteri)",
    re.IGNORECASE | re.MULTILINE,
)

# OURS: below this, the text is a fragment, not a story
MIN_WORDS = 6

# OURS: only an unusable input stops the flow; the rest travels as signal
BLOCKING_CHECKS = {"well_formed", "ac_present"}


@dataclass
class Check:
    # API contract stays in Spanish: consumed by the frontend
    id: str
    label: str
    passed: bool
    evidencia: str = ""


def _means_fragment(story: str) -> str:
    """The span between the "quiero" and the "para", where the feature lives.

    Falls back to the whole story when the markers are absent.
    """
    m = MEANS.search(story)
    if not m:
        return story
    rest = story[m.end():]
    g = GOAL.search(rest)
    return rest[: g.start()] if g else rest


# Runs every structural check; never calls the model
def run_gate1(story: str, criteria: str = "") -> list[Check]:
    """Evaluate the input against the deterministic checks, in order."""
    story = (story or "").strip()
    checks: list[Check] = []

    # --- well_formed: role + means ---------------------------------------
    # QUS "well-formed" (Lucassen 2016), as-is
    has_role = bool(ROLE.search(story))
    has_means = bool(MEANS.search(story))
    missing = []
    if not has_role:
        missing.append("rol")
    if not has_means:
        missing.append("funcionalidad deseada")
    checks.append(
        Check(
            id="well_formed",
            label="Bien formada",
            passed=has_role and has_means,
            evidencia="" if not missing else f"No se identifica: {', '.join(missing)}.",
        )
    )

    # --- full_sentence ---------------------------------------------------
    # QUS "full sentence" (Lucassen 2016), as-is
    # OURS: the 6-word threshold; QUS sets no number
    word_count = len(story.split())
    complete = word_count >= MIN_WORDS
    checks.append(
        Check(
            id="full_sentence",
            label="Oración completa",
            passed=complete,
            evidencia="" if complete else f"Solo {word_count} palabras: parece un fragmento, no una historia.",
        )
    )

    # --- minimal: no acceptance criteria embedded -------------------------
    # QUS ADAPTED: QUS bans any extra; here only embedded AC
    embeds = bool(EMBEDDED_AC.search(story))
    checks.append(
        Check(
            id="minimal",
            label="Mínima",
            passed=not embeds,
            evidencia="Los criterios de aceptación deben ir aparte, no dentro del enunciado."
            if embeds
            else "",
        )
    )

    # --- atomicity signal (warning, not verdict) --------------------------
    # QUS ADAPTED: QUS "atomic" downgraded to a signal
    # AQUSA reports its worst false positives here ("R&D Manager"). Hence this
    # is emitted as a signal for gate 2, not as a failure of its own.
    means = _means_fragment(story)
    conj = CONJUNCTION.search(means)
    checks.append(
        Check(
            id="atomic_hint",
            label="Señal de atomicidad",
            passed=conj is None,
            evidencia=f"Conjunción en la funcionalidad: '{conj.group().strip()}'." if conj else "",
        )
    )

    # --- acceptance criteria present --------------------------------------
    # OURS: no source; comes from the pytest-bdd target
    has_ac = bool((criteria or "").strip())
    checks.append(
        Check(
            id="ac_present",
            label="Trae criterios de aceptación",
            passed=has_ac,
            evidencia="" if has_ac else "Sin criterios no hay insumo para derivar escenarios.",
        )
    )

    return checks


# Compact text injected into the gate 2 prompt
def summarize_for_prompt(checks: list[Check]) -> str:
    """Render the checks as the lines gate 2 receives inside its prompt."""
    lines = []
    for c in checks:
        state = "OK" if c.passed else "FALLA"
        extra = f" — {c.evidencia}" if c.evidencia else ""
        lines.append(f"- {c.id}: {state}{extra}")
    return "\n".join(lines)


# OURS: only hard failures block; the rest are signals
def blocks(checks: list[Check]) -> bool:
    """True when the input is unusable and the model must not be invoked."""
    return any(not c.passed for c in checks if c.id in BLOCKING_CHECKS)


def to_dicts(checks: list[Check]) -> list[dict]:
    """Serialize for the API response."""
    return [asdict(c) for c in checks]
