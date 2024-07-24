# -----------------------------------------------------------------------------

""" APIs used to modify the unpacked ISO.

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
    # APIs
    "add_package",
    "add_rpm",
    "add_keys",
    "add_bridging_bugfix",
    "get_zipped_and_unzipped_rpms",
    "remove_package",
    "remove_all_key_requests",
    "remove_key_requests",
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


def add_keys(pkg: str, iso_dir: str) -> None:
    """
    Add a key package to the unpacked ISO

    :param pkg:
        The key package to add to the keys group

    :param iso_dir:
        The directory in which the ISO has been unpacked and to add the package
        to

    """

    add_package(iso_dir, pkg=pkg, group=_isoformat.PackageGroup.KEY_PKGS)


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
        shutil.rmtree(
            os.path.join(iso_dir, _isoformat.ISO_GROUP_PKG_DIR.format(group))
        )
        _log.debug(
            "Removed packages %s", _isoformat.ISO_GROUP_PKG_DIR.format(group)
        )


def remove_all_key_requests(iso_dir: str, mdata: Dict[str, Any]) -> None:
    """
    Remove all key requests from the unpacked ISO.

    :param iso_dir:
        The directory in which the ISO has been unpacked.

    :param mdata:
        Iso metadata, as parsed json object returned from query content.

    """
    key_request_groups = gisoutils.get_groups_with_attr(
        mdata["groups"], "key_packages"
    )
    for group in key_request_groups:
        shutil.rmtree(
            os.path.join(iso_dir, _isoformat.ISO_GROUP_PKG_DIR.format(group))
        )
        _log.debug(
            "Removed key requests '%s'",
            _isoformat.ISO_GROUP_PKG_DIR.format(group),
        )


def remove_key_requests(
    iso_dir: str, mdata: Dict[str, Any], key_requests: List[str]
) -> None:
    """
    Remove specified key requests from the unpacked ISO.

    :param iso_dir:
        The directory in which the ISO has been unpacked.

    :param mdata:
        Iso metadata, as parsed json object returned from query content.

    :param key_requests:
        Filenames of key requests to be removed.

    """
    key_request_groups = gisoutils.get_groups_with_attr(
        mdata["groups"], "key_packages"
    )
    missing_key_requests: List[str] = key_requests.copy()
    for group in key_request_groups:
        packages_dir = os.path.join(
            iso_dir, _isoformat.ISO_GROUP_PKG_DIR.format(group)
        )
        for key_request in key_requests:
            key_request_path = os.path.join(
                packages_dir, os.path.basename(key_request)
            )
            if os.path.exists(key_request_path):
                os.remove(key_request_path)
                missing_key_requests.remove(key_request)
                _log.debug(
                    "Removed key request '%s' in group '%s'",
                    key_request,
                    group,
                )
    if missing_key_requests:
        msg = (
            "Some user-specified key requests to be removed could not be found "
            "in the ISO. This may be due to a user error: {}".format(
                ", ".join(sorted(missing_key_requests))
            )
        )
        _log.warning(msg)
        print(f"WARNING: {msg}")


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
                os.path.join(attr_dir, "{}.attr.json".format(attr)), "r",
            ) as f:
                attr_json = json.load(f)
            attr_json["value"] = value
            with open(
                os.path.join(attr_dir, "{}.attr.json".format(attr)), "w",
            ) as f:
                json.dump(attr_json, f, indent=4, sort_keys=True)
        except OSError as error:
            raise UpdateAttributeError(attr, group, str(error)) from error
