# -----------------------------------------------------------------------------

""" Launch a GISO build in a container.

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
    "system_resource_prep",
    "setup_copy_out_directory",
    "copy_artefacts",
)


import argparse
import json
import logging
import os
import pathlib
import re
import shutil
import tempfile
from typing import Optional

from utils import gisoglobals as gglobals
from utils import gisoutils

from .. import gisoutils as lnt_utils

logger = logging.getLogger("launcher")


# Output build artefacts to this location in the container
#
# - Output dir is input to the build script
# - Log dir and artifact dir are calculated by the build script based on the
#   output dir
_CTR_OUT_DIR = gglobals.CTR_OUT_DIR
_CTR_LOG_DIR = gglobals.CTR_LOG_DIR
_CTR_ARTIFACT_DIR = gglobals.CTR_ARTIFACT_DIR

# Name of the buildinfo file, generated in a temp dir and passed as input to
# the container.
_BUILDINFO_MDATA = "buildinfo_mdata.json"


def system_resource_prep(args: argparse.Namespace) -> str:
    """
    Convert any arguments provided into a yaml file

    :param args:
        The arguments provided to the unified giso build script

    :returns str:
        Path to the yaml file containing the arguments provided

    """

    tempdir = tempfile.mkdtemp()
    cliConfig_file = os.path.join(tempdir, "cliConfig.yaml")

    args_dict = args.__dict__.copy()
    args_dict["cli_yaml"] = None
    args_dict["docker"] = False
    args_dict["clean"] = True
    args_dict["in_docker"] = False
    # Set the location of where the build artefacts should be placed inside the
    # conatiner
    args_dict["out_directory"] = str(_CTR_OUT_DIR)
    args_dict["create_checksum"] = True

    # Generate build info metadata outside of docker environment
    buildinfo_mdata = lnt_utils.generate_buildinfo_mdata()
    mdata_file = os.path.join(tempdir, _BUILDINFO_MDATA)
    with open(mdata_file, "w") as f:
        f.write(json.dumps(buildinfo_mdata))
    args_dict["buildinfo"] = mdata_file

    # Make necessary changes to yaml file to be passed
    gisoutils.dump_yaml_giso_arguments(cliConfig_file, args_dict)

    return cliConfig_file


def setup_copy_out_directory(args: argparse.Namespace) -> None:
    """
    Check that copy and output directories are set accordingly.

    :param args:
        The arguments provided to the unified giso build script

    """
    out_dir = _canonical_path(args.out_directory)
    # Output directory is not optional (but the copy directory is).
    assert out_dir is not None
    copy_dir = _canonical_path(args.copy_directory)
    if copy_dir is not None:
        try:
            lnt_utils.check_copy_dir(str(copy_dir))
        except lnt_utils.CopyDirInvalidError as error:
            raise RuntimeError("Unable to setup output directories") from error


def copy_artefacts(
    src_dir: pathlib.Path,
    log_dir: pathlib.Path,  # pylint: disable=unused-argument
    out_dir: pathlib.Path,
    copy_dir: Optional[pathlib.Path],
) -> None:
    """
    Copy build artefacts from container to specified output directory and copy
    directory

    :param src_dir:
        Directory under which the artefact and logs directories are staged.

    :param log_dir:
        [Ignored] Directory where *eXR* thinks that built logs are staged.

    :param out_dir:
        Specified output directory

    :param copy_dir:
        Additional directory to copy built artefacts to

    """
    artefacts_to_copy = []
    artefact_dir = src_dir / _CTR_ARTIFACT_DIR
    output_dir = out_dir / _CTR_ARTIFACT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    for item in artefact_dir.iterdir():
        shutil.copy2(item, output_dir)
        artefacts_to_copy.append(str(item))
    print(f"Build artefacts copied to {output_dir}")
    gisoutils.verify_checksums(str(output_dir), gglobals.CHECKSUM_FILE_NAME)
    if copy_dir is not None:
        lnt_utils.copy_artefacts_to_dir(artefacts_to_copy, str(copy_dir))
        print(f"Build artefacts copied to {copy_dir}")
    # Copy build logs from container.
    _copy_logs(out_dir / _CTR_LOG_DIR, src_dir / _CTR_LOG_DIR)


def _copy_logs(log_dir: pathlib.Path, src_dir: pathlib.Path) -> None:
    """
    Copy all logs from container to the output directory

    :param log_dir:
        Output directory for logs.
    :param src_dir:
        Staged container output directory to copy from.

    """
    log_dir.mkdir(parents=True, exist_ok=True)
    tmp_log_dir = log_dir / "container"
    os.makedirs(tmp_log_dir, exist_ok=True)

    for item in src_dir.iterdir():
        # Match foo.log and foo.log.1, foo.log.2, etc
        if re.match(r".*\.log(\.\d+)?", item.name) is not None:
            shutil.copy2(item, tmp_log_dir)
    print(f"Container Logs copied to {tmp_log_dir}")


def _canonical_path(path: Optional[str]) -> Optional[pathlib.Path]:
    """
    Turn a maybe-relative path into a fully resolved absolute path.

    If the input is `None`, the output is `None`.

    """
    if path is None:
        return None
    else:
        return pathlib.Path(path).resolve()
