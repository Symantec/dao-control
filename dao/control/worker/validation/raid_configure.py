#!/bin/env python
#
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


import os
import time


def send_error(error_msg):
    raise RuntimeError('Pre-provisioning error: {0}'.format(error_msg))


def raid_init(_server, raid):
    cleanup_cmd = \
        ('for num in `seq 5`; '
         'do dd if=/dev/zero of=/dev/sda${num} bs=512 count=2 >/dev/null 2>&1;'
         ' done; dd if=/dev/zero of=/dev/sda bs=512 count=2 >/dev/null 2>&1 ;'
         '/opt/MegaRAID/MegaCli/MegaCli64 -CfgForeign -Clear -aALL')
    if os.popen(cleanup_cmd).close():
        raise RuntimeError('Can not cleanup raid')
    if _server['asset']['brand'] == 'Supermicro':
        exe = ' /usr/bin/raid-init-smc >/dev/null 2>&1'
    else:
        exe = ('/usr/bin/raid-init.pl --init --raid ' + raid +
               ' >/dev/null 2>&1')
    return os.popen(exe).close()


def main(server_dict):
    global RESULT
    print 'Raid config started:', time.ctime()
    hdd_type = server_dict['hdd_type'].lower().replace('raid', '')
    if raid_init(server_dict, hdd_type):
        send_error("Raid Init Failed")
    print 'After raid config:', time.ctime()
    RESULT = True

if __name__ == '__main__':
    global server
    main(server)
