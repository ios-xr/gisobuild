# -----------------------------------------------------------------------------

""" API towards loading and assembling compatibility matrix info.

Copyright (c) 2022 Cisco and/or its affiliates.
This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at

        https://developer.cisco.com/docs/licenses

All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.

"""

import argparse
import os
import logging
import glob
import json
from collections import OrderedDict
import re
try:
    import exrmod.exrutils.rpmutils as rpmutils
except ImportError:
    import sys
    sys.path.append (os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
    import exrutils.rpmutils as rpmutils

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

class Matrix:

    def __init__ (self, jsonfile, platform):
        self.jsonfile = jsonfile
        self.platform = platform
        self.isorel = None
        self.matrix = self.load_matrix ()
        return

    def load_matrix (self):
        jsonfile = self.jsonfile
        plat = self.platform
        jumbo_matrix = OrderedDict()   # Return the platform specific matrix info.
        datadict = {}    # Dictionary loaded from json file
        reldata = []
        if not os.path.isfile (jsonfile):
            raise AssertionError ("matrix file {} does not exist".format(jsonfile))
        
        with open (jsonfile, 'r') as fp:
            datadict = json.load (fp, object_pairs_hook=OrderedDict)

        if not datadict:
            raise AssertionError ("Unable to load data from {}".format(jsonfile))

        m = re.search (r'.*compatibility_matrix_(.*).json', jsonfile)
        if not m:
            raise AssertionError ("Matrix file name do not match supported naming format.")

        self.isorel = m.groups()[0]
        ''' Filter platform sepcific matrix. '''
        if self.isorel != datadict['release']:
            raise AssertionError ("Matrix file release {} do not match "
                                  "iso release {}".format (datadict['release'], self.isorel))

        for rel_v1, v1_info in datadict['permitted'].items():
            if rel_v1 == self.isorel:
                continue
            for rel_v2, v2_info in v1_info.items():
                if rel_v2 != self.isorel:
                    raise AssertionError ("Matrix file {} has invalid data under "
                                          "permitted for V2 as {}.".format(
                                          jsonfile, rel_v2))
                for iterdata in v2_info:
                    if iterdata.get('platform') == plat:
                        reldata = iterdata.get('bridge_smus')
                        if 'bridge_prereqs' in iterdata.keys():
                            reldata.extend (iterdata.get('bridge_prereqs'))
                        jumbo_matrix["r{}".format (''.join(rel_v1.split('.')))] = reldata

        return jumbo_matrix

    def data_release (self, rel):
        matrix = self.matrix
        reldata = {}

        for relnum in matrix.keys():
            if relnum in rel:
                reldata[rel] = matrix.get (relnum)

        if not reldata:
            print ("Release {} does not support upgrade to input iso "
                         "release {}.".format (rel.replace('r', ''),
                         ''.join(self.isorel.split('.'))))
        
        return reldata

    def data_release_all (self):
        matrix = self.matrix
        reldata = {}
        for rel in matrix.keys():
            reldata[rel] = self.data_release(rel)
        
        return reldata

    def validate_input_pkgs (self, release, pkglist):
        reldata = self.data_release (release)
        pkgs2consider = []

        if not reldata:
            return [], pkglist

        rel, bridgelist = reldata.popitem()
        if not bridgelist:
            print ("No bridge SMU data available for {}".format (
                                                rel.replace('r', '')))
            return []
        else:
            print ("Release {} bridge SMUs: {}".format (
                                                rel.replace('r', ''), 
                                                bridgelist))

        unresolved_pkgs = bridgelist.copy()
        for bdgpkg in bridgelist:
            sup_found = False
            m = re.search (r'(.*)-(.*)-.*\.(.*)\.rpm', bdgpkg)
            try:
                name,version,arch = m.groups()
            except:
                raise AssertionError ("Unable to parse {} as per rpm naming "
                                      "convention.".format (bdgpkg))

            for pkg in pkglist:
                if pkg == bdgpkg:
                    unresolved_pkgs.remove (pkg)
                    break
                
                if rpmutils.is_cisco_rpm (self.platform, bdgpkg):
                    try:
                        m = re.search (r'(.*)-(.*)-.*\.(.*)\.rpm', pkg)
                        pkgname,pkgversion,pkgarch = m.groups()
                    except:
                        raise AssertionError ("Unable to parse input {} as per rpm "
                                          "naming convention.".format (pkg))
                    if name != pkgname:
                        continue
                
                    if name == pkgname:
                        if arch != pkgarch:
                            continue
                        # Compare version and pkgversion
                        result = rpmutils.compare_rpm_ver (version, pkgversion)
                        if result < 0:
                            sup_found = True
                            pkgs2consider.append (pkg)
                            unresolved_pkgs.remove (bdgpkg)
                            break

            if not sup_found:
                pkgs2consider.append (bdgpkg)
        
        return pkgs2consider, unresolved_pkgs
