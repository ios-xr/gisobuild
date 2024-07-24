#!/usr/bin/env python3
# -----------------------------------------------------------------------------

""" Utility to build golden iso.

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

from utils import gisoutils
from utils.gisoglobals import *

try:
    sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
    import exr

    OPTIMIZE_CAPABLE = True
except ImportError:
    OPTIMIZE_CAPABLE = False

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
        self, pkgs: Set[str],
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
        help="Path to RPM repository. For LNT, user can "
        "specify .rpm, .tgz, .tar filenames, or directories. "
        "RPMs are only used if already included in the ISO, "
        "or specified by the user via the --pkglist option.",
    )

    parser.add_argument(
        "--bridging-fixes",
        dest="bridge_fixes",
        required=False,
        nargs="+",
        default=[],
        help="Bridging rpms to package. "
        "For EXR, takes from-release or rpm names; for LNT, the user can "
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
        help="Indicates that no label at all should be added to the GISO",
    )

    parser.add_argument(
        "--out-directory",
        dest="out_directory",
        type=str,
        default=os.path.join(os.path.abspath(os.getcwd()), "output_gisobuild"),
        help="Output Directory",
    )

    parser.add_argument(
        "--create-checksum",
        dest="create_checksum",
        default=False,
        help="Write a file with the checksum and size of the output file(s)",
        action="store_true",
    )

    parser.add_argument(
        "--yamlfile", dest="cli_yaml", help="Cli arguments via yaml"
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
            "For eXR: optional rpm or smu to package. "
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
        "--key-requests",
        dest="key_requests",
        required=False,
        nargs="+",
        default=[],
        help="Key requests to package to be used when validating "
        "customer and partner RPMs.",
    )

    """ EXR GISO build options."""
    exrgroup = parser.add_argument_group("EXR only build options")

    exrgroup.add_argument(
        "--script",
        dest="script",
        type=str,
        help="Path to user executable script "
        "executed as part of bootup post activate.",
    )

    exrgroup.add_argument(
        "--in_docker",
        dest="in_docker",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
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

    exrgroup.add_argument(
        "--x86-only",
        dest="x86_only",
        action="store_true",
        default=False,
        help="Use only x86_64 rpms even if other "
        "architectures are applicable.",
    )

    exrgroup.add_argument(
        "--migration",
        dest="migration",
        action="store_true",
        default=False,
        help="To build Migration tar only for ASR9k",
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
            help="To build full iso only for xrv9k",
        )

    """ LNT GISO build options."""
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
        "--skip-dep-check", action="store_true", help=argparse.SUPPRESS,
    )

    lntgroup.add_argument(
        "--copy-dir",
        dest="copy_directory",
        type=str,
        help="Copy built artefacts to specified directory if provided. The "
        "specified directory must already exist, be writable by the "
        "builder and must not contain a previously built artefact with "
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
        "--buildinfo", dest="buildinfo", type=str, help=argparse.SUPPRESS,
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
    lntgroup.add_argument(
        "--image-script",
        dest="image_script",
        help="User specified image.py script to be used for packing/unpacking "
        "instead of the version extracted from the ISO. It will not be "
        "inserted into the GISO. Intended for debugging purposes only.",
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
        "--remove-all-key-requests",
        action="store_true",
        help="Remove all key requests from the input ISO",
    )
    lntgroup.add_argument(
        "--remove-key-requests",
        nargs="+",
        default=[],
        help=(
            "Remove key requests, specified in a space separated list. These "
            "are matched against the filename, e.g. key_request.kpkg"
        ),
    )
    lntgroup.add_argument(
        "--no-buildinfo",
        action="store_true",
        help=(
            "Do not update the build metadata in mdata.json with "
            "the GISO build information"
        )
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

    """ Check input ISO. """
    if not os.path.isfile(args.iso):
        raise AssertionError("Bundle ISO {} does not exist.".format(args.iso))
    filetype = gisoutils.get_file_type(args.iso)
    args.iso = os.path.abspath(args.iso)
    if filetype not in {FILE_TYPE_ISO, FILE_TYPE_UDF}:
        raise AssertionError(
            "Bundle ISO {} is not an ISO or UDF file.".format(args.iso)
        )

    """ Check if iso provided has exr platform name """
    args.exriso = gisoutils.is_platform_exr(args.iso)

    """ Check if input iso is a GISO, we are trying to extend. """
    if re.match(".*golden.*", str(args.iso)):
        args.gisoExtend = True
    else:
        args.gisoExtend = False

    """ Check if optimized or a full iso build is being triggered. """
    if hasattr(args, "optimize") or hasattr(args, "fullISO"):
        if args.optimize or args.fullISO:
            display_string = "Optimized" if args.optimize else "Full ISO"
            if not OPTIMIZE_CAPABLE:
                raise AssertionError(
                    f"{display_string} build workflow is not supported."
                )

    """ Check repo given in input. """
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

    """ Check xr config file if provided. """
    if args.xrconfig:
        if not os.path.isfile(args.xrconfig):
            raise AssertionError(
                "XR Config file {} does not exist.".format(args.xrconfig)
            )
        filetype = gisoutils.get_file_type(args.xrconfig)
        args.xrconfig = os.path.abspath(args.xrconfig)
        if filetype != FILE_TYPE_TEXT:
            raise AssertionError(
                "XR Config file {} "
                "has an invalid file type.".format(args.xrconfig)
            )

    """ Check ztp.ini file if provided. """
    if args.ztp_ini:
        if not os.path.isfile(args.ztp_ini):
            raise AssertionError(
                "ZTP ini file {} does not exist.".format(args.ztp_ini)
            )
        filetype = gisoutils.get_file_type(args.ztp_ini)
        args.ztp_ini = os.path.abspath(args.ztp_ini)
        if filetype != FILE_TYPE_TEXT:
            raise AssertionError(
                "ZTP ini file {} "
                "has an invalid file type.".format(args.ztp_ini)
            )

    """ Check init script if provided. """
    if args.script:
        if not os.path.isfile(args.script):
            raise AssertionError(
                "Init script {} does not exist.".format(args.script)
            )
        filetype = gisoutils.get_file_type(args.script)
        args.script = os.path.abspath(args.script)
        if filetype != FILE_TYPE_TEXT:
            raise AssertionError(
                "Init script {} "
                "has an invalid file type.".format(args.script)
            )

    """ Check input label if provided. """
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
                "Error: label {} contains characters other than "
                "alphanumeric and underscore".format(args.label)
            )
            raise AssertionError(
                "Error: label {} contains characters other than "
                "alphanumeric and underscore".format(args.label)
            )

    """ Check that remove_packages doesn't have an RPM file extension. """
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

    """ Check key packages if provided. """
    if args.key_requests:
        missing_key_requests = [
            k for k in args.key_requests if not os.path.exists(k)
        ]
        if missing_key_requests:
            raise AssertionError(
                "Error: The following key requests do not exist: {}".format(
                    ", ".join(missing_key_requests)
                )
            )
    return args


def main() -> None:
    """Parse CLI options"""
    cli_args, parser = parsecli()
    transform_dict: Dict[str, Any] = {}

    """ If yaml file is provided at input, validate and populate cli_args """
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
    if not cli_args.out_directory:
        cli_args.out_directory = DFLT_OUTPUT_DIR

    """ Setup the tool arguments. """
    cli_args = validate_and_setup_args(cli_args)

    """ Set up the build env """
    try:
        gisoutils.create_working_dir(
            cli_args.clean, cli_args.out_directory, MODULE_NAME,
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
    except FileExistsError as e:
        print(
            "Output directory {} exists. \n"
            "Consider passing --clean "
            "as input or remove directory and rerun.".format(
                cli_args.out_directory
            )
        )
        sys.exit(-1)
    except PermissionError as e:
        print(
            "Output directory {} exists. \n"
            "Unable to do output directory cleanup ".format(
                cli_args.out_directory
            )
        )
        print(e)
        sys.exit(-1)
    except OSError as e:
        print(
            "Output directory {} exists. \n"
            "Consider passing --clean "
            "as input or remove directory and rerun.".format(
                cli_args.out_directory
            )
        )
        print(e)
        sys.exit(-1)
    except Exception as e:
        print(e)
        sys.exit(-1)

    """ Console logging to inherit legacy eXR gisobuild logger attributes. """
    if cli_args.docker or cli_args.exriso:
        gisoutils.initialize_console_logging()

    """ Transform the parameters as expected by eXR and LNT tools. """
    if cli_args.docker:
        from utils.gisocontainer import execute_build

    elif cli_args.exriso:
        from exrmod.isotools_exr import execute_build

        transform_dict = EXR_CLI_DICT_MAP
    else:
        from lnt.launcher import execute_build  # type: ignore

        transform_dict = LNT_CLI_DICT_MAP

    try:
        if transform_dict:
            # Filter & transform eXR & LNT specific parameters.
            cli_args.__dict__ = {
                transform_dict[k]: v
                for k, v in cli_args.__dict__.items()
                if transform_dict.get(k) is not None
            }
    except KeyError as e:
        logger.error("Option {} in input not supported".format(e.args))
        sys.exit(-1)
    execute_build(cli_args)


if __name__ == "__main__":
    main()
