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
from dao.control import server_helper
opts = [config.StrOpt('worker', 'hook',
                      default='dao.control.worker.hooks.base.HookBase',
                      help='Hook class to be used on server state change.')
        ]

config.register(opts)
CONF = config.get_config()
LOG = log.getLogger(__name__)


class HookBase(object):
    name2cls = dict()
    cls_obj = None

    def __init__(self, server, db):
        self.server = server
        self.db = db

    @classmethod
    def get_hook(cls, server, db):
        """
        :rtype: HookBase
        """
        hook_path = server_helper.get_hook_path(server)
        hook_cls = cls.name2cls.get(hook_path)
        if hook_cls is None:
            module, cls_name = hook_path.rsplit('.', 1)
            module = eventlet.import_patched(module)
            hook_cls = getattr(module, cls_name)
            cls.name2cls[hook_path] = hook_cls
        return hook_cls(server, db)

    def pre_validate(self):
        return self.server

    def validated(self):
        return self.server

    def pre_provision(self):
        return self.server

    def provisioned(self):
        return self.server

    def deleted(self):
        return self.server
