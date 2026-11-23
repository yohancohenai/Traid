"""Player identity resolution. Conservative: fuzzy matches go to manual review, never auto-merged."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ttq.core.timeutil import utcnow
from ttq.identity.names import find_candidates, normalize_name
from ttq.models import IdentityReview, Player, PlayerAlias
from ttq.services.audit import audit


def resolve_player(db: Session, raw_name: str, source_key: str, source_ref: str | None = None,
                   is_demo: bool = False, create_if_new: bool = True) -> int | None:
    """Return a player id, or None if the identity is ambiguous and has been queued for review."""
    norm = normalize_name(raw_name)
    # 1. Exact source player id
    if source_ref:
        a = db.scalar(select(PlayerAlias).where(PlayerAlias.source_key == source_key,
                                                PlayerAlias.source_player_ref == source_ref))
        if a:
            return a.player_id
    # 2. Exact alias from same source
    a = db.scalar(select(PlayerAlias).where(PlayerAlias.source_key == source_key, PlayerAlias.alias == raw_name))
    if a:
        return a.player_id
    # 3. Exact normalised name, unique among players of the same demo/live domain
    exact = db.scalars(select(Player).where(Player.normalized_name == norm, Player.is_demo == is_demo)).all()
    if len(exact) == 1:
        _add_alias(db, exact[0].id, raw_name, norm, source_key, source_ref, "exact")
        return exact[0].id
    if len(exact) > 1:
        _queue(db, raw_name, norm, source_key, source_ref, [{"player_id": p.id, "name": p.canonical_name, "score": 1.0} for p in exact])
        return None
    # 4. Fuzzy candidates -> review, never merge
    pool = [(p.id, p.canonical_name) for p in db.scalars(select(Player).where(Player.is_demo == is_demo)).all()]
    cands = find_candidates(raw_name, pool)
    if source_ref and cands:
        # A candidate already known to this source under a DIFFERENT stable id is provably a different person.
        distinct = {a.player_id for a in db.scalars(select(PlayerAlias).where(
            PlayerAlias.source_key == source_key, PlayerAlias.source_player_ref.isnot(None),
            PlayerAlias.source_player_ref != source_ref)).all()}
        cands = [c for c in cands if c["player_id"] not in distinct]
    if cands:
        _queue(db, raw_name, norm, source_key, source_ref, cands)
        return None
    if not create_if_new:
        return None
    p = Player(canonical_name=raw_name.strip(), normalized_name=norm, is_demo=is_demo)
    db.add(p)
    db.flush()
    _add_alias(db, p.id, raw_name, norm, source_key, source_ref, "source_id" if source_ref else "exact")
    return p.id


def _add_alias(db, pid, raw, norm, source_key, source_ref, how):
    exists = db.scalar(select(PlayerAlias).where(PlayerAlias.source_key == source_key, PlayerAlias.alias == raw))
    if not exists:
        db.add(PlayerAlias(player_id=pid, alias=raw, normalized=norm, source_key=source_key,
                           source_player_ref=source_ref, confirmed_by=how))
        db.flush()


def _queue(db, raw, norm, source_key, source_ref, cands):
    open_ = db.scalar(select(IdentityReview).where(IdentityReview.raw_name == raw, IdentityReview.source_key == source_key,
                                                   IdentityReview.status == "OPEN"))
    if not open_:
        db.add(IdentityReview(raw_name=raw, normalized=norm, source_key=source_key, source_player_ref=source_ref,
                              candidates=cands))
        db.flush()


def resolve_review(db: Session, review_id: int, action: str, player_id: int | None, actor: str, is_demo: bool = False):
    r = db.get(IdentityReview, review_id)
    if not r or r.status != "OPEN":
        raise ValueError("review not open")
    if action == "MERGE":
        if not player_id or not db.get(Player, player_id):
            raise ValueError("player_id required for MERGE")
        _add_alias(db, player_id, r.raw_name, r.normalized, r.source_key, r.source_player_ref, "manual")
        r.status, r.resolved_player_id = "MERGED", player_id
    elif action == "NEW_PLAYER":
        p = Player(canonical_name=r.raw_name, normalized_name=r.normalized, is_demo=is_demo)
        db.add(p); db.flush()
        _add_alias(db, p.id, r.raw_name, r.normalized, r.source_key, r.source_player_ref, "manual")
        r.status, r.resolved_player_id = "NEW_PLAYER", p.id
    elif action == "REJECT":
        r.status = "REJECTED"
    else:
        raise ValueError("action must be MERGE | NEW_PLAYER | REJECT")
    r.resolved_at = utcnow()
    audit(db, actor, f"identity_{action.lower()}", "identity_review", review_id, player_id=r.resolved_player_id)
    return r
