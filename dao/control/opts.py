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


conf_opts = [
    config.BoolOpt('common', 'debug',
                   default=False,
                   help='Include debugging information in logs.'),

    config.StrOpt('common', 'log_config',
                  default='/etc/dao/logger.cfg',
                  help='Path to config file for logging subsystem.'),

    config.StrOpt('common', 'location',
                  help='Abbreviation for environment geographical location. '
                       'Like PHX, etc.'),

    config.StrOpt('common', 'log_config',
                  default='/etc/dao/logger.cfg',
                  help='Path to config file for logging subsystem.'),

    config.StrOpt('salt', 'master_host',
                  help='Salt master host IP or hostname.'),

    config.StrOpt('worker', 'ipmi_login',
                  help='User name for server IPMI access.'),

    config.StrOpt('worker', 'ipmi_password',
                  help='Password for server IPMI access.'),

    config.JSONOpt('worker', 'net2vlan',
                   default={'ipmi': 100,
                            'mgmt': 101,
                            'prod': 102,
                            'api': 103,
                            'data': 104},
                   help='Network name to VLAN mapping.'),

    config.StrOpt('worker', 'primary_dns',
                  help='Primary DNS resolver address.'),

    config.StrOpt('worker', 'secondary_dns',
                  help='Secondary DNS resolver address.'),

    config.StrOpt('worker', 'default_dns_zone',
                  help='DNS zone for environment.'),

    config.StrOpt('foreman', 'user',
                  default='',
                  help='Foreman user name for login.'),

    config.StrOpt('foreman', 'password',
                  default='',
                  help='Foreman user password.'),

    config.StrOpt('foreman', 'url',
                  default='https://127.0.0.1:443',
                  help='FOreman API endpoint URL.'),


    config.IntOpt('dhcp', 'first_ip_offset', default=4,
                  help='First ip in a subnet available for allocation'),

    config.IntOpt('dhcp', 'last_ip_offset', default=-3,
                  help='Last ip in a subnet available for allocation'),


    config.StrOpt('openstack', 'username',
                  help='DAO user name to authorize to OpenStack.'),

    config.StrOpt('openstack', 'password',
                  help='DAO password to authorize to OpenStack.'),

    config.StrOpt('openstack', 'project',
                  help='OpenStack project for the DAO user.'),

    config.StrOpt('openstack', 'auth_url',
                  default='http://127.0.0.1:5000/v2.0',
                  help='URL to keystone.'),

    config.StrOpt('openstack', 'region',
                  default='nova',
                  help='Openstack region name.'),

]
