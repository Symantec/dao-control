# Copyright 2016 Symantec Inc.
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
import argparse
from dao.control import tool_init
from dao.control.db import manage as db_manage


def main():
    controllers = [db_manage.Controller]
    cmd2ctl = dict((ctl.command, ctl) for ctl in controllers)
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command',
                                       help='sub-command help')

    for cmd, ctl in cmd2ctl.items():
        sub_parser = subparsers.add_parser(cmd, help=ctl.help)
        ctl.fill_parser(sub_parser)

    args = parser.parse_args()

    cmd2ctl[args.command].feed(args)


if __name__ == '__main__':
    main()
