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
    asset = Table(
        'asset', meta,
        Column('created_at', DATETIME),
        Column('updated_at', DATETIME),
        Column('deleted_at', DATETIME),
        Column('deleted', INTEGER(display_width=11)),
        Column('key', VARCHAR(length=128)),
        Column('id', INTEGER(display_width=11),
               primary_key=True, nullable=False),
        Column('name', VARCHAR(length=63), nullable=False),
        Column('brand', VARCHAR(length=63)),
        Column('model', VARCHAR(length=63)),
        Column('serial', VARCHAR(length=63)),
        Column('mac', VARCHAR(length=31)),
        Column('ip', VARCHAR(length=127)),
        Column('type', VARCHAR(length=31), nullable=False),
        Column('location', VARCHAR(length=31), nullable=False),
        Column('asset_tag', VARCHAR(length=31)),
        Column('status', ENUM(u'New', u'Discovered',
                              u'DiscoveryMismatch', u'Decommissioned'),
               nullable=False),
        Column('protected', TINYINT(display_width=1), nullable=False),
        Column('rack_id', INTEGER(display_width=11)),
    )

    cluster = Table(
        'cluster', meta,
        Column('created_at', DATETIME),
        Column('updated_at', DATETIME),
        Column('deleted_at', DATETIME),
        Column('deleted', INTEGER(display_width=11)),
        Column('key', VARCHAR(length=128)),
        Column('id', INTEGER(display_width=11), primary_key=True,
               nullable=False),
        Column('name', VARCHAR(length=255), nullable=False),
        Column('location', VARCHAR(length=31), nullable=False),
        Column('type', VARCHAR(length=255), nullable=False),
    )

    network_map = Table(
        'network_map', meta,
        Column('created_at', DATETIME),
        Column('updated_at', DATETIME),
        Column('deleted_at', DATETIME),
        Column('deleted', INTEGER(display_width=11)),
        Column('key', VARCHAR(length=128)),
        Column('id', INTEGER(display_width=11),
               primary_key=True, nullable=False),
        Column('name', VARCHAR(length=255), nullable=False),
        Column('mgmt_port_map', TEXT),
        Column('number2unit', TEXT),
        Column('pxe_nic', VARCHAR(length=63)),
        Column('network', TEXT),
    )

    rack = Table(
        'rack', meta,
        Column('created_at', DATETIME),
        Column('updated_at', DATETIME),
        Column('deleted_at', DATETIME),
        Column('deleted', INTEGER(display_width=11)),
        Column('key', VARCHAR(length=128)),
        Column('id', INTEGER(display_width=11),
               primary_key=True, nullable=False),
        Column('name', VARCHAR(length=255), nullable=False),
        Column('location', VARCHAR(length=31), nullable=False),
        Column('status', VARCHAR(length=31)),
        Column('gw_ip', VARCHAR(length=31)),
        Column('environment', VARCHAR(length=31)),
        Column('sku_quota', TEXT),
        Column('network_map_id', INTEGER(display_width=11)),
        Column('worker_id', INTEGER(display_width=11)),
        Column('meta', TEXT),
    )

    server = Table(
        'server', meta,
        Column('created_at', DATETIME),
        Column('updated_at', DATETIME),
        Column('deleted_at', DATETIME),
        Column('deleted', INTEGER(display_width=11)),
        Column('key', VARCHAR(length=128)),
        Column('id', INTEGER(display_width=11),
               primary_key=True, nullable=False),
        Column('name', VARCHAR(length=255), nullable=False),
        Column('status',
               ENUM(u'Unmanaged', u'Unknown', u'Validating',
                    u'ValidatedWithErrors', u'Validated', u'Provisioning',
                    u'ProvisionedWithErrors', u'Provisioned', u'Deploying',
                    u'DeployedWithErrors', u'Deployed'),
               nullable=False),
        Column('pxe_ip', VARCHAR(length=15)),
        Column('pxe_mac', VARCHAR(length=31)),
        Column('role', VARCHAR(length=64)),
        Column('fqdn', VARCHAR(length=255)),
        Column('server_number', VARCHAR(length=15)),
        Column('rack_unit', INTEGER(display_width=11)),
        Column('description', TEXT),
        Column('lock_id', VARCHAR(length=36), nullable=False),
        Column('hdd_type', VARCHAR(length=127)),
        Column('os_args', TEXT),
        Column('role_alias', VARCHAR(length=64)),
        Column('gw_ip', VARCHAR(length=15)),
        Column('target_status',
               ENUM(u'Unmanaged', u'Validated', u'Provisioned', u'Deployed'),
               nullable=False),
        Column('message', VARCHAR(length=255)),
        Column('meta', TEXT),
        Column('asset_id', INTEGER(display_width=11)),
        Column('cluster_id', INTEGER(display_width=11)),
        Column('sku_id', INTEGER(display_width=11)),
        Column('version', INTEGER(display_width=11), nullable=False),
    )

    server_interface = Table(
        'server_interface', meta,
        Column('created_at', DATETIME),
        Column('updated_at', DATETIME),
        Column('deleted_at', DATETIME),
        Column('deleted', INTEGER(display_width=11)),
        Column('key', VARCHAR(length=128)),
        Column('name', VARCHAR(length=63), nullable=False),
        Column('mac', VARCHAR(length=31)),
        Column('id', INTEGER(display_width=11),
               primary_key=True, nullable=False),
        Column('server_id', INTEGER(display_width=11)),
        Column('state', VARCHAR(length=16)),
    )

    sku = Table(
        'sku', meta,
        Column('created_at', DATETIME),
        Column('updated_at', DATETIME),
        Column('deleted_at', DATETIME),
        Column('deleted', INTEGER(display_width=11)),
        Column('key', VARCHAR(length=128)),
        Column('id', INTEGER(display_width=11),
               primary_key=True, nullable=False),
        Column('name', VARCHAR(length=255), nullable=False),
        Column('location', VARCHAR(length=31), nullable=False),
        Column('description', VARCHAR(length=255)),
        Column('cpu', VARCHAR(length=255), nullable=False),
        Column('ram', VARCHAR(length=255), nullable=False),
        Column('storage', VARCHAR(length=255), nullable=False),
    )

    subnet = Table(
        'subnet', meta,
        Column('created_at', DATETIME),
        Column('updated_at', DATETIME),
        Column('deleted_at', DATETIME),
        Column('deleted', INTEGER(display_width=11)),
        Column('key', VARCHAR(length=128)),
        Column('id', INTEGER(display_width=11),
               primary_key=True, nullable=False),
        Column('name', VARCHAR(length=255), nullable=False),
        Column('location', VARCHAR(length=31), nullable=False),
        Column('ip', VARCHAR(length=31), nullable=False),
        Column('mask', VARCHAR(length=31), nullable=False),
        Column('vlan_tag', INTEGER(display_width=11),
               nullable=False),
        Column('gateway', VARCHAR(length=31), nullable=False),
        Column('tagged', TINYINT(display_width=1)),
    )

    switch = Table(
        'switch', meta,
        Column('created_at', DATETIME),
        Column('updated_at', DATETIME),
        Column('deleted_at', DATETIME),
        Column('deleted', INTEGER(display_width=11)),
        Column('key', VARCHAR(length=128)),
        Column('id', INTEGER(display_width=11),
               primary_key=True, nullable=False),
        Column('name', VARCHAR(length=255), nullable=False),
        Column('asset_id', INTEGER(display_width=11)),
    )

    switch_interface = Table(
        'switch_interface', meta,
        Column('created_at', DATETIME),
        Column('updated_at', DATETIME),
        Column('deleted_at', DATETIME),
        Column('deleted', INTEGER(display_width=11)),
        Column('key', VARCHAR(length=128)),
        Column('name', VARCHAR(length=63), nullable=False),
        Column('mac', VARCHAR(length=31)),
        Column('id', INTEGER(display_width=11),
               primary_key=True, nullable=False),
        Column('ip', VARCHAR(length=15)),
        Column('mask', VARCHAR(length=15)),
        Column('gw', VARCHAR(length=31)),
        Column('net_ip', VARCHAR(length=31)),
        Column('switch_id', INTEGER(display_width=11)),
    )

    worker = Table('worker', meta,
                   Column('created_at', DATETIME),
                   Column('updated_at', DATETIME),
                   Column('deleted_at', DATETIME),
                   Column('deleted', INTEGER(display_width=11)),
                   Column('key', VARCHAR(length=128)),
                   Column('id', INTEGER(display_width=11),
                          primary_key=True, nullable=False),
                   Column('name', VARCHAR(length=63), nullable=False),
                   Column('worker_url', VARCHAR(length=255), nullable=False),
                   Column('location', VARCHAR(length=31), nullable=False),
    )

    # create all tables
    tables = [cluster, sku, network_map, subnet,
              worker, rack, asset, server, server_interface,
              switch, switch_interface]

    for table in tables:
        try:
            table.create()
        except Exception:
            LOG.info(repr(table))
            LOG.exception('Exception while creating table.')
            raise

    indexes = [
        Index('asset_serial_idx', asset.c.serial),
        Index('asset_mac_idx', asset.c.mac),
        Index('server_name_idx', server.c.name),
        Index('server_status_idx', server.c.status),
    ]

    for index in indexes:
        index.create(migrate_engine)

    f_keys = [
        [[rack.c.network_map_id], [network_map.c.id]],
        [[rack.c.worker_id], [worker.c.id]],

        [[asset.c.rack_id], [rack.c.id]],

        [[switch.c.asset_id], [asset.c.id]],
        [[switch_interface.c.switch_id], [switch.c.id]],

        [[server.c.asset_id], [asset.c.id]],
        [[server.c.cluster_id], [cluster.c.id]],
        [[server.c.sku_id], [sku.c.id]],
        [[server_interface.c.server_id], [server.c.id]],
    ]

    for f_key_pair in f_keys:
        if migrate_engine.name in ('mysql', 'postgresql'):
            fkey = ForeignKeyConstraint(columns=f_key_pair[0],
                                        refcolumns=f_key_pair[1])
            fkey.create()


def downgrade(migrate_engine):
    raise NotImplementedError('Downgrade is unsupported.')
