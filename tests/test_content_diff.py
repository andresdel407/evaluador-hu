"""
Content-diff tests: the deterministic side of the non-over-generation rule.

Comparison is by lemma over content words, so inflection and word order are not
new content. Test texts stay in Spanish because that is what the detector parses.
"""

import pytest

pytest.importorskip("spacy")

from app import smells  # noqa: E402

pytest.importorskip("es_core_news_sm")


def test_a_pure_reordering_adds_nothing():
    original = "El cupón se aplica al total del carrito."
    rewritten = "Al total del carrito se le aplica el cupón."
    assert smells.content_diff(original, rewritten)["terminos_agregados"] == []


def test_an_added_value_is_reported():
    original = "El cupón se aplica al total."
    rewritten = "El cupón aplica un descuento del 10% al total."
    added = smells.content_diff(original, rewritten)["terminos_agregados"]
    assert "descuento" in added
    # spaCy keeps "10%" as a single SYM token, so the threshold travels whole.
    assert any("10" in term for term in added)


def test_a_shorter_rewrite_reports_the_dropped_term():
    original = "El cupón expirado se rechaza y se muestra un mensaje."
    rewritten = "El cupón expirado se rechaza."
    removed = smells.content_diff(original, rewritten)["terminos_quitados"]
    assert "mensaje" in removed


def test_inflection_alone_is_not_new_content():
    added = smells.content_diff("El sistema rechaza los cupones.", "El sistema rechazó el cupón.")
    assert added["terminos_agregados"] == []


def test_empty_sides_do_not_blow_up():
    assert smells.content_diff("", "") == {
        "terminos_agregados": [],
        "terminos_quitados": [],
    }
    assert smells.content_diff("", "El cupón se aplica.")["terminos_agregados"]
