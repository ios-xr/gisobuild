# -----------------------------------------------------------------------------
# BSD 3-Clause License
#
# Copyright (c) 2021-2025, Cisco Systems, Inc. and its affiliates
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the [organization] nor the names of its contributors
#    may be used to endorse or promote products derived from this software
#    without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# -----------------------------------------------------------------------------

"""APIs used to modify the unpacked ISO."""

__all__ = (
    # APIs
    "add_package",
    "add_rpm",
    "add_key_request",
    "add_ownership_vouchers",
    "add_ownership_certificate",
    "add_bridging_bugfix",
    "get_zipped_and_unzipped_rpms",
    "remove_package",
    "clear_key_request",
    "clear_ownership_vouchers",
    "clear_ownership_certificate",
    # Exceptions
    "ItemToAddNotSpecifiedError",
    "CopyPkgError",
    "ItemToAddNotFoundError",
    "ISONotUnpackedError",
    "DeletePackageFailError",
)

import contextlib
import enum
import glob
import json
import logging
import os
import shutil
import tarfile
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from utils import gisoutils as ggisoutils

from .. import gisoutils
from . import _isoformat

# -------------------------------------------------------------------------
# Script global variables

_log = logging.getLogger("gisobuild")

###############################################################################
#                               Custom exceptions                             #
###############################################################################


class ItemToAddNotSpecifiedError(Exception):
    """Neither a group or file was specified to add to the unpacked iso"""

    def __init__(self) -> None:
        """Initialise a ItemToAddNotSpecifiedError"""
        super().__init__(
            "Nothing was selected to be added to the unpacked iso"
        )


class ItemToAddNotFoundError(Exception):
    """Could not find the item to add to the iso"""

    def __init__(self, source: str):
        """Initialise a ItemToAddNotFoundError"""
        super().__init__(
            "The item you are trying to add does not exist at %s", source
        )


class CopyPkgError(Exception):
    """Failed to add package or file to unpacked iso"""

    def __init__(self, source: str, dest: str, error: str):
        """Initialise a CopyPkgError"""
        super().__init__(
            "Failed to add file {} to {}: {}".format(source, dest, error)
        )


class ISONotUnpackedError(Exception):
    """Failed to find a directory."""

    def __init__(self, directory: str):
        """Initialise a ISONotUnpackedError"""
        super().__init__(
            "The ISO has not been unpacked correctly to {}".format(directory)
        )


class DeletePackageFailError(Exception):
    """Failed to delete a package in the unpacked ISO"""

    def __init__(self, item: str, error: str):
        """Initialise a DeletePackageFailError"""
        super().__init__(
            "Failed to remove package {} from the unpacked ISO: {}".format(
                item, error
            )
        )


class UpdateAttributeError(Exception):
    """Failed to delete a package in the unpacked ISO"""

    def __init__(self, attr: str, group: str, error: str):
        """Initialise a UpdateAttributeError"""
        super().__init__(
            "Failed to update the {} attribute for group {}: {}".format(
                attr, group, error
            )
        )


###############################################################################
#                               Custom classes                                #
###############################################################################


class FileType(enum.Enum):
    """
    The types of individual files that may be added to the GISO

    .. attribute:: CONFIG

        The file being added is a config file

    .. attribute:: LABEL

        The file being added is a label

    .. attribute:: ZTP

        The file being added is a ztp file

    .. attribute:: MDATA

        The file being added is the ISO mdata.json file

    ..attribute:: BUILDINFO
        The file being added is the ISO build-info.txt file

    """

    CONFIG = "config"
    LABEL = "label"
    ZTP = "ztp"
    MDATA = "mdata"
    BUILDINFO = "buildinfo"


###############################################################################
#                               Helper functions                              #
###############################################################################


@contextlib.contextmanager
def change_dir(directory: str) -> Generator[None, None, None]:
    """
    Cd's into the specified directory, raising a FileNotFoundError if
    unsuccessful

    :param directory:
        The directory we are going to cd into

    """
    original_ws = os.getcwd()
    try:
        os.chdir(directory)
        yield
    finally:
        os.chdir(original_ws)


def _unpack_tgz(tgz_file: str, tmp_dir: str) -> str:
    """
    Uncompresses a tgz file, returning a path to the directory with the
    unzipped files

    :param tgz_file:
        The path to the .tgz file

    :param tmp_dir:
        Temporary directory to unpack into

    :returns:
        String path to the unzipped directory

    """

    # Get the name of the tgz file which will be used as the directory name to
    # unpack into
    dirname = Path(os.path.basename(tgz_file)).resolve().stem

    output = os.path.join(tmp_dir, dirname, "tgz")
    _log.debug("Unpacking %s into %s", tgz_file, output)

    with tarfile.open(tgz_file, "r:gz") as tgz:
        ggisoutils.tar_extract_all(tgz, Path(output))

    return output


def _unpack_tar(tar_file: str, tmp_dir: str) -> str:
    """
    Uncompresses a tar file, returning a path to the directory with the
    unzipped files

    :param tar_file:
        The path to the .tar file

    :param tmp_dir:
        Temporary directory to unpack into

    :returns:
        String path to the unzipped directory

    """

    # Get the name of the tar file which will be used as the directory name to
    # unpack into
    dirname = Path(os.path.basename(tar_file)).resolve().stem

    output = os.path.join(tmp_dir, dirname, "tar")
    _log.debug("Unpacking %s into %s", tar_file, output)

    with tarfile.open(tar_file, "r") as tar:
        ggisoutils.tar_extract_all(tar, Path(output))

    return output


def _get_rpms_from_unzipped_dir(unzipped_dir: str) -> List[str]:
    """
    In a unzipped directory search any .rpm files and add them to a list

    :param unzipped_dir:
        Path to the unzipped directory

    :returns:
        List of paths to .rpm files

    """

    _log.debug("Looking in %s for .rpm files", unzipped_dir)
    rpms = set()
    for dirpath, _, files in os.walk(unzipped_dir):
        for file in files:
            if file.endswith(".rpm"):
                rpms.add(os.path.join(dirpath, file))

    return list(rpms)


def get_zipped_and_unzipped_rpms(item: str, tmp_dir: str) -> List[str]:
    """
    For a given item in a directory check to see if it is a zipped file. If it
    is unzip it and add it to the list. If it's just a rpm add that to the list
    too

    :param item:
        name of the file to check

    :param tmp_dir:
        Temporary directory to unpack into

    :returns:
        Paths to the found RPMs

    """
    rpms_found: List[str] = []
    if item.endswith(".tgz") or item.endswith(".tar.gz"):
        # Unpack the RPM if it's been compressed
        rpms_found += _get_rpms_from_unzipped_dir(_unpack_tgz(item, tmp_dir))
    elif item.endswith(".tar"):
        rpms_found += _get_rpms_from_unzipped_dir(_unpack_tar(item, tmp_dir))
    elif item.endswith(".rpm"):
        rpms_found.append(item)

    return rpms_found


def _ensure_group_exists(iso_dir: str, group: _isoformat.PackageGroup) -> None:
    """
    Ensure the given group exists within the ISO. If it does not exist, create
    it; if it does not have group attributes, create those too.
    """
    pkg_path = os.path.join(
        iso_dir, _isoformat.ISO_GROUP_PKG_DIR.format(group.group_name)
    )
    os.makedirs(pkg_path, exist_ok=True)

    attr_dir = os.path.join(
        iso_dir, _isoformat.ISO_GROUP_ATTR_DIR.format(group.group_name)
    )
    os.makedirs(attr_dir, exist_ok=True)

    for attr in group.attributes:
        with open(
            os.path.join(
                iso_dir,
                _isoformat.ISO_GROUP_ATTR_FILE.format(
                    group.group_name, attr.name
                ),
            ),
            "w",
        ) as f:
            f.write(attr.to_json())


###############################################################################
#                                   APIs                                      #
###############################################################################


def get_rpms_from_dir(dir_path: str, tmp_dir: str) -> List[str]:
    """
    For a given directory, search for any RPMs and return them. If there are
    any tgz or tar files then unzip them, search in these unpacked dirs for any
    RPMs and return these as well

    :param dir_path:
        Path to the directory to search

    :param tmp_dir:
        Temporary directory to unpack into

    :returns:
        Paths to the found RPMs

    """

    rpms_found: List[str] = []
    for item in os.listdir(dir_path):
        rpms_found += get_zipped_and_unzipped_rpms(
            os.path.join(dir_path, item), tmp_dir
        )

    return rpms_found


def get_group_package_dir(iso_dir: str, group: str) -> str:
    """
    Retrieve the package directory for the specified group

    :param iso_dir:
        The directory in which the ISO has been unpacked

    :param group:
        Name of group to retrieve

    :returns:
        Path to group package directory
    """
    group_dir = os.path.join(
        iso_dir, _isoformat.ISO_GROUP_PKG_DIR.format(group)
    )
    return group_dir


def get_group_rpms(iso_dir: str, group: str) -> List[str]:
    """
    Retrieve a list of all RPMs in the specified group within the ISO

    :param iso_dir:
        The directory in which the ISO has been unpacked

    :param group:
        Name of group to retrieve
    """
    group_dir = get_group_package_dir(iso_dir, group)
    if os.path.exists(group_dir):
        return _get_rpms_from_unzipped_dir(group_dir)
    return []


def add_package(
    iso_dir: str,
    pkg: Optional[str] = None,
    group: Optional[_isoformat.PackageGroup] = None,
    file_to_add: Optional[str] = None,
    file_type: Optional[FileType] = None,
) -> None:
    """
    Adds the specified package to the unpacked ISO directory where it will be
    repacked into the ISO

    :param iso_dir:
        The directory in which the ISO has been unpacked

    :param pkg:
        The location of the package to add

    :param group:
        Name of the group to add the package to

    :param file_to_add:
        Should be set if group is not specified. Add the file to the relevant
        place in the top level ISO. file_type must also be set to indicate
        which file is being added.

    :param file_type:
        What sort of file is being added


    """

    # Check that the ISO has been unpacked before beginning
    if not os.path.exists(iso_dir):
        _log.error("ISO has not been unpacked into %s", iso_dir)
        raise ISONotUnpackedError(iso_dir)

    # If a group has been specified and not a file then add the package under
    # that group. If a file has been specified but not a group then add the
    # file to its place in the top level ISO.
    if group and not file_to_add:
        # Groups are stored in the unpacked iso as group.<name>
        dest = os.path.join(
            iso_dir, _isoformat.ISO_GROUP_PKG_DIR.format(group.group_name)
        )
        # Make the packages directory if it doesn't already exist
        _ensure_group_exists(iso_dir, group)
        source = pkg
    elif file_to_add and not group:
        # Map the file to the expected location in the ISO
        if file_type is FileType.CONFIG:
            dest = os.path.join(iso_dir, _isoformat.ISO_PATH_INIT_CFG)
        elif file_type is FileType.ZTP:
            dest = os.path.join(iso_dir, _isoformat.ISO_PATH_ZTP)
        elif file_type is FileType.LABEL:
            dest = os.path.join(iso_dir, _isoformat.ISO_PATH_LABEL)
        elif file_type is FileType.MDATA:
            if os.path.exists(
                os.path.join(iso_dir, _isoformat.ISO_PATH_MDATA_751)
            ):
                dest = os.path.join(iso_dir, _isoformat.ISO_PATH_MDATA_751)
            else:
                dest = os.path.join(iso_dir, _isoformat.ISO_PATH_MDATA)
        elif file_type is FileType.BUILDINFO:
            dest = os.path.join(iso_dir, _isoformat.ISO_PATH_BUILDINFO)
        source = file_to_add
    else:
        raise ItemToAddNotSpecifiedError()

    source = str(source)
    if not os.path.exists(source):
        raise ItemToAddNotFoundError(source)
    if not os.path.exists(os.path.dirname(dest)):
        _log.debug("Creating directory %s", os.path.dirname(dest))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        _log.debug("Adding %s to %s in the unpacked ISO", source, dest)
        shutil.copy2(source, dest)
    except OSError as error:
        raise CopyPkgError(source, dest, str(error)) from error


def add_rpm(pkg: str, iso_dir: str, group: _isoformat.PackageGroup) -> None:
    """
    Add a RPM to the unpacked ISO

    :param pkg:
        The package to add to the main group

    :param iso_dir:
        The directory in which the ISO has been unpacked and to add the package
        to

    :param group:
        The group to which the package should be added

    """

    add_package(iso_dir, pkg=pkg, group=group)


def add_key_request(iso_dir: str, pkg: str) -> None:
    """
    Add a key request to the unpacked ISO

    :param pkg:
        The key request to add to the keys group

    :param iso_dir:
        The directory in which the ISO has been unpacked and to add the package
        to

    """

    add_package(iso_dir, pkg=pkg, group=_isoformat.PackageGroup.KEY_PKGS)


def add_ownership_vouchers(iso_dir: str, pkg: str) -> None:
    """
    Add an ownership voucher to the unpacked ISO

    :param pkg:
        The ownership voucher package to add to the ownership vouchers group.

    :param iso_dir:
        The directory in which the ISO has been unpacked and to add the package
        to.

    """
    add_package(
        iso_dir, pkg=pkg, group=_isoformat.PackageGroup.OWNERSHIP_VOUCHERS
    )


def add_ownership_certificate(iso_dir: str, pkg: str) -> None:
    """
    Add an ownership certificate to the unpacked ISO

    :param pkg:
        The ownership certificate package to add to the ownership certificate
        group.

    :param iso_dir:
        The directory in which the ISO has been unpacked and to add the package
        to.

    """
    add_package(
        iso_dir, pkg=pkg, group=_isoformat.PackageGroup.OWNERSHIP_CERTIFICATE
    )


def add_bridging_bugfix(pkg: str, iso_dir: str) -> None:
    """
    Add a bugfix RPM to the unpacked ISO.

    :param pkg:
        The bridging bugfix package to add to the bridging group.

    :param iso_dir:
        The directory in which the ISO has been unpacked and to add the package
        to.

    """
    add_package(iso_dir, pkg=pkg, group=_isoformat.PackageGroup.BRIDGING_PKGS)


def clear_bridging_bugfixes(iso_dir: str, mdata: Dict[str, Any]) -> None:
    """
    Remove all bridging bugfixes from the unpacked ISO

    :param iso_dir:
        The directory in which the ISO has been unpacked

    :param mdata:
        Iso metadata, as parsed json object returned from query content

    """
    bridging_groups = gisoutils.get_groups_with_attr(
        mdata["groups"], "bridging"
    )
    for group in bridging_groups:
        group_dir = os.path.join(
            iso_dir, _isoformat.ISO_GROUP_PKG_DIR.format(group)
        )
        if os.path.exists(group_dir):
            shutil.rmtree(group_dir)
            _log.debug(
                "Removed packages %s",
                _isoformat.ISO_GROUP_PKG_DIR.format(group),
            )
        else:
            _log.debug(
                "Could not find the %s directory, so have not attempted to delete any bridging bugfixes",
                _isoformat.ISO_GROUP_PKG_DIR.format(group),
            )


def clear_key_request(iso_dir: str, mdata: Dict[str, Any]) -> None:
    """
    Remove the key request from the unpacked ISO.

    :param iso_dir:
        The directory in which the ISO has been unpacked.

    :param mdata:
        Iso metadata, as parsed json object returned from query content.

    """
    key_request_groups = gisoutils.get_groups_with_attr(
        mdata["groups"], "key_packages"
    )
    for group in key_request_groups:
        group_dir = os.path.join(
            iso_dir, _isoformat.ISO_GROUP_PKG_DIR.format(group)
        )
        if os.path.exists(group_dir):
            shutil.rmtree(group_dir)
            _log.debug(
                "Removed key requests '%s'",
                _isoformat.ISO_GROUP_PKG_DIR.format(group),
            )
        else:
            _log.debug(
                "Could not find the %s directory, so have not attempted to delete any key packages",
                _isoformat.ISO_GROUP_PKG_DIR.format(group),
            )


def clear_ownership_vouchers(iso_dir: str, mdata: Dict[str, Any]) -> None:
    """
    Remove the ownership vouchers from the unpacked ISO.

    :param iso_dir:
        The directory in which the ISO has been unpacked.

    :param mdata:
        Iso metadata, as parsed json object returned from query content.

    """
    ownership_vouchers_groups = gisoutils.get_groups_with_attr(
        mdata["groups"], "ownership_vouchers"
    )
    for group in ownership_vouchers_groups:
        group_dir = os.path.join(
            iso_dir, _isoformat.ISO_GROUP_PKG_DIR.format(group)
        )
        if os.path.exists(group_dir):
            shutil.rmtree(group_dir)
            _log.debug(
                "Removed ownership vouchers '%s'",
                _isoformat.ISO_GROUP_PKG_DIR.format(group),
            )
        else:
            _log.debug(
                "Could not find the %s directory, so have not attempted to delete any ownership vouchers",
                _isoformat.ISO_GROUP_PKG_DIR.format(group),
            )


def clear_ownership_certificate(iso_dir: str, mdata: Dict[str, Any]) -> None:
    """
    Remove the ownership certificate from the unpacked ISO.

    :param iso_dir:
        The directory in which the ISO has been unpacked.

    :param mdata:
        Iso metadata, as parsed json object returned from query content.

    """
    ownership_certificate_groups = gisoutils.get_groups_with_attr(
        mdata["groups"], "ownership_certificate"
    )
    for group in ownership_certificate_groups:
        group_dir = os.path.join(
            iso_dir, _isoformat.ISO_GROUP_PKG_DIR.format(group)
        )
        if os.path.exists(group_dir):
            shutil.rmtree(group_dir)
            _log.debug(
                "Removed ownership certificate '%s'",
                _isoformat.ISO_GROUP_PKG_DIR.format(group),
            )
        else:
            _log.debug(
                "Could not find the %s directory, so have not attempted to delete any ownership certificates",
                _isoformat.ISO_GROUP_PKG_DIR.format(group),
            )


def remove_package(pkg: str, iso_dir: str, mdata: Dict[str, Any]) -> None:
    """
    Remove any packages matching the given package name or pattern from any
    groups in the install package set

    :param pkg:
        The package name or pattern to remove from the unpacked ISO

    :param iso_dir:
        The directory in which the ISO has been unpacked and to remove the
        package from

    :param mdata:
        Iso metadata, as parsed json object returned from query content

    """
    installable_groups = _isoformat.get_installable_groups(mdata["groups"])

    # Find all the packages that match the given pattern in the unpacked ISO
    # and remove them
    with change_dir(iso_dir):
        # Search under groups/*/packages so we don't end up accidentally
        # removing top level files
        for group in installable_groups:
            search_pattern = (
                _isoformat.ISO_GROUP_PKG_DIR.format(group) + "/" + pkg
            )
            for item in glob.iglob(search_pattern):
                try:
                    os.remove(item)
                except OSError as error:
                    raise DeletePackageFailError(item, str(error)) from error


def update_attr(attr: str, group: str, value: str, iso_dir: str) -> None:
    """
    Update a group attribute with a new value

    :param attr:
        The attribute to update

    :param group:
        The group whose attribute is to be updated

    :param value:
        The value to update the attribute to

    :param iso_dir:
        The directory the ISO is in

    """

    group_dir = os.path.join(iso_dir, "groups/group.{}".format(group))
    if os.path.exists(group_dir):
        attr_dir = os.path.join(group_dir, "attributes")
        if not os.path.exists(attr_dir):
            os.makedirs(attr_dir)
        try:
            with open(
                os.path.join(attr_dir, "{}.attr.json".format(attr)),
                "r",
            ) as f:
                attr_json = json.load(f)
            attr_json["value"] = value
            with open(
                os.path.join(attr_dir, "{}.attr.json".format(attr)),
                "w",
            ) as f:
                json.dump(attr_json, f, indent=4, sort_keys=True)
        except OSError as error:
            raise UpdateAttributeError(attr, group, str(error)) from error
