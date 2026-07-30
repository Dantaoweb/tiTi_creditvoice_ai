"""
School teacher roster routes: list, add (plan-limited), edit, delete.

Split out of web_routes.py. Register with register_school_routes(app);
shared helpers come from web_common.
"""
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User
from web_auth import require_web_auth
from web_common import _session_owner_phone


class SchoolTeacherRequest(BaseModel):
    name: str = Field(max_length=120)
    subject: Optional[str] = Field(default=None, max_length=60)
    class_name: Optional[str] = Field(default=None, max_length=60)
    phone: Optional[str] = Field(default=None, max_length=20)
    employee_id: Optional[str] = Field(default=None, max_length=60)


def register_school_routes(app):

    @app.get("/app/api/school/teachers")
    def web_school_teachers(session: dict = Depends(require_web_auth)):
        from models import SchoolTeacher
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            rows = db.query(SchoolTeacher).filter(
                SchoolTeacher.owner_phone == owner_phone
            ).order_by(SchoolTeacher.name).all()
            return {"teachers": [
                {"id": r.id, "name": r.name, "subject": r.subject,
                 "class_name": r.class_name, "phone": r.phone,
                 "employee_id": r.employee_id}
                for r in rows
            ]}
        finally:
            db.close()

    @app.post("/app/api/school/teachers")
    def web_add_school_teacher(
        payload: SchoolTeacherRequest,
        session: dict = Depends(require_web_auth),
    ):
        from models import SchoolTeacher
        from subscriptions import get_business_subscription
        from plans import plan_limit, normalize_plan
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            owner = db.query(User).filter(User.phone == owner_phone).first()
            sub = get_business_subscription(db, owner) if owner else None
            # sub is a dict — read its "plan" key (getattr never finds it, which
            # pinned upgraded schools to BASIC and capped them at 3 teachers).
            plan = normalize_plan((sub or {}).get("plan", "BASIC"))
            limit = plan_limit(plan, "school_teachers")
            if limit is not None:
                count = db.query(SchoolTeacher).filter(
                    SchoolTeacher.owner_phone == owner_phone
                ).count()
                if count >= limit:
                    raise HTTPException(
                        status_code=403,
                        detail=(
                            f"You have reached the Basic limit of {limit} teacher records. "
                            "Upgrade to Go or Pro to add more teachers."
                        ),
                    )
            teacher = SchoolTeacher(
                owner_phone=owner_phone,
                name=payload.name.strip(),
                subject=payload.subject,
                class_name=payload.class_name,
                phone=payload.phone,
                employee_id=payload.employee_id,
            )
            db.add(teacher)
            db.commit()
            db.refresh(teacher)
            return {"id": teacher.id, "name": teacher.name}
        finally:
            db.close()

    @app.put("/app/api/school/teachers/{teacher_id}")
    def web_edit_school_teacher(
        teacher_id: int,
        payload: SchoolTeacherRequest,
        session: dict = Depends(require_web_auth),
    ):
        from models import SchoolTeacher
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            teacher = db.query(SchoolTeacher).filter(
                SchoolTeacher.id == teacher_id,
                SchoolTeacher.owner_phone == owner_phone,
            ).first()
            if not teacher:
                raise HTTPException(status_code=404, detail="Teacher not found.")
            teacher.name       = payload.name.strip()
            teacher.subject    = payload.subject
            teacher.class_name = payload.class_name
            teacher.phone      = payload.phone
            teacher.employee_id = payload.employee_id
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.delete("/app/api/school/teachers/{teacher_id}")
    def web_delete_school_teacher(
        teacher_id: int,
        session: dict = Depends(require_web_auth),
    ):
        from models import SchoolTeacher
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            teacher = db.query(SchoolTeacher).filter(
                SchoolTeacher.id == teacher_id,
                SchoolTeacher.owner_phone == owner_phone,
            ).first()
            if not teacher:
                raise HTTPException(status_code=404, detail="Teacher not found.")
            from audit import audit
            audit(db, action="DELETE_TEACHER", actor_id=session["user_id"],
                  actor_phone=session["phone"], resource=f"teacher:{teacher_id}:{teacher.name}")
            db.delete(teacher)
            db.commit()
            return {"ok": True}
        finally:
            db.close()
