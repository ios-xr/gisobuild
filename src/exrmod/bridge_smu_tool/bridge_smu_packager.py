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
This is the mother script that packages bridge SMUs into the giso.
"""

import shutil
import os
import logging
import re
from typing import List, Dict, Set
from .adapters import BridgeSMUInput
from .matrix import MatrixHandler, RpmInfo
from .errors import InvalidInputError, PackagerError


def setup_logging():
    """
    Set up logging configuration.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s:%(name)s:%(levelname)s:%(message)s",
    )
    bridge_logger = logging.getLogger(__name__)
    return bridge_logger


logger = setup_logging()


class BridgeSMUPackager:
    """
    Class to package bridge SMUs into the giso.
    """

    def __init__(self, packager_inputs: BridgeSMUInput):
        """
        Initialize the BridgeSMUPackager with the provided inputs.
        """
        self.packager_inputs: BridgeSMUInput = packager_inputs
        self.matrix_parser: MatrixHandler = MatrixHandler(
            self.packager_inputs.matrixfile
        )
        logger.info(
            "Provided matrix file: %s", self.packager_inputs.matrixfile
        )

    def get_all_v1_versions(self) -> Set[str]:
        """
        Get all possible V1 versions of bridge SMU RPMs provided in the bridge_rpm_paths.
        """
        v1_versions: Set[str] = set()
        for rpm in self.packager_inputs.bridge_rpm_paths:
            rpm = os.path.basename(rpm)
            match = re.search(r"-(?P<release>r\S+)\.CSC[a-z]{2}[0-9]{5}", rpm)
            if match:
                v1_versions.add(match.group("release").lstrip("r"))
            else:
                # we should never reach here as the input is validated in the Adapter.
                raise InvalidInputError(
                    parameter="Bridge Rpms in input",
                    message=f"RPM {rpm} is not a SMU rpm",
                )
        return v1_versions

    def package(self):
        """
        Main method to package the bridge SMUs.
        """
        # Step 1: get all possible V1 versions bridge SMU rpms provided.
        v1_versions = self.get_all_v1_versions()

        # Step 2: get the bridge SMU list for the specified platform and versions.
        bridge_smus_by_release: Dict[str, List[str]] = (
            self.matrix_parser.validate_n_filter(
                self.packager_inputs.isorel,
                v1_versions,
                self.packager_inputs.platform,
            )
        )
        if not bridge_smus_by_release:
            raise PackagerError(
                f"No bridge SMUs found for platform {self.packager_inputs.platform} "
                f"to version: {self.packager_inputs.isorel} "
                f"from versions: {', '.join(v1_versions)}"
            )
        for release, smus in bridge_smus_by_release.items():
            logger.debug(
                "Found expected bridge SMUs for release %s: %s",
                release,
                ", ".join(smus),
            )

        # Convert the SMU names to regex patterns
        # This is required because the posted SMU's may have different version than the ones in the matrix.
        # The regex patterns will match any version of the SMU provided they have the same
        # name, release and architecture.
        smu_regexes = self.matrix_parser.convert_to_regex(
            bridge_smus_by_release
        )

        # Step 3: copy the bridge SMUs to the output directory making sure that:
        # All rpms specified in the bridge SMU list for each from_version
        # are present in the output directory.

        all_present_rpms: Set[str] = set(
            self.packager_inputs.bridge_rpm_paths.keys()
        )
        logger.debug(
            "All bridge SMUs present in repo: %s", ", ".join(all_present_rpms)
        )

        bridgeSMU_summary: Dict[str, List[str]] = {}
        missing_rpms: Dict[str, List[RpmInfo]] = {}
        for release, smu_patterns in smu_regexes.items():
            bridgeSMU_summary[release] = []
            release_dir = os.path.join(
                self.packager_inputs.out_dir, f"r{release}"
            )
            if not os.path.exists(release_dir):
                os.makedirs(release_dir)
            for smu_pattern, rpm_info in smu_patterns:
                # Find the SMU that matches the pattern
                matching_rpms = [
                    rpm
                    for rpm in all_present_rpms
                    if re.match(smu_pattern, rpm)
                ]  # should typically have one entry
                bridgeSMU_summary[release].extend(matching_rpms)
                if not matching_rpms:
                    missing_rpms.setdefault(release, []).append(rpm_info)
                    continue
                logger.debug(
                    "Found bridge SMUs for release %s matching pattern %s: %s",
                    release,
                    smu_pattern,
                    ", ".join(matching_rpms),
                )
                # Copy the SMUs to the output directory
                for smu in matching_rpms:
                    shutil.copy(
                        self.packager_inputs.bridge_rpm_paths[smu], release_dir
                    )

        if missing_rpms:
            # The following log will be used during UT. Change or reformat carefully.
            logger.info("Missing bridge SMUs for the following releases:")
            for release, rpms in missing_rpms.items():
                formatted_rpms = "\n\t".join(
                    [
                        f"{rpm.name}-<version>-{rpm.release}.{rpm.arch}.rpm"
                        for rpm in rpms
                    ]
                )
                logger.info("Release %s:\n\t%s", release, formatted_rpms)
            # Delete the output directory if there are missing SMUs as the mother script may choose to ignore this error.
            shutil.rmtree(self.packager_inputs.out_dir)
            raise PackagerError(
                "Aborting packaging due to missing bridge SMUs!"
            )
        # Step 4: log the summary of the packaged bridge SMUs

        # The following log will be used during UT. Change or reformat carefully.
        logger.info("\nBridge SMUs packaged successfully. Summary:\n")
        for release, smus in bridgeSMU_summary.items():
            formatted_rpms = "\n\t".join(smus)
            logger.info("Release %s:\n\t%s\n", release, formatted_rpms)
