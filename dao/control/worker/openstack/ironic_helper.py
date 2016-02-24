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


from ironicclient import client
from ironicclient import exceptions
from dao.common import config


CONF = config.get_config()
exceptions = exceptions


def get_client():
    ironic = client.get_client(
        api_version=1,
        os_auth_url=CONF.openstack.auth_url,
        os_region_name=CONF.openstack.region,
        os_username=CONF.openstack.username,
        os_password=CONF.openstack.password,
        os_tenant_name=CONF.openstack.project)
    return ironic
