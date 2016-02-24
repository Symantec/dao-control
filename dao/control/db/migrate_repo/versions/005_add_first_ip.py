from migrate import ForeignKeyConstraint
from sqlalchemy import Column, Table, MetaData, Index
import netaddr
import logging

from sqlalchemy import VARCHAR

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    subnet_table = Table('subnet', meta, autoload=True)

    first_ip = Column('first_ip', VARCHAR(length=31),)
    subnet_table.create_column(first_ip)


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    meta.bind = migrate_engine
    subnet_table = Table('subnet', meta, autoload=True)
    subnet_table.c.first_ip.drop()
