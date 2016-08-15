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


import inspect
import socket

from dao.common import log
from dao.control import server_helper
from dao.control.worker.validation import validation_script
from dao.control.worker.validation import server_info
from dao.control.worker.validation import raid_configure

LOG = log.getLogger(__name__)


def is_up(server, port):
    try:
        ip_address = server_helper.get_net_ip(server, 'mgmt')
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((ip_address, port))
        LOG.debug('%s connected', server.fqdn)
        s.close()
        return True, ''
    except socket.error:
        LOG.debug('Fail to connect %s', server.fqdn)
        return False, 'Waiting validation agent (%s port)' % port


def get_validation_code():
    path = inspect.getsourcefile(validation_script)
    with open(path) as fd:
        return fd.read()


def get_code(module):
    path = inspect.getsourcefile(module)
    with open(path) as fd:
        return fd.read()


def get_raid_configure_code():
    path = inspect.getsourcefile(raid_configure)
    with open(path) as fd:
        return fd.read()


def get_server_info_code():
    path = inspect.getsourcefile(server_info)
    with open(path) as fd:
        return fd.read()
