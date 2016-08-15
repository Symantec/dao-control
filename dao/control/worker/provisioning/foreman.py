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
import yaml
from dao.common import config
from dao.common import log
from dao.common import utils
from dao.control import exceptions
from dao.control import server_helper
from dao.control.worker.provisioning import foreman_helper
from dao.control.worker.provisioning import driver
from dao.control.worker.provisioning import server_update


CONF = config.get_config()

LOG = log.getLogger(__name__)


class ForemanDriver(driver.BaseDriver):
    helper = None

    def on_init(self):
        self.helper = foreman_helper.Foreman()

    def test(self):
        return self.helper.foreman_test()

    def server_delete(self, server):
        return self.helper.server_delete(server)

    def server_s0_s1(self, server, rack):
        subnets = self._rack_ensure(rack.name)
        server_update.pre_validation(server)
        os_args = dict(os_name=CONF.foreman.s1_os_name)
        self.helper.ensure_os_family(os_args)
        self.helper.server_build(
            server, subnets,
            env_name=CONF.foreman.s1_environment % server.to_dict(),
            os_args=os_args,
            gateway='mgmt')

    def server_s1_s2(self, server, rack):
        """Build server for S1 state based on an db information."""
        if server.os_args is None or not server.os_args.get('os_name'):
            raise exceptions.DAOInvalidData('No OS name provided')
        subnets = self._rack_ensure(rack.name)
        parameters = {'salt-minion': 'on',
                      'salt-master': CONF.salt.master_host,
                      'role': server.role,
                      'cluster': server.cluster_name,
                      'hardware': yaml.dump(server.description)}
        parameters.update(self.orchestrator.get_provision_parameters())
        self.helper.ensure_os_family(server.os_args)
        build_net = server_helper.network_build_patched(rack, server)
        self.helper.server_build(
            server, subnets,
            env_name=CONF.foreman.s2_environment % server.to_dict(),
            os_args=server.os_args,
            parameters=parameters,
            gateway='prod',
            build_net=build_net)
        self.orchestrator.host_recreated(server)

    def is_provisioned(self, server, iface):
        host = self.helper.get_host(server)
        if not host['build']:
            if self.orchestrator.is_up(server, iface):
                return True, None
            else:
                return False, 'Waiting SSH port up'
        else:
            return False, 'Waiting build completed'

    def os_list(self, os_name):
        """List OS (hostgroups in reality) with parameters.
        returns list of dicts with keys
         - name,
         - allowed medias (list of names)
         - allowed partitions (list of names)
        """
        host_groups = self.helper.hostgroup_list(os_name)
        host_groups = [hg for hg in host_groups if hg['operatingsystem_id']]
        result = dict.fromkeys(item['name'] for item in host_groups)
        for host_group in host_groups:
            os = self.helper._get_one('operatingsystems',
                                      host_group['operatingsystem_id'])
            d = dict(partitions=[ptable['name'] for ptable in os['ptables']],
                     medias=[media['name'] for media in os['media']])
            result[host_group['name']] = d
        return result

    @utils.CacheIt()
    def _rack_ensure(self, rack_name):
        networks = self._get_rack_networks(rack_name)
        for network in networks:
            tag = network.vlan_tag if network.tagged else ''
            self.helper.subnet_create(network.name,
                                      str(network.subnet.ip),
                                      str(network.subnet.netmask),
                                      gateway=network.gateway,
                                      vlan=tag)
        return networks

    @staticmethod
    def _is_up_and_running(host):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((host, int(22)))
            LOG.debug('%s connected', host)
            s.close()
            return True
        except socket.error:
            LOG.debug('Fail to connect %s', host)
            return False

    def _get_rack_networks(self, rack_name):
        networks = self.db.subnets_get(rack_name)
        return networks
