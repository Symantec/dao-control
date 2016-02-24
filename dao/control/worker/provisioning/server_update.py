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


import os
from eventlet.green import subprocess

from dao.common import log
from dao.common import config
from dao.control import exceptions

logger = log.getLogger(__name__)


opts = [config.StrOpt('worker', 'validation_scripts_path',
                      default='/opt/dell-scripts',
                      help='Path to scripts to validate ipmi'),
        config.StrOpt('worker', 'validation_scripts',
                      default='dummy',
                      help='Comma separated list of scripts to run')
        ]

config.register(opts)
CONF = config.get_config()


def pre_validation(server):
    if server.asset.status != 'New':
        idrac_ip = server.asset.ip
        logger.info('Validating server %s (iDrac: %s)', server.name, idrac_ip)
        script_names = CONF.worker.validation_scripts.split(',')
        backend = PreValidationBase.get_instance(server)
        for script in script_names:
            getattr(backend, script)()
        logger.info('Success validating server %s (iDrac: %s)',
                    server.name, idrac_ip)


class PreValidationBase(object):
    brand = None

    def __init__(self, server):
        self.server = server

    @classmethod
    def get_instance(cls, server):
        # Leasy discovery
        brand2cls = dict((i.brand, i) for i in globals().values()
                         if (type(i) is type and
                             issubclass(i, PreValidationBase) and
                             i.brand is not None))
        try:
            return brand2cls[server.asset.brand](server)
        except KeyError:
            raise exceptions.DAONotFound('Update backend for {0} is not found'.
                                         format(server.asset.brand))

    def change_pass(self):
        raise NotImplementedError()

    def update_ipmi(self):
        raise NotImplementedError()

    def update_bios(self):
        raise NotImplementedError()

    def cpe_power(self):
        raise NotImplementedError()

    def dummy(self):
        pass


class DellValidation(PreValidationBase):
    brand = 'Dell'

    def change_pass(self):
        return self._call('changepass')

    def update_ipmi(self):
        return self._call('upddrac')

    def update_bios(self):
        return self._call('updbios')

    def cpe_power(self):
        return self._call('cpe-dell-power.pl')

    def _call(self, script):
        idrac_ip = self.server.asset.ip
        script = os.path.join(CONF.worker.validation_scripts_path, script)

        logger.info('Run script: %s (iDrac: %s)', script, idrac_ip)
        try:
            subprocess.check_call([script, idrac_ip,
                                   CONF.worker.ipmi_login,
                                   CONF.worker.ipmi_password])
        except subprocess.CalledProcessError as e:
            message = 'Server update script {0} failed with code {1} for {2}'.\
                format(e.cmd, e.returncode, idrac_ip)
            message = message.replace(CONF.worker.ipmi_login, '<user>')
            message = message.replace(CONF.worker.ipmi_password, '<pwd>')
            logger.error(message)
            raise exceptions.DAOProvisionIncomplete(message)
        except OSError as e:
            message = 'Script {0} failed: {1}'.format(script, str(e))
            logger.critical(message)
            raise exceptions.DAOProvisionIncomplete(message)
        logger.info('Success running script for server %s (iDrac: %s)',
                    self.server.name, idrac_ip)


class SMValidation(PreValidationBase):
    brand = 'Supermicro'

    def change_pass(self):
        return self.dummy()

    def update_ipmi(self):
        return self.dummy()

    def update_bios(self):
        return self.dummy()

    def cpe_power(self):
        return self.dummy()
