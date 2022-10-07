# -----------------------------------------------------------------------------

""" Wrapper around eXR gisobuild legacy workflow.

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

from exrmod.gisobuild_exr_engine import *
from utils import gisoutils
from utils import gisoglobals as gglobals
import hashlib
import json
import os
import logging
import sys

cwd = os.getcwd()
MODULE_NAME = os.path.basename(__file__).split(".")[0]
DFLT_OUTPUT_DIR = os.path.join(cwd, "output_{}".format(MODULE_NAME))

logger = logging.getLogger(__name__)

def system_resource_prep (args):
    return None

def system_resource_check (args):
    from distutils.spawn import find_executable
    tools_check_err = False
    import_errors = False
    tools = ['mount', 'rm', 'cp', 'umount', 'zcat', 'chroot', 'mkisofs']

    if hasattr(args, 'fullISO') and args.fullISO:
        tools.remove('chroot')

    logger.debug("Performing System requirements check...")

    if sys.version_info < (3, 0):
        logger.error("Error: This tool requires Python version 3.0 or higher.")
        sys.exit(-1)

    isosize = os.path.getsize (args.bundle_iso) / 1024
    required_space = isosize * 10 / (1024 * 1024)
    disk = os.statvfs(args.out_directory)
    total_avail_space = float(disk.f_bavail*disk.f_frsize)
    avail_space = float((disk.f_bavail * disk.f_frsize) / (1024 * 1024 * 1024))

    logger.debug("Available space {} GB".format (avail_space))
    logger.debug("Required space {} GB".format (required_space))
    if avail_space < required_space:
        logger.error("Minimum {} GB of free disk space is required "
                     "for building Golden ISO.".format (int(required_space)))
        tools_check_err = True
    #tools_check_err = False

    if not tools_check_err:
        for tool in tools:
            executable_path = find_executable (tool)
            found = executable_path is not None
            if not found:
                logger.error("Error: Tool %s not found." % tool)
                tools_check_err = True
        if tools_check_err:
            logger.error("Failed to find pre-req tools, Check PATH "
                     "Env variable or install required tools.")

    ''' TODO: Any specific imports we need to take care of here? '''
    try:
        import yaml
    except:
        import_errors = True
        logger.error("Failed to import all pre-req modules.")
        pass

    if tools_check_err or import_errors:
        logger.error("Error: System requirements check [FAIL]")
        sys.exit(-1)
    logger.info("System requirements check [PASS]")
    return

def main (argv, infile):
    global cwd

    cwd = os.getcwd()
    global_platform_name = None

    initialize_globals (cwd, argv, logger, global_platform_name)
    pkglist=""
    with Giso() as giso:
        # set Extend gISO it is incremental giso build
        if argv.gisoExtend:
           giso.is_extend_giso = True
        giso.set_giso_info(argv.bundle_iso)
        logger.debug("\nFound Bundle ISO: %s" %
                     (os.path.abspath(argv.bundle_iso)))
        #global global_platform_name

        global_platform_name =  giso.get_bundle_iso_platform_name()
        initialize_globals (cwd, argv, logger, global_platform_name)
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

        #
        # 1.1.0 Check if migration option is provided for other platform than ASR9k
        #
        if argv.migTar and giso.get_bundle_iso_platform_name().upper() != "ASR9K":
            logger.error("Error: Migration option is only applicable for ASR9k platform")
            sys.exit(-1)

        if argv.migTar:
            logger.info("\nInfo: Migration option is provided so migration tar will be generated")
            giso.is_tar_require = True


        if hasattr(argv, 'fullISO') and argv.fullISO and giso.get_bundle_iso_platform_name().upper() != "XRV9K":
            logger.error("Error: fullISO option is only applicable for XRV9k platform")
            sys.exit(-1)

        if hasattr(argv, 'fullISO') and argv.fullISO:
            logger.info("\nInfo: fullISO option is provided so fullISO will be generated")
            giso.is_full_iso_require = True

        if argv.__dict__.get('skipDepCheck'):
            logger.info("\nInfo: skipDepCheck option is provided so GISO will be generated without dep check")
            giso.is_skip_dep_check = True
            giso.is_full_iso_require = True

        if argv.x86_only:
            giso.is_x86_only = True

        if argv.pkglist:
            giso.pkglist = True
            pkglist=argv.pkglist
            #logger.info("argv.pkglist = %s\n" %(argv.pkglist))

        #
        # 1.2 Scan for XR-Config file. 
        #
        if argv.xrConfig and os.path.isfile(argv.xrConfig) is True:
            if not argv.in_docker:
                logger.info("\nXR-Config file (%s) will be encapsulated in Golden ISO." %
                        (os.path.abspath(argv.xrConfig)))
            else:
                logger.info("\nXR-Config file in input will be encapsulated in Golden ISO.")
            giso.set_xrconfig(argv.xrConfig)

        #
        # Check for custom ztp.ini file.
        #
        if argv.ztp_ini and os.path.isfile(argv.ztp_ini):
            if not argv.in_docker:
                logger.info ("Custom ZTP ini file (%s) will be encapsulated in Golden ISO." %
                        (os.path.abspath(argv.ztp_ini)))
            else:
                logger.info ("Custom ZTP ini file in input will be encapsulated in Golden ISO.")
            giso.set_ztpini(argv.ztp_ini)

        rpm_db = Rpmdb()
        fs_root = giso.get_bundle_iso_extract_path()
        if argv.rpmRepo:

            # 1.3.1 Scan repository and build RPM data base.
            rpm_db.populate_rpmdb(fs_root, argv.rpmRepo, pkglist,
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
               argv.gisoLabel = "%s_Fixed" %(argv.gisoLabel)
               giso.set_giso_ver_label(argv.gisoLabel)
            else:
               giso.set_giso_ver_label(argv.gisoLabel)
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

        if argv.script and os.path.exists(argv.script) is True:
            if not argv.in_docker:
                logger.info("\nUser Script (%s) will be encapsulated in Golden ISO." %
                        (os.path.abspath(argv.script)))
            else:
                logger.info("\nUser Script in input will be encapsulated in Golden ISO.")
            giso.set_script(argv.script)


        logger.info('\nBuilding Golden ISO...')
        result = giso.build_giso(rpm_db, argv.bundle_iso)
        # clean old giso rpms from repository
        if argv.gisoExtend:
           giso.do_extend_clean(giso.ExtendRpmRepository)
        rpm_db.cleanup_tmp_repo_path()
        files_to_checksum = set()
        if not result:
            logger.info('\n\t...Golden ISO creation SUCCESS.')
            logger.info('\nGolden ISO Image Location: %s/%s' %
                        (cwd, giso.giso_name))
            img_name_file = 'img_built_name.txt'
            with open(img_name_file, "w") as f:
                f.write(giso.giso_name)
            files_to_checksum.add(giso.giso_name)
            files_to_checksum.add(img_name_file)
            files_to_checksum.add("rpms_packaged_in_giso.txt")
        if giso.is_tar_require:
            with Migtar() as migtar:
                logger.info('\nBuilding Migration tar...')
                migtar.create_migration_tar(cwd, giso.giso_name)
                logger.info('\nMigration tar creation SUCCESS.')
                logger.info('\nMigration tar Location: %s/%s' %
                            (cwd, migtar.dst_system_tar))
                files_to_checksum.add(migtar.dst_system_tar)
        if argv.create_checksum:
            gisoutils.create_checksum_file(cwd, files_to_checksum, gglobals.CHECKSUM_FILE_NAME)
        sys.exit(0)
