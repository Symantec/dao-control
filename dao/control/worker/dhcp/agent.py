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
import netaddr
from dao.common import config
from dao.common import log
from dao.common import rpc
from dao.common import utils
from dao.control import exceptions
from dao.control import server_helper
from dao.control.db import api as db_api
from dao.control.worker.dhcp import base


CONF = config.get_config()
logger = log.getLogger(__name__)


class DHCPHelper(base.DHCPBase):
    def __init__(self, worker):
        # Init vlan tags supported by DHCP helpers
        self.net2vlan = server_helper.net2vlan()
        self.tags = [self.net2vlan[net] for net in ['mgmt', 'ipmi']]

        self.db = db_api.Driver()
        self.dhcp_api = rpc.RPCApi(CONF.foreman.dhcp_proxy_url)
        self._worker = worker
        self._subnets = self._reinit_subnets()

    def allocate(self, rack, net, serial, mac, ip=''):
        """
        :type rack: dao.control.db.model.Rack
        :type net: dao.control.db.model.Subnet
        :type serial: str
        :type mac: str
        :type ip: str
        :rtype: str
        """
        net_type = self._ensure_subnet(net)
        port = self._create_isc_port(net, rack.name, serial, mac, ip)
        ip = port.ip
        if net_type in ('ipmi', 'mgmt'):
            result = self.dhcp_api.call('reload_allocations')
            if isinstance(result, Exception):
                raise exceptions.DAOException('Can not register DHCP: {msg}'.
                                              format(msg=repr(result)))
        return ip

    @utils.Synchronized('dao.control.worker.dhcp.agent._create_isc_port')
    def _create_isc_port(self, net, rack, serial, mac, ip):
        """
        :type rack: str
        :type net: dao.control.db.model.Subnet
        :type serial: str
        :type mac: str
        :type ip: str
        :rtype: dao.control.db.model.Port
        """
        ports = self.db.ports_list(vlan_tag=net.vlan_tag, rack_name=rack)
        allocated = [p for p in ports if p.device_id == serial]
        if allocated:
            port = allocated[0]
            if ip and port.ip != ip:
                raise exceptions.DAOConflict('Port is already created, IP '
                                             'mismatch: {0} instead of {1}'.
                                             format(port.ip, ip))
        else:
            if not ip:
                # TODO move this hardcode to config opt
                first = (netaddr.IPAddress(net.first_ip).value -
                         net.subnet.value
                         if net.first_ip else CONF.dhcp.first_ip_offset)
                subnet = net.subnet[first:CONF.dhcp.last_ip_offset]
                ips = set(netaddr.IPAddress(p.ip) for p in ports)
                ip = str(list(set(subnet).difference(ips))[0])
            port = self.db.port_create(rack, serial, net.vlan_tag,
                                       mac, ip, net.id)
        return port

    def delete_for_serial(self, serial, ignored=None):
        """
        :type serial: str
        :type ignored: str
        :rtype: None
        """
        ports = self.db.ports_list(device_id=serial)
        for port in ports:
            if ignored and port.vlan_tag == self.net2vlan[ignored]:
                continue
            self.db.object_delete(port)
        result = self.dhcp_api.call('reload_allocations')
        if isinstance(result, Exception):
            raise exceptions.DAOException('Can not delete DHCP: {msg}'.
                                          format(msg=repr(result)))

    def ensure_subnets(self, nets):
        """
        :type nets: dao.control.db.model.Subnet
        :return: None
        """
        for net in nets:
            if net.vlan_tag not in self.tags:
                continue
            self._ensure_subnet(net)

    @utils.Synchronized('dao.worker.dhcp_helper._ensure_subnet')
    def _ensure_subnet(self, subnet):
        if subnet.id not in self._subnets:
            self._subnets = self._reinit_subnets()
        return self._subnets[subnet.id]

    def _reinit_subnets(self):
        """
        Reinit DHCP to track all the subnets
        :return: dict, key is network id, value is network type
        :rtype: dict
        """
        # We need only ipmi and mgmt networks managed by DHCP
        vlan2net = server_helper.vlan2net()
        # Get all subnets for the location and then filter them by worker
        subnets = self.db.subnets_get_by()
        tors = self.db.network_device_get_by(
            **{'asset.rack.worker_id': self._worker.id})

        # Get list of lists of tuples (ip, rack_name)
        ip2rack = [[(i.net_ip, tor.asset.rack.name)
                    for i in tor.interfaces.values()] for tor in tors]
        ip2rack = dict(itertools.chain(*ip2rack))

        # Only subnets assigned to racks should be used
        rack2net = [(ip2rack[net.ip], net) for net in subnets
                    if net.ip in ip2rack]

        self._reinit_dhcp(rack2net)
        return dict((net.id, vlan2net[net.vlan_tag]) for net in subnets)

    def _reinit_dhcp(self, rack2net):
        # Preapare data for api call
        dhcp_api = rpc.RPCApi(CONF.foreman.dhcp_proxy_url)
        result = dhcp_api.call('update_networks')
        if isinstance(result, Exception):
            raise exceptions.DAOException('DHCP call {0} failed: {1}'.
                                          format('update_networks',
                                                 repr(result)))
