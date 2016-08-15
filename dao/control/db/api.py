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


import itertools
import six
from dao.common import config
from dao.control import exceptions
from dao.control.db import model as models
from dao.control.db.session_api import get_session, Session
from sqlalchemy import or_
from sqlalchemy.orm import exc as sa_exc
from sqlalchemy.orm import joinedload

CONF = config.get_config()


class Session(object):
    def __init__(self):
        self.session = None

    def __enter__(self):
        self.session = get_session()
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            self.session.close()


def _read_deleted_filter(query, db_model, deleted):
    if 'deleted' not in db_model.__table__.columns:
        raise ValueError(("There is no `deleted` column in `%s` table. "
                          "Project doesn't use soft-deleted feature.")
                         % db_model.__name__)

    default_deleted_value = db_model.__table__.c.deleted.default.arg
    if deleted:
        query = query.filter(db_model.deleted != default_deleted_value)
    else:
        query = query.filter(db_model.deleted == default_deleted_value)
    return query


def model_query(model,
                args=None,
                session=None,
                read_deleted='no'):
    """Query helper that accounts for context's `read_deleted` field.

    :param model:       Model to query. Must be a subclass of ModelBase.
    :param args:        Arguments to query. If None - model is used.
    :param session:     If present, the session to use.
    :param read_deleted: Permitted values are 'no', which does not return
                        deleted values; 'only', which only returns deleted
                        values; and 'yes', which does not filter deleted
                        values.
    """
    if not issubclass(model, models.Base):
        raise TypeError("model should be a subclass of ModelBase")

    if session is None:
        session = get_session()

    if 'no' == read_deleted:
        deleted = False
    elif 'only' == read_deleted:
        deleted = True
    elif 'yes' == read_deleted:
        deleted = None
    else:
        raise ValueError("Unrecognized read_deleted value '%s'" % read_deleted)

    query = session.query(model) if not args else session.query(*args)
    if deleted is not None:
        query = _read_deleted_filter(query, model, deleted)

    return query


class Driver(object):

    def __init__(self):
        # Patch exceptions
        sa_exc.NoResultFound = exceptions.DAONotFound

    def objects_get_by(self, cls, joins, loads, **kwargs):
        cls = getattr(models, cls)
        joins = [getattr(models, join) for join in joins]
        return self._object_get_by(cls, joins, loads, **kwargs).all()

    @staticmethod
    def worker_register(name, worker_url, location):
        """ Ensure worker record exists. Update worker_url field.
        :rtype: models.Worker
        """
        with Session() as session:
            try:
                worker = model_query(models.Worker, session=session).filter_by(
                    name=name, location=location).one()
                worker.worker_url = worker_url
                worker.save(session)
            except exceptions.DAONotFound:
                worker = models.Worker()
                worker.worker_url = worker_url
                worker.name = name
                worker.location = location
                worker.save(session)
            return worker

    @staticmethod
    def worker_get_by_rack(rack_name):
        """
        :type rack_name: str
        :rtype: models.Worker
        """
        worker = model_query(models.Worker).join(models.Rack)
        return worker.filter(models.Rack.name == rack_name).one()

    @staticmethod
    def worker_list(**kwargs):
        """
        :type kwargs: dict
        :rtype: list of models.Worker
        """
        return model_query(models.Worker).filter_by(**kwargs).all()

    @staticmethod
    def worker_get(**kwargs):
        """
        :type kwargs: dict
        :rtype: models.Worker
        """
        return model_query(models.Worker).filter_by(**kwargs).one()

    def sku_create(self, location, name, cpu, ram, storage, description=''):
        """ Create new SKU object
        :rtype: models.Sku
        """
        with Session() as session:
            try:
                self.sku_get(name)
                raise exceptions.DAOConflict('SKU <{0}> already exists'.
                                             format(name))
            except exceptions.DAONotFound:
                sku = models.Sku()
                sku.name = name
                sku.location = location or CONF.common.location
                sku.cpu = cpu
                sku.ram = ram
                sku.storage = storage
                sku.description = description
                sku.save(session)
                return sku

    @staticmethod
    def sku_get(sku_name):
        """ Request SKU object
        :rtype: models.Sku
        """
        query = model_query(models.Sku).filter_by(
            location=CONF.common.location, name=sku_name)
        return query.one()

    @staticmethod
    def sku_get_all(location=None):
        """ Request all SKU object
        :rtype: list of models.Sku
        """
        location = location or CONF.common.location
        return model_query(models.Sku).filter_by(location=location).all()

    @staticmethod
    def cluster_get(name):
        """ Request Cluster object by name
        :rtype: models.Cluster
        """
        return model_query(models.Cluster).filter_by(
            location=CONF.common.location, name=name).one()

    @staticmethod
    def cluster_list(**kwargs):
        """ Request Cluster objects by arguments
        :rtype: list of models.Cluster
        """
        return model_query(models.Cluster).filter_by(
            location=CONF.common.location, **kwargs).all()

    def cluster_create(self, location, name, cluster_type):
        """ Create Cluster object.
        :rtype: models.Cluster
        """
        try:
            self.cluster_get(name)
            raise exceptions.DAOConflict('Cluster {0} already exists'.
                                         format(name))
        except exceptions.DAONotFound:
            cluster = models.Cluster()
            cluster.name = name
            cluster.type = cluster_type
            cluster.location = location or CONF.common.location
            cluster.save()
            return cluster

    @staticmethod
    def network_map_list(**kwargs):
        """ Request list NetworkMap by arguments
        :rtype: list of models.NetworkMap
        """
        return model_query(models.NetworkMap).filter_by(**kwargs).all()

    @staticmethod
    def network_map_get(name):
        """ Request single NetworkMap by name
        :rtype: models.NetworkMap
        """
        return model_query(models.NetworkMap).filter_by(name=name).one()

    @staticmethod
    def network_map_get_by(**kwargs):
        """ Request single NetworkMap by arguments
        :rtype: models.NetworkMap
        """
        return model_query(models.NetworkMap).filter_by(**kwargs).one()

    def network_map_create(self, name, port2number, number2unit,
                           pxe_nic, network):
        """ Create NetworkMap new object
        :rtype: models.NetworkMap
        """
        try:
            self.network_map_get(name)
            raise exceptions.DAOConflict('Networking map {0} already exists'.
                                         format(name))
        except exceptions.DAONotFound:
            net_map = models.NetworkMap()
            net_map.name = name
            net_map.mgmt_port_map = port2number
            net_map.number2unit = number2unit
            net_map.pxe_nic = pxe_nic
            net_map.network = network
            net_map.save()
            return net_map

    @staticmethod
    def asset_create(rack, **kwargs):
        with Session() as session:
            asset = models.Asset()
            asset.update(kwargs)
            asset.rack_id = rack.id
            asset.save(session)
            return asset

    def assets_get_by(self, **kwargs):
        with Session() as session:
            r = self._object_get_by(models.Asset, [models.Rack], ['rack'],
                                    session=session, **kwargs)
            return r.all()

    def asset_get_by(self, **kwargs):
        with Session() as session:
            r = self._object_get_by(models.Asset, [models.Rack], ['rack'],
                                    session=session, **kwargs)
            return r.one()

    def subnets_get(self, rack_name, vlan=None):
        """
        Return list of dicts with info on subnets assigned to ToR switch.
        :type rack_name:
        :rtype: list of models.Subnet
        """
        nds = self.network_device_get_by_rack(rack_name)
        net_ips = [list(if_.net_ip for if_ in nd.interfaces.values()
                        if if_.net_ip)
                   for nd in nds]
        if net_ips:
            net_ips = list(itertools.chain(*net_ips))
            return self.subnets_get_by_ips(net_ips, vlan)
        else:
            return []

    @staticmethod
    def subnets_get_by_ips(ips, vlan=None):
        """
        Request subnets with specific ips and subnet type
        :type ips: list of str
        :type net_type: str
        :rtype: list of models.Subnet
        """
        obj_cls = models.Subnet
        ips = list(ips)
        if not ips:
            return []
        filters = [obj_cls.ip.in_(ips),
                   obj_cls.location == CONF.common.location]
        if vlan:
            filters.append(obj_cls.vlan_tag == vlan)
        query = model_query(obj_cls).filter(*filters)
        return query.all()

    def subnets_get_by(self, **kwargs):
        """
        Request subnets by parameters (joined by 'and' logic)
        :type kwargs: dict
        :rtype: list of models.Subnet
        """
        cls = models.Subnet
        filters = dict(location=CONF.common.location)
        filters.update(kwargs)
        return self._object_get_by(cls, [], [], **filters).all()

    def subnet_create(self, values):
        return self._create_object(models.Subnet, values)

    @classmethod
    def rack_get(cls, **kwargs):
        """
        :param kwargs: args to be used as a filter to get rack. Are joined
        using 'and' logic
        :rtype: models.Rack
        """
        with Session() as session:
            obj_cls = models.Rack
            return cls._object_get_by(
                obj_cls, [], ['_network_map', '_worker'],
                session=session,
                **kwargs).one()

    @staticmethod
    def rack_update(rack):
        """
        :type rack: models.Rack
        :rtype: models.Rack
        """
        with Session() as session:
            rack.save(session)
            return rack

    @classmethod
    def rack_get_by_subnet_ip(cls, ip):
        """
        :type ip: str
        :rtype: models.Rack
        """
        with Session() as session:
            nds = cls._object_get_by(
                models.NetworkDevice,
                [models.SwitchInterface],  # Join on interfaces
                ['asset.rack._network_map', '_interfaces'],
                session=session, **{'_interfaces.net_ip': ip}).all()
            racks = set(nd.asset.rack.id for nd in nds)
            if racks:
                if len(racks) == 1:
                    return nds[0].asset.rack
                else:
                    raise exceptions.DAOManyFound('More than one rack for {0}'.
                                                  format(ip))
            else:
                raise exceptions.DAONotFound('No rack found for {0}'.
                                             format(ip))

    @classmethod
    def rack_get_all(cls, **kwargs):
        """
        :type kwargs: dict
        :rtype: list of models.Rack
        """
        with Session() as session:
            joins = []
            if [k for k in kwargs.keys() if 'network_map.' in k]:
                joins.append(models.NetworkMap)
            if [k for k in kwargs.keys() if 'worker.' in k]:
                joins.append(models.Worker)
            return cls._object_get_by(models.Rack,
                                      joins,
                                      ['_worker', '_network_map'],
                                      session=session, **kwargs).all()

    def racks_get_by_worker(self, worker):
        """
        :rtype: list of models.Rack
        """
        return self.rack_get_all(**{'worker.id': worker.id})

    def rack_create(self, values):
        return self._create_object(models.Rack, values)

    @classmethod
    def _network_device_base(cls, join, **kwargs):
        load = ['asset.rack', '_interfaces']
        r = cls._object_get_by(models.NetworkDevice,
                               join,
                               load,
                               **kwargs)
        return r

    @classmethod
    def network_device_get_by_rack(cls, rack_name):
        join = [models.Asset, models.Rack]
        r = cls._network_device_base(join, **{'asset.rack.name': rack_name})
        return r.all()

    @classmethod
    def network_device_get_by(cls, **kwargs):
        join = [models.Asset, models.Rack]
        filters = {'asset.location': CONF.common.location}
        filters.update(kwargs)
        r = cls._network_device_base(join, **filters)
        return r.all()

    def server_create(self, cluster, asset, **kwargs):
        """

        :type server: models.Asset
        :return:
        """
        try:
            server = models.Server()
            server.update(kwargs)
            server.asset_id = asset.id
            server.cluster_id = cluster.id
            self.server_get_by(**{'asset.serial': asset.serial})
            raise exceptions.DAOConflict('Server %r exists' % server)
        except exceptions.DAONotFound:
            with Session() as session:
                server.save(session)
                return server

    @classmethod
    def server_update_sku(cls, server, sku):
        """Update single server using server key
        :type server: models.Server
        :type sku: models.Sku
        :rtype: models.Server"""
        server.sku_id = sku.id
        return cls.server_update(server)

    @classmethod
    def server_update(cls, server, comment=None, log=False, reload=False):
        """Update single server using server key
        :type server: models.Server
        :rtype: models.Server"""
        if comment is not None:
            server.message = comment
        cls.update(server, log=log)
        if reload:
            return cls.server_get_by(id=server.id)
        else:
            return server

    def servers_get_by_worker(self, worker, **kwargs):
        with Session() as session:
            kwargs['asset.rack.worker_id'] = worker.id
            return self.servers_get_by(session=session, **kwargs)

    @classmethod
    def servers_get_by(cls, **kwargs):
        """
        :param kwargs: filters joined by AND logic
        :rtype: list of models.Server
        """
        with Session() as session:
            join = [models.Asset, models.Rack]
            filters = {'asset.location': CONF.common.location}
            filters.update(kwargs)
            return cls._server_base(join, session=session, **filters).all()

    @classmethod
    def servers_get_by_cluster(cls, cluster):
        """
        :type cluster: models.Cluster
        :rtype: list of models.Server
        """
        return cls.servers_get_by(cluster_id=cluster.id)

    @classmethod
    def server_get_by(cls, **kwargs):
        """
        :param kwargs: filters joined by AND logic
        :rtype: models.Server
        """
        join = [models.Asset, models.Rack]
        filters = {'asset.location': CONF.common.location}
        filters.update(kwargs)
        with Session() as session:
            return cls._server_base(join, session=session, **filters).one()

    @classmethod
    def _server_base(cls, join, **kwargs):
        if [k for k in kwargs.keys() if k.startswith('interfaces.')]:
            join.append(models.ServerInterface)
        load = ['asset.rack._network_map', '_interfaces', 'cluster']
        r = cls._object_get_by(models.Server,
                               join, load, **kwargs)
        return r

    @staticmethod
    def server_add_interface(server, **kwargs):
        with Session() as session:
            iface = models.ServerInterface()
            for k, v in kwargs.items():
                setattr(iface, k, v)
            iface.server_id = server.id
            iface.save(session)

    def server_update_interface(self, interface):
        self._object_update(interface, force=True)

    @classmethod
    def pxe_boot_all(cls, **kwargs):
        """
        :param kwargs: filters joined by AND logic
        :rtype: list of models.PxEBoot
        """
        return cls._object_get_by(models.PxEBoot, [], [], **kwargs).all()

    @classmethod
    def pxe_boot_one(cls, **kwargs):
        """
        :param kwargs: filters joined by AND logic
        :rtype: models.PxEBoot
        """
        return cls._object_get_by(models.PxEBoot, [], [], **kwargs).one()

    @classmethod
    def pxe_boot_create(cls, serial, lock_id):
        """
        :param kwargs: filters joined by AND logic
        :rtype: models.PxEBoot
        """
        pxe_boot = models.PxEBoot()

        pxe_boot.serial = serial
        pxe_boot.lock_id = lock_id

        with Session() as session:
            pxe_boot.save(session)
            return pxe_boot

    def change_log(self, obj_type, obj_id):
        """
        Request change log from DB
        :param obj_type: Name of the DB object to inspect changes
        :type obj_type: str
        :param obj_id: key of the object to inspect changes
        :type obj_id: str
        :rtype: list of dao.control.db.model.ChangeLog
        """
        args = dict(type=obj_type)
        if obj_id:
            args['object_id'] = obj_id

        return self._object_get_by(models.ChangeLog, [], [], **args).all()

    def ports_list(self, **kwargs):
        """
        Request ports from DB
        :param kwargs: filters
        :type kwargs: dict
        :rtype: list of dao.control.db.model.Port
        """
        return self._object_get_by(models.Port, [], [], **kwargs).all()

    @staticmethod
    def port_create(rack_name, device_id, vlan_tag, mac, ip, subnet_id):
        """ Create new port record
        :type rack_name: str
        :type device_id: str
        :type vlan_tag: int
        :type mac: str
        :type ip: str
        :type subnet_id: int
        :rtype: dao.control.db.model.Port
        """
        with Session() as session:
            ports = model_query(models.Port, session=session).\
                filter_by(ip=ip).all()
            if ports:
                raise exceptions.DAOConflict('Port for ip %r exists' % ip)
            p = models.Port()
            p.device_id = device_id
            p.rack_name = rack_name
            p.vlan_tag = vlan_tag
            p.ip = ip
            p.mac = mac
            p.subnet_id = subnet_id
            p.save(session=session)
            return p

    @staticmethod
    def object_get(object_type, key, key_value):
        """
        Object get by key
        :param object_type: name of the DB object to get
        :type object_type: str
        :param key: name of the field used as a query key
        :type key: str
        :param key_value: value to be used for a query
        :type key_value: str
        :rtype: models.DaoBase
        """
        with Session() as session:
            obj_cls = getattr(models, object_type)
            key_field = getattr(obj_cls, key)
            return (model_query(obj_cls, session=session).
                    filter(key_field == key_value).one())

    @staticmethod
    def update(obj, log=False):
        with Session() as session:
            if log:
                log_obj = models.ChangeLog()
                log_obj.type = obj.__tablename__
                log_obj.object_id = obj.id
                log_obj.new, log_obj.old = obj.get_changes()
                log_obj.save()
            obj.save(session)
            return obj

    @staticmethod
    def object_create(obj):
        """
        Create DB object
        :type obj: models.DaoBase
        :return: Created object returned by DB
        :rtype: models.DaoBase
        """
        obj.save()
        return obj

    @staticmethod
    def object_delete(obj, soft=True):
        """
        Soft delete DB object
        :type obj: models.DaoBase
        :rtype: None
        """
        session = get_session()
        with session.begin():
            if soft:
                obj.soft_delete(session)
            else:
                session.delete(obj)

    @staticmethod
    def _create_object(cls, values):
        obj = cls()
        obj.update(values)
        obj.save()
        return obj

    @classmethod
    def _object_get_by(cls, obj_cls, joins, loads, **kwargs):
        """
        Build Query based on join and kwargs and run Request
        @type joins: list of BaseModel
        @type loads: list of strings
        """
        def arg2arg(_arg, _value):
            _arg = _arg.split('.')
            _cls = obj_cls
            for _ref_name in _arg[:-1]:
                attr = getattr(_cls, _ref_name)
                if isinstance(attr, property):
                    attr = getattr(_cls, '_' + _ref_name)
                _cls = attr.property.mapper.class_
            _attr = getattr(_cls, _arg[-1])
            if isinstance(_value, list):
                return _attr.in_(_value)
            else:
                return _attr == _value
        # Generate base query
        query = model_query(obj_cls, session=kwargs.pop('session', None))
        # Apply joins
        for join in joins:
            query = query.join(join)
        # Apply joined loads one by one
        for load in loads:
            load = load.split('.')
            j_load = joinedload(load[0])
            for field in load[1:]:
                j_load = j_load.joinedload(field)
            query = query.options(j_load)

        query_arg = [arg2arg(k, v) for k, v in six.iteritems(kwargs)]
        return query.filter(*query_arg)
