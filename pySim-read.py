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
#from pySim.ts_51_011 import EF, DF

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
        def __init__(self, name, tp ="transparent"):
                self.name = name
                self.fci = None
                self.tp = tp #transparent, linear, cyclic 
                self.data = None
                
        def __repr__(self):
                return "\nName: {}\n Type: {} \n FCI: {} \n Data: {}\n".format(self.name, self.tp, self.fci, self.data)
        
        def set_fci(self, fci):
                self.fci = fci
                
        def set_data(self, data):
                self.data = data

        def set_type(self, tp):
                assert(tp == "transparent" or tp =="linear" or tp =="cyclic")
                self.tp = tp

                
def lsdf(dir):
        adf_dir = []
        error_adf = []
        for adf_ef in dir:
                print("***********************************************************************")
                adf_ef = EF(adf_ef)
                print(adf_ef.name)
                #scc.send_apdu(ins = 'a4',p1 = '04', p2 = '04', data = parent)
                (fci, sw), parsed = scc.send_apdu(ins = 'a4',p1 = '00', p2 = '04', data = adf_ef.name)
                adf_ef.set_fci(fci)

                if sw == '6a82':
                        continue

                elif sw == '9000':
                        #transparent 
                        if '82' in parsed.keys() and parsed['82'].startswith('41'): 
                                (data, sw) = scc.send_apdu_without_length(ins = 'b0',p1 = '00', p2 = '00', data = parsed['80'][2:4])
                                assert(sw == '9000')
                                adf_ef.set_type('transparent')
                                adf_ef.set_data(data)

                        #linear
                        elif '82' in parsed.keys() and parsed['82'].startswith('42'):
                                record_list = []
                                num_rec = int(parsed['82'][8:], 16)
                                len_rec = parsed['82'][6:8]
                                for i in range(num_rec):
                                        i = i + 1
                                        (data ,sw) = scc.send_apdu_without_length(ins = 'b2',p1 = '%02x'%(i), p2 = '04', data = str(len_rec))
                                        record_list.append(data)

                                adf_ef.set_type('linear')
                                adf_ef.set_data(record_list)
                                assert(sw == '9000')


                        #cyclic 
                        elif '82' in parsed.keys() and parsed['82'].startswith('46'):
                                record_list = []
                                num_rec = int(parsed['82'][8:], 16)
                                len_rec = parsed['82'][6:8]
                                print(num_rec, len_rec)
                                for i in range(num_rec):
                                        i = i + 1
                                        (data ,sw) = scc.send_apdu_without_length(ins = 'b2',p1 = '%02x'%(i), p2 = '04', data = str(len_rec))
                                        record_list.append(data)
                                
                                assert(sw == '9000')
                                adf_ef.set_type('cyclic')
                                adf_ef.set_data(record_list)
                        else:
                                error_adf.append((adf_ef, sw))
                                continue
                        adf_dir.append(adf_ef)
                else:
                        error_adf.append((adf_ef, sw))
        return adf_dir, error_adf



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
	else: # Serial reader is default
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

        scc.send_apdu(ins = 'a4',p1 = '00', p2 = '04', data = '3F00')

        #mf
        mf_list = ['2F00', '2F05', '2F06', '2FE2', '2F08']
        
        mf_dir, error_mf = lsdf(mf_list)
        print(mf_dir)
        print(error_mf)

        
        #adf
        scc.send_apdu(ins = 'a4',p1 = '00', p2 = '04', data = '2F00')
        scc.send_apdu_without_length(ins = 'b2',p1 = '01', p2 = '04', data = '26')
        scc.send_apdu(ins = 'a4',p1 = '04', p2 = '04', data = 'a0000000871002ffffffff8907090000')
        #scc.send_apdu(ins = 'a4',p1 = '00', p2 = '04', data = '6F07')
        
        adf_list = ['6F05', '6F06','6F07','6F08','6F09','6F2C','6F31','6F32','6F37','6F38','6F39','6F3B','6F3C','6F3E','6F3F','6F40','6F41','6F42','6F43','6F45','6F46','6F47','6F48','6F49','6F4B','6F4C','6F4D','6F4E','6F4F','6F50','6F55','6F56','6F57','6F58','6F5B','6F5C','6F5C','6F60','6F61','6F62','6F73','6F78','6F7B','6F7E','6F80','6F81','6F82','6F83','6FAD','6FB1','6FB2','6FB3','6FB4','6FB5','6FB6','6FB7','6FC3','6FC4','6FC5','6FC6','6FC7','6FC8','6FC9','6FCA','6FCB','6FCC','6FCD','6FCE','6FCF','6FD0','6FD1','6FD2','6FD3','6FD4','6FD5','6FD6','6FD7','6FD8','6FD9','6FDA','6FDB',' 6FDC','6FDD','6FDE','6FDF','6FE2','6FE3','6FE4','6FE6','6FE7','6FE8','6FEC','6FED','6FEE','6FEF','6FF0','6FF1','6FF2','6FF3','6FF4']

        #adf_dir, error_adf = lsdf(dir)
        #print(adf_dir)
        #print(error_adf)
        
        scc.send_apdu(ins = 'a4',p1 = '00', p2 = '04', data = '3F00')
        scc.send_apdu(ins = 'a4',p1 = '00', p2 = '04', data = '7F20')
        gsm_list = ['6F05', '6F07', '6F20','6F2C','6F30','6F31','6F32','6F37','6F38','6F39','6F3E','6F3F','6F41','6F45','6F46','6F48','6F74','6F78','6F7B','6F7E','6FAD','6FAE','6FB1','6FB2','6FB3','6FB4','6FB5','6FB6','6FB7','6F50','6F51','6F52','6F53','6F54','6F60','6F61','6F62','6F63','6F64','6FC5','6FC6','6FC7','6FC8','6FC9','6FCA','6FCB','6FCC']
        #gsm_dir, error_gsm = lsdf(gsm_list)
        #print(gsm_dir)
        #print(error_gsm)
        
        
        
        
