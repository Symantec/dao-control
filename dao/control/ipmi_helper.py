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
import functools
import netaddr
import re
import time
from pysnmp.smi import builder, view

from dao.common import config
from dao.common import log
from dao.common import utils
from dao.control import exceptions

cmdgen = eventlet.import_patched('pysnmp.entity.rfc3413.oneliner.cmdgen')

opts = [
    config.BoolOpt('worker', 'ipmi_timeout',
                   default=20*60,
                   help='Timeout for IPMI operation.'),

    config.StrOpt('worker', 'snmp_community',
                  default='public',
                  help='SNMP community data field for snmpv1'),

    config.IntOpt('worker', 'snmp_port',
                  default=161,
                  help='SNMP port to use')
]

config.register(opts)
CONF = config.get_config()
LOG = log.getLogger(__name__)

mib_builder = builder.MibBuilder()
mib_builder.loadModules('SNMPv2-MIB')
mib_view = view.MibViewController(mib_builder)


class IPMIHelper(object):
    user = CONF.worker.ipmi_login
    password = CONF.worker.ipmi_password
    brand_name = None
    re_vendor = re.compile('Product Manufacturer.*: (\w+)')
    mib_brand_id = None
    mib_header = 'iso.org.dod.internet.private.enterprises'

    def __init__(self, ip, serial, asset_type, chassis_serial):
        self.ip = ip
        self.serial = serial
        self.asset_type = asset_type
        self.chassis_serial = chassis_serial

    @classmethod
    def get_backend(cls, ip):
        """
        :rtype: IPMIHelper
        """
        # In order to support different brands, use SNMP first
        # ipmitool doesn't work for FX2 chassis
        try:
            oid = cls._snmp_invoke(ip, 'SNMPv2-MIB', 'sysObjectID', '0')
        except exceptions.DAOException, exc:
            LOG.debug('Unable to communicate to idrac: {0}'.format(repr(exc)))
            raise exceptions.DAONotFound('Backend for {0} is not supported'.
                                         format(ip))

        oid, label, suffix = mib_view.getNodeNameByOid(oid)
        backends = [Dell]
        label = '.'.join(label)
        for b_cls in backends:
            if label == b_cls.mib_header and suffix[0] == b_cls.mib_brand_id:
                return b_cls(ip)
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
    def _snmp_invoke(cls, ip, *oid):
        cmd_gen = cmdgen.CommandGenerator()
        error_indication, error_status, error_index, var_binds = \
            cmd_gen.getCmd(
                cmdgen.CommunityData(CONF.worker.snmp_community),
                cmdgen.UdpTransportTarget((ip, CONF.worker.snmp_port)),
                cmdgen.MibVariable(*oid))

        if error_indication or error_status or error_index:
            raise exceptions.DAOException('SNMP Error: %r, %r, %r' %
                                          (error_indication,
                                           error_status,
                                           error_index))
        if not var_binds:
            raise exceptions.DAOException('SNMP Error: no object %s value' %
                                          repr(oid))

        return var_binds[0][1]

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
    mib_brand_id = 674
    description_oid = 'enterprises.674.10892.2.1.1.1.0'
    serial_oid = 'enterprises.674.10892.2.1.1.11.0'
    chassis_oid = 'enterprises.674.10892.5.1.2.1.0'
    idrac_tool = 'idracadm7'
    re_mac = re.compile('Current[^M]* MAC Address:\s+([0-9A-F:]+)')

    def __init__(self, ip):
        description = self._snmp_invoke(
            ip, 'SNMPv2-SMI', *self.description_oid.split('.')).prettyPrint()
        if description.lower() == 'chassis management controller':
            a_type = 'Chassis'
            chassis_serial = ''
        else:
            a_type = 'Server'
            chassis_serial = self._snmp_invoke(
                ip, 'SNMPv2-SMI',  *self.chassis_oid.split('.')).prettyPrint()
        serial = self._snmp_invoke(ip, 'SNMPv2-SMI',
                                   *self.serial_oid.split('.')).prettyPrint()
        if not serial:
            LOG.info('Serial number for %s is empty', ip)
            raise exceptions.DAOIgnore('Invalid serial number')

        super(Dell, self).__init__(ip, serial, a_type, chassis_serial)

    def get_nic_mac(self, nic_name):
        out = self._run_sh(self.idrac_tool, '-r', self.ip, '-u', self.user,
                           '-p', self.password,
                           'hwinventory', nic_name, ret_codes=[0, 2])
        return str(netaddr.eui.EUI(self.re_mac.search(out).group(1)))
