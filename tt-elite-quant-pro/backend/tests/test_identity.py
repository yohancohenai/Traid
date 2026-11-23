from ttq.identity.names import normalize_name, find_candidates
from ttq.models import IdentityReview, Player
from ttq.services.identity import resolve_player, resolve_review


def test_polish_normalisation():
    assert normalize_name("Łukasz Wiśniewski") == normalize_name("WISNIEWSKI, Lukasz") == normalize_name("Lukasz  Wisniewski (POL)")
    assert normalize_name("Żółć Ąę") == "ae zolc"


def test_abbreviation_is_candidate_not_match():
    c = find_candidates("Kowalski J.", [(1, "Jan Kowalski"), (2, "Janusz Kowalski"), (3, "Piotr Nowak")])
    assert {x["player_id"] for x in c} == {1, 2}


def test_exact_links_and_fuzzy_never_merges(db):
    a = resolve_player(db, "Łukasz Wiśniewski", "src", None)
    assert resolve_player(db, "Lukasz Wisniewski", "src2", None) == a       # exact normalised -> same
    r = resolve_player(db, "Lukasz Wisniewsky", "src2", None)               # fuzzy -> queued, not merged
    assert r is None
    assert db.query(IdentityReview).filter_by(status="OPEN").count() == 1
    assert db.query(Player).count() == 1


def test_two_players_same_name_ambiguous(db):
    db.add_all([Player(canonical_name="Jan Kowalski", normalized_name=normalize_name("Jan Kowalski")),
                Player(canonical_name="Jan Kowalski", normalized_name=normalize_name("Jan Kowalski"))])
    db.flush()
    assert resolve_player(db, "Jan Kowalski", "new_src", None) is None
    assert db.query(IdentityReview).count() == 1


def test_distinct_source_ids_are_distinct_people(db):
    a = resolve_player(db, "Jan Kowalski", "s", "id1")
    b = resolve_player(db, "Janusz Kowalski", "s", "id2")
    assert a and b and a != b


def test_manual_merge(db):
    a = resolve_player(db, "Jan Kowalski", "s", None)
    assert resolve_player(db, "Kowalski J.", "s2", None) is None
    rv = db.query(IdentityReview).one()
    resolve_review(db, rv.id, "MERGE", a, "tester")
    assert resolve_player(db, "Kowalski J.", "s2", None) == a
