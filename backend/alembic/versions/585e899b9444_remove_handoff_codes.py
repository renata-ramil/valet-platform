"""remove handoff codes

Revision ID: 585e899b9444
Revises: 6b3daf93f927
Create Date: 2026-10-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '585e899b9444'
down_revision: Union[str, Sequence[str], None] = '6b3daf93f927'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Dropping the one-time handoff code table: the lifecycle no longer has resident
    # confirmation entirely, so no code is ever generated or checked
    op.drop_index(op.f('ix_handoff_codes_request_id'), table_name='handoff_codes')
    op.drop_index(op.f('ix_handoff_codes_building_id'), table_name='handoff_codes')
    op.drop_table('handoff_codes')


def downgrade() -> None:
    """Downgrade schema."""
    # Recreating the table exactly as it was created in
    # 4b72bf4de46c_valet_queue_manager_support_tickets.py
    op.create_table(
        'handoff_codes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('request_id', sa.String(length=36), nullable=False),
        sa.Column('building_id', sa.String(length=36), nullable=False),
        sa.Column('code_hash', sa.String(length=255), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['building_id'], ['buildings.id'], ),
        sa.ForeignKeyConstraint(['request_id'], ['requests.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_handoff_codes_building_id'), 'handoff_codes', ['building_id'], unique=False
    )
    op.create_index(
        op.f('ix_handoff_codes_request_id'), 'handoff_codes', ['request_id'], unique=False
    )
