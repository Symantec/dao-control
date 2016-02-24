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

import functools
import netaddr
import re
import time

from dao.common import config
from dao.common import log
from dao.common import utils
from dao.control import exceptions

opts = [
    config.BoolOpt('worker', 'ipmi_timeout',
                   default=20*60,
                   help='Timeout for IPMI operation.')
]

config.register(opts)
CONF = config.get_config()
logger = log.getLogger(__name__)


class IPMIHelper(object):
    user = CONF.worker.ipmi_login
    password = CONF.worker.ipmi_password
    brand_name = None
    re_vendor = re.compile('Product Manufacturer.*: (\w+)')

    def __init__(self, ip, serial):
        self.ip = ip
        self.serial = serial

    @classmethod
    def get_backend(cls, ip):
        """
        :rtype: IPMIHelper
        """
        backends = [Dell, SuperMicro]
        fru = cls._run_sh('ipmitool', '-I', 'lanplus',
                          '-H', ip, '-U', cls.user, '-P', cls.password,
                          'fru', ret_codes=[0, 1])
        fru = cls._section_to_dict(cls._get_fru_section(fru))
        brand = fru.get('Board Mfg', '').capitalize()
        for backend in backends:
            if backend.brand_name == brand:
                return backend(ip, fru)
        else:
            raise exceptions.DAONotFound(
                'Backend for %s is not supported' % ip)

    def get_nic_mac(self, nic_name):
        raise NotImplementedError()

    @classmethod
    def restart_pxe(cls, ip):
        cmd = functools.partial(
            cls._run_sh, 'ipmitool', '-I', 'lanplus',
            '-H', ip,  '-U', cls.user, '-P', cls.password)
        cmd('chassis', 'bootdev', 'pxe')
        res = cmd('power', 'status')
        if res.split()[-1].strip() == 'off':
            cmd('power', 'on')
        else:
            cmd('power', 'cycle')

    @classmethod
    def match_vendor(cls, fru):
        result = cls.re_vendor.findall(fru)
        return result and result[0].capitalize() == cls.brand_name

    @classmethod
    def _run_sh(cls, *args, **kwargs):
        def replace_creds(msg):
            return msg.replace(cls.password, '<pwd>').\
                replace(cls.user, '<user>')
        ret_codes = kwargs.get('ret_codes', [0])
        for i in range(5):
            with utils.Timed(20*30):
                try:
                    stdout = utils.run_sh(args)
                    return stdout
                except exceptions.DAOExecError, exc:
                    if exc.return_code not in ret_codes:
                        time.sleep(3)
                        continue
                    else:
                        return exc.stdout
        else:
            raise exceptions.DAOException(replace_creds(str(exc.message)))

    @staticmethod
    def _get_fru_section(fru):
        fru = [l.splitlines() for l in fru.split('\n\n')]
        fru = [item for item in fru
               if item and 'Builtin FRU Device' in item[0]][0]
        return fru

    @staticmethod
    def _section_to_dict(section):
        """
        :type section: list of str
        :rtype: dict
        """
        result = dict()
        last_key = None
        for l in section:
            k, v = l.split(':', 1)
            k = k.strip()
            v = v.strip()
            if k:
                result[k] = v
                last_key = k
            else:
                result[last_key] = '\n'.join((result[last_key], v))
        return result


class Dell(IPMIHelper):
    brand_name = 'Dell'
    idrac_tool = 'idracadm7'
    re_mac = re.compile('Current[^M]* MAC Address:\s+([0-9A-F:]+)')

    def __init__(self, ip, fru):
        serial = fru['Product Serial']
        super(Dell, self).__init__(ip, serial)

    def get_nic_mac(self, nic_name):
        out = self._run_sh(self.idrac_tool, '-r', self.ip, '-u', self.user,
                           '-p', self.password,
                           'hwinventory', nic_name, ret_codes=[0, 2])
        return str(netaddr.eui.EUI(self.re_mac.search(out).group(1)))


class SuperMicro(IPMIHelper):
    brand_name = 'Supermicro'
    ipmi_tool = 'SMCIPMITool'
    re_mac = re.compile('Current[^M]* MAC Address:\s+([0-9A-F:]+)')

    def __init__(self, ip, fru):
        serial = fru['Product Serial']
        super(SuperMicro, self).__init__(ip, serial)

    def get_nic_mac(self, nic_name):
        out = self._run_sh(self.ipmi_tool, self.ip,
                           self.user, self.password,
                           'ipmi', nic_name, 'mac')
        return str(netaddr.eui.EUI(self.re_mac.search(out).group(1)))
