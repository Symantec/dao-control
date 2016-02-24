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

from dao.common import config
from dao.control import exceptions
from dao.control.db import model as db_model
from dao.control.db import api as db_api


CONF = config.get_config()
TAGGED_VLANS = [100, 200, 300]


def rack_ensure(db, rack_name):
    """
    :type db: db_api.Driver
    :return: db_model.Rack
    """
    try:
        return db.rack_get(name=rack_name)
    except exceptions.DAONotFound:
        r = db_model.Rack()
        r.name = rack_name
        r.location = CONF.common.location
        return db.object_create(r)


def subnet_ensure(db, rack, vlan, ip, gw, mask_len):
    vlan2net = dict((v, k) for k, v in CONF.worker.net2vlan.items())
    net_type = vlan2net.get(vlan)
    ip_net = netaddr.IPNetwork('{0}/{1}'.format(ip, mask_len))
    if not net_type:
        return None
    # Get or create subnet
    subnet = db.subnets_get_by(ip=str(ip_net.network), vlan_tag=vlan)
    if subnet:
        subnet = subnet[0]
    else:
        net_type = vlan2net[vlan]

        subnet = db_model.Subnet()
        subnet.name = '-'.join((rack.name, net_type))
        subnet.location = rack.location
        subnet.type = net_type
        subnet.ip = str(ip_net.network)
        subnet.mask = str(ip_net.netmask)
        subnet.vlan_tag = vlan
        subnet.tagged = vlan in TAGGED_VLANS
        subnet.gateway = str(gw)
        subnet = db.object_create(subnet)
    return subnet


def interfaces_ensure(db, db_switch, interfaces):
    cls = db_model.SwitchInterface
    for name, iface in interfaces.items():
        try:
            db_api.model_query(cls).filter_by(switch_id=db_switch.id,
                                              ip=iface.ip).one()
        except exceptions.DAONotFound:
            db_if = cls()
            vlan = iface.vlan
            ip = iface.ip
            gw = iface.gw
            mask_len = iface.mask_len
            subnet = subnet_ensure(db, db_switch.asset.rack,
                                   vlan, ip, gw, mask_len)
            if subnet is None:
                continue
            db_if.name = name
            db_if.ip = ip
            db_if.mask = subnet.mask
            db_if.mac = ''
            db_if.gw = iface.gw
            db_if.state = iface.up
            db_if.switch_id = db_switch.id
            db.object_create(db_if)


def switch_ensure(db, hostname, ip, rack, brand, model, serial, interfaces):
    """
    :param db: db_api.Driver
    :param rack: db_model.Rack
    :rtype: db_model.NetworkDevice
    """
    try:
        asset = db.asset_get_by(serial=serial)
    except exceptions.DAONotFound:
        asset = db_model.Asset()
        asset.name = serial
        asset.brand = brand
        asset.model = model
        asset.rack_id = rack.id
        asset.serial = serial
        asset.ip = ip
        asset.type = 'NetworkDevice'
        asset.location = rack.location
        db.object_create(asset)
        asset = db.asset_get_by(serial=serial)
    db_switch = db.network_device_get_by(**{'asset.serial': serial})
    if db_switch:
        db_switch = db_switch[0]
    else:
        db_switch = db_model.NetworkDevice()
        db_switch.name = hostname
        db_switch.asset_id = asset.id
        db_switch = db.object_create(db_switch)
        db_switch = db.network_device_get_by(id=db_switch.id)[0]
    interfaces_ensure(db, db_switch, interfaces)
    db_switch = db.network_device_get_by(**{'asset.serial': serial})[0]
    return db_switch
