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


opts = [config.StrOpt(
    'worker', 'switch_lib',
    default='dao.control.worker.switch.switchconf_helper.SwitchConf',
    help='Default switch library')]

config.register(opts)
CONF = config.get_config()
LOG = log.getLogger(__name__)


class Base(object):
    name2cls = dict()
    cls_obj = None

    def __init__(self, db):
        self.db = db

    @classmethod
    def get_helper(cls, db):
        """
        :rtype: Base
        """
        path = CONF.worker.switch_lib
        switch_lib_cls = cls.name2cls.get(path)
        if switch_lib_cls is None:
            module, cls_name = path.rsplit('.', 1)
            module = eventlet.import_patched(module)
            switch_lib_cls = getattr(module, cls_name)
            cls.name2cls[path] = switch_lib_cls
        return switch_lib_cls(db)

    def server_number_get(self, rack, net_map, server):
        """
         :type rack: dao.control.db.model.Rack
         :type net_map: dao.control.db.model.NetworkMap
         :type server: dao.control.db.model.Server
        """
        raise NotImplementedError()

    def switch_validate_for_server(self, rack, server):
        """
         :type rack: dao.control.db.model.Rack
         :type server: dao.control.db.model.Server
        """
        pass

    def switch_validate_for_rack(self, rack):
        """
         :type server: dao.control.db.model.Server
        """
        pass

    def switch_discover(self, hostname, ip):
        raise NotImplementedError()
