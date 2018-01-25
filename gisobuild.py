#! /usr/bin/env python
# =============================================================================
# gisobuild.py
#
# utility to build golden iso
#
# Copyright (c) 2015-2017 by cisco Systems, Inc.
# All rights reserved.
# =============================================================================
from datetime import datetime
import argparse
import functools
import getpass
import glob
import logging
import os
import re
import shutil 
import socket
import subprocess
import sys
import tempfile
import yaml

__version__ = '0.7'
GISO_PKG_FMT_VER = 1.0

# Minimum 3 GB Disk Space 
# required for building GISO
MIN_DISK_SPACE_SIZE_REQUIRED = 3 
MAX_RPM_SUPPORTED_BY_INSTALL = 128 
SPIRIT_BOOT_SUBSTRING = 'spirit-boot'
SYSADMIN_SUBSTRING = 'SYSADMIN'
CALVADOS_SUBSTRING = 'CALVADOS'
HOSTOS_SUBSTRING = 'hostos'
IOS_XR_SUBSTRING = 'IOS-XR'
ADMIN_SUBSTRING = 'ADMIN'
HOST_SUBSTRING = 'HOST'
SMU_SUBSTRING = 'SMU'
XR_SUBSTRING = 'XR'


def run_cmd(cmd):
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE, shell=True)
    out, error = process.communicate()
    sprc = process.returncode
    if sprc is None or sprc != 0:
        out = error
        raise RuntimeError("Error CMD=%s returned --->%s" % (cmd, out))
    return dict(rc=sprc, output=out)

class Migtar:
    ISO="iso"
    EFI="EFI"
    BOOT_DIR="boot"
    TMP_BOOT_DIR="tmp_boot"
    BZIMAGE="bzImage"
    INITRD="initrd.img"
    BOOT_INITRD=BOOT_DIR + "/" + INITRD
    SIGN_INITRD="signature.initrd.img"
    CERT_DIR="certs"
    GRUB_DIR="EFI/boot/"
    GRUB_CFG="set default=0\n"\
             "terminal_input console\nterminal_output console\n"\
             "set timeout=5\n"\
             "set iso_filename=system_image.tar\n"\
             "menuentry \"ASR9K Host OS - ISO ($iso_filename)\" "\
             "{\necho \"Booting from embedded USB\"\n"\
             "echo \"Loading Kernel...\"\n"\
             "linux (hd0,msdos3)/boot/bzImage root=/dev/ram install=/dev/sda "\
             "pci=hpmemsize=0M,hpiosize=0M platform=asr9k console=ttyS0,115200 "\
             "intel_idle.max_cstate=0 processor.max_cstate=1 giso_boot "\
             "eusbboottar=$iso_filename quiet\n"\
             "echo \"Loading initrd...\"\n"\
             "initrd (hd0,msdos3)/boot/initrd.img "\
             "signfile=(hd0,msdos3)/boot/signature.initrd.img\n}\n"

    def __init__(self):
        self.dst_system_tar = None
    #
    # Migration Tar object Setter Api's
    #

    def cleanup(self):
        if os.path.exists(self.BOOT_DIR):
            run_cmd('rm -rf ' + self.BOOT_DIR)

        if os.path.exists(self.TMP_BOOT_DIR):
            run_cmd('rm -rf ' + self.TMP_BOOT_DIR)

        if os.path.exists(self.EFI):
            run_cmd('rm -rf ' + self.EFI)

    def create_migration_tar(self, workspace_path, input_image):
        logger.debug("Workspace Path = %s and Iso name = %s"
                     % (workspace_path, input_image))
        # Check if workspace directory exists
        if not os.path.exists(workspace_path):
            logger.error("Workspace for building migration tar doesnot exist!")
            sys.exit(-1)
        # Check if input image exists
        if not os.path.exists(input_image):
            logger.error("ISO (%s) for  building migration tar doesnot exist!"
                         % input_image)
            sys.exit(-1)

        dst_system_image=os.path.basename(input_image)

        # Get Destination tar file name and check if this exists.
        self.dst_system_tar = dst_system_image.replace(".iso","-migrate_to_eXR.tar");

        if os.path.exists(self.dst_system_tar):
            logger.debug("Removing old tar file %s " % self.dst_system_tar)
            run_cmd('rm -rf ' + self.dst_system_tar)
    
        # Check if Boot Directory exists
        if os.path.exists(self.BOOT_DIR):
            logger.debug("Removing old boot dir %s " % self.BOOT_DIR)
            run_cmd('rm -rf '+ self.BOOT_DIR)

        # Check if system_image.iso file exists.
        if input_image != dst_system_image:
            logger.debug("Copying given ISO(%s) to migration tar name(%s)" 
                        % (input_image, dst_system_image))
            run_cmd('cp -f ' + input_image + " " + dst_system_image)

        run_cmd('mkdir -p ' + workspace_path + "/tmp")
        TMP_INITRD=workspace_path+"/tmp/initrd.img"
    
        logger.debug("Getting initrd(%s) from ISO" % self.BOOT_INITRD)
        run_cmd('iso-read -i ' + input_image + " -e /" + self.BOOT_INITRD + " -o " + TMP_INITRD)

        #check if Boot Directory exists
        if not os.path.exists(TMP_INITRD):
            logger.error("Failed to extract initrd(%s) from ISO" 
                         % (self.BOOT_INITRD, input_image))
            logger.Info("Please make sure at least 1.5 GB of space is availble in /tmp/")
            sys.exit(-1)

        logger.debug("Getting BOOT_DIR(%s) " % self.BOOT_DIR)
        run_cmd("zcat " + TMP_INITRD + " | cpio -id " + self.BOOT_DIR + "/*");

        logger.debug("Deleting tmp path (%s) in workspace path" 
                     %  workspace_path + "/tmp")
        run_cmd( "rm -rf " + workspace_path + "/tmp")

        # Check if Tmp boot dir  Directory exists
        if os.path.exists(self.TMP_BOOT_DIR):
            logger.debug("Removing old tmp_boot dir %s " % self.TMP_BOOT_DIR)
            run_cmd('rm -rf '+ self.TMP_BOOT_DIR)
        run_cmd( "mkdir " + self.TMP_BOOT_DIR)

        logger.debug("Copying BZIMAGE(%s) to TMP_BOOT_DIR(%s) "
                     % (self.BZIMAGE, self.TMP_BOOT_DIR))
        run_cmd( "cp " + self.BOOT_DIR + "/" + self.BZIMAGE + " " + self.TMP_BOOT_DIR)

        logger.debug("Moving INITRD(%s) to TMP_BOOT_DIR(%s) "
                     % (self.INITRD, self.TMP_BOOT_DIR))
        run_cmd( "mv " + self.BOOT_DIR + "/" + self.INITRD + " " + self.TMP_BOOT_DIR)

        logger.debug("Moving SIGN_INITRD(%s) to TMP_BOOT_DIR(%s) "
                     % (self.SIGN_INITRD, self.TMP_BOOT_DIR))
        run_cmd( "mv " + self.BOOT_DIR + "/" + self.SIGN_INITRD + " " + self.TMP_BOOT_DIR)

        logger.debug("Moving CERT_DIR(%s) to TMP_BOOT_DIR(%s) "
                     % (self.CERT_DIR, self.TMP_BOOT_DIR))
        run_cmd( "mv " + self.BOOT_DIR + "/" + self.CERT_DIR + " " + self.TMP_BOOT_DIR)

        logger.debug("Creating grub files")
        run_cmd ( "mkdir -p " + self.GRUB_DIR)
        run_cmd ( "cp " + self.BOOT_DIR + "/grub2/bootx64.efi " + self.GRUB_DIR + "grub.efi")

        GRUB_CFG_FILE=self.GRUB_DIR + "grub.cfg"
        logger.debug("Grub Config file: %s" % GRUB_CFG_FILE)
        with open(GRUB_CFG_FILE, 'w') as f:
	        f.write(self.GRUB_CFG)

        run_cmd( "rm -rf " + self.BOOT_DIR)
        run_cmd ("mv " + self.TMP_BOOT_DIR + " " + self.BOOT_DIR)

        logger.debug("tar -cvf " + self.dst_system_tar + " " + self.BOOT_DIR + " " + self.GRUB_DIR + " " + dst_system_image)
        run_cmd("tar -cvf " + self.dst_system_tar + " " + self.BOOT_DIR + " " + self.GRUB_DIR + " " + dst_system_image)

    def __enter__(self):
        return self

    def __exit__(self, type_name, value, tb):
        self.cleanup()

class Rpm:

    def __init__(self):
        self.name = None
        self.version = None
        self.release = None
        self.arch = None
        self.package_type = None
        self.package_presence = None
        self.package_pipd = None
        self.package_platform = None
        self.build_time = None
        self.platform = None
        self.card_type = None
        self.provides = None
        self.requires = None
        self.group = None
        self.vm_type = None
        self.supp_cards = None
        self.prefixes = None
        self.xrrelease = None
        self.file_name = None

    def populate_mdata(self, fs_root, rpm):
        self.file_name = rpm
        result = run_cmd("chroot "+fs_root+" rpm -qp --qf '%{NAME};%{VERSION};"
                         "%{RELEASE};%{ARCH};%{PACKAGETYPE};%{PACKAGEPRESENCE};"
                         "%{PIPD};%{CISCOHW};%{CARDTYPE};%{BUILDTIME};"
                         "%{GROUP};%{VMTYPE};%{SUPPCARDS};%{PREFIXES};"
                         "%{XRRELEASE};' "+rpm)

        result_str_list = result["output"].split(";")
        self.name = result_str_list[0]
        self.version = result_str_list[1]
        self.release = result_str_list[2]
        self.arch = result_str_list[3]
        self.package_type = result_str_list[4]
        self.package_presence = result_str_list[5]
        self.package_pipd = result_str_list[6]
        self.package_platform = result_str_list[7]
        self.card_type = result_str_list[8]
        self.build_time = result_str_list[9]
        self.group = result_str_list[10]
        self.vm_type = result_str_list[11]
        self.supp_cards = result_str_list[12].split(",")
        self.prefixes = result_str_list[13]
        self.xrrelease = result_str_list[14]

        result = run_cmd("chroot %s rpm -qp --provides %s" % (fs_root, rpm))
        self.provides = result["output"]

        result = run_cmd("chroot %s rpm -qp --requires %s" % (fs_root, rpm))
        #
        # There can be more than one requires.
        # Ignore requires starting with /
        # example /bin/sh
        # Ignore /bin/sh requires. 
        #
        result_str_list = result["output"].split("\n")
        requires_list = []
        map(lambda x: requires_list.append(x),
            filter(lambda y: not y.startswith('/'), result_str_list))

        self.requires = requires_list
        map(lambda x: logger.debug("%s:%s" % x), vars(self).items())
         
    #
    # RPM is Hostos RPM if rpm name has hostos keyword and platform name.
    #
    def is_hostos_rpm(self, platform):
        return ("hostos" in self.name) and (platform in self.name)

    #
    # RPM is Tirdparty(TP) rpm if IOS-XR HOST and SYSADMIN group doesnt not 
    # appear.
    #
    def is_cisco_rpm(self, platform):
        return ((platform in self.name) and 
                (IOS_XR_SUBSTRING in self.group.upper()
                 or HOST_SUBSTRING in self.group.upper()
                 or SYSADMIN_SUBSTRING in self.group.upper()))

    def is_tp_rpm(self, platform):
        if self.xrrelease.strip() == "(none)":
            return False
        else : 
            # All TP SMUs will have xrrelease 
            return True

    def is_spiritboot(self):
        return ((SPIRIT_BOOT_SUBSTRING in self.name) and 
                (IOS_XR_SUBSTRING in self.group.upper()
                 or HOST_SUBSTRING in self.group.upper()
                 or SYSADMIN_SUBSTRING in self.group.upper()))


class Rpmdb:
    def __init__(self):
        self.bundle_iso = Iso()
        self.repo_path = None
        self.rpm_list = []
        self.csc_rpm_list = []
        self.tp_rpm_list = []
        self.csc_rpm_count = 0
        self.tp_rpm_count = 0
        self.sdk_archs = []
        self.all_arch_list = []
        self.sdk_rpm_mdata = {}
        # It contains the list of tp rpms released via cisco
        self.tp_release_rpms_host_list = []
        self.tp_release_rpms_admin_list = []
        self.tp_release_rpms_xr_list = []
        # {"Host":{Arch:[rpmlist]},"Cal":{Arch:[rpmlist]},"Xr":{Arch:[rpmlist]}}
        # self.csc_rpms_by_vm_arch = {VM_TYPES"HOST": {}, "CALVADOS": {}, "XR": {}}
        self.csc_rpms_by_vm_arch = {HOST_SUBSTRING: {}, 
                                    CALVADOS_SUBSTRING: {}, 
                                    XR_SUBSTRING: {}}
        self.tp_rpms_by_vm_arch = {HOST_SUBSTRING: {},
                                   CALVADOS_SUBSTRING: {}, 
                                   XR_SUBSTRING: {}}

    def populate_rpmdb(self, fs_root, repo):
        if not (repo and fs_root):
            logger.error('Invalid arguments')
            return -1
        logger.info("\nScanning repository [%s]...\n" % (os.path.abspath(repo)))
        repo_files = glob.glob(repo+"/*")
        if not len(repo_files):
            logger.info('RPM repository directory \'%s\' is empty!!' % repo)
            return 0 
        rpm_name_version_release_arch_list = []
        logger.info("Building RPM Database...")
        for file_name in repo_files:
            result = run_cmd('file -b %s' % file_name)
            if re.match(".*RPM.*", result["output"]):
                shutil.copy(file_name, fs_root)
                rpm = Rpm()
                rpm.populate_mdata(fs_root, os.path.basename(file_name))
                rpm_name_ver_rel_arch = "%s-%s-%s.%s" % (rpm.name, rpm.version,
                                                         rpm.release, rpm.arch)
                if rpm_name_ver_rel_arch \
                   not in rpm_name_version_release_arch_list:
                    self.rpm_list.append(rpm)
                    rpm_name_version_release_arch_list.\
                        append(rpm_name_ver_rel_arch)
        logger.info("Total %s RPM(s) present in the repository path provided in CLI" % (len(self.rpm_list)))
        self.repo_path = repo
       
        return 0

    #
    # Categorize rpms into Cisco RPMS and TP RPMS.
    # Discard other rpms in the repository
    #
    def populate_tp_cisco_list(self, platform):
        non_tp_cisco_rpms = set()
        for rpm in self.rpm_list:
            if rpm.is_tp_rpm(platform):
                self.tp_rpm_list.append(rpm)
            elif rpm.is_cisco_rpm(platform):
                self.csc_rpm_list.append(rpm)
            else:
                non_tp_cisco_rpms |= set([rpm])
                logger.debug("Skipping Non Cisco/Tp rpm %s" % rpm.file_name)
        self.rpm_list = list(set(self.rpm_list)-non_tp_cisco_rpms)
        self.csc_rpm_count = len(self.csc_rpm_list)
        self.tp_rpm_count = len(self.tp_rpm_list)
        if non_tp_cisco_rpms: 
            logger.info("Skipped %s non Cisco/Tp RPM(s)" % 
                        (len(non_tp_cisco_rpms)))

    #
    # Filter and discard Cisco rpms not matching input release string.
    #
    def filter_cisco_rpms_by_release(self, release):
        iso_release = release.replace('.', '')
        version_missmatch_rpms = set()
        for rpm in self.csc_rpm_list:
            if not (iso_release in rpm.release):
                version_missmatch_rpms |= set([rpm])   
        self.csc_rpm_list = list(set(self.csc_rpm_list) - 
                                 version_missmatch_rpms)
        self.rpm_list = list(set(self.rpm_list) - version_missmatch_rpms)
        self.csc_rpm_count = len(self.csc_rpm_list)
        if version_missmatch_rpms:
            logger.info("Skipped %s RPMS not matching version %s"
                        % (len(version_missmatch_rpms), release))
        logger.debug('Found %s Cisco RPMs' % self.csc_rpm_count)
        map(lambda rpm_inst: logger.debug("\t\t%s" % rpm_inst.file_name),
            self.csc_rpm_list)

        # filter TP SMUs based on XR release
        version_missmatch_tp_rpms = set()
        for rpm in self.tp_rpm_list:
            if not (iso_release in rpm.xrrelease):
                version_missmatch_tp_rpms |= set([rpm])   
        self.tp_rpm_list = list(set(self.tp_rpm_list) - 
                                 version_missmatch_tp_rpms)
        self.rpm_list = list(set(self.rpm_list) - version_missmatch_tp_rpms)
        self.tp_rpm_count = len(self.tp_rpm_list)
        if version_missmatch_tp_rpms:
            logger.info("Skipped %s TP RPMS not matching version %s"
                        % (len(version_missmatch_tp_rpms), release))
        logger.debug('Found %s TP RPMs' % self.tp_rpm_count)
        map(lambda rpm_inst: logger.debug("\t\t%s" % rpm_inst.file_name),
            self.tp_rpm_list)
    #
    # Filter and discard Cisco rpms not matching platform of mini ISO.
    #
    def filter_cisco_rpms_by_platform(self, platform):
        platform_missmatch_rpms = set()
        for rpm in self.csc_rpm_list:
            if not (platform in rpm.package_platform):
                platform_missmatch_rpms |= set([rpm])   
        self.csc_rpm_list = list(set(self.csc_rpm_list) - 
                                 platform_missmatch_rpms)
        self.rpm_list = list(set(self.rpm_list) - platform_missmatch_rpms)
        self.csc_rpm_count = len(self.csc_rpm_list)

        if platform_missmatch_rpms:
            logger.info("Skipped %s RPMS not matching platform %s"
                        % (len(platform_missmatch_rpms), platform))
        logger.debug('Found %s Cisco RPMs' % self.csc_rpm_count)
        map(lambda rpm_inst: logger.debug("\t\t%s" % rpm_inst.file_name),
            self.csc_rpm_list)
        
        # filter TP SMUs based on platform
        platform_missmatch_tp_rpms = set()
        for rpm in self.tp_rpm_list:
            if not (platform in rpm.package_platform):
                platform_missmatch_tp_rpms |= set([rpm])   
        self.tp_rpm_list = list(set(self.tp_rpm_list) - 
                                 platform_missmatch_tp_rpms)
        self.rpm_list = list(set(self.rpm_list) - platform_missmatch_tp_rpms)
        self.tp_rpm_count = len(self.tp_rpm_list)

        if platform_missmatch_tp_rpms:
            logger.info("Skipped %s TP RPMS not matching platform %s"
                        % (len(platform_missmatch_tp_rpms), platform))
        logger.debug('Found %s TP RPMs' % self.csc_rpm_count)
        map(lambda rpm_inst: logger.debug("\t\t%s" % rpm_inst.file_name),
            self.csc_rpm_list)
        

    #
    # Read the content from release-rpms-*.txt and prepare list for each domain.
    #
    def populate_tp_rpmdb_from_sdk_release_file(self, platform_key, iso_mount_path):
        vm_list = [HOST_SUBSTRING, ADMIN_SUBSTRING, XR_SUBSTRING]
        self.sdk_archs = []
        sdk_rpm_list_files = glob.glob(os.path.join(iso_mount_path,
                                                    "release-rpms-*.txt"))
        if len(sdk_rpm_list_files) != 0:
            for sdk_rpmf in sdk_rpm_list_files:
                m = re.search(r'(.*/)release-rpms-(.*)-(.*)(\.txt)', sdk_rpmf)
                if m:
                    sdk_arch = m.groups()[2]
                    self.sdk_archs.append(sdk_arch)

            for sdk_arch in self.sdk_archs:
                for sdk_rpm_list_file in sdk_rpm_list_files:
                    for vm in vm_list:
                        vmstr = "-%s-" % vm.lower()
                        if sdk_arch not in sdk_rpm_list_file:
                            continue
                        if vmstr not in sdk_rpm_list_file:
                            continue              
                    
                        if platform_key not in self.sdk_rpm_mdata:
                            self.sdk_rpm_mdata[platform_key] = {}
                        if vm not in self.sdk_rpm_mdata[platform_key]:
                            self.sdk_rpm_mdata[platform_key][vm] = {}
                        if sdk_arch not in self.sdk_rpm_mdata[platform_key][vm]:
                            self.sdk_rpm_mdata[platform_key][vm][sdk_arch] = {}

                        fdin = open(os.path.join(iso_mount_path, sdk_rpm_list_file))
                        for line in fdin.readlines():
                            sdk_rpm_filename = line.strip() 
                            if sdk_rpm_filename.endswith('.rpm'):
                                mre = re.search(r'(.*)-(.*)-(.*)\.(.*)(\.rpm)', 
                                                sdk_rpm_filename)
                                if mre:
                                    s_rpm_name = mre.groups()[0]
                                    s_rpm_ver = mre.groups()[1]
                                    s_rpm_rel = mre.groups()[2]
                                    s_rpm_arch = mre.groups()[3]

                                    if s_rpm_arch not in self.all_arch_list:
                                        self.all_arch_list.append(s_rpm_arch)

                                    if s_rpm_name not in \
                                       self.sdk_rpm_mdata[platform_key][vm][sdk_arch]:
                                        self.sdk_rpm_mdata[platform_key][vm][sdk_arch][s_rpm_name] = {}

                                    if s_rpm_arch not in \
                                       self.sdk_rpm_mdata[platform_key][vm][sdk_arch][s_rpm_name]:
                                        self.sdk_rpm_mdata[platform_key][vm][sdk_arch][s_rpm_name][s_rpm_arch] = \
                                                          [s_rpm_ver, s_rpm_rel]
                        fdin.close()
        else:
            logger.error("Error: Unsupported iso provided for building Golden ISO")
            logger.debug("release-rpms-*.txt is not present in provided iso")
            sys.exit(-1)

        # sdk release file for host is not present
        # so host rpm metadata would be same as 
        # admin rpm metadata 
        if vm_list[1] in self.sdk_rpm_mdata[platform_key]:
            self.sdk_rpm_mdata[platform_key][vm_list[0]] = \
                 self.sdk_rpm_mdata[platform_key][vm_list[1]]
        logger.debug("SDK RPM metadata dictionary is created successfully")
                                
    def get_tp_base_rpm(self, platform, vm, rpm_name):
        base_rpm_filename = ''
        # vm = vm.lower()
        for sdk_arch in self.sdk_archs:
            # arm arch would not be available for xr vm
            if sdk_arch not in self.sdk_rpm_mdata[platform][vm]:
                continue
            for s_rpm_name in self.sdk_rpm_mdata[platform][vm][sdk_arch]:
                mre = re.search(r'(.*)-(.*)-(.*)\.(.*)(\.rpm)', rpm_name)
                if mre: 
                    i_rpm_name = mre.groups()[0]
                    # i_rpm_ver = mre.groups()[1]
                    # i_rpm_rel = mre.groups()[2]
                    i_rpm_arch = mre.groups()[3]
                    if i_rpm_name == s_rpm_name:
                        base_rpm_arch = \
                            self.sdk_rpm_mdata[platform][vm][sdk_arch][s_rpm_name].keys()[0]

                        # same rpm name and same vm type may have
                        # multiple rpm having different arch 
                        # if arch atches then that is the correct base rpm

                        if i_rpm_arch != base_rpm_arch:
                            break

                        base_rpm_ver = \
                            self.sdk_rpm_mdata[platform][vm][sdk_arch][s_rpm_name][base_rpm_arch][0]
                        base_rpm_rel = \
                            self.sdk_rpm_mdata[platform][vm][sdk_arch][s_rpm_name][base_rpm_arch][1]
                 
                        base_rpm_filename = '%s-%s-%s.%s.%s.%s' % (i_rpm_name,
                                                                   base_rpm_ver,
                                                                   base_rpm_rel,
                                                                   vm.lower(),
                                                                   base_rpm_arch,
                                                                   "rpm")
                        for rpm in self.tp_rpm_list:
                            if base_rpm_filename == rpm.file_name:
                                return rpm   
        if not base_rpm_filename:
            return None 

    # Find for any duplicate tp smu present in repo
    @staticmethod
    def find_duplicate_tp_smu(rpm_set):

        duplicate_rpm_set = set()
        seen_smu_dict = {}

        # If tp smus are built with all the metadata same except ddts id then
        # its not allowed and will throw error and exit
        for rpm in rpm_set:
            if rpm.package_type.upper() == SMU_SUBSTRING:
                smu_nva = "%s-%s-%s" % (rpm.name, rpm.version, rpm.arch)
                if smu_nva in seen_smu_dict:
                    duplicate_rpm_set.add(seen_smu_dict[smu_nva])
                    duplicate_rpm_set.add(rpm)
                else:
                    seen_smu_dict[smu_nva] = rpm

        return duplicate_rpm_set

    # Check and throw error for any duplicate tp smu present 
    def check_all_tp_duplicate_smu(self, host_rpm_set, admin_rpm_set, xr_rpm_set):
        duplicate_tp_host_rpm = set()
        duplicate_tp_admin_rpm = set()
        duplicate_tp_xr_rpm = set()
        rc = 0

        if host_rpm_set:
            duplicate_tp_host_rpm = Rpmdb.find_duplicate_tp_smu(host_rpm_set)
        if admin_rpm_set:
            duplicate_tp_admin_rpm = Rpmdb.find_duplicate_tp_smu(admin_rpm_set)
        if xr_rpm_set:
            duplicate_tp_xr_rpm = Rpmdb.find_duplicate_tp_smu(xr_rpm_set)

        if len(duplicate_tp_host_rpm) != 0:
            logger.error("\nFollowing are the duplicate host tp smus:\n")
            map(lambda rpm_inst: logger.info("\t(*) %s" % rpm_inst.file_name), 
                duplicate_tp_host_rpm)
        if len(duplicate_tp_admin_rpm) != 0:
            logger.error("\nFollowing are the duplicate admin tp smus:\n")
            map(lambda rpm_inst: logger.info("\t(*) %s" % rpm_inst.file_name), 
                duplicate_tp_admin_rpm)
        if len(duplicate_tp_xr_rpm) != 0:
            logger.error("\nFollowing are the duplicate xr tp smus:\n")
            map(lambda rpm_inst: logger.info("\t(*) %s" % rpm_inst.file_name), 
                duplicate_tp_xr_rpm)

        if (len(duplicate_tp_host_rpm) != 0 or len(duplicate_tp_admin_rpm) != 0  
            or len(duplicate_tp_xr_rpm) != 0):
            logger.info("\nThere are multiple TP SMU(s) for same package "
                        "and same version,\nPlease make sure that single "
                        "version per package present in repo.")
            sys.exit(-1)

    #
    # Filter and discard TP rpms not matching input release rpm list.
    #
    def filter_tp_rpms_by_release_rpm_list(self, iso_mount_path, iso_version):

        platform_key = 'platform'
        rc = 0
        valid_tp_host_rpm = set()
        valid_tp_admin_rpm = set()
        valid_tp_xr_rpm = set()
        invalid_tp_host_rpm = set()
        invalid_tp_admin_rpm = set()
        invalid_tp_xr_rpm = set()

        self.populate_tp_rpmdb_from_sdk_release_file(platform_key, 
                                                     iso_mount_path)

        # If name, relase and arch of the given tp rpm matches to the rpms
        # present in the release-rpms*.txt then its a valid rpm
        for rpm in self.tp_rpm_list:
            if rpm.package_type.upper() == SMU_SUBSTRING:

                # Validate Host tp rpm
                if rpm.vm_type.upper() == HOST_SUBSTRING:
                    base_rpm = self.get_tp_base_rpm(platform_key, 
                                                    HOST_SUBSTRING,
                                                    rpm.file_name)
                    if base_rpm is not None:
                        valid_tp_host_rpm |= set([rpm])
                        valid_tp_host_rpm |= set([base_rpm])
                    else:
                        invalid_tp_host_rpm |= set([rpm])

                # Validate Admin tp rpm
                # vm type in rpm mdata is calvados where as in rpm
                # filename it is admin
                elif rpm.vm_type.upper() == CALVADOS_SUBSTRING:
                    base_rpm = self.get_tp_base_rpm(platform_key,
                                                    ADMIN_SUBSTRING,
                                                    rpm.file_name)
                    if base_rpm is not None:
                        valid_tp_admin_rpm |= set([rpm])
                        valid_tp_admin_rpm |= set([base_rpm])
                    else:
                        invalid_tp_admin_rpm |= set([rpm])

                # Validate XR tp rpm
                elif rpm.vm_type.upper() == XR_SUBSTRING:
                    base_rpm = self.get_tp_base_rpm(platform_key,
                                                    XR_SUBSTRING,
                                                    rpm.file_name)
                    if base_rpm is not None:
                        valid_tp_xr_rpm |= set([rpm])
                        valid_tp_xr_rpm |= set([base_rpm])
                    else:
                        invalid_tp_xr_rpm |= set([rpm])

                else:
                    logger.debug("Skipping RPM not generated by Cisco: %s" % 
                                 rpm.file_name)

        if len(invalid_tp_host_rpm):
            logger.info("\nBase rpm(s) of following %s Thirdparty Host SMU(s) "
                        "is/are not present in the repository.\n" % 
                        len(invalid_tp_host_rpm)) 
            map(lambda rpm_inst: logger.info("\t-->%s" % rpm_inst.file_name), 
                invalid_tp_host_rpm)
            rc = -1
        if len(invalid_tp_admin_rpm):
            logger.info("\nBase rpm(s) of following %d Thirdparty Sysadmin SMU(s) "
                        "is/are not present in the repository.\n" % 
                        len(invalid_tp_admin_rpm)) 
            map(lambda rpm_inst: logger.info("\t-->%s" % rpm_inst.file_name), 
                invalid_tp_admin_rpm)
            rc = -1
        if len(invalid_tp_xr_rpm):
            logger.info("\nBase rpm(s) of following %d Thirdparty Xr SMU(s) "
                        "is/are not present in the repository.\n" % 
                        len(invalid_tp_xr_rpm)) 
            map(lambda rpm_inst: logger.info("\t-->%s" % rpm_inst.file_name), 
                invalid_tp_xr_rpm)
            rc = -1

        if rc != 0:
            logger.error("\nError: Thirdparty SMU(s) always released along with base rpm \n"
                         "Please provide base rpm of above Thirdparty SMU(s) in \n"
                         "repository and retry")
            logger.info("\nGolden ISO build process Exited due to above reason") 
            sys.exit(-1)

        self.check_all_tp_duplicate_smu(valid_tp_host_rpm, valid_tp_admin_rpm, 
                                        valid_tp_xr_rpm)

        invalid_tp_rpm_list = (set(self.tp_rpm_list) - (valid_tp_host_rpm |
                                                        valid_tp_admin_rpm |
                                                        valid_tp_xr_rpm))

        self.tp_rpm_list = list(set(self.tp_rpm_list) - invalid_tp_rpm_list)
        self.tp_rpm_count = len(self.tp_rpm_list)
        self.rpm_list = list(set(self.rpm_list) - invalid_tp_rpm_list)

        if invalid_tp_rpm_list:
            logger.info("Skipping following %s Thirdparty RPM(s) not supported\n" 
                        "for release %s:\n" % 
                        (len(invalid_tp_rpm_list), iso_version))
            map(lambda rpm_inst: logger.info("\t\t(-) %s" % rpm_inst.file_name), 
                invalid_tp_rpm_list)
            logger.info("If any of the above %s RPM(s) needed for Golden ISO then\n"
                        "provide RPM(s) supported for release %s" % 
                        (len(invalid_tp_rpm_list), iso_version))

        logger.debug('Found %s TP RPMs' % self.tp_rpm_count)
        map(lambda rpm_inst: logger.debug("\t\t%s" % rpm_inst.file_name), 
            self.tp_rpm_list)

    def filter_hostos_spirit_boot_base_rpms(self, platform):
        all_hostos_base_rpms = filter(lambda x: x.is_hostos_rpm(platform) and
                                      x.package_type.upper() != SMU_SUBSTRING,
                                      self.csc_rpm_list)
        all_spirit_boot_base_rpms = filter(lambda x: x.is_spiritboot() and 
                                           x.package_type.upper() != SMU_SUBSTRING,
                                           self.csc_rpm_list)

        if len(all_hostos_base_rpms):
            logger.info("\nSkipping following host os base rpm(s) "
                        "from repository:\n")
            for rpm in all_hostos_base_rpms:	
                logger.info("\t(-) %s" % rpm.file_name)

        map(self.csc_rpm_list.remove, all_hostos_base_rpms)
        map(self.rpm_list.remove, all_hostos_base_rpms)

        if len(all_spirit_boot_base_rpms):
            logger.info("\nSkipping following spirit-boot base rpm(s) "
                        "from repository:\n")
            for rpm in all_spirit_boot_base_rpms:	
                logger.info("\t(-) %s" % rpm.file_name)
        map(self.csc_rpm_list.remove, all_spirit_boot_base_rpms)
        map(self.rpm_list.remove, all_spirit_boot_base_rpms)

    def validate_associate_hostos_rpms(self, all_hostos_rpms):
        for rpm in all_hostos_rpms:
            associate_rpm_present = False
            if rpm.vm_type.upper() == HOST_SUBSTRING:
                asso_rel = rpm.release.replace(HOST_SUBSTRING.lower(), ADMIN_SUBSTRING.lower())
                associate_rpm = '%s-%s-%s.%s.%s' % (rpm.name, rpm.version, asso_rel, rpm.arch, "rpm")
                for rpm1 in all_hostos_rpms:
                    if rpm1.file_name == associate_rpm:
                        associate_rpm_present = True
                        break
                if not associate_rpm_present:
                    logger.error("Error: Hostos rpms are used together for host and syadmin vm")
                    logger.error("Error: Missing hostos rpm for syadamin is %s" % (associate_rpm))
                    sys.exit(-1)
                else:
                    break
        for rpm in all_hostos_rpms:
            associate_rpm_present = False
            if rpm.vm_type.upper() == CALVADOS_SUBSTRING:
                asso_rel = rpm.release.replace(ADMIN_SUBSTRING.lower(), HOST_SUBSTRING.lower())
                associate_rpm = '%s-%s-%s.%s.%s' % (rpm.name, rpm.version, asso_rel, rpm.arch, "rpm")
                for rpm1 in all_hostos_rpms:
                    if rpm1.file_name == associate_rpm:
                        associate_rpm_present = True
                        break
                if not associate_rpm_present:
                    logger.error("Error: Hostos rpms are used together for host and syadmin vm")
                    logger.error("Error: Missing hostos rpm for host is %s" % (associate_rpm))
                    sys.exit(-1)
                else:
                    break

    @staticmethod
    def rpm_version_string_cmp(rpm1, rpm2):
        if (not rpm1) and (not rpm2):
            return 0
        ilist1 = map(int, rpm1.version.split('.'))
        ilist2 = map(int, rpm2.version.split('.'))
        if ilist1 > ilist2:
            return -1
        elif ilist1 < ilist2:
            return 1
        else:
            return 0

    def filter_multiple_hostos_spirit_boot_rpms(self, platform):
        self.filter_hostos_spirit_boot_base_rpms(platform)

        all_hostos_rpms = filter(lambda x: x.is_hostos_rpm(platform), 
                                 self.csc_rpm_list)
        all_spirit_boot_rpms = filter(lambda x: x.is_spiritboot(), 
                                      self.csc_rpm_list)

        self.validate_associate_hostos_rpms(all_hostos_rpms)
 
        sorted_hostos_rpms = \
            sorted(all_hostos_rpms,   
                   key=functools.cmp_to_key(Rpmdb.rpm_version_string_cmp))
        discarded_hostos_rpms = \
            filter(lambda x: sorted_hostos_rpms[0].version != x.version, 
                   sorted_hostos_rpms)

        if len(discarded_hostos_rpms):
            logger.info("\nSkipping following older version of host os rpm(s) from repository:\n")
            for rpm in discarded_hostos_rpms:	
                logger.info("\t(-) %s" % rpm.file_name)

        map(self.csc_rpm_list.remove, discarded_hostos_rpms)
        map(self.rpm_list.remove, discarded_hostos_rpms)

        sorted_spiritboot = \
            sorted(all_spirit_boot_rpms,
                   key=functools.cmp_to_key(Rpmdb.rpm_version_string_cmp))
        discarded_spiritboot_rpms = \
            filter(lambda x: sorted_spiritboot[0].version != x.version, 
                   sorted_spiritboot)

        if len(discarded_spiritboot_rpms):
            logger.info("\nSkipping following older version of spirit-boot rpm(s) from repository:\n")
            for rpm in discarded_spiritboot_rpms:	
                logger.info("\t(-) %s" % rpm.file_name)
        map(self.csc_rpm_list.remove, discarded_spiritboot_rpms)
        map(self.rpm_list.remove, discarded_spiritboot_rpms)
            
    #
    # Group Cisco rpms based on VM_type and Architecture
    # {"HOST":{},"CALVADOS":{},"XR":{}}
    #
    def group_cisco_rpms_by_vm_arch(self):
        for rpm in self.csc_rpm_list:
            arch_rpms = self.csc_rpms_by_vm_arch[rpm.vm_type.upper()]
            if not (rpm.arch in arch_rpms.keys()):
                arch_rpms[rpm.arch] = [rpm]
            else:
                arch_rpms[rpm.arch].append(rpm)
    #
    # Group ThirdParty rpms based on VM_type and Architecture
    # {"HOST":{},"CALVADOS":{},"XR":{}}
    #

    def group_tp_rpms_by_vm_arch(self):
        for rpm in self.tp_rpm_list:
            arch_rpms = self.tp_rpms_by_vm_arch[rpm.vm_type.upper()]
            if not (rpm.arch in arch_rpms.keys()):
                arch_rpms[rpm.arch] = [rpm]
            else:
                arch_rpms[rpm.arch].append(rpm)
    #########################################
    # Getter api's
    #########################################

    def get_repo_path(self):
        return self.repo_path

    def get_cisco_rpm_list(self):
        return self.csc_rpm_list

    def get_tp_rpm_list(self):
        return self.tp_rpm_list

    def get_cisco_rpm_count(self):
        return self.csc_rpm_count

    def get_tp_rpm_count(self):
        return self.tp_rpm_count

    def get_abs_rpm_file_path(self, rpm):
        return "%s/%s" % (self.repo_path, rpm.file_name)

    def get_tp_rpms_by_vm_arch(self, vm_type, arch):
        if not (vm_type in self.tp_rpms_by_vm_arch.keys()):
            return []
        if not (arch in self.tp_rpms_by_vm_arch[vm_type].keys()):
            return []
        return self.tp_rpms_by_vm_arch[vm_type][arch]

    def get_cisco_rpms_by_vm_arch(self, vm_type, arch):
        if not (vm_type in self.csc_rpms_by_vm_arch.keys()):
            return []
        if not (arch in self.csc_rpms_by_vm_arch[vm_type].keys()):
            return []
        return self.csc_rpms_by_vm_arch[vm_type][arch] 

    #
    # In case of multi architecture, 
    # Rpms of all architecture should be present.
    # get_missing_arch_rpm() will return list of rpms 
    # missing for each architecture
    #
    def get_missing_arch_rpm(self, vm_type, supp_arch):
        missing_cisco_rpm_list = {}
        missing_tp_rpm_list = {}
        temp_missing_tp_rpm_list = {} 
        missing_rpm_list = {}
        arch_rpm_name_version = {}
        all_rpms = []
        platform_key = 'platform'

        for arch in supp_arch:
            arch_rpm_name_version[arch] = []
            for rpm2 in self.get_cisco_rpms_by_vm_arch(vm_type, arch):
                arch_rpm_name_version[arch].append("%s-%s-%s"
                                                   % (rpm2.name, rpm2.version, 
                                                      rpm2.release))
            all_rpms.extend(arch_rpm_name_version[arch])
        all_rpms = list(set(all_rpms))
        for arch in supp_arch:
            missing_cisco_rpm_list[arch] = list(set(all_rpms) - 
                                          set(arch_rpm_name_version[arch]))

        all_rpms = []
        arch_rpm_name_version = {}
        for arch in supp_arch:
            arch_rpm_name_version[arch] = []
            for rpm2 in self.get_tp_rpms_by_vm_arch(vm_type, arch):
                arch_rpm_name_version[arch].append("%s-%s-%s"
                                                   % (rpm2.name, rpm2.version, 
                                                      rpm2.release))
            all_rpms.extend(arch_rpm_name_version[arch])
        all_rpms = list(set(all_rpms))
        for arch in supp_arch:
            missing_tp_rpm_list[arch] = list(set(all_rpms) - 
                                          set(arch_rpm_name_version[arch]))
            temp_missing_tp_rpm_list[arch] = missing_tp_rpm_list[arch][:]  

        # tp rpms may be released for only one arch card. so need to validate
        # from sdk metadata whether its a real missing or virtual mising
        for arch in supp_arch:
            for rpm_nvr in temp_missing_tp_rpm_list[arch]:
                mre = re.search(r'(.*)-(.*)-(.*)', rpm_nvr)
                rpm_name = "%s.%s.%s" % (rpm_nvr, arch, "rpm")
                if mre:
                    tp_rpm_name = mre.groups()[0]
                    tp_rpm_ver = mre.groups()[1]
                    tp_rpm_rel = mre.groups()[2]
                    tp_rpm_arch = arch 
                    if tp_rpm_rel.upper().endswith(ADMIN_SUBSTRING):
                        base_rpm = self.get_tp_base_rpm(platform_key, 
                                                        ADMIN_SUBSTRING,
                                                        rpm_name)
                        if base_rpm is None:
                            logger.debug("Admin tp rpm %s is invalid\n" % rpm_name) 
                            missing_tp_rpm_list[arch].remove(rpm_nvr)

                    if tp_rpm_rel.upper().endswith(HOST_SUBSTRING):
                        base_rpm = self.get_tp_base_rpm(platform_key, 
                                                        HOST_SUBSTRING,
                                                        rpm_name)
                        if base_rpm is None:
                            logger.debug("Host tp rpm %s is invalid\n" % rpm_name) 
                            missing_tp_rpm_list[arch].remove(rpm_nvr)
      
        for arch in supp_arch:
            missing_rpm_list[arch] = list(set(missing_cisco_rpm_list[arch]) | 
                                          set(missing_tp_rpm_list[arch]))
        return missing_rpm_list

def system_resourse_check():
    rc = 0
    tools = ['mount', 'rm', 'cp', 'umount', 'zcat', 'chroot', 'mkisofs']
    logger.debug("\nPerforming System requirements check...")

    if sys.version_info < (2, 7):
        logger.error("Error: Must use python version 2.7")
        sys.exit(-1)
        
    disk = os.statvfs(cwd)
    total_avail_space = float(disk.f_bavail*disk.f_frsize)
    total_avail_space_gb = total_avail_space/1024/1024/1024

    if total_avail_space_gb < MIN_DISK_SPACE_SIZE_REQUIRED:
        logger.error("Minimum %s GB of free disk space is required "
                     "for building Golden ISO." % MIN_DISK_SPACE_SIZE_REQUIRED)
        logger.error("Error: %s GB free disk space available in %s" % 
                     (str(total_avail_space_gb), cwd))
        sys.exit(-1)
    for tool in tools:
        try:
            run_cmd("which %s" % tool)
        except Exception:
            exc_info = sys.exc_info()
            logger.debug("TB:", exc_info=True)
            print ("\n", "Exception:", exc_info[0], exc_info[1])
            logger.error("\tError: Tool %s not found." % tool)
            rc = -1
            
    if rc != 0:
        logger.error("\tFailed to find tools, Check PATH Env variable or "
                     "install required tools.")
        # logger.debug("\t...System requirements check [FAIL]")
        logger.error("\nError: System requirements check [FAIL]")
        sys.exit(-1)

    elif os.getuid() != 0:
        logger.error("\nError: User does not have root priviledges")
        sys.exit(-1)

    else:
        # logger.info("\t...System requirements check [PASS]")
        logger.info("\nSystem requirements check [PASS]")
        
     
class Iso(object):
    ISO_INFO_FILE = "iso_info.txt"
    ISO_INITRD_RPATH = "/boot/initrd.img"
    RPM_TEST_LOG = "/tmp/rpmtest.log"
    RPM_OPTIONS = " rpm -i --test --noscripts "
    GRUB_FILES = ["boot/grub2/grub-usb.cfg", "boot/grub2/grub.cfg"]

    def __init__(self):
        self.iso_name = None
        self.iso_path = None
        self.iso_version = None
        self.iso_mount_path = None
        self.iso_rpms = None
        self.iso_extract_path = None
        self.iso_platform_name = None

    def set_iso_info(self, iso_path):
        if os.system("losetup -f &> /dev/null") != 0:
            logger.error("No free loop device available for mouting ISO")
            sys.exit(-1)
          
        pwd = cwd
        self.iso_path = iso_path
        self.iso_mount_path = tempfile.mkdtemp(dir=pwd)      
        run_cmd("mount -o loop %s %s" % (self.iso_path, self.iso_mount_path))
        iso_info_file = open("%s/%s" % (self.iso_mount_path, Iso.ISO_INFO_FILE),
                             'r')
        iso_info_raw = iso_info_file.read()
        self.iso_name = iso_info_raw[iso_info_raw.find("Name:"):].split(" ")[1]
        self.iso_platform_name = self.iso_name.split("-")[0] 
        self.iso_version = \
            iso_info_raw[iso_info_raw.find("Version:"):].split(" ")[1]
        self.iso_rpms = glob.glob('%s/rpm/*/*' % self.iso_mount_path)
        iso_info_file.close()

    # Iso getter apis
    def get_iso_name(self):
        return self.iso_name

    def get_iso_version(self):
        return self.iso_version

    def get_iso_platform_name(self):
        return self.iso_platform_name

    def get_iso_rpms(self):
        return self.iso_rpms

    def get_iso_mount_path(self):
        return self.iso_mount_path

    def get_iso_extract_path(self):
        if self.iso_extract_path is not None:
            return self.iso_extract_path 
        else:
            pwd = cwd
            self.iso_extract_path = tempfile.mkdtemp(dir=pwd)
            if self.iso_extract_path is not None:
                os.chdir(self.iso_extract_path)
                run_cmd("zcat -f %s%s | cpio -id" % (self.iso_mount_path,
                        Iso.ISO_INITRD_RPATH))
                os.chdir(pwd)
            else:
                logger.error("Error: Couldn't create directory for extarcting initrd")
                sys.exit(-1)
        run_cmd('touch %s/etc/mtab' % self.iso_extract_path)
        logger.debug("ISO %s extract path %s" % (self.iso_name, 
                                                 self.iso_extract_path))
        return self.iso_extract_path

    def do_compat_check(self, repo_path, input_rpms):
        rpm_file_list = ""
        if self.iso_extract_path is None:
            self.get_iso_extract_path()
        rpm_staging_dir = "%s/rpms/" % self.iso_extract_path
        os.mkdir(rpm_staging_dir)
        input_rpms_set = set(input_rpms)
        iso_rpms_set = set(map(os.path.basename, self.iso_rpms))
        logger.debug("ISO RPMS:")
        map(logger.debug, iso_rpms_set)

        dup_input_rpms_set = input_rpms_set & iso_rpms_set
        # TBD Detect dup input rpms based on provides info of base iso pkgs
        input_rpms_unique = input_rpms_set - dup_input_rpms_set
        all_rpms = map(lambda x: "%s/%s" % (repo_path, x), 
                       input_rpms_unique) + self.iso_rpms
        all_rpms = list(set(all_rpms))

        for rpm in all_rpms:
            shutil.copy(rpm, rpm_staging_dir)
            rpm_file_list = "%s/rpms/%s  " % (rpm_file_list, 
                                              os.path.basename(rpm))
        try:
            run_cmd("chroot %s %s %s" % (self.iso_extract_path, Iso.RPM_OPTIONS,
                    rpm_file_list))
        except Exception as e:
            errstr = str(e).split("--->")
            logger.debug(errstr[0])
            errstr = errstr[1]
            rpm_log_data = errstr.split("\n")
            err_log = []
            for line in rpm_log_data:
                logger.debug('%s' % line)
                if re.match('.*Failed dependencies.*', line):
                    continue
                elif re.match('(\s*/)', line) or (not line):
                    logger.debug("Ignoring false dependancy")
                    continue
                # Fretta hack for netbase false dependeancy
                elif 'netbase' in line:
                    logger.debug("Ignoring false dependancy")
                    continue
                else: 
                    err_log.append(line)
            if len(err_log) != 0:
                logger.error("Error: ")
                logger.error('\n'.join(err_log))
                return False, list(dup_input_rpms_set)
        return True, list(dup_input_rpms_set)

    def __enter__(self):
        return self

    def __exit__(self, type_name, value, tb):
        try:
            logger.debug("Cleaning Iso")
            if self.iso_extract_path and os.path.exists(self.iso_extract_path):
                logger.debug("iso extract path %s" % self.iso_extract_path)
                shutil.rmtree(self.iso_extract_path)
            if self.iso_mount_path and os.path.exists(self.iso_mount_path):
                if os.path.ismount(self.iso_mount_path):
                    run_cmd(" umount " + self.iso_mount_path)
                    logger.debug("Unmounted iso successfully %s" % 
                                 self.iso_mount_path)
                shutil.rmtree(self.iso_mount_path)
        except (IOError, os.error) as why:
            logger.error("Exception why ? = " + str(why))


class Giso:
    SUPPORTED_PLATFORMS = ["asr9k", "ncs1k", "ncs5k", "ncs5500"]
    SUPPORTED_BASE_ISO = ["mini", "minik9"]
    SMU_CONFIG_SUMMARY_FILE = "giso_summary.txt"
    VM_TYPE = ["XR", "CALVADOS", "HOST"]
    XR_CONFIG_FILE_NAME = "router.cfg"
    GOLDEN_STRING = "golden"
    GOLDEN_K9_STRING = "goldenk9"
    GISO_INFO_TXT = "giso_info.txt"

    def __init__(self):
        self.repo_path = None
        self.bundle_iso = None
        self.vm_iso = {"XR": None, "CALVADOS": None, "HOST": None}
        self.giso_dir = None
        self.vm_rpm_file_paths = {"XR": None, "CALVADOS": None, "HOST": None}
        self.xrconfig = None
        self.system_image = None
        self.supp_archs = {'HOST': ['x86_64'], 'CALVADOS': ['x86_64'],
                           'XR': ['x86_64']}
        self.giso_name = None
        self.k9sec_present = False
        self.giso_ver_label = 0 
        self.is_tar_require = False
    #
    # Giso object Setter Api's
    #

    def set_giso_info(self, iso_path):
        self.bundle_iso = Iso() 
        self.bundle_iso.set_iso_info(iso_path)
        plat = self.get_bundle_iso_platform_name()
        if "ncs5500" in plat:
            logger.debug("Skipping the top level iso wrapper")
            iso_wrapper_fsroot = self.get_bundle_iso_extract_path()
            logger.debug("Iso top initrd path %s" % iso_wrapper_fsroot)
            self.system_image = "%s/system_image.iso" % cwd
            shutil.copyfile("%s/iso/system_image.iso" % iso_wrapper_fsroot,
                            self.system_image)
            logger.debug("Intermal System_image.iso %s"
                         % iso_path)
            self.bundle_iso.__exit__(None, None, None)
            self.bundle_iso = Iso() 
            self.bundle_iso.set_iso_info(self.system_image)
            
    def set_vm_rpm_file_paths(self, rpm_file_paths, vm_type):
        self.vm_rpm_file_paths[vm_type] = rpm_file_paths
        
    def set_xrconfig(self, xrconfig):
        self.xrconfig = xrconfig

    def set_repo_path(self, repo_path):
        self.repo_path = repo_path

    def set_giso_ver_label(self, ver_label):
        self.giso_ver_label = ver_label 

    @staticmethod
    def is_platform_supported(platform):
        try:
            Giso.SUPPORTED_PLATFORMS.index(platform)
            return True
        except:
            return False

    def is_bundle_image_type_supported(self):
        for sup_iso_type in Giso.SUPPORTED_BASE_ISO:
            if self.bundle_iso.iso_name.find(sup_iso_type) != -1:
                return True
        return False
    
    #
    # Giso object getter Api's
    #
    def get_bundle_iso_name(self):
        return self.bundle_iso.get_iso_name()

    def get_bundle_iso_version(self):
        return self.bundle_iso.get_iso_version()

    def get_bundle_iso_platform_name(self):
        return self.bundle_iso.get_iso_platform_name()

    def get_bundle_iso_extract_path(self):
        return self.bundle_iso.get_iso_extract_path()

    def get_bundle_iso_mount_path(self):
        return self.bundle_iso.get_iso_mount_path()

    def get_supp_arch(self, vm_type):
        if self.vm_iso['HOST'] is None:
            iso = Iso()
            vm_type_iso_file = self.get_vm_type_iso_file('HOST')
            iso.set_iso_info(vm_type_iso_file)
            self.vm_iso['HOST'] = iso
            fs_root = iso.get_iso_extract_path()
            bootstrap_file = \
                "%s/"\
                "/etc/rc.d/init.d/cisco-instance/fretta/calvados_bootstrap.cfg"\
                % fs_root
            search_str = ''
            if os.path.exists(bootstrap_file):
                for x in self.supp_archs.keys():
                    if "XR" in x:
                        search_str = "XR_SUPPORTED_ARCHS"
                    if "HOST" in x or "CALVADOS" in x:
                        search_str = "CALV_SUPPORTED_ARCHS"
                    try:
                        result = run_cmd("grep %s %s" % (search_str, 
                                                         bootstrap_file))
                        self.supp_archs[x] = \
                            map(lambda y: y.replace('\n', ''),
                                result['output'].split('=')[1].split(','))
                        logger.debug('vm_type %s Supp Archs: ' % x)
                        map(lambda y: logger.debug("%s" % y), self.supp_archs[x])
                    except Exception as e:
                        logger.debug(str(e))
            else:
                logger.debug("Failed to find %s file. Using Defaults archs" % 
                             bootstrap_file)
                
        logger.debug("Supp arch query for vm_type %s" % vm_type)
        map(lambda y: logger.debug("%s" % y), self.supp_archs[vm_type])
        return self.supp_archs[vm_type]

    @staticmethod
    def get_rp_arch():
        return 'x86_64'
    #
    # Pefrom compatability Check on input RPMS.
    # Returns True if RPM dependancies are met.
    # Returns False if RPM dependancies not met.
    #

    def do_compat_check(self, input_rpms, vm_type):
        if self.vm_iso[vm_type] is None:
            iso = Iso()
            vm_type_iso_file = self.get_vm_type_iso_file(vm_type)
            iso.set_iso_info(vm_type_iso_file)
            self.vm_iso[vm_type] = iso
        else:
            iso = self.vm_iso[vm_type]
        return iso.do_compat_check(self.repo_path, input_rpms)

    def get_vm_type_iso_file(self, vm_type):
        iso_file_names = glob.glob('%s/iso/*' % 
                                   (self.get_bundle_iso_extract_path()))
        vm_type_iso_file = ''
        # Name of the ISO doesnt match calvados vm_type
        # Hence search SYSADMIN ISO name for calvados vm_type.
        iso_name = "SYSADMIN.ISO" if vm_type == "CALVADOS" \
                   else vm_type + '.ISO'
        for iso_file in iso_file_names:
            vm_type_iso_file = \
                iso_file if iso_name in os.path.basename(iso_file).upper() \
                else None            
            if vm_type_iso_file is not None:
                break
        logger.debug("ISO  %s vm_type %s searchkey %s"
                     % (vm_type_iso_file, vm_type, iso_name))
        if vm_type_iso_file is None:
            return -1  # raise
        else:
            return vm_type_iso_file

    def prepare_giso_info_txt(self, iso):
        iso_name = iso.get_iso_name()

        if "-minik9-" in iso_name or self.k9sec_present:
            golden_string = Giso.GOLDEN_K9_STRING
        elif "-mini-" in iso_name:
            golden_string = Giso.GOLDEN_STRING
        else:
            logger.info("Given iso(%s.%s) is not supported" % (iso_name, "iso"))
            return -1

        iso_name_tupple = iso_name.split('-')
        giso_name_string = '%s-%s-%s' % (iso_name_tupple[0], golden_string,
                                         iso_name_tupple[2])

        # update iso_info.txt file with giso name
        with open("%s/%s" % (self.giso_dir, iso.ISO_INFO_FILE), 'r') as f:
            iso_info_raw = f.read()

        # Replace the iso name with giso string
        iso_info_raw = iso_info_raw.replace(iso_name, giso_name_string)

        with open("%s/%s" % (self.giso_dir, iso.ISO_INFO_FILE), 'w') as f:
            f.write(iso_info_raw)

        giso_pkg_fmt_ver = GISO_PKG_FMT_VER
        name = giso_name_string
        version = '%s.%s' % (iso.get_iso_version(), self.giso_ver_label)
        built_by = getpass.getuser()
        built_on = datetime.now().strftime("%a %b %d %H:%M:%S")
        built_host = socket.gethostname()
        workspace = os.getcwd()
        giso_info = '%s: %s\n%s: %s\n%s: %s\n%s: %s\n%s: %s\n%s: %s\n%s: %s\n'\
                    % ("GISO_PKG_FMT_VER", giso_pkg_fmt_ver, "Name", name,
                       "Version", version, "Built By", built_by,
                       "Built On", built_on, "Build Host", built_host,
                       "Workspace", workspace)

        file_yaml = "%s/%s"%(self.giso_dir, "iosxr_image_mdata.yml")        
        fd = open(file_yaml, 'r')
        mdata = {}
        mdata = yaml.load(fd)
        fd.close()

        with open("%s/%s" % (self.giso_dir, Giso.GISO_INFO_TXT), 'w') as f:
            f.write(giso_info)
            rpms_list = []
            for vm_type in Giso.VM_TYPE:
                vm_type_meta = vm_type.lower()
                rpm_files = self.vm_rpm_file_paths[vm_type]
                if rpm_files is not None:
                    f.write("\n\n%s rpms:\n" % vm_type)
                    f.write('\n'.join(rpm_files))
                    tmp_dict = {}
                    if vm_type_meta.upper() == CALVADOS_SUBSTRING:
                        vm_type_meta = SYSADMIN_SUBSTRING.lower()
                    tmp_dict['%s rpms in golden ISO'%(vm_type_meta)] = ' '.join(rpm_files)
                    rpms_list.append(tmp_dict)

        iso_mdata = mdata['iso_mdata']
        iso_mdata['name'] = "%s-%s"%(giso_name_string, iso.get_iso_version())
        iso_mdata['bundle_name'] = "%s-%s"%(iso_name, iso.get_iso_version())
        iso_mdata['label'] = self.giso_ver_label
        mdata['iso_mdata'] = iso_mdata
        mdata['golden ISO rpms'] = rpms_list
        fd = open(file_yaml, 'w')
        fd.write(yaml.dump(mdata, default_flow_style=False))
        fd.close()

        self.giso_name = '%s.%s-%s.%s' % (giso_name_string, "iso",
                                          iso.get_iso_version(), 
                                          self.giso_ver_label)

    def update_grub_cfg(self, iso):
        # update grub.cfg file with giso_boot parameter 
        lines = []
        for file in iso.GRUB_FILES:
            with open("%s/%s" % (self.giso_dir, file), 'r') as fd:
                for line in fd:
                    if "root=" in line and "noissu" in line:
                        line = line.rstrip('\n') + " giso_boot\n"
                    lines.append(line)

            # write updated grub.cfg
            with open("%s/%s" % (self.giso_dir, file), 'w') as fd:
                for line in lines:
                    fd.write(line)
        
    #
    # Build Golden ISO.
    #

    def build_giso(self, iso_path):
        rpms = False
        config = False 
        pwd = cwd
        rpm_count = 0
        self.giso_dir = "%s/giso_files_dir" % pwd
        if os.path.exists(self.giso_dir):
            shutil.rmtree(self.giso_dir)
        os.chdir(pwd)

        # ncs5500 iso structure is slightly different than other exr platform 
        # In case of ncs5500 complete iso is stored in initrd as system_image.iso
        # for the purpose of internal pxe. Individual vm(host, calvados, xr) isos 
        # are present in the initrd of system_image.iso. For compatibilty 
        # checking individual iso were used by this tool, but for building GISO 
        # outer iso would be used as place holder. So here we exited from 
        # earlier mounted internal system_image.iso and setting the new mount 
        # path as outer iso mount point
        if "ncs5500" in self.get_bundle_iso_platform_name():
            self.bundle_iso.__exit__(None, None, None)
            self.bundle_iso = Iso() 
            self.bundle_iso.set_iso_info(iso_path)

        shutil.copytree(self.bundle_iso.get_iso_mount_path(), self.giso_dir)

        logger.info("Summary .....")
        for vm_type in Giso.VM_TYPE:
            rpm_files = self.vm_rpm_file_paths[vm_type]
            if rpm_files is not None:
                # if rpm_files and (len(rpm_files) != 0):
                giso_repo_path = "%s/%s_rpms" % (self.giso_dir, 
                                                 str(vm_type).lower())
                os.mkdir(giso_repo_path)
                if vm_type == CALVADOS_SUBSTRING:
                    vm_type = SYSADMIN_SUBSTRING
                logger.info("\n%s rpms:" % vm_type)

                for rpm_file in rpm_files:
                    rpm_count += 1
                    shutil.copy('%s/%s' % (self.repo_path, rpm_file),
                                giso_repo_path)
                    logger.info('\t%s' % (os.path.basename(rpm_file)))
                    rpms = True
                    if "-k9sec-" in rpm_file:
                        self.k9sec_present = True

        if rpm_count > MAX_RPM_SUPPORTED_BY_INSTALL:
            logger.error("\nError: Total number of supported rpms in the "
                         "repository is %s.\nIt is exceeding the number "
                         "of rpms supported by install infra.\nPlease remove "
                         "some rpms and make sure total number doesn't exceed "
                         "%s" % (rpm_count, MAX_RPM_SUPPORTED_BY_INSTALL))
            sys.exit(-1)

        if self.xrconfig:
            logger.info("\nXR Config file:")
            logger.info('\t%s' % Giso.XR_CONFIG_FILE_NAME)
            shutil.copy(self.xrconfig, "%s/%s" % (self.giso_dir, 
                                                  Giso.XR_CONFIG_FILE_NAME))
            config = True

        if not (rpms or config):
            logger.info("Final rpm list is Zero and "
                        "there is no XR config specified")
            logger.info("Nothing to do")
            return -1
        else:
            self.prepare_giso_info_txt(self.bundle_iso)
            self.update_grub_cfg(self.bundle_iso)
            shutil.copy(logfile, '%s/%s' % (self.giso_dir, 
                                            Giso.SMU_CONFIG_SUMMARY_FILE))
            run_cmd('mkisofs -R -b boot/grub/stage2_eltorito -no-emul-boot \
                    -boot-load-size 4 -boot-info-table -o %s %s'
                    % (self.giso_name, self.giso_dir))
        return 0
            
    def __enter__(self):
        return self

    def __exit__(self, type_name, value, tb):
        if (self and self.giso_dir) and os.path.exists(self.giso_dir):
            shutil.rmtree(self.giso_dir)
        for vm_type in Giso.VM_TYPE:
            if self.vm_iso[vm_type]:
                self.vm_iso[vm_type].__exit__(type, value, tb)
        if self.bundle_iso:
            self.bundle_iso.__exit__(type, value, tb)
            if self.system_image and os.path.exists(self.system_image):
                os.remove(self.system_image)

         
def parsecli():
    parser = argparse.ArgumentParser(description="Utility to build \
                                                  Golden/Custom iso. \
                                                  Please provide atleast \
                                                  repo path or config file \
                                                  along with bundle iso")

    mandatory_args = parser.add_argument_group('required arguments')
    mandatory_args.add_argument('-i', '--iso', dest='bundle_iso', type=str,
                                required=True, action='append',
                                help='Path to Mini.iso/Full.iso file')
    parser.add_argument('-r', '--repo', dest='rpmRepo', type=str,
                        required=False, action='append',
                        help='Path to RPM repository')

    parser.add_argument('-c', '--xrconfig', dest='xrConfig', type=str,
                        required=False, action='append',
                        help='Path to XR config file')
    parser.add_argument('-l', '--label', dest='gisoLabel', type=str,
                        required=False, action='append',
                        help='Golden ISO Label')
    parser.add_argument('-m', '--migration', dest='migTar', action='store_true',
                        help='To build Migration tar only for ASR9k')
    version_string = "%%(prog)s (version %s)" %(__version__)
    parser.add_argument('-v', '--version', 
                        action='version',                    
                        help='Print version of this script and exit',
                        version=version_string)

    pargs = parser.parse_args()

    if len(pargs.bundle_iso) > 1:
        logger.error('Error: Multiple isos are given.')
        logger.error('Info : Please provide unique iso.')
        sys.exit(-1)
    elif not os.path.isfile(pargs.bundle_iso[0]):
        logger.error('Error: ISO File %s not found.' % pargs.bundle_iso[0])
        sys.exit(-1)
    else:
        result = run_cmd("file %s" % pargs.bundle_iso[0])
        if result["output"].find("ISO") == -1:
            logger.error("Error: File %s is not ISO file." % pargs.bundle_iso[0])
            sys.exit(-1)
    if not pargs.xrConfig:
        logger.debug('Info: XR Congifuration file not specified.')
        logger.debug('Info: Golden ISO will not have XR configuration file')
    elif len(pargs.xrConfig) > 1:
        logger.error('Error: Multiple xr config files are given.')
        logger.error('Info : Please provide unique xr config file.')
        sys.exit(-1)
    elif not os.path.isfile(pargs.xrConfig[0]):
        logger.error('Error: XR Configuration File %s not found.' % 
                     pargs.xrConfig[0])
        sys.exit(-1)
    if not pargs.rpmRepo:
        logger.info('Info: RPM repository path not specified.')
        logger.info('Info: No additional rpms will be included.')
    elif len(pargs.rpmRepo) > 1:
        logger.error('Error: Multiple rpm repo paths are given.')
        logger.error('Info : Please provide unique rpm repo path.')
        sys.exit(-1)
    elif not os.path.isdir(pargs.rpmRepo[0]):
        logger.error('Error: RPM respotiry path %s not found' % pargs.rpmRepo[0])
        sys.exit(-1)
    if (not pargs.xrConfig) and (not pargs.rpmRepo):
        logger.error('Info: Nothing to be done.')
        logger.error('Info: RPM repository path and/or XR configuration file')
        logger.error('      should be provided to build Golden ISO\n')
        os.system(os.path.realpath(__file__))
        sys.exit(-1)
    if not pargs.gisoLabel:
        pargs.gisoLabel = 0
        logger.info('Info: Golden ISO label is not specified '
                    'so defaulting to 0')
    elif len(pargs.gisoLabel) > 1:
        logger.error('Error: Multiple Golden ISO labels are given.')
        logger.error('Info : Please provide unique Golden ISO label.')
        sys.exit(-1)
    elif  not  pargs.gisoLabel[0].isalnum():
        logger.error('Error: label %s contains characters other than alphanumeric', pargs.gisoLabel[0])
        logger.error('Info : Non-alphanumeric characters are not allowed in GISO label ')
        sys.exit(-1)

    return pargs


def main(argv):
    with Giso() as giso:
        giso.set_giso_info(argv.bundle_iso[0])
        logger.debug("\nFound Bundle ISO: %s" % 
                     (os.path.abspath(argv.bundle_iso[0])))
        logger.info("\nPlatform: %s Version: %s" % 
                    (giso.get_bundle_iso_platform_name(),
                     giso.get_bundle_iso_version()))
        #
        # 1.1 Perform Giso support prechecks
        #
        if not Giso.is_platform_supported(giso.get_bundle_iso_platform_name()):
            logger.error("Error: Golden ISO build is not supported for the "
                         "platform %s " % (giso.get_bundle_iso_platform_name()))
            return

        if not giso.is_bundle_image_type_supported():
            logger.error("Error: Image %s is neither mini.iso nor minik9.iso"
                         % (giso.get_bundle_iso_name()))
            logger.error("Only mini or minik9 image type "
                         "can be used to build Golden ISO")
            return

        #
        # 1.1.0 Check if migration option is provided for other platform than ASR9k
        #
        if argv.migTar and giso.get_bundle_iso_platform_name().upper() != "ASR9K": 
            logger.error("Error: Migration option is only applicable for ASR9k platform")
            sys.exit(-1)

        if argv.migTar:
            logger.info("\nInfo: Migration option is provided so migration tar will be generated")
            giso.is_tar_require = True
                
        #
        # 1.2 Scan for XR-Config file. 
        #
        if argv.xrConfig and os.path.isfile(argv.xrConfig[0]) is True:
            logger.info("\nXR-Config file (%s) will be encapsulated in Golden ISO." % 
                        (os.path.abspath(argv.xrConfig[0])))
            giso.set_xrconfig(argv.xrConfig[0])

        rpm_db = Rpmdb()
        fs_root = giso.get_bundle_iso_extract_path() 
        if argv.rpmRepo:

            # 1.3.1 Scan repository and build RPM data base.
            rpm_db.populate_rpmdb(fs_root, os.path.abspath(argv.rpmRepo[0]))

            # 1.3.2 Seperate Cisco and TP rpms in RPM data base
            rpm_db.populate_tp_cisco_list(giso.get_bundle_iso_platform_name())

            # 1.3.3 Filter and discard RPMs not matching desired Version 
            rpm_db.filter_cisco_rpms_by_release(giso.get_bundle_iso_version())

            # 1.3.4 Filter and discard RPMs not matching platform
            rpm_db.filter_cisco_rpms_by_platform(giso.get_bundle_iso_platform_name())
            
            # 1.3.5 Filter and discard TP RPM which are not part of release-file 
            rpm_db.filter_tp_rpms_by_release_rpm_list(
                giso.get_bundle_iso_mount_path(), giso.get_bundle_iso_version())

            # 1.3.6 Filter and discard older version HOSTOS RPMS
            rpm_db.filter_multiple_hostos_spirit_boot_rpms(
                giso.get_bundle_iso_platform_name())

            # 1.3.7 Group RPMS by vm_type and card architecture 
            # {"Host":{Arch:[rpm list]},"Cal":{Arch:[rpmlist]},
            #  "Xr":{Arch:[rpmlist]}} 
            rpm_db.group_cisco_rpms_by_vm_arch()
            rpm_db.group_tp_rpms_by_vm_arch()
            giso.set_repo_path(os.path.abspath(argv.rpmRepo[0]))

            # 1.4
            # Nothing to do if there is no xrconfig nor 
            # valid RPMs in RPM database
        if rpm_db.get_cisco_rpm_count() == 0:
            logger.info("Warning: No RPMS or Optional Matching %s packages "
                        "found in repository" % (giso.get_bundle_iso_version()))
            if not argv.xrConfig and rpm_db.get_tp_rpm_count() == 0:
                logger.info("Info: No Valid rpms nor XR config file found. "
                            "Nothing to do")
                return

        # 1.5 Compatability Check
        for vm_type in giso.VM_TYPE:
            supp_arch = giso.get_supp_arch(vm_type)
            dup_rpm_files = []
            final_rpm_files = []
            local_card_arch_files = []
            for arch in supp_arch:
                arch_rpm_files = map(lambda rpm: rpm.file_name,
                                     rpm_db.get_cisco_rpms_by_vm_arch(vm_type, 
                                                                      arch) +
                                     rpm_db.get_tp_rpms_by_vm_arch(vm_type, 
                                                                   arch))
                if arch_rpm_files:
                    if vm_type == CALVADOS_SUBSTRING:
                        vmtype = SYSADMIN_SUBSTRING
                    else:
                        vmtype = vm_type
                    logger.info("\nFollowing %s %s rpm(s) will be used for building Golden ISO:\n" % (vmtype, arch))
                    map(lambda file_name: logger.info("\t(+) %s" % file_name), 
                        arch_rpm_files)
                    final_rpm_files += arch_rpm_files 
                    if Giso.get_rp_arch() != arch:
                        continue
                    else:
                        local_card_arch_files = arch_rpm_files

            # 1.5.1 Scan for missing architecture rpms.
            #       Fretta for example supports x86_64 and Arm.
            #       So both arm and x86_64 rpms must be present in RPM database.
            # missing_arch_rpms = [[Arm rpm list][x86_54 rpm list]]
            missing = False
            missing_arch_rpms = rpm_db.get_missing_arch_rpm(vm_type, supp_arch)
            for arch in missing_arch_rpms.keys():
                map(lambda x: logger.error("\tError: Missing %s.%s.rpm" % 
                                           (x, arch)),
                    missing_arch_rpms[arch])
                if len(missing_arch_rpms[arch]):
                    missing = True
            if missing:
                logger.info("Add the missing rpms to repository and "
                            "retry building Golden ISO.")
                return

            #
            # 1.5.2   Perform Compatibilty check
            #
            if local_card_arch_files:
                result, dup_rpm_files = \
                    giso.do_compat_check(local_card_arch_files, vm_type)
                if result is False:
                    logger.error("\n\t...RPM compatibility check [FAIL]")
                    return
            #
            # 1.5.3 Remove rpms's from input list 
            #       that are already part of base iso
            #
            if dup_rpm_files:    
                logger.info("\nSkipping following rpms from repository "
                            "since they are already present in base ISO:\n")
                map(lambda file_name: logger.error("\t(-) %s" % file_name), 
                    dup_rpm_files)
                final_rpm_files = list(set(final_rpm_files) - 
                                       set(dup_rpm_files))
                # TBD Remove other arch rpms as well.

            if final_rpm_files:
                if dup_rpm_files:
                    logger.debug("\nFollowing updated %s rpm(s) will be used for building Golden ISO:\n" % vm_type)
                    map(lambda x: logger.debug('\t(+) %s' % x), final_rpm_files)
                giso.set_vm_rpm_file_paths(final_rpm_files, vm_type)
                logger.info("\n\t...RPM compatibility check [PASS]")

        if argv.gisoLabel: 
            giso.set_giso_ver_label(argv.gisoLabel[0])
#
#       2.0 Build Golden Iso
#
        logger.info('\nBuilding Golden ISO...')
        result = giso.build_giso(argv.bundle_iso[0])
        if not result:
            logger.info('\n\t...Golden ISO creation SUCCESS.') 
            logger.info('\nGolden ISO Image Location: %s/%s' % 
                        (cwd, giso.giso_name))
        
        if giso.is_tar_require: 
            with Migtar() as migtar:
                logger.info('\nBuilding Migration tar...')
                migtar.create_migration_tar(cwd, giso.giso_name)
                logger.info('\nMigration tar creation SUCCESS.') 
                logger.info('\nMigration tar Location: %s/%s' % 
                            (cwd, migtar.dst_system_tar))

if __name__ == "__main__":

    cwd = os.getcwd()
    logfile = '%s/Giso_build.log-%s' % \
              (cwd, datetime.now().strftime("%Y-%m-%d:%H:%M:%S.%f"))

    # create logger
    logger = logging.getLogger('Giso_build_logger')
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s::  %(message)s', 
                                  "%Y-%m-%d %H:%M:%S")

    # Console message
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    logger.addHandler(ch)

    # Logs to logfile
    fh = logging.FileHandler(logfile)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.debug("##############START#####################")
    try:
        args = parsecli()
        logger.info("Golden ISO build process starting...")
        system_resourse_check()
        main(args)
        logger.debug("Exiting normally")
        logger.info("\nDetail logs: %s" % logfile)
    except Exception:
        logger.debug("Exiting with exception")
        exc_info1 = sys.exc_info()
        logger.debug("TB:", exc_info=True)
        print ("\n", "Exception:", exc_info1[0], exc_info1[1])
        logger.info("Detail logs: %s" % logfile)
    except KeyboardInterrupt:
        logger.info("User interrupted\n")
        logger.info("Cleaning up and Exiting")
        logger.info("Detail logs: %s" % logfile)
        sys.exit(0)
    finally:
        logger.debug("################END#####################")
