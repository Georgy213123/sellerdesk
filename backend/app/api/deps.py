from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Operator
from app.security import decode_token

bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[Session, Depends(get_session)]


def current_operator(
    session: SessionDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Operator:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нужен вход", headers={"WWW-Authenticate": "Bearer"})
    operator_id = decode_token(creds.credentials)
    operator = session.get(Operator, operator_id) if operator_id is not None else None
    if operator is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "сессия истекла", headers={"WWW-Authenticate": "Bearer"})
    return operator


OperatorDep = Annotated[Operator, Depends(current_operator)]
