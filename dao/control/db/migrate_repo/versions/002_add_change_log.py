from sqlalchemy import Column, Table, MetaData, Index
import logging

from sqlalchemy.dialects.mysql.base import DATETIME
from sqlalchemy.dialects.mysql.base import INTEGER
from sqlalchemy.dialects.mysql.base import VARCHAR
from sqlalchemy.dialects.mysql.base import TEXT

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    change_log = Table(
        'change_log', meta,
        Column('created_at', DATETIME),
        Column('updated_at', DATETIME),
        Column('deleted_at', DATETIME),
        Column('deleted', INTEGER(display_width=11)),
        Column('key', VARCHAR(length=128)),
        Column('id', INTEGER(display_width=11),
               primary_key=True, nullable=False),

        Column('object_id', INTEGER(display_width=11), nullable=False),
        Column('type', VARCHAR(length=32), nullable=False),
        Column('old', TEXT),
        Column('new', TEXT),
    )

    try:
        change_log.create()
    except Exception:
        LOG.info(repr(change_log))
        LOG.exception('Exception while creating table.')
        raise

    indexes = [
        Index('change_log_object_id_idx', change_log.c.object_id),
        Index('change_log_type_idx', change_log.c.type)
    ]

    for index in indexes:
        index.create(migrate_engine)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    table = Table('change_log', meta, autoload=True)
    table.drop()
