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


from dao.common import log
from dao.control.db import api as db_api
from dao.control import worker_api

logger = log.getLogger(__name__)


class ServerProcessor(object):

    statuses = ['Unknown', 'Unmanaged',
                'Validating', 'ValidatedWithErrors', 'Validated',
                'Provisioning', 'ProvisionedWithErrors', 'Provisioned']

    def __init__(self, server):
        """
        :type server: dao.control.db.model.Server
        :return:
        """
        self.db = db_api.Driver()
        self.server = server
        self.op_status2call = dict(
            Unmanaged=self.s0_s1,
            Validated=self.s1_s2
        )

    def next(self):
        if self.server.target_status != self.server.status:
            try:
                return self.op_status2call[self.server.status]()
            except KeyError:
                return self.skip()
        else:
            self.server.lock_id = ''
            self.server = self.db.server_update(self.server,
                                                comment='Target status ok')
            return False

    def error(self, message):
        status2status = {'Validating': 'ValidatedWithErrors',
                         'Provisioning': 'ProvisionedWithErrors'}
        logger.warning('Error for: {0.id}: {0.name}: {1}'.format(self.server,
                                                                 message))
        if self.server.lock_id:
            self.server.lock_id = ''
        self.server.status = status2status.get(self.server.status,
                                               'Unknown')
        message = str(message)
        self.server = self.db.server_update(self.server, message[-253:])

    def s0_s1(self):
        worker = worker_api.WorkerAPI.get_api(rack_name=self.server.rack_name)
        worker.send('validate_server', self.server.id, self.server.lock_id)
        return True

    def s1_s2(self):
        worker = worker_api.WorkerAPI.get_api(rack_name=self.server.rack_name)
        worker.send('provision_server', self.server.id, self.server.lock_id)
        return True

    def stop(self):
        if self.server.status in ('Validating', 'Provisioning'):
            worker = worker_api.WorkerAPI.get_api(
                rack_name=self.server.rack_name)
        else:
            return False
        return worker.call('stop_server', self.server.id, self.server.lock_id)

    def skip(self):
        if self.server.lock_id:
            self.server.lock_id = ''
            self.server = self.db.server_update(self.server)
        return False
