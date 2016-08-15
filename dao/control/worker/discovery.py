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


import netaddr
import pprint
import uuid

from dao.common import config
from dao.common import log
from dao.common import utils
from dao.control import exceptions
from dao.control import ipmi_helper
from dao.control import server_helper
from dao.control import server_processor
from dao.control.db import api as db_api
from dao.control.worker.switch import base as switch_base

opts = [
    config.BoolOpt('worker', 'discovery_disabled',
                   default=False,
                   help='Disable server auto discovery feature.'),
    config.BoolOpt('worker', 'discovery_log_only',
                   default=False,
                   help='Log only discovered servers.'),
    config.BoolOpt('worker', 'discovery_post_validation',
                   default=False,
                   help='Auto validate servers on discovery.'),
    config.StrOpt('worker', 'spare_cluster', default='spare-pool',
                  help='Name of a cluster to be used for discovered servers.'),
    config.StrOpt('worker', 'spare_role', default='spare',
                  help='Name of a role to be used for discovered servers.'),
    config.StrOpt('worker', 'spare_cluster_type', default='service',
                  help='Type of a spare cluster if being created.'),
]

config.register(opts)
CONF = config.get_config()
LOG = log.getLogger(__name__)


class Discovery(object):
    """Class implements Discovery code"""

    def __init__(self, worker, dhcp):
        """
        :type worker: dao.control.db.model.Worker
        :type dhcp: dao.control.worker.dhcp.base.DHCPBase
        :return:
        """
        self.db = db_api.Driver()
        self.mac2server = dict()
        self._processing = set()
        self._worker = worker
        self._spare_cluster = self._ensure_spare_cluster()
        self.dhcp = dhcp
        self._discovered = self._read_discovered()
        self._ignored = set()
        self._switch = switch_base.Base.get_helper(self.db)

    def cache_clean_for_mac(self, mac):
        self._ignored.discard(mac)

    def cache_clean(self):
        cache = self._ignored.copy()
        self._ignored.clear()
        return cache

    def server_delete(self, server):
        self._discovered.discard((server.asset.ip, server.asset.mac))

    def _read_discovered(self):
        assets = self.db.assets_get_by(**{'rack.worker_id': self._worker.id,
                                          'type': 'Server',
                                          'status': 'Discovered'})
        return set([(a.ip, a.mac) for a in assets])

    def _ensure_spare_cluster(self):
        try:
            return self.db.cluster_get(CONF.worker.spare_cluster)
        except exceptions.DAONotFound:
            return self.db.cluster_create(None,
                                          CONF.worker.spare_cluster,
                                          CONF.worker.spare_cluster_type)

    def dhcp_hook(self, ipmi_ip, ipmi_mac, force=False):
        """Process DHCP hook.
        :type ip: str
        :type asset_dict: dict
        :type interfaces: list of dict
        :rtype: dao.control.db.model.Server
        """
        if CONF.worker.discovery_disabled and not force:
            LOG.debug('discovery disabled')
            return
        ipmi_mac = str(netaddr.eui.EUI(ipmi_mac))
        if (ipmi_ip, ipmi_mac) in self._discovered:
            LOG.debug('%s already discovered', ipmi_ip)
            return
        if ipmi_mac in self._processing:
            LOG.debug('Mac in progress')
            return
        if ipmi_mac in self._ignored:
            LOG.debug('Mac ignored')
            return
        # Discovery enabled and is not in progress
        self._processing.add(ipmi_mac)
        LOG.debug('Add to processing: %s', ipmi_mac)
        try:
            # Check if server was discovered
            try:
                s = self.db.server_get_by(**{'asset.mac': ipmi_mac})
                self._discovered.add((s.asset.ip, s.asset.mac))
                raise exceptions.DAOIgnore('Server exists {0}'.
                                           format(ipmi_ip))
            except exceptions.DAONotFound:
                if CONF.worker.discovery_log_only:
                    LOG.info('TO be discovered: %s, %s', ipmi_ip, ipmi_mac)
                    self._ignored.add(ipmi_mac)
                    raise exceptions.DAOIgnore('Server to be discovered {0}'.
                                               format(ipmi_ip))
            # Ensure that ip is from ipmi network
            try:
                _ip = netaddr.IPAddress(ipmi_ip)
                ipmi_net = [_i for _i in self._subnets_get()
                            if _ip in _i.subnet][0]
            except IndexError:
                raise exceptions.DAOIgnore(
                    'IPMI subnet for {0} not found'.format(str(ipmi_ip)))

            # Check if rack is controlled by worker
            try:
                rack = self._rack_get_by_net_ip(ipmi_net.ip)
            except exceptions.DAONotFound:
                raise exceptions.DAOIgnore(
                    'No rack found for {0}'.format(ipmi_ip))
            if rack.worker_id != self._worker.id:
                raise exceptions.DAOIgnore(
                    'Rack {0} is not controlled by {1}'.
                    format(rack.name, self._worker.id))
            nets = self.db.subnets_get(rack_name=rack.name)
            asset, ipmi = self._ensure_asset(ipmi_ip, ipmi_mac, rack, nets)
            if asset.type == 'Server':
                # Asset is either found or created and is the server Asset.
                # Ensure server exists
                LOG.info('New server: %s, %s', ipmi_ip, asset.serial)
                self._discover_server(ipmi, rack, nets, asset)
            else:
                self._ignored.add(ipmi_mac)
        except exceptions.DAOIgnore, exc:
            LOG.debug('Asset ignored: %s', exc.message)
        except Exception, exc:
            LOG.warning('Discovery for %s failed: %s', ipmi_ip, exc.message)
            if 'is not supported' in exc.message:
                self._ignored.add(ipmi_mac)
            else:
                raise
        finally:
            self._processing.remove(ipmi_mac)

    def _ensure_asset(self, ipmi_ip, ipmi_mac, rack, nets):
        """
        Ensure asset in db. Raise DAOIgnore if asset is protected
        :type ipmi_ip: str
        :type ipmi_mac: str
        :type rack: dao.control.db.model.Rack
        :type nets: list of dao.control.db.model.Subnet
        :rtype: (dao.control.db.model.Asset,
                 dao.control.ipmi_helper.IPMIHelper)
        """
        ipmi = ipmi_helper.IPMIHelper.get_backend(ipmi_ip)
        serial = ipmi.serial
        ipmi_net = server_helper.network_get(nets, 'ipmi')
        try:
            asset = self.db.asset_get_by(serial=serial)
            if asset.mac and asset.mac != ipmi_mac:
                msg = ('MAC mismatch for ip:{0}, mac:{1}, serial: {2}'.
                       format(ipmi_ip, ipmi_mac, asset.serial))
                LOG.warning(msg)
                raise exceptions.DAOIgnore(msg)
            if asset.ip != ipmi_ip:
                asset.ip = ipmi_ip
                self.dhcp.allocate(rack, ipmi_net, serial, ipmi_mac, ipmi_ip)
            asset.mac = ipmi_mac
            asset.type = ipmi.asset_type
            if asset.protected:
                asset.status = 'New'
            asset = self.db.update(asset)
            if asset.protected:
                raise exceptions.DAOIgnore('Asset {0} is protected'.
                                           format(asset.serial))
        except exceptions.DAONotFound:
            self.dhcp.allocate(rack, ipmi_net, serial, ipmi_mac, ipmi_ip)
            LOG.info('Create asset for %s', ipmi_mac)
            asset = self.db.asset_create(rack,
                                         mac=ipmi_mac,
                                         ip=ipmi_ip,
                                         name=serial,
                                         serial=serial,
                                         location=rack.location,
                                         status='New',
                                         type=ipmi.asset_type)
        return asset, ipmi

    def _discover_server(self, ipmi, rack, nets, asset):
        """
        :type ipmi: dao.control.ipmi_helper.IPMIHelper
        :type rack: dao.control.db.model.Rack
        :type nets: list of dao.control.db.model.Subnet
        :type asset: dao.control.db.model.Asset
        :rtype: None
        """
        try:
            self.db.server_get_by(**{'asset.serial': asset.serial})
            raise exceptions.DAOIgnore('Server %s:%s exists' %
                                       (asset.serial, asset.ip))
        except exceptions.DAONotFound:
            pass
        mgmt_mac = ipmi.get_nic_mac(rack.network_map.pxe_nic)
        server = dict(pxe_mac=mgmt_mac,
                      pxe_ip='',
                      target_status='Validated',
                      status='Unmanaged',
                      os_args={},
                      role=CONF.worker.spare_role,
                      name='discovery_{0}'.format(asset.serial),
                      meta=dict(network={}),
                      lock_id='',
                      chassis_serial=ipmi.chassis_serial)
        server = self.db.server_create(self._spare_cluster,
                                       asset, **server)
        LOG.debug('Discovery: Server discovered: {0}'.format(
            pprint.pformat(server)))
        if CONF.worker.discovery_post_validation:
            server.lock_id = uuid.uuid4().get_hex()
            server = self.db.server_update(server, reload=True)
            server_processor.ServerProcessor(server).next()
            return True

    def finalize(self, server, asset_dict, interfaces):
        """Finalize server discovery.
        :type server: dao.control.db.model.Server
        :type asset_dict: dict
        :type interfaces: list of dict
        """
        # Fill in server
        for iface in interfaces:
            if iface['name'] not in server.interfaces:
                self.db.server_add_interface(server, mac=iface['mac'],
                                             name=iface['name'])
        # Server version is changed when interface is added
        server = self.db.server_get_by(id=server.id)

        # Generate server number and rack unit
        rack = server.asset.rack
        net_map = self.db.network_map_get_by(id=rack.network_map_id)
        number2unit = eval(net_map.number2unit)

        server_number = self._switch.server_number_get(rack, net_map, server)
        rack_unit = number2unit(server_number)

        server.server_number = str(server_number)
        server.rack_unit = rack_unit

        server.description = ('{asset.brand} {asset.model}, 2u, , ,'.
                              format(asset=server.asset))

        # Update asset. Can't use server one
        server.asset.brand = asset_dict['brand']
        server.asset.model = asset_dict['model']
        server.asset.status = 'Discovered'
        server.name = server.generate_name()
        server.fqdn = server_helper.fqdn_get(server)

        self.db.update(server.asset)
        self.db.server_update(server)

    @utils.CacheIt(180, ignore_self=True)
    def _subnets_get(self):
        return self.db.subnets_get_by(vlan_tag=CONF.worker.net2vlan['ipmi'])

    @utils.CacheIt(180, ignore_self=True)
    def _rack_get_by_net_ip(self, ip):
        return self.db.rack_get_by_subnet_ip(ip)
