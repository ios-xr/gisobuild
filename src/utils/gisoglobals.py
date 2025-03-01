# -----------------------------------------------------------------------------

""" GISO Globals.

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

import pathlib
import tempfile

GISO_PKG_FMT_VER = 1.0

SPIRIT_BOOT_SUBSTRING = "spirit-boot"
SYSADMIN_SUBSTRING = "SYSADMIN"
CALVADOS_SUBSTRING = "CALVADOS"
HOSTOS_SUBSTRING = "hostos"
IOS_XR_SUBSTRING = "IOS-XR"
ADMIN_SUBSTRING = "ADMIN"
HOST_SUBSTRING = "HOST"
SMU_SUBSTRING = "SMU"
XR_SUBSTRING = "XR"

DEFAULT_RPM_PATH = "giso/<rpms>"
SIGNED_RPM_PATH = "giso/boot/initrd.img/<rpms>"
SIGNED_NCS5500_RPM_PATH = (
    "giso/boot/initrd.img/iso/system_image.iso/boot/initrd.img/<rpms>"
)
SIGNED_651_NCS5500_RPM_PATH = (
    "giso/boot/initrd.img/iso/system_image.iso/<rpms>"
)
global_platform_name = "None"
EXR_SUPPORTED_PLATFORMS = [
    "asr9k",
    "ncs1k",
    "ncs1001",
    "ncs5k",
    "ncs5500",
    "ncs6k",
    "ncs560",
    "ncs540",
    "iosxrwb",
    "iosxrwbd",
    "ncs1004",
    "xrv9k",
]


FILE_TYPE_RPM = "RPM"
FILE_TYPE_ISO = "ISO"
FILE_TYPE_UDF = "UDF"
FILE_TYPE_TEXT = "TEXT"
FILE_TYPE_TAR = "TAR"
FILE_TYPE_UNKNOWN = "UNKNOWN"

file_types = {
    FILE_TYPE_RPM: ["RPM"],
    FILE_TYPE_ISO: ["ISO", "9660", "CD-ROM"],
    FILE_TYPE_UDF: ["UDF"],
    FILE_TYPE_TAR: ["POSIX", "tar", "archive"],
    FILE_TYPE_TEXT: ["ASCII"],
}

EXR_CLI_DICT_MAP = {
    "iso": "bundle_iso",
    "repo": "rpmRepo",
    "xrconfig": "xrConfig",
    "ztp_ini": "ztp_ini",
    "script": "script",
    "label": "gisoLabel",
    "no_label": "no_label",
    "out_directory": "out_directory",
    "create_checksum": "create_checksum",
    "cli_yaml": "cli_yaml",
    "clean": "out_clean",
    "migration": "migTar",
    "optimize": "optimize",
    "x86_only": "x86_only",
    "bes_logging": "bes_logging",
    "docker": "docker",
    "fullISO": "fullISO",
    "gisoExtend": "gisoExtend",
    "version": "version",
    "in_docker": "in_docker",
    "exriso": "exriso",
    "pkglist": "pkglist",
    "bridge_fixes": "bridge_fixes",
    "remove_packages": None,
    "skip_usb_image": None,
    "skip_dep_check": None,
    "clear_bridging_fixes": None,
    "buildinfo": None,
    "copy_directory": None,
    "verbose_dep_check": None,
    "debug": "debug",
    "isoinfo": None,
    "image_script": None,
    "key_request": None,
    "clear_key_request": None,
    "no_buildinfo": None,
}

LNT_CLI_DICT_MAP = {
    "iso": "iso",
    "repo": "repo",
    "xrconfig": "xrconfig",
    "remove_packages": "remove_packages",
    "skip_usb_image": "skip_usb_image",
    "skip_dep_check": "skip_dep_check",
    "ztp_ini": "ztp_ini",
    "label": "label",
    "no_label": "no_label",
    "out_directory": "out_dir",
    "create_checksum": "create_checksum",
    "copy_directory": "copy_dir",
    "clean": "clean",
    "bridge_fixes": "bridging_fixes",
    "clear_bridging_fixes": "clear_bridging_fixes",
    "version": "version",
    "script": None,
    "cli_yaml": None,
    "migration": None,
    "optimize": None,
    "x86_only": None,
    "bes_logging": "bes_logging",
    "docker": "docker",
    "fullISO": None,
    "gisoExtend": None,
    "in_docker": None,
    "exriso": "exriso",
    "pkglist": "pkglist",
    "buildinfo": "buildinfo",
    "verbose_dep_check": "verbose_dep_check",
    "debug": "debug",
    "isoinfo": "isoinfo",
    "image_script": "image_script",
    "only_support_pids": "only_support_pids",
    "key_request": "key_request",
    "clear_key_request": "clear_key_request",
    "no_buildinfo": "no_buildinfo",
}

# Name of JSON checksum file
CHECKSUM_FILE_NAME = "checksums.json"

# Container globals.
# This image version *MUST* be updated whenever the built container changes
# (e.g. Dockerfile change).
IMAGE_NAME = "cisco-xr-gisobuild"
IMAGE_VERSION = "2.3.4"

CTR_OUT_DIR = pathlib.Path(
    tempfile.TemporaryDirectory(prefix="output_gisobuild-").name
)
CTR_LOG_DIR = "logs"
CTR_ARTIFACT_DIR = "giso"

# Environment variables used by the image.py script.
IMAGE_PY_ENV_VARS = {
    "CISCO_IMAGE_PY_ISOINFO",
    "CISCO_IMAGE_PY_UNSQUASHFS",
    "CISCO_IMAGE_PY_7Z",
    "CISCO_IMAGE_PY_CREATEREPO",
    "CISCO_IMAGE_PY_MKSQUASHFS",
    "CISCO_IMAGE_PY_MKISOFS",
}
# Environment variables used by the Lindt gisobuild.
LNT_ENV_VARS = IMAGE_PY_ENV_VARS.copy()

# Environment variables used by eXR GISOBuild
EXR_ENV_VARS = {
    "JAM_PRODUCTION_IMAGE_BUILD",
    "SWIMS_TREAT_TICKET_AS_TOKEN",
    "SWIMS_SESSION_TOKEN",
    "SWIMS_SKIP_TICKET_CHECK",
    "SWIMS_TOGGLE_TOKEN",
    "SWIMS_OVERRIDE_TICKET_CLI_PARAM_WITH_ENV",
    "PYTHONPATH",
    "MATRIX_INFO_PATH",
}

# Environment variables that are always needed and should be preserved when
# sanitizing the environment.
REQUIRED_ENV_VARS = {
    "PATH",
    "TMPDIR",
}

# Names of parsed CLI arguments that correspond to input files and directories
# (either single entries or lists).
INPUT_FILE_DIR_ARGS_LNT = (
    "bridge_fixes",
    "buildinfo",
    "image_script",
    "isoinfo",
)
INPUT_FILE_DIR_ARGS_EXR = ()
INPUT_FILE_DIR_ARGS_CMN = (
    "cli_yaml",
    "iso",
    "key_request",
    "repo",
    "xrconfig",
    "ztp_ini",
)
