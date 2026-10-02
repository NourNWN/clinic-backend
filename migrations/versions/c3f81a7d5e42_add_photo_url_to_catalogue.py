"""add photo_url to services, service_variants and offers

Revision ID: c3f81a7d5e42
Revises: a1c7d4e90b52
Create Date: 2026-09-04 12:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3f81a7d5e42'
down_revision = 'a1c7d4e90b52'
branch_labels = None
depends_on = None


def upgrade():
    # The column is nullable with no default, so existing rows need no
    # backfill: a catalogue entry without a photo reads as NULL and the site
    # keeps drawing the category icon it already falls back to.
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.add_column(sa.Column('photo_url', sa.String(length=255), nullable=True))

    with op.batch_alter_table('service_variants', schema=None) as batch_op:
        batch_op.add_column(sa.Column('photo_url', sa.String(length=255), nullable=True))

    with op.batch_alter_table('offers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('photo_url', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('offers', schema=None) as batch_op:
        batch_op.drop_column('photo_url')

    with op.batch_alter_table('service_variants', schema=None) as batch_op:
        batch_op.drop_column('photo_url')

    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.drop_column('photo_url')
