# -----------------------------------------------------------------------------

""" Tool to generate a diff between two ISOs.

Copyright (c) 2022-2023 Cisco and/or its affiliates.
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

__all__ = ("RPMQueryError", "run")


import argparse
import collections
from dataclasses import asdict, dataclass
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile

from typing import Any, Dict, List, Tuple

import defusedxml.ElementTree as elemtree  # type: ignore

from .. import (
    gisoutils,
    image,
)

_log = logging.getLogger()

# Globals
DFLT_OUTPUT_DIR = "output_isodiff"
_LOGFILE = "isodiff.log"

# The names of the JSON dump files
_HIGH_LEVEL_DIFF = "db_diff.json"
_RPM_DIFF = "rpm_db_diff.json"

###############################################################################
#                                 Exceptions                                  #
###############################################################################


class AttributeNotFoundError(Exception):
    """Package is missing an attribute"""

    def __init__(self, attr: str, error: str):
        """Initialise a AttributeNotFoundError"""
        super().__init__(
            "Package missing the {} attribute: {}".format(attr, error)
        )


class OutputDirNotEmptyError(Exception):
    """The specified output dir isn't empty"""

    def __init__(self, output_dir: str):
        """Initialise a OutputDirNotEmptyError"""
        super().__init__(
            "The specified output dir is not empty: {}. Use the --clean option to overwrite it.".format(
                output_dir
            )
        )


class ISOInfoError(Exception):
    """Failed to extract file from ISO"""

    def __init__(self, cmd: List[str], error: str) -> None:
        """Call parent's initialiser with a suitable error message"""
        super().__init__(
            "Failed to extract file from the ISO with command {}: {}".format(
                cmd, error
            )
        )


###############################################################################
#                            Classes                                          #
###############################################################################


@dataclass(frozen=True)
class Package:
    """Package in an ISO."""

    name: str
    version: str
    release: str
    arch: str
    size: int
    group: str

    @property
    def rpm_name(self) -> str:
        """RPM file name for the package."""

        return "{}-{}-{}.{}.rpm".format(
            self.name, self.version, self.release, self.arch
        )


@dataclass(frozen=True, order=True)
class RPMFile:
    """RPM file in an ISO."""

    filename: str
    size: int


###############################################################################
#                            Helper functions                                 #
###############################################################################


def listdir(path: str) -> List[str]:
    """
    List contents of a directory.

    Enables tests to mock listdir() calls from this file without interfering
    with stdlib functions such as tempfile.TemporaryDirectory() which also
    call os.listdir().
    """
    return os.listdir(path)


class RPMQueryError(Exception):
    """Failed to query RPM correctly"""

    def __init__(self, rpm: str, error: str):
        """Initialise a RPMQueryError"""
        super().__init__("Query of RPM {} failed: {}".format(rpm, error))


def _query_rpm(rpm: str) -> List[RPMFile]:
    """
    Query the RPM to collect the list of files it contains

    :param rpm:
        The name of the RPM to query

    :returns:
        List of files and their sizes contained within the RPM

    """

    qf = "[%{FILENAMES}\t%{FILESIZES}\t%{FILEMODES:perms}\n]"
    try:
        output = subprocess.check_output(
            ["rpm", "-qp", "--qf", qf, rpm],
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
        )
    except subprocess.CalledProcessError as error:
        raise RPMQueryError(rpm, str(error)) from error

    # The output is returned one file per line
    #    <file>\t<size>\t<permissions>
    # e.g.
    # /usr/bin/yes.coreutils  34984   -rwxr-xr-x
    # /usr/lib64      0       drwxr-xr-x
    #
    # Just return files, not directories
    files = []
    for line in output.splitlines():
        if not line.strip() or line in ("(contains no files)",):
            continue
        filename, size, perms = line.split("\t", maxsplit=2)
        if perms.startswith("d"):
            continue
        files.append(RPMFile(filename=filename, size=int(size)))

    return files


def _get_rpm_files(
    pkg_list: List[Package], extracted_rpms: List[str], extract_dir: str
) -> Dict[Package, List[RPMFile]]:
    """
    Query rpms that are in the pkg list and get their file lists

    :param pkg_list:
        List of packages

    :param extracted_rpms:
        List of filenames of rpms that have been extracted from the ISO

    :param extract_dir:
        Directory in which RPMs have been extracted

    :returns:
        Mapping from package name to files

    """

    pkg_to_files = {}
    for pkg in pkg_list:
        if pkg.rpm_name in extracted_rpms:
            files = _query_rpm(
                os.path.join(
                    extract_dir,
                    "groups/group.{}/packages".format(pkg.group),
                    pkg.rpm_name,
                )
            )
            pkg_to_files[pkg] = files
        else:
            pkg_to_files[pkg] = []

    return pkg_to_files


def _compare_pkg_files(
    name: str,
    pkg_list_1: Dict[Package, List[RPMFile]],
    pkg_list_2: Dict[Package, List[RPMFile]],
    unchanged_pkg_list: Dict[Package, List[RPMFile]],
) -> Tuple[
    List[Tuple[RPMFile, RPMFile]], List[RPMFile],
]:
    """
    Compare files within a RPM and determine whether they should be added to
    one of the following lists:

    - size: the files sizes differ between the two ISOs
    - unchanged: the files are the same in the two ISOs

    :param name:
        Name of the pkg to compare files for

    :param pkg_list_1:
        List of dictionaries containing information on the packages in ISO 1

    :param pkg_list_2:
        List of dictionaries containing information on the packages in ISO 2

    :param unchanged_pkg_list:
        List of dictionaries containing information on the packages unchanged
        between the different ISOs

    :returns:
        Tuple of the size and unchanged lists

    """

    # Build up a list of file names that are shared between the packages and
    # their sizes
    file_sizes: Dict[str, Dict[str, int]] = {}
    for pkg, rpm_files in pkg_list_1.items():
        if pkg.name == name:
            for _file in rpm_files:
                file_sizes[_file.filename] = {
                    "size-1": _file.size,
                    "size-2": 0,
                }
    for pkg, rpm_files in pkg_list_2.items():
        if pkg.name == name:
            for _file in rpm_files:
                if _file.filename in file_sizes:
                    file_sizes[_file.filename]["size-2"] = _file.size
                else:
                    file_sizes[_file.filename] = {
                        "size-1": 0,
                        "size-2": _file.size,
                    }

    # Walk through the list and add them to the appropriate list depending on
    # their size difference
    size: List[Tuple[RPMFile, RPMFile]] = []
    unchanged: List[RPMFile] = []
    for filename, file_data in file_sizes.items():
        if file_data["size-1"] == file_data["size-2"]:
            unchanged.append(RPMFile(filename, file_data["size-1"]))
        else:
            size.append(
                (
                    RPMFile(filename, file_data["size-1"]),
                    RPMFile(filename, file_data["size-2"]),
                )
            )

    for pkg, rpm_files in unchanged_pkg_list.items():
        if pkg.name == name:
            for _file in rpm_files:
                unchanged.append(_file)

    return size, unchanged


def _dump_json(
    size_1: int,
    size_2: int,
    pkg_to_files_1: Dict[Package, List[RPMFile]],
    pkg_to_files_2: Dict[Package, List[RPMFile]],
    pkg_to_files_unchanged: Dict[Package, List[RPMFile]],
    file_list_1: List[RPMFile],
    file_list_2: List[RPMFile],
    unchanged_file_list: List[RPMFile],
    output_dir: str,
) -> None:
    """
    Dump JSON of the changed and unchanges files in the ISO. There will be two
    diff JSON dumps:
    - A high level dump containing: list of RPMs and files that are different
      for each ISO and their sizes; a list of unchanged RPMs and files and
      their sizes; sizes of the ISOs; size difference between the ISOs
    - A per-rpm diff dump: list of rpms, each having: the architecture, version
      /release, filename and files of the rpm as it appears in the ISO, the
      list of files that are different and a list of files that are unchanged

    :param size_1:
        Size in bytes of ISO1

    :param size_2:
        Size in bytes of ISO2

    :param pkg_list_1:
        Mapping of package to list of files for the packages in ISO 1

    :param pkg_list_2:
        Mapping of package to list of files for the packages in ISO 2

    :param unchanged_pkg_list:
        Mapping of package to list of files for the packages unchanged
        between the two ISOs

    :param file_list_1:
        List of files in the top level of ISO 1

    :param file_list_2:
        List of files in the top level of ISO 2

    :param unchanged_file_list:
        List of files in the top levels of both ISOs that are unchanged

    :param output_dir:
        Path to the output directory to dump the JSON in

    """

    # First dump the high level ISO dump
    def files_dump(
        pkgs: Dict[Package, List[RPMFile]], files: List[RPMFile]
    ) -> List[Dict[str, Any]]:
        pkg_files = [
            {"filename": pkg.rpm_name, "size": pkg.size} for pkg in pkgs
        ]
        return pkg_files + [asdict(file) for file in files]

    high_level_dump: Dict[str, Any] = {
        "iso-1-changed-files": files_dump(pkg_to_files_1, file_list_1),
        "iso-2-changed-files": files_dump(pkg_to_files_2, file_list_2),
        "iso-1-size": size_1,
        "iso-2-size": size_2,
        "iso-size-diff": abs(size_2 - size_1),
        "unchanged": files_dump(pkg_to_files_unchanged, unchanged_file_list),
    }

    # json.dump(high_level_dump, sys.stdout, indent=4, sort_keys=True)
    with open(os.path.join(output_dir, _HIGH_LEVEL_DIFF), "w") as json_file:
        json.dump(high_level_dump, json_file, indent=4, sort_keys=True)
    _log.debug("Dumped high level ISO diff")

    # Second create the per-rpm dump
    def rpm_dump(pkg: Package, rpm_files: List[RPMFile]) -> Dict[str, Any]:
        return {
            "rpm_arch": pkg.arch,
            "rpm_evr": "{}.{}".format(pkg.version, pkg.release),
            "rpm_filename": pkg.rpm_name,
            "rpm_files": [_file.filename for _file in rpm_files],
        }

    rpms_dump: Dict[str, Dict[str, Any]] = collections.defaultdict(dict)
    # For each package add the iso-specific information
    for i, pkg_to_files in enumerate([pkg_to_files_1, pkg_to_files_2]):
        for pkg, rpm_files in pkg_to_files.items():
            # For each package name add the package information as it appears
            # in both ISOs
            rpms_dump[pkg.name][str(i + 1)] = rpm_dump(pkg, rpm_files)

    # If the package is the same in both ISOs, add the same package information
    for pkg, rpm_files in pkg_to_files_unchanged.items():
        for i in (1, 2):
            rpms_dump[pkg.name][str(i)] = rpm_dump(pkg, [])

    # Walk through the packages, get their files and add the files to one of
    # three lists:
    # - size: the files sizes differ between the two ISOs
    # - unchanged: the files are the same in the two ISOs
    for pkg_name, data in rpms_dump.items():
        size, unchanged = _compare_pkg_files(
            pkg_name, pkg_to_files_1, pkg_to_files_2, pkg_to_files_unchanged
        )
        data["size"] = [
            {"filename": a.filename, "size-1": a.size, "size-2": b.size}
            for a, b in size
        ]
        data["unchanged"] = [asdict(f) for f in unchanged]

        iso_1_files = data["1"]["rpm_files"] if "1" in data.keys() else []
        iso_2_files = data["2"]["rpm_files"] if "2" in data.keys() else []
        for _file in unchanged:
            if _file.filename in iso_1_files:
                rpms_dump[pkg_name]["1"]["rpm_files"].remove(_file.filename)
            if _file.filename in iso_2_files:
                rpms_dump[pkg_name]["2"]["rpm_files"].remove(_file.filename)

    with open(os.path.join(output_dir, _RPM_DIFF), "w") as json_file:
        json.dump(rpms_dump, json_file, indent=4, sort_keys=True)
    _log.debug("Dumped per-RPM ISO diff")


def _get_iso_files(iso: image.Image) -> List[RPMFile]:
    """
    Get the list of files present in an ISO.

    :param iso:
        The ISO to query

    :returns:
        Top level files

    """

    return sorted(
        RPMFile(f.filename.lstrip("/"), f.size)
        for f in iso.list_files()
        if not f.is_dir
    )


def _get_package_lists(
    iso1: image.Image, iso2: image.Image
) -> Tuple[List[Package], List[Package], List[str], List[str]]:
    """
    For each individual ISO get the repodata for each group to build up a
    list of packages contained in that ISO.

    :param iso1:
        The first ISO to query

    :param iso2:
        The second ISO to query

    :returns:
        For each ISO, the packages and the groups contained within the ISO.

    """

    # Packages and groups that are present in both ISOs
    pkg_list_1: List[Package] = []
    pkg_list_2: List[Package] = []
    groups_in_iso1: List[str] = []
    groups_in_iso2: List[str] = []

    for iso, pkg_list, groups in [
        (iso1, pkg_list_1, groups_in_iso1),
        (iso2, pkg_list_2, groups_in_iso2),
    ]:
        for group in iso.list_groups():
            try:
                repodata = iso.get_repodata(group)
                mdata = elemtree.fromstring(repodata)
            except elemtree.ParseError as error:
                print(f"BADREPODATA: {repodata}")
                raise image.GetRepoDataError(iso, group, str(error)) from error

            # Strip the namespace data for easier parsing.
            gisoutils.xml_strip_ns(mdata)
            # Store the relevant information in a dictionary for each
            # package
            for pkg in mdata:
                if pkg is not None:
                    try:
                        version = pkg.find("version")
                        pkg_to_add = Package(
                            name=pkg.find("name").text,
                            version=version.attrib["ver"],
                            release=version.attrib["rel"],
                            arch=pkg.find("arch").text,
                            size=int(pkg.find("size").get("package")),
                            group=group,
                        )
                    except (KeyError, AttributeError) as error:
                        raise image.GetRepoDataError(
                            iso, group, str(error)
                        ) from error

                    # To start with, assume there are no shared packages and
                    # add the pkg lists to a list specific to that iso
                    pkg_list.append(pkg_to_add)
            # If the group contains packages add it to the list
            if group not in groups:
                groups.append(group)

    return pkg_list_1, pkg_list_2, groups_in_iso1, groups_in_iso2


def _get_package_files(
    iso1: image.Image,
    iso2: image.Image,
    iso_shared_list: List[Package],
    iso_pkg_list_1: List[Package],
    iso_pkg_list_2: List[Package],
    groups_in_iso1: List[str],
    groups_in_iso2: List[str],
) -> Tuple[
    Dict[Package, List[RPMFile]],
    Dict[Package, List[RPMFile]],
    Dict[Package, List[RPMFile]],
]:
    """
    For each package in the shared or individual ISO package lists, extract the
    file names and update the list

    :param iso1:
        The first ISO the user specified.

    :param iso2:
        The second ISO the user specified.

    :param iso_shared_list:
        List of packages that are shared between ISO1 and ISO2

    :param iso_pkg_list_1:
        List of packages unique to ISO1

    :param iso_pkg_list_2:
        List of packages unique to ISO2

    :param groups_in_iso1:
        List of groups in ISO1

    :param groups_in_iso2:
        List of groups in ISO2

    :returns:
        Tuple of image_script, iso_pkg_list_1, iso_pkg_list_2, updated so that
        they now contain the filenames contained with their packages

    """

    with tempfile.TemporaryDirectory() as extract_dir:
        # Extract all rpms for all the groups in ISO1
        iso1.extract_groups(
            groups_in_iso1, extract_dir,
        )
        # Get the list of rpms that were extracted
        extracted_rpms = [
            pkg
            for group in listdir(os.path.join(extract_dir, "groups"))
            if os.path.exists(
                os.path.join(extract_dir, "groups", group, "packages")
            )
            for pkg in listdir(
                os.path.join(extract_dir, "groups", group, "packages")
            )
        ]
        iso_shared_pkgs_to_files = _get_rpm_files(
            iso_shared_list, extracted_rpms, extract_dir
        )
        iso_pkgs_to_files_1 = _get_rpm_files(
            iso_pkg_list_1, extracted_rpms, extract_dir
        )

    with tempfile.TemporaryDirectory() as extract_dir:
        iso2.extract_groups(
            groups_in_iso2, extract_dir,
        )
        extracted_rpms = [
            pkg
            for group in listdir(os.path.join(extract_dir, "groups"))
            if os.path.exists(
                os.path.join(extract_dir, "groups", group, "packages")
            )
            for pkg in listdir(
                os.path.join(extract_dir, "groups", group, "packages")
            )
        ]
        iso_pkgs_to_files_2 = _get_rpm_files(
            iso_pkg_list_2, extracted_rpms, extract_dir
        )

    return iso_shared_pkgs_to_files, iso_pkgs_to_files_1, iso_pkgs_to_files_2


###############################################################################
#                          Main and argument handling                         #
###############################################################################


def run_iso_diff(args: argparse.Namespace) -> None:
    """
    Obtain the diff of the two ISOs

    The function proceeds as follows:
    - For each individual ISO get the repodata for each group to build up a
      list of packages for that iso
    - Go through each list and determine whether there are any shared packages
      by comparing package version number and release
    - Any packages that aren't in the shared list are added to a list for each
      ISO that contain packages that are unique to that ISO
    - Get the list of files present for each RPM in the shared list, ISO1 list
      and ISO2 list
    - Get the list of top level ISO files for each ISO and their size
    - JSON dump the information we have collected

    :param args:
        The parsed arguments that will be used for the script

    """

    # Clean the output directory if one was specified and clean was specified
    if not os.path.exists(args.OUTPUT_DIR):
        os.makedirs(args.OUTPUT_DIR)
    elif len(listdir(args.OUTPUT_DIR)) != 0:
        if args.OUT_CLEAN:
            items = [
                os.path.join(args.OUTPUT_DIR, item)
                for item in listdir(args.OUTPUT_DIR)
            ]
            for item in items:
                if os.path.isfile(item):
                    os.remove(item)
                elif os.path.isdir(item):
                    shutil.rmtree(item, ignore_errors=True)
        else:
            raise OutputDirNotEmptyError(args.OUTPUT_DIR)

    iso1 = image.Image(
        args.ISO1,
        prefix="isodiff1",
        log_dir=args.log_dir,
        disable_logging=args.no_logs,
    )
    iso2 = image.Image(
        args.ISO2,
        prefix="isodiff2",
        log_dir=args.log_dir,
        disable_logging=args.no_logs,
    )

    # Obtain the repodata for each group in each ISO, collect its package
    # information and add to the list of packages in the ISO
    (
        pkg_list_1,
        pkg_list_2,
        groups_in_iso1,
        groups_in_iso2,
    ) = _get_package_lists(iso1, iso2)

    # Initialise list corresponding to RPMs that are unchanged in both ISO 1
    # and ISO 2(present in both ISOs with the same version)
    iso_shared_list: List[Package] = []
    iso_pkg_list_1: List[Package] = []
    iso_pkg_list_2: List[Package] = []

    # Iterate over both package lists and if there is an RPM that is shared
    # between the ISOs add it to the shared set
    for pkg_1 in pkg_list_1:
        for pkg_2 in pkg_list_2:
            if pkg_1 == pkg_2 and pkg_1 not in iso_shared_list:
                iso_shared_list.append(pkg_1)

    # Create lists of RPMs that are different in ISO1 and ISO 2
    iso_pkg_list_1 = [
        pkg
        for pkg in pkg_list_1
        if pkg not in iso_shared_list and pkg not in iso_pkg_list_1
    ]
    iso_pkg_list_2 = [
        pkg
        for pkg in pkg_list_2
        if pkg not in iso_shared_list and pkg not in iso_pkg_list_2
    ]

    # Get the list of files contained in the packages for each list
    (
        iso_shared_pkg_to_files,
        iso_pkg_to_files_1,
        iso_pkg_to_files_2,
    ) = _get_package_files(
        iso1,
        iso2,
        iso_shared_list,
        iso_pkg_list_1,
        iso_pkg_list_2,
        groups_in_iso1,
        groups_in_iso2,
    )

    # Get the ISO sizes
    iso_1_size = os.path.getsize(args.ISO1)
    iso_2_size = os.path.getsize(args.ISO2)

    # Get the list of files in the top level ISO and their sizes
    file_list_1 = _get_iso_files(iso1)
    file_list_2 = _get_iso_files(iso2)

    unchanged_file_list = []
    for _file_1 in file_list_1:
        for _file_2 in file_list_2:
            if _file_1 == _file_2 and _file_1 not in unchanged_file_list:
                unchanged_file_list.append(_file_1)

    unique_file_list_1 = [
        _file for _file in file_list_1 if _file not in unchanged_file_list
    ]
    unique_file_list_2 = [
        _file for _file in file_list_2 if _file not in unchanged_file_list
    ]

    # Now construct the JSON to dump
    _dump_json(
        iso_1_size,
        iso_2_size,
        iso_pkg_to_files_1,
        iso_pkg_to_files_2,
        iso_shared_pkg_to_files,
        unique_file_list_1,
        unique_file_list_2,
        unchanged_file_list,
        args.OUTPUT_DIR,
    )


def _parse_cli_args(argv: List[str]) -> argparse.Namespace:
    """
    Parses arguments from the CLI

    """

    parser = argparse.ArgumentParser(description="Generate diff of two ISOs")

    parser.add_argument(
        "--iso1",
        dest="ISO1",
        required=True,
        help="Path to ISO to take diff from",
    )

    parser.add_argument(
        "--iso2",
        dest="ISO2",
        required=True,
        help="Path to ISO to take diff to",
    )

    parser.add_argument(
        "--clean",
        dest="OUT_CLEAN",
        default=False,
        help="Delete output dir before proceeding",
        action="store_true",
    )

    parser.add_argument(
        "--out-directory",
        dest="OUTPUT_DIR",
        default=DFLT_OUTPUT_DIR,
        help="Output Directory",
    )

    parser.add_argument(
        "--log-dir", default=".", help="Directory to put the log file."
    )

    parser.add_argument(
        "--no-logs", action="store_true", help="Do not store the logs anywhere"
    )

    args = parser.parse_args(argv)

    if len(argv) < 2:
        parser.print_help()
        sys.exit(0)

    return args


def run(argv: List[str]) -> None:
    """
    The main module, responsible for co-ordinating the overall flow for the
    script

    :returns:
        System exit code indicating result of the script (0 for success)

    """

    # Ensure umask is consistent for this process
    os.umask(0o22)

    # Parse cli.
    args = _parse_cli_args(argv)

    _log = gisoutils.init_logging(args.log_dir, _LOGFILE, disable=args.no_logs)
    _log.info("Invoked as '%s'", " ".join(sys.argv))

    try:
        gisoutils.add_wrappers_to_path()
        run_iso_diff(args)
    except Exception as error:
        _log.error(
            "Failed to run isodiff, see %s for more info: %s",
            _LOGFILE,
            str(error),
        )
        _log.debug(str(error), exc_info=True)
        sys.exit(1)
