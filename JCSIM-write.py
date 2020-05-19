#!/usr/bin/env python2

#
# Utility to display some informations about a SIM card
#
#
# Copyright (C) 2009  Sylvain Munaut <tnt@246tNt.com>
# Copyright (C) 2010  Harald Welte <laforge@gnumonks.org>
# Copyright (C) 2013  Alexander Chemeris <alexander.chemeris@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import hashlib
from optparse import OptionParser
import os
import random
import re
import sys
# from pySim.ts_51_011 import EF, DF
import json

try:
    import json
except ImportError:
    # Python < 2.5
    import simplejson as json

from pySim.commands import SimCardCommands
from pySim.utils import h2b, swap_nibbles, rpad, dec_imsi, dec_iccid, format_xplmn_w_act


def parse_options():
    parser = OptionParser(usage="usage: %prog [options]")

    parser.add_option("-d", "--device", dest="device", metavar="DEV",
                      help="Serial Device for SIM access [default: %default]",
                      default="/dev/ttyUSB0",
                      )
    parser.add_option("-b", "--baud", dest="baudrate", type="int", metavar="BAUD",
                      help="Baudrate used for SIM access [default: %default]",
                      default=9600,
                      )
    parser.add_option("-p", "--pcsc-device", dest="pcsc_dev", type='int', metavar="PCSC",
                      help="Which PC/SC reader number for SIM access",
                      default=None,
                      )
    parser.add_option("--osmocon", dest="osmocon_sock", metavar="PATH",
                      help="Socket path for Calypso (e.g. Motorola C1XX) based reader (via OsmocomBB)",
                      default=None,
                      )

    (options, args) = parser.parse_args()

    if args:
        parser.error("Extraneous arguments")

    return options


class EF:
    def __init__(self, name, tp="transparent"):
        self.name = name
        self.fci = None
        self.tp = tp  # transparent, linear, cyclic
        self.data = None
        self.adpu = None

    def __repr__(self):
        return "\nName: {}\n Type: {} \n FCI: {} \n Data: {}\n".format(self.name, self.tp, self.fci, self.data)

    def set_fci(self, fci):
        self.fci = fci

    def set_data(self, data):
        self.data = data

    def set_type(self, tp):
        assert (tp == "transparent" or tp == "linear" or tp == "cyclic")
        self.tp = tp

    def set_apdu(self, apdu):
        self.apdu = apdu


def lsdf(dir):
    adf_dir = []
    error_adf = []
    for adf_ef in dir:
        print("***********************************************************************")
        adf_ef = EF(adf_ef)
        print(adf_ef.name)
        # scc.send_apdu(ins = 'a4',p1 = '04', p2 = '04', data = parent)
        (fci, sw), parsed = scc.send_apdu(ins='a4', p1='00', p2='04', data=adf_ef.name)
        adf_ef.set_fci(fci)

        if sw == '6a82':
            continue
        elif sw == '6982':
            print("Access Rule Encountered")
            continue
            # scc.verify_chv()
        elif sw == '9000':
            # transparent
            if '82' in parsed.keys() and parsed['82'].startswith('41'):
                (data, sw) = scc.send_apdu_without_length(ins='b0', p1='00', p2='00', data=parsed['80'][2:4])
                if sw == '6982':
                    print("Access Rule Encountered")
                    continue
                assert (sw == '9000')
                adf_ef.set_type('transparent')
                adf_ef.set_data(data)

            # linear
            elif '82' in parsed.keys() and parsed['82'].startswith('42'):
                record_list = []
                num_rec = int(parsed['82'][8:], 16)
                len_rec = parsed['82'][6:8]
                for i in range(num_rec):
                    i = i + 1
                    (data, sw) = scc.send_apdu_without_length(ins='b2', p1='%02x' % (i), p2='04', data=str(len_rec))
                    record_list.append(data)

                adf_ef.set_type('linear')
                adf_ef.set_data(record_list)
                assert (sw == '9000')


            # cyclic
            elif '82' in parsed.keys() and parsed['82'].startswith('46'):
                record_list = []
                num_rec = int(parsed['82'][8:], 16)
                len_rec = parsed['82'][6:8]
                print(num_rec, len_rec)
                for i in range(num_rec):
                    i = i + 1
                    (data, sw) = scc.send_apdu_without_length(ins='b2', p1='%02x' % (i), p2='04', data=str(len_rec))
                    record_list.append(data)

                assert (sw == '9000')
                adf_ef.set_type('cyclic')
                adf_ef.set_data(record_list)
            else:
                error_adf.append((adf_ef, sw))
                continue
            adf_dir.append(adf_ef)
        else:
            error_adf.append((adf_ef, sw))
    return adf_dir, error_adf


def save_profile(mf="", adf="", gsm="", telecom="", folder="./profile/"):
    import pickle
    with open(folder + "mf.profile", "wb") as f:
        pickle.dump(mf, f)
    with open(folder + "mf.txt", 'w') as f:
        f.write(str(mf))

    with open(folder + "adf.profile", "wb") as f:
        pickle.dump(adf, f)
    with open(folder + "adf.txt", 'w') as f:
        f.write(str(adf))

    with open(folder + "gsm.profile", "wb") as f:
        pickle.dump(gsm, f)
    with open(folder + "gsm.txt", 'w') as f:
        f.write(str(gsm))

    with open(folder + "telecom.profile", "wb") as f:
        pickle.dump(telecom, f)
    with open(folder + "telecom.txt", 'w') as f:
        f.write(str(telecom))


def load_profile_single(s):
    # print(s)
    l = [k.strip("]").strip(":").strip().split("\n") for k in s.split("Name")[1:]]
    ret = []
    for record in l:
        ef = EF(record[0])
        ef.tp = record[1].strip().strip("Type").strip(":").strip()
        ef.fci = record[2].strip().strip("FCI").strip(":").strip()
        st = record[3].strip().strip("Data").strip(":").strip()
        print(st)
        if ef.tp == "transparent":
            ef.data = st
        else:
            ef.data = [subst.strip().strip("'") for subst in st.strip('][').split(',')]
        ret.append(ef)
    return ret


def load_profile(folder="./profile/"):
    with open(folder + "mf.txt", "r") as f:
        mf = load_profile_single(f.read())

    with open(folder + "adf.txt", "r") as f:
        adf = load_profile_single(f.read())

    with open(folder + "gsm.txt", "r") as f:
        gsm = load_profile_single(f.read())

    with open(folder + "telecom.txt", "r") as f:
        telecom = load_profile_single(f.read())

    return mf, adf, gsm, telecom


if __name__ == '__main__':

    # Parse options
    opts = parse_options()

    # Init card reader driver
    if opts.pcsc_dev is not None:
        print("Using PC/SC reader (dev=%d) interface"
              % opts.pcsc_dev)
        from pySim.transport.pcsc import PcscSimLink

        sl = PcscSimLink(opts.pcsc_dev)
    elif opts.osmocon_sock is not None:
        print("Using Calypso-based (OsmocomBB, sock=%s) reader interface"
              % opts.osmocon_sock)
        from pySim.transport.calypso import CalypsoSimLink

        sl = CalypsoSimLink(sock_path=opts.osmocon_sock)
    else:  # Serial reader is default
        print("Using serial reader (port=%s, baudrate=%d) interface"
              % (opts.device, opts.baudrate))
        from pySim.transport.serial import SerialSimLink

        sl = SerialSimLink(device=opts.device, baudrate=opts.baudrate)

    # Create command layer
    scc = SimCardCommands(transport=sl)

    # Wait for SIM card
    sl.wait_for_card()

    # Program the card
    print("Reading ...")

    print(scc._tp.send_apdu('00a404000b0102030405060708090102'))
    scc.send_apdu(ins='a4', p1='00', p2='00', data='3F00')


    def write_EF(ef, parent):
        print("===============")
        print(ef)
        # scc.send_apdu(ins = 'a4',p1 = '00', p2 = '00', data = '3F00')
        # scc.send_apdu(ins = 'a4',p1 = '00', p2 = '00', data = parent)
        scc.send_apdu(ins='e0', p1='00', p2='00', data=ef.fci)
        scc.send_apdu(ins='a4', p1='00', p2='00', data=ef.name)
        if ef.tp == "transparent":
            scc.send_apdu(ins='d6', p1='00', p2='00', data=ef.data)
            scc.send_apdu(ins='a4', p1='00', p2='00', data=ef.name)
            sw, data = scc.send_apdu_without_length(ins='b0', p1='00', p2='00', data='0a')
            print(sw, data)
        if ef.tp == "linear":
            records = ef.data
            item = 1
            for record in records:
                if set(record) == set("f"):
                    continue

                print(item)
                sw, data = scc.send_apdu(ins='dc', p1='%02x' % (item), p2='04', data=record)
                sw, data = scc.send_apdu_without_length(ins='b2', p1='%02x' % (item), p2='04', data=str(26))

                item += 1


    mf, adf, gsm, telecom = load_profile()
    # print(mf)

    # master file
    for ef in mf:
        write_EF(ef, '3F00')

    scc.send_apdu(ins='a4', p1='00', p2='00', data='3F00')
    scc.send_apdu(ins='e0', p1='00', p2='00',
                  data="62308202782183027f20a51683027fffcb0d00000000000000000000000000ca01828a01058b032f0601c606900100830101")
    for ef in gsm:
        write_EF(ef, '7F20')

    scc.send_apdu(ins='a4', p1='00', p2='00', data='3F00')
    scc.send_apdu(ins='e0', p1='00', p2='00',
                  data='62308202782183027f10a51683027fffcb0d00000000000000000000000000ca01828a01058b032f0601c606900100830101')
    for ef in telecom:
        write_EF(ef, '7F10')

    scc.send_apdu(ins='a4', p1='00', p2='00', data='3F00')
    scc._tp.send_apdu(
        '00e000005962578202782183027fff8410a0000000871002ffffffff8907090000a51683027fffcb0d00000000000000000000000000ca01808a0105ab15800101a40683010a95010880014097008001069000c609900140830101830181')
    # scc.send_apdu(ins='e0', p1='00', p2='00', data= '62308202782183027fffa51683027fffcb0d00000000000000000000000000ca01828a01058b032f0601c606900100830101')
    for ef in adf:
        write_EF(ef, '7FFF')
