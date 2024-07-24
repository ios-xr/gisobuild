# -----------------------------------------------------------------------------

""" Tool to extract ISO information.

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

__all__ = ("run",)


import argparse
import json
import logging
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional, Union, cast

from .. import gisoutils, image
from .. import lnt_gisoglobals as isoglobals

_LOGFILE = "isols.log"
_log = logging.getLogger("isols")


###############################################################################
#                                 Exceptions                                  #
###############################################################################


class NoOptionChosenError(Exception):
    """No option was selected by the user"""

    def __init__(self, cmd: List[str], error: str):
        """Initialise a NoOptionChosenError"""
        super().__init__(
            "No option was selected for isols.py choose one of: {}. Error: {}".format(
                cmd, error
            )
        )


class InvalidGroupError(Exception):
    """Isols was queried with an invalid group"""

    def __init__(self) -> None:
        """Isols was queried with an invalid group"""
        super().__init__("Invalid group specified")


###############################################################################
#                              Helper functions                               #
###############################################################################


def _print_json_data(json_data: Union[List[Any], Dict[Any, Any]]) -> None:
    """
    Print the mdata using JSON.

    """
    print(json.dumps(json_data, indent=4, sort_keys=True))


def _print_build_info(iso_mdata: Dict[str, str]) -> None:
    """
    Print the metadata

    :param iso_mdata:
        The iso metadata JSON

    """
    if isoglobals.LNT_PLATFORM_FAMILY in iso_mdata:
        print(
            "Platform Family: {}".format(
                iso_mdata[isoglobals.LNT_PLATFORM_FAMILY]
            )
        )
    if isoglobals.LNT_IMAGE_NAME in iso_mdata:
        print(
            "Base Image Name: {}".format(iso_mdata[isoglobals.LNT_IMAGE_NAME])
        )
    if isoglobals.LNT_ISO_TYPE_KEY in iso_mdata:
        print("ISO Type: {}".format(iso_mdata[isoglobals.LNT_ISO_TYPE_KEY]))
    if isoglobals.LNT_ISO_FMT_VER in iso_mdata:
        print(
            "ISO Format Version: {}".format(
                iso_mdata[isoglobals.LNT_ISO_FMT_VER]
            )
        )
    if isoglobals.LNT_XR_VERSION in iso_mdata:
        print("Version: {}".format(iso_mdata[isoglobals.LNT_XR_VERSION]))
    if isoglobals.LNT_GISO_LABEL in iso_mdata:
        print("GISO Label: {}".format(iso_mdata[isoglobals.LNT_GISO_LABEL]))
    if isoglobals.LNT_GISO_BUILDER in iso_mdata:
        print("Built By: {}".format(iso_mdata[isoglobals.LNT_GISO_BUILDER]))
    if isoglobals.LNT_GISO_BUILD_TIME in iso_mdata:
        print("Built On: {}".format(iso_mdata[isoglobals.LNT_GISO_BUILD_TIME]))
    if isoglobals.LNT_GISO_BUILD_HOST in iso_mdata:
        print(
            "Build Host: {}".format(iso_mdata[isoglobals.LNT_GISO_BUILD_HOST])
        )
    if isoglobals.LNT_GISO_BUILD_DIR in iso_mdata:
        print("Workspace: {}".format(iso_mdata[isoglobals.LNT_GISO_BUILD_DIR]))
    if isoglobals.LNT_GISO_BUILD_CMD in iso_mdata:
        print(
            "GISO Build Command: {}".format(
                iso_mdata[isoglobals.LNT_GISO_BUILD_CMD]
            )
        )


###############################################################################
#                                 Operations                                  #
###############################################################################


def display_build_info(iso: image.Image, *, print_json: bool = False) -> None:
    """
    Show the build info

    :param iso:
        The ISO to query

    :param print_json:
        Print the output in JSON format

    """
    _NO_ISO_STRING = "Could not find label in ISO"
    json_data = iso.query_content()

    if isoglobals.LNT_GISO_LABEL not in json_data["mdata"].keys():
        try:
            label = iso.show_label()
        except image.ImageScriptExecutionError as exc:
            # If the exception was just because there was no label in the ISO,
            # then continue; otherwise, raise the exception.
            if _NO_ISO_STRING not in str(exc):
                raise
        else:
            if _NO_ISO_STRING not in label:
                json_data["mdata"][isoglobals.LNT_GISO_LABEL] = label
    # Populate any missing fields from buildinfo
    json_data["mdata"] = gisoutils.parse_buildinfo_mdata(
        iso.show_buildinfo(), json_data["mdata"],
    )
    if print_json:
        _print_json_data(json_data["mdata"])
    else:
        _print_build_info(json_data["mdata"])


def display_fixes(iso: image.Image, *, print_json: bool = False) -> None:
    """
    List the bug IDs for fixes included in the ISO bridging group

    :param iso:
        The ISO to query

    :param print_json:
        Print the output in JSON format

    """
    fixes = iso.list_bugfixes()

    if print_json:
        # The list_bugfixes tags a description line on, so make sure to remove
        # it if it's there.
        fixes_str = fixes.splitlines()
        if fixes_str[0].startswith(
            ("Bugfixes in this ISO:", "No bugfixes in this ISO:")
        ):
            fixes_str = fixes_str[1:]
        _print_json_data(fixes_str)
    else:
        # Because the list_bugfixes() may be passing through some direct output
        # (that already ends with newline characters), don't include a newline
        # character for this print statement.
        print(fixes, end="")


def display_key_requests(
    iso: image.Image, *, print_json: bool = False
) -> None:
    """
    List the key requests contained in the ISO.

    :param iso:
        The ISO to query.

    :param print_json:
        Print the output in JSON format.

    """
    key_requests = iso.list_key_requests()

    if print_json:
        _print_json_data(key_requests)
    else:
        if key_requests:
            print("\n".join(key_requests))


def list_packages(
    iso: image.Image,
    *,
    rpms: bool = False,
    group_tags: Optional[List[str]] = None,
    groups: bool = False,
    print_json: bool = False,
) -> None:
    """
    Print the list of packages contained in the ISO

    :param iso:
        The ISO to query

    :param rpms:
        Whether to query the RPMs of the main install group.

    :param group_tags:
        Specific groups of packages to query.

    :param groups:
        Whether to query the packages of all groups.

    :param print_json:
        Print the output in JSON format

    """

    def group_has_attr(group_info: Dict[str, Any], attr_name: str) -> bool:
        return any(
            cast(str, attr["name"]) == attr_name
            for attr in group_info["attrs"]
        )

    assert (
        rpms ^ groups
    ), "Only one of rpms or groups can be specified for listing packages"

    # Determine set of groups to list
    if group_tags is None:
        group_tags = ["install", "owner_packages", "partner_packages"]
    if rpms:
        # List all packages forming part of the main install
        group_info = iso.query_content()["groups"]
        groups_to_list = [
            group["name"]
            for group in group_info
            if any(group_has_attr(group, attr) for attr in group_tags)
        ]
    elif groups:
        groups_to_list = iso.list_rpm_groups()
    else:
        # This function is only invoked if one of the above args is specified
        assert False

    group_packages = {
        group: iso.list_packages(group) for group in groups_to_list
    }

    if rpms:
        all_packages: List[str] = sum(group_packages.values(), [])
        if print_json:
            _print_json_data(sorted(all_packages))
        else:
            if all_packages:
                print("\n".join(sorted(all_packages)))
    else:
        if print_json:
            _print_json_data(group_packages)
        else:
            for group, pkgs in group_packages.items():
                if pkgs:
                    print("Packages in group {}:".format(group))
                    print("\n".join(pkgs))


def dump_mdata(iso: image.Image) -> None:
    """
    Query the content of the specified ISO and return information on all groups
    and RPMs in the ISO in a JSON format

    :param iso:
        The ISO to query

    """
    json_data = iso.query_content(supported_pids=True)

    mdata = json_data["mdata"]
    rpm_group_names = iso.list_rpm_groups()
    rpm_groups = [
        g for g in json_data.get("groups", []) if g["name"] in rpm_group_names
    ]
    # Go through all the groups and collect the rpms
    mdata["rpms"] = {}
    for group in rpm_groups:
        pkg_list: List[str] = []
        group_name = group["name"]
        pkgs = group["pkgs"]
        for pkg in pkgs:
            if pkg.startswith("group.{}/packages/".format(group_name)):
                # Remove the first bit so we are just left with the package
                # name
                pkg_list.append(
                    pkg[len("group.{}.packages/".format(group_name)) :]
                )
        mdata["rpms"][group_name] = pkg_list
    if iso.supports("query-content-supported-pids"):
        mdata["supported-pids"] = json_data.get("supported_pids", {})

    # Add buildinfo
    try:
        buildinfo = iso.show_buildinfo()
    except Exception as exc:
        _log.error("Unable to add buildinfo: %s", exc)
    else:
        mdata = gisoutils.parse_buildinfo_mdata(buildinfo, mdata)

    # Add label
    if isoglobals.LNT_GISO_LABEL not in mdata:
        try:
            label = iso.show_label()
        except Exception as exc:
            _log.error("Unable to query label: %s", exc)
        else:
            if "Could not find label in ISO" not in label:
                mdata[isoglobals.LNT_GISO_LABEL] = label

    # Add sw-hash
    try:
        sw_hash = iso.extract_sw_hash()
    except Exception as exc:
        _log.error("Unable to add sw-hash: %s", exc)
    else:
        mdata["sw-hash"] = sw_hash

    # Update the metadata returned from image.py with the list of all packages
    try:
        data = iso.get_optional_pkgs()
    except Exception as exc:
        _log.error("Unable to add optional packages: %s", exc)
    else:
        mdata["optional-packages"] = dict(
            (group, pkgs) for (group, pkgs) in data.items()
        )

    # Update the metadata with the key requests
    try:
        key_requests = iso.list_key_requests()
    except image.CapabilityNotSupported as exc:
        _log.debug(str(exc))
    except Exception as exc:
        _log.error("Unable to add key requests: %s", exc)
    else:
        mdata["key-requests"] = key_requests

    json.dump(mdata, sys.stdout, indent=4, sort_keys=True)


def list_optional_packages(
    iso: image.Image, *, print_json: bool = False
) -> None:
    """
    Print a list of all the non-core packages

    :param iso:
        The ISO to query

    """
    data = iso.get_optional_pkgs()
    if print_json:
        _print_json_data(data)
    else:
        for group, optional_packages in data.items():
            if optional_packages:
                print("Group: {}".format(group))
                for optional_package in optional_packages:
                    print("  " + optional_package)


def _run_isols_cmds(args: argparse.Namespace) -> None:
    """
    Run the ISO query

    :param args:
        The parsed arguments that will be used for the script

    :param tmp_dir:
        Temporary directory to store intermediate files

    """

    # Extract the image.py script from the ISO which is then used to query the
    # iso
    iso = image.Image(
        args.ISO,
        prefix="isols",
        log_dir=args.log_dir,
        disable_logging=args.no_logs,
    )
    if args.BUILD_INFO:
        display_build_info(iso, print_json=args.json)
    elif args.FIXES:
        display_fixes(iso, print_json=args.json)
    elif args.RPMS:
        list_packages(iso, rpms=True, print_json=args.json)
    elif args.XRPACKAGES:
        list_packages(
            iso, rpms=True, group_tags=["install"], print_json=args.json
        )
    elif args.OWNERPACKAGES:
        list_packages(
            iso, rpms=True, group_tags=["owner_packages"], print_json=args.json
        )
    elif args.PARTNERPACKAGES:
        list_packages(
            iso,
            rpms=True,
            group_tags=["partner_packages"],
            print_json=args.json,
        )
    elif args.KEYREQUESTS:
        display_key_requests(iso, print_json=args.json)
    elif args.GROUPS:
        list_packages(iso, groups=True, print_json=args.json)
    elif args.DUMP_MDATA:
        dump_mdata(iso)
    elif args.OPTIONAL_PACKAGES:
        list_optional_packages(iso, print_json=args.json)
    else:
        # This should have already been caught
        assert False


def _validate_args(args: argparse.Namespace) -> None:
    """
    Do some preliminary checks before listing the ISO contents

    :param args:
        The parsed arguments that will be used for the script

    """

    if not args.ISO:
        raise AssertionError("Please provide an ISO with --iso option")

    if not os.path.isfile(args.ISO):
        raise AssertionError(
            "Input ISO does not exist or not a file: {}".format(args.ISO)
        )


###############################################################################
#                          Main and argument handling                         #
###############################################################################


def _parse_args(argv: List[str]) -> argparse.Namespace:
    """
    Parses arguments from the CLI

    """
    parser = argparse.ArgumentParser(
        description="Helper utility to query information about an ISO"
    )

    parser.add_argument(
        "--log-dir", default=".", help="Directory to put the log file."
    )

    parser.add_argument(
        "--no-logs", action="store_true", help="Do not store the logs anywhere"
    )

    parser.add_argument(
        "--json", action="store_true", help="Output data in JSON format"
    )

    # Mandatory iso argument
    iso_group = parser.add_argument_group("required options")
    iso_group.add_argument(
        "-i",
        "--iso",
        dest="ISO",
        default=None,
        required=True,
        help="Path to ISO to query",
    )

    # Available options for isols - one must be chosen
    group = parser.add_argument_group("isols options")
    isols_group = group.add_mutually_exclusive_group(required=True)
    isols_group.add_argument(
        "--build-info",
        dest="BUILD_INFO",
        default=False,
        help="Display ISO build information",
        action="store_true",
    )
    isols_group.add_argument(
        "--dump-mdata",
        dest="DUMP_MDATA",
        default=False,
        help="Display ISO metadata information in JSON format",
        action="store_true",
    )
    isols_group.add_argument(
        "--rpms",
        dest="RPMS",
        default=False,
        help="List all non-bridging RPMs in the ISO",
        action="store_true",
    )
    isols_group.add_argument(
        "--owner-packages",
        dest="OWNERPACKAGES",
        default=False,
        help="List all owner package RPMs in the ISO",
        action="store_true",
    )
    isols_group.add_argument(
        "--partner-packages",
        dest="PARTNERPACKAGES",
        default=False,
        help="List all partner package RPMs in the ISO",
        action="store_true",
    )
    isols_group.add_argument(
        "--xr-packages",
        dest="XRPACKAGES",
        default=False,
        help="List all Cisco IOS XR RPMs in the ISO",
        action="store_true",
    )
    isols_group.add_argument(
        "--key-requests",
        dest="KEYREQUESTS",
        default=False,
        help="List all key requests in the ISO",
        action="store_true",
    )
    isols_group.add_argument(
        "--groups",
        dest="GROUPS",
        default=False,
        help="List all packages on a per-group basis.",
        action="store_true",
    )
    isols_group.add_argument(
        "--optional-packages",
        dest="OPTIONAL_PACKAGES",
        default=False,
        help="List optional packages in the ISO",
        action="store_true",
    )
    isols_group.add_argument(
        "--fixes",
        dest="FIXES",
        default=False,
        help="List bug fixes included in the ISO",
        action="store_true",
    )

    return parser.parse_args(argv)


def run(argv: List[str]) -> None:
    """
    The main module, responsible for co-ordinating the overall flow for the
    script

    :returns:
        System exit code indicating result of the script (0 for success)

    """
    args = _parse_args(argv)

    if args.no_logs:
        temp_dir = tempfile.TemporaryDirectory()
        args.log_dir = temp_dir.name

    _log = gisoutils.init_logging(args.log_dir, _LOGFILE, disable=args.no_logs)

    try:
        gisoutils.add_wrappers_to_path()
        _validate_args(args)
        _run_isols_cmds(args)
    except Exception as error:
        _log.error(
            "Failed to run isols, see %s for more info: %s",
            _LOGFILE,
            str(error),
        )
        _log.debug(str(error), exc_info=True)
        sys.exit(1)
