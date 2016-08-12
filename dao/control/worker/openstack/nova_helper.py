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


from dao.common import config
from novaclient.v2 import client


CONF = config.get_config()


def get_client():
    return client.Client(CONF.openstack.username, CONF.openstack.password,
                         CONF.openstack.project, CONF.openstack.auth_url,
                         region_name=CONF.openstack.region,
                         insecure=CONF.openstack.insecure)
