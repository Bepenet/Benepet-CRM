"""parcelas de venda

Revision ID: c7a1f0e93b84
Revises: f3832ca5ed7f
Create Date: 2026-09-30 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7a1f0e93b84'
down_revision = 'f3832ca5ed7f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('parcela_venda',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('venda_id', sa.Integer(), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('valor', sa.Float(), nullable=False),
    sa.Column('vencimento', sa.Date(), nullable=False),
    sa.Column('paga', sa.Boolean(), nullable=True),
    sa.Column('data_pagamento', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['venda_id'], ['venda.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_parcela_venda_vencimento', 'parcela_venda', ['vencimento'], unique=False)


def downgrade():
    op.drop_index('ix_parcela_venda_vencimento', table_name='parcela_venda')
    op.drop_table('parcela_venda')