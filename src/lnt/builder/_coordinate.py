# -----------------------------------------------------------------------------

""" Tool to coordinate the building of the GISO.

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

__all__ = (
    "run",
    "ReqPackageBeingRemovedError",
)

import argparse
import copy
import itertools
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile

from collections import defaultdict
from functools import cmp_to_key
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
)


from . import _blocks
from . import _file
from . import _packages
from . import _pkgchecks
from . import _pkgpicker
from .. import gisoutils
from .. import image
from .. import lnt_gisoglobals as gisoglobals


###############################################################################
#                               Global variables                              #
###############################################################################

# -------------------------------------------------------------------------
# Script global variables

_LOGFILE = "gisobuild.log"
_log = logging.getLogger(__name__)


###############################################################################
#                               Custom exceptions                             #
###############################################################################


class OutputDirNotEmptyError(Exception):
    """The specified output dir isn't empty"""

    def __init__(self, output_dir: str):
        """Initialise a OutputDirNotEmptyError"""
        super().__init__(
            "The specified output dir is not empty: {}. Use the --clean option to overwrite it.".format(
                output_dir
            )
        )


class LegacyVersionError(Exception):
    """Using outdated image.py"""

    def __init__(self) -> None:
        """Initialise a LegacyVersionError"""
        super().__init__(
            "The ISO contains a legacy version of image.py which does not "
            "have the required capabilities for this build script"
        )


class ISONotSpecifiedError(Exception):
    """The given ISO cannot be found"""

    def __init__(self, iso: str) -> None:
        """Initialise a ISONotSpecifiedError"""
        super().__init__(
            "The specified ISO file does not exist: {}".format(iso)
        )


class InvalidLabelError(Exception):
    """The label was not alphanumeric"""

    def __init__(self, label: str) -> None:
        """Initialise a InvalidLabelError"""
        super().__init__(
            "The label ({}) should consist of only letters and "
            "numbers and underscores".format(label)
        )


class RPMWrongFormatError(Exception):
    """The RPM is not in an expected format"""

    def __init__(self, rpm: str) -> None:
        """Initialise a RPMWrongFormatError"""
        super().__init__(
            "The RPM specified ({}) is not in an expected form. Must be "
            "either a .rpm, .tar, .tgz file or a directory containing those "
            "file types".format(rpm)
        )


class FailedToProduceIsoError(Exception):
    """
    Failed to make the ISO file

    """

    def __init__(self) -> None:
        """Initialise a FailedToProduceIsoError"""
        super().__init__("Failed to create the ISO file")


class NoISOVersionError(Exception):
    """
    ISO mdata did not contain a version number

    """

    def __init__(self) -> None:
        """Initialise a NoISOVersionError"""
        super().__init__("Could not determine version from ISO metadata")


class InvalidPkgsError(Exception):
    """Error if there are invalid packages."""

    def __init__(
        self,
        invalid_xr_version_pkgs: Set[_packages.Package],
        iso_version: str,
        invalid_arch_pkgs: Set[_packages.Package],
        iso_archs: Set[str],
    ) -> None:
        """
        Initialize the class.

        :param invalid_xr_version_pkgs:
            The packages with invalid xr version.

        :param iso_version:
            The xr version of the input iso.

        :param invalid_arch_pkgs:
            The packages with invalid architecture.

        :param iso_archs:
            The architectures of the rpms in the input iso.

        """
        assert invalid_xr_version_pkgs or invalid_arch_pkgs
        lines = []
        if invalid_xr_version_pkgs:
            lines.append(
                "The following XR packages have a different XR version to "
                f"the input ISO (expected '{iso_version}'):"
            )
            for pkg in sorted(invalid_xr_version_pkgs, key=str):
                lines.append(
                    f"  {str(pkg)} has XR version {pkg.version.xr_version}"
                )
        if invalid_arch_pkgs:
            archs_str = ", ".join(sorted(iso_archs))
            lines.append(
                "The following XR packages have a different architecture to "
                f"the input ISO (expected {archs_str}):"
            )
            for pkg in sorted(invalid_arch_pkgs, key=str):
                lines.append(f"  {str(pkg)} has arch {pkg.arch}")
        super().__init__("\n".join(lines))


class BridgingIsoVersionError(Exception):
    """
    User attempted to add a bridging bugfix of the same version as the ISO

    """

    def __init__(self, rpms: Set[str], version: str) -> None:
        """Initialise a BridgingIsoVersionError"""
        super().__init__(
            "Rejecting the following bridging rpms as they are the same "
            "xr version as the ISO ({}): {}".format(
                version, ", ".join(sorted(rpms))
            )
        )


class RPMDoesNotExistError(Exception):
    """The RPM does not exist"""

    def __init__(self, rpm: str) -> None:
        """Initialise a RPMDoesNotExistError"""
        super().__init__(
            "The RPM specified ({}) could not be found".format(rpm)
        )


class ReqPackageBeingRemovedError(Exception):
    """The user has specified required packages to be removed."""

    def __init__(self, pkgs: Set[str]) -> None:
        """Initialise a ReqPackageBeingRemovedError"""
        super().__init__(
            "The following packages were requested to be removed, but they "
            "are required: {}".format(" ".join(pkgs))
        )


###############################################################################
#                              Helper functions                               #
###############################################################################


def _prelim_checks(args: argparse.Namespace) -> None:
    """
    Do some preliminary checks before building the ISO

    :param args:
        The parsed arguments that will be used for the script

    """

    if re.match(r"^[\w_]+$", str(args.label)) is None:
        # The label should be alphanumeric except for underscores
        raise InvalidLabelError(args.label)

    # Check that the path to the ISO exists
    if not os.path.exists(args.iso):
        raise ISONotSpecifiedError(args.iso)

    # If copy_dir, the dir that will contain copies of built artefacts, is
    # specified make sure it already exists and is writeable
    if args.copy_dir is not None:
        gisoutils.check_copy_dir(args.copy_dir)


def _split_list(list_to_parse: List[str]) -> List[str]:
    """
    Takes a comma or space separated list string and parse it into a list

    :param list_to_parse:
        The string which is a comma separated list

    :returns:
        A list of the parsed items

    """

    return_list: List[str] = []
    # Arguments can be provided comma or space separated. If they were space
    # separated argparse will have separated them into a list in which case we
    # just add them to the list. If they were comma separated then we need to
    # parse them here.
    for item in list_to_parse:
        return_list += item.split(",")

    return return_list


def _get_rpms(rpm_type: str, packages: List[str], tmp_dir: str) -> List[str]:
    """
    Parse the comma separated list of packages. Unpack them if they are
    compressed.

    :param rpm_type:
        String of what type of RPMs that are to be retrieved for logging
        purposes

    :param packages:
        List of RPMS separated by commas in a single string

    :param tmp_dir:
        Temporary directory to store intermediate files

    :returns:
        List of paths to unpacked RPMs

    """

    rpms = _split_list(packages)

    rpms_found: List[str] = []
    # Go through the set of listed items: they can either be tgz, tar, rpm
    # files or directories. If it's a tgz or tar file unpacked then add any
    # RPMs in the unpacked directories to the list. If it is a rpm file just
    # append it to the list. If a dir has been specified, search the dir for
    # rpms and follow the same logic.
    for rpm in rpms:
        if not os.path.exists(rpm):
            raise RPMDoesNotExistError(rpm)

        if (
            rpm.endswith(".tgz")
            or rpm.endswith(".tar.gz")
            or rpm.endswith(".tar")
            or rpm.endswith(".rpm")
        ):
            rpms_found += _file.get_zipped_and_unzipped_rpms(rpm, tmp_dir)
        elif os.path.isdir(rpm):
            rpms_found += _file.get_rpms_from_dir(rpm, tmp_dir)
        else:
            raise RPMWrongFormatError(rpm)

    _log.debug(
        "Will attempt to add the following %s RPMs to the ISO: %s",
        rpm_type,
        rpms_found,
    )

    return rpms_found


def _get_updated_mdata(
    args: argparse.Namespace,
    iso_content: Dict[str, Dict[str, Any]],
    install_packages: List["_packages.Package"],
) -> Dict[str, Any]:
    """
    :param args:
        Parsed arguments

    :param iso_content:
        Base ISO information, as returned by query-content

    :param install_packages:
        Packages in the final install set

    :returns:
        Metadata with updated build & bugfix information
    """
    new_mdata = copy.deepcopy(iso_content["mdata"])
    build_info = {}

    generate_buildinfo = False
    if args.buildinfo is not None:
        try:
            with open(args.buildinfo) as f:
                build_info = json.loads(f.read())
        except (OSError, json.JSONDecodeError) as exc:
            _log.debug(
                "Failed to load build info %s: %s", args.buildinfo, str(exc)
            )
            generate_buildinfo = True
    else:
        generate_buildinfo = True

    if generate_buildinfo:
        _log.debug("Regenerating GISO build info")
        build_info = gisoutils.generate_buildinfo_mdata()
    new_mdata.update(build_info)

    # Iterate over packages in main install groups, adding any provided fixes
    bugfixes = defaultdict(list)
    for package in install_packages:
        for provide in package.provides:
            if provide.name.startswith("cisco-CSC"):
                bugfixes[provide.name].append(str(package))
    for k, v in bugfixes.items():
        bugfixes[k] = sorted(v)
    new_mdata[gisoglobals.LNT_GISO_CDETS] = bugfixes

    return new_mdata


def _log_on_success(
    args: argparse.Namespace,
    iso_file: str,
    usb_file: Optional[str],
    log_file: str,
) -> None:
    """
    Output to the CLI when the GISO build is successful

    :param args:
        Parsed args
    :param iso_file:
        Path to the re-packed iso file
    :param usb_file:
        Path to the corresponding USB zip image
    :param log_file:
        Path to the logs

    """

    # Create a command string that the script was called with
    arg_string = ""
    for arg in sys.argv[1:]:
        arg_string += arg + " "

    # Get size of iso file in bytes then convert to gigabytes
    size_bytes = os.path.getsize(iso_file)

    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    # Convert the size in bytes to a whatever size it's closest to
    if size_bytes == 0:
        power = 0
        size = 0.0
    else:
        power = int(math.floor(math.log(size_bytes, 1024)))
        divisor = math.pow(1024, power)
        size = round(size_bytes / divisor, 2)

    print("gisobuild.py {}".format(arg_string))
    print("GISO build successful")
    print("ISO: {}".format(iso_file))
    print("Size: {} {}".format(size, size_name[power]))
    if usb_file is not None:
        print("USB image: {}".format(usb_file))
    print("ISO label: {}".format(args.label))
    print("Further logs at {}".format(log_file))


###############################################################################
#                           Coordination methods                              #
###############################################################################


def _get_package_info_from_groups(
    iso_dir: str, groups: List[str],
) -> Tuple[Dict[str, str], Dict[str, "_packages.Package"]]:
    """
    Retrieve set of RPMs and corresponding package objects from the specified
    groups

    :param iso_dir:
        Unpacked ISO directory

    :param groups:
        List of groups to retrieve packages for

    :returns:
        Tuple containing:
        - Mapping from package string to RPM path
        - Mapping from RPM path to package object
    """
    rpm_mapping = {}
    package_mapping = {}
    for group in groups:
        rpms = _file.get_group_rpms(iso_dir, group)
        for rpm in rpms:
            package = _packages.Package.from_rpm_file(rpm)
            package_mapping[rpm] = package
            rpm_mapping[str(package)] = rpm

    return (rpm_mapping, package_mapping)


def _get_pkgs_from_groups(
    iso_dir: str, groups: List[str],
) -> List["_packages.Package"]:
    """
    Get the list of packages from the specified groups in the ISO.

    :param iso_dir:
        Path to the unpackaged iso directory.

    :param groups:
        List of group names to get packages for.

    :returns:
        List of packages from the specified groups in the ISO.

    """
    _, pkg_mapping = _get_package_info_from_groups(iso_dir, groups)
    return list(pkg_mapping.values())


def _remove_rpms(rpms_to_remove: Set[str]) -> None:
    """
    Remove all given RPMs from the unpacked ISO

    :param rpms_to_remove:
        RPMS to remove from the ISO

    """
    for rpm in rpms_to_remove:
        _log.debug("Removing %s", rpm)
        os.remove(rpm)


def _calculate_rpms_to_remove(
    blocks_to_include: List["_blocks.AnyBlock"],
    blocks_to_remove: List["_blocks.AnyBlock"],
    rpm_mapping: Dict[str, str],
) -> Set[str]:
    """
    Calculate which RPMs should be removed from the unpacked ISO.

    :param blocks_to_include:
        Blocks to include from the ISO

    :param blocks_to_remove:
        Blocks to remove from the ISO

    :param rpm_mapping:
        Mapping from package string to path of the corresponding RPM within the
        ISO

    """
    for block in blocks_to_remove:
        _log.debug(
            "Excluding %s-%s, as it is obsoleted by other packages",
            block.name,
            block.evra,
        )

    blocks_to_packages = lambda blocks: set(
        itertools.chain.from_iterable(block.all_pkgs for block in blocks)
    )

    packages_to_include = blocks_to_packages(blocks_to_include)
    candidate_packages_to_remove = blocks_to_packages(blocks_to_remove)

    # Must make sure that any packages in "to include" are retained.
    #
    # For example we might be removing some thirdparty tie block at an "old"
    # version but which happens to use a thirdparty RPM at the same version as
    # the "latest" (because other thirdparty RPMs in the tie got upgraded).
    packages_to_remove = candidate_packages_to_remove - packages_to_include

    rpms_to_remove = set(
        rpm_mapping.get(str(package), "") for package in packages_to_remove
    )
    rpms_to_remove.discard("")

    return rpms_to_remove


def _coordinate_bridging(
    bugfixes: List[str],
    mdata: Dict[str, Any],
    iso_dir: str,
    tmp_dir: str,
    iso_version: str,
) -> None:
    """
    Co-ordinate addition of bridging RPMs

    :param bugfixes:
        List of bridging bugfixes to add

    :param mdata:
        ISO metadata, as returned from query-content

    :param iso_dir:
        Location of unpacked ISO

    :param tmp_dir:
        Temporary directory to store intermediate files

    :param iso_version:
        XR version of the input ISO.

    """
    # Retrieve set of bridging RPMs already within the input GISO
    bridging_groups = gisoutils.get_groups_with_attr(
        mdata["groups"], "bridging"
    )

    base_rpm_mapping, base_package_mapping = _get_package_info_from_groups(
        iso_dir, bridging_groups
    )
    base_packages = list(base_package_mapping.values())

    # Build set of bridging RPMs to add
    rpms_to_add = _get_rpms("bridging", bugfixes, tmp_dir)
    packages_to_add = []
    add_rpm_mapping = {}
    version_errors = set()
    for rpm in rpms_to_add:
        package = _packages.Package.from_rpm_file(rpm)
        if package.version.xr_version == iso_version:
            version_errors.add(rpm)
        packages_to_add.append(package)
        add_rpm_mapping[str(package)] = rpm
    if version_errors:
        raise BridgingIsoVersionError(version_errors, iso_version)

    bridging_blocks = _blocks.group_packages(base_packages + packages_to_add)

    blocks_to_include: Dict[str, List[_blocks.AnyBlock]] = defaultdict(list)
    blocks_to_exclude: List[_blocks.AnyBlock] = []

    # For each block, iterate over all versions of it.
    # For each XR version, select the latest version of the block to include
    # in the ISO.
    # Add all unselected versions to a list of blocks to exclude
    _BlockType = TypeVar("_BlockType", _blocks.Block, _blocks.TieBlock)

    def _remove_duplicates(
        blocks_: Dict[str, Dict[_packages.EVRA, _BlockType]]
    ) -> None:
        for _, block_versions in blocks_.items():
            xr_version_dict = defaultdict(list)
            for version in block_versions.keys():
                xr_version_dict[version.version.xr_version].append(version)
            for xr_version, pkg_versions in xr_version_dict.items():
                sorted_versions = sorted(
                    pkg_versions,
                    key=cmp_to_key(_pkgpicker.compare_versions),
                    reverse=True,
                )
                blocks_to_include[xr_version].append(
                    block_versions[sorted_versions[0]]
                )
                for version in sorted_versions[1:]:
                    blocks_to_exclude.append(block_versions[version])

    _remove_duplicates(bridging_blocks.blocks)
    _remove_duplicates(bridging_blocks.tie_blocks)

    # Remove any excluded blocks that are already in the input ISO
    rpms_to_remove = _calculate_rpms_to_remove(
        [block for blocks in blocks_to_include.values() for block in blocks],
        blocks_to_exclude,
        base_rpm_mapping,
    )
    _remove_rpms(rpms_to_remove)

    # For any included blocks, add all RPMs
    for _, includes in blocks_to_include.items():
        for block in includes:
            _log.debug(
                "Including bridging bugfix %s-%s", block.name, block.evra
            )
            for package in block.all_pkgs:
                rpm_path: Optional[str] = (
                    add_rpm_mapping[str(package)]
                    if str(package) in add_rpm_mapping.keys()
                    else None
                )
                if rpm_path is not None:
                    _file.add_bridging_bugfix(rpm_path, iso_dir)


def _check_invalid_pkgs(
    pkgs: Iterable[_packages.Package], iso_version: str, iso_archs: Set[str]
) -> None:
    """
    Check if the given packages are valid in terms of XR version and arch.

    :param pkgs:
        The collection of packages to check.

    :param iso_version:
        The XR verison of the ISO.

    :param iso_archs:
        The set of architectures of the packages in the input ISO.

    :raises InvalidPkgsError:
        If there are any invalid packages.

    """
    different_xr_version_pkgs = set()
    different_arch_pkgs = set()
    for pkg in pkgs:
        # Only check XR version of this is an XR package (rather than third
        # party).
        if _blocks.is_xr_pkg(pkg) and pkg.version.xr_version != iso_version:
            different_xr_version_pkgs.add(pkg)
        if pkg.arch not in iso_archs:
            different_arch_pkgs.add(pkg)

    if different_xr_version_pkgs or different_arch_pkgs:
        raise InvalidPkgsError(
            different_xr_version_pkgs,
            iso_version,
            different_arch_pkgs,
            iso_archs,
        )


def _coordinate_pkgs(
    out_dir: str,
    repo: List[str],
    pkglist: List[str],
    remove_packages: List[str],
    verbose_dep_check: bool,
    skip_dep_check: bool,
    tmp_dir: str,
    mdata: Dict[str, Any],
    dev_signed: bool,
    iso_version: str,
) -> List["_packages.Package"]:
    """
    Coordinate the packages to include in the main install.

    :param out_dir:
        Path to the output directory where the GISO is built into.
    :param repo:
        List of paths to repositories specified on the CLI containing
        additional rpms that can be included.
    :param remove_packages:
        List of blocks to specify rpms to remove.
    :param verbose_dep_check:
        Flag to indicate whether to use verbose output of the dependency
        checker.
    :param skip_dep_check:
        Flag to indicate whether to skip the dependency check.
    :param tmp_dir:
        Temporary directory used for extracting various data.
    :param mdata:
        ISO metadata, as returned from query-content.
    :param dev_signed:
        True if packages in the input ISO are signed with the DEV key;
        False if signed with the REL key.
    :param iso_version:
        The XR version of the input ISO.
    :param iso_arch:
        The architecture of the input ISO.

    :return:
        List of packages in the final install.

    """
    _log.debug("Getting input ISO packages")
    install_groups = gisoutils.get_groups_with_attr(mdata["groups"], "install")
    iso_dirs = [
        _file.get_group_package_dir(out_dir, group)
        for group in install_groups
        if os.path.exists(_file.get_group_package_dir(out_dir, group))
    ]
    iso_pkgs = _get_pkgs_from_groups(out_dir, install_groups)
    _log.debug("Packages in the input ISO:")
    for pkg in sorted(iso_pkgs, key=str):
        _log.debug("  %s", str(pkg))

    _log.debug("Getting repo packages")
    repo_pkg_paths = _get_rpms("group", repo, tmp_dir)
    repo_dirs = [os.path.dirname(p) for p in repo_pkg_paths]
    repo_pkgs = _packages.get_packages_from_rpm_files(repo_pkg_paths)
    _log.debug("Packages in the repos:")
    for pkg in sorted(repo_pkgs, key=str):
        _log.debug("  %s", str(pkg))

    iso_archs = {pkg.arch for pkg in iso_pkgs}
    _check_invalid_pkgs(repo_pkgs, iso_version, iso_archs)

    _log.debug("Grouping ISO and repo packages into blocks")
    iso_blocks = _blocks.group_packages(iso_pkgs)
    non_xr_iso_pkgs = {pkg for pkg in iso_pkgs if not _blocks.is_xr_pkg(pkg)}
    repo_blocks = _blocks.group_packages(set(repo_pkgs) | non_xr_iso_pkgs)

    _log.debug("Picking packages to go into main part of the GISO")
    giso_blocks = _pkgpicker.pick_main_pkgs(
        iso_blocks, repo_blocks, pkglist, remove_packages
    )
    _log.debug("Packages picked to go in the GISO:")
    for pkg in sorted(giso_blocks.get_all_pkgs(), key=str):
        _log.debug("  %s", str(pkg))

    pkg_to_file = _packages.packages_to_file_paths(
        repo_pkgs + iso_pkgs, [*iso_dirs, *repo_dirs]
    )

    if not skip_dep_check:
        _log.debug("Performing dependency and signature checks")
        _pkgchecks.run(giso_blocks, pkg_to_file, verbose_dep_check, dev_signed)

    for action in _pkgpicker.determine_output_actions(
        giso_blocks, iso_blocks, pkg_to_file, mdata
    ):
        action.run(out_dir)

    return list(giso_blocks.get_all_pkgs())


def _coordinate_giso(
    args: argparse.Namespace, tmp_dir: str, log_dir: str
) -> Tuple[str, Optional[str]]:
    """
    Co-ordinate the building of the ISO

    :param args:
        The parsed arguments that will be used for the script

    :param tmp_dir:
        Temporary directory to store intermediate files

    :param log_dir:
        The directory for the image.py logs to be written to.

    :returns:
        Path to the re-packed iso-file

    """

    # Get the ISO capabilities to check whether we have a legacy version of
    # image.py (i.e. unsupported). Must do this first so that we don't attempt
    # any invalid operations!
    iso_image = image.Image(args.iso, tmp_dir=tmp_dir, log_dir=log_dir)
    version_num, _ = iso_image.get_capabilities()
    if version_num == "0":
        raise LegacyVersionError()

    # If there are any remove packages, then make sure they are not in the
    # required packages list. We do the check this way, because if the user
    # has mistyped a package (or using an optional package that is not
    # present), then we don't want to error. (A mistype will be caught in a
    # later check that warns the user it has no impact)
    if args.remove_packages:
        required_packages: Set[str] = set()

        required_packages_dict = iso_image.get_required_pkgs()
        for pkgs in required_packages_dict.values():
            required_packages |= set(pkgs)

        remove_packages = set(args.remove_packages).intersection(
            required_packages
        )
        if remove_packages:
            _log.error(ReqPackageBeingRemovedError(remove_packages))
            raise ReqPackageBeingRemovedError(remove_packages)

    out_dir = os.path.join(args.out_dir, "giso")

    # The resultant ISO needs to have a name of the form:
    # <PLATFORM>-golden-<ARCH>-<VERSION>-<LABEL>.iso
    # Query the ISO to get the required metadata
    iso_content = iso_image.query_content()
    mdata = iso_content["mdata"]
    assert isinstance(mdata, dict)

    try:
        iso_version = mdata["xr-version"]
    except KeyError as e:
        raise NoISOVersionError() from e

    print("Building GISO...")
    # Passed dependency checking so now unpack the ISO to the output directory
    iso_image.unpack_iso(out_dir)

    # Now that all packages have been added, remove any duplicates,
    # and run the dependency check
    install_packages = _coordinate_pkgs(
        out_dir,
        args.repo,
        args.pkglist,
        args.remove_packages,
        args.verbose_dep_check,
        args.skip_dep_check,
        tmp_dir,
        iso_content,
        iso_image.is_dev_signed,
        iso_version,
    )

    # If clear bridging fixes requested, remove all bridging fixes before
    # adding new ones
    if args.clear_bridging_fixes:
        _file.clear_bridging_bugfixes(out_dir, iso_content)

    # Add any specified bridging fixes
    if args.bridging_fixes:
        with tempfile.TemporaryDirectory(
            prefix="giso_build_bridging_"
        ) as tmp_bridging_dir:
            _coordinate_bridging(
                args.bridging_fixes,
                iso_content,
                out_dir,
                tmp_bridging_dir,
                iso_version,
            )

    # Add any of the files that are specified
    if args.label:
        label_file = os.path.join(tmp_dir, "label")
        with open(label_file, "w") as lbl:
            lbl.write(args.label)
        _file.add_package(
            out_dir,
            file_to_add=label_file,
            file_type=_file.FileTypeEnum.LABEL,
        )
    if args.xrconfig:
        _file.add_package(
            out_dir,
            file_to_add=args.xrconfig,
            file_type=_file.FileTypeEnum.CONFIG,
        )
    if args.ztp_ini:
        _file.add_package(
            out_dir,
            file_to_add=args.ztp_ini,
            file_type=_file.FileTypeEnum.ZTP,
        )

    # Update ISO metadata
    new_mdata = _get_updated_mdata(args, iso_content, install_packages)
    _log.debug("Updating ISO metadata: %s", new_mdata)
    json_mdata = json.dumps(new_mdata)
    mdata_file = os.path.join(tmp_dir, "mdata.json")
    with open(mdata_file, "w") as mdata_f:
        mdata_f.write(json_mdata)
    _file.add_package(
        out_dir, file_to_add=mdata_file, file_type=_file.FileTypeEnum.MDATA,
    )

    # Now that all desired files and packages have been added/removed repack
    # the ISO then build the USB image unless skipped
    platform_golden = "{}-golden".format(new_mdata["platform-family"],)
    arch = ""
    if "architecture" in new_mdata.keys():
        arch = "-{}".format(new_mdata["architecture"])
    xr_version = ""
    if "xr-version" in new_mdata.keys():
        xr_version += "-{}".format(new_mdata["xr-version"])
    label = ""
    if args.label is not None:
        label += "-{}".format(args.label)

    iso_name = f"{platform_golden}{arch}{xr_version}{label}.iso"
    iso_image.pack_iso(out_dir, iso_name)
    _log.info("Output to %s", str(os.path.join(out_dir, iso_name)))

    iso_file = os.path.join(out_dir, iso_name)
    if not os.path.exists(iso_file):
        raise FailedToProduceIsoError()

    usb_file: Optional[str] = None
    if not args.skip_usb_image:
        usb_name = f"{platform_golden}{arch}-usb_boot{xr_version}{label}.zip"
        usb_file = os.path.join(out_dir, usb_name)
        iso_image.build_usb_image(iso_file, usb_file)

    # Update permissions following ISO creation
    os.chmod(out_dir, 0o755)

    if args.copy_dir:
        _log.debug("Copying GISO to %s", args.copy_dir)
        copy_arts = [iso_file]
        if usb_file is not None and os.path.exists(usb_file):
            copy_arts.append(usb_file)
        gisoutils.copy_artefacts_to_dir(copy_arts, args.copy_dir)

    return (iso_file, usb_file)


def _prepare_output_dir(out_dir: str, log_dir_name: str, clean: bool) -> None:
    """
    Ensure the output directory is clean, or clean it if necessary.

    Raises `OutputDirNotEmptyError` is the output directory contains anything
    other than logs, and the clean option wasn't specified.

    """
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    non_log_contents = [
        item for item in os.listdir(out_dir) if item != log_dir_name
    ]
    if non_log_contents:
        if clean:
            items = (os.path.join(out_dir, item) for item in non_log_contents)
            for item in items:
                if os.path.isfile(item):
                    os.remove(item)
                elif os.path.isdir(item):
                    shutil.rmtree(item, ignore_errors=True)
        else:
            raise OutputDirNotEmptyError(out_dir)


def _main(args: argparse.Namespace, log_dir: str) -> Tuple[str, Optional[str]]:
    """Internals of main, suitable for calling directly from tests."""
    _prelim_checks(args)
    with tempfile.TemporaryDirectory(prefix="giso_build_") as tmp_dir:
        iso_file, usb_file = _coordinate_giso(args, tmp_dir, log_dir)
    return iso_file, usb_file


def run(args: argparse.Namespace) -> int:
    """
    Run the coordination flow.

    :param args:
        parsed arguments

    :return:
        The returncode for the script.

    """
    if args.debug:
        _log.setLevel(logging.DEBUG)

    # Check the status of the output directory first, cleaning it if necessary.
    # Then can safely start logging there.
    log_dir_name = "logs"
    try:
        _prepare_output_dir(args.out_dir, log_dir_name, args.clean)
    except OutputDirNotEmptyError:
        print(
            f"Output directory '{args.out_dir}' has contents from a previous "
            f"run of the tool. Remove these or pass the `--clean` option.",
            file=sys.stderr,
        )
        return 1

    log_dir = os.path.join(args.out_dir, log_dir_name)
    log_path = os.path.join(log_dir, _LOGFILE)
    gisoutils.init_logging(log_dir, _LOGFILE, debug=args.debug)

    # Log all the arguments for debug purposes. Note that we don't separate
    # out YAML file vs CLI or anything at this stage.
    _log.info("Input arguments for build: %s", args)

    gisoutils.set_user_specified_tools(args)

    rc = 0
    try:
        iso_file, usb_file = _main(args, log_dir)
        _log_on_success(args, iso_file, usb_file, log_path)
    except Exception as exc:
        _log.error(
            "Gisobuild script failed, see %s for more info: %s",
            log_path,
            str(exc),
        )
        _log.debug(str(exc), exc_info=True)
        rc = 1

    return rc
