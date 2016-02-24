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

import datetime
import eventlet
import netaddr
import traceback
import uuid

from dao.common import log
from dao.common import rpc
from dao.common import config
from dao.control import exceptions
from dao.control import server_helper
from dao.control import server_processor
from dao.control import worker_api
from dao.control.db import api as db_api


opts = [config.StrOpt('master', 'port', default='5555',
                      help='port to access master')
        ]

config.register(opts)
CONF = config.get_config()

logger = log.getLogger(__name__)


class Context(object):
    def __init__(self, reply_to, user, location):
        self.reply_to = reply_to
        self.user = user
        self.location = location


class Manager(rpc.RPCServer):
    def __init__(self):
        super(Manager, self).__init__(CONF.master.port)
        self.db = db_api.Driver()

    def _call(self, reply_addr, func_name, args, kwargs):
        """
        :type reply_addr: str
        :type func_name: str
        :type args: list
        :type kwargs: dict
        :rtype: any
        """
        user, environment, args = args[0], args[1], args[2:]
        context = Context(reply_addr, user, environment)
        args = (context,) + args
        super(Manager, self)._call(reply_addr, func_name, args, kwargs)

    def objects_list(self, context, cls, joins, loads, **kwargs):
        return [obj.to_dict() for obj in
                self.db.objects_get_by(cls, joins, loads, **kwargs)]

    def object_update(self, context, object_type, key, key_value, args_dict):
        obj = self.db.object_get(object_type, key, key_value)
        for k, v in args_dict.items():
            setattr(obj, k, v)
        self.db.update(obj, log=True)

    def asset_protect(self, context, serial, rack_name, set_protected):
        rack = self.db.rack_get(name=rack_name)
        if rack.location != context.location:
            raise exceptions.DAOConflict('Rack {0} is not from {1}'.
                                         format(rack.name, context.location))
        try:
            asset = self.db.asset_get_by(serial=serial)
            if asset.rack.name != rack.name:
                raise exceptions.DAOConflict(
                    'Asset {serial} belongs to rack {asset.rack.name}'.
                    format(**locals()))
            asset.protected = set_protected
            asset = self.db.update(asset, log=True)
        except exceptions.DAONotFound:
            if set_protected:
                asset = self.db.asset_create(rack,
                                             serial=serial,
                                             type='Server',
                                             name=serial)
            else:
                raise
        return asset.to_dict()

    def worker_list(self, context):
        """Update rack with meta information"""
        workers = self.db.worker_list(location=context.location)
        return [w.to_dict() for w in workers]

    def history(self, context, obj_type, key, value):
        """Update rack with meta information"""
        if key and value:
            obj_id = self.db.object_get(obj_type, key, value).id
        else:
            obj_id = None
        history = [x.to_dict() for x in self.db.change_log(obj_type, obj_id)]
        return history

    def rack_discover(self, context, worker_name, switch_name, ip, create):
        worker = self._worker_get(context, worker_name=worker_name)
        worker = worker_api.WorkerAPI.get_api(worker=worker)
        return worker.call('rack_discover', switch_name, ip, create)

    def rack_renumber(self, context, rack_name, fake):
        worker = self._worker_get(context, rack_name=rack_name)
        worker = worker_api.WorkerAPI.get_api(worker=worker)
        return worker.call('rack_renumber', rack_name, fake)

    def dhcp_rack_update(self, context, rack_name):
        worker = self._worker_get(context, rack_name=rack_name)
        worker = worker_api.WorkerAPI.get_api(worker=worker)
        return worker.call('dhcp_rack_update', rack_name)

    def dhcp_hook(self, context, worker_name, ip, mac, force):
        worker = self._worker_get(context, worker_name=worker_name)
        worker = worker_api.WorkerAPI.get_api(worker=worker)
        return worker.send('dhcp_hook', ip, mac, force)

    def network_map_list(self, context, **kwargs):
        return [i.to_dict() for i in self.db.network_map_list(**kwargs)]

    def discovery_cache_reset(self, context, worker_name, mac):
        worker = self._worker_get(context, worker_name=worker_name)
        worker = worker_api.WorkerAPI.get_api(worker=worker)
        return worker.call('discovery_cache_reset', mac)

    def network_map_create(self, context, name, port2number, number2unit,
                           pxe_nic, network):
        net_map = self.db.network_map_create(
            name, port2number, number2unit, pxe_nic, network)
        return net_map.to_dict()

    def rack_update(self, context, rack_name, env, gw, net_map, worker_name,
                    reset_worker, meta):
        """Update rack with meta information"""
        rack = self.db.rack_get(name=rack_name)
        if rack.location != context.location:
            raise exceptions.DAOConflict('Rack {0} is not from {1}'.
                                         format(rack.name, context.location))
        if env:
            rack.environment = env
        if gw:
            # Chech if gateway is meaningful
            subnets = self.db.subnets_get(rack_name)
            gateway = netaddr.IPAddress(gw)
            for net in subnets:
                if gateway in net.subnet:
                    break
            else:
                raise exceptions.DAONotFound('There is no subnet for gateway')
            rack.gw_ip = gw
        if net_map:
            rack.network_map = self.db.network_map_get(name=net_map)
        if worker_name is not None:
            worker = self.db.worker_get(name=worker_name)
            rack.worker = worker
        elif reset_worker:
            worker = rack.worker
            rack.worker = None
        else:
            worker = None
        if meta:
            rack.meta = meta

        self.db.update(rack, log=True)

        if worker:
            api = worker_api.WorkerAPI.get_api(worker=worker)
            api.call('dhcp_rack_update', rack_name)
        return self.db.rack_get(name=rack_name).to_dict()

    def health_check(self, context, worker):
        worker = self._worker_get(context, worker_name=worker)
        worker = worker_api.WorkerAPI.get_api(worker=worker)
        return worker.call('health_check')

    def rack_trigger(self, context, rack_name, cluster_name, role, hdd_type,
                     serial, names, from_status, set_status, target_status,
                     os_args):

        rack = self.db.rack_get(name=rack_name)
        if rack.meta.get('maintenance', False):
            raise exceptions.DAOConflict('Rack is under maintenance')
        request_id = uuid.uuid4().get_hex()
        response = ['Request_id={0}'.format(request_id)]
        logger.info('Request id: {0}'.format(request_id))
        filters = {'asset.rack.location': context.location}
        if rack_name:
            filters['asset.rack.name'] = rack_name
        if serial:
            filters['asset.serial'] = serial
        if names:
            filters['name'] = names
        if from_status:
            filters['status'] = from_status
        servers = self.db.servers_get_by(**filters)
        if cluster_name:
            cluster = self.db.cluster_get(cluster_name)

        if not servers:
            raise exceptions.DAONotFound(
                'No servers were found. Please check filter conditions')
        for server in servers:
            old_status = server.status
            if server.lock_id:
                response.append('Server {0.id}:{0.name} is busy '
                                'with request {0.lock_id}'.format(server))
                continue
            if server.asset.protected:
                response.append('Server {0.id}:{0.name} is protected one'.
                                format(server))
                continue
            if server.meta.get('ironicated', False):
                response.append('Server {0.key}:{0.name} '
                                'is under Ironic control'.format(server))
                continue
            action = None
            if os_args:
                server.os_args = os_args
            if set_status is not None:
                server.status = set_status
            if role is not None:
                server.role = role
            if cluster_name:
                server.cluster_set(cluster)
            if target_status is not None:
                server.target_status = target_status
            if hdd_type is not None:
                server.hdd_type = hdd_type
            # Ensure current and target statuses
            _index = server_processor.ServerProcessor.statuses.index
            if _index(server.status) > _index(server.target_status):
                action = 'target status is less than current status. Ignored.'
            elif _index(server.target_status) >= _index('Provisioned'):
                # for some reason if cluster wasn't assigned cluster_id is '0'
                # because of this validate cluster_name
                if not cluster_name and not server.cluster_name:
                    action = 'cluster is not specified. Ignored.'
                elif not server.role:
                    action = 'role is not specified. Ignored.'
            # if everything is ok with parameters continue
            if not action:
                message = 'Pre-provision clean-up' \
                    if old_status != server.status else None
                server.lock_id = request_id
                server.initiator = context.user
                server = self.db.server_update(server, message, log=True)
                started = server_processor.ServerProcessor(server).next()
                if started:
                    action = 'Processing started' if started else 'ignored'
                else:
                    action = 'Fields update only, status={0}, ' \
                             'target_status={1}'.\
                        format(server.status, server.target_status)
            response.append('Server {0.id}:{0.name} {1}'.format(server,
                                                                action))
        return response

    @staticmethod
    def get_env(context):
        return dict(db_url=CONF.common.db_url)

    def server_delete(self, context, sid, serial, name):
        server = self.db.server_get_by(
            **{'id': int(sid), 'asset.serial': serial, 'name': name})
        if server.lock_id:
            raise exceptions.DAOConflict('Server {0} is busy'.format(name))
        worker = self._worker_get(context, rack_name=server.asset.rack.name)
        worker = worker_api.WorkerAPI.get_api(worker=worker)
        return worker.call('server_delete', server.id)

    def server_stop(self, context, request_id, names, rack_name, force):
        filters = dict()
        filters['asset.rack.location'] = context.location
        if request_id:
            filters['lock_id'] = request_id
        else:
            if not force:
                raise exceptions.DAOConflict(
                    'force is False and not request_id specified')
            if not rack_name and not names:
                raise exceptions.DAOConflict(
                    'force is True and names or rack_name used')
        if names:
            filters['name'] = names
        if rack_name:
            filters['asset.rack.name'] = rack_name

        servers = self.db.servers_get_by(**filters)
        response = []
        for server in servers:
            if server.lock_id:
                result = server_processor.ServerProcessor(server).stop()
                if result:
                    action = 'Stop sent'
                else:
                    server_processor.ServerProcessor(server).error('stop')
                    action = 'Force unlock'
                response.append('Server {0.name} {1}'.format(server, action))
        return response

    def servers_list(self, context, rack_name, cluster_name, serials, ips,
                     macs, names, from_status, sku_name, detailed):
        # get servers
        skus = self.db.sku_get_all() if detailed or sku_name else None
        filters = dict()
        filters['asset.rack.location'] = context.location
        if serials:
            filters['asset.serial'] = serials
        if rack_name:
            filters['asset.rack.name'] = rack_name
        if cluster_name:
            filters['cluster_id'] = self.db.cluster_get(cluster_name).id
        if from_status:
            filters['status'] = from_status
        if ips:
            filters['interfaces.ip'] = ips
        if macs:
            filters['interfaces.mac'] = [str(netaddr.eui.EUI(m)) for m in macs]

        if sku_name:
            try:
                filters['sku_id'] = [sku.id for sku in skus
                                     if sku.name == sku_name][0]
            except IndexError:
                raise exceptions.DAONotFound(
                    'SKU <{0}> not found'.format(sku_name))

        if names:
            filters['name'] = names
        servers = self.db.servers_get_by(**filters)
        # format servers output
        return self._servers2dict(servers, skus, detailed)

    @staticmethod
    def _servers2dict(servers, skus, detailed):
        def get_field(_field, _s_dict):
            _fields = _field.split('.')
            _it = _s_dict
            for _f in _fields:
                _it = _it.get(_f)
            return _it
        # format servers output
        fields = ['name', 'status', 'asset.rack.name', 'asset.asset_tag',
                  'asset.serial', 'lock_id', 'role', 'message']
        if detailed:
            sku2name = dict((sku.id, sku.name) for sku in skus)
            fields.extend(['id', 'hdd_type', 'meta', 'os_args', 'gw_ip',
                           'fqdn', 'target_status', 'cluster.name',
                           'interfaces', 'description', 'asset.protected',
                           'server_number', 'pxe_mac', 'pxe_ip', 'asset.ip',
                           'asset.mac', 'rack_unit', 'asset.key'])
        if_fields = ['state', 'mac', 'name']
        result = dict()
        for server in servers:
            s_dict = server.to_dict()
            s_dict = dict((item, get_field(item, s_dict))
                          for item in fields)
            if detailed:
                s_dict['updated'] = str(server.updated_at)
                s_dict['sku'] = sku2name.get(server.sku_id)
                interfaces = [dict((k, if_[k]) for k in if_fields)
                              for if_ in s_dict['interfaces'].values()]
                s_dict['interfaces'] = interfaces

            result[server.name] = s_dict
        return result

    def assets_list(self, context, rack_name, protected, names,
                    serials, type_):
        # get servers
        filters = dict()
        filters['rack.location'] = context.location
        if rack_name:
            filters['rack.name'] = rack_name
        if names:
            filters['name'] = names
        if protected:
            filters['protected'] = protected
        if serials:
            filters['serial'] = serials
        if type_:
            filters['type'] = type_

        assets = self.db.assets_get_by(**filters)
        fields = ['name', 'asset_tag', 'ip', 'mac', 'location', 'serial',
                  'status', 'type', 'protected', 'model', 'brand']
        result = [asset.to_dict(deep=False) for asset in assets]
        return result

    def rack_list(self, context, detailed, **kwargs):
        racks = self.db.rack_get_all(**kwargs)
        # TODO: Workaround. Apply filter on query step
        racks = [r for r in racks if r.location == context.location]
        result = {}
        for rack in racks:
            temp = dict(
                id=rack.id,
                name=rack.name,
                worker=rack.worker.name if rack.worker is not None else None,
                environment=rack.environment
            )
            if detailed:
                temp['networks'] = [net.to_dict() for net in
                                    self.db.subnets_get(rack.name)]
                temp['gw_ip'] = rack.gw_ip
                if rack.network_map is not None:
                    temp['pxe_nic'] = rack.network_map.pxe_nic
                    temp['mgmt_port_map'] = rack.network_map.mgmt_port_map
                    temp['network'] = rack.network_map.network
                else:
                    temp['pxe_nic'] = None
                    temp['mgmt_port_map'] = None
                    temp['network'] = None
                temp['sku_quota'] = rack.sku_quota.copy()
                temp['meta'] = rack.meta.copy()
            result[rack.name] = temp
        return result

    def cluster_list(self, context, detailed, **kwargs):
        clusters = self.db.cluster_list(**kwargs)
        # TODO: Workaround. Apply filter on query step
        clusters = [c for c in clusters if c.location == context.location]
        result = {}
        for cluster in clusters:
            c_dict = dict(
                id=cluster.id,
                name=cluster.name,
                type=cluster.type
            )
            if detailed:
                cs = [dict(name=s.name,
                           serial=s.asset.serial,
                           status=s.status)
                      for s in self.db.servers_get_by_cluster(cluster)]
                c_dict['servers'] = cs
            result[cluster.name] = c_dict
        return result

    def cluster_create(self, context, name, cluster_type):
        return self.db.cluster_create(context.location,
                                      name, cluster_type).to_dict()

    def sku_create(self, context, name, cpu, ram, storage, description):
        return self.db.sku_create(context.location, name, cpu, ram, storage,
                                  description).to_dict()

    def sku_list(self, context):
        return [i.to_dict() for i in self.db.sku_get_all(context.location)]

    def os_list(self, context, worker_name, os_name):
        worker = self._worker_get(context, worker_name=worker_name)
        worker = worker_api.WorkerAPI.get_api(worker=worker)
        return worker.call('os_list', os_name)

    def _worker_get(self, context, worker_name=None, rack_name=None):
        """
        :type context: dao.control.master.manager.Context
        :type worker_name: str
        :type rack_name: str
        :rtype: dao.control.db.model.Worker
        """
        filters = dict(location=context.location)
        if rack_name is not None:
            rack = self.db.rack_get(name=rack_name)
            filters['id'] = rack.worker.id
        if worker_name:
            filters['name'] = worker_name
        return self.db.worker_get(**filters)


def run():
    logger.info('Started')
    try:
        eventlet.monkey_patch()
        manager = Manager()
        manager.do_main()
    except:
        logger.warning(traceback.format_exc())
        raise
