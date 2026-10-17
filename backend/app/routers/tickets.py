from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_csrf, scoped_query
from app.models import Role, Ticket, TicketMessage, User
from app.schemas import (
    TicketCreate,
    TicketMessageCreate,
    TicketResponse,
    TicketStatusUpdate,
)

router = APIRouter(prefix="/tickets", tags=["tickets"], dependencies=[Depends(require_csrf)])

STAFF_ROLES = (Role.manager, Role.support)


def _get_ticket_or_404(db: Session, user: User, ticket_id: str) -> Ticket:
    ticket = db.scalar(scoped_query(Ticket, user.building_id).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    if ticket.resident_id != user.id and user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this ticket")
    return ticket


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TicketResponse)
def create_ticket(
    payload: TicketCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Ticket:
    ticket = Ticket(
        building_id=user.building_id,
        resident_id=user.id,
        request_id=payload.request_id,
        subject=payload.subject,
    )
    db.add(ticket)
    db.flush()
    db.add(TicketMessage(ticket_id=ticket.id, author_id=user.id, body=payload.message))
    db.commit()
    db.refresh(ticket)
    return ticket


@router.get("", response_model=list[TicketResponse])
def list_tickets(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Ticket]:
    query = scoped_query(Ticket, user.building_id)
    if user.role not in STAFF_ROLES:
        query = query.where(Ticket.resident_id == user.id)
    return list(db.scalars(query))


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket(
    ticket_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Ticket:
    return _get_ticket_or_404(db, user, ticket_id)


@router.post("/{ticket_id}/messages", status_code=status.HTTP_201_CREATED)
def add_message(
    ticket_id: str,
    payload: TicketMessageCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ticket = _get_ticket_or_404(db, user, ticket_id)
    message = TicketMessage(ticket_id=ticket.id, author_id=user.id, body=payload.body)
    db.add(message)
    if user.role in STAFF_ROLES and ticket.status == "open":
        ticket.status = "waiting"
        db.add(ticket)
    db.commit()
    return {"status": "created"}


@router.patch("/{ticket_id}/status", response_model=TicketResponse)
def update_status(
    ticket_id: str,
    payload: TicketStatusUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Ticket:
    if user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only staff can change ticket status")
    ticket = _get_ticket_or_404(db, user, ticket_id)
    ticket.status = payload.status
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket
