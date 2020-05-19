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


def save_profile(mf="", adf="", gsm="", telecom=""):
    with open("mf.profile", 'w') as f:
        f.write(str(mf))
    with open("adf.profile", 'w') as f:
        f.write(str(adf))
    with open("gsm.profile", 'w') as f:
        f.write(str(gsm))
    with open("telecom.profile", 'w') as f:
        f.write(str(telecom))


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
    # Read Trace
    # ret = scc._tp.send_apdu('0099000000')
    # print (ret)
    # ret = scc._tp.send_apdu('0098000000')
    # print (ret)

    # ret = scc._tp.send_apdu('00a40004022F00')
    # print (ret)

    # ret = scc._tp.send_apdu('00a404000b0102030405060708090102')
    # print (ret)

    # # reset history bytes 0092
    # ret = scc._tp.send_apdu('0092000000')
    # print (ret)

    # ret = scc._tp.send_apdu('00CB004200')
    # print (ret)

    # ret = scc._tp.send_apdu('00a40004023F00')
    # print (ret)
    # switch profile
    ret = scc._tp.send_apdu('00a9030000')
    print (ret)
    # delete profile
    # ret = scc._tp.send_apdu('00a6020000')
    # print (ret)
    # install profile
    # ret = scc._tp.send_apdu('00a70000290829430191348767650644092A26DCEBA00503CF739EC097EEC8D74B739DAB27C6CEAB9BA5C98B7D67')
    # print (ret)

    # print(scc._tp.send_apdu('00a8000000')) # check sim status
    # # -------------------------check IMSI-------------------------------
    # print(scc._tp.send_apdu('00a40000026F07'))
    # print(scc._tp.send_apdu('00b0000009'))
    # # -------------------------check SIM Service Table-------------------------------
    # print(scc._tp.send_apdu('00a40004027F20'))
    # # print(scc._tp.send_apdu('00b0000009'))
    # print(scc._tp.send_apdu('00a40004026F38'))
    # print(scc._tp.send_apdu('00b000000a'))
    # print(scc._tp.send_apdu('0098000000'))
    # # -------------------------Send Terminal Profile-------------------------------
    # print(scc._tp.send_apdu('8010000014FFFFFFFF1F0000DFD7030A000000000600000000'))
    # # -------------------------Fetch cmd-------------------------------
    # print(scc._tp.send_apdu('8012000028'))
    # # -------------------------terminal response-------------------------------
    # print(scc._tp.send_apdu('801400000C810301250002028281030100'))
    # # # -------------------------Send Terminal Profile-------------------------------
    # print(scc._tp.send_apdu('8011040000'))
    # print(scc._tp.send_apdu('801200000b'))

    # print(scc._tp.send_apdu('0099000000'))
    # print(scc._tp.send_apdu('0098000000'))


    # ret = scc._tp.send_apdu('00A5000000')
    # print (ret)
    # ret = scc._tp.send_apdu('80CAFF2100')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40400080102030405060708')
    #
    # print (ret)

    # -----------------------Read ATT SIM card---------------------------------------
    # ret = scc._tp.send_apdu('00a40004023F00')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004022F00')
    # print (ret)
    # ret = scc._tp.send_apdu('00b2010426')
    # print (ret)
    # ret = scc._tp.send_apdu('00b2020426')
    # print (ret)
    # ret = scc._tp.send_apdu('00b2030426')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004027FF0')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004026FC4') # Network Parameter
    # print (ret)
    # ret = scc._tp.send_apdu('00b00000da')
    # print (ret)


    # ret = scc._tp.send_apdu('00A904000100')
    # print (ret)
    # ret = scc._tp.send_apdu('00990400023F00')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40800023F00')
    # print (ret)
    # ret = scc._tp.send_apdu('84E20801083F00')
    # print (ret)

    # Switch Profile
    # ret = scc._tp.send_apdu('00A9020000')
    # print (ret)
    # ret = scc._tp.send_apdu('00A8000000')
    # print (ret)


    # ret = scc._tp.send_apdu('00a40004022F00')
    # print (ret)
    # ret = scc._tp.send_apdu('00b2010426')
    # print (ret)
    # print("--------------------------------Select ADF-----------------------------------")
    # ret = scc._tp.send_apdu('00a4040410a0000000871002ffffffff8907090000')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40804047fff6f73')
    # print (ret)
    # ret = scc._tp.send_apdu('00b000000e')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40804047fff6f07')
    # print (ret)
    # ret = scc._tp.send_apdu('00b0000009')
    # print (ret)
    # ret = scc._tp.send_apdu('00a404000ba000000308000010000100')
    # print (ret)

    # ret = scc._tp.send_apdu('00a40804047fff6f7b')
    # print (ret)
    # ret = scc._tp.send_apdu('00b000000c')
    # print (ret)



    # print("--------------------------------Get Kc-----------------------------------")
    # ret = scc._tp.send_apdu('00a40804047F206F20')
    # print (ret)
    # ret = scc._tp.send_apdu('00b0000009')
    # print (ret)

    # print("--------------------------------Verify the ADM-----------------------------------")
    # ret = scc._tp.send_apdu('0020000a083937363734373630')
    # print (ret)
    # ret = scc._tp.send_apdu('0020000a')
    # print (ret)
    # print("--------------------------------Get the KI-----------------------------------")
    # ret = scc._tp.send_apdu('00a40004027F20')
    # print (ret)
    # ret = scc._tp.send_apdu('00a400040200FF')
    # print (ret)
    # ret = scc._tp.send_apdu('00b0000010')
    # print (ret)
    # print("--------------------------------Get the OPc-----------------------------------")
    # ret = scc._tp.send_apdu('00a400040200F7')
    # print (ret)
    # ret = scc._tp.send_apdu('00b0000011')
    # print (ret)

    # print("--------------------------------Get the Algorithm-----------------------------------")
    # ret = scc._tp.send_apdu('00a40004023F00')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004027FCC')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004026F00')
    # print (ret)
    # ret = scc._tp.send_apdu('00b0000002')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004026F01')
    # print (ret)
    # ret = scc._tp.send_apdu('00b0000055')
    # print (ret)

    # ret = scc._tp.send_apdu('00b000000111')
    # print (ret)


    # Auth
    # ret = scc._tp.send_apdu('00a4040410a0000000871002ffffffff8907090000')
    # print (ret)
    # ret = scc._tp.send_apdu('008800812210000102030405060708090a0b0c0d0e0f1087f13e021abf00006c02a47ff765dd84')
    # print (ret)
    # ret = scc._tp.send_apdu('00c0000035')
    # print (ret)


    # # CREATE GSM
    # ret = scc._tp.send_apdu('00e000003262308202782183027f20a51683027fffcb0d00000000000000000000000000ca01828a01058b032f0601c606900100830101')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004027F20')
    # print (ret)

    # # CREATE GSM IMSI
    # ret = scc._tp.send_apdu('00e000002462228202412183026f07a50ac00100cd02ff01ca01848a01058b036f0603800200098800')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40000026F07')
    # print (ret)
    # ret = scc._tp.send_apdu('00b000000a')
    # print (ret)
    #
    # ret = scc._tp.send_apdu('00a40004023F00')
    # print (ret)
    # # Create ADF
    # ret = scc._tp.send_apdu('00e000005962578202782183027fff8410a0000000871002ffffffff8907090000a51683027fffcb0d00000000000000000000000000ca01808a0105ab15800101a40683010a95010880014097008001069000c609900140830101830181')
    # print (ret)
    # ret = scc._tp.send_apdu('00a4040410a0000000871002ffffffff8907090000')
    # print (ret)


    # # # Create ADF 6FAD
    # ret = scc._tp.send_apdu('00e000002962278202412183026fada50ec001009b063f007f206fadca01808a01058b036f060680020004880118')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40804047F206FAD')
    # print (ret)
    # ret = scc._tp.send_apdu('00b0000004')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40804047FFF6FAD')
    # print (ret)
    # ret = scc._tp.send_apdu('00b0000004')
    # print (ret)
    # ret = scc._tp.send_apdu('00e40000026FAD')
    # print (ret)

    # Start Record
    # ret = scc._tp.send_apdu('0097000000')
    # print (ret)
    # ret = scc._tp.send_apdu('0098000000')
    # print (ret)
    # ret = scc._tp.send_apdu('0099000000')
    # print (ret)


    # # # Create ADF IMSI
    # ret = scc._tp.send_apdu('00e000002962278202412183026f07a50ec001009b063f007f206f07ca01808a01058b036f060380020009880138')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40000026F07')
    # print (ret)
    # ret = scc._tp.send_apdu('00b000000a')
    # print (ret)

    # ret = scc._tp.send_apdu('00a40004026F07')
    # print (ret)

    # ret = scc._tp.send_apdu('00a40804047FFF6F07')
    # print (ret)
    #
    # ret = scc._tp.send_apdu('00a40804047F206F07')
    # print (ret)
    # CREATE GSM IMSI
    # ret = scc._tp.send_apdu('00e000002462228202412183026f07a50ac00100cd02ff01ca01848a01058b036f0603800200098800')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40000026F07')
    # print (ret)
    # ret = scc._tp.send_apdu('00b000000a')
    # print (ret)
    #
    # ret = scc._tp.send_apdu('00a40000023F00')
    # print (ret)

    # CREATE GSM
    # ret = scc._tp.send_apdu('00e000003262308202782183027f20a51683027fffcb0d00000000000000000000000000ca01828a01058b032f0601c606900100830101')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004027F20')
    # print (ret)

    # Create ADF
    # ret = scc._tp.send_apdu('00e000005962578202782183027fff8410a0000000871002ffffffff8907090000a51683027fffcb0d00000000000000000000000000ca01808a0105ab15800101a40683010a95010880014097008001069000c609900140830101830181')
    # print (ret)
    # ret = scc._tp.send_apdu('00a4040410a0000000871002ffffffff8907090000')
    # print (ret)

    # # Create ADF IMSI
    # ret = scc._tp.send_apdu('00e000002962278202412183026f07a50ec001009b063f007f206f07ca01808a01058b036f060380020009880138')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40000026F07')
    # print (ret)
    # ret = scc._tp.send_apdu('00b000000a')
    # print (ret)

    # ret = scc._tp.send_apdu('00a40004026F07')
    # print (ret)
    # ret = scc._tp.send_apdu('00e40000026F07')
    # print (ret)


    # scc.send_apdu(ins='a4', p1='00', p2='04', data="3F00")
    # ret = scc._tp.send_apdu('00a40004026F05')
    # print (ret)
    # ret = scc._tp.send_apdu('00b2010426')
    # print (ret)

    # Create ADF
    # ret = scc._tp.send_apdu('00e000005962578202782183027fff8410a0000000871002ffffffff8907090000a51683027fffcb0d00000000000000000000000000ca01808a0105ab15800101a40683010a95010880014097008001069000c609900140830101830181')
    # print (ret)
    # ret = scc._tp.send_apdu('00a4040410a0000000871002ffffffff8907090000')
    # print (ret)

    # CREATE GSM
    # ret = scc._tp.send_apdu('00e000003262308202782183027f20a51683027fffcb0d00000000000000000000000000ca01828a01058b032f0601c606900100830101')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004027F20')
    # print (ret)

    # ret = scc._tp.send_apdu('00e0000024622282054221006e0c83026f06a506c00100ca01808a01058b036f0606800205288801b8')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40000026F06')
    # print (ret)
    # ret = scc._tp.send_apdu('00b2010426')
    # print (ret)

    # # ADF IMSI
    # ret = scc._tp.send_apdu('00e000002962278202412183026f07a50ec001009b063f007f206f07ca01808a01058b036f060380020009880138')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40000026F07')
    # print (ret)
    # ret = scc._tp.send_apdu('00b000000a')
    # print (ret)

    # GSM IMSI
    # ret = scc._tp.send_apdu('00e000002462228202412183026f07a50ac00100cd02ff01ca01848a01058b036f0603800200098800')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40000026F07')
    # print (ret)
    # ret = scc._tp.send_apdu('00b000000a')
    # print (ret)




    # ret = scc._tp.send_apdu('00e000002462228205422100260283022f00a506c00100ca01808a01058b032f06048002004c8801f0')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40000022F00')
    # print (ret)
    # ret = scc._tp.send_apdu('00b2010426')
    # print (ret)
    #
    #
    # ret = scc._tp.send_apdu('00e00002962278202412183026f07a50ec001009b063f007f206f07ca01808a01058b036f060380020009880138')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004026F07')
    # print (ret)
    # ret = scc._tp.send_apdu('00b0000009')
    # print (ret)

    # ret = scc._tp.send_apdu('00b2010426')
    # print (ret)

    # R&S ADF: a0000000871002ff86ff0a89ffffffff
    # ret = scc._tp.send_apdu('00a4040410a0000000871002ff86ff0a89ffffffff')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004027FF0')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004023F00')
    # print (ret)
    # # sysmocom ADF: a0000000871002ffffffff8907090000
    # ret = scc._tp.send_apdu('00a4040410a0000000871002ffffffff8907090000')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004022F00')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004023F00')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004022F00')
    # print (ret)


    # ret = scc._tp.send_apdu('00e00000096f0782013883023f00')
    # print (ret)


    # # Create EF_DIR 2F00
    # ret = scc._tp.send_apdu('00e000002462228205422100260283022f00a506c00100ca01808a01058b032f06048002004c8801f0')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004022F00')
    # print (ret)
    # ret = scc._tp.send_apdu('00b2010426')
    # print (ret)

    # scc.send_apdu(ins='e4', p1='00', p2='00', data="2FE2")
    # scc.send_apdu(ins='e0', p1='00', p2='00', data="621c8202412183022fe2a506c00100ca01808a01058b032f06048002000a")

    # Create 2FE2
    # ret = scc._tp.send_apdu('00a40004022FE2')
    # print (ret)
    # # scc.send_apdu(ins='e4', p1='00', p2='00', data="2FE2")
    # scc.send_apdu(ins='e0', p1='00', p2='00', data="621c8202412183022fe2a506c00100ca01808a01058b032f06048002000a")



    # # create EF 6F07
    # ret = scc._tp.send_apdu(
    #     '00e000002962278202412183026f07a50ec001009b063f007f206f07ca01808a01058b036f060380020009880138')
    # print (ret)
    # ret = scc._tp.send_apdu('00a40004026F07')
    # print (ret)
    #update 6F07 binary
    # ret = scc._tp.send_apdu('00d6000009089910070000200493')
    # print (ret)
    # scc.send_apdu(ins='D6', p1='00', p2='00', data="089910070000200493")
    # scc.send_apdu_without_length(ins='b0', p1='00', p2='00', data='09')



    # scc.send_apdu(ins='e0', p1='00', p2='00',data="62278202412183026f028a01058b036f060380020009")
    # scc.send_apdu(ins='e0', p1='00', p2='00',data="62308202782183027f20a51683027fffcb0d00000000000000000000000000ca01828a01058b032f0601c606900100830101")
    # for ef in gsm:
    #        write_EF(ef, '7F20')

    # scc.send_apdu(ins='e0', p1='00', p2='00',data='62308202782183027f10a51683027fffcb0d00000000000000000000000000ca01828a01058b032f0601c606900100830101')

    # ret = scc._tp.send_apdu('00e000001662278202412183026f028a01058b036f060380020009')




    # scc.send_apdu(ins='a4', p1='00', p2='04', data='3F00')
    # scc.send_apdu(ins='a4', p1='00', p2='04', data='2F00')
    # scc.send_apdu_without_length(ins='b2', p1='01', p2='04', data='26')
    # scc.send_apdu_without_length(ins='b2', p1='02', p2='04', data='26')
    # scc.send_apdu_without_length(ins='b2', p1='03', p2='04', data='26')
    # scc.send_apdu_without_length(ins='b2', p1='04', p2='04', data='26')
    # scc.send_apdu(ins='a4', p1='04', p2='04', data='a0000000871002ffffffff8907090000')
    # scc.send_apdu(ins='a4', p1='04', p2='04', data='0102030405060708090102')
    # scc.send_apdu(ins='e0', p1='00', p2='00', data='62228205422100260283022f00a506c00100ca01808a01058b032f06048002004c8801f0')
    # scc.send_apdu(ins='a4', p1='00', p2='04', data='7F20')
    # scc.send_apdu(ins='a4', p1='00', p2='04', data='6F07')
    # scc.send_apdu_without_length(ins='b0', p1='00', p2='00', data='09')
    # scc.send_apdu(ins='a4', p1='00', p2='04', data='6F08')

    # ret = scc._tp.send_apdu('00e000002662278202412183026f028a01058b036f060380020009')
    # ret = scc._tp.send_apdu('00e000002462228205422100260283022f00a506c00100ca01808a01058b032f06048002004c8801f0')
    # print (ret)

    # scc.send_apdu_without_length(ins='b0', p1='00', p2='00', data='09')
    # scc.send_apdu(ins='a4', p1='00', p2='04', data='6F02')
    # scc.send_apdu(ins='20', p1='00', p2='01', data='')
    # scc.send_apdu(ins='20', p1='00', p2='01', data='33303634ffffffff')
    # scc.send_apdu(ins='a4', p1='00', p2='04', data='7FF1')
    # scc.send_apdu_without_length(ins='b0', p1='00', p2='00', data='09')
    # scc.send_apdu(ins='e4', p1='00', p2='00', data='6F02')
    # scc.send_apdu(ins='e0', p1='00', p2='00', data='62278202412183027ff18a01058b036f060380020009')
    # scc.send_apdu(ins='a4', p1='00', p2='04', data='7ff1')

    # scc.send_apdu_without_length(ins='b0', p1='00', p2='00', data='09')

    # #mf
    # mf_list = ['2F00', '2F05', '2F06', '2FE2', '2F08']
    #
    # mf_dir, error_mf = lsdf(mf_list)
    # print(mf_dir)
    # print(error_mf)

    # adf
    # scc.send_apdu(ins = 'a4',p1 = '00', p2 = '04', data = '2F00')
    # scc.send_apdu_without_length(ins = 'b2',p1 = '01', p2 = '04', data = '26')
    # scc.send_apdu(ins = 'a4',p1 = '04', p2 = '04', data = 'a0000000871002ffffffff8907090000')
    # #scc.send_apdu(ins = 'a4',p1 = '00', p2 = '04', data = '6F07')
    #
    # adf_list = ['6F05', '6F06', '6F07', '6F08', '6F09', '6F2C', '6F31', '6F32', '6F37', '6F38', '6F39', '6F3B', '6F3C',
    #             '6F3E', '6F3F', '6F40', '6F41', '6F42', '6F43', '6F45', '6F46', '6F47', '6F48', '6F49', '6F4B', '6F4C',
    #             '6F4D', '6F4E', '6F4F', '6F50', '6F55', '6F56', '6F57', '6F58', '6F5B', '6F5C', '6F5C', '6F60', '6F61',
    #             '6F62', '6F73', '6F78', '6F7B', '6F7E', '6F80', '6F81', '6F82', '6F83', '6FAD', '6FB1', '6FB2', '6FB3',
    #             '6FB4', '6FB5', '6FB6', '6FB7', '6FC3', '6FC4', '6FC5', '6FC6', '6FC7', '6FC8', '6FC9', '6FCA', '6FCB',
    #             '6FCC', '6FCD', '6FCE', '6FCF', '6FD0', '6FD1', '6FD2', '6FD3', '6FD4', '6FD5', '6FD6', '6FD7', '6FD8',
    #             '6FD9', '6FDA', '6FDB', '6FDC', '6FDD', '6FDE', '6FDF', '6FE2', '6FE3', '6FE4', '6FE6', '6FE7', '6FE8',
    #             '6FEC', '6FED', '6FEE', '6FEF', '6FF0', '6FF1', '6FF2', '6FF3', '6FF4']
    # #
    # adf_dir, error_adf = lsdf(adf_list)
    # print(adf_dir)
    # print(error_adf)
    #
    # scc.send_apdu(ins = 'a4',p1 = '00', p2 = '04', data = '3F00')
    # scc.send_apdu(ins = 'a4',p1 = '00', p2 = '04', data = '7F20')
    # gsm_list = ['6F05', '6F07', '6F20','6F2C','6F30','6F31','6F32','6F37','6F38','6F39','6F3E','6F3F','6F41','6F45','6F46','6F48','6F74','6F78','6F7B','6F7E','6FAD','6FAE','6FB1','6FB2','6FB3','6FB4','6FB5','6FB6','6FB7','6F50','6F51','6F52','6F53','6F54','6F60','6F61','6F62','6F63','6F64','6FC5','6FC6','6FC7','6FC8','6FC9','6FCA','6FCB','6FCC']
    # gsm_dir, error_gsm = lsdf(gsm_list)
    # #print(gsm_dir)
    # #print(error_gsm)
    #
    # scc.send_apdu(ins = 'a4',p1 = '00', p2 = '04', data = '3F00')
    # scc.send_apdu(ins = 'a4',p1 = '00', p2 = '04', data = '7F10')
    # telecom_list = ['6F06', '6F3A', '6F3B', '6F3C', '6F40', '6F42', '6F43', '6F44', '6F47', '6F49', '6F4A', '6F4B', '6F4C', '6F4D', '6F4E', '6F4F', '6F53', '6F54', '6FE0', '6FE1', '6FE5']
    # telecom_dir, error_telecom = lsdf(telecom_list)
    #
    # print(error_mf, error_adf, error_gsm, error_telecom)
    # save_profile(mf_dir, adf_dir, gsm_dir, telecom_dir)
