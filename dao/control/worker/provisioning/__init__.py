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


opts = [config.StrOpt('worker', 'provision_driver',
                      default='dao.control.worker.provisioning.pxe.PxeDriver',
                      help='Backend module for provisioning')]

config.register(opts)
CONF = config.get_config()

logger = log.getLogger(__name__)


def get_driver(worker_url=None):
    """
    :rtype: dao.control.worker.provisioning.foreman.ForemanDriver
    """
    module, obj = CONF.worker.provision_driver.rsplit('.', 1)
    logger.info('Load %s from %s', obj, module)
    module = eventlet.import_patched(module)
    return getattr(module, obj)(worker_url)
