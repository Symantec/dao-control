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


import abc
import eventlet
from dao.common import config
from dao.common import log
opts = [config.StrOpt('dhcp', 'driver',
                      default='dao.control.worker.dhcp.neutron.NeutronHelper',
                      help='Path to DHCP helper')
        ]

config.register(opts)
CONF = config.get_config()
LOG = log.getLogger(__name__)


class DHCPBase(object):

    instance = None

    @classmethod
    def get_helper(cls, worker=None):
        """
        :rtype: DHCPBase
        """
        if cls.instance:
            return cls.instance
        module, cls_name = CONF.dhcp.driver.rsplit('.', 1)
        module = eventlet.import_patched(module)
        cls_obj = getattr(module, cls_name)
        cls.instance = cls_obj(worker)
        return cls.instance

    @abc.abstractmethod
    def allocate(self, rack, net, serial, mac, ip=''):
        """
        :type rack: dao.control.db.model.Rack
        :type net: dao.control.db.model.Subnet
        :type serial: str
        :type ip: str
        :type mac: str
        :rtype: str
        """
        pass

    @abc.abstractmethod
    def delete_for_serial(self, serial, ignored=None):
        """
        :type serial: str
        :type ignored: str
        :rtype: None
        """
        pass

    @abc.abstractmethod
    def ensure_subnets(self, nets):
        """
        :type nets: dao.control.db.model.Subnet
        :return: None
        """
        pass
