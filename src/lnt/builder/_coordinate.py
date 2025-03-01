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
    Union,
)

from utils import bes
from utils import gisoglobals as gglobals
from utils import gisoutils as ggisoutils

from .. import gisoutils, image
from .. import lnt_gisoglobals as gisoglobals
from . import _blocks, _file, _isoformat, _packages, _pkgchecks, _pkgpicker

###############################################################################
#                               Global variables                              #
###############################################################################

# -------------------------------------------------------------------------
# Script global variables

_LOGFILE = "gisobuild.log"
_log = logging.getLogger(__name__)

# First XR version that supported specifying owner and partner packages.
_MIN_XR_VERSION_FOR_OWNER_PARTNER = "7.11.1"
# Prefixes of XR versions that fall between the version that first supported
# owner and partner packages and the version that added the image.py capability
# that indicates they are supported.
_XR_VERSIONS_FOR_OWNER_PARTNER_BEFORE_CAP = ("7.11.", "24.", "25.1.1")

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
        pre_supported_version_owner_pkgs: Set[_packages.Package],
        pre_supported_version_partner_pkgs: Set[_packages.Package],
        invalid_arch_pkgs: Set[_packages.Package],
        iso_archs: Set[str],
    ) -> None:
        """
        Initialize the class.

        :param invalid_xr_version_pkgs:
            The packages with invalid xr version.

        :param iso_version:
            The xr version of the input iso.

        :param pre_supported_version_owner_pkgs:
            Any owner packages that were given with an ISO with an XR version
            before _MIN_XR_VERSION_FOR_OWNER_PARTNER.

        :param pre_supported_version_partner_pkgs:
            Any partner packages that were given with an ISO with an XR version
            before _MIN_XR_VERSION_FOR_OWNER_PARTNER.

        :param invalid_arch_pkgs:
            The packages with invalid architecture.

        :param iso_archs:
            The architectures of the rpms in the input iso.

        """
        assert any(
            [
                invalid_xr_version_pkgs,
                pre_supported_version_owner_pkgs,
                pre_supported_version_partner_pkgs,
                invalid_arch_pkgs,
            ]
        )
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
        if (
            pre_supported_version_owner_pkgs
            or pre_supported_version_partner_pkgs
        ):
            lines.append(
                "Partner and owner packages cannot be installed on ISOs with XR versions before "
                f"{_MIN_XR_VERSION_FOR_OWNER_PARTNER}. An ISO with version {iso_version} was provided."
            )
            if pre_supported_version_owner_pkgs:
                lines.append("  The following owner packages were provided:")
                for pkg in sorted(pre_supported_version_owner_pkgs, key=str):
                    lines.append(f"    {str(pkg)}")
            if pre_supported_version_partner_pkgs:
                lines.append("  The following partner packages were provided:")
                for pkg in sorted(pre_supported_version_partner_pkgs, key=str):
                    lines.append(f"    {str(pkg)}")
        super().__init__("\n".join(lines))


class InvalidBugfixesError(Exception):
    """Error if there are invalid bugfixes."""

    def __init__(
        self,
        partner_packages: Set[_packages.Package],
        owner_packages: Set[_packages.Package],
        invalid_arch_pkgs: Set[_packages.Package],
        iso_arch: str,
    ) -> None:
        """
        Initialize the class.

        :param partner_packages:
            The list of partner packages provided as bridging bugfixes.

        :param owner_packages:
            The list of owner packages provided as bridging bugfixes.

        :param invalid_arch_pkgs:
            The packages with invalid architecture.

        :param iso_arch:
            The architectures of the rpms in the input iso.

        """
        assert any([partner_packages, owner_packages, invalid_arch_pkgs])
        lines = []
        if partner_packages:
            lines.append(
                "Bridging bugfixes must be Cisco packages, but the following "
                "partner packages were provided:"
            )
            for pkg in sorted(partner_packages, key=str):
                lines.append(f"  {str(pkg)}")
        if owner_packages:
            lines.append(
                "Bridging bugfixes must be Cisco packages, but the following "
                "owner packages were provided:"
            )
            for pkg in sorted(owner_packages, key=str):
                lines.append(f"  {str(pkg)}")
        if invalid_arch_pkgs:
            lines.append(
                "The following bugfix packages have a different architecture "
                f"to the input ISO (expected {iso_arch}):"
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


def _format_pid_types(pid_types: Dict[str, str]) -> str:
    if not pid_types:
        return "(No PIDs supported by this ISO)"

    # Map to readable names
    pid_types = {
        pid: (
            _isoformat.CARD_CLASS_READABLE[card_type]
            if card_type in _isoformat.CARD_CLASS_READABLE
            else card_type
        )
        for pid, card_type in pid_types.items()
    }
    sorted_pids = sorted(pid_types.keys())
    max_pid_len = max(len(pid) for pid in pid_types.keys())
    max_class_len = max(len(card_class) for card_class in pid_types.values())

    return (
        "The PIDs supported by the input ISO are:\n"
        + f"{'PID'.ljust(max_pid_len)} | {'Card class'.ljust(max_class_len)}\n"
        + f"{'-'*max_pid_len}-|-{'-' * max_class_len}\n"
        + "\n".join(
            f"{pid.ljust(max_pid_len)} | {pid_types[pid].ljust(max_class_len)}"
            for pid in sorted_pids
        )
    )


class UnsupportedPIDError(Exception):
    """The user has specified PIDs to keep that do not exist in the input ISO."""

    def __init__(
        self, unexpected_pids: Set[str], pid_types: Dict[str, str]
    ) -> None:
        """Initialise an UnsupportedPIDError"""
        top_msg = (
            "The following PIDs were requested to be supported by the GISO, but they "
            "are not supported in the input ISO: {}".format(
                ", ".join(unexpected_pids)
            )
        )
        super().__init__(f"{top_msg}.\n{_format_pid_types(pid_types)}")


class BadPIDClassesError(Exception):
    """The user has specified a distributed RP PID without an LC PID, or vice
    versa."""

    def __init__(
        self, rp_in_selection: bool, pid_types: Dict[str, str]
    ) -> None:
        """Initialise an BadPIDClassesError"""

        top_msg = (
            f"One or more {'Route Processor' if rp_in_selection else 'Line Card'} PIDs have been selected without a "
            + ("Line Card" if rp_in_selection else "Route Processor")
            + " PID - images for modular hardware must contain at least one of each."
        )

        super().__init__(f"{top_msg}\n{_format_pid_types(pid_types)}")


###############################################################################
#                              Helper functions                               #
###############################################################################


def _prelim_checks(args: argparse.Namespace) -> None:
    """
    Do some preliminary checks before building the ISO

    :param args:
        The parsed arguments that will be used for the script

    """

    if args.label and re.match(r"^[\w_]+$", str(args.label)) is None:
        # The label should be alphanumeric except for underscores
        raise InvalidLabelError(args.label)

    # Check that the path to the ISO exists
    if not os.path.exists(args.iso):
        raise ISONotSpecifiedError(args.iso)

    # If copy_dir, the dir that will contain copies of built artefacts, is
    # specified make sure it already exists and is writeable
    if args.copy_dir is not None:
        gisoutils.check_copy_dir(args.copy_dir)


def _get_rpms(rpm_type: str, packages: List[str], tmp_dir: str) -> List[str]:
    """
    Parse the list of packages. Unpack them if they are compressed.

    :param rpm_type:
        String of what type of RPMs that are to be retrieved for logging
        purposes

    :param packages:
        List of RPMS

    :param tmp_dir:
        Temporary directory to store intermediate files

    :returns:
        List of paths to unpacked RPMs

    """

    rpms_found: List[str] = []
    # Go through the set of listed items: they can either be tgz, tar, rpm
    # files or directories. If it's a tgz or tar file unpacked then add any
    # RPMs in the unpacked directories to the list. If it is a rpm file just
    # append it to the list. If a dir has been specified, search the dir for
    # rpms and follow the same logic.
    for rpm in packages:
        if not os.path.exists(rpm):
            raise RPMDoesNotExistError(rpm)

        if rpm.endswith((".tgz", ".tar.gz", ".tar", ".rpm")):
            rpms_found += _file.get_zipped_and_unzipped_rpms(rpm, tmp_dir)
        elif os.path.isdir(rpm):
            rpms_found += _file.get_rpms_from_dir(rpm, tmp_dir)
        else:
            raise RPMWrongFormatError(rpm)

    # The input tarballs have been logged earlier. Log the constituent RPMs
    # here, now they have been unpacked.
    bes.log_files(rpms_found, f"input {rpm_type} RPMs")

    _log.debug(
        "Will attempt to add the following %s RPMs to the ISO: %s",
        rpm_type,
        rpms_found,
    )

    return rpms_found


def _get_updated_mdata(
    args: argparse.Namespace,
    iso_content: Dict[str, Union[Dict[str, Any], str]],
    install_packages: List["_packages.Package"],
    no_buildinfo: bool,
) -> Tuple[Dict[str, Any], str]:
    """
    :param args:
        Parsed arguments

    :param iso_content:
        Base ISO information, as returned by query-content

    :param install_packages:
        Packages in the final install set

    :param no_buildinfo:
        Whether to skip updating the mdata.json contents with the GISO build
        information.

    :returns:
        ISO mdata.json and build-info.txt contents with updated build & bugfix
        information.
    """
    # Keep mypy happy by affirming the types.
    mdata = iso_content["mdata"]
    assert isinstance(mdata, dict)
    buildinfo = str(iso_content["buildinfo"])

    new_mdata: Dict[str, Any] = copy.deepcopy(mdata)

    # The "--buildinfo" argument is intended for use with container builds and
    # allows the GISO build metadata to be generated outside the container.
    giso_info = {}
    generate_giso_info = True
    if args.buildinfo is not None:
        try:
            with open(args.buildinfo) as f:
                giso_info = json.loads(f.read())
            generate_giso_info = False
        except (OSError, json.JSONDecodeError) as exc:
            _log.debug(
                "Failed to load build info %s: %s", args.buildinfo, str(exc)
            )

    # If the GISO build metadata has not been provided via the "--buildinfo"
    # argument, generate it now.
    if generate_giso_info:
        _log.debug("Regenerating GISO build info")
        giso_info = gisoutils.generate_buildinfo_mdata()

    if not no_buildinfo:
        # Only update specific fields with the GISO build metadata, as the build
        # host and directory should be unchanged in the mdata.json file to avoid
        # confusing changes in the "show version" output after GISO builds.
        new_mdata.update(
            {
                x: giso_info[x]
                for x in (
                    gisoglobals.LNT_GISO_BUILDER,
                    gisoglobals.LNT_GISO_BUILD_TIME,
                    gisoglobals.LNT_GISO_BUILD_CMD,
                )
                if x in giso_info
            }
        )

        # Populate the remaining GISO metadata fields in the mdata.json file
        # with values from the original build found in the build-info.txt file.
        new_mdata = gisoutils.parse_buildinfo_mdata(buildinfo, new_mdata)

    # Append the GISO build metadata to the build-info.txt file to ensure
    # the information is available for debugging.
    new_buildinfo = gisoutils.format_buildinfo_mdata(buildinfo, giso_info)
    # Iterate over packages in main install groups, adding any provided fixes
    bugfixes = defaultdict(list)
    for package in install_packages:
        for provide in package.provides:
            if provide.name.startswith("cisco-CSC"):
                bugfixes[provide.name].append(str(package))
    for k, v in bugfixes.items():
        bugfixes[k] = sorted(v)
    new_mdata[gisoglobals.LNT_GISO_CDETS] = bugfixes

    return new_mdata, new_buildinfo


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

    # Build environment logging
    output_files = [iso_file]
    if usb_file is not None:
        output_files.append(usb_file)
    bes.log("GISO build successful")
    bes.log_files(output_files, "output files")

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
    iso_dir: str,
    groups: List[str],
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
    rpms = [
        rpm for group in groups for rpm in _file.get_group_rpms(iso_dir, group)
    ]
    package_mapping = _packages.get_packages_from_rpm_files(rpms)
    rpm_mapping = {
        str(package): rpm for rpm, package in package_mapping.items()
    }

    return (rpm_mapping, package_mapping)


def _get_pkgs_from_groups(
    iso_dir: str,
    groups: List[str],
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
    only_support_pids: Optional[List[str]],
    mdata: Dict[str, Any],
    iso_dir: str,
    tmp_dir: str,
    iso_version: str,
    iso_arch: str,
) -> None:
    """
    Co-ordinate addition of bridging RPMs

    :param bugfixes:
        List of bridging bugfixes to add

    :param only_support_pids:
        If given, only support this list of PIDs in the GISO.

    :param mdata:
        ISO metadata, as returned from query-content

    :param iso_dir:
        Location of unpacked ISO

    :param tmp_dir:
        Temporary directory to store intermediate files

    :param iso_version:
        XR version of the input ISO.

    :param iso_arch:
        Architecture of the input ISO.

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
    rpms_to_packages = _packages.get_packages_from_rpm_files(rpms_to_add)
    for rpm, package in rpms_to_packages.items():
        if package.version.xr_version == iso_version:
            version_errors.add(rpm)
        packages_to_add.append(package)
        add_rpm_mapping[str(package)] = rpm
    if version_errors:
        raise BridgingIsoVersionError(version_errors, iso_version)

    _check_invalid_bugfixes(packages_to_add, iso_arch)

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
                assert (
                    xr_version is not None
                )  # All bridging fixes must have an XR version
                blocks_to_include[xr_version].append(
                    block_versions[sorted_versions[0]]
                )
                for version in sorted_versions[1:]:
                    blocks_to_exclude.append(block_versions[version])

    if only_support_pids is not None:
        _log.debug("Filtering unsupported PIDs from bridging pkgs")
        bridging_blocks.filter_pkgs_to_supported_pids(only_support_pids)

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
    pkgs: Iterable[_packages.Package],
    iso_version: str,
    iso_archs: Set[str],
    supports_owner_partner_packages: bool,
) -> None:
    """
    Check if the given packages are valid in terms of XR version and arch.

    :param pkgs:
        The collection of packages to check.

    :param iso_version:
        The XR verison of the ISO.

    :param iso_archs:
        The set of architectures of the packages in the input ISO.

    :param supports_owner_partner_packages:
        Whether the input ISO supports specifying owner and partner packages.

    :raises InvalidPkgsError:
        If there are any invalid packages.

    """
    different_xr_version_pkgs = set()
    pre_supported_version_owner_pkgs = set()
    pre_supported_version_partner_pkgs = set()
    different_arch_pkgs = set()
    for pkg in pkgs:
        # Only check XR version of this is an XR package (rather than third
        # party).
        if _blocks.is_xr_pkg(pkg) and pkg.version.xr_version != iso_version:
            different_xr_version_pkgs.add(pkg)
        if pkg.is_owner_package and not supports_owner_partner_packages:
            pre_supported_version_owner_pkgs.add(pkg)
        if pkg.is_partner_package and not supports_owner_partner_packages:
            pre_supported_version_partner_pkgs.add(pkg)
        if pkg.arch not in iso_archs:
            different_arch_pkgs.add(pkg)

    if any(
        [
            different_xr_version_pkgs,
            pre_supported_version_owner_pkgs,
            pre_supported_version_partner_pkgs,
            different_arch_pkgs,
        ]
    ):
        raise InvalidPkgsError(
            different_xr_version_pkgs,
            iso_version,
            pre_supported_version_owner_pkgs,
            pre_supported_version_partner_pkgs,
            different_arch_pkgs,
            iso_archs,
        )


def _check_invalid_bugfixes(
    bugfixes: Iterable[_packages.Package], iso_arch: str
) -> None:
    """
    Check if the given bugfixes are valid.

    :param: bugfixes:
        The collection of bugfixes to check.

    :param iso_arch:
        The architecture of the input ISO.

    :raises InvalidBugfixesError:
        If there are any invalid bugfixes.

    """
    partner_packages = set()
    owner_packages = set()
    different_arch_pkgs = set()
    for pkg in bugfixes:
        if pkg.is_partner_package:
            partner_packages.add(pkg)
        if pkg.is_owner_package:
            owner_packages.add(pkg)
        if pkg.arch != iso_arch:
            different_arch_pkgs.add(pkg)

    if any([partner_packages, owner_packages, different_arch_pkgs]):
        raise InvalidBugfixesError(
            partner_packages,
            owner_packages,
            different_arch_pkgs,
            iso_arch,
        )


def _validate_pid_selection(
    selected_pids: List[str], giso_blocks: _blocks.GroupedPackages
) -> None:
    """Check that all selected PIDs exist in the base ISO, and the selection
    has a sensible mix of card classes."""

    if not selected_pids:
        raise ValueError("No PIDs selected - a GISO cannot be made.")

    pid_types = {
        pid: card_type
        for pid, _, card_type in _blocks.get_pid_identifier_packages(
            giso_blocks.get_all_pkgs(
                _isoformat.PackageGroup.INSTALLABLE_XR_PKGS
            )
        )
    }

    unexpected_pids = set(selected_pids) - set(giso_blocks.supported_pids)
    if unexpected_pids:
        raise UnsupportedPIDError(unexpected_pids, pid_types)

    rp_in_selection = any(
        pid_types[pid] == "rp-distributed" for pid in selected_pids
    )
    lc_in_selection = any(
        pid_types[pid] == "lc-distributed" for pid in selected_pids
    )
    if rp_in_selection != lc_in_selection:
        raise BadPIDClassesError(rp_in_selection, pid_types)


def _coordinate_pkgs(
    out_dir: str,
    repo: List[str],
    pkglist: List[str],
    remove_packages: List[str],
    only_support_pids: Optional[List[str]],
    verbose_dep_check: bool,
    skip_dep_check: bool,
    tmp_dir: str,
    mdata: Dict[str, Any],
    dev_signed: bool,
    iso_version: str,
    supports_owner_partner_packages: bool,
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
    :param only_support_pids:
        List of PIDs to include in the GISO. Non-specified PIDs will be removed.
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
    :param supports_owner_partner_packages:
        Whether the input ISO supports specifying owner and partner packages.

    :return:
        List of packages in the final install.

    """
    _log.debug("Getting input ISO packages")
    installable_groups = _isoformat.get_installable_groups(mdata["groups"])

    iso_dirs = [
        _file.get_group_package_dir(out_dir, group)
        for group in installable_groups
        if os.path.exists(_file.get_group_package_dir(out_dir, group))
    ]
    iso_pkgs = _get_pkgs_from_groups(out_dir, list(installable_groups))
    _log.debug("Packages in the input ISO:")
    for pkg in sorted(iso_pkgs, key=str):
        _log.debug("  %s", str(pkg))

    _log.debug("Getting repo packages")
    repo_pkg_paths = _get_rpms("group", repo, tmp_dir)
    repo_dirs = [os.path.dirname(p) for p in repo_pkg_paths]
    repo_pkgs = list(
        _packages.get_packages_from_rpm_files(repo_pkg_paths).values()
    )
    _log.debug("Packages in the repos:")
    for pkg in sorted(repo_pkgs, key=str):
        _log.debug("  %s", str(pkg))

    iso_archs = {pkg.arch for pkg in iso_pkgs}
    _check_invalid_pkgs(
        repo_pkgs, iso_version, iso_archs, supports_owner_partner_packages
    )

    _log.debug("Grouping ISO and repo packages into blocks")
    iso_blocks = _blocks.group_packages(iso_pkgs)
    non_xr_iso_pkgs = {pkg for pkg in iso_pkgs if not _blocks.is_xr_pkg(pkg)}
    repo_blocks = _blocks.group_packages(set(repo_pkgs) | non_xr_iso_pkgs)

    _log.debug("Picking packages to go into main part of the GISO")
    giso_blocks = _pkgpicker.pick_installable_pkgs(
        iso_blocks, repo_blocks, pkglist, remove_packages
    )

    if only_support_pids is not None:
        _validate_pid_selection(only_support_pids, giso_blocks)
        pids_to_support = only_support_pids
    else:
        pids_to_support = list(giso_blocks.supported_pids)

    _log.debug("Filtering unsupported PIDs from the input ISO & repo pkgs")
    giso_blocks.filter_pkgs_to_supported_pids(pids_to_support)

    _log.debug("Packages picked to go in the GISO:")
    for group in _isoformat.PackageGroup:
        _log.debug("  Group %s", str(group))
        for pkg in sorted(giso_blocks.get_all_pkgs(group), key=str):
            _log.debug("    %s", str(pkg))

    pkg_to_file = _packages.packages_to_file_paths(
        repo_pkgs + iso_pkgs, [*iso_dirs, *repo_dirs]
    )

    if not skip_dep_check:
        _log.debug("Performing dependency and signature checks")
        key_type = (
            _pkgchecks.KeyType.DEV if dev_signed else _pkgchecks.KeyType.REL
        )
        _pkgchecks.run(giso_blocks, pkg_to_file, verbose_dep_check, key_type)

    for action in _pkgpicker.determine_output_actions(
        giso_blocks, iso_blocks, pkg_to_file, mdata
    ):
        action.run(out_dir)

    return list(
        pkg
        for group in _isoformat.PackageGroup
        for pkg in giso_blocks.get_all_pkgs(group)
    )


def _supports_owner_partner_packages(
    iso: image.Image, iso_version: str
) -> bool:
    """
    Determine whether the ISO supports specifying owner and partner packages.

    :param iso:
        The image object representing the ISO.

    :param iso_version:
        The XR version of the ISO.

    :returns:
        True if the ISO supports specifying owner and partner packages; False
        otherwise.
    """
    # ISO supports specifying owner and partner packages if it either contains
    # an image.py capability indicating that it is supported, or falls in the
    # range of XR versions since they were supported but before the image.py
    # capability was added.
    return iso.supports("owner-partner-packages") or any(
        iso_version.startswith(x)
        for x in _XR_VERSIONS_FOR_OWNER_PARTNER_BEFORE_CAP
    )


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
        args.only_support_pids,
        args.verbose_dep_check,
        args.skip_dep_check,
        tmp_dir,
        iso_content,
        iso_image.is_dev_signed,
        iso_version,
        _supports_owner_partner_packages(iso_image, iso_version),
    )

    # If key requests are to be removed or added, remove existing ones before
    # adding new ones.
    if args.clear_key_request or args.key_request:
        _file.clear_key_request(out_dir, iso_content)

    # Add key requests
    if args.key_request:
        _file.add_package(
            out_dir,
            pkg=args.key_request,
            group=_isoformat.PackageGroup.KEY_PKGS,
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
                args.only_support_pids,
                iso_content,
                out_dir,
                tmp_bridging_dir,
                iso_version,
                mdata["architecture"],
            )

    # Add any of the files that are specified
    if args.label:
        label_file = os.path.join(tmp_dir, "label")
        with open(label_file, "w") as lbl:
            lbl.write(args.label)
        _file.add_package(
            out_dir,
            file_to_add=label_file,
            file_type=_file.FileType.LABEL,
        )
    if args.xrconfig:
        _file.add_package(
            out_dir,
            file_to_add=args.xrconfig,
            file_type=_file.FileType.CONFIG,
        )
    if args.ztp_ini:
        _file.add_package(
            out_dir,
            file_to_add=args.ztp_ini,
            file_type=_file.FileType.ZTP,
        )

    new_mdata, new_buildinfo = _get_updated_mdata(
        args, iso_content, install_packages, args.no_buildinfo
    )
    # Only update the mdata.json if the "--no-buildinfo" argument is not given.
    _log.debug(
        "Updating ISO metadata in %s: %s",
        gisoglobals.LNT_MDATA_FILE,
        new_mdata,
    )
    json_mdata = json.dumps(new_mdata, indent=4)
    mdata_file = os.path.join(tmp_dir, gisoglobals.LNT_MDATA_FILE)
    with open(mdata_file, "w") as mdata_f:
        mdata_f.write(json_mdata)
    _file.add_package(
        out_dir,
        file_to_add=mdata_file,
        file_type=_file.FileType.MDATA,
    )

    # Update the build-info.txt even if the "--no-buildinfo" argument is given,
    # so it can be used for debugging (it is not used by install).
    _log.debug(
        "Updating ISO build info in %s: %s",
        gisoglobals.LNT_BUILDINFO_FILE,
        new_buildinfo,
    )
    buildinfo_file = os.path.join(tmp_dir, gisoglobals.LNT_BUILDINFO_FILE)
    with open(buildinfo_file, "w") as f:
        f.write(new_buildinfo)
    _file.add_package(
        out_dir,
        file_to_add=buildinfo_file,
        file_type=_file.FileType.BUILDINFO,
    )

    # Now that all desired files and packages have been added/removed repack
    # the ISO then build the USB image unless skipped
    platform_golden = "{}-golden".format(
        new_mdata["platform-family"],
    )
    arch = ""
    if "architecture" in new_mdata.keys():
        arch = "-{}".format(new_mdata["architecture"])
    xr_version = ""
    if "xr-version" in new_mdata.keys():
        xr_version += "-{}".format(new_mdata["xr-version"])
    label = ""
    if args.label is not None:
        label += "-{}".format(args.label)

    files_to_checksum = set()

    iso_name = f"{platform_golden}{arch}{xr_version}{label}.iso"
    iso_image.pack_iso(out_dir, iso_name)
    _log.info("Output to %s", str(os.path.join(out_dir, iso_name)))
    files_to_checksum.add(iso_name)

    iso_file = os.path.join(out_dir, iso_name)
    if not os.path.exists(iso_file):
        raise FailedToProduceIsoError()

    usb_file: Optional[str] = None
    if not args.skip_usb_image:
        usb_name = f"{platform_golden}{arch}-usb_boot{xr_version}{label}.zip"
        usb_file = os.path.join(out_dir, usb_name)
        iso_image.build_usb_image(iso_file, usb_file)
        files_to_checksum.add(usb_name)

    # Update permissions following ISO creation
    os.chmod(out_dir, 0o755)

    # Create checksum file, if requested
    checksum_file = None
    if args.create_checksum:
        checksum_file = gglobals.CHECKSUM_FILE_NAME
        ggisoutils.create_checksum_file(
            out_dir,
            files_to_checksum,
            checksum_file,
        )

    if args.copy_dir:
        _log.debug("Copying GISO to %s", args.copy_dir)
        copy_arts = [iso_file]
        if usb_file is not None and os.path.exists(usb_file):
            copy_arts.append(usb_file)
        if checksum_file is not None and os.path.exists(checksum_file):
            copy_arts.append(checksum_file)
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

    rc = 0
    try:
        iso_file, usb_file = _main(args, log_dir)
        _log_on_success(args, iso_file, usb_file, log_path)
    except Exception as exc:
        bes.log("Gisobuild failed: %s", str(exc))
        _log.error(
            "Gisobuild script failed, see %s for more info: %s",
            log_path,
            str(exc),
        )
        _log.debug(str(exc), exc_info=True)
        rc = 1

    return rc
