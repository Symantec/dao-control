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
import netaddr
import requests
import traceback

from dao.common import config
from dao.common import log
from dao.common import rpc

from dao.control import exceptions
from dao.control import server_helper
from dao.control import server_processor
from dao.control import sku
from dao.control.db import api as db_api
from dao.control.worker import discovery
from dao.control.worker import provisioning
from dao.control.worker import rack_discover
from dao.control.worker.dhcp import base as dhcp_helper
from dao.control.worker.hooks import base as hook_base
from dao.control.worker.switch import base as switch_base
from dao.control.worker.validation import helper as validation_helper


opts = [
    config.StrOpt('worker', 'name',
                  help='Unique name assigned to Worker for identification.'),

    config.StrOpt('worker', 'port',
                  default='5556',
                  help='Port listening for RPC messages to Worker.'),

    config.StrOpt('worker', 'fqdn_net',
                  default='prod',
                  help='Network name where server FQDN is reachable.'),

    config.IntOpt('worker', 'validation_port',
                  default=5000,
                  help='Port number of validation agent.'),

]

config.register(opts)
CONF = config.get_config()

LOG = log.getLogger(__name__)


class ServerLock(object):
    locked_keys = dict()

    def __init__(self, sid):
        self.sid = sid

    def __enter__(self):
        if self.sid in self.locked_keys:
            raise exceptions.DAOConflict('Server {0} is processed'.
                                         format(self.sid))
        self.locked_keys[self.sid] = eventlet.greenthread.getcurrent()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.locked_keys.pop(self.sid)


class Manager(rpc.RPCServer):
    """
    Class implements worker manager inheriting RPC server (ZMQ)
    Class implements some tricks.
    1. Lock servers to prevent event racing (see track_server, Manager._spawn
    and for example Manager.validate).
    2. Have periodic logic (Manager._periodic_runner)
    """
    def __init__(self):
        super(Manager, self).__init__(CONF.worker.port)
        self.db = db_api.Driver()
        self.worker = self.db.worker_register(CONF.worker.name, self.url,
                                              CONF.common.location)
        self.dhcp = dhcp_helper.DHCPBase.get_helper(self.worker)
        self.provision = provisioning.get_driver(self.url)
        self.discovery = discovery.Discovery(self.worker,
                                             self.dhcp)
        self.vlan2net = server_helper.vlan2net()
        self._switch = switch_base.Base.get_helper(self.db)

    @staticmethod
    def stop_server(sid, lock_id):
        """ Find a green thread that process server and kill it if can be found
        :param sid: Server ID
        :param lock_id: Lock id field from Server
        :rtype: None
        """
        thread = ServerLock.locked_keys.get(sid)
        if thread is not None:
            eventlet.greenthread.kill(thread, exceptions.DAOException,
                                      'Stopped by user request')
            return True
        else:
            return False

    def rack_discover(self, switch_name, ip, create):

        switch = self._switch.switch_discover(switch_name, ip)
        if create:
            rack = rack_discover.rack_ensure(self.db, switch['rack_name'])
            nd = rack_discover.switch_ensure(
                self.db, switch_name, ip, rack,
                brand=switch['brand'],
                model=switch['model'],
                serial=switch['serial'],
                interfaces=switch['interfaces'])
            return rack.to_dict(), nd.to_dict()
        else:
            return switch

    def dhcp_rack_update(self, rack_name):
        subnets = self.db.subnets_get(rack_name)
        self.dhcp.ensure_subnets(subnets)

    def dhcp_hook(self, ipmi_ip, ipmi_mac, force=False):
        """ Process DHCP hook from DHCP server.
        :type ipmi_ip: str
        :type ipmi_mac: str
        :type force: bool
        """
        ipmi_mac = str(netaddr.eui.EUI(ipmi_mac))
        if force:
            self.discovery.cache_clean_for_mac(ipmi_mac)
        self.discovery.dhcp_hook(ipmi_ip, ipmi_mac, force)

    def discovery_cache_reset(self, ipmi_mac):
        """ Clear discovery cache.
        :type ipmi_mac: str
        """
        if ipmi_mac is not None:
            ipmi_mac = str(netaddr.eui.EUI(ipmi_mac))
            self.discovery.cache_clean_for_mac(ipmi_mac)
            return set((ipmi_mac,))
        else:
            return self.discovery.cache_clean()

    def server_delete(self, sid):
        server = self.db.server_get_by(id=sid)
        if server.lock_id:
            raise exceptions.DAOConflict('Server {0} is busy'.
                                         format(server.name))
        # 1. Delete from foreman
        self.provision.server_delete(server)
        # 2. Delete from DHCP
        self.dhcp.delete_for_serial(server.asset.serial)
        # 3. Delete from ironic
        hook_base.HookBase.get_hook(server, self.db).deleted()
        # 4. Delete form db
        for iface in server.interfaces.values():
            self.db.object_delete(iface)
        self.db.object_delete(server)
        self.db.object_delete(server.asset)
        # 5 Clean discovery cache
        self.discovery.server_delete(server)
        return 'Deleted'

    def rack_renumber(self, rack_name, fake):
        """ Generate server number and rack unit """
        servers = self.db.servers_get_by(**{'asset.rack.name': rack_name})
        for index, s in enumerate(servers):
            if s.asset.status != 'Discovered':
                continue
            if fake:
                s_number, u_number = str(index), 0
            else:
                s_number, u_number = self.discovery.get_server_number(
                    s.asset.rack, 'mgmt', s.pxe_mac)
            s.server_number = str(s_number)
            s.rack_unit = u_number
            self.db.server_update(s)

    def validate_server(self, sid, lock_id):
        """ Start server validation
        1. Validate switch for the rack server belongs to
        2. Run scripts to update/validate IPMI
        3. Add server to provisioning tool and reboot it
        4. Periodically check if server is provisioned (self._check_validated)

        :param sid: Server ID
        :param lock_id: Lock id field from Server
        """
        with ServerLock(sid):
            server = self.db.server_get_by(id=sid, lock_id=lock_id)
            try:
                server.status = 'Validating'
                server.message = ''
                self.db.server_update(server, 'Validating started')

                hook_base.HookBase.get_hook(server, self.db).pre_validate()
                rack, server = self._prepare_server(server, 'Validating')
                # Check if ToR is validated.
                status, msg = self._switch.switch_validate_for_rack(rack)
                if status != 'Validated':
                    raise exceptions.DAOException('ToR failed: %s' % msg)
                rack.status = status
                rack = self.db.rack_update(rack)
                self.provision.server_s0_s1(server, rack)
                self.db.server_update(server)
            except Exception, exc:
                msg = str(traceback.format_exc())
                LOG.warning('Error: %s, msg is %s', server.name, msg)
                server_processor.ServerProcessor(server).error(exc.message)
                raise

    def _check_validated(self, sid, lock_id):
        """ Function called periodically in a green thread
        (from self._check_state) to
        1. check if server is provisioned to validation image.
        2. run validation script remotely (using RPC)
        3. Validate switch configuration for this server

        Parameters:
        :param sid: Server ID
        :param lock_id: Lock id field from Server
        :rtype: None
        """
        with ServerLock(sid):
            server = self.db.server_get_by(id=sid, lock_id=lock_id)
            try:
                done, msg = self.provision.is_provisioned(server, 'mgmt')
                if not done:
                    raise exceptions.DAOIgnore(msg)
                done, msg = validation_helper.is_up(
                    server, CONF.worker.validation_port)
                if not done:
                    raise exceptions.DAOIgnore(msg)
                server = self._run_validation_scripts(server)
                # Validate switch configuration for server.
                rack = self.db.rack_get(name=server.rack_name)
                self._switch.switch_validate_for_server(rack, server)
                # Validation completed
                server.status = 'Validated'
                self.db.server_update(server, comment='Validated')
                server = hook_base.HookBase.get_hook(server,
                                                     self.db).validated()
                server_processor.ServerProcessor(server).next()
            except exceptions.DAOIgnore, exc:
                # Server is not ready yet. Will try next time
                server.message = exc.message
                self.db.update(server)
            except Exception, exc:
                LOG.warning(traceback.format_exc())
                if isinstance(exc, KeyError):
                    exc.message = 'KeyError: {0}'.format(exc.message)
                server = self._reload_server_record(server)
                server_processor.ServerProcessor(server).error(exc.message)

    def _run_validation_scripts(self, server):
        """ Run validation scripts
        :type server: api.models.Server
        :rtype: api.models.Server
        """
        self.db.server_update(server, 'Running validation script')
        rack = self.db.rack_get(id=server.asset.rack_id)
        # Weird but let the server load everything
        eventlet.sleep(60)
        # Prepare validation script parameters
        ip = server_helper.get_net_ip(server, 'mgmt')
        if server.asset.status == 'New':
            # New server. Pull the interfaces data and generate networking
            code = validation_helper.get_server_info_code()
            asset_dict, interfaces = \
                self.call_dao_agent(ip, {}, code)
            self.discovery.finalize(server, asset_dict, interfaces)
            server = self._reload_server_record(server)
            nets = self.db.subnets_get(rack.name)
            server.network = server_helper.generate_network(
                self.dhcp, rack, server, nets)
            self.db.server_update(server)
            server = self._reload_server_record(server)
        # Run validation script
        s_dict = server.to_dict()
        s_dict['meta']['network'] = server_helper.network_build(rack, server)
        code = validation_helper.get_validation_code()
        hw_info = self.call_dao_agent(ip, s_dict, code)
        # And finally validate and update sku for server/rack
        sku.update_sku(self.db, server, hw_info)
        sku.update_sku_quota(self.db, server)
        return server

    def _reload_server_record(self, server):
        return self.db.server_get_by(id=server.id, lock_id=server.lock_id)

    @staticmethod
    def call_dao_agent(ip, server_dict, code):
        data = dict(server_dict=server_dict, code=code)
        result = requests.post('http://{0}:5000/v1.0/validate'.format(ip),
                               data=json.dumps(data),
                               headers={'Content-Type': 'application/json'})

        if 200 <= result.status_code <= 300:
            return result.json()['result']
        else:
            raise exceptions.DAOException(result.text)

    def provision_server(self, sid, lock_id):
        """ Configure provisioning tool to provision server with a final image
        and restart server

        Parameters:
        :param sid: Server ID
        :param lock_id: Lock id field from Server
        :rtype: None
        """
        with ServerLock(sid):
            server = self.db.server_get_by(id=sid, lock_id=lock_id)
            try:
                server.status = 'Provisioning'
                self.db.server_update(server, 'Provisioning started')
                hook_base.HookBase.get_hook(server, self.db).pre_provision()
                rack, server = self._prepare_server(server, 'Provisioning')
                port = CONF.worker.validation_port
                up, _ = validation_helper.is_up(server, port)
                if up:
                    # Configure HDD first
                    ip = server_helper.get_net_ip(server, 'mgmt')
                    code = validation_helper.get_raid_configure_code()
                    self.call_dao_agent(ip, server.to_dict(), code)
                    # And finally start provisioning
                    self.provision.server_s1_s2(server, rack)
                    self.db.server_update(server, 'Provisioned')
                else:
                    msg = 'Validation agent is not loaded, restart from S0'
                    server_processor.ServerProcessor(server).error(msg)
            except Exception, exc:
                LOG.warning(exc.message)
                msg = str(traceback.format_exc())
                LOG.warning('Error: %s, msg is %s', server.name, msg)
                server_processor.ServerProcessor(server).error(exc.message)
                raise

    def _check_provisioned(self, sid, lock_id):
        """ Function called periodically (from self._check_state) in a green
        thread to check if server is provisioned to target image.
        Parameters:
        :param sid: Server ID
        :param lock_id: Lock id field from Server
        :rtype: None
        """
        with ServerLock(sid):
            server = self.db.server_get_by(id=sid, lock_id=lock_id)
            try:
                done, msg = self.provision.is_provisioned(
                    server, CONF.worker.fqdn_net)
                if done:
                    server.status = 'Provisioned'
                    self.db.server_update(server)
                    server_processor.ServerProcessor(server).next()
                    hook_base.HookBase.get_hook(server, self.db).provisioned()
                else:
                    if server.message != msg:
                        self.db.server_update(server, msg)
            except Exception, exc:
                msg = str(traceback.format_exc())
                LOG.warning('Error: %s, msg is %s', server.name, msg)
                server_processor.ServerProcessor(server).error(exc.message)

    def _prepare_server(self, server, status):
        """ Prepare server for provisioning
        Parameters:
        :type server: dao.control.db.model.Server
        :rtype: (dao.control.db.model.Rack, dao.control.db.model.Server)
        """
        rack = self.db.rack_get(name=server.rack_name)
        server.gw_ip = rack.gw_ip
        nets = self.db.subnets_get(rack_name=rack.name)
        # pxe_ip might be not allocated yet. Ensure it.
        server.pxe_ip = self.dhcp.allocate(
            rack,
            server_helper.network_get(nets, 'mgmt'),
            server.asset.serial, server.pxe_mac, server.pxe_ip)
        if server.asset.status != 'New':
            server.network = server_helper.generate_network(
                self.dhcp, rack, server, nets)
        # generate name + fqdn
        server.name = server.generate_name(rack.environment)
        server.fqdn = server_helper.fqdn_get(server)
        self.db.server_update(server, '%s started' % status)
        return rack, server

    def os_list(self, os_name):
        """ Return list of operation systems (hostgroups for Foreman) available
        for provisioning"""
        return self.provision.os_list(os_name)

    @staticmethod
    def health_check():
        """Perform dependent systems health check.
        :returns: dict
        """
        status = {}
        return status

    def do_main(self):
        """ Function is an entry point for manager.
        Start periodic enventlet task and pass control to RPC."""
        self.pool.spawn_n(self._periodic_runner)
        super(Manager, self).do_main()

    def _periodic_runner(self):
        """ Function is called in a green thread to perform periodic actions
        for manager"""
        while True:
            try:
                self._check_state()
            except Exception:
                traceback.print_exc()
                LOG.warning(traceback.format_exc())
            eventlet.sleep(30)

    def _check_state(self):
        """ Periodic function that pull all servers in a validation/provisioning
        state and start green thread with a code to ensure if process is
        completed"""
        self._run_check_by_status('Validating', self._check_validated.__name__)
        self._run_check_by_status('Provisioning',
                                  self._check_provisioned.__name__)

    def _run_check_by_status(self, status, func_name):
        """ Extention for self._check_state function.
        :param status: Which status should be used as a filter for servers to
        be processed
        :param func_name: function to be called to check if
        validation/provisioning process completed
        :return: None
        """
        racks = self.db.racks_get_by_worker(self.worker)
        for rack in racks:
            servers = self.db.servers_get_by(**{'asset.rack.id': rack.id,
                                                'status': status})
            for server in servers:
                if server.id in ServerLock.locked_keys:
                    continue
                if server.meta.get('ironicated', False):
                    continue
                try:
                    self._spawn(None, func_name, (server.id,
                                                  server.lock_id), {})
                except exceptions.DAONotFound, exc:
                    LOG.warning(traceback.format_exc())
                    server_processor.ServerProcessor(server).error(exc.message)
                except Exception:
                    LOG.warning(traceback.format_exc())


def run():
    LOG.info('Started')
    try:
        manager = Manager()
        eventlet.monkey_patch()
        manager.do_main()
    except Exception:
        LOG.warning(traceback.format_exc())
        raise
