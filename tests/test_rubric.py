"""
Rubric shape tests.

The rubric is the single source of truth for both the prompt and the API, so
its shape is worth pinning: a duplicated id would silently collide in LABELS,
and a renamed id would leave the server resolving a label it no longer has.
Criterion content stays Spanish; only the ids are code-facing.
"""

from app import rubric


ALL_CRITERIA = rubric.STORY_CRITERIA + rubric.AC_CRITERIA


def test_rubric_exposes_eight_criteria():
    assert len(rubric.STORY_CRITERIA) == 5
    assert len(rubric.AC_CRITERIA) == 3
    assert len(ALL_CRITERIA) == 8


def test_the_two_new_story_criteria_are_present():
    story_ids = [c.id for c in rubric.STORY_CRITERIA]
    assert "internally_consistent" in story_ids
    assert "aligned" in story_ids


def test_labels_resolve_the_new_ids():
    assert rubric.LABELS["internally_consistent"] == "Internamente consistente"
    assert rubric.LABELS["aligned"] == "Criterios alineados con la historia"


def test_no_duplicate_ids():
    ids = [c.id for c in ALL_CRITERIA]
    assert len(ids) == len(set(ids))


def test_conflict_free_is_gone():
    # The name is reserved for the backlog-level criterion, still pending.
    assert "conflict_free" not in {c.id for c in ALL_CRITERIA}


def test_aligned_is_a_story_level_criterion():
    # It looks at the relation between the two halves of the input, so it does
    # not belong to the AC block.
    assert "aligned" not in {c.id for c in rubric.AC_CRITERIA}


def test_aligned_does_not_claim_a_source_it_does_not_have():
    source = rubric.LABELS and next(c for c in ALL_CRITERIA if c.id == "aligned").fuente
    assert "QUS" not in source


def test_labels_covers_every_criterion():
    assert set(rubric.LABELS) == {c.id for c in ALL_CRITERIA}


def test_every_criterion_reaches_the_prompt():
    prompt = rubric.build_evaluation_prompt("G1")
    for criterion in ALL_CRITERIA:
        assert criterion.id in prompt
        assert criterion.definicion in prompt
