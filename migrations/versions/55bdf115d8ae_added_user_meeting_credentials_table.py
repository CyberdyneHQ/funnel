"""Added user_meeting_credentials table
Revision ID: 55bdf115d8ae
Revises: 0fae06340346
Create Date: 2022-01-10 19:45:10.864289
"""

from alembic import op
import sqlalchemy as sa
import sqlalchemy_utils

# revision identifiers, used by Alembic.
revision = '55bdf115d8ae'
down_revision = '0fae06340346'
branch_labels = None
depends_on = None


def upgrade(engine_name=''):
    # Do not modify. Edit `upgrade_` instead
    globals().get('upgrade_%s' % engine_name, lambda: None)()


def downgrade(engine_name=''):
    # Do not modify. Edit `downgrade_` instead
    globals().get('downgrade_%s' % engine_name, lambda: None)()





def upgrade_():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('user_meeting_credentials',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('access_key', sa.String(length=100), nullable=True),
    sa.Column('secret_key', sa.String(length=100), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('provider', sa.String(length=100), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), nullable=True),
    sa.Column('is_default', sa.Boolean(), nullable=True),
    sa.Column('date_created', sa.DateTime(), nullable=True),
    sa.Column('uuid', sqlalchemy_utils.types.uuid.UUIDType(binary=False), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('uuid')
    )
    # ### end Alembic commands ###


def downgrade_():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('user_meeting_credentials')
    # ### end Alembic commands ###


def upgrade_geoname():
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###


def downgrade_geoname():
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###
