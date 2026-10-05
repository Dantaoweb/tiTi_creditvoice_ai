"""
Everything a school runs on: the teacher roster, and the fee structure —
sessions and terms, classes, what each class is charged, registering a pupil,
opening a term, textbooks taken during it, and what the bursar chases.

The money itself is not special: a pupil is a Customer and a charge is an
ordinary credit transaction, so balances, receipts, debtors and reminders all
work without knowing anything about schools. See school_service.py.

Split out of web_routes.py. Register with register_school_routes(app);
shared helpers come from web_common.
"""
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User
from web_auth import require_web_auth
from web_common import _require_can_record, _session_owner_phone, _session_user


class SchoolTeacherRequest(BaseModel):
    name: str = Field(max_length=120)
    subject: Optional[str] = Field(default=None, max_length=60)
    class_name: Optional[str] = Field(default=None, max_length=60)
    phone: Optional[str] = Field(default=None, max_length=20)
    employee_id: Optional[str] = Field(default=None, max_length=60)


class SessionRequest(BaseModel):
    name: str = Field(max_length=40)                      # "2025/2026"


class ClassRequest(BaseModel):
    name: str = Field(max_length=60)
    level_order: int = 0
    teacher_id: Optional[int] = None
    is_active: bool = True


class FeeItemRequest(BaseModel):
    name: str = Field(max_length=80)
    kind: str = Field(default="FEE", max_length=20)
    default_amount: Optional[int] = None
    is_optional: bool = False
    is_active: bool = True


class ScheduleRequest(BaseModel):
    term_id: str = Field(max_length=64)
    class_id: str = Field(max_length=64)
    amounts: dict = {}                                    # {fee_item_id: amount}


class PupilRequest(BaseModel):
    name: str = Field(max_length=120)
    class_id: Optional[str] = Field(default=None, max_length=64)
    parent_name: Optional[str] = Field(default=None, max_length=120)
    parent_phone: Optional[str] = Field(default=None, max_length=20)
    admission_no: Optional[str] = Field(default=None, max_length=40)
    details: dict = {}            # answers to this school's own questions


class PupilFieldRequest(BaseModel):
    label: str = Field(max_length=60)
    field_type: str = Field(default="text", max_length=20)
    options: Optional[list] = None
    is_required: bool = False
    key: Optional[str] = Field(default=None, max_length=40)


class PupilFieldUpdateRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=60)
    field_type: Optional[str] = Field(default=None, max_length=20)
    options: Optional[list] = None
    is_required: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class PromoteRequest(BaseModel):
    customer_id: int
    class_id: str = Field(max_length=64)
    session_id: str = Field(max_length=64)


class ChargeRequest(BaseModel):
    customer_id: int
    term_id: Optional[str] = Field(default=None, max_length=64)
    items: list = []                                      # [{fee_item_id, quantity}]


class FeePaymentRequest(BaseModel):
    customer_id: int
    amount: int
    note: Optional[str] = Field(default=None, max_length=120)


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


    # ── Fee structure ─────────────────────────────────────────────────────────
    # Everything below answers one question a shop never has to ask: what is
    # owed this term, and by whom.

    def _owner(db, session):
        return _session_owner_phone(db, session)

    @app.get("/app/api/school/setup")
    def web_school_setup(session: dict = Depends(require_web_auth)):
        """Sessions, terms, classes and fee items — everything the screens need
        to draw themselves, in one call."""
        import school_service as school
        from models import AcademicSession, FeeItem, SchoolClass, SchoolTeacher, SchoolTerm
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            sessions = (db.query(AcademicSession)
                        .filter(AcademicSession.owner_phone == owner_phone)
                        .order_by(AcademicSession.created_at.desc()).all())
            terms = (db.query(SchoolTerm)
                     .filter(SchoolTerm.owner_phone == owner_phone)
                     .order_by(SchoolTerm.position.asc()).all())
            classes = (db.query(SchoolClass)
                       .filter(SchoolClass.owner_phone == owner_phone)
                       .order_by(SchoolClass.level_order.asc(), SchoolClass.name.asc()).all())
            items = (db.query(FeeItem)
                     .filter(FeeItem.owner_phone == owner_phone)
                     .order_by(FeeItem.is_optional.asc(), FeeItem.name.asc()).all())
            teachers = {t.id: t.name for t in db.query(SchoolTeacher).filter(
                SchoolTeacher.owner_phone == owner_phone).all()}
            current = school.current_term(db, owner_phone)
            return {
                "sessions": [{"id": s.id, "name": s.name, "is_current": bool(s.is_current)}
                             for s in sessions],
                "terms": [{"id": t.id, "session_id": t.session_id, "name": t.name,
                           "position": t.position, "is_current": bool(t.is_current),
                           "invoiced_at": t.invoiced_at.isoformat() if t.invoiced_at else None}
                          for t in terms],
                "classes": [{"id": c.id, "name": c.name, "level_order": c.level_order,
                             "teacher_id": c.teacher_id,
                             "teacher_name": teachers.get(c.teacher_id),
                             "is_active": bool(c.is_active)} for c in classes],
                "fee_items": [{"id": i.id, "name": i.name, "kind": i.kind,
                               "default_amount": i.default_amount,
                               "is_optional": bool(i.is_optional),
                               "is_active": bool(i.is_active)} for i in items],
                "current_term_id": current.id if current else None,
            }
        finally:
            db.close()

    @app.post("/app/api/school/sessions")
    def web_school_start_session(payload: SessionRequest,
                                 session: dict = Depends(require_web_auth)):
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            _require_can_record(db, session)
            new_session, terms = school.start_session(db, owner_phone, payload.name)
            return {"id": new_session.id, "name": new_session.name,
                    "terms": [{"id": t.id, "name": t.name} for t in terms]}
        finally:
            db.close()

    @app.post("/app/api/school/terms/{term_id}/current")
    def web_school_set_current_term(term_id: str,
                                    session: dict = Depends(require_web_auth)):
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            _require_can_record(db, session)
            term = school.set_current_term(db, owner_phone, term_id)
            if not term:
                raise HTTPException(status_code=404, detail="Term not found.")
            return {"id": term.id, "name": term.name}
        finally:
            db.close()

    @app.post("/app/api/school/classes")
    def web_school_add_class(payload: ClassRequest,
                             session: dict = Depends(require_web_auth)):
        from models import SchoolClass
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            _require_can_record(db, session)
            if not payload.name.strip():
                raise HTTPException(status_code=400, detail="A class needs a name.")
            row = SchoolClass(owner_phone=owner_phone, name=payload.name.strip(),
                              level_order=payload.level_order or 0,
                              teacher_id=payload.teacher_id,
                              is_active=payload.is_active)
            db.add(row)
            db.commit()
            db.refresh(row)
            return {"id": row.id, "name": row.name}
        finally:
            db.close()

    @app.put("/app/api/school/classes/{class_id}")
    def web_school_update_class(class_id: str, payload: ClassRequest,
                                session: dict = Depends(require_web_auth)):
        from models import SchoolClass
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            _require_can_record(db, session)
            row = db.query(SchoolClass).filter(SchoolClass.owner_phone == owner_phone,
                                               SchoolClass.id == class_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="Class not found.")
            row.name = payload.name.strip() or row.name
            row.level_order = payload.level_order or 0
            row.teacher_id = payload.teacher_id
            row.is_active = payload.is_active
            db.commit()
            return {"id": row.id, "name": row.name}
        finally:
            db.close()

    @app.post("/app/api/school/fee-items")
    def web_school_add_fee_item(payload: FeeItemRequest,
                                session: dict = Depends(require_web_auth)):
        import school_service as school
        from models import FeeItem
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            _require_can_record(db, session)
            kind = (payload.kind or "FEE").upper()
            if kind not in school.FEE_KINDS:
                raise HTTPException(status_code=400,
                                    detail=f"Kind must be one of: {', '.join(school.FEE_KINDS)}")
            if not payload.name.strip():
                raise HTTPException(status_code=400, detail="A fee item needs a name.")
            row = FeeItem(owner_phone=owner_phone, name=payload.name.strip(), kind=kind,
                          default_amount=payload.default_amount,
                          is_optional=payload.is_optional, is_active=payload.is_active)
            db.add(row)
            db.commit()
            db.refresh(row)
            return {"id": row.id, "name": row.name, "kind": row.kind}
        finally:
            db.close()

    @app.get("/app/api/school/schedule")
    def web_school_schedule(term_id: str, class_id: str,
                            session: dict = Depends(require_web_auth)):
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            rows = school.schedule_for(db, owner_phone, term_id, class_id)
            return {"schedule": rows, "total": sum(r["amount"] for r in rows
                                                   if not r["is_optional"])}
        finally:
            db.close()

    @app.post("/app/api/school/schedule")
    def web_school_set_schedule(payload: ScheduleRequest,
                                session: dict = Depends(require_web_auth)):
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            _require_can_record(db, session)
            rows = school.set_fee_schedule(db, owner_phone, payload.term_id,
                                           payload.class_id, payload.amounts or {})
            return {"schedule": rows}
        finally:
            db.close()

    # ── Pupils ────────────────────────────────────────────────────────────────

    @app.get("/app/api/school/pupils")
    def web_school_pupils(class_id: str = "", session: dict = Depends(require_web_auth)):
        import school_service as school
        from models import Customer, SchoolClass, StudentEnrolment
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            current = school.current_session(db, owner_phone)
            q = db.query(StudentEnrolment).filter(
                StudentEnrolment.owner_phone == owner_phone,
                StudentEnrolment.status == "ACTIVE")
            if current:
                q = q.filter(StudentEnrolment.session_id == current.id)
            if class_id:
                q = q.filter(StudentEnrolment.class_id == class_id)
            enrolments = q.all()
            if not enrolments:
                return {"pupils": []}
            customers = {c.id: c for c in db.query(Customer).filter(
                Customer.id.in_([e.customer_id for e in enrolments])).all()}
            classes = {c.id: c.name for c in db.query(SchoolClass).filter(
                SchoolClass.owner_phone == owner_phone).all()}
            pupils = []
            for e in enrolments:
                customer = customers.get(e.customer_id)
                if not customer:
                    continue
                pupils.append({
                    "customer_id": customer.id, "name": customer.name,
                    "admission_no": e.admission_no, "class_id": e.class_id,
                    "class_name": classes.get(e.class_id, "—"),
                    "parent_name": e.parent_name,
                    "parent_phone": customer.customer_phone,
                    "balance": int(customer.balance or 0),
                })
            pupils.sort(key=lambda p: p["name"].lower())
            return {"pupils": pupils}
        finally:
            db.close()

    @app.post("/app/api/school/pupils")
    def web_school_register_pupil(payload: PupilRequest,
                                  session: dict = Depends(require_web_auth)):
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            _require_can_record(db, session)
            try:
                customer, enrolment = school.register_pupil(
                    db, owner_phone, payload.name, class_id=payload.class_id,
                    parent_name=payload.parent_name, parent_phone=payload.parent_phone,
                    admission_no=payload.admission_no, details=payload.details or {},
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            return {"customer_id": customer.id, "name": customer.name,
                    "admission_no": enrolment.admission_no,
                    "details": school.pupil_details(db, owner_phone, customer)}
        finally:
            db.close()

    # ── What this school keeps about a pupil ──────────────────────────────────

    @app.get("/app/api/school/pupil-fields")
    def web_school_pupil_fields(session: dict = Depends(require_web_auth)):
        """The registration form this school has built, plus the library of
        common details it has not added yet."""
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            rows = school.pupil_fields(db, owner_phone, include_inactive=True)
            taken = {r.key for r in rows}
            return {
                "fields": [school.field_dict(r) for r in rows],
                "suggestions": [s for s in school.SUGGESTED_PUPIL_FIELDS
                                if s["key"] not in taken],
                "field_types": list(school.FIELD_TYPES),
            }
        finally:
            db.close()

    @app.post("/app/api/school/pupil-fields")
    def web_school_add_pupil_field(payload: PupilFieldRequest,
                                   session: dict = Depends(require_web_auth)):
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            _require_can_record(db, session, count_sale=False)
            try:
                row = school.add_pupil_field(
                    db, owner_phone, payload.label, payload.field_type,
                    payload.options, payload.is_required, payload.key)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            return school.field_dict(row)
        finally:
            db.close()

    @app.put("/app/api/school/pupil-fields/{field_id}")
    def web_school_update_pupil_field(field_id: str, payload: PupilFieldUpdateRequest,
                                      session: dict = Depends(require_web_auth)):
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            _require_can_record(db, session, count_sale=False)
            try:
                row = school.update_pupil_field(
                    db, owner_phone, field_id,
                    **{k: v for k, v in payload.dict().items() if v is not None})
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            if not row:
                raise HTTPException(status_code=404, detail="Field not found.")
            return school.field_dict(row)
        finally:
            db.close()

    @app.post("/app/api/school/promote")
    def web_school_promote(payload: PromoteRequest,
                           session: dict = Depends(require_web_auth)):
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            _require_can_record(db, session)
            enrolment = school.promote(db, owner_phone, payload.customer_id,
                                       payload.class_id, payload.session_id)
            return {"id": enrolment.id, "class_id": enrolment.class_id}
        finally:
            db.close()

    @app.get("/app/api/school/pupils/{customer_id}/statement")
    def web_school_statement(customer_id: int,
                             session: dict = Depends(require_web_auth)):
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            statement = school.student_statement(db, owner_phone, customer_id)
            if not statement:
                raise HTTPException(status_code=404, detail="Pupil not found.")
            return statement
        finally:
            db.close()

    # ── Charging and collecting ───────────────────────────────────────────────

    @app.post("/app/api/school/terms/{term_id}/open")
    def web_school_open_term(term_id: str, session: dict = Depends(require_web_auth)):
        """Charge every active pupil what their class owes this term."""
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            _require_can_record(db, session)
            user = _session_user(db, session)
            try:
                return school.open_term(db, owner_phone, term_id,
                                        recorded_by_id=user.id if user else None)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        finally:
            db.close()

    @app.post("/app/api/school/charge")
    def web_school_charge(payload: ChargeRequest,
                          session: dict = Depends(require_web_auth)):
        """A textbook or anything else taken during the term."""
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            _require_can_record(db, session)
            user = _session_user(db, session)
            term_id = payload.term_id
            if not term_id:
                current = school.current_term(db, owner_phone)
                term_id = current.id if current else None
            if not term_id:
                raise HTTPException(status_code=400, detail="No term is open yet.")
            try:
                invoice = school.charge_items(
                    db, owner_phone, payload.customer_id, term_id, payload.items,
                    recorded_by_id=user.id if user else None)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            if not invoice:
                raise HTTPException(status_code=400,
                                    detail="Nothing to charge — those items have no price.")
            return {"id": invoice.id, "total": invoice.total}
        finally:
            db.close()

    @app.post("/app/api/school/payments")
    def web_school_payment(payload: FeePaymentRequest,
                           session: dict = Depends(require_web_auth)):
        import school_service as school
        from models import Customer
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            # count_sale=False: a fee payment is money coming in. A school that
            # has hit the Basic cap must still be able to collect fees.
            _require_can_record(db, session, count_sale=False)
            user = _session_user(db, session)
            try:
                tx = school.record_payment(db, owner_phone, payload.customer_id,
                                           payload.amount, note=payload.note,
                                           recorded_by_id=user.id if user else None)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            balance = db.query(Customer.balance).filter(
                Customer.id == payload.customer_id).scalar() or 0
            return {"transaction_id": tx.id, "amount": tx.amount,
                    "balance": int(balance)}
        finally:
            db.close()

    # ── What the bursar reads ─────────────────────────────────────────────────

    @app.get("/app/api/school/term-summary")
    def web_school_term_summary(term_id: str = "",
                                session: dict = Depends(require_web_auth)):
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            if not term_id:
                current = school.current_term(db, owner_phone)
                term_id = current.id if current else ""
            if not term_id:
                return {"summary": None}
            return {"summary": school.term_summary(db, owner_phone, term_id)}
        finally:
            db.close()

    @app.get("/app/api/school/defaulters")
    def web_school_defaulters(term_id: str = "", class_id: str = "",
                              session: dict = Depends(require_web_auth)):
        import school_service as school
        db = SessionLocal()
        try:
            owner_phone = _owner(db, session)
            if not term_id:
                current = school.current_term(db, owner_phone)
                term_id = current.id if current else ""
            if not term_id:
                return {"defaulters": []}
            return {"defaulters": school.defaulters(db, owner_phone, term_id,
                                                    class_id or None)}
        finally:
            db.close()
