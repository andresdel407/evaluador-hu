"""
Verdict derivation and output exclusion.

Since evaluation and complementation were split, the model no longer emits a
verdict: it returns state and type per criterion, and Python applies the
priority rule. These tests cover that rule and the exclusion that follows from
it, both deterministic and model-free.

Verdict values stay Spanish: they are prompt and API payload.
"""

import pytest

# gate2 imports litellm, a requirements.txt dependency. On an environment where
# it is not installed this skips instead of failing for an unrelated reason.
pytest.importorskip("litellm")

from app.gate2 import (  # noqa: E402
    _drop_output_not_matching_verdict,
    derive_verdict_from_failures,
)


def evaluation(*criteria) -> dict:
    return {"gate2_historia": list(criteria), "gate2_criterios": []}


def test_no_failures_is_approved():
    e = evaluation({"id": "atomic", "estado": "pass", "tipo": None})
    assert derive_verdict_from_failures(e) == "aprobado"


def test_only_wording_failures():
    e = evaluation(
        {"id": "atomic", "estado": "fail", "tipo": "redaccion"},
        {"id": "unambiguous", "estado": "fail", "tipo": "redaccion"},
    )
    assert derive_verdict_from_failures(e) == "rechazo_redaccion"


def test_a_single_information_failure_takes_priority():
    e = evaluation(
        {"id": "atomic", "estado": "fail", "tipo": "redaccion"},
        {"id": "unambiguous", "estado": "fail", "tipo": "informacion"},
    )
    assert derive_verdict_from_failures(e) == "rechazo_informacion"


def test_looks_at_both_rubric_blocks():
    e = {
        "gate2_historia": [{"id": "atomic", "estado": "pass", "tipo": None}],
        "gate2_criterios": [{"id": "verifiable", "estado": "fail", "tipo": "informacion"}],
    }
    assert derive_verdict_from_failures(e) == "rechazo_informacion"


def test_empty_response_does_not_blow_up():
    assert derive_verdict_from_failures({}) == "aprobado"


# --- exclusion between rewrite and questions for the PO --------------------
BOTH = {
    "complementacion": {"historia": "reescrita", "criterios": [], "cambios": []},
    "preguntas_po": ["¿Cuál es el umbral?"],
}


def test_missing_information_drops_the_rewrite():
    # Filling in what is missing would be inventing: only questions survive.
    r = _drop_output_not_matching_verdict(BOTH, "rechazo_informacion")
    assert r["complementacion"] is None
    assert r["preguntas_po"] == ["¿Cuál es el umbral?"]


def test_wording_rejection_drops_the_questions():
    r = _drop_output_not_matching_verdict(BOTH, "rechazo_redaccion")
    assert r["complementacion"]["historia"] == "reescrita"
    assert r["preguntas_po"] == []


def test_disobedience_is_reported_when_something_was_dropped():
    assert _drop_output_not_matching_verdict(BOTH, "rechazo_informacion")[
        "modelo_desobedecio"
    ]
    assert _drop_output_not_matching_verdict(BOTH, "rechazo_redaccion")[
        "modelo_desobedecio"
    ]


def test_obedient_reply_is_not_flagged():
    only_questions = {"complementacion": None, "preguntas_po": ["¿Umbral?"]}
    assert not _drop_output_not_matching_verdict(only_questions, "rechazo_informacion")[
        "modelo_desobedecio"
    ]

    only_rewrite = {"complementacion": {"historia": "x"}, "preguntas_po": []}
    assert not _drop_output_not_matching_verdict(only_rewrite, "rechazo_redaccion")[
        "modelo_desobedecio"
    ]
