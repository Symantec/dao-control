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
from dao.common import log
from dao.common import utils
from dao.control import exceptions


CONF = config.get_config()
logger = log.getLogger(__name__)


def update_sku(db, server, hw_info):
    """
    :type db: dao.control.db.api.Driver
    :type server: dao.control.db.model.Server
    :type hw_info: dict
    :return:
    """
    if hw_info:
        ram = hw_info['ram']
        cpu = hw_info['cpu']
        storage = hw_info['disks']
        skus = db.sku_get_all()
        sku_match = None
        for sku in skus:
            if ram == sku.ram and cpu == sku.cpu and \
                    storage == sku.storage:
                sku_match = sku
                break

        if sku_match is not None:
            db.server_update_sku(server, sku)
        else:
            msg = 'Validation failed, SKU not found for ' \
                  'cpu: {0}, ram: {1}, disks: {2}'.format(cpu, ram, storage)
            raise exceptions.DAOException(msg)
    else:
        raise exceptions.DAOException('HW info is empty')


@utils.Synchronized('sku.update_sku_quota')
def update_sku_quota(db, server):
    """
    :type db: dao.control.db.api.Driver
    :return:
    """
    # Update rack SKU quota
    rack = db.rack_get(name=server.asset.rack.name)
    rack_servers = db.servers_get_by(
        **{'asset.rack.name': server.asset.rack.name})
    skus = db.sku_get_all()

    sku_map = dict((sku.id, sku.name) for sku in skus)
    assigned_skus = [s.sku_id for s in rack_servers
                     if s.sku_id is not None]
    sku_counts = dict((sku_map[i], assigned_skus.count(i))
                      for i in set(assigned_skus))
    rack.sku_quota = sku_counts
    rack = db.update(rack)
    return rack
