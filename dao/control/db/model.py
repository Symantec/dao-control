# Copyright 2016 Symantec, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


from datetime import datetime
import netaddr
import json

from sqlalchemy import inspect
from sqlalchemy import ForeignKey
from sqlalchemy import (Column, Integer, Boolean, String, Enum, Text)
from sqlalchemy.orm import class_mapper
from sqlalchemy.orm import relationship, backref
from sqlalchemy.orm import exc as sa_exc
from sqlalchemy.ext.declarative import declarative_base

from dao.control.db import model_base
from dao.control.db.model_base import (MutableDict, JSONEncodedDict)


class KeyMixin(object):
    """Mixin to be used during migration from YiDB to CMS"""
    key = Column(String(128))


class DaoBase(KeyMixin,
              model_base.TimestampMixin,
              model_base.SoftDeleteMixin,
              model_base.ModelBase):
    __table_args__ = {'mysql_engine': 'InnoDB'}
    metadata = None

    def save(self, session=None):
        from dao.control.db import session_api

        if session is None:
            session = session_api.get_session()

        super(DaoBase, self).save(session)

    def get_ref_cls(self, ref_name):
        mapper = class_mapper(self.__class__)
        return mapper.relationships[ref_name].argument.class_

    def to_dict(self, deep=True):
        def val2val(_x):
            if isinstance(_x, datetime):
                return str(_x)
            elif isinstance(_x, model_base.MutableDict):
                return _x.copy()
            else:
                return _x
        mapper = class_mapper(self.__class__)
        result = dict((col.name, val2val(getattr(self, col.name)))
                      for col in mapper.mapped_table.c)
        if deep:
            for k, v in mapper.relationships.items():
                try:
                    field = getattr(self, k)
                    if v.backref:
                        #to avoid recursion skip references with backref
                        continue
                    if field is None:
                        result[k] = None
                    elif v.uselist:
                        result[k] = [i.to_dict() for i in field]
                    else:
                        result[k] = field.to_dict()
                except sa_exc.DetachedInstanceError:
                    result[k] = None
        return result

    def get_changes(self):
        inspector = inspect(self)
        attributes = class_mapper(self.__class__).column_attrs
        new = dict()
        old = dict()
        for attr in attributes:
            history = getattr(inspector.attrs, attr.key).history
            if history.has_changes():
                new[attr.key] = history.added[0]
                old[attr.key] = history.deleted[0] if history.deleted else {}
        return new, old

    def __repr__(self):
        return str(self.to_dict(deep=False))

Base = declarative_base(cls=DaoBase)


class Sku(Base):
    """Class describes server type"""
    __tablename__ = 'sku'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    location = Column(String(31), nullable=False)
    description = Column(String(255))
    cpu = Column(String(255), nullable=False)
    ram = Column(String(255), nullable=False)
    storage = Column(String(255), nullable=False)


class Worker(Base):
    """Class describes worker"""
    __tablename__ = 'worker'
    id = Column(Integer, primary_key=True)
    name = Column(String(63), nullable=False)
    worker_url = Column(String(255), nullable=False)
    location = Column(String(31), nullable=False)


class NetworkMap(Base):
    __tablename__ = 'network_map'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    mgmt_port_map = Column(Text)
    number2unit = Column(Text)
    pxe_nic = Column(String(63))
    network = Column(Text)

    @property
    def network_map(self):
        #test if it is possible to have it as json natively. For YiDB not.
        return json.loads(self.network)


class Rack(Base):
    __tablename__ = 'rack'

    _indexes = {'nameIndex': ['index']}
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    location = Column(String(31), nullable=False)
    status = Column(String(31))
    gw_ip = Column(String(31), nullable=True)
    environment = Column(String(31), nullable=True)
    sku_quota = Column(MutableDict.as_mutable(JSONEncodedDict))
    network_map_id = Column(Integer,
                            ForeignKey('network_map.id'), nullable=True)
    worker_id = Column(Integer, ForeignKey('worker.id'), nullable=True)
    meta = Column(MutableDict.as_mutable(JSONEncodedDict))

    _network_map = relationship(
        NetworkMap, foreign_keys=network_map_id,
        primaryjoin=network_map_id == NetworkMap.id)
    _worker = relationship(
        Worker, foreign_keys=worker_id,
        primaryjoin=worker_id == Worker.id)

    def to_dict(self, deep=True):
        result = super(Rack, self).to_dict(deep)
        result['worker'] = result.pop('_worker', None)
        result['network_map'] = result.pop('_network_map', None)
        return result

    @property
    def network_map(self):
        return self._network_map

    @network_map.setter
    def network_map(self, network_map):
        """:type network_map: NetworkMap"""
        self.network_map_id = network_map.id

    @property
    def worker(self):
        return self._worker

    @worker.setter
    def worker(self, worker=None):
        """
        :type worker: Worker
        """
        self.worker_id = worker.id if worker is not None else None

    @property
    def neutron_dhcp(self):
        return bool(self.meta.get('neutron_dhcp', None))

    @neutron_dhcp.setter
    def neutron_dhcp(self, use_neutron):
        self.meta['neutron_dhcp'] = use_neutron


class Subnet(Base):
    __tablename__ = 'subnet'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    location = Column(String(31), nullable=False)
    ip = Column(String(31), nullable=False)
    mask = Column(String(31), nullable=False)
    vlan_tag = Column(Integer, nullable=False)
    gateway = Column(String(31), nullable=False)
    tagged = Column(Boolean, default=False)
    first_ip = Column(String(31))

    @property
    def subnet(self):
        return netaddr.IPNetwork('%s/%s' % (self.ip, self.mask), version=4)


class Asset(Base):
    __tablename__ = 'asset'

    _statuses = ['New', 'Discovered', 'DiscoveryMismatch', 'Decommissioned']
    id = Column(Integer, primary_key=True)
    name = Column(String(63), nullable=False)
    brand = Column(String(63))
    model = Column(String(63))
    serial = Column(String(63))
    mac = Column(String(31))
    ip = Column(String(127))
    type = Column(String(31), nullable=False)
    location = Column(String(31), nullable=False)
    asset_tag = Column(String(31))
    status = Column(Enum(*_statuses), default='New', nullable=False)
    protected = Column(Boolean, default=False, nullable=False)
    rack_id = Column(Integer, ForeignKey('rack.id'), nullable=True)

    rack = relationship(Rack, foreign_keys=rack_id,
                        primaryjoin=rack_id == Rack.id)


class Cluster(Base):
    __tablename__ = 'cluster'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    location = Column(String(31), nullable=False)
    type = Column(String(255), nullable=False)


class NetworkDevice(Base):
    __tablename__ = 'switch'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)

    asset_id = Column(Integer, ForeignKey('asset.id'), nullable=True)
    asset = relationship(Asset, foreign_keys=asset_id,
                         primaryjoin=asset_id == Asset.id)
    @property
    def rack_name(self):
        return self.asset.rack.name

    @property
    def interfaces(self):
        return dict((_if['name'], _if) for _if in (self._interfaces or []))


class NetworkInterfaceMixin(object):
    name = Column(String(63), nullable=False)
    mac = Column(String(31))

    @property
    def n_mac(self):
        # mac normalized for foreman. Ugly thing
        return self.mac.replace('-', ':').lower()


def _get_net_ip(context):
    params = context.current_parameters
    return str(netaddr.IPNetwork('{ip}/{mask}'.format(**params)).network)


class SwitchInterface(NetworkInterfaceMixin, Base):
    __tablename__ = 'switch_interface'

    id = Column(Integer, primary_key=True)
    ip = Column(String(15))
    mask = Column(String(15))
    gw = Column(String(31))
    net_ip = Column(String(31),
                    onupdate=_get_net_ip,
                    default=_get_net_ip)
    switch_id = Column(Integer, ForeignKey('switch.id'),
                       nullable=True)
    switch = relationship(NetworkDevice, foreign_keys=switch_id,
                          primaryjoin=switch_id == NetworkDevice.id,
                          backref=backref('_interfaces', uselist=True))


class Server(Base):
    __tablename__ = 'server'
    _statuses = ['Unmanaged', 'Unknown',
                 'Validating', 'ValidatedWithErrors', 'Validated',
                 'Provisioning', 'ProvisionedWithErrors', 'Provisioned',
                 'Deploying', 'DeployedWithErrors', 'Deployed']
    _target_statuses = ['Unmanaged', 'Validated', 'Provisioned', 'Deployed']

    id = Column(Integer, primary_key=True)

    name = Column(String(255), nullable=False)
    status = Column(Enum(*_statuses), default='New', nullable=False)

    pxe_ip = Column(String(15))
    pxe_mac = Column(String(31))

    role = Column(String(64))
    fqdn = Column(String(255))
    server_number = Column(String(15))

    rack_unit = Column(Integer)
    description = Column(Text)
    # Fields required by framework itself
    lock_id = Column(String(36))
    hdd_type = Column(String(127))
    os_args = Column(MutableDict.as_mutable(JSONEncodedDict))
    role_alias = Column(String(64))
    gw_ip = Column(String(15))
    target_status = Column(Enum(*_target_statuses),
                           default='Validated', nullable=False)
    message = Column(String(255))
    meta = Column(MutableDict.as_mutable(JSONEncodedDict))

    asset_id = Column(Integer, ForeignKey('asset.id'), nullable=True)
    asset = relationship(Asset, foreign_keys=asset_id,
                         primaryjoin=asset_id == Asset.id)

    cluster_id = Column(Integer, ForeignKey('cluster.id'), nullable=True)
    cluster = relationship(Cluster, foreign_keys=cluster_id,
                           primaryjoin=cluster_id == Cluster.id)

    sku_id = Column(Integer, ForeignKey('sku.id'), nullable=True)
    sku = relationship(Sku, foreign_keys=sku_id,
                       primaryjoin=sku_id == Sku.id)

    version = Column(Integer, nullable=False)

    __mapper_args__ = {
        "version_id_col": version
    }

    def to_dict(self, deep=True):
        result = super(Server, self).to_dict(deep)
        interfaces = result.pop('_interfaces', [])
        result['interfaces'] = dict((if_['name'], if_)
                                    for if_ in interfaces)
        return result

    @property
    def interfaces(self):
        return dict((_if['name'], _if) for _if in (self._interfaces or []))

    @property
    def cluster_name(self):
        return self.cluster.name

    def cluster_set(self, cluster):
        self.cluster_id = cluster.id

    @property
    def rack_name(self):
        return self.asset.rack.name

    @property
    def network(self):
        return self.meta.get('network', '{}')

    @network.setter
    def network(self, value):
        self.meta['network'] = value

    @property
    def initiator(self):
        return self.meta.get('initiator', None)

    @initiator.setter
    def initiator(self, username):
        self.meta['initiator'] = username

    def generate_name(self, environment=None, version='0.2'):
        environment = environment or self.asset.rack.environment
        if self.asset.status == 'Discovered':
            role = self.role_alias or self.role or self.status
            role = role[:8].lower()
            number = int(self.server_number)
            rack = self.rack_name.rsplit('-', 1)[-1].lower()
            return 'b-{role}-r{number:02d}{rack}-{environment}'.\
                format(**locals()).lower()
        else:
            return '-'.join(('discovery', self.asset.serial, environment))


class ServerInterface(NetworkInterfaceMixin, Base):
    __tablename__ = 'server_interface'
    id = Column(Integer, primary_key=True)

    server_id = Column(Integer, ForeignKey('server.id'), nullable=True)
    state = Column(String(16), default='')
    server = relationship(Server, foreign_keys=server_id,
                          primaryjoin=server_id == Server.id,
                          backref=backref('_interfaces', uselist=True))


class Port(Base):
    __tablename__ = 'port'
    id = Column(Integer, primary_key=True)
    device_id = Column(String(32), nullable=False)
    rack_name = Column(String(32), nullable=False)
    vlan_tag = Column(Integer, nullable=False)
    ip = Column(String(15))
    mac = Column(String(31))
    subnet_id = Column(Integer, ForeignKey('subnet.id'), nullable=False)


class ChangeLog(Base):
    __tablename__ = 'change_log'
    id = Column(Integer, primary_key=True)
    object_id = Column(Integer, nullable=False)
    type = Column(String(32), nullable=False)
    old = Column(JSONEncodedDict)
    new = Column(JSONEncodedDict)
