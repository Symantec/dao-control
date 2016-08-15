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


import netaddr
import os
import sh
import time

dim = {'B': pow(1024, 0),
       'KB': pow(1024, 1),
       'MB': pow(1024, 2),
       'GB': pow(1024, 3),
       'TB': pow(1024, 4)}
dim_hdd = {'GB': pow(1000, 3), 'TB': pow(1000, 4)}


def send_error(error_msg):
    raise RuntimeError('ValidatedWithErrors: {0}'.format(error_msg))


def get_hw_info(_server):
    model, unit, ram, cpu, disks = _server['description'].split(',')
    ram = ram.split()
    ram = ram[0] if ram else ''
    hw_class = dict((k, v.strip()) for k, v in locals().items() if k[0] != '_')
    return hw_class, _server


def get_mem_gb():
    dmidecode = '/usr/sbin/dmidecode'
    mem = os.popen(dmidecode +
                   ' -t memory |grep Size |grep -vi "no module"').read()
    mem = [l.split()[1:] for l in mem.splitlines()]
    mem = sum(int(l[0])*dim[l[1]]/dim['GB'] for l in mem)
    return '{0}GB'.format(mem)


def check_mem(mem, real_mem):
    if mem == real_mem:
        return True
    else:
        send_error("Memory doesn't match")


def get_hdds_itop(disks):
    disks = disks.split('*')[1:]
    hdds_itop = []
    for item in disks:
        disk = item.split()
        hdds_itop.append(dict(size=int(disk[2][0:-2])*dim_hdd[disk[2][-2:]],
                              type=disk[-1],
                              count=int(disk[0])))
    return hdds_itop


def get_hdds_local(_server):
    hdds_local = {}
    if _server['asset']['brand'] == 'Supermicro':
        exe = 'sas3ircu 0 DISPLAY | grep "Size (in MB)/(in sectors)\|Protocol"'
        sas3ircu_output = os.popen(exe).read().rstrip().splitlines()
        for size, hdd_type in zip(sas3ircu_output[::2], sas3ircu_output[1::2]):
            hdd_type = hdd_type.split()[-1]
            size = size.split()[-1].split('/', 1)[0]
            size = int(float(size) * dim['MB'])
            size = (size/dim_hdd['GB'])*dim_hdd['GB']
            key = (size, hdd_type)
            if key in hdds_local:
                hdds_local[key] += 1
            else:
                hdds_local[key] = 1
    else:
        megacli = '/opt/MegaRAID/MegaCli/MegaCli64'
        exe = megacli + ' -PDList -aALL | grep "Raw Size:\|PD Type:"'
        megacli_output = os.popen(exe).read().rstrip().splitlines()
        for hdd_type, size in zip(megacli_output[::2], megacli_output[1::2]):
            hdd_type = hdd_type.split()[-1]
            size = size.split()
            size = int(float(size[2]) * dim[size[3]])
            # Round it to GB
            size = (size/dim_hdd['GB'])*dim_hdd['GB']
            key = (size, hdd_type)
            if key in hdds_local:
                hdds_local[key] += 1
            else:
                hdds_local[key] = 1
    return [dict(size=k[0],
                 type=k[1],
                 count=v) for k, v in hdds_local.items()]


def check_hdds(hdds_itop, hdds_local):
    if len(hdds_itop) != len(hdds_local):
        send_error("Number of disk sets doesn't match")

    if sorted(hdds_itop) != sorted(hdds_local):
        msg = 'Disks are different. Expected <%s>, found <%s>' % (hdds_itop,
                                                                  hdds_local)
        send_error(msg)


def hdd2itop(disks):
    def size2human(size):
        if size % dim_hdd['TB']:
            return '{0}GB'.format(size/dim_hdd['GB'])
        else:
            return '{0}TB'.format(size/dim_hdd['TB'])
    template = '*{0[count]} x {1} 0K RPM {0[type]}'
    return ' '.join(template.format(item, size2human(item['size']))
                    for item in disks)


def get_cpu_local():
    def get_value_by_prefix(prefix):
        return [l.split(':')[-1].strip()
                for l in cpuinfo if l.startswith(prefix)]
    with open('/proc/cpuinfo', 'r') as fd:
        cpuinfo = fd.read().splitlines()
        cpus = len(set(get_value_by_prefix('physical id')))
        cores = get_value_by_prefix('cpu cores')[0]
        model = get_value_by_prefix('model name')[0]
        proc = '{cpus} x {model} {cores}C'.format(**locals())
        return proc


def check_cpu(cpu_itop, cpu_local):
    def cpu2values(cpu):
        cpu = cpu.replace('(R)', '').split()
        cpus = cpu[0]
        family = cpu[3]
        freq = float(cpu[-2][0:3])
        return cpus, family, freq
    if cpu2values(cpu_itop) != cpu2values(cpu_local):
        send_error("CPU doesn't match")


def get_bond_status(bond):
    with open('/proc/net/bonding/%s' % bond, 'r') as f:
        for line in f.readlines():
            line = line.strip().lower()
            if not line.startswith('mii status'):
                continue
            if line != 'mii status: up':
                return False
    return True


def wait_bond_up(bond, timeout=60):
    # Wait for bonding to be UP
    deadline = time.time() + timeout
    while time.time() < deadline:
        if get_bond_status(bond):
            # Wait for 30 seconds (maximum time for LLDP negotiation)
            time.sleep(30)
            return True
        else:
            time.sleep(5)
    return False


def read_net_interfaces():
    def read_iface(ifname, file_name):
        path = os.path.join('/sys/class/net/', ifname, file_name)
        with open(path) as fd:
            return fd.read().strip()

    def iface2iface(ifname):
        return dict(name=ifname,
                    mac=str(netaddr.eui.EUI(read_iface(ifname, 'address'))),
                    state=read_iface(ifname, 'operstate'))

    ifaces = os.listdir('/sys/class/net/')
    return [iface2iface(iface) for iface in ifaces if iface != 'lo']


def build_network(_server):
    network = _server['meta']['network']
    sort_order = ['physical', 'symlink', 'bond', 'tagged']
    networks = sorted(network.items(),
                      key=lambda x: sort_order.index(x[1]['type']))

    for name, net in networks:
        if net['type'] == 'symlink':
            continue
        elif net['type'] == 'bond':
            sh.modprobe('bonding', 'mode=4', 'miimon=100',
                        'xmit_hash_policy=1')
            sh.ifconfig(name, 'up')
            for iface in net['interfaces']:
                sh.ifenslave(name, iface)
        elif net['type'] == 'tagged':
            iface = net['interfaces'][0]
            sh.vconfig('add', iface, net['vlan'])
            sh.ifconfig(name, 'up')
        # Assign ip if required
        if net.get('ip'):
            ip = netaddr.IPNetwork('/'.join((net['ip'], net['mask'])))
            sh.ip('addr', 'add', str(ip),
                  'brd', str(ip.broadcast), 'dev', name)


def ensure_network(_server):
    networks = dict((k, v) for k, v in _server['meta']['network'].items()
                    if 'ip' in v)
    for name, net in networks.items():
        if_name = name if net['type'] != 'symlink' else net['interfaces'][0]
        cmd = '-I {0} -c 3 {1}'.format(if_name, net['gw'])
        try:
            sh.ping(cmd.split())
        except sh.ErrorReturnCode as exc:
            send_error(exc.message)


def hw_verify(_server):
    hw_info = dict()

    hw_info['unit'] = '2u'

    memory = get_mem_gb()
    hw_info['ram'] = memory

    cpu_local = get_cpu_local()
    hw_info['cpu'] = cpu_local

    hw_info['interfaces'] = read_net_interfaces()
    build_network(_server)

    if not wait_bond_up('bond0', 3*60):
        send_error("Timeout waiting for bond0 to up.")

    ensure_network(_server)

    hdd_local = get_hdds_local(_server)
    hw_info['disks'] = hdd2itop(hdd_local)

    return hw_info


def main(server_dict):
    global RESULT
    print 'After get info:', time.ctime()
    hw_info = hw_verify(server_dict)
    print 'After verify:', time.ctime()
    RESULT = hw_info

if __name__ == '__main__':
    global server
    main(server)
