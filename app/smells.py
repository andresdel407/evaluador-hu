"""
Deterministic requirement-smell detector. No model, no network, pure functions.

Base: Zakeri-Nasrabadi and Parsa (2024), "Natural language requirements
testability measurement based on requirement smells", Neural Computing and
Applications 36(21), 13051-13085. Extends the Femmer et al. (Smella) catalogue,
itself derived from ISO/IEC/IEEE 29148.

Unit of analysis: ONE sentence. The story is one unit; every acceptance
criterion is an independent unit. Nothing is averaged or aggregated across
units — each one reports its own findings.

    # Def. 2 of the paper: a clean one-sentence requirement
    # is fully testable

Clarity is eq. 3 of the paper. T(R) and alpha are deliberately absent:

    # One-sentence unit => T(R) = C(R) (eq. 4);
    # the alpha machinery does not apply

S9 (polysemy) is out of scope. It needs the paper's word-embedding pipeline: a
Word2Vec model trained over a domain corpus to count how many distinct senses a
term carries, then a threshold on that count. There is no equivalent resource
for Spanish requirements here, and approximating it with a static dictionary
would measure something else and report it under the paper's name.

Findings are SIGNAL, never a gate:

    # Precision 0.42, recall 0.70 in the paper: too many
    # false positives to ever block

Smell ids and API payload stay in Spanish, like the rest of the contract.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

# ---------------------------------------------------------------------------
# Smell catalogue
# ---------------------------------------------------------------------------
# Femmer et al., via Zakeri 2024
S4_SUPERLATIVES = "S4"
# Femmer et al., via Zakeri 2024
S5_COMPARATIVES = "S5"
# Femmer et al., via Zakeri 2024
S6_NEGATIVE = "S6"
# Femmer et al., via Zakeri 2024
S7_VAGUE_PRONOUNS = "S7"
# Zakeri 2024, new smell in that catalogue
S8_UNCERTAIN_VERBS = "S8"
# Femmer et al., via Zakeri 2024
S1_SUBJECTIVE = "S1"
# Femmer et al., via Zakeri 2024
S2_AMBIGUOUS_ADV_ADJ = "S2"
# Femmer et al., via Zakeri 2024
S3_NON_VERIFIABLE = "S3"

# Labels travel to the API, so they stay Spanish.
SMELL_LABELS: dict[str, str] = {
    S1_SUBJECTIVE: "Lenguaje subjetivo",
    S2_AMBIGUOUS_ADV_ADJ: "Adverbio o adjetivo ambiguo",
    S3_NON_VERIFIABLE: "Término no verificable",
    S4_SUPERLATIVES: "Superlativo",
    S5_COMPARATIVES: "Comparativo",
    S6_NEGATIVE: "Enunciado negativo",
    S7_VAGUE_PRONOUNS: "Pronombre vago",
    S8_UNCERTAIN_VERBS: "Verbo incierto",
}

# ---------------------------------------------------------------------------
# Dictionaries
# ---------------------------------------------------------------------------
# PRELIMINARY: the paper builds its dictionary with
# Word2Vec over Wikipedia; no Spanish one exists
SUBJECTIVE_SEED = {
    "amigable", "intuitivo", "cómodo", "agradable", "elegante", "moderno",
    "limpio", "sencillo", "claro", "natural", "atractivo", "útil", "práctico",
    "eficiente", "robusto", "flexible", "potente", "adecuado", "apropiado",
    "razonable", "aceptable", "satisfactorio",
}

# PRELIMINARY: the paper builds its dictionary with
# Word2Vec over Wikipedia; no Spanish one exists
AMBIGUOUS_SEED = {
    "rápido", "rápidamente", "lento", "pronto", "aproximadamente", "casi",
    "cerca", "algunos", "varios", "pocos", "muchos", "suficiente", "bastante",
    "frecuentemente", "ocasionalmente", "normalmente", "habitualmente",
    "generalmente", "usualmente", "periódicamente", "oportunamente", "mínimo",
}

# PRELIMINARY: the paper builds its dictionary with
# Word2Vec over Wikipedia; no Spanish one exists
NON_VERIFIABLE_SEED = {
    "etc", "etcétera", "otros", "similar", "similares", "correspondiente",
    "correspondientes", "pertinente", "pertinentes", "relevante", "relevantes",
    "necesario", "necesarios", "apropiadamente", "correctamente",
    "debidamente", "eficazmente", "adecuadamente", "soportar", "gestionar",
    "manejar", "procesar",
}

# Zakeri 2024, smell S8; single-token forms
UNCERTAIN_VERB_WORDS = {
    "puede", "puedan", "pueda", "pueden", "podría", "podrían", "podrá",
    "podrán", "pudiera", "pudieran", "debería", "deberían", "quizá", "quizás",
    "posiblemente", "eventualmente", "probablemente",
}

# Multi-token forms; matched over the raw text, not token by token.
UNCERTAIN_VERB_PHRASES = ("tal vez", "de ser posible", "si es posible")

# "debe"/"deberá" are obligation, not a smell
# (the paper excepts "shall" for the same reason)
OBLIGATION_WORDS = {"debe", "deben", "deberá", "deberán", "debemos"}

# Periphrastic superlatives that spaCy does not mark Degree=Sup
SUPERLATIVE_SEED = {"óptimo", "óptima", "pésimo", "pésima", "supremo", "ínfimo"}

# Comparatives spaCy sometimes leaves unmarked
COMPARATIVE_SEED = {"superior", "inferior", "preferible"}

# Fixed phrases built on "más"/"menos" that compare nothing. spaCy still tags
# the adverb Degree=Cmp inside them, so S5 has to be suppressed by hand.
# ADAPTED: fixed phrases are not comparatives in Spanish;
# deviation from the catalog as reported in the paper
COMPARATIVE_STOP_PHRASES = (
    "al menos",
    "a lo menos",
    "por lo menos",
    "más o menos",
    "a más tardar",
    "ni más ni menos",
)

# Negation carried by a word rather than by Polarity=Neg
NEGATIVE_SEED = {"sin", "salvo", "excepto", "tampoco", "ni"}

# Vague pronouns beyond the demonstratives spaCy marks PronType=Dem
VAGUE_PRONOUN_SEED = {"ello", "aquello", "alguno", "alguien", "algo",
                      "cualquiera", "uno", "mismo"}

# Reflexive and clitic pronouns are structural in Spanish ("se muestra"), so
# flagging them would drown the signal.
# OURS: clitics excluded; not vague, just Spanish syntax
_CLITIC_LEMMAS = {"él", "se", "lo", "la", "le", "les", "los", "las"}

# Smells detected and reported on a unit type, but kept out of C(R) there.
# ADAPTED: S6 excluded from C(R) on AC units. Negation
# is the normal form of a failure path (G.AC.7/G.AC.8)
#
# The original catalogue scores requirements written as prose, where a negation
# flags a capability the system must not provide. An acceptance criterion uses
# it for something else: to state the failure path the rubric itself asks for
# under path_coverage. Counting it would penalise exactly what is rewarded.
SMELLS_EXCLUDED_FROM_CLARITY_BY_UNIT: dict[str, frozenset[str]] = {
    "criterio": frozenset({S6_NEGATIVE}),
    "historia": frozenset(),
}


def counts_for_clarity(smell: str, kind: str) -> bool:
    """Whether this smell feeds C(R) on this unit type. Detection is unaffected."""
    return smell not in SMELLS_EXCLUDED_FROM_CLARITY_BY_UNIT.get(kind, frozenset())


SPACY_MODEL = "es_core_news_sm"

# Whether the rule findings reach the EVALUATION prompt. Never the
# complementation one.
# OURS: if the model sees the rule findings first it
# anchors on them, and its own contribution stops
# being measurable
SMELLS_IN_PROMPT = os.getenv("SMELLS_EN_PROMPT", "false").strip().lower() in {
    "1",
    "true",
    "si",
    "sí",
    "yes",
}


@dataclass(frozen=True)
class Finding:
    word: str
    smell: str
    # False when the smell is reported but excluded from C(R) on this unit type.
    counts: bool = True


@dataclass
class Unit:
    """One sentence, analysed on its own. `kind` is 'historia' or 'criterio'."""

    text: str
    kind: str
    findings: list[Finding] = field(default_factory=list)
    clarity: float = 1.0
    words: int = 0


@lru_cache(maxsize=1)
def _nlp():
    """Load the Spanish pipeline once. Imported lazily so tests can skip it."""
    import spacy

    return spacy.load(SPACY_MODEL)


# Eq. 3 of Zakeri 2024; t = distinct types, not count
def clarity(smelly_words: int, total_words: int, distinct_types: int) -> float:
    """C(R) = 1 if no smells, else 1 - (n_smelly / n_words) ** (1/t).

    Guards the degenerate inputs: an empty unit, a one-word unit, and the
    division by zero that a unit with no countable words would cause.
    """
    if total_words <= 0 or smelly_words <= 0 or distinct_types <= 0:
        return 1.0
    ratio = min(smelly_words / total_words, 1.0)
    return 1.0 - ratio ** (1.0 / distinct_types)


def _phrase_findings(text: str) -> list[tuple[int, Finding]]:
    """Multi-token uncertain verbs, matched over the raw lowercased text."""
    out = []
    lowered = text.lower()
    for phrase in UNCERTAIN_VERB_PHRASES:
        for m in re.finditer(rf"\b{re.escape(phrase)}\b", lowered):
            out.append((m.start(), Finding(text[m.start(): m.end()], S8_UNCERTAIN_VERBS)))
    return out


def _tokens_covered_by(doc, phrases: tuple[str, ...]) -> set[int]:
    """Indices of the tokens falling inside any of `phrases`.

    Same scan as the multi-token uncertain verbs: match over the lowercased
    text, then map the character span back onto tokens.
    """
    covered: set[int] = set()
    lowered = doc.text.lower()
    for phrase in phrases:
        for m in re.finditer(rf"\b{re.escape(phrase)}\b", lowered):
            for token in doc:
                if m.start() <= token.idx < m.end():
                    covered.add(token.i)
    return covered


def _token_smells(token, suppressed: frozenset[str] = frozenset()) -> list[str]:
    """Every smell that fires on one token. A word can carry more than one.

    `suppressed` drops a smell entirely for this token: the finding is never
    created, as opposed to being reported and excluded from C(R).
    """
    smells = []
    lower = token.text.lower()
    lemma = token.lemma_.lower()
    morph = token.morph

    # S4 — POS tagging (Degree) plus a seed list for the periphrastic cases.
    if "Sup" in morph.get("Degree") or "Abs" in morph.get("Degree"):
        smells.append(S4_SUPERLATIVES)
    elif lemma in SUPERLATIVE_SEED or lower in SUPERLATIVE_SEED:
        smells.append(S4_SUPERLATIVES)

    # S5 — comparatives. Degree=Cmp covers "mejor", "peor", "más", "menos".
    if "Cmp" in morph.get("Degree") or lemma in COMPARATIVE_SEED:
        smells.append(S5_COMPARATIVES)

    # S6 — negative statement.
    if "Neg" in morph.get("Polarity") or lower in NEGATIVE_SEED:
        smells.append(S6_NEGATIVE)

    # S7 — vague pronouns. Demonstratives, minus the clitics.
    if token.pos_ == "PRON" and lemma not in _CLITIC_LEMMAS:
        if "Dem" in morph.get("PronType") or lemma in VAGUE_PRONOUN_SEED:
            smells.append(S7_VAGUE_PRONOUNS)

    # S8 — uncertain verbs. Obligation is explicitly not a smell, so the check
    # is on the surface form and the mood, never on the lemma: "debe" and
    # "debería" share the lemma "deber".
    if lower not in OBLIGATION_WORDS:
        conditional = lemma in {"poder", "deber"} and (
            "Cnd" in morph.get("Mood") or "Sub" in morph.get("Mood")
        )
        if lower in UNCERTAIN_VERB_WORDS or conditional:
            smells.append(S8_UNCERTAIN_VERBS)

    # S1/S2/S3 — seed dictionaries, pending the paper's embedding pipeline.
    if lemma in SUBJECTIVE_SEED or lower in SUBJECTIVE_SEED:
        smells.append(S1_SUBJECTIVE)
    if lemma in AMBIGUOUS_SEED or lower in AMBIGUOUS_SEED:
        smells.append(S2_AMBIGUOUS_ADV_ADJ)
    if lemma in NON_VERIFIABLE_SEED or lower in NON_VERIFIABLE_SEED:
        smells.append(S3_NON_VERIFIABLE)

    return [s for s in smells if s not in suppressed]


def analyze_unit(text: str, kind: str) -> Unit:
    """Analyse one sentence. Never raises on empty or single-word input."""
    cleaned = (text or "").strip()
    unit = Unit(text=cleaned, kind=kind)
    if not cleaned:
        return unit

    doc = _nlp()(cleaned)
    countable = [t for t in doc if not t.is_punct and not t.is_space]
    unit.words = len(countable)

    # Tokens inside a fixed phrase: S5 never fires there in the first place.
    no_comparative = _tokens_covered_by(doc, COMPARATIVE_STOP_PHRASES)

    findings: list[Finding] = []
    # Only findings that count feed n_smelly and t; the rest are still reported.
    smelly_indices = set()
    for token in countable:
        suppressed = (
            frozenset({S5_COMPARATIVES}) if token.i in no_comparative else frozenset()
        )
        for smell in _token_smells(token, suppressed):
            counts = counts_for_clarity(smell, kind)
            findings.append(Finding(token.text, smell, counts))
            if counts:
                smelly_indices.add(token.i)

    for start, finding in _phrase_findings(cleaned):
        counts = counts_for_clarity(finding.smell, kind)
        findings.append(Finding(finding.word, finding.smell, counts))
        if counts:
            # A phrase occupies tokens the loop above may not have flagged.
            for token in doc:
                if start <= token.idx < start + len(finding.word):
                    smelly_indices.add(token.i)

    unit.findings = findings
    unit.clarity = clarity(
        smelly_words=len(smelly_indices),
        total_words=unit.words,
        distinct_types=len({f.smell for f in findings if f.counts}),
    )
    return unit


def split_criteria(criteria: str) -> list[str]:
    """One acceptance criterion per unit. Bullets and newlines both separate."""
    lines = []
    for raw in (criteria or "").splitlines():
        line = re.sub(r"^\s*[-*•]\s*", "", raw).strip()
        if line:
            lines.append(line)
    return lines


# The story is one unit; each criterion is another
def analyze_input(story: str, criteria: str) -> list[Unit]:
    """Split the input into one-sentence units and analyse each separately."""
    units = []
    if (story or "").strip():
        units.append(analyze_unit(story, "historia"))
    for criterion in split_criteria(criteria):
        units.append(analyze_unit(criterion, "criterio"))
    return units


# ---------------------------------------------------------------------------
# Content introduced by the rewrite
# ---------------------------------------------------------------------------
# POS that carry requirement content; the rest is grammar. SYM is in because
# spaCy tags "10%" as SYM, not NUM, and a threshold is exactly the kind of
# content this check exists to catch.
CONTENT_POS = {"NOUN", "PROPN", "VERB", "ADJ", "NUM", "SYM"}

# The Spanish stoplist contains domain nouns ("total", "parte"), so dropping
# every stopword would hide real added content.
# OURS: stopword filter skipped for nouns and numbers
_NEVER_STOPWORDS = {"NOUN", "PROPN", "NUM", "SYM"}


def content_terms(text: str) -> set[str]:
    """Content lemmas of a text: nouns, proper nouns, verbs, adjectives, numbers.

    Stopwords are dropped and comparison is by lemma, so a reordering or a
    change of inflection does not read as new content.
    """
    if not (text or "").strip():
        return set()
    terms = set()
    for t in _nlp()(text):
        if t.pos_ not in CONTENT_POS or t.is_punct:
            continue
        if t.is_stop and t.pos_ not in _NEVER_STOPWORDS:
            continue
        # A bare symbol ("%", "·") is not content; "10%" is.
        if t.pos_ == "SYM" and not any(c.isdigit() for c in t.text):
            continue
        terms.add(t.lemma_.lower())
    return terms


# OURS: deterministic check of the non-over-generation
# rule (D7, Zhang 2024); today it lives only in the prompt
def content_diff(original: str, rewritten: str) -> dict[str, list[str]]:
    """Terms the rewrite introduced, and terms it dropped.

    Reports only. It never blocks and never repairs: the paper's own numbers
    do not support acting on this automatically.
    """
    before = content_terms(original)
    after = content_terms(rewritten)
    return {
        "terminos_agregados": sorted(after - before),
        "terminos_quitados": sorted(before - after),
    }


# ---------------------------------------------------------------------------
# API payload
# ---------------------------------------------------------------------------
def unit_to_dict(unit: Unit) -> dict:
    # API contract stays in Spanish: consumed by the frontend
    return {
        "texto": unit.text,
        "tipo": unit.kind,
        "hallazgos": [
            {
                "palabra": f.word,
                "smell": f.smell,
                "etiqueta": SMELL_LABELS[f.smell],
                "cuenta_para_claridad": f.counts,
            }
            for f in unit.findings
        ],
        # OURS: C(R) rises if the rewrite is shorter; word count
        # must travel with it or the delta is misleading
        "claridad": round(unit.clarity, 4),
        "palabras": unit.words,
    }


def summarize_for_prompt(units: list[Unit]) -> str:
    """Compact findings, for the evaluation prompt when SMELLS_EN_PROMPT is on."""
    lines = []
    for unit in units:
        if not unit.findings:
            continue
        hits = ", ".join(
            f"{f.word} ({SMELL_LABELS[f.smell]})" for f in unit.findings
        )
        lines.append(f"- [{unit.kind}] {unit.text[:60]}: {hits}")
    return "\n".join(lines)


def rewritten_text(complementation: dict | None) -> tuple[str, str]:
    """Pull (story, criteria) out of a complementation block, tolerating nulls."""
    if not isinstance(complementation, dict):
        return "", ""
    story = complementation.get("historia") or ""
    criteria = complementation.get("criterios") or []
    if isinstance(criteria, str):
        criteria = [criteria]
    return story, "\n".join(str(c) for c in criteria if c)


def build_report(story: str, criteria: str, complementation: dict | None) -> dict:
    """The whole smells block of the response, before/after when there is a rewrite."""
    original_units = analyze_input(story, criteria)
    # API contract stays in Spanish: consumed by the frontend
    report = {
        "unidades": [unit_to_dict(u) for u in original_units],
        "unidades_reescritas": None,
        "terminos_agregados": [],
        "terminos_quitados": [],
        "reevaluacion": None,
    }

    new_story, new_criteria = rewritten_text(complementation)
    if not (new_story or new_criteria):
        return report

    report["unidades_reescritas"] = [
        unit_to_dict(u) for u in analyze_input(new_story, new_criteria)
    ]
    before = f"{story}\n{criteria}"
    after = f"{new_story}\n{new_criteria}"
    report.update(content_diff(before, after))
    return report
