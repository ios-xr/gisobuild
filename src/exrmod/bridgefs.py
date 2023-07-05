# -----------------------------------------------------------------------------

""" Module to run checks on available rpms for bridge SMU corresponding to
a release.

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
import sys
import argparse
import logging
import glob
import tarfile
import shutil
import tempfile
import re
try:
    import exrmod.gisobuild_exr_engine as gb
except ImportError:
    import sys 
    sys.path.append (os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
    import exrmod.gisobuild_exr_engine as gb
import utils.gisoutils as gu
import exrmod.exrutils.rpmutils as exu
from utils.gisoglobals import *

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

class BridgeRpmDB:

    class BridgeDBdirpath:

        @classmethod
        def get_dirpath_release (cls, out_dir, rel):
            dir_name = os.path.join (out_dir, "staged_rel_{}".format(rel))
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
            rel = re.search(r'staged_rel_(.*)', 
                        os.path.basename (dir_name)).groups()[0]
            return rel

    def __init__(self, platform, isorel, repolist, fsroot, out_dir):
        self.repolist = repolist
        self.isorel = isorel
        self.out_dir = out_dir
        self.platform = platform
        self.fsroot = fsroot
        self.rpm_bridge_path = []    # List of dirpath for different releases.
        self.rpm_bridge_mdata = {}   # Dictionary of rpm mdata for each release.
        self.rpms_in_db = []         # Rpms being considered for bridge smus.
        self.tars_in_db = {}         # Dictionary for tar and constituent rpms
        return

    def get_rpm_release (self, rpmfile):
        rpmrel = None
        if exu.is_tp_rpm (self.platform, rpmfile):
            shutil.copy (rpmfile, self.fsroot)
            os.chmod (os.path.join(self.fsroot, 
                            os.path.basename(rpmfile)), 0o644)
            try:
                rpmrel = gu.run_cmd ("chroot {} rpm -qp --qf {} {}"
                                .format(self.fsroot, "\'%{XRRELEASE}\'", 
                                os.path.basename(rpmfile)))
                rpmrel = "r{}".format (rpmrel)
            except Exception as e:
                raise AssertionError ("Unable to query xr release for "
                                              "{}:{}".format(rpmfile, e))
            finally:
                os.unlink (os.path.join(self.fsroot, os.path.basename(rpmfile)))
        else:
            m = re.search (r'(.*/)(.*)-(.*)-(.*)\.(.*)(\.rpm)', rpmfile)
            rpmrel = m.groups()[3] 
            m = re.search(r'(.*)\.(.*)\.(.*)', rpmrel)
            if not m:
                m = re.search (r'(.*)\.(.*)', rpmrel)
            if not m:
                m = re.search (r'(.*)', rpmrel)
            if m:
                rpmrel = m.groups()[0]
        return rpmrel

    def handle_rpm (self,rpmfile):
        rpm_dir_path = None
        diff_rel_rpm = True
        rpm_rel = self.get_rpm_release (rpmfile)
        if not rpm_rel:
            diff_rel_rpm = False
        if self.isorel == rpm_rel:
            diff_rel_rpm = False

        if diff_rel_rpm:
            dir_name = self.BridgeDBdirpath.get_dirpath_release (self.out_dir, rpm_rel)
            shutil.copy (rpmfile, dir_name)
            if dir_name not in self.rpm_bridge_path:
                self.rpm_bridge_path.append (dir_name) 
            rpm_dir_path = os.path.join (dir_name, os.path.basename (rpmfile))
            self.rpms_in_db.append (os.path.basename (rpmfile))

        return rpm_dir_path

    def handle_tar (self, tarf):
        rpmdirpath = []
        if not os.path.isfile (tarf):
            return

        extract_path = tempfile.mkdtemp (dir = self.out_dir)
        try:
            with tarfile.open(tarf, "r") as tar:
                tar_extract_all(tar, extract_path)
        except Exception as e:
            raise AssertionError ("Unable to extract {}:{}".format (
                                       tarf, e))
             
        for rpmfile in glob.glob (extract_path + "/*.rpm"):
            rpmdirpath.append(self.handle_rpm (rpmfile))

        if os.path.exists (extract_path):
            shutil.rmtree (extract_path)

        self.tars_in_db[tarf] = rpmdirpath

        return

    def get_nonisorelease_rpms (self):
        repofiles = []

        for repo in self.repolist:
            repofiles.extend (glob.glob(repo+"/*"))

        for repofile in repofiles:
            if gu.get_file_type (repofile) == FILE_TYPE_TAR:
                self.handle_tar (repofile)
            elif gu.get_file_type (repofile) == FILE_TYPE_RPM:
                self.handle_rpm (repofile)
            else:
                continue

        return

    def populate_bridgedb_mdata (self):
        self. get_nonisorelease_rpms ()
        repolist = self.rpm_bridge_path
        for repo in repolist:
            rel = self.BridgeDBdirpath.get_release_dirpath (repo)
            self.rpm_bridge_mdata [rel] = []
            for rpmfile in glob.glob (repo + "/*.rpm"):
                shutil.copy (rpmfile, self.fsroot)
                try:
                    rpm = gb.Rpm()
                    rpm.populate_mdata (self.fsroot, os.path.basename (rpmfile), False)
                    self.rpm_bridge_mdata [rel].append (rpm)
                except Exception as e:
                    raise AssertionError ("Unable to populate mdata for {}: {}"
                                           .format (rpmfile, e))
                finally:
                    os.unlink (os.path.join(self.fsroot, os.path.basename(rpmfile)))
        return

    def get_fs_bridge_db (self):
        return self.rpm_bridge_mdata

    def get_fs_rpms_in_db (self):
        return self.rpms_in_db

    def get_fs_tars_in_db (self):
        return self.tars_in_db

    def get_release_path(self, rel):
        dir_name = self.BridgeDBdirpath.get_dirpath_release (self.out_dir, rel)
        return dir_name

    def __enter__(self):
        return self

    def cleanup (self):
        print ("Cleaning staging location.")
        for repo in self.rpm_bridge_path:
            try:
                if os.path.exists (repo):
                    shutil.rmtree (repo)
            except:
                pass
        return

    def __del__(self):
        for repo in self.rpm_bridge_path:
            try:
                if os.path.exists (repo):
                    shutil.rmtree (repo)
            except:
                pass
        return

    def __exit__(self, exc_type, exc_val, exc_tb):
        for repo in self.rpm_bridge_path:
            if os.path.exists (repo):
                shutil.rmtree (repo)
        return True if exc_type is None else False

