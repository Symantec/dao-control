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


import collections
from dao.common import exceptions
from dao.common import rpc
from dao.common import utils
from dao.control.db import api as db_api


class WorkerAPI(rpc.RPCApi):
    instances = collections.defaultdict(dict)

    @classmethod
    def get_api(cls, rack_name=None, worker=None):
        # return the same for a while
        if worker is None:
            if rack_name:
                worker = cls._get_service(rack_name=rack_name)
            else:
                raise exceptions.DAONotFound('Unable to detect worker')
        return cls(worker.worker_url)

    @classmethod
    @utils.CacheIt(60, ignore_self=True)
    def _get_service(cls, rack_name):
        db = db_api.Driver()
        return db.worker_get_by_rack(rack_name)

    @classmethod
    @utils.CacheIt(60, ignore_self=True)
    def _get_worker(cls, worker_name):
        db = db_api.Driver()
        return db.worker_get(name=worker_name)
