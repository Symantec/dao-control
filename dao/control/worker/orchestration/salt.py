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


import requests
from dao.common import config
from dao.common import log
from dao.common import utils
from dao.control import exceptions
from dao.control.worker.orchestration import driver

opts = [
    config.StrOpt('salt', 'master_port', default='8080',
                  help='Port of Salt master RPC API.'),

    config.StrOpt('salt', 'username', default='salt',
                  help='Username to access SALT API'),

    config.StrOpt('salt', 'password',
                  help='Password to access SALT API'),

    config.StrOpt('salt', 'master_minion_id',
                  help='ID of the Salt minion running at Salt master host.')
]

config.register(opts)
CONF = config.get_config()

logger = log.getLogger(__name__)


class SaltDriver(driver.DummyDriver):
    def __init__(self):
        """Required configuration parameters::

            [salt]
            master_host = <ip>
            master_port = <port>
            username = <username>
            password = <password>
        """
        self.master = CONF.salt.master_host
        self.port = CONF.salt.master_port
        self.salt_url = 'http://' + self.master + ':' + self.port + '/run'

        self.username = CONF.salt.username
        self.password = CONF.salt.password

        self.headers = {'accept': 'application/json',
                        'content-type': 'application/x-www-form-urlencoded'}
        self.common_params = {'eauth': 'pam',
                              'username': self.username,
                              'password': self.password,
                              'client': 'local'}

    def get_provision_parameters(self):
        return {'salt-minion': 'on',
                'salt-master': CONF.salt.master_host}

    @utils.Synchronized('host_recreated')
    def host_recreated(self, server):
        """Delete Salt host key.
        Must be called after host reprovision to update keys.
        NOTE: Make sure Salt Master host allows Salt user to execute `salt-key`
            command in `/etc/sudoers`.
        Args:
            server: dao.control.db.model.Server

        """
        # NOTE(Ruslan): salt master fqdn and minion id on salt master node do
        # not necessarily match and according to Alex Sakhnov they should not
        # match. Therefore I stuck in additional config parameter.
        # TODO: This has to be figured out and implemented more elegantly.
        try:
            command = 'salt-key -qyd %s' % server.fqdn
            master_minion = CONF.salt.master_minion_id
            ret = self.execute(master_minion, command)
            logger.info(ret)
            if master_minion not in ret:
                logger.warning('Failing to remove certificate. '
                               'Master minion not found.')
        except Exception, exc:
            logger.warning('Exception while host recreate: %s' % repr(exc))
        return

    def execute(self, fqdn, cmd):
        timeout = 3600
        payload = {'tgt': fqdn,
                   'fun': 'cmd.run',
                   'arg': cmd,
                   'timeout': timeout}
        payload.update(self.common_params)
        logger.debug('Salt command: salt {tgt} {fun} {arg}'.format(**payload))
        r = requests.post(self.salt_url, data=payload, headers=self.headers)
        return self._get_result(r)

    def run_cmd(self, cluster, roles, cmd, timeout=3600):
        """Run command on Salt minions.

        Triggers Salt REST API to run specified command on target minions.

        Args:
            cluster (str): Cluster name in db.
            roles (list): Hosts with specified roles will be applied.
            cmd (str): Command to execute on target hosts (minions).

        Kwargs:
            timeout (int): The  timeout  in seconds to wait for replies from
                the Salt minions. Default: 3600

        Returns:
            dict. Keys are FQDNs of executed hosts, values are responses.

        """
        tgt = 'G@cluster:%s' % cluster
        if roles:
            target_roles = ' or '.join('G@roles:%s' % r for r in roles)
            tgt = ' '.join([tgt, 'and',  '( %s )' % target_roles])
        logger.info("tgt = %s, cmd = %s", tgt, cmd)

        payload = {'tgt': tgt,
                   'fun': 'cmd.run',
                   'arg': cmd,
                   'timeout': timeout,
                   'expr_form': 'compound'}
        payload.update(self.common_params)

        r = requests.post(self.salt_url, data=payload, headers=self.headers)
        return self._get_result(r)

    def _get_result(self, response):
        if response.status_code != 200:
            msg = 'Communication problem with Salt Master at {0} ' \
                'with parameters: {1}'.format(self.master, self.common_params)
            logger.warning(msg)
        data = response.json()
        # Actual salt response is under 'return' key represented as list
        result = data.get('return')
        if result is None or isinstance(result, str):
            raise exceptions.DAOException('Salt result is: %r' % result)
        return result[0]
