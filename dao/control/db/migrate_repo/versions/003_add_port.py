from migrate import ForeignKeyConstraint
from sqlalchemy import Column, Table, MetaData, Index
import logging

from sqlalchemy.dialects.mysql.base import DATETIME
from sqlalchemy.dialects.mysql.base import INTEGER
from sqlalchemy.dialects.mysql.base import VARCHAR
from sqlalchemy.dialects.mysql.base import ENUM
from sqlalchemy.dialects.mysql.base import TINYINT
from sqlalchemy.dialects.mysql.base import TEXT

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    port = Table(
        'port', meta,
        Column('created_at', DATETIME),
        Column('updated_at', DATETIME),
        Column('deleted_at', DATETIME),
        Column('deleted', INTEGER(display_width=11)),
        Column('key', VARCHAR(length=128)),
        Column('id', INTEGER(display_width=11),
               primary_key=True, nullable=False),
        Column('device_id', VARCHAR(length=32), nullable=False),
        Column('rack_name', VARCHAR(length=32), nullable=False),
        Column('vlan_tag', INTEGER(display_width=11), nullable=False),
        Column('ip', VARCHAR(length=15)),
        Column('mac', VARCHAR(length=31)),
    )

    try:
        port.create()
    except Exception:
        LOG.info(repr(port))
        LOG.exception('Exception while creating table.')
        raise

    indexes = [
        Index('port_vlan_tag_idx', port.c.vlan_tag),
        Index('port_rack_name_idx', port.c.rack_name)
    ]

    for index in indexes:
        index.create(migrate_engine)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    table = Table('port', meta, autoload=True)
    table.drop()
