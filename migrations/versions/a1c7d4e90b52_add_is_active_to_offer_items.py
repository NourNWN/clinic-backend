"""add is_active to offer_items

Revision ID: a1c7d4e90b52
Revises: 4eb4bfec8bbc
Create Date: 2026-09-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c7d4e90b52'
down_revision = '4eb4bfec8bbc'
branch_labels = None
depends_on = None


def upgrade():
    # Existing rows are all still part of their offer, so they backfill to
    # true; the server default is then dropped so the model's default applies.
    with op.batch_alter_table('offer_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.alter_column('is_active', server_default=None)


def downgrade():
    with op.batch_alter_table('offer_items', schema=None) as batch_op:
        batch_op.drop_column('is_active')
