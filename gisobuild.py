#! /usr/bin/env python
# =============================================================================
# gisobuild.py
#
# utility to build golden iso
#
# Copyright (c) 2015-2021 by Cisco Systems, Inc.
# All rights reserved.
# =============================================================================
from datetime import datetime
import subprocess
import argparse
import functools
import getpass
import glob
import logging
import os
import re
import shutil 
import socket
import sys
import tempfile
import yaml
import string
import stat
import pprint

__version__ = '0.38'
GISO_PKG_FMT_VER = 1.0

custom_mdata = {
                "SUPPCARDS" : '(none)',
                "VMTYPE": '(none)',
                "CISCOHW" : '(none)',
                "PACKAGETYPE" : '(none)',
                "PKGTYPE" : '(none)',
                "PACKAGEPRESENCE" : '(none)',
                "RESTARTTYPE" : '(none)',
                "INSTALLMETHOD" : '(none)',
                "XRVERSION" : '(none)',
                "XRRELEASE" : '(none)',
                "PARENTVERSION" : '(none)',
                "PIPD" : '(none)',
                "SKIPRELEASE" : '(none)',
                "CARDTYPE" : '(none)'
               }

try:
    from itertools import zip_longest
except ImportError:
    from itertools import izip_longest as zip_longest
_subfield_pattern = re.compile(
    r'(?P<junk>[^a-zA-Z0-9]*)((?P<text>[a-zA-Z]+)|(?P<num>[0-9]+))'
)

# Minimum 6 GB Disk Space 
# required for building GISO
MIN_DISK_SPACE_SIZE_REQUIRED = 6 
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
OPTIONS = None
DEFAULT_RPM_PATH = 'giso/<rpms>'
SIGNED_RPM_PATH =  'giso/boot/initrd.img/<rpms>'
SIGNED_NCS5500_RPM_PATH =  'giso/boot/initrd.img/iso/system_image.iso/boot/initrd.img/<rpms>'
SIGNED_651_NCS5500_RPM_PATH = 'giso/boot/initrd.img/iso/system_image.iso/<rpms>'
OPTIMIZE_CAPABLE = os.path.exists('/sw/packages/jam_IOX/signing/xr_sign')
AUTO_RPM_BINARY_PATH = "/auto/thirdparty-sdk/host-x86_64/lib/rpm-5.1.9/rpm"
global_platform_name="None"
BZIMAGE_712="bzImage-7.1.2"

def run_cmd(cmd):
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE, shell=True, executable='/bin/bash')
    out, error = process.communicate()
    try:
        out = out.decode('utf8')
    except:
        pass
    sprc = process.returncode
    if sprc is None or sprc != 0:
        try:
           error = error.decode('utf8')
        except:
           pass
        out = error
        raise RuntimeError("Error CMD=%s returned --->%s" % (cmd, out))
    return dict(rc=sprc, output=out)

def run_cmd2 (cmd):
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, shell=True)
    out, error = process.communicate()
    sprc = process.returncode
    if sprc is None or sprc != 0:
        out = error
        raise RuntimeError("Error CMD=%s returned --->%s" % (cmd, out))
    else:
        ''' rpm returns exit code 0 even when error is populated '''
        if not out:
            out = error
            raise RuntimeError("Error CMD=%s returned --->%s" % (cmd, out))
    return out.strip()

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

        pwd=cwd
        dst_mpath = os.path.join(pwd, "upgrade_matrix")
        if os.path.exists(dst_mpath):
            shutil.rmtree(dst_mpath)

    def __generate_md5(self, inputpath):
        if os.path.isfile(inputpath):
            filename = os.path.basename(inputpath)
            if not str(filename).endswith(".md5sum"):
                run_cmd("echo $(md5sum " + inputpath + " | cut -d' ' -f1) > " + inputpath + ".md5sum")
            return
        for path in os.listdir(inputpath):
            abspath = os.path.join(inputpath, path)
            self.__generate_md5(abspath)

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
        self.dst_system_tar = dst_system_image.replace(".iso","-migrate_to_eXR.tar")

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
        #run_cmd('iso-read -i ' + input_image + " -e /" + self.BOOT_INITRD + " -o " + TMP_INITRD)
        run_cmd('isoinfo -i ' + input_image + " -R -x /" + self.BOOT_INITRD + " > " + TMP_INITRD)

        #check if Boot Directory exists
        if not os.path.exists(TMP_INITRD):
            logger.error("Failed to extract initrd(%s) from ISO %s" 
                         % (self.BOOT_INITRD, input_image))
            logger.info("Please make sure at least 1.5 GB of space is availble in /tmp/")
            sys.exit(-1)

        logger.debug("Getting BOOT_DIR(%s) " % self.BOOT_DIR)
        run_cmd("zcat " + TMP_INITRD + " | cpio -id " + self.BOOT_DIR + "/*")
        run_cmd("chmod -R 777 %s"%(self.BOOT_DIR))

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

        self.__generate_md5(os.path.abspath(self.BOOT_DIR))
        self.__generate_md5(os.path.abspath(self.GRUB_DIR))
        self.__generate_md5(os.path.abspath(dst_system_image))

        logger.debug("tar -cvf " + self.dst_system_tar + " " + self.BOOT_DIR + " " + self.GRUB_DIR + " " + dst_system_image + " " + dst_system_image + ".md5sum")
        run_cmd("tar -cvf " + self.dst_system_tar + " " + self.BOOT_DIR + " " + self.GRUB_DIR + " " + dst_system_image + " " + dst_system_image + ".md5sum")
 

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

    def populate_mdata(self, fs_root, rpm, is_full_iso):
        self.file_name = rpm
        rpm_data_filled = False
        # Some RPMs(k9) dont have read access which causes RPM query fail 
        run_cmd(" chmod 644 %s"%(os.path.join(fs_root,rpm)))
        if not is_full_iso:
            group_info = run_cmd("chroot "+fs_root+" rpm -qp --qf '%{GROUP}' "+rpm)
            if 'SUPPCARDS' in group_info["output"].upper() or 'XRRELEASE' in group_info["output"].upper():
                result = run_cmd("chroot "+fs_root+" rpm -qp --qf '%{NAME};%{VERSION};"
                             "%{RELEASE};%{ARCH};"
                             "%{BUILDTIME};"
                             "%{PREFIXES};%{GROUP};"
                             "' "+rpm)
                result_str_list = result["output"].split(";")
                self.name = result_str_list[0]
                self.version = result_str_list[1]
                self.release = result_str_list[2]
                self.arch = result_str_list[3]
                self.build_time = result_str_list[4]
                self.prefixes = result_str_list[5]
                self.group = result_str_list[6].split(',',1)[0]
                grp = group_info["output"].split(',', 1)[1]
                cfg = dict([(item.partition(':')[0].upper(),
                            item.partition(':')[2])
                            for item in grp.split(';') if not
                            item.strip().startswith('#') and item.strip()])
                '''custom tag SUPPCARDS used to hold data with ',' as delimiter'''
                if cfg.has_key('SUPPCARDS'):
                    cfg['SUPPCARDS'] = ','.join(cfg['SUPPCARDS'].split('-'))
                pkgdict = dict (custom_mdata)
                pkgdict.update (cfg)
                self.supp_cards = pkgdict['SUPPCARDS']
                self.vm_type = pkgdict['VMTYPE']
                self.package_platform = pkgdict['CISCOHW']
                self.package_type = pkgdict['PACKAGETYPE']
                self.package_presence = pkgdict['PACKAGEPRESENCE']
                self.xrrelease = pkgdict['XRRELEASE']
                self.package_pipd = pkgdict['PIPD']
                self.card_type = pkgdict['CARDTYPE']
                rpm_data_filled = True
            else:
                result = run_cmd("chroot "+fs_root+" rpm -qp --qf '%{NAME};%{VERSION};"
                             "%{RELEASE};%{ARCH};%{PACKAGETYPE};%{PACKAGEPRESENCE};"
                             "%{PIPD};%{CISCOHW};%{CARDTYPE};%{BUILDTIME};"
                             "%{GROUP};%{VMTYPE};%{SUPPCARDS};%{PREFIXES};"
                             "%{XRRELEASE};' "+rpm)
        else:
            if os.path.exists(AUTO_RPM_BINARY_PATH):
                result = run_cmd(AUTO_RPM_BINARY_PATH+
                         " -qp --qf '%{NAME};%{VERSION};"
                         "%{RELEASE};%{ARCH};%{PACKAGETYPE};%{PACKAGEPRESENCE};"
                         "%{PIPD};%{CISCOHW};%{CARDTYPE};%{BUILDTIME};"
                         "%{GROUP};%{VMTYPE};%{SUPPCARDS};%{PREFIXES};"
                         "%{XRRELEASE};' "+fs_root+ "/"+rpm)
            else:
                logger.error("Error: %s is not accessible for collecting rpm metadata\n" %(AUTO_RPM_BINARY_PATH))
                sys.exit(-1)
        if not rpm_data_filled:
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

        if not is_full_iso:
            result = run_cmd("chroot %s rpm -qp --provides %s" % (fs_root, rpm))
        else:
            if os.path.exists(AUTO_RPM_BINARY_PATH):
                result = run_cmd("%s -qp --provides %s" % (AUTO_RPM_BINARY_PATH, fs_root+"/"+rpm))
        self.provides = result["output"]

        if not is_full_iso:
            result = run_cmd("chroot %s rpm -qp --requires %s" % (fs_root, rpm))
        else:
            if os.path.exists(AUTO_RPM_BINARY_PATH):
                result = run_cmd("%s -qp --requires %s" % (AUTO_RPM_BINARY_PATH, fs_root+"/"+rpm))
        #
        # There can be more than one requires.
        # Ignore requires starting with /
        # example /bin/sh
        # Ignore /bin/sh requires. 
        #
        result_str_list = result["output"].split("\n")
        requires_list = []
        list(map(lambda x: requires_list.append(x),
            [y for y in result_str_list if not y.startswith('/')]))

        self.requires = requires_list
        list(map(lambda x: logger.debug("%s:%s" % x), list(vars(self).items())))
         
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
        if not self.is_cisco_rpm (platform):
            return True
        else:
            return False

    def is_spiritboot(self):
        return ((SPIRIT_BOOT_SUBSTRING in self.name) and 
                (IOS_XR_SUBSTRING in self.group.upper()
                 or HOST_SUBSTRING in self.group.upper()
                 or SYSADMIN_SUBSTRING in self.group.upper()))


class Rpmdb:

    tmp_smu_tar_extract_path = ""

    def __init__(self):
        self.bundle_iso = Iso()
        self.repo_path = []
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
        self.tmp_repo_path = None
        self.sp_info = None
        self.sp_names = [] 
        self.latest_sp_name = None
        self.sp_name_invalid = []
        self.sp_mount_path = None
        self.vm_sp_rpm_file_paths = {"XR": None, "CALVADOS": None, "HOST": None}
        self.is_full_iso_require = False
        self.is_skip_dep_check = False
        self.tmp_smu_repo_path = []

    @staticmethod
    def get_pre_req_opt_rpm(repo_paths, pkg):
        pre_req_rpms = []
        pre_req_rpm_list = []

        if "asr9k-bng-" in pkg or "asr9k-cnbng" in pkg:
            for repo_path in repo_paths:
                pre_req_rpm=("%s/%s*.rpm" %(repo_path, "asr9k-bng-supp-x64"))
                pre_req_rpms += glob.glob(pre_req_rpm)
            for el in pre_req_rpms:
                if not re.search('CSC[a-z][a-z]\d{5}', el):
                    pre_req_rpm_list.append(el)
        if "-mpls-te-" in pkg:
            for repo_path in repo_paths:
                pre_req_rpm=("%s/*%s*.rpm" %(repo_path, "-mpls-"))
                pre_req_rpms += glob.glob(pre_req_rpm)
            for el in pre_req_rpms:
                if not re.search('CSC[a-z][a-z]\d{5}', el) and not "-mpls-te-" in el:
                    pre_req_rpm_list.append(el)
        return pre_req_rpm_list

    @staticmethod
    def validate_and_return_list(platform, repo_paths, pkglist):
        repo_files = []
        new_repo_paths = []
        rpm_tar_list = []
        tmp_file_list = []
        require_rpms_list = []
        require_name_list = []
        ciso_rpm_files = []
        tar_rpm_file_list = []

        for repo in repo_paths:
            for pkg in pkglist:
                if re.search('CSC[a-z][a-z]\d{5}', pkg):

                    # DDTS ID with tar extension
                    if pkg.endswith('.tar'):
                        filepath=("%s/%s" %(repo, pkg))
                        if os.path.isfile(filepath):
                            if not Rpmdb.tmp_smu_tar_extract_path:
                                pwd=cwd
                                Rpmdb.tmp_smu_tar_extract_path = tempfile.mkdtemp(dir=pwd)
                            run_cmd("tar -xf %s -C %s" % (filepath, Rpmdb.tmp_smu_tar_extract_path))
                            run_cmd("ls -ltr %s" % (Rpmdb.tmp_smu_tar_extract_path))
                            tar_rpm_file_list = glob.glob(Rpmdb.tmp_smu_tar_extract_path+"/*.rpm")
                            repo_files.extend(tar_rpm_file_list)
                            for el in tar_rpm_file_list:
                                if platform in os.path.basename(el):
                                    cmd = "rpm -qpR %s | grep -e %s | grep  ' = '" %(el, platform)
                                    result = run_cmd(cmd)

                                    if len(require_name_list) == 0:
                                        require_name_list = result["output"].splitlines()
                                    else:
                                        require_name_list = list(set(require_name_list) | set(result["output"].splitlines()))
                                    logger.debug("XR rpm require list %s\n" % (require_name_list))
                                    print ("XR rpm require list %s\n" % (require_name_list))
                                    for repo_path in repo_paths:
                                        cisco_rpm=("%s/%s*.rpm" %(repo_path, platform))
                                        ciso_rpm_files += glob.glob(cisco_rpm)

                                    for require_field in require_name_list:
                                        for cisco_rpm_file in ciso_rpm_files:
                                            if "-sysadmin-" not in cisco_rpm_file:
                                                cmd = "rpm -qp --provides %s " %(cisco_rpm_file)
                                                result = run_cmd(cmd)
                                                if require_field in result["output"]:
                                                    logger.debug("Dependant rpm: %s\n" %(cisco_rpm_file))
                                                    repo_files.append(cisco_rpm_file)
                                                    pre_req_rpm_list = Rpmdb.get_pre_req_opt_rpm(repo_paths, cisco_rpm_file)
                                                    repo_files.extend(pre_req_rpm_list)
                                                    break
                            new_repo_paths.append(Rpmdb.tmp_smu_tar_extract_path)

                    # DDTS ID with rpm extension
                    elif pkg.endswith('.rpm'):
                        filepath=("%s/%s" %(repo, pkg))
                        if os.path.isfile(filepath):
                            # sysadmin rpms -> include missing arch rpms
                            if "-sysadmin-" in pkg:
                                temp=pkg.split('.')
                                if "-hostos-" not in pkg:
                                    pkg_nvr='.'.join(temp[:-2])
                                else:
                                    pkg_nvr='.'.join(temp[:-3])
                                host_rpms_filepath=("%s/*%s*" %(repo, pkg_nvr))
                                require_rpms_list += glob.glob(host_rpms_filepath)
                                for element in require_rpms_list:
                                    repo_files.append(element)
                            # Thirdparty rpms
                            elif platform not in pkg:
                                result = run_cmd("rpm -qp --qf '%{NAME}' " + filepath)
                                host_rpms_filepath=("%s/*%s*" %(repo, result["output"]))
                                require_rpms_list += glob.glob(host_rpms_filepath)
                                for element in require_rpms_list:
                                    cmd = "rpm -qpR %s | grep -e '>=' -e '=' | cut -d ' ' -f1" %(element)
                                    result = run_cmd(cmd)
                                    if len(require_name_list) == 0:
                                        require_name_list = result["output"].splitlines()
                                    else:
                                        require_name_list = list(set(require_name_list) | set(result["output"].splitlines()))
                                    repo_files.append(element)
                                logger.debug("require list \n%s\n" %(require_name_list))
                                for require_name in require_name_list:
                                    host_rpms_filepath=("%s/*%s*" %(repo, require_name))
                                    require_rpms_list += glob.glob(host_rpms_filepath)
                                    for element in require_rpms_list:
                                        repo_files.append(element)
                            # XR rpms
                            elif platform in pkg:
                                if SPIRIT_BOOT_SUBSTRING  not in filepath:
                                    cmd = "rpm -qpR %s | grep -e %s | grep  ' = '" %(filepath, platform)
                                    result = run_cmd(cmd)

                                    if len(require_name_list) == 0:
                                        require_name_list = result["output"].splitlines()
                                    else:
                                        require_name_list = list(set(require_name_list) | set(result["output"].splitlines()))
                                logger.debug("XR rpm require list %s\n" % (require_name_list))
                                for repo_path in repo_paths:
                                    cisco_rpm=("%s/%s*.rpm" %(repo_path, platform))
                                    ciso_rpm_files += glob.glob(cisco_rpm)

                                for require_field in require_name_list:
                                    for cisco_rpm_file in ciso_rpm_files:
                                        if "-sysadmin-" not in cisco_rpm_file:
                                            cmd = "rpm -qp --provides %s " %(cisco_rpm_file)
                                            result = run_cmd(cmd)
                                            if require_field in result["output"]:
                                                logger.debug("Dependant rpm: %s\n" %(cisco_rpm_file))
                                                repo_files.append(cisco_rpm_file)
                                                pre_req_rpm_list = Rpmdb.get_pre_req_opt_rpm(repo_paths, cisco_rpm_file)
                                                repo_files.extend(pre_req_rpm_list)
                                                break
                                repo_files.append(filepath)

                    # DDTS ID with No extension
                    else:
                        filepath=("%s/*%s*" %(repo, pkg))
                        rpm_tar_list += glob.glob(filepath)
                        if len(rpm_tar_list):
                            for element in rpm_tar_list:
                                if element.endswith('.tar'):
                                    if not Rpmdb.tmp_smu_tar_extract_path:
                                        pwd=cwd
                                        Rpmdb.tmp_smu_tar_extract_path = tempfile.mkdtemp(dir=pwd)
                                    run_cmd("tar -xf %s -C %s" % (element, Rpmdb.tmp_smu_tar_extract_path))
                                    run_cmd("ls -ltr %s" % (Rpmdb.tmp_smu_tar_extract_path))

                                    tmp_file_list  += glob.glob(Rpmdb.tmp_smu_tar_extract_path+"/*.rpm")
                                    for el in tmp_file_list:
                                        if el not in repo_files:
                                            repo_files.append(el)
                                    for el in tmp_file_list:
                                        pre_req_rpm_list = Rpmdb.get_pre_req_opt_rpm(repo_paths, el)
                                        repo_files.extend(pre_req_rpm_list)
                                    new_repo_paths.append(Rpmdb.tmp_smu_tar_extract_path)

                                elif element.endswith('.rpm'):
                                    repo_files.append(element)
                                    pre_req_rpm_list = Rpmdb.get_pre_req_opt_rpm(repo_paths, element)
                                    repo_files.extend(pre_req_rpm_list)

                # Presence of "all" in the input parameter
                elif pkg == "all":
                    repo_files = []
                    for repo in repo_paths:
                        tmp_file_list += glob.glob(repo+"/*")
                        for el in tmp_file_list:
                            # DDTS ID with tar extension
                            if el.endswith('.tar'):
                                filepath=("%s/%s" %(repo, el))
                                if os.path.isfile(filepath):
                                    if not Rpmdb.tmp_smu_tar_extract_path:
                                        pwd=cwd
                                        Rpmdb.tmp_smu_tar_extract_path = tempfile.mkdtemp(dir=pwd)
                                    run_cmd("tar -xf %s -C %s" % (filepath, Rpmdb.tmp_smu_tar_extract_path))
                                    run_cmd("ls -ltr %s" % (Rpmdb.tmp_smu_tar_extract_path))
                                    repo_files += glob.glob(Rpmdb.tmp_smu_tar_extract_path+"/*")
                                    new_repo_paths.append(Rpmdb.tmp_smu_tar_extract_path)
                            if el.endswith('.rpm') and el not in repo_files:
                                repo_files.append(el)
                # No presence of DDTS ID in the input parameter e.g opt rpms
                else:
                    filepath=("%s/%s" %(repo, pkg))
                    if os.path.isfile(filepath):
                        repo_files.append(filepath)
                        pre_req_rpm_list = Rpmdb.get_pre_req_opt_rpm(repo_paths, pkg)
                        repo_files.extend(pre_req_rpm_list)

        repo_files = list(set(repo_files))
        logger.debug("\nFile list After Unification [%s] \n" %(repo_files))
        return new_repo_paths, repo_files

    def populate_rpmdb(self, fs_root, repo_paths, pkglist, platform, iso_version, full_iso, eRepo):
        retval = 0
        repo_files = []
        new_repo_paths = repo_paths
        #tmp_repo_path = []
        if not (repo_paths and fs_root):
            logger.error('Invalid arguments')
            return -1
        for repo in repo_paths:
            logger.info("\nScanning repository [%s]...\n" % (os.path.abspath(repo)))

            if len(pkglist):
                self.tmp_smu_repo_path, repo_files = Rpmdb.validate_and_return_list(platform, repo_paths, pkglist)
            else:
                repo_files += glob.glob(repo+"/*")

        # Notify skipped packages which are not present in repo
        if len(pkglist) and "all" not in pkglist:
            skipped_pkg = []
            found = False
            for item in pkglist:
                found = False
                for item1 in repo_files:
                    if item in item1:
                        found = True
                        break
                if not found:
                    skipped_pkg.append(item)

            if len(skipped_pkg):
                logger.info("\nFollowing packages in input for pkglist were skipped "
                        "as these are not present in the given repositories, "
                        "continuing with Golden ISO build...\n")
            list(map(lambda file_name: logger.info("\t(-) %s" % os.path.basename(file_name)), skipped_pkg))

        if not len(repo_files) and not len(pkglist):
            logger.info('RPM repository directory \'%s\' is empty!!' % repo)
        else:
            new_repo_paths += self.tmp_smu_repo_path

        if not len(repo_files):
            return 0 
        # if it is gISO extend look at eRepo as well.
        if eRepo is not None:
            repo_files += glob.glob(eRepo+"/*")
        rpm_name_version_release_arch_list = []
        if full_iso:
            self.is_full_iso_require = True
        logger.info("Building RPM Database...")
        # creating temporary path to hold user provided rpms and sp's rpms
        pwd=cwd
        self.tmp_repo_path = tempfile.mkdtemp(dir=pwd)      
        for file_name in repo_files:
            result = run_cmd('file -b %s' % file_name)
            if re.match(".*RPM.*", result["output"]):
                shutil.copy(file_name, fs_root)
                shutil.copy(file_name, self.tmp_repo_path)
                rpm = Rpm()
                rpm.populate_mdata(fs_root, os.path.basename(file_name), 
                                   self.is_full_iso_require)
                rpm_name_ver_rel_arch = "%s-%s-%s.%s" % (rpm.name, rpm.version,
                                                         rpm.release, rpm.arch)
                if rpm_name_ver_rel_arch \
                   not in rpm_name_version_release_arch_list:
                    self.rpm_list.append(rpm)
                    rpm_name_version_release_arch_list.\
                        append(rpm_name_ver_rel_arch)
            if re.match(".*SERVICEPACK.*", result["output"]):
                sp_basename = os.path.basename(file_name) 
                if platform in sp_basename.split('-')[0]:
                    sp_version = sp_basename.split('-')[-1]
                    sp_version = sp_version.replace('.iso', '')
                    if sp_version == iso_version:
                        self.sp_names.append(file_name)
                    else:
                        self.sp_name_invalid.append(sp_basename)
                else:
                    self.sp_name_invalid.append(sp_basename)

        if self.sp_names:
            logger.info("\nFollowing are the valid Service pack present in the repository path provided in CLI\n")
            list(map(lambda file_name: logger.info("\t(+) %s" % os.path.basename(file_name)), self.sp_names))

        if self.sp_name_invalid:
            logger.info("\nSkipping following invalid Service pack from the repository path\n")
            list(map(lambda file_name: logger.info("\t(-) %s" % os.path.basename(file_name)), self.sp_name_invalid))

        try:
            self.process_sp()    
        except:
            self.cleanup_tmp_sp_data()
            
        logger.info("\nTotal %s RPM(s) present in the repository path provided in CLI" % (len(self.rpm_list)))
        self.repo_path = new_repo_paths
       
        return 0

    @staticmethod
    def sp_version_string_cmp(sp1, sp2):
        if (not sp1) and (not sp2):
            return 0
        list1 = os.path.basename(sp1).split('-')
        list2 = os.path.basename(sp2).split('-') 

        spv1 = int(re.findall(r'\d+', list1[1])[0])
        spv2 = int(re.findall(r'\d+', list2[1])[0])

        if spv1 > spv2:
            return -1
        elif spv1 < spv2:
            return 1
        else:
            return 0

    def process_sp(self):

        sorted_sps = \
            sorted(self.sp_names,   
                   key=functools.cmp_to_key(Rpmdb.sp_version_string_cmp))
        self.latest_sp_name = sorted_sps[0] 
        
        #latest service pack will be used if multiple sp is present
        logger.info("\nService pack used in giso = %s" % (sorted_sps[0]))
        pwd=cwd
        self.sp_mount_path = tempfile.mkdtemp(dir=pwd)      
        self
        readiso(self.latest_sp_name, self.sp_mount_path)

        
        sp_files = glob.glob(self.sp_mount_path+"/*")
        for sp_file in sp_files:
            if "/host_rpms" in sp_file:
                self.vm_sp_rpm_file_paths[HOST_SUBSTRING] = glob.glob(sp_file+"/*")
            if "/calvados_rpms" in sp_file:
                self.vm_sp_rpm_file_paths[CALVADOS_SUBSTRING] = glob.glob(sp_file+"/*")
            if "/xr_rpms" in sp_file:
                self.vm_sp_rpm_file_paths[XR_SUBSTRING] = glob.glob(sp_file+"/*")
            if "/sp_info.txt" in sp_file:
                self.sp_info = sp_file

        if len(self.vm_sp_rpm_file_paths[HOST_SUBSTRING]) != 0:
            logger.info("\nFollowing are the host rpms in service pack:\n")
            list(map(lambda file_name: logger.info("\t(*) %s" % os.path.basename(file_name)), self.vm_sp_rpm_file_paths[HOST_SUBSTRING]))
        if len(self.vm_sp_rpm_file_paths[CALVADOS_SUBSTRING]) != 0:
            logger.info("\nFollowing are the cavados rpms in service pack:\n")
            list(map(lambda file_name: logger.info("\t(*) %s" % os.path.basename(file_name)), self.vm_sp_rpm_file_paths[CALVADOS_SUBSTRING]))
        if len(self.vm_sp_rpm_file_paths[XR_SUBSTRING]) != 0:
            logger.info("\nFollowing are the xr rpms in service pack:\n")
            list(map(lambda file_name: logger.info("\t(*) %s" % os.path.basename(file_name)), self.vm_sp_rpm_file_paths[XR_SUBSTRING]))

        return 0

    def cleanup_tmp_sp_data(self):
        if self.sp_mount_path and  os.path.exists(self.sp_mount_path):
            logger.debug("Cleaning sp temporaray data %s" % self.sp_mount_path)
            shutil.rmtree(self.sp_mount_path)
        return 0

    def cleanup_tmp_repo_path(self):
        if self.tmp_repo_path and os.path.exists(self.tmp_repo_path):
            logger.debug("Cleaning repo temporary data %s" % self.tmp_repo_path)
            shutil.rmtree(self.tmp_repo_path)
        if len(self.tmp_smu_repo_path):
            for repo_path in self.tmp_smu_repo_path:
                if os.path.exists(repo_path):
                    logger.debug("Cleaning smu repo temporary data %s" % repo_path)
                    shutil.rmtree(repo_path)
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
        list(map(lambda rpm_inst: logger.debug("\t\t%s" % rpm_inst.file_name),
            self.csc_rpm_list))

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
        list(map(lambda rpm_inst: logger.debug("\t\t%s" % rpm_inst.file_name),
            self.tp_rpm_list))
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
        list(map(lambda rpm_inst: logger.debug("\t\t%s" % rpm_inst.file_name),
            self.csc_rpm_list))
        
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
        list(map(lambda rpm_inst: logger.debug("\t\t%s" % rpm_inst.file_name),
            self.csc_rpm_list))
        
    #
    # Filter and discard cnbng Cisco rpm if both bng and cnbng rpm present.
    #
    def filter_cnbng_rpm(self):
        bng_rpms = set()
        cnbng_rpms = set()

        for rpm in self.csc_rpm_list:
            if "asr9k-bng-x64" in rpm.name:
                bng_rpms |= set([rpm])
            elif "asr9k-cnbng-x64" in rpm.name:
                cnbng_rpms |= set([rpm])
        if len(bng_rpms) and len(cnbng_rpms):
            self.csc_rpm_list = list(set(self.csc_rpm_list) - cnbng_rpms)
            self.rpm_list = list(set(self.rpm_list) - cnbng_rpms)
            self.csc_rpm_count = len(self.csc_rpm_list)

            if cnbng_rpms:
                logger.info("\nSkipped following RPM(s) due to conflict with bng-x64 rpms\n")
                for rpm in cnbng_rpms:
                    logger.info("\t(-) %s" % rpm.file_name)
            logger.debug('Found updated %s Cisco RPMs' % self.csc_rpm_count)
            list(map(lambda rpm_inst: logger.debug("\t\t%s" % rpm_inst.file_name),
                 self.csc_rpm_list))

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
                                    # if release file have multiple base rpm for a package,
                                    # read first available  instance
                                    else:
                                        continue

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
                    i_rpm_ver = mre.groups()[1]
                    # i_rpm_rel = mre.groups()[2]
                    i_rpm_arch = mre.groups()[3]
                    if i_rpm_name == s_rpm_name:
                        base_rpm_arch = \
                            list(self.sdk_rpm_mdata[platform][vm][sdk_arch][s_rpm_name].keys())[0]

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
                            if base_rpm_filename == rpm.file_name and base_rpm_ver in i_rpm_ver:
                                return rpm   
        if not base_rpm_filename:
            for rpm in self.tp_rpm_list:
                if rpm.vm_type.upper() == CALVADOS_SUBSTRING:
                    vmstr="admin"
                else:
                    vmstr=rpm.vm_type
                if (rpm.file_name.find("CSC") == -1) :
                    if i_rpm_arch != rpm.arch:
                        continue
                    if vm != vmstr.upper():
                        continue
                    if i_rpm_name ==  rpm.name:
                        logger.debug("Base rpm was calculated without thirdparty list\n")
                        return rpm
                    else:
                        logger.debug("Didn't find base rpm\n")
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
            list(map(lambda rpm_inst: logger.info("\t(*) %s" % rpm_inst.file_name), 
                duplicate_tp_host_rpm))
        if len(duplicate_tp_admin_rpm) != 0:
            logger.error("\nFollowing are the duplicate admin tp smus:\n")
            list(map(lambda rpm_inst: logger.info("\t(*) %s" % rpm_inst.file_name), 
                duplicate_tp_admin_rpm))
        if len(duplicate_tp_xr_rpm) != 0:
            logger.error("\nFollowing are the duplicate xr tp smus:\n")
            list(map(lambda rpm_inst: logger.info("\t(*) %s" % rpm_inst.file_name), 
                duplicate_tp_xr_rpm))

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
            list(map(lambda rpm_inst: logger.info("\t-->%s" % rpm_inst.file_name), 
                invalid_tp_host_rpm))
            rc = -1
        if len(invalid_tp_admin_rpm):
            logger.info("\nBase rpm(s) of following %d Thirdparty Sysadmin SMU(s) "
                        "is/are not present in the repository.\n" % 
                        len(invalid_tp_admin_rpm)) 
            list(map(lambda rpm_inst: logger.info("\t-->%s" % rpm_inst.file_name), 
                invalid_tp_admin_rpm))
            rc = -1
        if len(invalid_tp_xr_rpm):
            logger.info("\nBase rpm(s) of following %d Thirdparty Xr SMU(s) "
                        "is/are not present in the repository.\n" % 
                        len(invalid_tp_xr_rpm)) 
            list(map(lambda rpm_inst: logger.info("\t-->%s" % rpm_inst.file_name), 
                invalid_tp_xr_rpm))
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

        superseded_tp_smu_list = self.filter_superseded_tp_smu(valid_tp_host_rpm,
                                                               valid_tp_admin_rpm,
                                                               valid_tp_xr_rpm)

        self.tp_rpm_list = list(set(self.tp_rpm_list) - superseded_tp_smu_list)
        self.tp_rpm_count = len(self.tp_rpm_list)
        self.rpm_list = list(set(self.rpm_list) - superseded_tp_smu_list)

        if invalid_tp_rpm_list:
            logger.info("Skipping following %s Thirdparty RPM(s) not supported\n" 
                        "for release %s:\n" % 
                        (len(invalid_tp_rpm_list), iso_version))
            list(map(lambda rpm_inst: logger.info("\t\t(-) %s" % rpm_inst.file_name), 
                invalid_tp_rpm_list))
            logger.info("If any of the above %s RPM(s) needed for Golden ISO then\n"
                        "provide RPM(s) supported for release %s" % 
                        (len(invalid_tp_rpm_list), iso_version))

        if superseded_tp_smu_list:
            logger.debug("Skipping following superseded Thirdparty SMU(s)\n")
            list(map(lambda rpm_inst: logger.debug("\t\t%s" % rpm_inst.file_name),
                superseded_tp_smu_list))

        logger.debug('Found %s TP RPMs' % self.tp_rpm_count)
        list(map(lambda rpm_inst: logger.debug("\t\t%s" % rpm_inst.file_name), 
            self.tp_rpm_list))

    # Remove superseded tp smu present in the list
    @staticmethod
    def find_superseded_tp_smu(rpm_set):

        superseded_tp_rpm_set = set()
        highest_ver_seen_smu_dict = {}

        # TP smus of same package get built with different version
        # than previous one. running number will be incremeneted after .p[n]
        # e.g cisco-klm-0.1.p1-r0.0.CSCvr59318.admin.x86_64.rpm
        # cisco-klm-0.1.p2-r0.0.r663.CSCvv27341.admin.x86_64.rpm
        for rpm in rpm_set:
            if rpm.package_type.upper() == SMU_SUBSTRING:
                smu_na = "%s-%s" % (rpm.name, rpm.arch)
                if smu_na in highest_ver_seen_smu_dict:
                    if highest_ver_seen_smu_dict[smu_na].version < rpm.version:
                        superseded_tp_rpm_set.add(highest_ver_seen_smu_dict[smu_na])
                        highest_ver_seen_smu_dict[smu_na] = rpm
                    else:
                        superseded_tp_rpm_set.add(rpm)
                else:
                    highest_ver_seen_smu_dict[smu_na] = rpm

        return superseded_tp_rpm_set

    # filter superseded tp smu present
    def filter_superseded_tp_smu(self, host_rpm_set, admin_rpm_set, xr_rpm_set):
        superseded_tp_host_rpm = set()
        superseded_tp_admin_rpm = set()
        superseded_tp_xr_rpm = set()
        all_superseded_tp_rpm = set()

        if host_rpm_set:
            superseded_tp_host_rpm = Rpmdb.find_superseded_tp_smu(host_rpm_set)
        if admin_rpm_set:
            superseded_tp_admin_rpm = Rpmdb.find_superseded_tp_smu(admin_rpm_set)
        if xr_rpm_set:
            superseded_tp_xr_rpm = Rpmdb.find_superseded_tp_smu(xr_rpm_set)

        all_superseded_tp_rpm = (superseded_tp_host_rpm |
                                 superseded_tp_admin_rpm |
                                 superseded_tp_xr_rpm)

        return all_superseded_tp_rpm

    def filter_hostos_spirit_boot_base_rpms(self, platform):
        all_hostos_base_rpms = [x for x in self.csc_rpm_list if x.is_hostos_rpm(platform) and
                                x.package_type.upper() != SMU_SUBSTRING]
        all_spirit_boot_base_rpms = [x for x in self.csc_rpm_list if x.is_spiritboot() and 
                                     x.package_type.upper() != SMU_SUBSTRING]

        if len(all_hostos_base_rpms):
            logger.info("\nSkipping following host os base rpm(s) "
                        "from repository:\n")
            for rpm in all_hostos_base_rpms:    
                logger.info("\t(-) %s" % rpm.file_name)

        list(map(self.csc_rpm_list.remove, all_hostos_base_rpms))
        list(map(self.rpm_list.remove, all_hostos_base_rpms))

        if len(all_spirit_boot_base_rpms):
            logger.info("\nSkipping following spirit-boot base rpm(s) "
                        "from repository:\n")
            for rpm in all_spirit_boot_base_rpms:    
                logger.info("\t(-) %s" % rpm.file_name)
        list(map(self.csc_rpm_list.remove, all_spirit_boot_base_rpms))
        list(map(self.rpm_list.remove, all_spirit_boot_base_rpms))

    def _iter_rpm_subfields(self, field):
        """Yield subfields as 2-tuples that sort in the desired order

        Text subfields are yielded as (0, text_value)
        Numeric subfields are yielded as (1, int_value)
        """
        for subfield in _subfield_pattern.finditer(field):
            text = subfield.group('text')
            if text is not None:
                yield (0, text)
            else:
                yield (1, int(subfield.group('num')))

    def _compare_rpm_field(self, lhs, rhs):
        # Short circuit for exact matches (including both being None)
        if lhs == rhs:
            return 0
        # Otherwise assume both inputs are strings
        lhs_subfields = self._iter_rpm_subfields(lhs)
        rhs_subfields = self._iter_rpm_subfields(rhs)
        for lhs_sf, rhs_sf in zip_longest(lhs_subfields, rhs_subfields):
            if lhs_sf == rhs_sf:
                # When both subfields are the same, move to next subfield
                continue
            if lhs_sf is None:
                # Fewer subfields in LHS, so it's less than/older than RHS
                return -1
            if rhs_sf is None:
                # More subfields in LHS, so it's greater than/newer than RHS
                return 1
            # Found a differing subfield, so it determines the relative order
            return -1 if lhs_sf < rhs_sf else 1
        # No relevant differences found between LHS and RHS
        return 0

    def _compare_rpm_labels(self, lhs, rhs):
        lhs_epoch, lhs_version, lhs_release = lhs
        rhs_epoch, rhs_version, rhs_release = rhs
        result = self._compare_rpm_field(lhs_epoch, rhs_epoch)
        if result:
            return result
        result = self._compare_rpm_field(lhs_version, rhs_version)
        if result:
            return result
        return self._compare_rpm_field(lhs_release, rhs_release)

    def filter_superseded_rpms(self):
        count = 0
        latest_smu = {}
        for pkg in self.csc_rpm_list :
            count = count + 1
            logger.info("[%2d] %s "%(count,pkg.file_name))
            key = "%s.%s.%s.%s"%(pkg.name, pkg.package_type, pkg.arch, pkg.vm_type)
            if key in latest_smu:
                p_v = latest_smu[key].version
                p_r = latest_smu[key].release
                t_v = pkg.version
                t_r = pkg.release
                if self._compare_rpm_labels([0,p_v,p_r],[0,t_v,t_r]) < 0 :
                    latest_smu[key] = pkg
            else :
                latest_smu[key] = pkg

        for pkg in self.tp_rpm_list :
            count = count + 1
            logger.info("[%2d] %s "%(count,pkg.file_name))

        self.csc_rpm_list = [ latest_smu[key] for key in list(latest_smu.keys()) ]


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
        ilist1 = list(map(int, rpm1.version.split('.')))
        ilist2 = list(map(int, rpm2.version.split('.')))
        if ilist1 > ilist2:
            return -1
        elif ilist1 < ilist2:
            return 1
        else:
            return 0

    def filter_multiple_hostos_spirit_boot_rpms(self, platform):
        self.filter_hostos_spirit_boot_base_rpms(platform)

        all_hostos_rpms = [x for x in self.csc_rpm_list if x.is_hostos_rpm(platform)]
        all_spirit_boot_rpms = [x for x in self.csc_rpm_list if x.is_spiritboot()]

        self.validate_associate_hostos_rpms(all_hostos_rpms)
 
        sorted_hostos_rpms = \
            sorted(all_hostos_rpms,   
                   key=functools.cmp_to_key(Rpmdb.rpm_version_string_cmp))
        discarded_hostos_rpms = \
            [x for x in sorted_hostos_rpms if sorted_hostos_rpms[0].version != x.version]

        if len(discarded_hostos_rpms):
            logger.info("\nSkipping following older version of host os rpm(s) from repository:\n")
            for rpm in discarded_hostos_rpms:    
                logger.info("\t(-) %s" % rpm.file_name)

        list(map(self.csc_rpm_list.remove, discarded_hostos_rpms))
        list(map(self.rpm_list.remove, discarded_hostos_rpms))

        sorted_spiritboot = \
            sorted(all_spirit_boot_rpms,
                   key=functools.cmp_to_key(Rpmdb.rpm_version_string_cmp))
        discarded_spiritboot_rpms = \
            [x for x in sorted_spiritboot if sorted_spiritboot[0].version != x.version]

        if len(discarded_spiritboot_rpms):
            logger.info("\nSkipping following older version of spirit-boot rpm(s) from repository:\n")
            for rpm in discarded_spiritboot_rpms:
                logger.info("\t(-) %s" % rpm.file_name)
        list(map(self.csc_rpm_list.remove, discarded_spiritboot_rpms))
        list(map(self.rpm_list.remove, discarded_spiritboot_rpms))
            
    #
    # Group Cisco rpms based on VM_type and Architecture
    # {"HOST":{},"CALVADOS":{},"XR":{}}
    #
    def group_cisco_rpms_by_vm_arch(self):
        for rpm in self.csc_rpm_list:
            arch_rpms = self.csc_rpms_by_vm_arch[rpm.vm_type.upper()]
            if not (rpm.arch in list(arch_rpms.keys())):
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
            if not (rpm.arch in list(arch_rpms.keys())):
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
        for repo_path in self.repo_path:
            if os.path.exists(repo_path+rpm.file_name):
                return "%s/%s" % (repo_path, rpm.file_name)

    def get_tp_rpms_by_vm_arch(self, vm_type, arch):
        if not (vm_type in list(self.tp_rpms_by_vm_arch.keys())):
            return []
        if not (arch in list(self.tp_rpms_by_vm_arch[vm_type].keys())):
            return []
        return self.tp_rpms_by_vm_arch[vm_type][arch]

    def get_cisco_rpms_by_vm_arch(self, vm_type, arch):
        if not (vm_type in list(self.csc_rpms_by_vm_arch.keys())):
            return []
        if not (arch in list(self.csc_rpms_by_vm_arch[vm_type].keys())):
            return []
        return self.csc_rpms_by_vm_arch[vm_type][arch] 

    def get_sp_mount_path(self): 
        return self.sp_mount_path

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

    def get_sp_info(self):
        return self.sp_info

def system_resource_check(args):
    rc = 0
    tools = ['mount', 'rm', 'cp', 'umount', 'zcat', 'chroot', 'mkisofs']
    logger.debug("\nPerforming System requirements check...")

    if sys.version_info < (2, 7):
        logger.error("Error: This tool requires Python version 2.7 or higher.")
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
    
    if args.fullISO:
        tools.remove('chroot')
    for tool in tools:
        try:
            run_cmd("which %s" % tool)
        except Exception:
            exc_info = sys.exc_info()
            logger.debug("TB:", exc_info=True)
            print("\n", "Exception:", exc_info[0], exc_info[1])
            logger.error("\tError: Tool %s not found." % tool)
            rc = -1
            
    if rc != 0:
        logger.error("\tFailed to find tools, Check PATH Env variable or "
                     "install required tools.")
        # logger.debug("\t...System requirements check [FAIL]")
        logger.error("\nError: System requirements check [FAIL]")
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
    INSTALL_PKG_PLATFORMS = ["ncs5500", "asr9k-x64", "ncs1k", "ncs1001", "ncs1004", "ncs5k"]

    def __init__(self):
        self.iso_name = None
        self.iso_path = None
        self.iso_version = None
        self.iso_mount_path = None
        self.iso_rpms = None
        self.iso_extract_path = None
        self.iso_platform_name = None
        self.system_image_extract_path = None
        self.com_iso_path = None
        self.com_iso_mount_path = None
        self.iso_pkg_fmt_ver = None
        self.shrinked_iso_extract_path = None
        self.matrix_extract_path = None

    def create_com_iso_path(self, iso_path):
        dirpath = os.path.dirname(iso_path)
        basename = os.path.basename(iso_path)
        #print "self.iso_platform_name = %s" % (self.iso_platform_name)
        if "host" in self.iso_platform_name:
            com_iso_name = "%s-common.iso" %(global_platform_name)
        else:
            com_iso_name = "%s-common.iso" %(self.iso_platform_name)
        self.com_iso_path = "%s/%s" % (dirpath, com_iso_name)

    def set_iso_info(self, iso_path):
        #if os.system("losetup -f &> /dev/null") != 0:
        #    logger.error("No free loop device available for mouting ISO")
        #    sys.exit(-1)
          
        pwd = cwd
        self.iso_path = iso_path
        self.iso_mount_path = tempfile.mkdtemp(dir=pwd)      
        self.com_iso_mount_path = tempfile.mkdtemp(dir=pwd)      
        readiso(self.iso_path, self.iso_mount_path)
        iso_info_file = open("%s/%s" % (self.iso_mount_path, Iso.ISO_INFO_FILE),
                             'r')
        iso_info_raw = iso_info_file.read()
        self.iso_name = iso_info_raw[iso_info_raw.find("Name:"):].split(" ")[1]
        self.iso_platform_name = self.iso_name.split("-")[0] 
        self.iso_version = \
            iso_info_raw[iso_info_raw.find("Version:"):].split(" ")[1]
        self.iso_pkg_fmt_ver = \
            iso_info_raw[iso_info_raw.find("PKG_FORMAT_VER:"):].split(" ")[1]
        self.iso_rpms = glob.glob('%s/rpm/*/*' % self.iso_mount_path)
        if self.iso_pkg_fmt_ver >= "1.2":
            self.create_com_iso_path(self.iso_path)
            #print "self.com_iso_path = %s" % self.com_iso_path
            if os.path.exists(self.com_iso_path):
                readiso(self.com_iso_path, self.com_iso_mount_path)
                #print "self.com_iso_path = %s is valid " % self.com_iso_path
            else:
                self.com_iso_path = None
                #print "self.com_iso_path = %s is not valid " % self.com_iso_path
            
        iso_info_file.close()

        #Copy matrix files from the XR ISO to the extraction path 
        src_mpath = os.path.join(self.iso_mount_path, "upgrade_matrix")
        dst_mpath = os.path.join(pwd, "upgrade_matrix")
        if os.path.exists(src_mpath):
            try: 
                shutil.copytree(src_mpath, dst_mpath)
                run_cmd("chmod 644 %s/*" % (dst_mpath))
                self.matrix_extract_path = dst_mpath
            except:
                pass

    # Iso getter apis
    def get_iso_path(self):
        return self.iso_path

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

    def get_com_iso_mount_path(self):
        return self.com_iso_mount_path

    def get_iso_extract_path(self):
        if self.iso_extract_path is not None:
            return self.iso_extract_path 
        else:
            pwd = os.getcwd()
            self.iso_extract_path = tempfile.mkdtemp(dir=pwd)
            if self.iso_extract_path is not None:
                os.chdir(self.iso_extract_path)
                run_cmd("zcat -f %s%s | cpio -id" % (self.iso_mount_path,
                        Iso.ISO_INITRD_RPATH))
                # if single initrd image
                if self.iso_pkg_fmt_ver >= "1.2" and self.com_iso_path is not None:
                   run_cmd("zcat -f %s%s | cpio -idu" % (self.com_iso_mount_path,
                        Iso.ISO_INITRD_RPATH))
                # if shrinked asr9k image
                cpio_file = glob.glob('files.*.cpio')
                if len(cpio_file):
                    logger.debug("CPIO file present : %s" % cpio_file[0])
                    # copy for nested giso where shrinked mini iso is used
                    self.shrinked_iso_extract_path = tempfile.mkdtemp(dir=pwd)
                    run_cmd("cp -fr %s/* %s " % (self.iso_extract_path, self.shrinked_iso_extract_path))
                    pwd1 = os.getcwd()
                    cpioext = tempfile.mkdtemp(dir=pwd1)
                    os.chdir(cpioext)
                    run_cmd("cpio -idmu < %s/%s " % (self.iso_extract_path, cpio_file[0]))
                    logger.debug("CPIO %s extract path %s" % (cpio_file[0], 
                                                 cpioext))
                    os.chdir(pwd1)
                    run_cmd("zcat -f %s%s | cpio -idu" % (cpioext,
                        Iso.ISO_INITRD_RPATH))
                run_cmd("chmod -R 777 ./")
                os.chdir(pwd)
            else:
                logger.error("Error: Couldn't create directory for extarcting initrd")
                sys.exit(-1)
        run_cmd('touch %s/etc/mtab' % self.iso_extract_path)
        logger.debug("ISO %s extract path %s" % (self.iso_name, 
                                                 self.iso_extract_path))
        return self.iso_extract_path

    def get_shrinked_iso_extract_path(self):
        return self.shrinked_iso_extract_path

    def get_matrix_extract_path(self):
        return self.matrix_extract_path

    def do_compat_check(self, repo_path, input_rpms, iso_key, eRepo):
        rpm_file_list = ""
        all_rpms = []
        if self.iso_extract_path is None:
            self.get_iso_extract_path()
        rpm_staging_dir = "%s/rpms/" % self.iso_extract_path
        os.mkdir(rpm_staging_dir)
        input_rpms_set = set(input_rpms)
        iso_rpms_set = set(list(map(os.path.basename, self.iso_rpms)))
        logger.debug("ISO RPMS:")
        list(map(logger.debug, iso_rpms_set))

        dup_input_rpms_set = input_rpms_set & iso_rpms_set
        # TBD Detect dup input rpms based on provides info of base iso pkgs
        input_rpms_unique = input_rpms_set - dup_input_rpms_set
        for rpath in repo_path:
            for x in input_rpms_unique:
                rpm_path = "%s/%s" % (rpath, x)
                if os.path.exists(rpm_path):
                   all_rpms.append(rpm_path)
        all_rpms += self.iso_rpms
        all_rpms = list(set(all_rpms))
        try:
            for rpm in all_rpms:
              # In 712 and some otehr release base rpm version part of smu is 
              # lower version than base rpm in initrd. Due to this GISO build compatibility 
              # check failed. So skipping base rpm from compatibility check
              if global_platform_name not in rpm and not re.search('CSC[a-z][a-z]\d{5}', rpm):
                  continue
              if os.path.isfile(rpm):
                shutil.copy(rpm, rpm_staging_dir)
                rpm_file_list = "%s/rpms/%s  " % (rpm_file_list,
                                              os.path.basename(rpm))

                #Extract matrix files from the infra/iosxr-install SMU if present and copy them to extraction path
                pwd = os.getcwd()
                self.matrix_extract_path = os.path.join(pwd, "upgrade_matrix")
                if self.iso_platform_name in Iso.INSTALL_PKG_PLATFORMS:
                   matrix_pkg = "iosxr-install-"
                else:
                   matrix_pkg = "-infra-"
                if "CSC" in rpm and matrix_pkg in rpm:
                   rpm_extract_dir = tempfile.mkdtemp(dir=pwd)
                   extracted_files_list = os.path.join(rpm_extract_dir, "filelist.txt")
                   cmd = "rpm2cpio %s | (cd %s ; cpio -idmv \"*/compatibility_matrix_*\" >> %s 2>&1)" %(rpm, rpm_extract_dir, extracted_files_list)
                   run_cmd(cmd)
                   with open(extracted_files_list, 'r') as fd:
                      matrix_files = fd.read().splitlines()
                   for f in matrix_files:
                      if os.path.exists(self.matrix_extract_path) and f.endswith(".json"):
                         logger.debug("Extracted %s from the SMU %s" %(f, rpm))               
                         shutil.copy(os.path.join(rpm_extract_dir, f), self.matrix_extract_path)
                   shutil.rmtree(rpm_extract_dir, ignore_errors=True)
                   run_cmd("cd %s" % (pwd))
              else:
                # if RPM doesn't exist look at eRepo
                eRpm = rpm.split('/')[-1]
                shutil.copy(eRepo+'/'+eRpm, rpm_staging_dir)
                rpm_file_list = "%s/rpms/%s " % (rpm_file_list, eRpm)
            run_cmd("chmod 644 %s/rpms/*.rpm"%(self.iso_extract_path))
        except:
            logger.info("\n\t...Failed to copy files to staging directory")

        # Verify RPM signatures and abort gISO build if any RPM signature doesn't
        # match with ISO signature to avoid install/boot issues.
        # For older releases if RPM doesn't have signature, it will be (none)
        # so verification will not have any problem with it.
        PkgSigCheckList = []
        logger.debug("The ISO key is %s"%(iso_key))
        try:
            for pkg in input_rpms_unique:
                if global_platform_name not in pkg and not re.search('CSC[a-z][a-z]\d{5}', pkg):
                    continue
                ret=run_cmd("chroot %s rpm -qip rpms/%s | grep %s"%
                            (self.iso_extract_path, pkg, "Signature"))
                key=ret["output"].split(" ")[-1].strip('\n')
                if iso_key != "(none)": 
                   if key[8:] != iso_key:
                      logger.debug("%s key:%s doesn't match with iso image"%
                                        (os.path.basename(pkg), key[8:]))
                      PkgSigCheckList.append(os.path.basename(pkg))
                else: 
                   if key != iso_key:
                      logger.debug("%s key:%s doesn't match with iso image"%
                                        (os.path.basename(pkg), key))
                      PkgSigCheckList.append(os.path.basename(pkg))
            if PkgSigCheckList:
               logger.info("\nFollowing RPMs signature doesn't match with iso image\n")
               for pkg in PkgSigCheckList:
                  logger.info("\t(!) %s"%(pkg))

               logger.error("\n\t...RPM signature check [Failed]")
               return False, list(dup_input_rpms_set)
            #No mismatch found in RPM signatures
            logger.info("\n\t...RPM signature check [PASS]")
        except:
           logger.info("\n\t...Failed to complete RPM signature checks")

        # run compatibility check
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
                elif 'netbase' or 'rpm' or 'udev' in line:
                    logger.debug("Ignoring false dependancy")
                    continue
                elif 'signature: NOKEY' in line :
                    logger.debug("Ignoring RPM signing ")
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
            if self.shrinked_iso_extract_path and os.path.exists(self.shrinked_iso_extract_path):
                logger.debug("shrinked iso extract path %s" % self.shrinked_iso_extract_path)
                shutil.rmtree(self.shrinked_iso_extract_path)
            if self.system_image_extract_path and os.path.exists(self.system_image_extract_path):
                logger.debug("iso extract path %s" % self.system_image_extract_path)
                shutil.rmtree(self.system_image_extract_path)
            if self.iso_mount_path and os.path.exists(self.iso_mount_path):
                if os.path.ismount(self.iso_mount_path):
                    run_cmd(" umount " + self.iso_mount_path)
                    logger.debug("Unmounted iso successfully %s" % 
                                 self.iso_mount_path)
                shutil.rmtree(self.iso_mount_path)
            if self.com_iso_mount_path and os.path.exists(self.com_iso_mount_path):
                if os.path.ismount(self.com_iso_mount_path):
                    run_cmd(" umount " + self.com_iso_mount_path)
                    logger.debug("Unmounted iso successfully %s" % 
                                 self.com_iso_mount_path)
                shutil.rmtree(self.com_iso_mount_path)
        except (IOError, os.error) as why:
            logger.error("Exception why ? = " + str(why))

class Giso:
    SUPPORTED_PLATFORMS = ["asr9k", "ncs1k", "ncs1001", "ncs5k", "ncs5500", "ncs6k", "ncs560","ncs540", 'iosxrwb', 'iosxrwbd', "ncs1004", "xrv9k"]
    SUPPORTED_BASE_ISO = ["mini", "minik9"]
    SMU_CONFIG_SUMMARY_FILE = "giso_summary.txt"
    ISO_INFO_FILE = "iso_info.txt"
    VM_TYPE = ["XR", "CALVADOS", "HOST"]
    XR_CONFIG_FILE_NAME = "router.cfg"
    ZTP_INI_FILE_NAME = "ztp.ini"
    GOLDEN_STRING = "golden"
    GOLDEN_K9_STRING = "goldenk9"
    GISO_INFO_TXT = "giso_info.txt"
    NESTED_ISO_PLATFORMS = ["ncs5500", "ncs560", "ncs540", "iosxrwbd"]
    GISO_SCRIPT = "autorun"
    ISO_RPM_KEY ="(none)"
    def __init__(self):
        self.repo_path = None
        self.bundle_iso = None
        self.vm_iso = {"XR": None, "CALVADOS": None, "HOST": None}
        self.giso_dir = None
        self.vm_rpm_file_paths = {"XR": None, "CALVADOS": None, "HOST": None}
        self.xrconfig = None
        self.ztp_ini = None
        self.system_image = None
        self.supp_archs = {'HOST': ['x86_64'], 'CALVADOS': ['x86_64'],
                           'XR': ['x86_64']}
        self.giso_name = None
        self.k9sec_present = False
        self.giso_ver_label = 0 
        self.is_tar_require = False
        self.sp_info_path = None
        self.iso_wrapper_fsroot = None
        self.platform = None
        self.giso_rpm_path = DEFAULT_RPM_PATH
        self.giso_name_string = None
        self.script = None
        self.is_full_iso_require = False
        self.is_extend_giso = False
        self.xr_extgiso_rpms = [] 
        self.cal_extgiso_rpms = []
        self.host_extgiso_rpms = []
        self.gisoExtendRpms = 0
        self.ExtendRpmRepository = None
        self.is_skip_dep_check = False
        self.is_x86_only = False

        self.xrconfig_md5sum = None
        self.ztp_ini_md5sum = None
        self.script_md5sum = None

        self.matrix_extract_path = None
        
    #
    # Giso object Setter Api's
    #

    def set_giso_info(self, iso_path):
        self.bundle_iso = Iso() 
        self.bundle_iso.set_iso_info(iso_path)
        plat = self.get_bundle_iso_platform_name()
        if self.is_extend_giso:
           self.do_extend_giso(self.bundle_iso.iso_mount_path)
        if OPTIMIZE_CAPABLE and not args.optimize:
            self.giso_rpm_path = DEFAULT_RPM_PATH
            logger.debug("Golden ISO RPM_PATH: %s" % self.giso_rpm_path)
        elif OPTIMIZE_CAPABLE and args.optimize:
            if plat in Giso.NESTED_ISO_PLATFORMS :
                # This was interim change for 651 release for fretta only
                if "6.5.1." in self.bundle_iso.get_iso_version() or '6.5.1' == self.bundle_iso.get_iso_version():
                    print(self.bundle_iso.get_iso_version())
                    self.giso_rpm_path = SIGNED_651_NCS5500_RPM_PATH
                else :
                    self.giso_rpm_path = SIGNED_NCS5500_RPM_PATH
            else :
                self.giso_rpm_path = SIGNED_RPM_PATH
            logger.debug("Optimised Golden ISO RPM_PATH: %s"
                         % self.giso_rpm_path)
        else :
            # Build Server is not capable of otimize the Golden ISO
            self.giso_rpm_path = DEFAULT_RPM_PATH
            logger.debug("Golden ISO RPM_PATH: %s" % self.giso_rpm_path)


        if plat in Giso.NESTED_ISO_PLATFORMS:
            logger.debug("Skipping the top level iso wrapper")
            self.iso_wrapper_fsroot = self.get_bundle_iso_extract_path()
            logger.debug("Iso top initrd path %s" % self.iso_wrapper_fsroot)
            self.system_image = "%s/system_image.iso" % cwd
            shutil.copyfile("%s/iso/system_image.iso" % self.iso_wrapper_fsroot,
                            self.system_image)
            logger.debug("Intermal System_image.iso %s"
                         % iso_path)
            self.bundle_iso.__exit__(None, None, None)
            self.bundle_iso = Iso() 
            self.bundle_iso.set_iso_info(self.system_image)
    def gisoExtendExtractSignedRpmPath(self, repo):
        '''
           Find the RPM location and extract rpms
           giso is of SIGNED_RPM_PATH
        '''
        pwd = os.getcwd()
        print("working dir %s"%(pwd))
        optimised_rpm_path = tempfile.mkdtemp(dir=pwd)
        if os.path.exists(optimised_rpm_path):
           #print("ISO MOUNTED AT  %s"%(IsoMountPath))
           os.chdir(optimised_rpm_path)
           run_cmd("zcat -f  %s | cpio -idu"%(repo+"/boot/initrd.img"))
           run_cmd("isoinfo -R -i iso/system_image.iso -x /boot/initrd.img >initrd2.img")
           run_cmd("zcat -f initrd2.img | cpio -idu")
           os.chdir(pwd)
           return optimised_rpm_path
        else:
           logger.error("Failed to create directory to extract RPMs")
           return None
    # Extend the gISO, if input is existing gISO instead of mini.iso
    # it appends rpms in repository to the existing gISO
    # so we can build gISO incrementally with having only
    # new set of RPMs needed in repository, without worrying rpms
    # present in gISO
    #
    def do_extend_giso(self, GisoMountDir):
        '''
        Look at the given gISO mounted directory and check what all
        rpms exist in the given gISO and copy them to repo for
        extending the gISO
        '''

        # Find RPM path in the Giso
        RpmPathInGiso = ""
        with open(GisoMountDir+"/giso_info.txt", 'r') as fd:
             GisoInfo = fd.read()
        for line in GisoInfo.split('\n'):
            if line.split(' ')[0] == 'RPM_PATH:':
               RpmPathInGiso = line.split(' ')[-1]
               break
        logger.debug("RPM location in the given gISO %s"%(RpmPathInGiso))

        if DEFAULT_RPM_PATH == RpmPathInGiso:
           iso_rpm_path = GisoMountDir 
        elif SIGNED_RPM_PATH == RpmPathInGiso:
            iso_rpm_path = self.get_bundle_iso_extract_path()
        elif SIGNED_NCS5500_RPM_PATH == RpmPathInGiso:
             iso_rpm_path = self.gisoExtendExtractSignedRpmPath(GisoMountDir)
        else:
           print("Coudn't determine RPM location in input gISO, failed extend gISO\n")
           return False
        # create repository for giso rpms
        pwd = cwd
        extended_rpm_dir = tempfile.mkdtemp(dir=pwd) 
        if extended_rpm_dir is None:
           logger.info("Failed to create staging directory for RPMS")
           return False

        logger.info("Following RPMS found in the input gISO")
        if os.path.exists(iso_rpm_path+"/xr_rpms"): 
           xr_extgiso_rpms = glob.glob(iso_rpm_path+"/xr_rpms/*")
           for rpm in xr_extgiso_rpms:
               self.xr_extgiso_rpms.append(os.path.basename(rpm))
               logger.info("\t%s"%(os.path.basename(rpm)))
           ret=run_cmd("cp %s/xr_rpms/* %s/"%(iso_rpm_path, extended_rpm_dir))
           self.gisoExtendRpms += len(self.xr_extgiso_rpms)


        if os.path.exists(iso_rpm_path+"/calvados_rpms"):
           cal_extgiso_rpms = glob.glob(iso_rpm_path+"/calvados_rpms/*")
           for rpm in cal_extgiso_rpms:
               self.cal_extgiso_rpms.append(os.path.basename(rpm))
               logger.info("\t%s"%(os.path.basename(rpm)))
           ret=run_cmd("cp %s/calvados_rpms/* %s/"%(iso_rpm_path, extended_rpm_dir))
           self.gisoExtendRpms += len(self.cal_extgiso_rpms)

        if os.path.exists(iso_rpm_path+"/host_rpms"):
           host_extgiso_rpms = glob.glob(iso_rpm_path+"/host_rpms/*")
           for rpm in host_extgiso_rpms:
               self.host_extgiso_rpms.append(os.path.basename(rpm))
               logger.info("\t%s"%(os.path.basename(rpm)))
           ret=run_cmd("cp %s/host_rpms/* %s/"%(iso_rpm_path, extended_rpm_dir))
           self.gisoExtendRpms += len(self.host_extgiso_rpms)
        self.ExtendRpmRepository = extended_rpm_dir

        # if input is optimised gISO then we have to extract rpms from
        # initrd so rpm path is not iso mount path, needs to be cleaned
        if SIGNED_NCS5500_RPM_PATH == RpmPathInGiso:
           shutil.rmtree(iso_rpm_path)

    def do_extend_clean(self, eRepo):
        '''
            clear extend specific things
        '''
        logger.debug("Extend gISO cleaned")
        if eRepo is not None and os.path.exists(eRepo): 
           shutil.rmtree(eRepo)
           pass

    def set_iso_rpm_key(self, fs_root):
        '''
           get the GPG key and keep it for RPM signature key
           verification.
        '''
        if os.path.isfile(fs_root+"/boot/certs/public-key.gpg"):
           ret = run_cmd("chroot %s rpm --import %s"%(fs_root, "boot/certs/public-key.gpg"))
           ret = run_cmd("chroot %s rpm -qa | grep %s"%(fs_root, "gpg-pubkey"))
           key = ret["output"].split("-")[-2]
           self.ISO_RPM_KEY = key
           logger.debug("The ISO Key is %s\n"%(key))
        else:
           logger.debug("Failed to find public-key.gpg file")

    def set_vm_rpm_file_paths(self, rpm_file_paths, vm_type):
        self.vm_rpm_file_paths[vm_type] = rpm_file_paths
        
    def set_xrconfig(self, xrconfig):
        self.xrconfig = xrconfig

    def set_ztpini(self, ztp_ini):
        self.ztp_ini = ztp_ini

    def set_repo_path(self, repo_path):
        self.repo_path = repo_path

    def set_giso_ver_label(self, ver_label):
        self.giso_ver_label = ver_label 

    def set_sp_info_file_path(self, sp_info_path):
        self.sp_info_path = sp_info_path

    def set_script(self, script):
        self.script = script

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

    def set_xrconfig_md5sum(self, xrconfig_md5sum):
        self.xrconfig_md5sum = xrconfig_md5sum
    
    def set_ztp_ini_md5sum(self, ztp_ini_md5sum):
        self.ztp_ini_md5sum = ztp_ini_md5sum

    def set_script_md5sum(self, script_md5sum):
        self.script_md5sum = script_md5sum
    #
    # Giso object getter Api's
    #
    def get_bundle_iso_name(self):
        return self.bundle_iso.get_iso_name()

    def get_bundle_iso_version(self):
        return self.bundle_iso.get_iso_version()

    def get_bundle_iso_platform_name(self):
        if not self.platform :
            self.platform = self.bundle_iso.get_iso_platform_name()
        return self.platform

    def get_bundle_iso_extract_path(self):
        return self.bundle_iso.get_iso_extract_path()

    def get_bundle_shrinked_iso_extract_path(self):
        return self.bundle_iso.get_shrinked_iso_extract_path()

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
                "/etc/init.d/cisco-instance/fretta/calvados_bootstrap.cfg"\
                % fs_root
            search_str = ''
            if os.path.exists(bootstrap_file):
                for x in list(self.supp_archs.keys()):
                    if "XR" in x:
                        search_str = "XR_SUPPORTED_ARCHS"
                    if "HOST" in x or "CALVADOS" in x:
                        search_str = "CALV_SUPPORTED_ARCHS"
                    try:
                        result = run_cmd("grep %s %s" % (search_str, 
                                                         bootstrap_file))
                        self.supp_archs[x] = \
                            list(map(lambda y: y.replace('\n', ''),
                                result['output'].split('=')[1].split(',')))
                        logger.debug('vm_type %s Supp Archs: ' % x)
                        list(map(lambda y: logger.debug("%s" % y), self.supp_archs[x]))
                    except Exception as e:
                        logger.debug(str(e))
            else:
                logger.debug("Failed to find %s file. Using Defaults archs" % 
                             bootstrap_file)
                
        logger.debug("Supp arch query for vm_type %s" % vm_type)
        list(map(lambda y: logger.debug("%s" % y), self.supp_archs[vm_type]))
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
            mpath = iso.get_matrix_extract_path()
            if mpath:
               self.matrix_extract_path = mpath
            self.vm_iso[vm_type] = iso
        else:
            iso = self.vm_iso[vm_type]
        return iso.do_compat_check(self.repo_path, input_rpms,
                                   self.ISO_RPM_KEY, self.ExtendRpmRepository)
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

    def is_new_format_giso_name_supported(self, version):

        retval = False 
        version_tupple = version.split('.')

        if int(version_tupple[0]) > 6:
            retval = True
        elif int(version_tupple[0]) == 6 and int(version_tupple[1]) > 5 :
            retval = True
        elif len(version_tupple) == 3 and int(version_tupple[0]) == 6 and \
             int(version_tupple[1]) == 5 and int(version_tupple[2]) == 2:
            retval = True
        elif len(version_tupple) >= 3 and int(version_tupple[0]) == 6 and \
             int(version_tupple[1]) == 5 and int(version_tupple[2]) > 2:
            retval = True
        elif len(version_tupple) == 3 and int(version_tupple[0]) == 6 and \
             int(version_tupple[1]) == 3 and int(version_tupple[2]) == 3:
            retval = True
        return retval

    def giso_optional_label_supported(self):
        version = self.get_bundle_iso_version()
        version = version.split('.')
        if int(version[0]) ==7:
           if int(version[1])==0 and int(version[2]) >1:
              return True
           elif int(version[1])>=1 and int(version[2]) >= 1:
              return True
        elif int(version[0])>7:
              return True
        return False
        
    def prepare_giso_info_txt(self, iso, sp_name):
        iso_name = iso.get_iso_name()

        if "-minik9-" in iso_name or self.k9sec_present:
            golden_string = Giso.GOLDEN_K9_STRING
        elif "-mini-" in iso_name:
            golden_string = Giso.GOLDEN_STRING
        elif self.is_extend_giso:
             if self.k9sec_present:
                golden_string = Giso.GOLDEN_K9_STRING
             else:
                golden_string = Giso.GOLDEN_STRING
        else:
            logger.info("Given iso(%s.%s) is not supported" % (iso_name, "iso"))
            return -1

        iso_name_tupple = iso_name.split('-')
        giso_name_string = '%s-%s-%s' % (iso_name_tupple[0], golden_string,
                                         iso_name_tupple[2])

        self.giso_name_string = giso_name_string
        # update iso_info.txt file with giso name
        with open("%s/%s" % (self.giso_dir, iso.ISO_INFO_FILE), 'r') as f:
            iso_info_raw = f.read()

        # Replace the iso name with giso string
        iso_info_raw = iso_info_raw.replace(iso_name, giso_name_string)

        with open("%s/%s" % (self.giso_dir, iso.ISO_INFO_FILE), 'w') as f:
            f.write(iso_info_raw)

        giso_pkg_fmt_ver = GISO_PKG_FMT_VER
        name = giso_name_string
        version = '%s-%s' % (iso.get_iso_version(), self.giso_ver_label)
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
        mdata = yaml.safe_load(fd)
        fd.close()

        with open("%s/%s" % (self.giso_dir, Giso.GISO_INFO_TXT), 'w') as f:
            f.write(giso_info)
            f.write("RPM_PATH:  %s"%(self.giso_rpm_path))
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
            # if sp is present its added to yaml file to be displayed as part of
            # show install package <giso>
            if sp_name is not None:
                tmp_dict = {}
                tmp_dict['sp in golden ISO'] = os.path.basename(sp_name)
                rpms_list.append(tmp_dict) 
            # if XR Config file present then add the name
            if self.xrconfig is not None:
                f.write("\n\nXR-Config file:\n")
                f.write("%s %s" % (self.xrconfig_md5sum, Giso.XR_CONFIG_FILE_NAME))

            # if ztp ini file present then add the name
            if self.ztp_ini is not None:
                f.write("\n\nZTP INI file:\n")
                f.write("%s %s" % (self.ztp_ini_md5sum, Giso.ZTP_INI_FILE_NAME))
             
            # if autorun script present then add the name
            if self.script is not None:
                f.write("\n\nUser script:\n")
                f.write("%s %s" % (self.script_md5sum, Giso.GISO_SCRIPT))

        iso_mdata = mdata['iso_mdata']
        iso_mdata['name'] = "%s-%s"%(giso_name_string, iso.get_iso_version())
        iso_mdata['bundle_name'] = "%s-%s"%(iso_name, iso.get_iso_version())
        if not self.giso_ver_label and self.giso_optional_label_supported():
            iso_mdata['label'] = ""
        else:
            iso_mdata['label'] = self.giso_ver_label
        mdata['iso_mdata'] = iso_mdata
        mdata['golden ISO rpms'] = rpms_list
        fd = open(file_yaml, 'w')
        fd.write(yaml.dump(mdata, default_flow_style=False))
        fd.close()

 
        #New format GISO Name:(<platform>-<golden(k9)>-x-<version>-<label>.iso)
        if self.is_new_format_giso_name_supported(iso.get_iso_version()):
           if not self.giso_ver_label and self.giso_optional_label_supported():
              logger.info('Info: Label is not specified so ' 
                          'Golden ISO will not have any label ')
              self.giso_name = '%s-%s.%s' % (giso_name_string,
                                      iso.get_iso_version(), "iso")
           else:
              if not self.giso_ver_label:
                 logger.info('Info: Golden ISO label is not specified '
                          'so defaulting to 0')
              self.giso_name = '%s-%s-%s.%s' % (giso_name_string,
                                          iso.get_iso_version(),
                                          self.giso_ver_label, "iso")
        #Old format GISO Name:(<platform-name>-goldenk9-x.iso-<version>.<label>)
        else : 
            if not self.giso_ver_label and self.giso_optional_label_supported():
               self.giso_name = '%s.%s-%s' % (giso_name_string, "iso",
                                        iso.get_iso_version())
               logger.info('Info: Label is not specified so '
                          'Golden ISO will not have any label') 
            else:
               logger.info('Info: Golden ISO label is not specified '
                          'so defaulting to 0')
               self.giso_name = '%s.%s-%s.%s' % (giso_name_string, "iso",
                                           iso.get_iso_version(), 
                                           self.giso_ver_label)

    def update_grub_cfg(self, iso):
        # update grub.cfg file with giso_boot parameter 
        lines = []
        for grub_file in iso.GRUB_FILES:
            with open("%s/%s" % (self.giso_dir, grub_file), 'r') as fd:
                for line in fd:
                    if "root=" in line and "noissu" in line:
                        line = line.rstrip('\n') + " giso_boot\n"
                    lines.append(line)

            # write updated grub.cfg
            with open("%s/%s" % (self.giso_dir, grub_file), 'w') as fd:
                for line in lines:
                    fd.write(line)

    def get_inner_initrd(self, giso_dir):
        pwd = cwd
        initrd_extract_path = tempfile.mkdtemp(dir=pwd)
        if initrd_extract_path is not None:
            os.chdir(initrd_extract_path)
            run_cmd("zcat -f %s%s | cpio -id" % (giso_dir, Iso.ISO_INITRD_RPATH))
            os.chdir(pwd)
        
        system_image_iso_path = "%s/%s" % (initrd_extract_path, "iso/system_image.iso")
        if os.path.exists(system_image_iso_path):
            pwd = cwd
            system_image_iso_extract_path = tempfile.mkdtemp(dir=pwd)
            if system_image_iso_extract_path is not None:
                readiso(system_image_iso_path, system_image_iso_extract_path)
        
        pwd = cwd
        inner_initrd_extract_path = tempfile.mkdtemp(dir=pwd)
        if inner_initrd_extract_path is not None:
            os.chdir(inner_initrd_extract_path)
            run_cmd("zcat -f %s%s | cpio -id" % (system_image_iso_extract_path, Iso.ISO_INITRD_RPATH))
            os.chdir(pwd)

        if initrd_extract_path is not None:
            run_cmd("rm -rf " + initrd_extract_path)

        if system_image_iso_extract_path is not None:
            run_cmd("rm -rf " +  system_image_iso_extract_path)

        return inner_initrd_extract_path

    def get_initrd(self, giso_dir):
        pwd = cwd
        initrd_extract_path = tempfile.mkdtemp(dir=pwd)
        if initrd_extract_path is not None:
            os.chdir(initrd_extract_path)
            run_cmd("zcat -f %s%s | cpio -id" % (giso_dir, Iso.ISO_INITRD_RPATH))
            os.chdir(pwd)

        return initrd_extract_path
        
    # get base rpm of the spiritboot or hostos
    def get_base_rpm(self, plat, vm_type, rpm_file, giso_dir, giso_repo_path):

        base_rpm_path = None
        if plat in Giso.NESTED_ISO_PLATFORMS:
            initrd_path = self.get_inner_initrd(giso_dir)
        else:
            initrd_path = self.get_initrd(giso_dir)

        if rpm_file.endswith('.rpm'):
            mre = re.search(r'(.*)-(.*)-(.*)\.(.*)(\.rpm)', rpm_file)
            if mre:
                s_rpm_name = mre.groups()[0]
                s_rpm_ver = mre.groups()[1]
                s_rpm_rel = mre.groups()[2]
                s_rpm_arch = mre.groups()[3]

        if vm_type == HOST_SUBSTRING:
            '''
            if s_rpm_arch == "x86_64":
                host_iso_path = "%s/%s" % (initrd_path, "iso/host.iso")
                if os.path.exists(host_iso_path):
                    pwd = cwd
                    host_iso_extract_path = tempfile.mkdtemp(dir=pwd)
                    if host_iso_extract_path is not None:
                        readiso(host_iso_path, host_iso_extract_path)
                        rpms_path = glob.glob('%s/rpm/*' % host_iso_extract_path)
                        for rpm_path in rpms_path:
                            if HOSTOS_SUBSTRING in os.path.basename(rpm_path): 
                                shutil.copy(rpm_path, giso_repo_path)
                                base_rpm_path = rpm_path
                                break
                        run_cmd("rm -rf " + host_iso_extract_path)
            '''

            if s_rpm_arch == "arm":
                nbi_initrd_img_name = "%s-sysadmin-nbi-initrd.img" % (plat)
                nbi_initrd_path = "%s/%s/%s" % (initrd_path, "nbi-initrd", nbi_initrd_img_name)
                pwd = cwd
                nbi_initrd_extract_path = tempfile.mkdtemp(dir=pwd)
                if nbi_initrd_extract_path is not None:
                    os.chdir(nbi_initrd_extract_path)
                    run_cmd("zcat -f %s | cpio -id" % (nbi_initrd_path))
                    os.chdir(pwd)
                    rpms_path = glob.glob('%s/rpm/*' % nbi_initrd_extract_path)
                    for rpm_path in rpms_path:
                        if (HOSTOS_SUBSTRING in rpm_path) and ".host." in rpm_path: 
                            shutil.copy(rpm_path, giso_repo_path)
                            base_rpm_path = rpm_path
                            break
                    run_cmd("rm -rf " + nbi_initrd_extract_path)


        elif vm_type == SYSADMIN_SUBSTRING:
            '''
            if s_rpm_arch == "x86_64":
                sysadmin_iso_path = "%s/%s/%s%s" % (initrd_path, "iso", plat, "-sysadmin.iso")
                if os.path.exists(sysadmin_iso_path):
                    pwd = cwd
                    sysadmin_iso_extract_path = tempfile.mkdtemp(dir=pwd)
                    if sysadmin_iso_extract_path is not None:
                        readiso(sysadmin_iso_path, sysadmin_iso_extract_path)
                        rpms_path = glob.glob('%s/rpm/calvados/*' % sysadmin_iso_extract_path)
                        for rpm_path in rpms_path:
                            if HOSTOS_SUBSTRING in os.path.basename(rpm_path): 
                                shutil.copy(rpm_path, giso_repo_path)
                                base_rpm_path = rpm_path
                                break
                        run_cmd("rm -rf " + sysadmin_iso_extract_path)
            '''
            if s_rpm_arch == "arm":
                nbi_initrd_img_name = "%s-sysadmin-nbi-initrd.img" % (plat)
                nbi_initrd_path = "%s/%s/%s" % (initrd_path, "nbi-initrd", nbi_initrd_img_name)
                pwd = cwd
                nbi_initrd_extract_path = tempfile.mkdtemp(dir=pwd)
                if nbi_initrd_extract_path is not None:
                    os.chdir(nbi_initrd_extract_path)
                    run_cmd("zcat -f %s | cpio -id" % (nbi_initrd_path))
                    os.chdir(pwd)
                    rpms_path = glob.glob('%s/rpm/*' % nbi_initrd_extract_path)
                    for rpm_path in rpms_path:
                        if (HOSTOS_SUBSTRING in rpm_path) and ".admin." in rpm_path: 
                            shutil.copy(rpm_path, giso_repo_path)
                            base_rpm_path = rpm_path
                            break
                    run_cmd("rm -rf " + nbi_initrd_extract_path)
        elif vm_type == XR_SUBSTRING:
            xr_iso_path = "%s/%s/%s%s" % (initrd_path, "iso", plat, "-xr.iso")
            if os.path.exists(xr_iso_path):
                pwd = cwd
                xr_iso_extract_path = tempfile.mkdtemp(dir=pwd)
                if xr_iso_extract_path is not None:
                    readiso(xr_iso_path, xr_iso_extract_path)
                    rpms_path = glob.glob('%s/rpm/xr/*' % xr_iso_extract_path)
                    for rpm_path in rpms_path:
                        if SPIRIT_BOOT_SUBSTRING in os.path.basename(rpm_path): 
                            shutil.copy(rpm_path, giso_repo_path)
                            base_rpm_path = rpm_path
                            break
                    run_cmd("rm -rf " + xr_iso_extract_path)
        
        if initrd_path is not None:
            run_cmd("rm -rf " + initrd_path)
            
        return base_rpm_path

    def update_bzimage(self, giso_dir):
        script_dir = os.path.abspath( os.path.dirname( __file__ ))
        bzImage_712_path = script_dir + "/" + BZIMAGE_712
        if os.path.exists(bzImage_712_path):
            logger.debug("Replacing top level bzImage in GISO with %s to support PXE boot of >2GB ISO" %(bzImage_712_path))
            cmd="cp %s %s/%s" %(bzImage_712_path, giso_dir, "boot/bzImage")
            run_cmd(cmd)

    #
    # Build Golden ISO.
    #

    def build_giso(self, rpm_db, iso_path):
        rpms = False
        config = False 
        ztp_ini = False
        service_pack = False
        pwd = cwd
        rpm_count = 0
        repo = ""
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
        plat = self.get_bundle_iso_platform_name()
        if plat in Giso.NESTED_ISO_PLATFORMS:
            self.bundle_iso.__exit__(None, None, None)
            self.bundle_iso = Iso() 
            self.bundle_iso.set_iso_info(iso_path)

        shutil.copytree(self.bundle_iso.get_iso_mount_path(), self.giso_dir)

        logger.info("Summary .....")
        duplicate_xr_rpms = []
        duplicate_calv_rpms = []
        duplicate_host_rpms = []
        with open('rpms_packaged_in_giso.txt',"w") as fdr:
            for vm_type in Giso.VM_TYPE:
                rpm_files = self.vm_rpm_file_paths[vm_type]
                if rpm_files is not None:
                    giso_repo_path = "%s/%s_rpms" % (self.giso_dir, 
                                                     str(vm_type).lower())
                    try:
                        os.mkdir(giso_repo_path)
                    except:
                        if self.is_extend_giso: 
                           logger.debug("Info: extending, giso directory exist") 
                        else:
                           raise
                    if vm_type == CALVADOS_SUBSTRING:
                        vm_type = SYSADMIN_SUBSTRING
                    logger.info("\n%s rpms:" % vm_type)

                    for rpm_file in rpm_files:
                        rpm_file_basename = os.path.basename(rpm_file)
                        if vm_type == HOST_SUBSTRING: 
                            if (plat in rpm_file_basename) and (HOSTOS_SUBSTRING in rpm_file_basename): 
                                host_base_rpm = self.get_base_rpm(plat, vm_type, rpm_file_basename, self.giso_dir, giso_repo_path)
                                logger.debug("\nbase rpm of %s: %s" % (rpm_file, host_base_rpm))

                            duplicate_present = False
                            if rpm_db.vm_sp_rpm_file_paths[HOST_SUBSTRING] is not None:
                                for sp_rpm_file in rpm_db.vm_sp_rpm_file_paths[HOST_SUBSTRING]:
                                    if rpm_file in sp_rpm_file:
                                        duplicate_host_rpms.append(rpm_file)
                                        duplicate_present = True
                                        break
                                if duplicate_present:
                                    continue

                        if vm_type == SYSADMIN_SUBSTRING: 
                            if (plat in rpm_file_basename) and (HOSTOS_SUBSTRING in rpm_file_basename): 
                                sysadmin_base_rpm = self.get_base_rpm(plat, vm_type, rpm_file_basename, self.giso_dir, giso_repo_path)
                                logger.debug("\nbase rpm of %s: %s" % (rpm_file, sysadmin_base_rpm))

                            duplicate_present = False
                            if rpm_db.vm_sp_rpm_file_paths[CALVADOS_SUBSTRING] is not None:
                                for sp_rpm_file in rpm_db.vm_sp_rpm_file_paths[CALVADOS_SUBSTRING]:
                                    if rpm_file in sp_rpm_file:
                                        duplicate_calv_rpms.append(rpm_file)
                                        duplicate_present = True
                                        break
                                if duplicate_present:
                                    continue

                        if vm_type == XR_SUBSTRING: 
                            '''
                            if (plat in rpm_file_basename) and (SPIRIT_BOOT_SUBSTRING in rpm_file_basename): 
                                xr_base_rpm = self.get_base_rpm(plat, vm_type, rpm_file_basename, self.giso_dir, giso_repo_path)
                                logger.debug("\nbase rpm of %s: %s" % (rpm_file, xr_base_rpm))
                            '''

                            duplicate_present = False
                            if rpm_db.vm_sp_rpm_file_paths[XR_SUBSTRING] is not None:
                                for sp_rpm_file in rpm_db.vm_sp_rpm_file_paths[XR_SUBSTRING]:
                                    if rpm_file in sp_rpm_file:
                                        duplicate_xr_rpms.append(rpm_file)
                                        duplicate_present = True
                                        break
                                if duplicate_present:
                                    continue
                        rpm_count += 1
                        if self.ExtendRpmRepository and os.path.isdir(self.ExtendRpmRepository):
                           self.repo_path.append(self.ExtendRpmRepository)
                        for rpath in self.repo_path:
                            if os.path.isfile(rpath+'/'+rpm_file):
                               repo=rpath 
                        shutil.copy('%s/%s' % (repo, rpm_file),
                                    giso_repo_path)
                        logger.info('\t%s' % (os.path.basename(rpm_file)))
                        fdr.write("%s\n"%os.path.basename(rpm_file))
                        rpms = True
                        if "-k9sec-" in rpm_file:
                            self.k9sec_present = True
                # TODO: Print duplicate
                if vm_type == HOST_SUBSTRING and duplicate_host_rpms:
                    logger.debug("\nSkipped following duplicate host rpms from repo\n")
                    list(map(lambda file_name: logger.debug("\t(-) %s" % file_name), duplicate_host_rpms))
                if vm_type == SYSADMIN_SUBSTRING and duplicate_calv_rpms:
                    logger.debug("\nSkipped following duplicate calvados rpm from repo\n")
                    list(map(lambda file_name: logger.debug("\t(-) %s" % file_name), duplicate_calv_rpms))
                if vm_type == XR_SUBSTRING and duplicate_xr_rpms:
                    logger.debug("\nSkipped following duplicate xr rpm from repo\n")
                    list(map(lambda file_name: logger.debug("\t(-) %s" % file_name), duplicate_xr_rpms))

        if self.sp_info_path is not None:
            for vm_type in Giso.VM_TYPE:
                if vm_type ==  SYSADMIN_SUBSTRING:
                    vm_type = CALVADOS_SUBSTRING
                giso_repo_path = "%s/%s_rpms" % (self.giso_dir, 
                                                     str(vm_type).lower())

                if rpm_db.vm_sp_rpm_file_paths[vm_type] and not os.path.isdir(giso_repo_path):
                    os.mkdir(giso_repo_path)
                for sp_rpm_file in rpm_db.vm_sp_rpm_file_paths[vm_type]:
                    rpm_count += 1
                    shutil.copy('%s' % (sp_rpm_file), giso_repo_path)

                    # If sp has hostos rpm then extarct hostos base rpm and copy it to giso_repo_path
                    rpm_file_basename = os.path.basename(sp_rpm_file)
                    if vm_type == HOST_SUBSTRING: 
                        if (plat in rpm_file_basename) and (HOSTOS_SUBSTRING in rpm_file_basename): 
                            host_base_rpm = self.get_base_rpm(plat, vm_type, rpm_file_basename, self.giso_dir, giso_repo_path)
                            logger.debug("\nbase rpm of %s: %s" % (sp_rpm_file, host_base_rpm))

                    if vm_type == CALVADOS_SUBSTRING: 
                        vmt = SYSADMIN_SUBSTRING
                        if (plat in rpm_file_basename) and (HOSTOS_SUBSTRING in rpm_file_basename): 
                            sysadmin_base_rpm = self.get_base_rpm(plat, vmt, rpm_file_basename, self.giso_dir, giso_repo_path)
                            logger.debug("\nbase rpm of %s: %s" % (sp_rpm_file, sysadmin_base_rpm))
  

        if rpm_count > MAX_RPM_SUPPORTED_BY_INSTALL:
            logger.error("\nError: Total number of supported rpms in the "
                         "repository is %s.\nIt is exceeding the number "
                         "of rpms supported by install infra.\nPlease remove "
                         "some rpms and make sure total number doesn't exceed "
                         "%s" % (rpm_count, MAX_RPM_SUPPORTED_BY_INSTALL))
            rpm_db.cleanup_tmp_sp_data()
            sys.exit(-1)

        if self.xrconfig:
            logger.info("\nXR Config file:")
            logger.info('\t%s' % Giso.XR_CONFIG_FILE_NAME)
            shutil.copy(self.xrconfig, "%s/%s" % (self.giso_dir, 
                                                  Giso.XR_CONFIG_FILE_NAME))
            config = True
            cmd = "md5sum %s" %(self.xrconfig)
            result = run_cmd(cmd)
            config_md5sum = result["output"].split(" ")[0]
            logger.debug("Md5sum of Config: %s" %(config_md5sum))
            self.set_xrconfig_md5sum(config_md5sum)

        if self.ztp_ini:
            logger.info("\nZTP INI file:")
            logger.info('\t%s' % Giso.ZTP_INI_FILE_NAME)
            shutil.copy(self.ztp_ini, "%s/%s" % (self.giso_dir, 
                                                  Giso.ZTP_INI_FILE_NAME))
            ztp_ini = True
            cmd = "md5sum %s" %(self.ztp_ini)
            result = run_cmd(cmd)
            ztp_ini_md5sum = result["output"].split(" ")[0]
            logger.debug("Md5sum of ztp_ini: %s" %(ztp_ini_md5sum))
            self.set_ztp_ini_md5sum(ztp_ini_md5sum)

        if self.sp_info_path:
            #logger.info('\t%s' % self.sp_info_path)
            logger.info("\nService Pack:")
            logger.info('\t%s' % os.path.basename(rpm_db.latest_sp_name))
            shutil.copy(self.sp_info_path, "%s/%s" % (self.giso_dir, 
                                                      os.path.basename(self.sp_info_path)))
            service_pack = True

        if self.script:
            logger.info("\nUser script:")
            logger.info('\t%s' % Giso.GISO_SCRIPT)
            shutil.copy(self.script, "%s/%s" % (self.giso_dir, 
                                                  Giso.GISO_SCRIPT))
            cmd = "chmod +x %s/%s"%(self.giso_dir, Giso.GISO_SCRIPT)
            script = True
            cmd = "md5sum %s" %(self.script)
            result = run_cmd(cmd)
            script_md5sum = result["output"].split(" ")[0]
            logger.debug("Md5sum of script: %s" %(script_md5sum))
            self.set_script_md5sum(script_md5sum)
 
        rpm_db.cleanup_tmp_sp_data()

        if plat == "iosxrwbd" and hasattr(args, 'optimize') and not args.optimize:
            os.symlink("bzImage", "%s/boot/bzImage_GISO" %(self.giso_dir))

        if not (rpms or service_pack or config or script or ztp_ini):
            logger.info("Final rpm list or service pack is Zero and "
                        "there is no XR config/user script specified")
            logger.info("Nothing to do")
            return -1
        else:
            self.prepare_giso_info_txt(self.bundle_iso, rpm_db.latest_sp_name)
            self.update_grub_cfg(self.bundle_iso)
            shutil.copy(logfile, '%s/%s' % (self.giso_dir, 
                                            Giso.SMU_CONFIG_SUMMARY_FILE))
            #Copy the upgrade matrix files to the top level of GISO
            dest_dir = os.path.join(self.giso_dir, "upgrade_matrix")
            src_dir = self.matrix_extract_path
            if src_dir and os.path.exists(src_dir):
               if not os.path.exists(dest_dir):
                  shutil.copytree(src_dir, dest_dir)
               shutil.rmtree(src_dir, ignore_errors=True)

            #update bzimage for 663/664/702 fretta to support >2GB ISO
            if plat == "ncs5500" and ((self.get_bundle_iso_version() == "6.6.3") or
                                      (self.get_bundle_iso_version() == "6.6.4") or 
                                      (self.get_bundle_iso_version() == "7.0.2")):
               self.update_bzimage(self.giso_dir)

            if OPTIMIZE_CAPABLE and args.optimize:
                # If optimised GISO, 
                # 1. push RPMs in system_image for nested platform
                #    push RPMS to initrd for non nested platfomr
                # 2. recreate initrd
                # 3. Sign initrd
                # 4. Move new signature and initrd in this dir 
                # 5. Create Giso
                if plat in Giso.NESTED_ISO_PLATFORMS :
                    self.build_system_image()
                    if self.giso_rpm_path is SIGNED_NCS5500_RPM_PATH:
                       self.recreate_initrd_nested_platform_7xx()
                    else:
                       self.recreate_initrd_nested_platform()
                else :
                    self.recreate_initrd_non_nested_platform()
                self.update_signature(self.giso_dir)
                if os.path.exists(self.giso_dir+"/boot/grub/stage2_eltorito"):
                    cmd = "mkisofs -R -b boot/grub/stage2_eltorito -no-emul-boot -input-charset utf-8 \
                        -boot-load-size 4 -boot-info-table -o %s %s" % (self.giso_name, self.giso_dir)
                else:
                    cmd = "mkisofs -R -o %s %s" % (self.giso_name, self.giso_dir)
                run_cmd(cmd)

            else:
                if os.path.exists(self.giso_dir+"/boot/grub/stage2_eltorito"):
                    cmd = "mkisofs -R -b boot/grub/stage2_eltorito -no-emul-boot -input-charset utf-8 \
                            -boot-load-size 4 -boot-info-table -o %s %s" \
                            % (self.giso_name, self.giso_dir)
                else :
                    cmd = "mkisofs -R -o %s %s" % (self.giso_name, self.giso_dir)
                run_cmd(cmd)
        return 0
            
    def build_system_image(self):
        """ extract system_image """

        pwd = cwd
        self.system_image_extract_path = tempfile.mkdtemp(dir=pwd)

        if self.system_image_extract_path is not None:
            readiso(self.system_image, self.system_image_extract_path)
            os.chdir(self.system_image_extract_path)

            rpms_path = glob.glob('%s/*_rpms' % self.giso_dir)
            if len(rpms_path):
                # Move the RPMS to system_image.iso content
                run_cmd("mv  -f %s/*_rpms %s " % (self.giso_dir, self.system_image_extract_path))

            # Move giso metadata to system_image.iso content
            run_cmd("cp  -f %s/giso_* %s " % (self.giso_dir, self.system_image_extract_path))
            if os.path.isfile(self.giso_dir+"/sp_info.txt"):
               run_cmd("cp  -f %s/sp_* %s " % (self.giso_dir, self.system_image_extract_path))
            if os.path.isfile(self.giso_dir+"/"+Giso.XR_CONFIG_FILE_NAME):
               run_cmd("cp  -f %s/%s %s " % (self.giso_dir, Giso.XR_CONFIG_FILE_NAME, self.system_image_extract_path))
            if os.path.isfile(self.giso_dir+"/"+Giso.GISO_SCRIPT):
               run_cmd("cp  -f %s/%s %s " % (self.giso_dir, Giso.GISO_SCRIPT, self.system_image_extract_path))
            if os.path.isfile(self.giso_dir+"/"+Giso.ZTP_INI_FILE_NAME):
               run_cmd("cp  -f %s/%s %s " % (self.giso_dir, Giso.ZTP_INI_FILE_NAME, self.system_image_extract_path))
            run_cmd("cp  -f %s/*.yml %s " % (self.giso_dir, self.system_image_extract_path))

            # update iso_info.txt file with giso name
            with open("%s/%s" % (self.system_image_extract_path, self.bundle_iso.ISO_INFO_FILE), 'r') as f:
                iso_info_raw = f.read()
                # Replace the iso name with giso string
                iso_info_raw = iso_info_raw.replace(self.bundle_iso.iso_name, self.giso_name_string)
            fd = open("%s/%s" % (self.system_image_extract_path, self.bundle_iso.ISO_INFO_FILE), 'w')
            fd.write(iso_info_raw)
            fd.close()
            os.chdir(pwd)

            #update bzimage for 663/664/702 fretta to support >2GB ISO
            if global_platform_name == "ncs5500" and ((self.get_bundle_iso_version() == "6.6.3") or
                                                      (self.get_bundle_iso_version() == "6.6.4") or
                                                      (self.get_bundle_iso_version() == "7.0.2")):
               self.update_bzimage(self.system_image_extract_path)

            # Recreate system_image.iso
            if os.path.exists(self.system_image_extract_path+"/boot/grub/stage2_eltorito"):
                cmd = "mkisofs -R -b boot/grub/stage2_eltorito -no-emul-boot -boot-load-size 4 \
                       -boot-info-table -o new_system_image.iso %s"%(self.system_image_extract_path)
            else:
                cmd = "mkisofs -R -o new_system_image.iso %s"%(self.system_image_extract_path)

            run_cmd(cmd)

            # Cleanup
            shutil.rmtree(self.system_image_extract_path)
            run_cmd("mv new_system_image.iso %s"%(self.system_image))
        else:
            logger.error("Error: Couldn't create directory for extarcting initrd")
            sys.exit(-1)
    def recreate_initrd_nested_platform(self):
        """ Extract initrd and add RPMs and metadatafile """
        pwd = cwd
        extracted_bundle_path = self.get_bundle_iso_extract_path()
        new_initrd_path = tempfile.mkdtemp(dir=pwd)
        run_cmd("cp -fr %s/* %s " % (extracted_bundle_path, new_initrd_path))
        #over write with new system_image
        run_cmd("cp %s %s/iso/"%(self.system_image,new_initrd_path))
        # Following workaround to work install replace commit operation 
        run_cmd("cp -f %s/*.yml %s " % (self.giso_dir, new_initrd_path))
        os.chdir(new_initrd_path)
        cmd = "find . | cpio -o -H newc | gzip > %s/boot/initrd.img"%(self.giso_dir)
        run_cmd(cmd)
        os.chdir(pwd)
        # Cleanup
        shutil.rmtree(new_initrd_path)
    def recreate_initrd_nested_platform_7xx(self):
        pwd = cwd
        extracted_bundle_path = self.get_bundle_iso_extract_path()
        new_initrd_path = tempfile.mkdtemp(dir=pwd)
        # get system_image.iso extracted copy to new_initrd_path
        run_cmd("cp -fr %s/* %s " % (extracted_bundle_path, new_initrd_path))
        extract_system_image_initrd_path = tempfile.mkdtemp(dir=pwd)
        # extract giso(system_image.iso) created 
        readiso(self.system_image, extract_system_image_initrd_path)
        # extract system_image.iso/boot/initrd.img
        system_image_initrd=("%s/boot/initrd.img"% extract_system_image_initrd_path)
        extract_initrd_r71x=tempfile.mkdtemp(dir=pwd)
        os.chdir(extract_initrd_r71x)
        run_cmd("zcat -f %s | cpio -id" %(system_image_initrd)) 
        os.chdir(pwd)
        if self.is_x86_only:
            nbi_initrd_dir_path=("%s/nbi-initrd"% extract_initrd_r71x)
            if os.path.isdir(nbi_initrd_dir_path):
                logger.debug ("Deleting nbi-initrd as x86_only option is selected")
                run_cmd("rm -rf %s" % (nbi_initrd_dir_path))
        rpms_path = glob.glob('%s/*_rpms' % extract_system_image_initrd_path)
        if len(rpms_path):
            # Move the RPMS to initrd content
            run_cmd("mv  -f %s/*_rpms %s " % (extract_system_image_initrd_path, extract_initrd_r71x))
        # Move giso metadata to initrd content
        run_cmd("cp  -f %s/giso_* %s " % (extract_system_image_initrd_path, extract_initrd_r71x))
        if os.path.isfile(extract_system_image_initrd_path+"/sp_info.txt"):
           run_cmd("cp  -f %s/sp_* %s " % (extract_system_image_initrd_path, extract_initrd_r71x))
        if os.path.isfile(extract_system_image_initrd_path+"/"+Giso.XR_CONFIG_FILE_NAME):
           run_cmd("cp  -f %s/%s %s " % (extract_system_image_initrd_path,
                                  Giso.XR_CONFIG_FILE_NAME, extract_initrd_r71x))
        if os.path.isfile(extract_system_image_initrd_path+"/"+Giso.GISO_SCRIPT):
           run_cmd("cp  -f %s/%s %s " % (extract_system_image_initrd_path,
                                  Giso.GISO_SCRIPT, extract_initrd_r71x))
        if os.path.isfile(extract_system_image_initrd_path+"/"+Giso.ZTP_INI_FILE_NAME):
           run_cmd("cp  -f %s/%s %s " % (extract_system_image_initrd_path,
                                  Giso.ZTP_INI_FILE_NAME, extract_initrd_r71x))


        run_cmd("cp  -f %s/*.yml %s " % (extract_system_image_initrd_path, extract_initrd_r71x))
        os.chdir(extract_initrd_r71x)
        cmd = "find . | cpio -o -H newc | gzip > %s/boot/initrd.img"%(extract_system_image_initrd_path)
        run_cmd(cmd)
        # Update initrd signature
        self.update_signature(extract_system_image_initrd_path)
        os.chdir(pwd)

        #update bzimage for 663/664/702 fretta to support >2GB ISO
        if global_platform_name == "ncs5500" and ((self.get_bundle_iso_version() == "6.6.3") or
                                                  (self.get_bundle_iso_version() == "6.6.4") or
                                                  (self.get_bundle_iso_version() == "7.0.2")):
           self.update_bzimage(extract_system_image_initrd_path)

        # Recreate system_image.iso
        if os.path.exists(extract_system_image_initrd_path+"/boot/grub/stage2_eltorito"):
            cmd = "mkisofs -R -b boot/grub/stage2_eltorito -no-emul-boot -boot-load-size 4 \
                       -boot-info-table -o new_system_image.iso %s"%(extract_system_image_initrd_path)
        else:
            cmd = "mkisofs -R -o new_system_image.iso %s"%(extract_system_image_initrd_path)

        run_cmd(cmd) 
        run_cmd("mv new_system_image.iso %s"%(self.system_image))
        # replace system_image.iso
        run_cmd("cp %s %s/iso/"%(self.system_image,new_initrd_path))
        # Following workaround to work install replace commit operation 
        run_cmd("cp  -f %s/*.yml %s " % (self.giso_dir, new_initrd_path))
        os.chdir(new_initrd_path)
        cmd = "find . | cpio -o -H newc | gzip > %s/boot/initrd.img"%(self.giso_dir)
        run_cmd(cmd)
        os.chdir(pwd)
        # Cleanup
        shutil.rmtree(extract_initrd_r71x)
        # ignore_errors=True is added to skip "Directory not empty" error
        shutil.rmtree(extract_system_image_initrd_path, ignore_errors=True)
        shutil.rmtree(new_initrd_path)

    def recreate_initrd_non_nested_platform(self):
        """ Extract initrd and add RPMs and metadatafile """
        pwd = cwd
        if self.get_bundle_shrinked_iso_extract_path() is not None:
            extracted_bundle_path = self.get_bundle_shrinked_iso_extract_path()
        else :
            extracted_bundle_path = self.get_bundle_iso_extract_path()
        new_initrd_path = tempfile.mkdtemp(dir=pwd)
        run_cmd("cp -fr %s/* %s " % (extracted_bundle_path, new_initrd_path))
        run_cmd("rm -f %s/*.rpm  " % (new_initrd_path))
        #copy GISO related stuff
        rpms_path = glob.glob('%s/*_rpms' % self.giso_dir)
        if len(rpms_path):
            # Move the RPMS to system_image.iso content
            run_cmd("mv  -f %s/*_rpms %s " % (self.giso_dir, new_initrd_path))

        # Move giso metadata to system_image.iso content
        run_cmd("cp  -f %s/giso_* %s " % (self.giso_dir, new_initrd_path))
        if os.path.isfile(self.giso_dir+"/sp_info.txt"):
           run_cmd("cp  -f %s/sp_* %s " % (self.giso_dir, new_initrd_path))
        if os.path.isfile(self.giso_dir+"/"+Giso.XR_CONFIG_FILE_NAME):
           run_cmd("cp  -f %s/%s %s " % (self.giso_dir, \
                                  Giso.XR_CONFIG_FILE_NAME, new_initrd_path))
        if os.path.isfile(self.giso_dir+"/"+Giso.GISO_SCRIPT):
           run_cmd("cp  -f %s/%s %s " % (self.giso_dir, \
                                  Giso.GISO_SCRIPT, new_initrd_path))
        if os.path.isfile(self.giso_dir+"/"+Giso.ZTP_INI_FILE_NAME):
           run_cmd("cp  -f %s/%s %s " % (self.giso_dir, \
                                  Giso.ZTP_INI_FILE_NAME, new_initrd_path))


        run_cmd("cp  -f %s/*.yml %s " % (self.giso_dir, new_initrd_path))

        os.chdir(new_initrd_path)
        cmd = "find . | cpio -o -H newc | gzip > %s/boot/initrd.img"%(self.giso_dir)
        run_cmd(cmd)
        os.chdir(pwd)
        # Cleanup
        shutil.rmtree(new_initrd_path)

    def create_sign_env(self):
        """ Pretend to be in workspace as thats a requirement for signing and
            get platforms .cer and .der files
        """
        logger.info("\nCreating signing environment...\n")
        logger.debug("ISO path: %s" %(self.bundle_iso.get_iso_path()))
        plat = self.get_bundle_iso_platform_name()
        if plat in Giso.NESTED_ISO_PLATFORMS :
            cmd = "IFS='[] ' read -a a <<< $(isoinfo -i %s -R -l | grep \" initrd.img\") " \
                  "&& dd bs=2048 skip=${a[8]} if=%s | head -c ${a[4]} | " \
                  "cpio -i --to-stdout --quiet  etc/show_version.txt | " \
                  "grep \"Lineup =\" | cut -d ' ' -f3" \
                  %(self.bundle_iso.get_iso_path(), self.bundle_iso.get_iso_path())
        else :
            cmd = "isoinfo -i %s -R -x /boot/initrd.img | gunzip -c | " \
                  "cpio -i --to-stdout --quiet  etc/show_version.txt | " \
                  "grep \"Lineup =\" | cut -d ' ' -f3" \
                   %(self.bundle_iso.get_iso_path())
        pwd=os.getcwd()
        # In case of nested platform we will be inside tmp directory
        # to sign the inner initrd. To access the iso here if relative path
        # of mini is provided we temporariliy moved to build directory 
        os.chdir(cwd)
        result = run_cmd(cmd)
        os.chdir(pwd) 
        devline = result["output"].rstrip("\n")
        logger.debug("Devline: %s" %devline)

        if not devline:
            logger.debug("platform: %s" %plat)
            if plat == "asr9k":
                logger.debug("This might  be shrinked asr9k image tryin with different  path")
                cmd = "isoinfo -i %s -R -x /boot/initrd.img | gunzip -c | " \
                  "cpio -i --to-stdout --quiet files*.cpio | " \
                  "cpio -i --to-stdout --quiet  etc/show_version.txt | " \
                  "grep \"Lineup =\" | cut -d ' ' -f3" \
                   %(self.bundle_iso.get_iso_path())
                result = run_cmd(cmd)
                devline = result["output"].rstrip("\n")
                logger.debug("Devline for shrinked a9k image: %s" %devline)

        if not devline:
            logger.error("Error: Couldn't get the lineup info from the image: %s" % self.bundle_iso.get_iso_path())
            sys.exit(-1)
        cmd = "acme dp -devline %s | grep tools/code-sign > my_lineup_file.lu" %devline
        result = run_cmd(cmd)
        pwd=os.getcwd()
        tmp_tool_dir = tempfile.mkdtemp(dir=pwd)
        os.chdir(tmp_tool_dir)
        cmd = "acme nw -lineup ../my_lineup_file.lu"
        result = run_cmd(cmd)
        os.chdir(pwd)
        cmd="rm -f my_lineup_file.lu"
        run_cmd(cmd)
        cmd="cp -rf %s/* %s/" %(tmp_tool_dir, pwd)
        run_cmd(cmd)
        cmd="cp -rf %s/.[a-zA-Z0-9]* %s/" %(tmp_tool_dir, pwd)
        run_cmd(cmd)
        cmd="rm -rf %s" %(tmp_tool_dir)
        run_cmd(cmd)

    def update_signature(self, path):
        """ Pretend to be in workspace as thats a requirement for signing and 
            get platforms .cer and .der files
        """
        if not os.path.exists("tools") or not os.path.exists(".ACMEROOT"):
            self.create_sign_env()
        XR_SIGN = "/sw/packages/jam_IOX/signing/xr_sign"
        # ncs1004 is signed with ncs1k key
        if self.platform == "ncs1004":
            SIGNING_CMD = "%s -plat %s -file %s/boot/initrd.img  -dir %s -signature %s/boot/signature.initrd.img"% \
                (XR_SIGN,"ncs1k", path, path, path)
        else:
            SIGNING_CMD = "%s -plat %s -file %s/boot/initrd.img  -dir %s -signature %s/boot/signature.initrd.img"% \
                (XR_SIGN,self.platform, path, path, path)
        logger.info("\nenviron before signing is {}".format(os.environ))              
        result = run_cmd(SIGNING_CMD)                                                
        logger.info("\nOutput of {} is \n {}".format(SIGNING_CMD, result["output"]))

        # Update MD5SUM in gisobuild after initrd
        with open("%s/%s" % (path, Giso.ISO_INFO_FILE), 'r') as f:
            iso_info_raw = f.read()

        #iso_info_raw = iso_info_raw.replace(, giso_name_string)
        cmd = "md5sum %s/boot/initrd.img"%(path)
        result = run_cmd(cmd)
        status = result["rc"]
        if not status :
            md5sum_of_initrd = result["output"].split(" ")[0].strip()
        else :
            raise RuntimeError("Error CMD=%s returned --->%s" % (cmd, result["output"]))

        iso_info_raw = iso_info_raw.replace(re.search(r'Initrd: initrd.img (.*)\n',
            iso_info_raw).group(1),md5sum_of_initrd)
        with open("%s/%s" % (path, Giso.ISO_INFO_FILE), 'w') as f:
            f.write(iso_info_raw)
        return

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
                        required=False, action='append', nargs='+',
                        help='Path to RPM repository')

    parser.add_argument('-c', '--xrconfig', dest='xrConfig', type=str,
                        required=False, action='append',
                        help='Path to XR config file')

    parser.add_argument('-z', '--ztp-ini', dest='ztp_ini', type=str,
                        required=False, action='append',
                        help='Path to user ztp ini file')

    parser.add_argument('-s', '--script', dest='script', type=str,
                        required=False, action='append',
                        help='Path to user executable script')
 
    parser.add_argument('-l', '--label', dest='gisoLabel', type=str,
                        required=False, action='append',
                        help='Golden ISO Label')

    parser.add_argument('-e', '--extend', dest='gisoExtend', 
                        action='store_true', required=False,
                        help='extend gISO by adding more rpms to existing gISO')

    parser.add_argument('-m', '--migration', dest='migTar', action='store_true',
                        help='To build Migration tar only for ASR9k')
    if OPTIMIZE_CAPABLE: 
        parser.add_argument('-o', '--optimize', dest='optimize', action='store_true',
                        help='Optimize GISO by recreating and resigning initrd')
    parser.add_argument('-x', '--x86_only', dest='x86_only', action='store_true',
                        help='Use only x86_64 rpms even if arm is applicable for the platform')
    version_string = "%%(prog)s (version %s)" %(__version__)

    parser.add_argument('-f', '--fullISO', dest='fullISO', action='store_true',
                        help='To build full iso only for xrv9k')

    parser.add_argument('-d', '--skip-dep-check', dest='skipDepCheck', action='store_true',
                        help='To build giso by skipping dependency check')

    parser.add_argument('-g', '--gisoInfo', dest='gisoInfo', action='store_true',
                        help='To display Golden ISO Information')

    parser.add_argument('--pkglist', dest='pkglist', type=str,
                        required=False, action='append', nargs='+',
                        help='Takes optional rpm or smu name or smu tar or ddts id or all as keyword')
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
    if not pargs.gisoInfo and not pargs.xrConfig:
        logger.debug('Info: XR Congifuration file not specified.')
        logger.debug('Info: Golden ISO will not have XR configuration file')
    elif not pargs.gisoInfo and len(pargs.xrConfig) > 1:
        logger.error('Error: Multiple xr config files are given.')
        logger.error('Info : Please provide unique xr config file.')
        sys.exit(-1)
    elif not pargs.gisoInfo and not os.path.isfile(pargs.xrConfig[0]):
        logger.error('Error: XR Configuration File %s not found.' % 
                     pargs.xrConfig[0])
        sys.exit(-1)
    if not pargs.gisoInfo and not pargs.script:
        logger.debug('Info: User script is not specified.')
    elif not pargs.gisoInfo and len(pargs.script) > 1:
        logger.error('Error: Multiple xr user scripts are given.')
        logger.error('Info : Please provide unique script file.')
        sys.exit(-1)
    elif not pargs.gisoInfo and not os.path.isfile(pargs.script[0]):
        logger.error('Error: User script %s not found.' % 
                     pargs.script[0])
        sys.exit(-1)
 
    if not pargs.gisoInfo and not pargs.rpmRepo:
        logger.info('Info: RPM repository path not specified.')
        logger.info('Info: No additional rpms will be included.')
    elif not pargs.gisoInfo and len(pargs.rpmRepo) > 1:
        logger.error('Error: Multiple rpm repo paths are given.')
        logger.error('Info : Please provide unique rpm repo path.')
        sys.exit(-1)
    elif not pargs.gisoInfo:
        for repopath in pargs.rpmRepo[0]:
            if not os.path.exists(repopath):
               logger.error('Error: RPM respotiry path %s not found' % repopath)
               sys.exit(-1)
    if not pargs.gisoInfo and not pargs.xrConfig and not pargs.script and not pargs.rpmRepo:
        logger.error('Info: Nothing to be done.')
        logger.error('Info: RPM repository path and/or XR configuration file or User Scripts')
        logger.error('      should be provided to build Golden ISO\n')
        os.system(os.path.realpath(__file__))
        sys.exit(-1)
    if not pargs.gisoInfo and not pargs.gisoLabel:
        pargs.gisoLabel = 0
        logger.info('Info: Golden ISO label is not specified '
                     'so defaulting to 0')
    elif not pargs.gisoInfo and len(pargs.gisoLabel) > 1:
        logger.error('Error: Multiple Golden ISO labels are given.')
        logger.error('Info : Please provide unique Golden ISO label.')
        sys.exit(-1)
    elif not pargs.gisoInfo and pargs.gisoLabel:
        temp_label = pargs.gisoLabel[0]
        new_label = temp_label.replace('_', '')
        if not new_label.isalnum():
            logger.error('Error: label %s contains characters other than alphanumeric and underscore', pargs.gisoLabel[0])
            logger.error('Info : Non-alphanumeric characters except underscore are not allowed in GISO label ')
            sys.exit(-1)
    if pargs.gisoExtend:
       if  re.match('.*golden.*', str(pargs.bundle_iso)):
           pass
       else:
           logger.error("To Extend gISO, please provide previously built gISO as input iso")
           sys.exit(-1)

    return pargs

def print_giso_info(iso_file):
    ISOINFO="isoinfo"
    cmd = ("%s -i %s -R -x /giso_info.txt"%(ISOINFO,iso_file))
    result = run_cmd(cmd)
    status = result["rc"]
    if status :
        logger.error("Command :%s failed with error :\n%s"%(cmd, result["output"]))
        return -1
    else :
        logger.info("\n%s\n" %(result["output"]))

def main(argv):
    pkglist=""
    with Giso() as giso:
        # set Extend gISO it is incremental giso build
        if argv.gisoExtend:
           giso.is_extend_giso = True
        giso.set_giso_info(argv.bundle_iso[0])
        logger.debug("\nFound Bundle ISO: %s" % 
                     (os.path.abspath(argv.bundle_iso[0])))
        global global_platform_name

        global_platform_name =  giso.get_bundle_iso_platform_name()
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
          if argv.gisoExtend:
             logger.info("\n\t... Extending the gISO ..")
          else:
            logger.error("Error: Image %s is neither mini.iso nor minik9.iso"
                         % (giso.get_bundle_iso_name()))
            logger.error("Only mini or minik9 image type "
                         "can be used to build Golden ISO")
            return

        if global_platform_name in Giso.NESTED_ISO_PLATFORMS:
          if argv.gisoExtend:
             logger.info("\n\t... Extending the gISO ..")

        #
        # 1.1.0 Check if migration option is provided for other platform than ASR9k
        #
        if argv.migTar and giso.get_bundle_iso_platform_name().upper() != "ASR9K": 
            logger.error("Error: Migration option is only applicable for ASR9k platform")
            sys.exit(-1)

        if argv.migTar:
            logger.info("\nInfo: Migration option is provided so migration tar will be generated")
            giso.is_tar_require = True


        if argv.fullISO and giso.get_bundle_iso_platform_name().upper() != "XRV9K": 
            logger.error("Error: fullISO option is only applicable for XRV9k platform")
            sys.exit(-1)
                
        if argv.fullISO:
            logger.info("\nInfo: fullISO option is provided so fullISO will be generated")
            giso.is_full_iso_require = True

        if argv.skipDepCheck:
            logger.info("\nInfo: skipDepCheck option is provided so GISO will be generated without dep check")
            giso.is_skip_dep_check = True
            giso.is_full_iso_require = True

        if argv.x86_only:
            giso.is_x86_only = True

        if argv.pkglist:
            giso.pkglist = True
            pkglist=argv.pkglist[0]
            #logger.info("argv.pkglist = %s\n" %(argv.pkglist))

        #
        # 1.2 Scan for XR-Config file. 
        #
        if argv.xrConfig and os.path.isfile(argv.xrConfig[0]) is True:
            logger.info("\nXR-Config file (%s) will be encapsulated in Golden ISO." % 
                        (os.path.abspath(argv.xrConfig[0])))
            giso.set_xrconfig(argv.xrConfig[0])

        #
        # Check for custom ztp.ini file.
        #
        if argv.ztp_ini and os.path.isfile(argv.ztp_ini[0]):
            logger.info ("Custom ZTP ini file (%s) will be encapsulated in Golden ISO." %
                        (os.path.abspath(argv.ztp_ini[0])))
            giso.set_ztpini(argv.ztp_ini[0])

        rpm_db = Rpmdb()
        fs_root = giso.get_bundle_iso_extract_path() 
        if argv.rpmRepo:

            # 1.3.1 Scan repository and build RPM data base.
            rpm_db.populate_rpmdb(fs_root, argv.rpmRepo[0], pkglist,
                 giso.get_bundle_iso_platform_name(), 
                 giso.get_bundle_iso_version(),
                 giso.is_full_iso_require,
                 giso.ExtendRpmRepository)

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

            rpm_db.filter_superseded_rpms()

            #Filter and discard cnbng RPMs if bng and cnbng rpm coexist in repo
            rpm_db.filter_cnbng_rpm()

            # 1.3.7 Group RPMS by vm_type and card architecture 
            # {"Host":{Arch:[rpm list]},"Cal":{Arch:[rpmlist]},
            #  "Xr":{Arch:[rpmlist]}} 
            rpm_db.group_cisco_rpms_by_vm_arch()
            rpm_db.group_tp_rpms_by_vm_arch()
            giso.set_repo_path(rpm_db.repo_path)

            # 1.4
            # Nothing to do if there is no xrconfig nor 
            # valid RPMs in RPM database
        if rpm_db.get_cisco_rpm_count() == 0 and rpm_db.sp_info == None:
            logger.info("Warning: No RPMS or Optional Matching %s packages "
                        "found in repository" % (giso.get_bundle_iso_version()))
            if not argv.xrConfig and not argv.script and rpm_db.get_tp_rpm_count() == 0:
                logger.info("Info: No Valid rpms nor XR config file found. "
                            "Nothing to do")
                return

        if argv.gisoExtend and not argv.xrConfig:
           if giso.gisoExtendRpms == len(rpm_db.rpm_list):
              logger.info("..No new RPMs present in the repository,"
                         " input gISO contain all the rpm/package in the repository")
              return
        #
        # get ISO RPM key
        #
        if not giso.is_full_iso_require and not giso.is_skip_dep_check: 
            giso.set_iso_rpm_key(fs_root)

        # 1.5 Compatability Check
        for vm_type in giso.VM_TYPE:
            supp_arch = giso.get_supp_arch(vm_type)
            dup_rpm_files = []
            final_rpm_files = []
            local_card_arch_files = []
            for arch in supp_arch:
                if arch == "arm" and argv.x86_only:
                    logger.info("\nSkipping arm rpms as given x86_only option")
                    continue
                arch_rpm_files = list(map(lambda rpm: rpm.file_name,
                                     rpm_db.get_cisco_rpms_by_vm_arch(vm_type, 
                                                                      arch) +
                                     rpm_db.get_tp_rpms_by_vm_arch(vm_type, 
                                                                   arch)))
                if arch_rpm_files:
                    if vm_type == CALVADOS_SUBSTRING:
                        vmtype = SYSADMIN_SUBSTRING
                    else:
                        vmtype = vm_type
                    logger.info("\nFollowing %s %s rpm(s) will be used for building Golden ISO:\n" % (vmtype, arch))
                    list(map(lambda file_name: logger.info("\t(+) %s" % file_name), 
                        arch_rpm_files))
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
            for arch in list(missing_arch_rpms.keys()):
                if arch == "arm" and argv.x86_only:
                    logger.debug("Skipping arm rpms in missing_arch_rpms check as given x86_only option")
                    continue
                list(map(lambda x: logger.error("\tError: Missing %s.%s.rpm" % 
                                           (x, arch)),
                    missing_arch_rpms[arch]))
                if len(missing_arch_rpms[arch]):
                    missing = True
            if missing:
                logger.info("Add the missing rpms to repository and "
                            "retry building Golden ISO.")
                return

            #
            # 1.5.2   Perform Compatibilty check
            #
            if not giso.is_full_iso_require and not giso.is_skip_dep_check: 
                if local_card_arch_files:
                    result, dup_rpm_files = \
                        giso.do_compat_check(local_card_arch_files, vm_type)
                    if result is False:
                        logger.error("\n\t...RPM compatibility check [FAIL]")
                        rpm_db.cleanup_tmp_repo_path()
                        return
            #
            # 1.5.3 Remove rpms's from input list 
            #       that are already part of base iso
            #
            if dup_rpm_files:    
                logger.info("\nSkipping following rpms from repository "
                            "since they are already present in base ISO:\n")
                list(map(lambda file_name: logger.error("\t(-) %s" % file_name), 
                    dup_rpm_files))
                final_rpm_files = list(set(final_rpm_files) - 
                                       set(dup_rpm_files))
                # TBD Remove other arch rpms as well.

            if final_rpm_files:
                if dup_rpm_files:
                    logger.debug("\nFollowing updated %s rpm(s) will be used for building Golden ISO:\n" % vm_type)
                    list(map(lambda x: logger.debug('\t(+) %s' % x), final_rpm_files))
                giso.set_vm_rpm_file_paths(final_rpm_files, vm_type)
                if not giso.is_full_iso_require: 
                    logger.info("\n\t...RPM compatibility check [PASS]")
                else:
                    logger.info("\n\t...RPM compatibility check [SKIPPED]")

        if argv.gisoLabel: 
            # if -x option is selected for fixed chassis fretta(ncs5500) then
            # Label field will be appended with "_Fixed" to distinguish GISO is
            # intended for only fixed chassis and shouldn't be used in modular
            if argv.x86_only:
               argv.gisoLabel[0] = "%s_Fixed" %(argv.gisoLabel[0])
               giso.set_giso_ver_label(argv.gisoLabel[0])
            else:
               giso.set_giso_ver_label(argv.gisoLabel[0])
            #if no label is provided then 0 would be default label. if -x is given
            #without any label then 0_Fixed would be the label
        else:
            if argv.x86_only:
                label="0_Fixed"
                giso.set_giso_ver_label(label)


#
#       2.0 Build Golden Iso
#
        if rpm_db.sp_info:
           giso.set_sp_info_file_path(rpm_db.get_sp_info())
        
        if argv.script and os.path.exists(argv.script[0]) is True:
            logger.info("\nUser Script (%s) will be encapsulated in Golden ISO." % 
                        (os.path.abspath(argv.script[0])))
            giso.set_script(argv.script[0])


        logger.info('\nBuilding Golden ISO...')
        result = giso.build_giso(rpm_db, argv.bundle_iso[0])
        # clean old giso rpms from repository
        if argv.gisoExtend:
           giso.do_extend_clean(giso.ExtendRpmRepository)
        rpm_db.cleanup_tmp_repo_path()
        if not result:
            logger.info('\n\t...Golden ISO creation SUCCESS.') 
            logger.info('\nGolden ISO Image Location: %s/%s' % 
                        (cwd, giso.giso_name))
            with open('img_built_name.txt',"w") as f:
                f.write(giso.giso_name)
        if giso.is_tar_require: 
            with Migtar() as migtar:
                logger.info('\nBuilding Migration tar...')
                migtar.create_migration_tar(cwd, giso.giso_name)
                logger.info('\nMigration tar creation SUCCESS.') 
                logger.info('\nMigration tar Location: %s/%s' % 
                            (cwd, migtar.dst_system_tar))
        sys.exit(0)

def readiso(iso_file, out_dir):
    ISOINFO="isoinfo"
    DIR_PREFIX="Directory listing of /"

    pwd = cwd
    cmd = ("%s -R -l -i %s "%(ISOINFO,iso_file))
    result = run_cmd(cmd) 
    status = result["rc"]
    if status :
        logger.error("Command :%s failed with error :\n%s"%(cmd, result["output"]))
        return -1

    for line in result["output"].splitlines():
        if not line :
            continue
        elif line.startswith("d"):
            continue
        elif line.startswith(DIR_PREFIX):
            dir_name = line.replace(DIR_PREFIX,'').strip()
            if not os.path.exists(os.path.join(out_dir,dir_name)):
                os.makedirs(os.path.join(out_dir,dir_name))
        else:
            file_name = line.split()[-1]
            if file_name == ".." :
                continue
            out_dir_file = os.path.join(out_dir,dir_name,file_name)
            cmd = "IFS='[] ' read -a a <<< $(%s -i %s -R -l | grep \" %s\") && dd bs=2048 skip=${a[8]} if=%s | head -c ${a[4]} > %s" %(ISOINFO, iso_file, file_name, iso_file, out_dir_file)
            run_cmd(cmd)

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
    logger.debug("Tool version is %s" %(__version__))
    try:
        args = parsecli()
        logger.debug("Argument passed to %s : %s" %(sys.argv[0], args))
        if args.gisoInfo:
            print_giso_info(args.bundle_iso[0])
            sys.exit(0)
        system_resource_check(args)
        logger.info("Golden ISO build process starting...")
        OPTIONS = args
        main(args)
        logger.debug("Exiting normally")
        logger.info("\nDetail logs: %s" % logfile)
    except Exception:
        logger.debug("Exiting with exception")
        exc_info1 = sys.exc_info()
        logger.debug("TB:", exc_info=True)
        print("\n", "Exception:", exc_info1[0], exc_info1[1])
        logger.info("Detail logs: %s" % logfile)
    except KeyboardInterrupt:
        logger.info("User interrupted\n")
        logger.info("Cleaning up and Exiting")
        logger.info("Detail logs: %s" % logfile)
        sys.exit(0)
    finally:
        logger.debug("################END#####################")


