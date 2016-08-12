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


from dao.control.db import api as db_api
from dao.control.worker import orchestration


class BaseDriver(object):
    def __init__(self, worker_url=None):
        self.db = db_api.Driver()
        self.orchestrator = orchestration.get_driver()
        self.worker_url = worker_url
        self.on_init()

    def on_init(self):
        pass

    def test(self):
        raise NotImplementedError()

    def server_delete(self, server):
        raise NotImplementedError()

    def server_s0_s1(self, server, rack):
        """Build server for S1 state based on an db information."""
        raise NotImplementedError()

    def server_s1_s2(self, server, rack):
        """Build server for S1 state based on an db information."""
        raise NotImplementedError()

    def os_list(self, os_name):
        raise NotImplementedError()

    def is_provisioned(self, server, iface):
        """Check if server is provisioned.
        """
        raise NotImplementedError()

    def os_list(self, os_name):
        """List OS with available parameters.
        If os_name is pointed get information for this OS only.
        OS means OS with default parameters (hostgroup for Foreman and
        profile for Cobbler)
        Returns dictionary of os_name: available parameters
        """
        raise NotImplementedError()
