# Copyright 2015 Symantec.
#
# Author: Sergii Kashaba <sergii_kashaba@symantec.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from dao.common import config
from dao.control import exceptions
from dao.control import server_helper
from dao.control.worker import provisioning
from dao.control.worker.hooks import base as hook_base
from dao.control.worker.dhcp import base as dhcp_base
from dao.control.worker.openstack import ironic_helper
from dao.control.worker.openstack import nova_helper


opts = [
    config.StrOpt('openstack', 'image_name_kernel',
                  default='vi-ipa.kernel',
                  help='Ironic python agent kernel image UUID'),

    config.StrOpt('openstack', 'image_name_ram',
                  default='vi-ipa.initramfs',
                  help='Ironic python agent ram image UUID'),
]

config.register(opts)
CONF = config.get_config()


def ram2mb(_sku):
    multiplier = {'GB': 1024, 'MB': 1}
    return int(_sku.ram[:-2]) * multiplier[_sku.ram[-2:]]


class IronicHook(hook_base.HookBase):
    def __init__(self, server, db):
        """
        :type server: dao.control.db.model.Server
        :type db: dao.control.db.api.Driver
        :return:
        """
        super(IronicHook, self).__init__(server, db)
        self.ipmi_tag = server_helper.net2vlan()['ipmi']

    def pre_validate(self):
        ironic = ironic_helper.get_client()
        if self.server.asset.status != 'New':
            try:
                ironic.node.get(self.server.name)
                raise exceptions.DAOConflict('Server is managed by Ironic')
            except ironic_helper.exceptions.NotFound:
                pass
        return self.server

    def validated(self):
        # Ensure chassis
        rack = self.db.rack_get(id=self.server.asset.rack_id)
        rack_name = rack.name.lower()
        ironic = ironic_helper.get_client()
        chassis = [c for c in ironic.chassis.list()
                   if c.description == rack_name]
        # Ensure chassis
        if chassis:
            chassis = chassis[0]
        else:
            chassis = ironic.chassis.create(description=rack_name, extra={})

        # We do require an SKU description
        sku = self.db.object_get('Sku', 'id', self.server.sku_id)
        # Build parameters
        network = server_helper.network_map_get(rack, self.server)
        vlan2net = server_helper.vlan2net()
        iface2vlan = dict((iface, net['vlan'])
                          for iface, net in network.items() if 'vlan' in net)
        net2iface = dict((vlan2net[vlan], iface)
                         for iface, vlan in iface2vlan.items())

        extra = dict(interfaces=dict((i.name, i.mac.replace('-', ':').lower())
                                     for i in self.server.interfaces.values()),
                     network=server_helper.network_map_get(rack, self.server),
                     description={'fqdn': self.server.fqdn},
                     salt={'master': CONF.salt.master_host},
                     dns_nameservers=[CONF.worker.primary_dns,
                                      CONF.worker.secondary_dns],
                     dns_zone=CONF.worker.default_dns_zone,
                     net2iface=net2iface)

        kernel_id, ram_id = self._get_ipa_images()
        driver_info = dict(
            deploy_kernel=kernel_id,
            deploy_ramdisk=ram_id,
            ipmi_address=self.server.asset.ip,
            ipmi_username=CONF.worker.ipmi_login,
            ipmi_password=CONF.worker.ipmi_password)

        properties = dict(
            capabilities='sku:{0},rack:{1}'.format(sku.name, rack_name),
            memory_mb=ram2mb(sku),
            cpu_arch='x86_64',
            cpus=1,
            serial=self.server.asset.serial,
            rack=rack_name,
            root_device={'name': '/dev/sda'}
        )

        kwargs = dict(
            name=self.server.name,
            chassis_uuid=chassis.uuid,
            driver='agent_ipmitool',
            driver_info=driver_info,
            extra=extra,
            properties=properties)

        provision = provisioning.get_driver()
        dhcp = dhcp_base.DHCPBase.get_helper()
        # Delete server from provisioning tool. To avoid keeping IPs
        provision.server_delete(self.server)
        # Delete DHCP lease and change server
        dhcp.delete_for_serial(self.server.asset.serial, ignored='ipmi')
        self.server.network = None
        self.server.pxe_ip = None
        self.db.server_update(self.server)

        # Create Ironic node and keep it turned off
        new_node = ironic.node.create(**kwargs)
        ironic.node.set_power_state(new_node.uuid, 'off')

        # Create Ironic port to be used for PxE
        mgmg_iface = new_node.extra['network']['mgmt']['interfaces'][0]
        kwargs = dict(address=new_node.extra['interfaces'][mgmg_iface],
                      node_uuid=new_node.uuid)
        ironic.port.create(**kwargs)

        # Mark server as controlled by Ironic and exit
        self.server.meta['ironicated'] = True
        self.db.server_update(self.server)
        return self.server

    def pre_provision(self):
        raise exceptions.DAOIgnore('Provision is not allowed for: %s'
                                   % self.server.name)

    def provisioned(self):
        return self.server

    def deleted(self):
        ironic = ironic_helper.get_client()
        try:
            node = ironic.node.get(self.server.name)
            ironic.node.delete(node.uuid)
        except (ironic_helper.exceptions.NotFound,
                ironic_helper.exceptions.BadRequest):
            pass
        return self.server

    def _get_ipa_images(self):
        nova = nova_helper.get_client()
        images = nova.images.list()
        image2id = dict((im.name, im.id) for im in images)
        return (image2id[CONF.openstack.image_name_kernel],
                image2id[CONF.openstack.image_name_ram])
