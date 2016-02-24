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
from dao.common import log
from dao.common import utils
from dao.control import exceptions
from dao.control import server_helper


opts = [
    config.StrOpt('dns', 'driver',
                  default='dao.control.worker.dns_helper.DNSTool',
                  help='DNS management back-end module.'),
    config.StrOpt('dns', 'script_path',
                  default='/usr/local/bin/dnstool',
                  help='DNS tool script location executed by DAO DNS '
                       'management back-end.'),
    config.StrOpt('dns', 'api_url', default='', help='DNS url.'),
    config.StrOpt('dns', 'api_key', default='', help='DNS api key'),

]

config.register(opts)
CONF = config.get_config()

logger = log.getLogger(__name__)


class DNSBase(object):
    @staticmethod
    def get_driver():
        """
        :return: DNSBase()
        """
        module, obj = CONF.dns.driver.rsplit('.', 1)
        module = eventlet.import_patched(module)
        return getattr(module, obj)()

    def register(self, fqdn, server):
        raise NotImplementedError()

    def delete(self, fqdn, server):
        raise NotImplementedError()

    def test(self):
        """Method tests backend availability"""
        raise NotImplementedError()


class DNSTool(DNSBase):
    def __init__(self):
        super(DNSTool, self).__init__()
        self.script = CONF.dns.script_path

    def delete(self, fqdn, server):
        nets = self._get_nets(server)
        for net in nets:
            ip = net.get('ip')
            if not ip:
                continue
            self._clean_for_ip(ip)

    def register(self, server, ipmi_only=True):
        fqdn = server.fqdn
        self._register('ipmi', fqdn, server.asset.ip, server)
        if server.network:
            for net_name, net in server.network.items():
                self._register(net_name, fqdn, net['ip'], server)
        else:
            self._register('mgmt', fqdn, server.pxe_ip, server)

    def _register(self, net_name, fqdn, ip, server):
        if net_name != CONF.worker.fqdn_net:
            fqdn = server_helper.fqdn_get(
                server, server.generate_name(net_name))
        command = [self.script,
                   '--api_url', CONF.dns.api_url,
                   '--api_key', CONF.dns.api_key,
                   '--action', 'change',
                   '--fqdn', fqdn,
                   '--type', 'A,PTR',
                   '--value', ip,
                   '--ttl', '3600']
        logger.debug('Running: %s', ' '.join(command))
        try:
            utils.run_sh(command)
            logger.info('DNS record {0} added for IP {1}'.format(fqdn, ip))
        except exceptions.DAOExecError, exc:
            logger.info('Failed to add DNS record {0} for IP {1}.'
                        ' Return code: {2}'.format(fqdn, ip, exc.return_code))


    @staticmethod
    def _get_nets(server):
        nets = server_helper.get_net2ip(server)
        return [dict(name=k, ip=v) for k, v in nets.items()]

    def _clean_for_ip(self, ip):
        try:
            stdout = utils.run_sh(['nslookup', ip])
            name = [l for l in stdout.splitlines() if 'name = ' in l][0]
            name = name.split('name = ', 1)[1].strip('.')
            self._delete(name, ip)
        except exceptions.DAOExecError:
            pass

    def _delete(self, fqdn, ip):
        command = [self.script,
                   '--api_url', CONF.dns.api_url,
                   '--api_key', CONF.dns.api_key,
                   '--action', 'delete',
                   '--fqdn', fqdn,
                   '--type', 'A,PTR',
                   '--value', ip]
        logger.debug('Running: %s', ' '.join(command))
        try:
            utils.run_sh(command)
            logger.info('DNS record {0} for IP {1} deleted'.format(fqdn, ip))
        except exceptions.DAOExecError, exc:
            msg = 'Failed to delete DNS record {0} for IP {1}: ' \
                'returned code {2}'.format(fqdn, ip, exc.return_code)
            logger.warning(msg)
