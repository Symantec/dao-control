from migrate import ForeignKeyConstraint
from sqlalchemy import Column, Table, MetaData, Index
import netaddr
import logging

from sqlalchemy import Integer

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    port_table = Table('port', meta, autoload=True)
    subnet_table = Table('subnet', meta, autoload=True)

    subnet_id = Column('subnet_id', Integer)
    port_table.create_column(subnet_id)

    ports = port_table.select().execute()
    subnets = subnet_table.select().execute()
    subnets = dict((netaddr.IPNetwork('%s/%s' % (net.ip, net.mask), version=4),
                   net.id) for net in subnets)

    for port in ports:
        match = [v for k, v in subnets.items()
                 if netaddr.IPAddress(port.ip) in k]
        if len(match) != 1:
            raise RuntimeError('More than one subnet matches %s' % port.ip)
        port_table.update().where(port_table.c.id == port.id).\
            values(subnet_id=match[0]).execute()

    port_table.c.subnet_id.alter(nullable=False)

    fkey = ForeignKeyConstraint(columns=[port_table.c.subnet_id],
                                refcolumns=[subnet_table.c.id])
    fkey.create()


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    meta.bind = migrate_engine

    port_table = Table('port', meta, autoload=True)
    subnet_table = Table('subnet', meta, autoload=True)

    for fk in port_table.foreign_keys:
        if fk.column == subnet_table.c.id:
            # Delete the FK
            fkey = ForeignKeyConstraint(columns=[port_table.c.subnet_id],
                                        refcolumns=[subnet_table.c.id],
                                        name=fk.name)
            fkey.drop()
            break
    port_table.c.subnet_id.drop()
