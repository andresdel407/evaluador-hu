"""
Gate 1 tests.

The deterministic gate is the only part of the system testable without invoking
a model, which is exactly why it is worth covering: it is the baseline every
other measurement is taken against.
"""

from app import gate1


def failed_ids(story: str, criteria: str = "x") -> set[str]:
    return {c.id for c in gate1.run_gate1(story, criteria) if not c.passed}


def test_well_formed_story_passes():
    story = "Como cliente registrado quiero aplicar un cupón en el carrito para reducir el total."
    assert failed_ids(story) == set()


def test_detects_missing_role():
    story = "Quiero aplicar un cupón en el carrito para reducir el total de la compra."
    assert "well_formed" in failed_ids(story)


def test_detects_missing_means():
    story = "Como cliente registrado del sistema de compras en línea de la tienda."
    assert "well_formed" in failed_ids(story)


def test_conjunction_signals_non_atomicity():
    story = (
        "Como usuario quiero aplicar cupones de descuento y también quiero ver "
        "el historial de mis cupones usados para ahorrar dinero."
    )
    assert "atomic_hint" in failed_ids(story)


def test_conjunction_inside_the_goal_is_not_a_signal():
    # A "y" after the "para" does not mean two features: the gate only looks at
    # the means fragment. This is the false positive AQUSA reports.
    story = "Como cliente quiero cancelar un pedido para no recibirlo y no pagarlo."
    assert "atomic_hint" not in failed_ids(story)


def test_detects_acceptance_criteria_embedded_in_the_story():
    story = (
        "Como cliente quiero aplicar un cupón para pagar menos.\n"
        "- El cupón se aplica al total."
    )
    assert "minimal" in failed_ids(story)


def test_detects_missing_acceptance_criteria():
    story = "Como cliente registrado quiero aplicar un cupón en el carrito para pagar menos."
    assert "ac_present" in failed_ids(story, criteria="")


def test_only_hard_failures_block():
    hard = gate1.run_gate1("Cupones.", "")
    assert gate1.blocks(hard) is True

    soft = gate1.run_gate1(
        "Como usuario quiero aplicar cupones y también ver el historial para ahorrar.",
        "- algo",
    )
    # There is an atomicity signal, but that does not stop the flow: it travels
    # to gate 2.
    assert gate1.blocks(soft) is False


def test_summary_is_injectable_text():
    summary = gate1.summarize_for_prompt(
        gate1.run_gate1("Como cliente quiero X para Y.", "- algo")
    )
    assert "well_formed" in summary
    assert "\n" in summary
