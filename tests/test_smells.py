"""
Requirement-smell detector tests. No model involved.

The detector is deterministic, so every expectation here is exact. Test texts
stay in Spanish because that is what the detector parses.
"""

import pytest

# spaCy and es_core_news_sm are requirements.txt dependencies. On an environment
# without them this skips rather than failing for an unrelated reason.
pytest.importorskip("spacy")

from app import smells  # noqa: E402

pytest.importorskip("es_core_news_sm")


def smells_of(text: str) -> set[str]:
    return {f.smell for f in smells.analyze_unit(text, "criterio").findings}


# --- one positive and one negative case per implemented smell --------------
def test_s4_superlative_positive():
    assert smells.S4_SUPERLATIVES in smells_of("El sistema muestra la máxima prioridad.")


def test_s4_superlative_negative():
    assert smells.S4_SUPERLATIVES not in smells_of("El sistema muestra la prioridad.")


def test_s5_comparative_positive():
    assert smells.S5_COMPARATIVES in smells_of("El resultado debe ser mejor que el anterior.")


def test_s5_comparative_negative():
    assert smells.S5_COMPARATIVES not in smells_of("El sistema registra el resultado.")


def test_s6_negative_statement_positive():
    assert smells.S6_NEGATIVE in smells_of("El total no cambia.")


def test_s6_negative_statement_negative():
    assert smells.S6_NEGATIVE not in smells_of("El total cambia.")


def test_s7_vague_pronoun_positive():
    assert smells.S7_VAGUE_PRONOUNS in smells_of("Eso se aplica al total.")


def test_s7_vague_pronoun_negative():
    assert smells.S7_VAGUE_PRONOUNS not in smells_of("El cupón se aplica al total.")


def test_s8_uncertain_verb_positive():
    assert smells.S8_UNCERTAIN_VERBS in smells_of("El sistema podría mostrar el total.")


def test_s8_uncertain_verb_negative():
    assert smells.S8_UNCERTAIN_VERBS not in smells_of("El sistema debe mostrar el total.")


# --- obligation is not uncertainty, even sharing the lemma "deber" ---------
def test_obligation_does_not_trigger_s8():
    assert smells.S8_UNCERTAIN_VERBS not in smells_of("el sistema debe mostrar el total")


def test_conditional_triggers_s8():
    assert smells.S8_UNCERTAIN_VERBS in smells_of("el sistema podría mostrar el total")


def test_multiword_uncertain_phrase():
    assert smells.S8_UNCERTAIN_VERBS in smells_of("Tal vez el sistema muestre el total.")


# --- clarity, eq. 3 --------------------------------------------------------
def test_clean_unit_has_clarity_one():
    unit = smells.analyze_unit("El sistema registra el pedido del cliente.", "criterio")
    assert unit.findings == []
    assert unit.clarity == 1.0


def test_clarity_drops_when_smells_are_added():
    clean = smells.analyze_unit("El sistema muestra el total del pedido.", "criterio")
    smelly = smells.analyze_unit("El sistema podría mostrar el total del pedido.", "criterio")
    assert smelly.clarity < clean.clarity


def test_clarity_drops_further_with_more_distinct_types():
    # Same smelly-word ratio direction, but a second TYPE lowers the exponent
    # 1/t and therefore the score. Scored as a story: on a criterion S6 is
    # reported but excluded from C(R), so it would not add a second type.
    one_type = smells.analyze_unit("El sistema podría mostrar el total.", "historia")
    two_types = smells.analyze_unit("El sistema podría no mostrar el total.", "historia")
    assert len({f.smell for f in two_types.findings}) > len(
        {f.smell for f in one_type.findings}
    )
    assert two_types.clarity < one_type.clarity


def test_clarity_formula_matches_equation_3():
    # 2 smelly words out of 10, 2 distinct types -> 1 - (0.2 ** 0.5)
    assert smells.clarity(2, 10, 2) == pytest.approx(1 - 0.2 ** 0.5)
    assert smells.clarity(0, 10, 0) == 1.0


def test_clarity_handles_edges():
    assert smells.clarity(0, 0, 0) == 1.0          # empty unit
    assert smells.clarity(1, 1, 1) == 0.0          # single smelly word
    assert smells.clarity(5, 0, 2) == 1.0          # would divide by zero
    assert smells.clarity(9, 3, 1) == 0.0          # ratio clamped at 1.0


def test_empty_unit_does_not_blow_up():
    unit = smells.analyze_unit("", "criterio")
    assert unit.clarity == 1.0
    assert unit.words == 0
    assert unit.findings == []


# --- unit splitting --------------------------------------------------------
def test_story_with_three_criteria_yields_four_units():
    story = "Como cliente quiero aplicar un cupón para pagar menos."
    criteria = (
        "- El cupón se aplica al total.\n"
        "- El cupón expirado se rechaza.\n"
        "- El cupón usado se rechaza.\n"
    )
    units = smells.analyze_input(story, criteria)
    assert len(units) == 4
    assert [u.kind for u in units] == ["historia", "criterio", "criterio", "criterio"]


def test_each_unit_is_scored_on_its_own():
    # No averaging: a smelly criterion must not drag the clean ones down.
    units = smells.analyze_input(
        "Como cliente quiero aplicar un cupón para pagar menos.",
        "- El sistema registra el pedido del cliente.\n- El sistema podría mostrarlo.",
    )
    assert units[1].clarity == 1.0
    assert units[2].clarity < 1.0


def test_word_count_travels_with_every_unit():
    units = smells.analyze_input("Como cliente quiero X para Y.", "- El total cambia.")
    assert all(u.words > 0 for u in units)


# --- S6 does not feed C(R) on acceptance-criteria units --------------------
NEGATIVE = "El total no cambia y el descuento no se aplica."


def test_criterion_with_only_negations_stays_clear():
    unit = smells.analyze_unit(NEGATIVE, "criterio")
    assert unit.clarity == 1.0


def test_the_same_sentence_as_a_story_is_penalised():
    unit = smells.analyze_unit(NEGATIVE, "historia")
    assert unit.clarity < 1.0


def test_negation_is_still_reported_on_a_criterion():
    unit = smells.analyze_unit(NEGATIVE, "criterio")
    negatives = [f for f in unit.findings if f.smell == smells.S6_NEGATIVE]
    assert negatives, "S6 debe seguir detectándose y reportándose"
    assert all(not f.counts for f in negatives)


def test_negation_does_not_add_a_type_on_a_criterion():
    # t must stay 1: the uncertain verb is the only smell that counts.
    with_both = smells.analyze_unit("El total no se puede modificar.", "criterio")
    only_uncertain = smells.analyze_unit("El total se puede modificar.", "criterio")
    assert with_both.words == only_uncertain.words + 1
    assert {f.smell for f in with_both.findings} == {
        smells.S6_NEGATIVE,
        smells.S8_UNCERTAIN_VERBS,
    }
    assert len({f.smell for f in with_both.findings if f.counts}) == 1


def test_negation_plus_uncertain_verb_scores_like_the_verb_alone():
    # Same sentence, same word count, so the only difference is the negation.
    with_negation = smells.analyze_unit("El cupón no se puede aplicar hoy.", "criterio")
    without = smells.analyze_unit("El cupón ya se puede aplicar hoy.", "criterio")
    assert with_negation.words == without.words
    assert with_negation.clarity == pytest.approx(without.clarity)


def test_the_exclusion_table_is_explicit():
    assert smells.SMELLS_EXCLUDED_FROM_CLARITY_BY_UNIT["criterio"] == frozenset(
        {smells.S6_NEGATIVE}
    )
    assert smells.SMELLS_EXCLUDED_FROM_CLARITY_BY_UNIT["historia"] == frozenset()
    assert not smells.counts_for_clarity(smells.S6_NEGATIVE, "criterio")
    assert smells.counts_for_clarity(smells.S6_NEGATIVE, "historia")
    assert smells.counts_for_clarity(smells.S8_UNCERTAIN_VERBS, "criterio")


# --- fixed phrases are not comparatives ------------------------------------
def test_al_menos_is_not_a_comparative():
    assert smells.S5_COMPARATIVES not in smells_of("al menos un producto en el carrito")


def test_a_real_comparative_still_fires():
    assert smells.S5_COMPARATIVES in smells_of("más rápido que el anterior")


def test_por_lo_menos_is_not_a_comparative():
    assert smells.S5_COMPARATIVES not in smells_of("por lo menos tres resultados")


def test_the_suppressed_finding_is_gone_entirely():
    # Not a finding with counts=False: inside a fixed phrase it is no smell at
    # all, so nothing reaches the findings list.
    unit = smells.analyze_unit("El carrito tiene al menos un producto.", "criterio")
    assert [f for f in unit.findings if f.smell == smells.S5_COMPARATIVES] == []
    assert unit.clarity == 1.0


def test_every_listed_phrase_is_suppressed():
    for phrase in smells.COMPARATIVE_STOP_PHRASES:
        assert smells.S5_COMPARATIVES not in smells_of(
            f"El sistema espera {phrase} un resultado."
        ), phrase


def test_suppression_does_not_leak_to_other_smells():
    # "al menos" silences S5 on those tokens only; S8 elsewhere is untouched.
    found = smells_of("El sistema podría mostrar al menos un total.")
    assert smells.S8_UNCERTAIN_VERBS in found
    assert smells.S5_COMPARATIVES not in found
