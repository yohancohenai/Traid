from sqlalchemy.orm import Session
from ttq.models import AuditLog


def audit(db: Session, actor: str, action: str, entity: str, entity_id=None, **detail):
    db.add(AuditLog(actor=actor, action=action, entity=entity, entity_id=str(entity_id) if entity_id is not None else None,
                    detail={k: (v if isinstance(v, (int, float, str, bool, type(None), list, dict)) else str(v)) for k, v in detail.items()}))
