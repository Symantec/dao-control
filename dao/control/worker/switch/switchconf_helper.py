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


import yaml
import netaddr
import traceback
from dao.common import config
from dao.common import log
from dao.common import utils as dao_utils
from dao.control import exceptions
from dao.control import server_helper
from dao.control.worker.switch import base

from switchconf import introspector
from switchconf import utils
from switchconf import validator
from switchconf.db import driver
from switchconf.switch import manager


opts = [config.StrOpt('switchconf', 'switch_user',
                      help=''),
        config.StrOpt('switchconf', 'switch_password',
                      help=''),
        config.StrOpt('switchconf', 'vrf_mapping',
                      help=''),
        config.StrOpt('switchconf', 'dhcp_relays',
                      help=''),
        config.StrOpt('switchconf', 'required_features',
                      help=''),
        config.StrOpt('switchconf', 'default_vlans',
                      help=''),
        config.StrOpt('switchconf', 'service_port_speed',
                      help=''),
        config.BoolOpt('switchconf', 'enabled',
                       default=True,
                       help='Turn on Switch configuration validation.'),
        ]

config.register(opts)
CONF = config.get_config()
LOG = log.getLogger(__name__)


class SwitchConf(base.Base):
    def server_number_get(self, rack, net_map, server):
        """
        Function detects server number, using 2 sources:
         - number of port used for IPMI interface
         - lambda function from config file for this location.

         :type rack: dao.control.db.model.Rack
         :type net_map: dao.control.db.model.NetworkMap
         :type server: dao.control.db.model.Server
         :rtype: int
        """
        mac = netaddr.eui.EUI(server.pxe_mac)
        vlan_tag = server_helper.net2vlan()['mgmt']
        mac2port = self._get_mac2port(vlan_tag, rack)
        port2number = eval(net_map.mgmt_port_map)
        switch, iface = (mac2port[mac])
        switch_index, _ = server_helper.switch_name_parse(switch)
        server_number = port2number(switch_index, iface.port_no)
        return server_number

    def switch_discover(self, hostname, ip):
        mgr_pool = None
        try:
            mgr_pool = manager.SwitchManagerPool(
                self.db,
                CONF.switchconf.switch_user,
                CONF.switchconf.switch_password,
                False)

            switch = mgr_pool.get_switch(ip)
            ifaces = switch.interfaces
            model, serial = switch.get_version()
            brand = switch.brand
            rack_name = switch.rack_generator(hostname)
            return dict(brand=brand,
                        model=model,
                        serial=serial,
                        interfaces=ifaces,
                        rack_name=rack_name)
        finally:
            if mgr_pool:
                mgr_pool.cleanup()

    @dao_utils.Synchronized('switchconf.SwitchConf.switch_validate_for_server')
    def switch_validate_for_server(self, rack, server):
        if not CONF.switchconf.enabled:
            return
        try:
            # Because of for FX2 servers bonded interfaces depends on
            # a slot in a chassis, get patched network map
            net = server_helper.network_map_get(rack, server)
            errors = self._validate_switch_for_server(rack, net, server)
            if errors:
                raise exceptions.DAOException(
                    self._format_switch_errors(errors))
        except Exception, exc:
            LOG.warning(traceback.format_exc())
            raise exceptions.DAOException(
                'Failed to validate switch configuration: {0}'.
                format(repr(exc)))

    @dao_utils.Synchronized('switchconf.SwitchConf.switch_validate_for_rack')
    def switch_validate_for_rack(self, rack):
        if not CONF.switchconf.enabled:
            return 'Validated', 'Ignored'

        if rack.status == 'Validated':
            return 'Validated', 'ok'

        try:
            all_errors = self._validate_switch_for_rack(rack)
            # Hint: filter out messages about missing BMC MACs from errors
            warnings = []
            errors = []
            for error in all_errors:
                if 'MAC not found in' in error.get('_message', ''):
                    warnings.append(error)
                else:
                    errors.append(error)

            if errors:
                status = 'ValidatedWithErrors'
                message = self._format_switch_errors(errors)
            else:
                status = 'Validated'
                if warnings:
                    message = self._format_switch_errors(warnings)
                else:
                    message = 'Ok'
        except Exception, exc:
            LOG.warning(traceback.format_exc())
            status = 'ValidatedWithErrors'
            message = 'Failed to validate switch configuration. %s'
            message %= exc.message
        return status, message

    def _validate_switch_for_rack(self, rack, features_only=False):
        if not int(CONF.switchconf.enabled):
            return []
        switch_mgr_pool = None
        try:
            rv, switch_mgr_pool = self._prepare_validator(rack)
            errors = rv.validate_features()
            if not features_only:
                errors += rv.validate_service_ports('ipmi')
                errors += rv.validate_virtual_l3_ifaces(
                    ['ipmi', 'mgmt', 'prod'])
                errors += rv.validate_vlans()
            return errors
        finally:
            if switch_mgr_pool is not None:
                switch_mgr_pool.cleanup()

    @staticmethod
    def _format_switch_errors(errors):
        msg = ''
        for error in errors:
            # Format error message
            try:
                switch_msg = error.get(
                    '_message', 'No message').format(**error)
            except Exception:
                LOG.warning('Failed to format %s', repr(error))
                LOG.warning(traceback.format_exc())
                switch_msg = 'Error formatting message, see worker log.'

            # Add message with additional info to change notice
            if msg:
                msg += '\n'
            msg += switch_msg
        # TODO: remove it
        if len(msg) > 254:
            msg = msg[:254]
        return msg

    def _validate_switch_for_server(self, rack, net, server):
        if not int(CONF.switchconf.enabled):
            return None
        switch_mgr_pool = None
        try:
            rv, switch_mgr_pool = self._prepare_validator(rack)
            lacp_errors = rv.validate_server_link_aggregation(net, server)
            mgmt_errors = rv.validate_service_ports('mgmt', server.name)
            return lacp_errors + mgmt_errors
        finally:
            if switch_mgr_pool is not None:
                switch_mgr_pool.cleanup()

    @staticmethod
    def _prepare_validator(rack):
        db_mgr = driver.Driver()
        switch_mgr_pool = manager.SwitchManagerPool(
            db_mgr, CONF.switchconf.switch_user,
            CONF.switchconf.switch_password, False)

        vrf_mapping = yaml.load(CONF.switchconf.vrf_mapping)
        dhcp_relays = yaml.load(CONF.switchconf.dhcp_relays)
        required_features = yaml.load(CONF.switchconf.required_features)
        default_vlans = [
            int(x) for x in yaml.load(CONF.switchconf.default_vlans)]
        service_port_speed = utils.convert_port_speed(
            CONF.switchconf.service_port_speed)
        rv = validator.RackValidator(
            rack, db_mgr, switch_mgr_pool, vrf_mapping, dhcp_relays,
            required_features, default_vlans, service_port_speed)
        return rv, switch_mgr_pool

    @staticmethod
    def _get_mac2port(vlan_tag, rack):
        db_mgr = driver.Driver()
        switch_mgr_pool = manager.SwitchManagerPool(
            db_mgr, CONF.switchconf.switch_user,
            CONF.switchconf.switch_password, False)
        x = introspector.RackSwitchIntrospector(db_mgr, switch_mgr_pool)
        return dict((m, (n, p))
                    for (n, p, m) in x.get_subnet_mac_table_by_rack_name(
                        vlan_tag, rack)
                    if p.kind and p.kind != 'virtual' and p.is_port)
