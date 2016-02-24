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
import json
import requests
from dao.common import config
from dao.common import log
from dao.common import utils
from dao.control import exceptions
from dao.control import ipmi_helper
from dao.control import server_helper
from dao.control.worker import dns_helper


opts = [
    config.StrOpt('foreman', 'proxy_tftp',
                  help='Foreman TFTP proxy address.'),

    config.StrOpt('foreman', 'dhcp_proxy_url',
                  default='tcp://0.0.0.0:5557'),

    config.StrOpt('foreman', 's1_environment',
                  default='verification',
                  help='Foreman environment name used for host validation.'),

    config.StrOpt('foreman', 's2_environment',
                  default='production',
                  help='Foreman environment name used for host provisioning.'),

    config.StrOpt('foreman', 's1_os_name',
                  default='verifying',
                  help='Foreman hostgroup name for host validation.'),
]

config.register(opts)
CONF = config.get_config()

logger = log.getLogger(__name__)


@utils.singleton
class Foreman(object):
    def __init__(self):
        self.user = CONF.foreman.user
        self.password = CONF.foreman.password
        self.url = CONF.foreman.url
        self.proxy = None
        self.environments_cache = {}
        self.host_groups_cache = {}
        self.rack2networks = {}
        self.dns = dns_helper.DNSBase.get_driver()

    def server_delete(self, server):
        """Delete server from foreman if exists.
        Server is not created if exists but is rebooted with pxe boot

        :type server: dao.control.db.model.Server
        """
        try:
            foreman_server = self._get_host_no_cache(
                'mac', self._mac2mac(server.pxe_mac))
            self.dns.delete(foreman_server['name'], server)
            self._request('delete', 'api/hosts/%s' % foreman_server['id'])
        except exceptions.DAONotFound:
            pass

    def server_build(self, server, subnets, env_name, os_args={},
                     parameters={}, gateway='prod', build_net=None):
        """Build server based on an db information.
        Server is not created if exists but is rebooted with pxe boot

        :type server: dao.control.db.model.Server
        :type subnets: list of dao.control.db.model.Subnet
        :type env_name: str
        :param os_args: dictionary that describes os to be provisioned.
                        os_name field is used to get hostgroup (like a profile)
        :type os_args: dict
        :type parameters: dict
        :type gateway: str
        :param build_net: disctionary that describes how to build network
        :type build_net: dict
        """
        # delete server if exists
        try:
            foreman_server = self._get_host_no_cache(
                'mac', self._mac2mac(server.pxe_mac))
            self.dns.delete(foreman_server['name'], server)
            self._request('delete', 'api/hosts/%s' % foreman_server['id'])
        except exceptions.DAONotFound:
            pass
        # prepare parameters for configuring prod interface
        parameters = [{"name": key, "value": value, "nested": ""}
                      for key, value in parameters.items()]
        # create server
        hostgroup = self._search_one('hostgroups', name=os_args['os_name'])
        new_server = dict(
            name=server.name.replace('_', '-'),
            environment_id=self._get_one('environments', env_name)['id'],
            hostgroup_id=hostgroup['id'],
        )
        if parameters:
            new_server['host_parameters_attributes'] = parameters
        new_server['interfaces_attributes'] = \
            self._interface_attributes_get(server, subnets, gateway, build_net)
        # modify hostgroup args if required
        if os_args.get('media'):
            new_server['medium_id'] = \
                self._search_one('media', name=os_args['media'])['id']
        if os_args.get('ptable'):
            new_server['ptable_id'] = \
                self._search_one('ptables', name=os_args['ptable'])['id']
        if os_args.get('root_pass'):
            new_server['root_pass'] = os_args['root_pass']
        # finally create server and reboot it
        foreman_server = self._create_server(new_server)
        ipmi_helper.IPMIHelper.restart_pxe(server.asset.ip)
        self.dns.register(server)
        return foreman_server

    def _interface_attributes_get(self, server, subnets, gateway, build_net):
        """
        :type server: dao.control.db.model.Server
        :type subnets: dao.control.db.model.Subnet
        :type gateway: str
        :type build_net: dict
        :return:
        """
        interfaces = dict()
        domain_id = self._get_one('domains',
                                  CONF.worker.default_dns_zone)['id']
        # First add BMC
        ipmi_net = server_helper.network_get(subnets, 'ipmi')
        interfaces['bmc'] = dict(
            type='bmc',
            provider='IPMI',
            ip=server.asset.ip,
            mac=self._mac2mac(server.asset.mac),
            subnet_id=self._get_subnet(ipmi_net.name)['id'],
            domain_id=domain_id,
            username=CONF.worker.ipmi_login,
            password=CONF.worker.ipmi_password,
        )
        # Add pxe if there pxe vlan not in server.network or if
        # server.interfaces is empty
        mgmt_net = server_helper.network_get(subnets, 'mgmt')
        if build_net is None:
            # S0->S1
            interfaces['mgmt'] = dict(
                primary=('mgmt' == gateway),
                type='interface',
                managed=True,
                provision=True,
                ip=server.pxe_ip,
                mac=self._mac2mac(server.pxe_mac),
                subnet_id=self._get_subnet(mgmt_net.name)['id'],
                domain_id=domain_id,
            )
        else:
            # S1->S2 workflow
            macs = dict()
            type2type = dict(bond='bond',
                             symlink='interface',
                             phys='interface',
                             tagged='interface')
            logger.debug(repr(build_net))
            for name, net in build_net:
                net_name = net.get('name')
                mac = net.get('mac') or macs[net['interfaces'][0]]
                macs[name] = mac
                vlan = net.get('vlan')
                ip = net.get('ip')
                if net['type'] == 'symlink':
                    # We need just to update parameters
                    name = net['interfaces'][0]
                    iface = interfaces[name]
                    # Update vlan net_name dependent fields
                    iface.update(primary=(net_name == gateway),
                                 provision=(net_name == 'mgmt'))
                else:
                    iface = dict(
                        primary=(net_name == gateway),
                        type=type2type[net['type']],
                        identifier=name,
                        managed=True,
                        provision=(net_name == 'mgmt'),
                        mac=self._mac2mac(mac))
                if ip:
                    db_net = dict((i.vlan_tag, i) for i in subnets)[vlan]
                    iface.update(
                        ip=ip,
                        subnet_id=self._get_subnet(db_net.name)['id'],
                        domain_id=domain_id)
                if net['type'] == 'bond':
                    iface.update(dict(
                        mode='802.3ad',
                        bond_options='miimon=100 xmit_hash_policy=1',
                        attached_devices=net['interfaces']))
                if net['type'] == 'tagged':
                    iface.update(dict(
                        tag=str(vlan),
                        virtual=True,
                        attached_to=net['interfaces'][0]))
                interfaces[name] = iface
        return dict((i, iface) for i, iface in enumerate(interfaces.values()))

    def ensure_os_family(self, os_args):
        try:
            hostgroup = self._search_one('hostgroups', name=os_args['os_name'])
        except exceptions.DAONotFound:
            raise exceptions.DAONotFound('OS (hostgroup) {0} not found'.
                                         format(os_args['os_name']))
        os = self._get_one('operatingsystems', hostgroup['operatingsystem_id'])
        return os['family']

    def get_host(self, server):
        return self._get_host_no_cache('mac', self._mac2mac(server.pxe_mac))

    def subnet_create(self, name, ip, mask, gateway, vlan):
        """Create subnet, scip if exists
        @param name: subnet name
        @param ip: string, ip address
        @param mask: string, netmask
        @param gateway: string, gateway
        """
        name = self._get_subnet_name(name)
        try:
            self._get_subnet(name)
            return
        except exceptions.DAONotFound:
            pass
        domain = self._get_domain(CONF.worker.default_dns_zone)
        data = dict(
            name=name,
            network=ip,
            mask=mask,
            dhcp_id='',
            tftp_id=self._get_proxy('tftp')['id'],
            dns_id="",
            domain_ids=[str(domain['id'])],
            dns_primary=CONF.worker.primary_dns,
            dns_secondary=CONF.worker.secondary_dns,
            boot_mode='Static',
            vlanid=str(vlan))
        if gateway is not None:
            data['gateway'] = gateway
        data = {"subnet": data}
        self._request('post', 'api/subnets', data=data)

    def foreman_test(self):
        """Test foreman for proper setup.
        returns url to validation check script
        """
        self._get_environment(CONF.foreman.s1_environment)
        self._get_environment(CONF.foreman.s2_environment)
        hg = self._search_one('hostgroups', name=CONF.foreman.s1_os_name)
        hg = self._get_object('hostgroups', hg['id'])
        s1_params = dict((p['name'], p['value']) for p in hg['parameters'])
        return s1_params['check_url']

    def hostgroup_list(self, name):
        if name:
            return self._search_all('hostgroups', name=name)
        else:
            return self._search_all('hostgroups')

    @staticmethod
    def _mac2mac(mac):
        return mac.lower().replace('-', ':')

    def _create_server(self, server):
        # Create server
        data = dict(
            type='Host::Managed',
            managed='true',
            provision_method='build',
            build='true')
        data.update(server)
        ret_server = self._request('post', 'api/hosts', data={'host': data})
        return ret_server

    def _get_subnet(self, name):
        # create network
        return self._search_one('subnets', name=self._get_subnet_name(name))

    @staticmethod
    def _get_subnet_name(name):
        return name.replace('.', '_')

    def _get_host_no_cache(self, key, value):
        # create network
        kwargs = {key: value}
        host = self._get_objects_by('hosts', **kwargs)
        if not host:
            raise exceptions.DAONotFound('No hosts found for %s: %s' %
                                         (key, value))
        return host[0]

    def _get_domain(self, name):
        # create network
        return self._get_one('domains', name)

    def _get_environment(self, name, create=False):
        return self._get_one('environments', name)

    def _get_proxy(self, proxy_type):
        name = CONF.foreman['proxy_{0}'.format(proxy_type)]
        proxy = self._get_one('smart_proxies', name)
        return proxy

    @utils.CacheIt(120)
    def _search_one(self, object_type, **kwargs):
        obj = self._get_objects_by(object_type, **kwargs)
        if obj:
            return obj[0]
        else:
            raise exceptions.DAONotFound('Can not find foreman %s, %s' %
                                         (object_type, kwargs))

    @utils.CacheIt(120)
    def _search_all(self, object_type, **kwargs):
        return self._get_objects_by(object_type, **kwargs)

    @utils.CacheIt(120)
    def _get_one(self, object_type, name_id):
        return self._get_object(object_type, name_id)

    def _get_objects_by(self, object_type, **kwargs):
        url = 'api/%s' % object_type
        params = ['{0}="{1}"'.format(key, val) for key, val in kwargs.items()]
        params = {'search': '&'.join(params)}
        obj = self._request('get', url, params=params)['results']
        return obj

    def _get_object(self, object_type, name_id):
        url = 'api/%s/%s' % (object_type, name_id)
        return self._request('get', url)

    @utils.Synchronized('foreman._request')
    def _request(self, method, url, params=None, data=None):
        url = requests.utils.requote_uri('%s/%s' % (self.url, url))
        if data:
            data = json.dumps(data)
        log_func = logger.debug if method == 'get' else logger.info
        log_func('%s issued, url=%s, params=%s, data=%s',
                 method, url, params, data)
        method = getattr(requests, method)
        for i in range(5):
            r = method(url=url,
                       auth=(self.user, self.password),
                       data=data, params=params,
                       verify=False,
                       headers={'Content-Type': 'application/json',
                                'Accept': 'version=2,application/json'})
            if 200 <= r.status_code < 300:
                break
            eventlet.sleep(5)
        else:
            if r.status_code == 404:
                raise exceptions.DAONotFound('%s not found' % url)
            logger.warning(r.text)
            data = r.json().get('error')
            msg = data.get('full_messages') or data.get('message') or r.text
            raise exceptions.DAOException(
                'Text: %r, foreman status code is: %s' %
                (msg, r.status_code))
        r = r.json()
        # logger.debug('Foreman response: %r', r)
        return r
