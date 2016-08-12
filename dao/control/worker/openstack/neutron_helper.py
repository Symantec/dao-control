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


import eventlet
from dao.common import config

clientv20 = eventlet.import_patched('neutronclient.v2_0.client')


CONF = config.get_config()


def get_client():
    neutron = clientv20.Client(
        auth_url=CONF.openstack.auth_url,
        region_name=CONF.openstack.region,
        username=CONF.openstack.username,
        password=CONF.openstack.password,
        tenant_name=CONF.openstack.project,
        insecure=CONF.openstack.insecure)
    return neutron


def networks_get(client):
    """
    :type client: clientv20.Client
    :type net_name: str
    :type rack_name: str
    :rtype: dict(net_name, network_dict)
    """
    networks = client.list_networks()['networks']
    # Build dictionary subnet_id: subnet
    subnets = client.list_subnets()['subnets']
    subnets = dict((_subnet['id'], _subnet) for _subnet in subnets)
    # Build final networks dictionary
    networks = dict((_net['name'], _net) for _net in networks)
    for net in networks.values():
        net['subnets'] = dict((subnets[s_id]['name'], subnets[s_id])
                              for s_id in net['subnets'])
    return networks


def create_subnet(client, rack_name, n_network, db_subnet):
    """
    :type client: clientv20.Client
    :type rack_name: str
    :type n_network: dict
    :type db_subnet: dao.control.db.model.Subnet
    :return: dict
    """
    dhcp_net = 'mgmt'
    ref_dict = dict(network_id=n_network['id'],
                    enable_dhcp=False,
                    gateway_ip=db_subnet.gateway,
                    ip_version=4,
                    name=rack_name.lower(),
                    cidr=str(db_subnet.subnet),
                    dns_nameservers=[CONF.worker.primary_dns,
                                     CONF.worker.secondary_dns])

    first = db_subnet.first_ip \
        if db_subnet.first_ip else db_subnet.subnet[CONF.dhcp.first_ip_offset]
    last = db_subnet.subnet[CONF.dhcp.last_ip_offset]
    pools = dict(start=str(first), end=str(last))
    ref_dict['allocation_pools'] = [pools]
    if n_network['name'] == dhcp_net:
        ref_dict['enable_dhcp'] = True
    return client.create_subnet({'subnet': ref_dict})
