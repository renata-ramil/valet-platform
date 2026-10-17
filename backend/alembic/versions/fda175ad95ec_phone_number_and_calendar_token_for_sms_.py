"""phone number and calendar token for sms and ics feed

Revision ID: fda175ad95ec
Revises: 8cd9cd42d2da
Create Date: 2026-10-08 19:17:45.186487

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fda175ad95ec'
down_revision: Union[str, Sequence[str], None] = '8cd9cd42d2da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('phone_number', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('calendar_token', sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint('uq_users_phone_number', ['phone_number'])
        batch_op.create_unique_constraint('uq_users_calendar_token', ['calendar_token'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_constraint('uq_users_calendar_token', type_='unique')
        batch_op.drop_constraint('uq_users_phone_number', type_='unique')
        batch_op.drop_column('calendar_token')
        batch_op.drop_column('phone_number')
