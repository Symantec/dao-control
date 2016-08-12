#!/bin/env python
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
import os
import re
import time
import subprocess


class IPMIHelper(object):
    re_vendor = re.compile('Product Manufacturer.*: (\w+)')

    def __init__(self, brand, serial, model, mac, ip):
        self._brand = brand
        self._serial_number = serial
        self._model = model
        self._mac = mac
        self._ip = ip

    @classmethod
    def get_backend(cls):
        """
        :rtype: IPMIHelper
        """
        fru = cls._run_sh('ipmitool', 'fru', ret_codes=[0, 1])
        fru = cls._section_to_dict(cls._get_fru_section(fru))
        lan = cls._section_to_dict(cls._get_lan_section())
        brand = fru['Board Mfg'].capitalize()
        model = fru['Board Product']
        serial = fru['Product Serial']
        ip = lan['IP Address']
        mac = lan['MAC Address']
        return IPMIHelper(brand, serial, model, mac, ip)

    @classmethod
    def _get_fru(cls):
        """Get server hardware vendor via IPMI."""
        fru = cls._run_sh('ipmitool', 'fru', ret_codes=[0, 1])
        return fru

    @property
    def ip(self):
        return self._ip

    @property
    def mac(self):
        return self._mac

    @property
    def brand(self):
        return self._brand

    @property
    def model(self):
        return self._model

    @property
    def serial(self):
        return self._serial_number

    @staticmethod
    def _run_sh(*args, **kwargs):

        p = subprocess.Popen(args,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        ret_codes = kwargs.get('ret_codes', [0])
        if p.returncode not in ret_codes:
            raise RuntimeError(stderr)
        return stdout

    @staticmethod
    def _get_fru_section(fru):
        fru = [l.splitlines() for l in fru.split('\n\n')]
        fru = [item for item in fru
               if item and 'Builtin FRU Device' in item[0]][0]
        return fru

    @classmethod
    def _get_lan_section(cls):
        return cls._run_sh('ipmitool', 'lan', 'print').splitlines()

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


def get_asset():
    """Read asset information
    :rtype: dict([brand, model, serial, ip, mac])
    """
    ipmi = IPMIHelper.get_backend()
    asset = dict(brand=ipmi.brand, model=ipmi.model, serial=ipmi.serial)
    return asset


def read_net_interfaces():
    def read_iface(ifname, file_name):
        path = os.path.join('/sys/class/net/', ifname, file_name)
        with open(path) as fd:
            return fd.read().strip()

    def iface2iface(ifname):
        return {'name': ifname,
                'mac': str(netaddr.eui.EUI(read_iface(ifname, 'address'))),
                'state': read_iface(ifname, 'operstate')}

    ifaces = os.listdir('/sys/class/net/')
    return [iface2iface(iface) for iface in ifaces if iface != 'lo']


def main(server_dict):
    global RESULT
    print 'Getting server information:', time.ctime()
    asset = get_asset()
    interfaces = read_net_interfaces()
    RESULT = (asset, interfaces)


if __name__ == '__main__':
    global server
    main(server)

