#!/usr/bin/env python3
# -----------------------------------------------------------------------------

""" Tool to parse input repos for bridge SMUs.

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

import os
import argparse
import logging
import glob
import tarfile
import shutil
import traceback
import tempfile
from collections import OrderedDict
import re
import sys
try:
    import exrmod.gisobuild_exr_engine as gb
except ImportError:
    sys.path.append (os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
    import exrmod.gisobuild_exr_engine as gb
from exrmod.bridgefs import BridgeRpmDB
import exrmod.exrutils.rpmutils as rpmutils
import exrmod.load_matrix as load_matrix

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

def parsecli ():
    parser = argparse.ArgumentParser (description = "Test utility")
    parser.add_argument("--repo",
                        dest='repo', nargs='+',
                        default = [],
                        help='Repo path to look for bridge SMUs.')
    parser.add_argument('--from-release', dest='bridgelist',
                        required=False, nargs='+',
                        default=[],
                        help='Bridge smus to package.')
    parser.add_argument("--out-directory", dest="out_directory",
                        type = str,
                        help="Output Directory")
    parser.add_argument("--to-release",
                        dest='isorel', type=str,
                        help='ISO release')
    parser.add_argument("--matrixfile",
                        dest='matfile', type=str,
                        help='Compatibility matrix file to get data')
    parser.add_argument("--fsroot",
                        dest='fsroot', type=str,
                        help='GISO file system root')
    parser.add_argument("--platform",
                        dest='platform', type=str,
                        help='Platform')
    args = parser.parse_args ()
    return args

class GisoBridgeDB:
    # Helper class to encode dirpath from release or decode release from dirpath
    class BridgeDBdirpath:

        @classmethod
        def get_dirpath_release (cls, out_dir, rel):
            dir_name = os.path.join (out_dir, "{}".format(rel))
            try:
                os.makedirs (dir_name)
            except FileExistsError as e:
                pass
            except Exception as e:
                raise AssertionError ("Unable to create directory {}:{}"
                                              .format(dir_name, e)) 
            return dir_name

        @classmethod
        def get_release_dirpath (cls, dir_name):
            rel = re.search(r'(.*)', os.path.basename (dir_name)).groups()[0]
            return rel 

    def __init__ (self, platform, isorel, repolist, fsroot, out_dir):
        self.fs_bridge_db = BridgeRpmDB (platform, isorel, repolist,
                                         fsroot, out_dir)
        self.platform = platform
        self.giso_bridge_db = {}
        self.giso_bridge_repos = []  # Repo path for different release being considered.
        self.out_dir = out_dir
        self.fs_bridge_db.populate_bridgedb_mdata ()
        return

    def error_cleanup (self):
        print ("Encountered an error while packaging bridge SMUs. Cleaning up any staged rpm")
        for repo in self.giso_bridge_repos:
            try:
                if os.path.exists (repo):
                    shutil.rmtree (repo)
            except:
                pass
        if os.path.isdir (self.out_dir):
            try:
                shutil.rmtree (self.out_dir)
            except:
                pass
        return

    def cleanup (self):
        print ("Do cleanups.")
        self.fs_bridge_db.cleanup()

    def is_rpm_in_bridge_db (self, rpmfile):
        dir_path = None
        release = None
        bridge_mdata = self.fs_bridge_db.get_fs_bridge_db()
        for key, value in bridge_mdata.items():
            rpms_rel = [x.file_name for x in value]
            if rpmfile in rpms_rel:
                release = key
                dir_path = self.fs_bridge_db.get_release_path (key)
                break

        return dir_path, release

    def handle_tar (self, tarname):
        rpmsintar = None
        bridgefs_tars = self.fs_bridge_db.get_fs_tars_in_db ()
        for key, value in bridgefs_tars.items ():
            filename = os.path.basename (key)
            if tarname == filename:
                rpmsintar = [os.path.basename(x) for x in value]
        return rpmsintar

    def handle_release (self, relnum, matrixobj):
        rpmlist = []
        dotted_rel = relnum
            
        m = re.search (r'r(.*)', relnum)
        if not m:
            # Modify the release number to align with PROD releases.
            if not relnum.split('.')[-1].isnumeric():
                relnum = "r{}".format(''.join(relnum.split('.')))
            else:
                relnum = "r{}".format(''.join(relnum.split('.')))
        reldata = matrixobj.data_release (relnum)
        if not reldata:
            print ("Ignoring release {}"
                   .format (dotted_rel))
        else:
            _, rpmlist = reldata.popitem()
        return rpmlist

    def split_packages_release (self, pkglist, matrixobj):
        rpmlist = []
        for pkg in pkglist:
            if pkg.endswith (".rpm"):
                rpmlist.append (pkg)
            elif pkg.endswith (".tar"):
                rpms_in_tar = self.handle_tar (pkg)
                if rpms_in_tar:
                    rpmlist.extend (rpms_in_tar)
                else:
                    raise AssertionError ("Tar {} in input not available "
                                "in any of the input repositories.".format(pkg))
            else:
                rpms_in_rel = self.handle_release (pkg, matrixobj)
                if rpms_in_rel:
                    rpmlist.extend (rpms_in_rel)

        package_repo = OrderedDict()
        for rpmfile in rpmlist:
            dir_path, rel = self.is_rpm_in_bridge_db (rpmfile)
            if not dir_path and not rel:
                raise AssertionError ("RPM {} in input not "
                        "available in any of the input repositories."
                        .format(rpmfile))
            if not package_repo.get (rel):
                package_repo[rel] = []
            package_repo[rel].append (rpmfile)
        return package_repo 

    def handle_rpm (self, rpmfile):
        dir_path, rel = self.is_rpm_in_bridge_db (rpmfile)
        if not dir_path and not rel:
            raise AssertionError ("RPM {} in bridging release not available "
                            "in any of the input repositories".format(rpmfile))

        dir_name = self.BridgeDBdirpath.get_dirpath_release (self.out_dir, rel)
        print ("Copy {} to destination.".format (rpmfile))
        shutil.copy (os.path.join(dir_path, rpmfile), dir_name)
        if dir_name not in self.giso_bridge_repos:
            self.giso_bridge_repos.append(dir_name)
        return

    def add_req_rpms (self, reqList, provList, repodata, rel):
        totalreqs = rpmutils.optimise_reqlist (reqList)
        while True:
            if not totalreqs:
                break
            totalreqs_temp = list (totalreqs)
            for reqstr in totalreqs:
                rpmdata = rpmutils.whatprovides (reqstr, repodata)
                if rpmdata:
                    # Copy the rpm to gisobuild staging path.
                    src_path = os.path.join(
                                self.fs_bridge_db.get_release_path (rel), 
                                rpmdata.file_name)
                    dest_path = os.path.join(
                                self.BridgeDBdirpath.get_dirpath_release (
                                                        self.out_dir, rel), 
                                rpmdata.file_name)
                    if not os.path.exists (dest_path):
                        shutil.copy (src_path, dest_path)
                    self.giso_bridge_db[rel].append (rpmdata.file_name)
                    print ("Add {} to the build repo".format (
                                                        rpmdata.file_name))
                    # Add this rpm requires and provides for consideration
                    requires, provides = rpmutils.sanitize_reqs_rpm (
                                        rpmdata.file_name, 
                                        repodata, 
                                        rel, 
                                        self.platform)
                    provList.extend (provides)
                    totalreqs_temp.extend (rpmutils.get_unresolved_reqs (
                                                                requires, 
                                                                provList))
                    totalreqs_temp.remove (reqstr)
                else:
                    raise AssertionError ("Failed Dependencies: Unable to "
                                          "resolve needed capability {} in "
                                          "repo.".format (reqstr))
            totalreqs = rpmutils.optimise_reqlist (totalreqs_temp)
                
        return    

    def sanitize_giso_bridge_rpms (self):
        print ("Add pre-requisite and dependent rpms for calculated bridge SMU list.")
        bridge_mdata = self.fs_bridge_db.get_fs_bridge_db()
        repolist = self.giso_bridge_repos
        for repo in repolist:
            totalreq = []
            totalprov = []
            unresolved_reqs_repo = []
            rel = self.BridgeDBdirpath.get_release_dirpath (repo)
            self.giso_bridge_db[rel] = []
            repomdata = bridge_mdata.get (rel)

            if not repomdata:
                raise AssertionError ("Metadata for release {} not "
                                      "available.".format (rel))

            for rpmfile in glob.glob (repo+"/*"):
                self.giso_bridge_db[rel].append (os.path.basename(rpmfile))
                requires, provides = rpmutils.sanitize_reqs_rpm (
                                                                rpmfile,
                                                                repomdata,
                                                                rel,
                                                                self.platform)
                totalprov.extend (provides)
                totalreq.extend (requires)

            unresolved_reqs_repo = rpmutils.get_unresolved_reqs (totalreq,
                                                                 totalprov)
            
            self.add_req_rpms (unresolved_reqs_repo, totalprov, repomdata, rel)

        return

    def populate_giso_bridge_db (self, pkglist):
        for pkg in pkglist:
            if pkg.endswith (".rpm"):
                self.handle_rpm (pkg)
            elif pkg.endswith (".tar"):
                self.handle_tar (pkg)
            elif re.search('CSC[a-z][a-z]\d{5}', pkg):
                self.handle_ddts (pkg)
            else:
                self.handle_release (pkg)

        # Now that pkglist is moved to destination release directory, 
        # check for pre-reqs.
        self.sanitize_giso_bridge_rpms ()

        return

'''Validate input arguments.'''
def validate_and_setup_args (args):
    if args.platform == "asr9k":
        args.platform = "asr9k-x64"

    if not os.path.exists (args.fsroot):
        raise AssertionError ("Build rootfs not provided")

    return args

if __name__ == '__main__':
    rel_bridge_dict = OrderedDict()
    bridgelist = []
    unresolved_pkgs = []
    matrixobj = None
    ret_success = 0

    args = parsecli()
    args = validate_and_setup_args (args)
    
    gb.initialize_globals (os.getcwd(), args, logger, args.platform)

    obj = GisoBridgeDB(args.platform, args.isorel, args.repo, 
                       args.fsroot, args.out_directory)
    
    print ("\nLoad and validate the upgrade compatibility matrix associated "
                "with input iso.")
    try:
        matrixobj = load_matrix.Matrix (args.matfile, args.platform)
    except Exception as e:
        print ("Unable to load input matrix {}".format (args.matfile))
        exc_type, exc_value, exc_tb = sys.exc_info()
        tb = traceback.TracebackException(exc_type, exc_value, exc_tb)
        print(''.join(tb.format_exception_only()))
        ret_success = -1

    if matrixobj and args.bridgelist:
        try:
            print ("Validate the input against bridge SMUs defined for "
                   "supported releases.")
            rel_bridge_dict = obj.split_packages_release (args.bridgelist, 
                                                                matrixobj)
        except Exception as e:
            exc_type, exc_value, exc_tb = sys.exc_info()
            tb = traceback.TracebackException(exc_type, exc_value, exc_tb)
            print(''.join(tb.format_exception_only()))
            ret_success = -1

    for rel, rpmlist in rel_bridge_dict.items():
        repobridgelist, unresolved_pkgs = matrixobj.validate_input_pkgs (rel, rpmlist)
        if unresolved_pkgs:
            print ("Input packages {} do not match against the specified bridge "
               "SMUs in upgrade matrix file for release {}. Ignoring from "
               "GISO build.".format (','.join(unresolved_pkgs), rel))
        bridgelist.extend (repobridgelist)

    try:
        if ret_success == 0:
            obj.populate_giso_bridge_db(bridgelist)
    except Exception as e:
        obj.error_cleanup ()
        exc_type, exc_value, exc_tb = sys.exc_info()
        tb = traceback.TracebackException(exc_type, exc_value, exc_tb)
        print(''.join(tb.format_exception_only()))
        ret_success = -1

    obj.cleanup ()
    sys.exit (ret_success)
