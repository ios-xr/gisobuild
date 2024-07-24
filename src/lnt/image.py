# -----------------------------------------------------------------------------

"""APIs to handle interactions with the image.py script.

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
    # Classes
    "ImageFile",
    "Image",
    # Exceptions
    "InvalidVersionOutputError",
    "QueryContentError",
)

import json
import logging
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from tempfile import TemporaryDirectory
from typing import Any, Dict, Generator, List, Optional, Set, Tuple, cast

from . import builder, gisoutils
from . import lnt_gisoglobals as gisoglobals

_log = logging.getLogger()


_XR_FOUNDATION = "xr-foundation"

# Attributes that indicate a group contains RPMs.
_RPM_GROUP_ATTRS = [
    "install",
    "owner_packages",
    "partner_packages",
    "bridging",
]

###############################################################################
#                               Custom exceptions                             #
###############################################################################


class NoCapabilitiesError(Exception):
    """
    Nothing was output to stdout when calling image.py

    """

    def __init__(self) -> None:
        """Initialise a NoCapabilitiesError"""
        super().__init__("Could not retrieve capabilities from image.py")


class InvalidVersionOutputError(Exception):
    """
    The capabilities JSON did not have a version attribute

    """

    def __init__(self, error: str):
        """Initialise a InvalidVersionOutputError"""
        super().__init__(
            "Could not find the image.py version number: {}".format(error)
        )


class QueryContentError(Exception):
    """
    Failed to get metadata from ISO

    """

    def __init__(self, error: str):
        """Initialise a QueryContentError"""
        super().__init__(
            "Failed to query the content of the ISO: {}".format(error)
        )


class CapabilityNotSupported(Exception):
    """Capability is not supported by ISO."""

    def __init__(self, capability: str):
        """Call parent's initialiser with a suitable error message"""
        super().__init__(f"Image doesn't support capability: {capability}")


class ImageScriptExecutionError(Exception):
    """
    Running image.py raised an exception

    .. attribute:: subprocess_error

        `CalledProcessError` from subprocess.

    """

    def __init__(
        self, subprocess_error: subprocess.CalledProcessError
    ) -> None:
        """Initialise a ImageScriptExecutionError"""
        super().__init__(
            "Failed to run image.py with command {}: {}".format(
                " ".join(subprocess_error.cmd), str(subprocess_error)
            )
        )
        self.subprocess_error = subprocess_error

    def __str__(self) -> str:
        """Format this exception."""
        output = super().__str__()
        if hasattr(self.subprocess_error, "stdout"):
            output += f"\n\nFull output:\n{self.subprocess_error.stdout}"
        if hasattr(self.subprocess_error, "stderr"):
            output += f"\n\nFull error:\n{self.subprocess_error.stderr}"
        return output + "\n"


class GetRepoDataError(Exception):
    """
    Failed to get the repodata for the ISO

    """

    def __init__(self, iso: "Image", group: str, error: str):
        """Initialise a GetRepoDataError"""
        super().__init__(
            "Failed to parse the XML returned for ISO {}, group {}. "
            "Error: {}".format(iso.iso, group, error)
        )


###############################################################################
#                                Classes                                      #
###############################################################################


@dataclass
class ImageFile:
    """
    Metadata for a file inside an image.
    """

    filename: str
    size: int
    is_dir: bool = False


###############################################################################
#                             Utility Functions                               #
###############################################################################


def call_image_py(
    iso_script: str,
    iso: Optional[str] = None,
    operation: Optional[str] = None,
    args: Optional[List[str]] = None,
    *,
    log_dir: Optional[pathlib.Path] = None,
    disable_logging: bool = False,
) -> str:
    """
    Run image.py

    :param iso_script:
        Path to the extracted image.py script

    :param iso:
        Path to the ISO to query

    :param operation:
        The operation to run image.py with

    :param args:
        List of args to run image.py with

    :param log_dir:
        The directory that image.py should put log files in.

    :param disable_logging:
        If True, disables the logging (overruling the log_dir argument)

    :returns:
        Anything printed to stdout during the operation of image.py

    """
    assert operation or args, "call_image_py needs some arguments to be set"

    if args is None:
        args = []

    cmd = [sys.executable, iso_script]

    if disable_logging:
        cmd.append("--disable-logging")

    if operation is not None:
        cmd.append(operation)
        # Can only add log path argument if a subcommand is selected, and
        # not (e.g.) --capabilities.
        if log_dir is not None and not disable_logging:
            cmd.extend(["-L", str(log_dir / "iso_image.log")])
    if iso is not None:
        cmd += ["-i", iso]
    cmd += args
    try:
        output = subprocess.check_output(
            cmd, encoding="utf-8", stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as error:
        raise ImageScriptExecutionError(error) from error

    return output


###############################################################################
#                        Capabilities Image class                             #
###############################################################################
class _Capabilities:
    """
    Storage class for the capabilities of a specific image.py script to allow
    for re-checking whether a specific capability is supported.

    :attribute _image_script:
        The image script the capabilities are associated with.

    :attribute _dict:
        The dictionary of capabilities from the image.py

    :attribue _storage:
        Class attribute containing all previously queried capabilities.

    """

    def __init__(self, image_script: str):
        json_dict = self._capabilities(image_script)
        self._dict = dict(json_dict)
        self._image_script = image_script

    def __new__(cls, image_script: str) -> "_Capabilities":
        """
        Re-uses a cached set of capabilities for a given script, so that it
        doesn't have to be requeried every time.

        """
        if not hasattr(cls, "_storage"):
            cls._storage: Dict[str, _Capabilities] = {}

        # Only use a new instance if there currently isn't an instance for
        # this image_script.
        if image_script not in cls._storage:
            cls._storage[image_script] = super().__new__(
                cls
            )  # Args will be set in the __init__
        return cls._storage[image_script]

    def supports(self, capability: str) -> bool:
        """Indicates whether the capability is specified, and so supported"""
        return capability in self._dict

    def caps(self) -> Dict[str, str]:
        """Returns the capability dictionary directly"""
        return self._dict

    def __getitem__(self, key: str) -> str:
        """Gets the specified capability"""
        return self._dict[key]

    def _capabilities(self, image_script: str) -> Dict[str, str]:
        """Retrieve the capabilities of the specific image_script."""
        try:
            caps = call_image_py(image_script, args=["--capabilities"])
        except ImageScriptExecutionError as exc:
            if (
                "unrecognized arguments: --capabilities"
                in exc.subprocess_error.stdout
            ):
                # The capabilities option isn't present in this version of image.py
                # so mark it as legacy - and then base the capabilities on the
                # sub-commands output in the help string.
                #
                # The output of the help string is of the form:
                # usage: tools/image.py [-h] [-v]
                #      {unpack-iso,pack-iso,create-usb,query-content}
                #
                # Where the second line is the list of sub-commands, but for
                # versions that don't support the --capabilities, the
                # sub-commands are the same as the capabilities.
                _log.info("caps output: %s", exc.subprocess_error.stdout)
                capabilities_dict = {"version": "0"}
                sub_commands_list = re.search(
                    "{(.*)}", exc.subprocess_error.stdout
                )
                if sub_commands_list:
                    capabilities_dict.update(
                        {
                            sub_command: "Able to run sub-command: {}".format(
                                sub_command
                            )
                            for sub_command in sub_commands_list.group(
                                1
                            ).split(",")
                        }
                    )
            else:
                raise
        else:
            try:
                capabilities_dict = json.loads(caps)
            except json.JSONDecodeError:
                _log.error("Failed to decode capabilities JSON: %s", caps)
                raise

        return capabilities_dict


###############################################################################
#                               Image class                                   #
###############################################################################


# pylint: disable=too-many-public-methods
class Image:
    """
    Class which handles interactions with and stores results from image.py

    """

    def __init__(
        self,
        iso: str,
        *,
        tmp_dir: Optional[str] = None,
        prefix: Optional[str] = None,
        log_dir: Optional[str] = None,
        disable_logging: bool = False,
    ) -> None:
        """
        Extract image.py from the ISO, verify its signature, and store it for
        future use

        :param iso:
            The path to the ISO to extract from

        :param tmp_dir:
            Optional directory to use as a temporary output directory.

        :param prefix:
            Optional string to be the prefix for the temporary output
            directory. Ignored if tmp_dir is specified.

        :param log_dir:
            The directory that is used for logging any image.py calls.

        :param disable_logging:
            If True, will disable the logging of the ISO's image.py script
            whenever the script is called.

        """

        # Store the location of the ISO and image.py for future use. The
        # temporary directory will be cleaned up when the Image is freed.
        self.iso = iso
        self.log_dir = None
        if log_dir is not None:
            self.log_dir = pathlib.Path(log_dir)
        if tmp_dir is None:
            self._tmp_dir = TemporaryDirectory(prefix=prefix)
            tmp_dir = self._tmp_dir.name

        (self.image_script, self.dev_signed,) = gisoutils.extract_image_py_sig(
            self.iso, tmp_dir
        )
        self._capabilities = _Capabilities(self.image_script)
        if not self._capabilities.caps():
            raise NoCapabilitiesError

        self._tmp_log_dir = None
        if disable_logging:
            # If the ISO image has the disable_logging capability, then use
            # that. If not, then use a temp directory for the logging
            # directory (if the logging directory is already set to be a temp
            # directory, then just keep using that)
            if self.supports("disable-logging"):
                self.disable_logging = True
                self.log_dir = None
            else:
                self.disable_logging = False
                # Note: parents returns the full path of each parent, starting
                # at the longest ending at the shortest (/); so we need to try
                # to check the penultimate one.
                if not self.log_dir or not str(self.log_dir.parent).startswith(
                    "/tmp/"
                ):
                    self._tmp_log_dir = TemporaryDirectory(prefix=prefix)
                    self.log_dir = pathlib.Path(self._tmp_log_dir.name)
        try:
            self._version = self._capabilities["version"]
        except KeyError as error:
            raise InvalidVersionOutputError(str(error)) from error

        # The capabilities and version are printed to stdout if successful
        _log.debug("Using version number %s", self._version)

    @property
    def is_dev_signed(self) -> bool:
        """
        Boolean indicating whether the image is dev-signed.
        """
        return self.dev_signed

    @property
    def version(self) -> str:
        """
        String indicating the version of the image capabilities.
        """
        return self._version

    @property
    def caps(self) -> Dict[str, str]:
        """
        Dict of the capabilities.
        """
        return self._capabilities.caps()

    def get_capabilities(self) -> Tuple[str, Dict[str, str]]:
        """
        Retrieves the list of capabilities from image.py

        :returns:
            String containing the version number and dictionary containing the
            image.py capabilities

        """

        return self._version, self._capabilities.caps()

    def supports(self, caps: str) -> bool:
        """
        Indicates whether this image supports the specified capability.

        """
        return self._capabilities.supports(caps)

    ###########################################################################
    #                              Utility Functions                          #
    ###########################################################################

    def _call_image_py_if_caps_supported(
        self,
        operation: str,
        iso: Optional[str] = None,
        args: Optional[List[str]] = None,
        *,
        caps: Optional[str] = None,
        log_dir: Optional[pathlib.Path] = None,
    ) -> str:
        """
        Wrapper function that calls the image.py script if the capability is
        supported. It raises an error if the caps is not supported.

        :param iso:
            Path to the ISO to query

        :param operation:
            The operation to run image.py with, if caps it not set - then the
            operation string is used as the capability.

        :args:
            List of args to run image.py with

        :param caps:
            If set, this string is used as the capability.

        :param log_dir:
            The directory that image.py should put log files in.

        :returns:
            Anything printed to stdout during the operation of image.py

        """
        if caps is None:
            caps = operation

        if self.supports(caps):
            return call_image_py(
                self.image_script, iso, operation, args, log_dir=log_dir
            )
        else:
            raise CapabilityNotSupported(caps)

    def _assert_caps_is_not_supported(self, caps: str) -> None:
        """
        Raise an AssertionError if the specified caps *is* supported.

        """
        assert not self.supports(
            caps
        ), f"{caps} should not be supported by the image"

    ###############################################################################
    #                 Functions for calling image.py subcommands                  #
    ###############################################################################
    def unpack_iso(self, iso_dir: str) -> None:
        """
        Unpack the ISO to the specified directory

        :param iso_dir:
            Location of directory to unpack to

        """

        _log.debug("Unpacking ISO into %s", iso_dir)

        self._call_image_py_if_caps_supported(
            operation="unpack-iso",
            iso=self.iso,
            args=["--iso-directory", iso_dir],
            log_dir=self.log_dir,
        )

    def pack_iso(self, iso_dir: str, iso_name: str) -> None:
        """
        Pack the ISO located in the specified directory

        :param iso_dir:
            Location of the directory to pack

        :param iso_name:
            Name to call the resultant ISO

        """

        _log.debug("Packing ISO into %s", iso_dir)

        self._call_image_py_if_caps_supported(
            operation="pack-iso",
            args=["--iso-name", iso_name, "--iso-directory", iso_dir],
            log_dir=self.log_dir,
        )

    @lru_cache(maxsize=8)
    def query_content(self, supported_pids: bool = False) -> Dict[str, Any]:
        """
        Query the ISO to return JSON data containing ISO metadata

        :param supported_pids:
            Include supported PIDs information. This requires image.py to
            parse XML repodata in the ISO.
        """

        _log.debug("Querying ISO")

        try_query_content = False
        if supported_pids:
            try:
                output = self._call_image_py_if_caps_supported(
                    iso=self.iso,
                    operation="query-content",
                    args=["--supported-pids"],
                    caps="query-content-supported-pids",
                    log_dir=self.log_dir,
                )
                try:
                    json_data = json.loads(output)
                except json.decoder.JSONDecodeError as error:
                    raise QueryContentError(str(error)) from error
            except CapabilityNotSupported:
                try_query_content = True
        else:
            try_query_content = True

        fallback_isoinfo = False
        if try_query_content:
            try:
                output = self._call_image_py_if_caps_supported(
                    iso=self.iso,
                    operation="query-content",
                    log_dir=self.log_dir,
                )
                try:
                    json_data = json.loads(output)
                except json.decoder.JSONDecodeError as error:
                    raise QueryContentError(str(error)) from error
            except CapabilityNotSupported:
                fallback_isoinfo = True

        if fallback_isoinfo:
            cmd = [
                gisoutils.get_isoinfo(),
                "-R",
                "-x",
                "/" + str(gisoglobals.LNT_MDATA_PATH),
                "-i",
                self.iso,
            ]
            try:
                output = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                ).stdout.decode("utf-8")
            except subprocess.CalledProcessError as error:
                raise ImageScriptExecutionError(error) from error

            try:
                json_data = {
                    str(gisoglobals.LNT_MDATA_DIR): json.loads(output)
                }
            except json.decoder.JSONDecodeError as error:
                raise QueryContentError(str(error)) from error

        return cast(Dict[str, Any], json_data)

    def get_repodata(self, group: str) -> str:
        """
        Retrieve the repodata XML from the ISO

        :param group:
            Name of the group to get repodata for

        :returns xml:
            The repodata XML returned from image.py

        """

        _log.debug("Retrieving repodata for %s group", group)
        return self._call_image_py_if_caps_supported(
            iso=self.iso,
            operation="get-repodata",
            args=["--group-name", group],
            log_dir=self.log_dir,
        )

    def create_usb(self, input_iso: str, output_file: str) -> None:
        """
        Build the USB image

        :param input_iso:
            ISO to build the USB image from (note - explicitly *not* self.iso,
            as this is the base ISO, not the produced GISO)

        :param output_file:
            The path to the output file to place the USB image

        """

        _log.debug("Building USB image")

        self._call_image_py_if_caps_supported(
            iso=input_iso,
            operation="create-usb",
            args=["--output-file", output_file],
            log_dir=self.log_dir,
        )

    def get_object(self, obj: str) -> str:
        """Retrieve a specific file from the ISO.

        :param obj:
            Name of object to retrieve.

        :return:
            `str` value of the object.

        """
        return self._call_image_py_if_caps_supported(
            iso=self.iso,
            operation="get-object",
            args=[obj],
            log_dir=self.log_dir,
        )

    def list_rpm_groups(self) -> List[str]:
        """List all the groups that may contain RPMs within the ISO."""
        content = self.query_content()
        rpm_groups = set()
        for attr in _RPM_GROUP_ATTRS:
            rpm_groups.update(
                gisoutils.get_groups_with_attr(content["groups"], attr)
            )
        return sorted(list(rpm_groups))

    def extract_groups(self, groups: List[str], output_dir: str) -> None:
        """Extracts the specified groups to the given output directory."""
        self._call_image_py_if_caps_supported(
            iso=self.iso,
            operation="extract-groups",
            args=[",".join(list(groups)), "-o", output_dir],
            log_dir=self.log_dir,
        )

    def list_packages(self, group: str) -> List[str]:
        """List all the packages within the specified group."""
        pkgs = self._call_image_py_if_caps_supported(
            iso=self.iso,
            operation="list-packages",
            args=[group],
            log_dir=self.log_dir,
        )
        return [pkg for pkg in pkgs.split("\n") if pkg != ""]

    def list_squashfs(self) -> List[str]:
        """List all the files in the squashfs."""
        files = self._call_image_py_if_caps_supported(
            iso=self.iso, operation="list-squashfs", log_dir=self.log_dir,
        )
        return [file for file in files.split("\n") if file]

    def show_label(self) -> str:
        """Returns the label of the ISO."""
        _caps = "show-label"
        return self._call_image_py_if_caps_supported(
            iso=self.iso, operation="show-label", log_dir=self.log_dir,
        ).strip()

    def show_buildinfo(self) -> str:
        """Returns the build info of the ISO."""
        return self._call_image_py_if_caps_supported(
            iso=self.iso,
            operation="show-buildinfo",
            log_dir=self.log_dir,
            caps="show-build-info",
        )

    def extract_sw_hash(self) -> str:
        """Returns the sw-hash of the ISO."""
        output = self._call_image_py_if_caps_supported(
            iso=self.iso,
            operation="extract-sw-hash",
            log_dir=self.log_dir,
            caps="extract-sw-hash",
        )

        output = output.strip()
        hash_match = re.search("([a-fA-F0-9]*)$", output)
        if hash_match:
            output = hash_match.group(1)
        return output

    def list_bugfixes(self) -> str:
        """Returns a list of the bugfixes in the ISO."""
        try:
            return self._call_image_py_if_caps_supported(
                iso=self.iso, operation="list-bugfixes", log_dir=self.log_dir,
            )
        except CapabilityNotSupported:
            json_data = self.query_content()
            mdata = json_data["mdata"]
            if (
                gisoglobals.LNT_GISO_CDETS in mdata.keys()
                and len(mdata[gisoglobals.LNT_GISO_CDETS]) > 0
            ):
                _CISCO_TAG = "cisco-"
                _DDTS_TAG = _CISCO_TAG + "CSC"
                retval = [f"Bugfixes in this ISO: {self.iso}"]
                retval += sorted(
                    bug[len(_CISCO_TAG) :]
                    for bug in mdata[gisoglobals.LNT_GISO_CDETS]
                    if bug.startswith(_DDTS_TAG)
                )
            else:
                retval = ["ISO contains no bugfixes"]

            # The direct return from image.py includes a terminating newline char.
            return "\n".join(retval) + "\n"

    def list_pids(self) -> str:
        """Returns a list of PIDs that this ISO supports."""
        return self._call_image_py_if_caps_supported(
            iso=self.iso,
            operation="list-pids",
            log_dir=self.log_dir,
            caps="list-pids",
        )

    def list_key_requests(self) -> List[str]:
        """Returns a list of key requests in the ISO."""
        return self._call_image_py_if_caps_supported(
            iso=self.iso, operation="list-key-requests", log_dir=self.log_dir,
        ).splitlines()

    ###############################################################################
    #                        Data handling of image.py                            #
    ###############################################################################

    def build_usb_image(self, input_iso: str, output_file: str) -> None:
        """
        Wrapper function, to allow for backwards compatibility.

        :param input_iso:
            ISO to build the USB image from (note - explicitly *not* self.iso,
            as this is the base ISO, not the produced GISO)

        :param output_file:
            The path to the output file to place the USB image

        """

        return self.create_usb(input_iso, output_file)

    def list_files(self) -> List[ImageFile]:
        """Returns a list of files within the ISO."""
        # Currently expected that this capability is not supported!
        self._assert_caps_is_not_supported("list-files")

        # If image.py doesn't support list-files, resort to using isoinfo
        # directly.
        ls_cmd = [gisoutils.get_isoinfo(), "-R", "-l", "-i", self.iso]
        try:
            ls_output = subprocess.check_output(ls_cmd, encoding="utf-8")
        except subprocess.CalledProcessError as error:
            raise gisoutils.ISOInfoError(ls_cmd, str(error)) from error

        # Example chunk of "isoinfo -l" output:
        #
        # Directory listing of /tools/certs/
        # drwxr-xr-x   2    0    0    2048 Aug 12 2020 [     32 02]  .
        # drwxr-xr-x   3    0    0    2048 Aug 12 2020 [     31 02]  ..
        # -rwxr-xr-x   1    0    0    2342 Aug 12 2020 [ 533856 00]  CertFile

        files = []
        dir_line_prefix = "Directory listing of "
        curr_dir = None
        seen_dirs = set()
        ls_l_regex = re.compile(
            r"(?P<perms>\S+)\s+(?P<nlink>\d+)\s+(?P<uid>\d+)\s+(?P<gid>\d+)\s+"
            r"(?P<size>\d+)\s+(?P<date>.+)\s+\[\s*(?P<extent_and_flags>.+)\]\s+"
            r"(?P<filename>.+)$"
        )
        for line in ls_output.splitlines():
            if not line.strip():
                curr_dir = None
                continue
            if line.startswith(dir_line_prefix):
                curr_dir = line[len(dir_line_prefix) :]
                continue

            assert curr_dir is not None

            # "isoinfo -l" adds a trailing space to the end of each line
            # Remove explicitly here rather than calling line.strip() as
            # files in the ISO can have names including spaces and we don't
            # want to mangle the actual filename here
            if line[-1] == " ":
                line = line[:-1]

            match = ls_l_regex.match(line)
            assert match is not None, "unexpected line: '{}'".format(line)

            perms = match.group("perms")
            size = int(match.group("size"))
            filename = match.group("filename")
            if filename == "..":
                continue
            path = os.path.normpath(os.path.join(curr_dir, filename))

            # Avoid duplicate directory entries (already seen in their
            # parent directory listing)
            if perms.startswith("d") and path in seen_dirs:
                continue
            seen_dirs.add(path)

            files.append(ImageFile(path, size, perms.startswith("d")))

        return files

    def extract_file(self, file: str, output_dir: str) -> str:
        """
        Extracts the specified file from the ISO into the output directory.

        """
        # Currently expected that this capability is not supported!
        self._assert_caps_is_not_supported("extract-file")
        return gisoutils.extract_file_from_iso(
            self.iso, file, output_dir, error_on_empty=False
        )

    def _get_packages_per_group(
        self,
    ) -> Generator[Tuple[str, List["builder.Package"]], None, None]:
        """Generator returning a tuple of (group name, packages)."""
        for group in self.list_rpm_groups():
            # Get repo-data for each group
            data = self.get_repodata(group)
            if not data:
                yield (group, [])
                continue

            try:
                pkgs = builder.get_packages_from_repodata(data, group)
            except Exception as exc:
                raise GetRepoDataError(self, group, str(exc)) from exc

            yield (group, pkgs)

    def _get_required_or_optional_pkgs(
        self, optional: bool
    ) -> Dict[str, List[str]]:
        """
        Get a dict of all the required or optional packages in the ISO, grouped
        by the group they are in.

        :param optional:
            If True, get the optional packages, otherwise get the required
            packages.

        """
        requested_pkgs = {}
        all_pkgs: Set[builder.Package] = set()
        packages = {}

        for group, pkgs in self._get_packages_per_group():
            if pkgs:
                packages[group] = pkgs
                all_pkgs |= set(pkgs)
        if not all_pkgs:
            _log.info("No packages in the repodata")
            return {}

        foundation_pkg = builder.get_xr_foundation_package(all_pkgs)

        for group, pkgs in packages.items():
            if optional:
                group_pkgs = builder.get_xr_optional_packages(
                    foundation_pkg, pkgs
                )
            else:
                group_pkgs = builder.get_xr_required_packages(
                    foundation_pkg, pkgs
                )
            _log.info(
                "%s packages for group %s: %s",
                "Optional" if optional else "Required",
                group,
                group_pkgs,
            )
            if group_pkgs:
                requested_pkgs[group] = [
                    pkg.name for pkg in sorted(group_pkgs, key=str)
                ]

        return requested_pkgs

    def get_required_pkgs(self) -> Dict[str, List[str]]:
        """
        Get a dict of all the required packages (those packages that are
        required for the xr-foundation rpm) in the ISO, grouped by the group
        they are in.

        """
        return self._get_required_or_optional_pkgs(optional=False)

    def get_optional_pkgs(self) -> Dict[str, List[str]]:
        """
        Get a dict of all the optional packages (those packages that are not
        required for the xr-foundation rpm) in the ISO, grouped by the group
        they are in.

        """
        return self._get_required_or_optional_pkgs(optional=True)
