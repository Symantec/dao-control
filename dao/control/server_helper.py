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

import json
import re
from dao.common import config
from dao.common import exceptions


CONF = config.get_config()
RE_SWITCH_NAME = re.compile('trr([0-9]+)\-([^.]+)\.(.*)$')


def patch_interface_name(server, if_name):
    # Workaround OPENSTACK-1399
    if if_name in server.interfaces:
        return if_name
    else:
        i_re = re.compile('p([\d])p([\d])')
        x, y = i_re.findall(if_name)[0]
        ext = [i_re.findall(key) for key in server.interfaces.keys()]
        offset = int(min([i[0][0] for i in ext if i])) - 1
        return 'p{0}p{1}'.format(offset+int(x), y)


def fqdn_get(server, server_name=None):
    server_name = server_name or server.name
    return server_name + '.' + CONF.worker.default_dns_zone


def network_get(nets, name):
    type2net = dict((net.vlan_tag, net) for net in nets)
    return type2net[CONF.worker.net2vlan[name]]


def network_map_get(rack, server):
    network = json.loads(rack.network_map.network)
    bond = network.get('bond0')
    if bond:
        bond['interfaces'] = [patch_interface_name(server, if_name)
                              for if_name in bond['interfaces']]
    return network


def network_build(rack, server):
    network = network_map_get(rack, server)
    _vlan2net = dict((v['vlan'], (k, v)) for k, v in server.network.items())
    for net in network.values():
        if 'vlan' in net:
            name, ext = _vlan2net[net['vlan']]
            net['name'] = name
            net.update(ext)
    return network


def get_hook_path(server):
    """
    :type server: dao.control.db.model.Server
    :rtype: str
    """
    r_meta = server.asset.rack.meta
    hook_path = (r_meta['hook_cls'] if r_meta and 'hook_cls' in r_meta
                 else CONF.worker.hook)
    return hook_path


def network_build_patched(rack, server):
    """
    Function returns dictonary with all the interfaces that should be
    configured on the target OS
    :type rack: dao.control.db.model.Rack
    :type server: dao.control.db.model.Server
    :return: list
    """
    # The base iface order is what validation image has.
    def f_key(x):
        return ['phys', 'bond', 'symlink', 'tagged'].index(x[1]['type'])
    # If map for os family doesn't exist, use 1 to 1
    # Get initial network
    build_net = network_build(rack, server)
    # Append physical interfaces used for bond/vlan
    phys = dict((name, dict(name=name,
                            mac=server.interfaces[name].mac,
                            type='phys'))
                for name, net in server.interfaces.items())
    build_net.update(phys)
    return sorted(build_net.items(), key=f_key)


def vlan2net():
    return dict((vlan, net) for net, vlan in CONF.worker.net2vlan.items())


def net2vlan():
    return CONF.worker.net2vlan


def mac_get(network_map, vlan_tag, server):
    # Array to prevent looping
    passed = []
    _net_map = [i for i in network_map.values()
                if i.get('vlan') == vlan_tag][0]
    while True:
        _nested_iface = _net_map['interfaces'][0]
        # Check looping
        if _nested_iface in passed:
            raise exceptions.DAOException('Looping detected')
        # It is ok
        passed.append(_nested_iface)
        if _nested_iface not in network_map:
            _nested_iface = patch_interface_name(server, _nested_iface)
            return server.interfaces[_nested_iface].mac
        else:
            _net_map = network_map[_nested_iface]


def generate_network(dhcp, rack, server, nets):
    def _get_ip(_net):
        return dhcp.allocate(rack, _net, server.asset.serial,
                             mac_get(network, _net.vlan_tag, server))

    def net_item(vlan):
        return (_vlan2net[vlan], dict(ip=vlan2ip[vlan][0],
                                      mask=vlan2ip[vlan][1],
                                      gw=vlan2ip[vlan][2],
                                      vlan=vlan))

    network = rack.network_map.network_map
    _vlan2net = vlan2net()
    tags = [i['vlan'] for i in network.values() if 'vlan' in i]

    vlan2ip = dict((net.vlan_tag, (_get_ip(net), net.mask, net.gateway))
                   for net in nets if net.vlan_tag in tags)
    return dict(net_item(v['vlan']) for v in network.values() if 'vlan' in v)


def get_net2ip(server):
    v2n = vlan2net()
    nets = dict((v2n[net['vlan']], net['ip'])
                for net in server.network.values() if 'vlan' in net)
    nets.update({'ipmi': server.asset.ip, 'mgmt': server.pxe_ip})
    return nets


def get_net_ip(server, net):
    if net == 'ipmi':
        return server.asset.ip
    elif net == 'mgmt':
        return server.pxe_ip
    else:
        vlan = CONF.worker.net2vlan[net]
        ip = [i for i in server.network.values() if i.get('vlan') == vlan]
        if ip:
            return ip[0]['ip']
        else:
            raise exceptions.DAONotFound('IP not found for {0} and server {1}'.
                                         format(net, server.name))


def switch_name_parse(switch_name):
    """Function parse switch name using naming convention:
        ttr{index}-{rack_name}.{location}
       TODO: move it to dao.control/worker/switch
        :param switch_name: switch name to be parsed
        :return tuple(switch_index, rack_name)
    """
    result = RE_SWITCH_NAME.findall(switch_name)
    if not result:
        print result
        raise exceptions.DAOException('Unable to parse {0}'.
                                      format(switch_name))
    index, rack, dc = result[0]
    return int(index), '-'.join((dc, rack)).upper()
