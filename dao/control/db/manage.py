#
# Copyright 2015 Symantec.
#
# Author: Sergii Kashaba <sergii_kashaba@symantec.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import argparse
import os.path
import migrate.exceptions
from migrate.versioning import api as versioning_api
from migrate.versioning import repository

from dao.control.db import session_api
from dao.control.db import migrate_repo


CONF = session_api.CONF
ACTIONS = dict()


def action(name):
    def _foo(f):
        ACTIONS[name] = f.__name__
        return f
    return _foo


class Controller(object):
    command = 'db'
    help = 'DB manage'

    @staticmethod
    def fill_parser(parser):
        parser.add_argument('action', choices=ACTIONS.keys())

    @classmethod
    def feed(cls, args):
        print getattr(cls, ACTIONS[args.action])()

    @staticmethod
    def _get_repo_path():
        return repository.Repository(os.path.split(migrate_repo.__file__)[0])

    @classmethod
    @action('control')
    def _db_version_control(cls):
        try:
            versioning_api.version_control(
                CONF.db.sql_connection, cls._get_repo_path())
        except migrate.exceptions.DatabaseAlreadyControlledError:
            return 'DB is already controlled my migrate'

        return 'Success'

    @classmethod
    @action('upgrade')
    def _db_upgrade(cls):
        versioning_api.upgrade(
            CONF.db.sql_connection, cls._get_repo_path())
        return 'Success'

    @classmethod
    @action('version')
    def _db_version(cls):
        return versioning_api.db_version(
            CONF.db.sql_connection, cls._get_repo_path())
