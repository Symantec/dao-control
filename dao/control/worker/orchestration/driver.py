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
from dao.control import server_helper

CONF = config.get_config()
LOG = log.getLogger(__name__)


class BaseDriver(object):
    """Base class to define driver to orchestrate hosts
    """
    def host_recreated(self, server):
        """Take care that certificates for servers are going to be changed"""
        raise NotImplementedError()

    def is_up(self, server, iface):
        """Check if server is up and running"""
        raise NotImplementedError()

    def execute(self, fqdn, cmd):
        raise NotImplementedError()

    def run_cmd(self, env, roles, cmd):
        raise NotImplementedError()

    def get_provision_parameters(self):
        return {}


class DummyDriver(BaseDriver):

    def host_recreated(self, server):
        pass

    def is_up(self, server, iface):
        try:
            ip_address = server_helper.get_net_ip(server, iface)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((ip_address, int(22)))
            LOG.debug('%s connected', server.fqdn)
            s.close()
            return True
        except socket.error:
            LOG.debug('Fail to connect %s', server.fqdn)
            return False
