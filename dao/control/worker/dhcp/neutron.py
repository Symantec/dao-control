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


import socket
from dao.common import config
from dao.common import log
from dao.control import exceptions
from dao.control import server_helper
from dao.control.worker.dhcp import agent
from dao.control.worker.openstack import neutron_helper


opts = [config.BoolOpt('dhcp', 'all_neutron',
                       default=True,
                       help='Use both neutron and DAO DHCPs if False'),
        config.StrOpt('dhcp', 'tftp', default='', help='TFTP address')
        ]

config.register(opts)
CONF = config.get_config()
logger = log.getLogger(__name__)


class NeutronHelper(agent.DHCPHelper):
    """
    Class implements DHCP interface to neutron.
    Base DHCPHelper is still used to support IPMI and gen2 hardware
    """
    pxe_net = 'mgmt'
    isc_nets = ['ipmi']
    device_owner = 'DAO'

    def __init__(self, worker):
        """
        :param worker: dao.control.worker.manager.Manager
        :return:
        """
        # Init vlan tags supported by DHCP helpers
        tftp_url = (CONF.dhcp.tftp or
                    CONF.foreman.url.split('://')[-1].rsplit(':')[0])
        ips = socket.gethostbyname_ex(tftp_url)[-1]
        if not ips:
            raise exceptions.DAOException('Unable to detect ip for {0}'.
                                          format(tftp_url))
        self.tftp_url = ips[0]
        super(NeutronHelper, self).__init__(worker)

    def allocate(self, rack, net, serial, mac, ip=''):
        """
        :type rack: dao.control.db.model.Rack
        :type net: dao.control.db.model.Subnet
        :type serial: str
        :type ip: str
        :type mac: str
        :rtype: None
        """
        net_type = self._ensure_subnet(net)
        if net_type not in self.isc_nets and \
                (CONF.dhcp.all_neutron or rack.neutron_dhcp):
            mac = mac.replace('-', ':').lower()
            port = self._create_port(net_type, rack.name,
                                     serial, mac, ip,
                                     pxe=self.pxe_net == net_type)
            return port['fixed_ips'][0]['ip_address']
        else:
            return super(NeutronHelper, self).allocate(rack, net,
                                                       serial, mac, ip)

    def _create_port(self, net_name, rack_name, serial, mac, ip, pxe=False):
        neutron = self._get_client()
        net_id = neutron.list_networks(name=net_name)['networks'][0]['id']
        ports = neutron.list_ports(network_id=net_id, mac_address=mac)
        if ports['ports']:
            port = ports['ports'][0]
            if port['device_owner'] not in ('', self.device_owner):
                raise exceptions.DAOConflict('Port {0} in use'.format(ip))
            old_ip = port['fixed_ips'][0]['ip_address']
            if ip and old_ip != ip:
                raise exceptions.DAOConflict('Port is already created, IP '
                                             'mismatch: {0} instead of {1}'.
                                             format(old_ip, ip))
        else:
            body = {'port': {'network_id': net_id,
                             'admin_state_up': True,
                             'mac_address': mac.replace('-', ':').lower(),
                             'device_owner': self.device_owner,
                             'device_id': serial}}
            if ip:
                body['port']['fixed_ips'] = [{'ip_address': ip}]
            else:
                subnet = neutron.list_subnets(
                    network_id=net_id,
                    name=rack_name.lower())['subnets'][0]
                body['port']['fixed_ips'] = [{'subnet_id': subnet['id']}]
            port = neutron.create_port(body)['port']
        if pxe:
            options = [{'opt_name': 'bootfile-name',
                        'opt_value': 'pxelinux.0'},
                       {'opt_name': 'server-ip-address',
                        'opt_value': self.tftp_url},
                       {'opt_name': 'tftp-server',
                        'opt_value': self.tftp_url}]
            port_req_body = {'port': {'extra_dhcp_opts': options}}
            neutron.update_port(port['id'], port_req_body)
        return port

    def delete_for_serial(self, serial, ignored=None):
        """
        :type serial: str
        :type ignored: str
        :rtype: None
        """
        neutron = self._get_client()
        if ignored:
            skip = neutron.list_networks(name=ignored)['networks']
            skip = [0]['id'] if skip else None
        else:
            skip = None
        ports = neutron.list_ports(device_id=serial,
                                   device_owner=self.device_owner)
        for port in ports['ports']:
            if port['network_id'] == skip:
                continue
            neutron.delete_port(port['id'])
        return super(NeutronHelper, self).delete_for_serial(serial, ignored)

    @staticmethod
    def _get_client():
        return neutron_helper.get_client()

    def _reinit_dhcp(self, rack2net):
        """
        :type rack2net: list of tuples(str, dao.control.db.model.Subnet)
        :return:
        """
        # Generate data
        vlan2net = server_helper.vlan2net()
        client = self._get_client()
        net2network = neutron_helper.networks_get(client)
        for rack, db_subnet in rack2net:
            net_name = vlan2net[db_subnet.vlan_tag]
            if net_name in self.isc_nets:
                continue
            n_network = net2network[net_name]
            if rack.lower() not in n_network['subnets']:
                neutron_helper.create_subnet(client, rack,
                                             n_network, db_subnet)
        return super(NeutronHelper, self)._reinit_dhcp(rack2net)
