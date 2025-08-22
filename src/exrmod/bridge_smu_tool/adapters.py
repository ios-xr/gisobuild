# -----------------------------------------------------------------------------
# BSD 3-Clause License
#
# Copyright (c) 2022-2025, Cisco Systems, Inc. and its affiliates
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

"""
Contains a set of adapters that converts various types of inputs to the tool to one unified format.

Currently the tool supports inputs like:
- a list of paths to BridgeSMU rpms.
- a list of complete paths to BridgeSMU files (the files can be rpms or tarballs)
- a list of rpm names + a list of repositories where the rpm files can be found
- a list of DDTS IDs + a list of repositories where the rpm files can be found
- a list of v1 releases.

Our tool natively supports only the first interface, so this module is responsible for converting
the other interfaces to the first one.
"""

import os
import re
import json
from subprocess import run, PIPE, CompletedProcess
from typing import List, Dict, Set
import shutil
import logging
import tempfile
import glob
from .errors import InvalidInputError, InputParameter, PackagerError

logger = logging.getLogger(__name__)


class BridgeSMUInput:
    """
    Contains utilites to load and validate the input for the bridge SMU tool.
    """

    def __init__(  # pylint: disable=too-many-positional-arguments
        self,
        out_dir: str,
        platform: str,
        isorel: str,
        repolist: List[str],
        fsroot: str,
        matrixfile: str,
        bridge_rpms: List[str],
    ):
        self.out_dir = out_dir
        self.platform = platform
        self.isorel = isorel
        self.repolist = repolist
        self.fsroot = fsroot
        self.matrixfile = matrixfile
        self.bridge_rpms = bridge_rpms
        self.validate()
        self.bridge_rpm_paths: Dict[str, str] = self.get_bridge_rpm_paths()

    def validate(self):
        """
        Validate the input parameters for the bridge SMU tool.
        :raises InvalidInputError: If any of the input parameters are invalid.
        """

        def validate_output_dir(out_dir: str):
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)
            if not os.path.isdir(out_dir):
                raise InvalidInputError(
                    parameter=InputParameter.OUT_DIR,
                    message=f"Output path {out_dir} is not a directory.",
                )

        def validate_fsroot(fsroot: str):
            if not os.path.exists(fsroot):
                raise InvalidInputError(
                    parameter=InputParameter.FSROOT,
                    message=f"Filesystem root {fsroot} does not exist.",
                )
            if not os.path.isdir(fsroot):
                raise InvalidInputError(
                    parameter=InputParameter.FSROOT,
                    message=f"Filesystem root {fsroot} is not a directory.",
                )
            folders: List[str] = ["bin", "lib", "usr", "etc"]
            missing_folders = [
                folder
                for folder in folders
                if not os.path.exists(os.path.join(fsroot, folder))
            ]
            if missing_folders:
                raise InvalidInputError(
                    parameter=InputParameter.FSROOT,
                    message=f"Given path to the filesystem root {fsroot} doesn't seem to be a linux rootfs. {fsroot} contents: {', '.join(os.listdir(fsroot))}.",
                )

        def validate_repolist(repolist: List[str]):
            if not repolist:
                raise InvalidInputError(
                    parameter=InputParameter.REPOLIST,
                    message="Repository list cannot be empty.",
                )
            for repo in repolist:
                if not os.path.exists(repo):
                    raise InvalidInputError(
                        parameter=InputParameter.REPOLIST,
                        message=f"Repository {repo} does not exist.",
                    )
                if not os.path.isdir(repo):
                    raise InvalidInputError(
                        parameter=InputParameter.REPOLIST,
                        message=f"Repository {repo} is not a directory.",
                    )

        def validate_matrixfile(matrixfile: str):
            if not os.path.exists(matrixfile):
                raise InvalidInputError(
                    parameter=InputParameter.MATRIXFILE,
                    message=f"Matrix file {matrixfile} does not exist.",
                )
            if not os.path.isfile(matrixfile):
                raise InvalidInputError(
                    parameter=InputParameter.MATRIXFILE,
                    message=f"Matrix file {matrixfile} is not a file.",
                )
            if not re.match(r"\S*compatibility_matrix_\S*\.json$", matrixfile):
                raise InvalidInputError(
                    parameter=InputParameter.MATRIXFILE,
                    message=f"Matrix file {matrixfile} is not named correctly (format should be compatibility_matrix_*.json) were * stands for '.' delimited IOS-XR version.",
                )
            if not os.path.dirname(matrixfile).endswith("upgrade_matrix"):
                raise InvalidInputError(
                    parameter=InputParameter.MATRIXFILE,
                    message=f"Matrix file {matrixfile} should have 'upgrade_matrix' as the parent directory.",
                )
            try:
                with open(matrixfile, "r", encoding="utf-8") as f:
                    json.load(f)  # Validate JSON format
            except json.JSONDecodeError as e:
                raise InvalidInputError(
                    parameter=InputParameter.MATRIXFILE,
                    message=f"Matrix file {matrixfile} is not a valid JSON file: {e}",
                ) from e

        def validate_n_fix_platform(platform: str):
            if not platform:
                raise InvalidInputError(
                    parameter=InputParameter.PLATFORM,
                    message="Platform name cannot be empty.",
                )
            if not re.match(r"^[a-z0-9\-]+$", platform):
                raise InvalidInputError(
                    parameter=InputParameter.PLATFORM,
                    message=f"Platform {platform} is not valid. It should contain only lowercase letters, numbers, and hyphens.",
                )
            if self.platform == "asr9k":
                self.platform = "asr9k-x64"

        validate_output_dir(self.out_dir)
        validate_matrixfile(self.matrixfile)
        validate_fsroot(self.fsroot)
        validate_repolist(self.repolist)
        validate_n_fix_platform(self.platform)

    def get_bridge_rpm_paths(self) -> Dict[str, str]:
        """
        Get the full paths of the bridge RPMs.
        """
        rpm_paths: Dict[str, str] = {}
        missing_rpms = self.bridge_rpms.copy()
        for rpm in self.bridge_rpms:
            for repo in self.repolist:
                rpm_path = os.path.join(repo, rpm)
                if os.path.exists(rpm_path):
                    # check file type
                    if not re.match(
                        r"(\S+)-(\S+)-r(\S+)\.CSC[a-z]{2}[0-9]{5}\.(\S+)\.rpm$",
                        os.path.basename(rpm_path),
                    ):
                        raise InvalidInputError(
                            parameter=InputParameter.BRIDGE_RPMS,
                            message=f"File {rpm_path} is not a valid RPM file.",
                        )
                    cp: CompletedProcess = run(
                        ["file", "-Lb", rpm_path],
                        stdout=PIPE,
                        stderr=PIPE,
                        check=False,
                    )
                    if cp.returncode != 0:
                        raise InvalidInputError(
                            parameter=InputParameter.BRIDGE_RPMS,
                            message=f"Error checking file type for {os.path.basename(rpm_path)}: {cp.stderr.decode().strip()}",
                        )
                    if "RPM" not in cp.stdout.decode():
                        raise InvalidInputError(
                            parameter=InputParameter.BRIDGE_RPMS,
                            message=f"File {os.path.basename(rpm_path)} is not a valid RPM file. Type: {cp.stdout.decode().strip()}",
                        )
                    # If valid, add to the list
                    rpm_paths[rpm] = rpm_path
                    missing_rpms.remove(rpm)
                    break
        if missing_rpms:
            raise InvalidInputError(
                parameter=InputParameter.BRIDGE_RPMS,
                message=f"Bridge RPMs {', '.join(missing_rpms)} not found in any of the specified repositories.",
            )
        return rpm_paths


class Adapter:
    """
    Base class for all adapters.
    It defines the interface that all adapters should implement.
    """

    def __init__(  # pylint: disable=too-many-positional-arguments
        self,
        out_dir: str,
        platform: str,
        isorel: str,
        repolist: List[str],
        fsroot: str,
        matrixfile: str,
        bridge_input: List[str],
    ):
        self.out_dir = out_dir
        self.platform = platform
        self.isorel = isorel
        self.repolist = repolist
        self.fsroot = fsroot
        self.matrixfile = matrixfile
        self.input_data = bridge_input
        self.tmp_staging: List[str] = []

    def adapt(self) -> BridgeSMUInput:
        """
        Converts the input data to a list of paths to BridgeSMU rpms.
        This method should be implemented by all subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def prepare_input(self) -> BridgeSMUInput:
        """Small utility function to prepare the input data for the BridgeSMUInput class."""
        return BridgeSMUInput(
            os.path.join(self.out_dir, "bridge_smus"),
            self.platform,
            self.isorel,
            self.repolist,
            self.fsroot,
            self.matrixfile,
            self.input_data,
        )

    def __enter__(self):
        """
        Initializes the adapter and prepares the temporary staging area.
        """
        return self

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """
        Cleans up the temporary staging area.
        """
        for path in self.tmp_staging:
            if os.path.exists(path):
                try:
                    shutil.rmtree(path)
                except Exception as e:
                    logger.debug(
                        "Error removing temporary Directory %s: %s",
                        path,
                        str(e),
                        exc_info=True,
                    )
                    raise PackagerError(
                        f"Error removing temporary Directory {path}: {e}"
                    ) from e


class RpmAdapter(Adapter):
    """
    Adapter for a list of paths to BridgeSMU rpms.
    """

    def adapt(self) -> BridgeSMUInput:
        tar_file_paths: List[str] = []
        undiscovered_tars: List[str] = [
            tar
            for tar in self.input_data
            if tar.endswith((".tar", ".tar.gz", ".tgz"))
        ]
        for bridge_file in self.input_data:
            if bridge_file.endswith(".rpm"):
                continue
            for repo in self.repolist:
                full_path = os.path.join(repo, bridge_file)
                if os.path.exists(full_path):
                    tar_file_paths.append(full_path)
                    undiscovered_tars.remove(bridge_file)
                    break
        if undiscovered_tars:
            raise InvalidInputError(
                parameter=InputParameter.BRIDGE_RPMS,
                message=f"Bridge SMU files {', '.join(undiscovered_tars)} not found "
                "in any of the specified repositories.",
            )
        if tar_file_paths:
            # Create a temporary directory to extract the tar files
            tmp_dir = tempfile.mkdtemp(prefix="bridge_smu_", dir=self.out_dir)
            logger.debug(
                "Extracting tar files to temporary directory: %s", tmp_dir
            )
            # Add the temporary directory to the staging area for cleanup later
            self.tmp_staging.append(tmp_dir)
            self.repolist.append(tmp_dir)
            for tar_file in tar_file_paths:
                cp: CompletedProcess = None
                if tar_file.endswith(".tar.gz") or tar_file.endswith(".tgz"):
                    cp: CompletedProcess = run(
                        ["tar", "-xzf", tar_file, "-C", tmp_dir],
                        stdout=PIPE,
                        stderr=PIPE,
                        check=False,
                    )
                else:
                    cp: CompletedProcess = run(
                        ["tar", "-xf", tar_file, "-C", tmp_dir],
                        stdout=PIPE,
                        stderr=PIPE,
                        check=False,
                    )
                if cp.returncode != 0:
                    raise PackagerError(
                        f"Error extracting {tar_file}: {cp.stderr.decode().strip()}"
                    )
                self.input_data.remove(os.path.basename(tar_file))
            # Collect all RPMs from the extracted files
            bridge_rpms = [
                f for f in os.listdir(tmp_dir) if f.endswith(".rpm")
            ]
            if not bridge_rpms:
                dir_contents = os.listdir(tmp_dir)
                logger.debug(
                    "No RPM files found in the extracted tar files: "
                    "Extracted files in tar: %s",
                    ", ".join(dir_contents),
                )
                raise InvalidInputError(
                    parameter=InputParameter.BRIDGE_RPMS,
                    message="No RPM files found in the extracted tar files.",
                )
            logger.info("Found Bridge SMU RPMs: %s", ", ".join(bridge_rpms))
            self.input_data.extend(bridge_rpms)
        # Create a BridgeSMUInput object with the validated data
        return self.prepare_input()


class DDTSAdapter(Adapter):
    """
    Adapter for a list of DDTS IDs.
    """

    def adapt(self) -> BridgeSMUInput:
        undiscovered_ddts: Set[str] = set(self.input_data.copy())
        logger.info(
            "Searching for BridgeSMU rpms for DDTS IDs: %s",
            ", ".join(undiscovered_ddts),
        )
        discovered_rpms: List[str] = []
        for repo in self.repolist:
            for rpm in glob.glob(os.path.join(repo, "*CSC*.rpm")):
                m = re.search(
                    r"(?P<ddts_id>" + "|".join(self.input_data) + r")", rpm
                )
                if m:
                    # TODO: ignore rpms that have the same version as the iso even though
                    # they have the same DDTS ID
                    discovered_rpms.append(os.path.basename(rpm))
                    undiscovered_ddts.discard(
                        m.group("ddts_id"),
                    )
        if undiscovered_ddts:
            raise InvalidInputError(
                parameter=InputParameter.BRIDGE_RPMS,
                message=f"rpms for DDTS IDs {', '.join(undiscovered_ddts)} not "
                "found in any of the specified repositories.",
            )
        self.input_data = discovered_rpms
        # Create a BridgeSMUInput object with the validated data
        return self.prepare_input()


class ReleaseAdapter(Adapter):
    """
    Adapter for a list of release versions.
    """

    def adapt(self) -> BridgeSMUInput:
        self.input_data = [rel.replace(".", "") for rel in self.input_data]
        undiscovered_rels: Set[str] = set(self.input_data.copy())
        discovered_rpms: List[str] = []
        for repo in self.repolist:
            for rpm in glob.glob(
                os.path.join(repo, "*CSC*.rpm"), recursive=False
            ):
                m = re.search(
                    r"-r(?P<rel>"
                    + "|".join(self.input_data)
                    + r")(\S*)\.CSC[a-z]{2}[0-9]{5}",
                    rpm,
                )
                if m:
                    discovered_rpms.append(os.path.basename(rpm))
                    undiscovered_rels.discard(m.group("rel"))
        # Create a BridgeSMUInput object with the validated data
        if undiscovered_rels:
            raise InvalidInputError(
                parameter=InputParameter.BRIDGE_RPMS,
                message=f"SMUs for releases {', '.join(undiscovered_rels)} not "
                "found in any of the specified repositories.",
            )
        self.input_data = discovered_rpms
        return self.prepare_input()
