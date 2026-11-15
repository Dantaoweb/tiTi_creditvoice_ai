"""
Recording works offline and is sent when the internet returns (the phone's
offline queue). On a weak signal a record can reach the server while its reply
is lost; the phone then sends it again. Every record from the phone carries its
own ID in the X-Client-Ref header: the first time it is done and the answer
kept; the same ID again gets that answer back and nothing is recorded twice.

Only POSTs under /app/api/ with the header are touched, and only answers that
succeeded are kept (a refused record can be fixed and sent again).
"""
import json
import re
from datetime import timedelta

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

KEEP_DAYS = 30
_REF = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _user_id(request):
    """The logged-in user — only a login that is still valid: not signed out
    everywhere since (token_version) and the account not removed. Otherwise
    nothing is replayed and the request goes through the normal login check."""
    from web_auth import verify_web_token
    token = request.cookies.get("cv_session") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    payload = verify_web_token(token) if token else None
    if not payload:
        return None
    from database import SessionLocal
    from models import User
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == payload["user_id"]).first()
        if not u or u.deleted_at or (u.token_version or 0) != payload.get("ver", 0):
            return None
        return u.id
    finally:
        db.close()


class ClientRefMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        ref = request.headers.get("x-client-ref", "")
        if request.method != "POST" or not request.url.path.startswith("/app/api/") or not _REF.match(ref):
            return await call_next(request)
        user_id = _user_id(request)
        if not user_id:
            return await call_next(request)

        from database import SessionLocal
        from models import ClientRequest
        db = SessionLocal()
        try:
            done = db.query(ClientRequest).filter(ClientRequest.user_id == user_id, ClientRequest.ref == ref).first()
            if done:
                return Response(content=done.body or "{}", status_code=done.status_code or 200,
                                media_type="application/json", headers={"X-Client-Ref-Replayed": "1"})
        finally:
            db.close()

        response = await call_next(request)
        if not 200 <= response.status_code < 300:
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        db = SessionLocal()
        try:
            from models import utcnow
            text = body.decode("utf-8", "replace")
            json.loads(text or "{}")                      # only JSON answers are kept
            db.add(ClientRequest(user_id=user_id, ref=ref, path=request.url.path[:200],
                                 status_code=response.status_code, body=text, created_at=utcnow()))
            # Now and then, forget answers older than KEEP_DAYS
            if ref[-1] in "0a":
                db.query(ClientRequest).filter(ClientRequest.created_at < utcnow() - timedelta(days=KEEP_DAYS)).delete()
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(content=body, status_code=response.status_code, headers=headers,
                        media_type=response.media_type)
