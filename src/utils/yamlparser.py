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

"""GISO YAML handling."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TextIO

import validate.validate as validate
import yaml


@dataclass
class Packages:
    """
    Representation of package selection (ISO, repo and packages)
    specified in YAML.
    """

    iso: str
    repo: List[str]
    pkglist: List[str]
    remove_packages: List[str]
    remove_rpms_matching_pattern: List[str]
    bridge_fixes: List[str]
    skip_usb_image: bool
    skip_dep_check: bool
    clear_bridging_fixes: bool
    only_support_pids: Optional[List[str]]
    key_request: Optional[str]
    clear_key_request: bool
    ownership_vouchers: Optional[str] = None
    clear_ownership_vouchers: bool = False
    ownership_certificate: Optional[str] = None
    clear_ownership_certificate: bool = False

    @classmethod
    def from_dict(cls, ydict: Dict[str, Any]) -> "Packages":
        """Create a Packages class from a dictionary."""
        # Check if arguments have been passed in, and update if they are
        # present.
        iso = ""
        repo: List[str] = []
        pkglist: List[str] = []
        remove_packages: List[str] = []
        remove_rpms_matching_pattern: List[str] = []
        bridge_fixes: List[str] = []
        skip_usb_image = False
        skip_dep_check = False
        clear_bridging_fixes = False
        only_support_pids: Optional[List[str]] = None
        key_request: Optional[str] = None
        clear_key_request = False
        ownership_vouchers: Optional[str] = None
        clear_ownership_vouchers = False
        ownership_certificate: Optional[str] = None
        clear_ownership_certificate = False

        if ydict:
            iso = ydict.get("iso", "")
            repo = ydict.get("repo", [])
            pkglist = ydict.get("pkglist", [])

            # The arguments appear as remove-packages in the yaml file but
            # remove_packages in the args namespace
            if ydict.get("remove-packages"):
                remove_packages = ydict.get("remove-packages", [])
            elif ydict.get("remove_packages"):
                remove_packages = ydict.get("remove_packages", [])

            if ydict.get("remove-rpms-matching-pattern"):
                remove_rpms_matching_pattern = ydict.get(
                    "remove-rpms-matching-pattern", []
                )
            elif ydict.get("remove_rpms_matching_pattern"):
                remove_rpms_matching_pattern = ydict.get(
                    "remove_rpms_matching_pattern", []
                )

            if ydict.get("skip-usb-image"):
                skip_usb_image = ydict.get("skip-usb-image", False)
            elif ydict.get("skip_usb_image"):
                skip_usb_image = ydict.get("skip_usb_image", False)

            if ydict.get("skip-dep-check"):
                skip_dep_check = ydict.get("skip-dep-check", False)
            elif ydict.get("skip_dep_check"):
                skip_dep_check = ydict.get("skip_dep_check", False)
            bridge_fixes = []

            if ydict.get("bridge-fixes"):
                bridge_rpms = ydict.get("bridge-fixes", {}).get("rpms")
                if bridge_rpms:
                    bridge_fixes.extend(bridge_rpms)
                bridge_rel = ydict.get("bridge-fixes", {}).get(
                    "upgrade-from-release"
                )
                if bridge_rel:
                    bridge_fixes.extend(bridge_rel)
            elif ydict.get("bridging_fixes"):
                bridge_rpms = ydict.get("bridging_fixes")
                bridge_fixes.extend(bridge_rpms)
            elif ydict.get("bridge_fixes"):
                bridge_rpms = ydict.get("bridge_fixes")
                bridge_fixes.extend(bridge_rpms)

            if ydict.get("clear-bridging-fixes"):
                clear_bridging_fixes = ydict.get("clear-bridging-fixes", False)
            elif ydict.get("clear_bridging_fixes"):
                clear_bridging_fixes = ydict.get("clear_bridging_fixes", False)

            if ydict.get("only-support-pids"):
                only_support_pids = ydict.get("only-support-pids")
            elif ydict.get("only_support_pids"):
                only_support_pids = ydict.get("only_support_pids")

            key_request = ydict.get("key-request", None) or ydict.get(
                "key_request", None
            )

            clear_key_request = ydict.get(
                "clear-key-request", False
            ) or ydict.get("clear_key_request", False)

            ownership_vouchers = ydict.get("ownership_vouchers", None)
            clear_ownership_vouchers = ydict.get(
                "clear_ownership_vouchers", False
            )

            ownership_certificate = ydict.get("ownership_certificate", None)
            clear_ownership_certificate = ydict.get(
                "clear_ownership_certificate", False
            )

        return validate.create(
            cls,
            {
                "iso": iso,
                "repo": repo,
                "pkglist": pkglist,
                "remove_packages": remove_packages,
                "remove_rpms_matching_pattern": remove_rpms_matching_pattern,
                "skip_usb_image": skip_usb_image,
                "skip_dep_check": skip_dep_check,
                "bridge_fixes": bridge_fixes,
                "clear_bridging_fixes": clear_bridging_fixes,
                "only_support_pids": only_support_pids,
                "key_request": key_request,
                "clear_key_request": clear_key_request,
                "ownership_vouchers": ownership_vouchers,
                "clear_ownership_vouchers": clear_ownership_vouchers,
                "ownership_certificate": ownership_certificate,
                "clear_ownership_certificate": clear_ownership_certificate,
            },
        )


@dataclass
class UserContent:
    """
    Representation of post-build script, XR config and buildinfo
    specified in YAML.
    """

    script: str = ""
    xrconfig: str = ""
    buildinfo: str = ""
    ztp_ini: str = ""
    no_buildinfo: bool = False

    @classmethod
    def from_dict(cls, ydict: Dict[str, Any]) -> "UserContent":
        """Create a UserContent class from a dictionary."""
        script = ""
        xrconfig = ""
        buildinfo = ""
        ztp_ini = ""
        no_buildinfo = False
        if ydict:
            script = ydict.get("script") or ""
            xrconfig = ydict.get("xrconfig") or ""
            buildinfo = ydict.get("buildinfo") or ""
            no_buildinfo = ydict.get("no_buildinfo", False)

            # The arguments appear as ztp-ini in the yaml file but
            # ztp_ini in the args namespace
            ztp_ini = ydict.get("ztp_ini", "")
            if not ztp_ini:
                ztp_ini = ydict.get("ztp-ini", "")

        return validate.create(
            cls,
            {
                "script": script,
                "xrconfig": xrconfig,
                "buildinfo": buildinfo,
                "ztp_ini": ztp_ini,
                "no_buildinfo": no_buildinfo,
            },
        )


@dataclass
class Output:
    """
    Representation of output options specified in YAML.
    """

    label: Optional[str] = None
    out_directory: str = ""
    copy_directory: Optional[str] = None
    clean: bool = False
    create_checksum: bool = False
    no_label: bool = False

    @classmethod
    def from_dict(cls, ydict: Dict[str, Any]) -> "Output":
        """Create an Output class from a dictionary."""
        label = None
        out_directory = ""
        copy_directory = None
        clean = False
        create_checksum = False
        no_label = False

        if ydict:
            label = ydict.get("label", None)

            # The arguments appear as out-directory in the yaml file but
            # out_directory in the args namespace
            if ydict.get("out-directory"):
                out_directory = ydict.get("out-directory", "")
            elif ydict.get("out_directory"):
                out_directory = ydict.get("out_directory", "")
            elif ydict.get("out_dir"):
                out_directory = ydict.get("out_dir", "")

            if ydict.get("copy-dir"):
                copy_directory = ydict.get("copy-dir")
            elif ydict.get("copy_dir"):
                copy_directory = ydict.get("copy_dir")
            clean = ydict.get("clean", False)
            if ydict.get("no_label"):
                no_label = ydict.get("no_label", False)

            if ydict.get("create-checksum"):
                create_checksum = ydict.get("create-checksum", False)
            elif ydict.get("create_checksum"):
                create_checksum = ydict.get("create_checksum", False)

        return validate.create(
            cls,
            {
                "label": label,
                "out_directory": out_directory,
                "copy_directory": copy_directory,
                "clean": clean,
                "create_checksum": create_checksum,
                "no_label": no_label,
            },
        )


@dataclass
class Options:
    """
    Representation of boolean build options specified in YAML.
    """

    docker: bool = False
    in_docker: bool = False
    fullISO: bool = False
    migration: bool = False
    optimize: bool = False
    x86_only: bool = False
    bes_logging: bool = False

    isoinfo: Optional[str] = None
    image_script: Optional[str] = None

    @classmethod
    def from_dict(cls, ydict: Dict[str, Any]) -> "Options":
        """Create an Options class from a dictionary."""
        docker: bool = False
        in_docker: bool = False
        fullISO: bool = False
        migration: bool = False
        optimize: bool = False
        x86_only: bool = False
        bes_logging: bool = False

        isoinfo: Optional[str] = None
        image_script: Optional[str] = None

        if ydict:
            docker = ydict.get("docker", False)
            in_docker = ydict.get("in_docker", False)
            migration = ydict.get("migration", False)
            optimize = ydict.get("optimize", False)
            fullISO = ydict.get("full-iso", False)
            x86_only = ydict.get("x86_only", False)
            bes_logging = ydict.get("bes_logging", False)
            isoinfo = ydict.get("isoinfo", None)
            image_script = ydict.get("image_script", None)

        return validate.create(
            cls,
            {
                "docker": docker,
                "in_docker": in_docker,
                "fullISO": fullISO,
                "migration": migration,
                "optimize": optimize,
                "x86_only": x86_only,
                "bes_logging": bes_logging,
                "isoinfo": isoinfo,
                "image_script": image_script,
            },
        )


class CliConfigFromYaml:
    """
    Convert YAML representation to CLI args.
    """

    configdict: Dict[str, Any] = {}

    def __init__(self, fd: TextIO) -> None:
        params = yaml.safe_load(fd)

        # Package selection parameters
        pdict = params.get("packages")
        self.packages = Packages.from_dict(pdict)

        # User content parameters
        udict = params.get("user-content")
        self.usercontent = UserContent.from_dict(udict)

        # Output option parameters
        odict = params.get("output")
        self.output = Output.from_dict(odict)

        # Build option parameters
        odict = params.get("options")
        self.options = Options.from_dict(odict)

        self.configdict.update(self.packages.__dict__)
        self.configdict.update(self.usercontent.__dict__)
        self.configdict.update(self.output.__dict__)
        self.configdict.update(self.options.__dict__)

    def __repr__(self) -> str:
        return repr(
            "{}, {}, {}, {}".format(
                repr(self.packages),
                repr(self.usercontent),
                repr(self.output),
                repr(self.options),
            )
        )


class CliConfigToYaml:
    """
    Convert CLI args to YAML representation.
    """

    configstr = ""

    def __init__(self, cli_args: Dict[str, Any]) -> None:
        # Package selection parameters
        self.packages = Packages.from_dict(cli_args)

        # User content parameters
        self.usercontent = UserContent.from_dict(cli_args)

        # Output option parameters
        self.output = Output.from_dict(cli_args)

        # Build option parameters
        self.options = Options.from_dict(cli_args)

        params = {}
        params["packages"] = self.packages.__dict__
        params["user-content"] = self.usercontent.__dict__
        params["output"] = self.output.__dict__
        params["options"] = self.options.__dict__

        self.configstr = yaml.dump(params)

    def __repr__(self) -> str:
        return repr(
            "{}, {}, {}, {}".format(
                repr(self.packages),
                repr(self.usercontent),
                repr(self.output),
                repr(self.options),
            )
        )


def safe_load(fd: TextIO) -> Dict[str, Any]:
    """Get CLI config from YAML."""
    return CliConfigFromYaml(fd).configdict


def dump(data: Dict[str, Any]) -> str:
    """Get YAML from CLI config."""
    return CliConfigToYaml(data).configstr
