#!/usr/bin/env python3
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

"""Utility to build golden iso."""

import sys

try:
    assert sys.version_info >= (3, 6)
except AssertionError:
    print("This tool requires python version 3.6 or higher")
    sys.exit(-1)
import argparse
import logging
import os
import pathlib
import re
from typing import Any, Dict, Set, Tuple

from utils import bes, gisoglobals, gisoutils

OPTIMIZE_CAPABLE = (
    pathlib.Path(__file__).resolve().parents[2] / "exr"
).is_dir()

cwd = os.getcwd()
__version__ = "1.0"
MODULE_NAME = os.path.basename(__file__).split(".")[0]
DFLT_OUTPUT_DIR = os.path.join(cwd, "output_{}".format(MODULE_NAME))
logger = logging.getLogger(MODULE_NAME)


class InvalidArgsError(Exception):
    """General error for invalid CLI args."""


class InvalidPkgListPkgError(Exception):
    """Error if the package list contains invalid packages."""

    def __init__(
        self,
        pkgs: Set[str],
    ):
        """
        Initialize the class.

        :param pkgs:
            The packages that are invalid.

        """
        assert pkgs
        lines = []
        lines.append("The following packages are invalid:")
        for pkg in sorted(pkgs):
            lines.append(f"  {pkg}")
        super().__init__("\n".join(lines))


def parsecli() -> Tuple[argparse.Namespace, argparse.ArgumentParser]:
    """Parse CLI options."""
    parser = argparse.ArgumentParser(
        description="Utility to build Golden ISO for IOS-XR.",
    )

    parser.add_argument(
        "--iso",
        dest="iso",
        type=str,
        help="Path to an input LNT ISO, EXR mini/full ISO, or a GISO.",
    )

    parser.add_argument(
        "--repo",
        dest="repo",
        nargs="+",
        default=[],
        help="List of paths to RPM repositories. For LNT, user can specify "
        ".rpm, .tgz, .tar filenames, or directories. RPMs are only used if "
        "already included in the ISO, or specified by the user via the "
        "--pkglist option.",
    )

    parser.add_argument(
        "--bridging-fixes",
        dest="bridge_fixes",
        required=False,
        nargs="+",
        default=[],
        help="Bridging RPMs to package. "
        "For EXR, takes from-release or RPM names; for LNT, the user can "
        "specify the same file types as for the --repo option.",
    )

    parser.add_argument(
        "--xrconfig", dest="xrconfig", type=str, help="Path to XR config file"
    )

    parser.add_argument(
        "--ztp-ini", dest="ztp_ini", type=str, help="Path to user ztp ini file"
    )

    parser.add_argument(
        "--label",
        "-l",
        dest="label",
        type=str,
        default="iso",
        help="Golden ISO Label",
    )

    parser.add_argument(
        "--no-label",
        action="store_true",
        help="Indicates that no label should be added to the GISO, and any "
        "existing label should be removed",
    )

    parser.add_argument(
        "--out-directory",
        dest="out_directory",
        type=str,
        default=os.path.join(os.path.abspath(os.getcwd()), "output_gisobuild"),
        help="Directory to put all artifacts of the GISO build",
    )

    parser.add_argument(
        "--create-checksum",
        dest="create_checksum",
        default=False,
        help="Write a file with the checksum and size of the output file(s)",
        action="store_true",
    )

    parser.add_argument(
        "--yamlfile",
        dest="cli_yaml",
        help="Cli arguments via yaml. See the files in ./sample_yaml/ for "
        "examples",
    )

    parser.add_argument(
        "--clean",
        dest="clean",
        default=False,
        help="Delete output dir before proceeding",
        action="store_true",
    )

    parser.add_argument(
        "--exriso",
        dest="exriso",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--pkglist",
        dest="pkglist",
        required=False,
        nargs="+",
        default=[],
        help=(
            "Packages to be added to the output GISO. "
            "For eXR: optional RPM or SMU to package. "
            "For LNT: either full package filenames or package names for user "
            "installable packages can be specified. "
            "Full package filenames can be specified to choose a particular "
            "version of a package, the rest of the block that the package is "
            "in will be included as well. "
            "Package names can be specified to include optional packages in "
            "the output GISO."
        ),
    )

    parser.add_argument(
        "--key-request",
        dest="key_request",
        required=False,
        help="Key request to package to be used when validating customer and "
        "partner RPMs.",
    )

    parser.add_argument(
        "--docker",
        "--use-container",
        dest="docker",
        action="store_true",
        default=False,
        help="Build GISO in container environment."
        "Pulls and run pre-built container image to build GISO. ",
    )

    #  Output build environment security logs to console
    parser.add_argument(
        "--bes-logging",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )

    # EXR GISO build options.
    exrgroup = parser.add_argument_group("EXR only build options")

    exrgroup.add_argument(
        "--script",
        dest="script",
        type=str,
        help="Path to user executable script, executed as part of boot, post "
        "activate.",
    )

    exrgroup.add_argument(
        "--in_docker",
        dest="in_docker",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )

    exrgroup.add_argument(
        "--x86-only",
        dest="x86_only",
        action="store_true",
        default=False,
        help="Only use x86_64 RPMs, even if other architectures are applicable.",
    )

    exrgroup.add_argument(
        "--migration",
        dest="migration",
        action="store_true",
        default=False,
        help="Build migration tar (only valid for ASR9k)",
    )

    if OPTIMIZE_CAPABLE:
        exrgroup.add_argument(
            "--optimize",
            dest="optimize",
            action="store_true",
            default=False,
            help="Optimize GISO by recreating and resigning initrd",
        )

        exrgroup.add_argument(
            "--full-iso",
            dest="fullISO",
            action="store_true",
            default=False,
            help="Build full ISO (only valid for xrv9k)",
        )

    # LNT GISO build options.
    lntgroup = parser.add_argument_group("LNT only build options")

    lntgroup.add_argument(
        "--remove-packages",
        dest="remove_packages",
        nargs="+",
        default=[],
        help=(
            "Remove RPMs, specified in a space separated list. These are "
            "matched against user installable package names, and must be "
            "the whole package name, e.g: xr-bgp"
        ),
    )
    lntgroup.add_argument(
        "--skip-usb-image",
        action="store_true",
        help="Do not build the USB image",
    )
    lntgroup.add_argument(
        "--skip-dep-check",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    lntgroup.add_argument(
        "--copy-dir",
        dest="copy_directory",
        type=str,
        help="Copy built artifacts to specified directory if provided. The "
        "specified directory must already exist, be writable by the "
        "builder and must not contain a previously built artifact with "
        "the same name.",
    )
    lntgroup.add_argument(
        "--clear-bridging-fixes",
        action="store_true",
        help="Remove all bridging bugfixes from the input ISO",
    )
    lntgroup.add_argument(
        "--verbose-dep-check",
        action="store_true",
        help="Verbose output for the dependency check.",
    )
    # Hidden argument to allow GISO build metadata to be given as a json file
    # instead of being generated during the GISO build.
    lntgroup.add_argument(
        "--buildinfo",
        dest="buildinfo",
        type=str,
        help=argparse.SUPPRESS,
    )
    lntgroup.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        default=False,
        help="Output debug logs to console",
    )
    lntgroup.add_argument(
        "--isoinfo",
        dest="isoinfo",
        help="User specified isoinfo executable to use instead of the "
        "default version",
    )
    # User specified image.py script to be used for packing/unpacking instead of
    # the version extracted from the ISO. It will not be inserted into the GISO.
    # Intended for debugging purposes only.
    lntgroup.add_argument(
        "--image-script", dest="image_script", help=argparse.SUPPRESS
    )
    lntgroup.add_argument(
        "--only-support-pids",
        dest="only_support_pids",
        nargs="+",
        default=None,
        help=(
            "Support only these hardware PIDs in the output ISO (e.g. "
            "'8800-RP' '8800-LC-36FH' '8800-LC-48H'); other PIDs from the "
            "input ISO will be removed. This option is generally used to "
            "reduce the size of the output ISO. Do not use this option before "
            "discussing with Cisco support."
        ),
    )
    lntgroup.add_argument(
        "--clear-key-request",
        action="store_true",
        help="Remove all key requests from the input ISO",
    )
    lntgroup.add_argument(
        "--ownership-vouchers",
        dest="ownership_vouchers",
        required=False,
        help="Ownership vouchers to package to be used when validating owner "
        "and partner RPMs.",
    )
    lntgroup.add_argument(
        "--clear-ownership-vouchers",
        action="store_true",
        help="Remove all ownership vouchers from the input ISO, if there are "
        "any present",
    )
    lntgroup.add_argument(
        "--ownership-certificate",
        dest="ownership_certificate",
        required=False,
        help="Ownership certificate to package to be used when validating "
        "owner and partner RPMs.",
    )
    lntgroup.add_argument(
        "--clear-ownership-certificate",
        action="store_true",
        help="Remove the ownership certificate from the input ISO, if there is "
        "one present",
    )
    lntgroup.add_argument(
        "--no-buildinfo",
        action="store_true",
        help=(
            "Do not update the build metadata in mdata.json with "
            "the GISO build information"
        ),
    )

    version_string = "%%(prog)s (version %s)" % (__version__)
    parser.add_argument(
        "--version",
        action="version",
        help="Print version of this script and exit",
        version=version_string,
    )

    pargs = parser.parse_args()

    return pargs, parser


def validate_and_setup_args(args: argparse.Namespace) -> argparse.Namespace:
    """Validate input arguments. Also return if exr or lnt iso is provided."""

    if not args.iso:
        raise AssertionError("Please provide an input ISO")

    # Check input ISO.
    if not os.path.isfile(args.iso):
        raise AssertionError("Bundle ISO {} does not exist.".format(args.iso))
    filetype = gisoutils.get_file_type(args.iso)
    args.iso = os.path.abspath(args.iso)
    if filetype not in {gisoglobals.FILE_TYPE_ISO, gisoglobals.FILE_TYPE_UDF}:
        raise AssertionError(
            "Bundle ISO {} is not an ISO or UDF file.".format(args.iso)
        )

    # Check if iso provided has exr platform name
    args.exriso = gisoutils.is_platform_exr(args.iso)

    # Check if input iso is a GISO, we are trying to extend.
    if re.match(".*golden.*", str(args.iso)):
        args.gisoExtend = True
    else:
        args.gisoExtend = False

    # Check if optimized or a full iso build is being triggered.
    if hasattr(args, "optimize") or hasattr(args, "fullISO"):
        if args.optimize or args.fullISO:
            display_string = "Optimized" if args.optimize else "Full ISO"
            if not OPTIMIZE_CAPABLE:
                raise AssertionError(
                    f"{display_string} build workflow is not supported."
                )

    # Check repo given in input.
    if args.repo:
        for repopath in args.repo:
            if repopath and not os.path.exists(repopath):
                raise AssertionError(
                    "RPM Repository path {} does not exist.".format(repopath)
                )

    args.repo = [os.path.abspath(repopath) for repopath in args.repo]

    # If --pkglist is specified, --repo must be provided
    if args.pkglist and not args.repo:
        raise InvalidArgsError(
            "If --pkglist is specified, --repo must also be provided"
        )

    # Packages in the pkglist don't need an extension, but if they have one, it
    # must be ".rpm"
    bad_pkglist_pkgs = set()
    for pkg in args.pkglist:
        if "." in pkg and not pkg.endswith(".rpm"):
            bad_pkglist_pkgs.add(pkg)
    if bad_pkglist_pkgs:
        raise InvalidPkgListPkgError(bad_pkglist_pkgs)

    # Check xr config file if provided.
    if args.xrconfig:
        if not os.path.isfile(args.xrconfig):
            raise AssertionError(
                "XR Config file {} does not exist.".format(args.xrconfig)
            )
        filetype = gisoutils.get_file_type(args.xrconfig)
        args.xrconfig = os.path.abspath(args.xrconfig)
        if filetype != gisoglobals.FILE_TYPE_TEXT:
            raise AssertionError(
                "XR Config file {} "
                "has an invalid file type.".format(args.xrconfig)
            )

    # Check ztp.ini file if provided.
    if args.ztp_ini:
        if not os.path.isfile(args.ztp_ini):
            raise AssertionError(
                "ZTP ini file {} does not exist.".format(args.ztp_ini)
            )
        filetype = gisoutils.get_file_type(args.ztp_ini)
        args.ztp_ini = os.path.abspath(args.ztp_ini)
        if filetype != gisoglobals.FILE_TYPE_TEXT:
            raise AssertionError(
                "ZTP ini file {} "
                "has an invalid file type.".format(args.ztp_ini)
            )

    # Check init script if provided.
    if args.script:
        if not os.path.isfile(args.script):
            raise AssertionError(
                "Init script {} does not exist.".format(args.script)
            )
        if not os.access(args.script, os.X_OK):
            raise AssertionError(
                "Init script {} is not executable.".format(args.script)
            )
        filetype = gisoutils.get_file_type(args.script)
        args.script = os.path.abspath(args.script)
        if filetype != gisoglobals.FILE_TYPE_TEXT:
            raise AssertionError(
                "Init script {} "
                "has an invalid file type.".format(args.script)
            )

    # Check input label if provided.
    if args.no_label:
        logger.info("Info: User has requested a Golden ISO with no label")
        args.label = None
    elif not args.label:
        logger.info(
            "Info: Golden ISO label is not specified so defaulting to 0"
        )
        args.label = "0"
    else:
        new_label = args.label.replace("_", "")
        if not new_label.isalnum():
            logger.error(
                "Error: label %s contains characters other than "
                "alphanumeric and underscore",
                str(args.label),
            )
            raise AssertionError(
                "Error: label {} contains characters other than "
                "alphanumeric and underscore".format(str(args.label))
            )

    # Check that remove_packages doesn't have an RPM file extension.
    # In theory, this should check that the specified item is a proper block;
    # but for now just check the the user hasn't specified an RPM (they might
    # still specify with a version/architecture/etc, but we'll flag up
    # warnings later on for this scenario)
    if args.remove_packages:
        rpm_suffix = [r for r in args.remove_packages if r.endswith(".rpm")]
        if rpm_suffix:
            raise AssertionError(
                "Error: --remove-packages expects package names, not RPM file "
                "names. The following end with a .rpm suffix suggesting that they "
                "are RPM file names: {}".format(" ".join(rpm_suffix))
            )

    # Check key packages if provided.
    if args.key_request:
        if not os.path.exists(args.key_request):
            raise AssertionError(
                f"Error: The given key request does not exist: {args.key_request}"
            )

    if args.ownership_vouchers:
        if not os.path.exists(args.ownership_vouchers):
            raise AssertionError(
                "Error: The given ownership vouchers file ("
                + args.ownership_vouchers
                + ") does not exist."
            )
        elif not (
            args.ownership_vouchers.endswith(
                (".vcj", ".tar", ".tar.gz", ".tgz")
            )
        ):
            raise AssertionError(
                "Error: The given ownership vouchers file ("
                + args.ownership_vouchers
                + ") is not a valid file format. It should be either a .vcj or "
                "a tarball (.tar, .tar.gz, .tgz)."
            )

    if args.ownership_certificate:
        if not os.path.exists(args.ownership_certificate):
            raise AssertionError(
                "Error: The given ownership certificate file ("
                + args.ownership_certificate
                + ") does not exist."
            )
        elif not args.ownership_certificate.endswith(".cms"):
            raise AssertionError(
                "Error: The given ownership certificate file ("
                + args.ownership_certificate
                + ") is not a valid "
                "file format. It should be a .cms file."
            )
    return args


def main() -> None:
    """Parse CLI options"""
    cli_args, parser = parsecli()
    transform_dict: Dict[str, Any] = {}

    # If yaml file is provided at input, validate and populate cli_args
    if cli_args.cli_yaml:
        yaml_args = gisoutils.load_yaml_giso_arguments(cli_args.cli_yaml)
        yaml_args.update(
            {
                x: y
                for x, y in cli_args.__dict__.items()
                if cli_args.__dict__[x] != parser.get_default(x)
            }
        )
        cli_args.__dict__.update(yaml_args)
    else:
        yaml_args = {}
    if not cli_args.out_directory:
        cli_args.out_directory = DFLT_OUTPUT_DIR

    # Setup the tool arguments.
    cli_args = validate_and_setup_args(cli_args)

    if cli_args.bes_logging:
        bes.enable_logging()
    bes.log_os_release()
    bes.log_cmd_call(cli_args, yaml_args)
    # The container tools must be logged separately, as the other required
    # tools in requirements.yaml relate to the build environment inside the
    # container.
    if cli_args.docker:
        bes.log_tools(("docker", "podman"), "container tools")

    # Remove any environment variables that have not been explicitly listed as
    # dependencies of gisobuild to prevent any unexpected behavior.
    if not cli_args.exriso:
        gisoutils.sanitize_env_vars(gisoglobals.LNT_ENV_VARS)
        bes.log_env_vars(gisoglobals.LNT_ENV_VARS)
    if cli_args.exriso:
        gisoutils.sanitize_env_vars(gisoglobals.EXR_ENV_VARS)
        bes.log_env_vars(gisoglobals.EXR_ENV_VARS)
    # Set up the build env
    try:
        gisoutils.create_working_dir(
            cli_args.clean,
            cli_args.out_directory,
            MODULE_NAME,
        )
    except OSError as error:
        print(
            "Output directory {} exists. \n"
            "Consider passing --clean "
            "as input or remove directory and rerun.".format(
                cli_args.out_directory
            )
        )
        print(str(error))
        sys.exit(-1)
    except Exception as e:
        print(e)
        sys.exit(-1)

    # Console logging to inherit legacy eXR gisobuild logger attributes.
    if cli_args.docker or cli_args.exriso:
        gisoutils.initialize_console_logging()

    # Transform the parameters as expected by eXR and LNT tools.
    if cli_args.docker:
        from utils.gisocontainer import execute_build

    elif cli_args.exriso:
        from exrmod.isotools_exr import execute_build

        transform_dict = gisoglobals.EXR_CLI_DICT_MAP
    else:
        from lnt.launcher import execute_build  # type: ignore

        transform_dict = gisoglobals.LNT_CLI_DICT_MAP

    try:
        if transform_dict:
            # Filter & transform eXR & LNT specific parameters.
            cli_args.__dict__ = {
                transform_dict[k]: v
                for k, v in cli_args.__dict__.items()
                if transform_dict.get(k) is not None
            }
    except KeyError as e:
        logger.error("Option %s in input not supported", str(e.args))
        sys.exit(-1)
    execute_build(cli_args)


if __name__ == "__main__":
    main()
