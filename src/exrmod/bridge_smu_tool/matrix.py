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
Contains classes to handling the compatibility matrix for the bridge SMU tool.
"""

# -----------------------------------------------------------------------------
# Compatibiltiy Matrix has the following structure:
# {
#     "file_version": "1.0",
#     "release": "25.4.1",
#     "permitted": {
#         "24.1.1": {
#             "25.4.1": [
#                 {
#                     "platform": "ncs1004",
#                     "caveats": [
#                         "First caveat",
#                         "Second caveat"
#                     ],
#                     "bridge_smus": [
#                         "ncs1004-sysadmin-install-24.1.1.9-r2411.CSCwn05862.x86_64.rpm"
#                     ],
#                     "bridge_prereqs": [],
#                     "blocklisted_smus": []
#                 }
#             ]
#         },
#         "24.3.1": {
#             "25.4.1": [
#                 {
#                     "platform": "ncs1004",
#                     "caveats": [
#                         "First caveat",
#                         "Second caveat"
#                     ],
#                     "bridge_smus": [
#                         "ncs1004-sysadmin-install-24.3.1.15-r2431.CSCwn05862.x86_64.rpm"
#                     ],
#                     "bridge_prereqs": []
#                     "blocklisted_smus": []
#                 }
#             ]
#         }
#     }
# }

from typing import List, Dict, Set
import json
import re
import logging
from .errors import MatrixError, InvalidInputError, InputParameter

logger = logging.getLogger(__name__)


class RpmInfo:
    """
    Class to represent the RPM information.
    """

    def __init__(self, name: str, version: str, release: str, arch: str):
        self.name = name
        self.version = version
        self.release = release
        self.arch = arch

    def __str__(self):
        return f"{self.name}-{self.version}-{self.release}.{self.arch}.rpm"


class MatrixHandler:
    """
    This class handles the compatibility matrix for the bridge SMU tool.
    It provides methods to load, validate, and retrieve compatibility data.
    """

    def __init__(self, matrixfile: str):
        self.matrix_file = matrixfile
        self.matrix_data = self.load_matrix()

    def load_matrix(self):
        """
        Load the compatibility matrix from the specified file.
        """
        try:
            with open(self.matrix_file, "r", encoding="utf-8") as f:
                return json.load(f)
        # We should never encounter the following errors as the input is validated in the Adapter.
        except FileNotFoundError as e:
            raise InvalidInputError(
                parameter=InputParameter.MATRIXFILE,
                message=f"Matrix file {self.matrix_file} does not exist.",
            ) from e
        except json.JSONDecodeError as e:
            raise InvalidInputError(
                parameter=InputParameter.MATRIXFILE,
                message=f"Matrix file {self.matrix_file} is not a valid JSON file: {e}",
            ) from e

    def convert_to_regex(
        self, matrix_data: Dict[str, List[str]]
    ) -> Dict[str, List[str]]:
        """
        Given the input similar to the output of validate_n_filter,
        convert the each smu name to a regex pattern ignoring the version field.

        :param: matrix_data: The compatibility matrix data containing SMU names.
        :return: A dictionary with the same structure as matrix_data but with SMU names
                 converted to regex patterns.
        """
        regex_data = {}
        for from_version, smus in matrix_data.items():
            regex_data[from_version] = []
            for smu in smus:
                # Convert the SMU name to a regex pattern
                match = re.match(
                    r"(?P<name>.+)-(?P<version>.+)-(?P<release>.+)\.(?P<arch>.+)\.rpm$",
                    smu,
                )
                if match:
                    smu_pattern = r"{}-.*-{}\.{}\.rpm$".format(  # pylint: disable=consider-using-f-string
                        match.group("name"),
                        match.group("release"),
                        match.group("arch"),
                    )
                    rpm_info: RpmInfo = RpmInfo(
                        name=match.group("name"),
                        version=match.group("version"),
                        release=match.group("release"),
                        arch=match.group("arch"),
                    )
                    regex_data[from_version].append((smu_pattern, rpm_info))
                else:
                    raise MatrixError(
                        where=f"SMU: {smu}",
                        message=f"SMU name {smu} does not match the expected pattern.",
                    )
        return regex_data

    def validate_n_filter(
        self, to_version: str, from_version: Set[str], platform: str
    ):
        """
        Validate the compatibility matrix structure.
        Run basic sanity checks on the matrix data at least for the relevant fields.
        We assume that the matrix file is well-formed JSON and loaded correctly by this point.

        :param to_version: The target version the user is going to upgrade to.
        :param from_version: The list of versions the user is upgrading from.
        :param platform: The platform for which the compatibility is being checked.

        :raises ValueError: If the matrix data is not structured correctly.

        :return: A dictionary containing the compatibility data for the specified platform and to_version.
        """
        # Return structure of the compatibility dictionary:
        # {
        #     "from_version_1": [<smu1>, <smu2>, ...],
        #     "from_version_2": [<smu1>, <smu2>, ...],
        #     ...
        # }
        # This function will pre filtered based on the platform and to_version.

        logger.info(
            "Validating compatibility matrix for platform: %s, "
            "to_version: %s, from_versions: %s",
            platform,
            to_version,
            from_version,
        )
        compatibility_data = {}

        from_version = [
            v.replace(".", "") for v in from_version
        ]  # may end with 08I, 99I etc. iteration number.
        to_version = to_version.replace(
            ".", ""
        )  # may end with 08I, 99I etc. iteration number.

        def validate_n_get_platform_data(platform_data: List[dict]):
            # Structure:
            # [
            #     {
            #         "platform": "ncs1004",
            #         "bridge_smus": ["ncs1004-sysadmin-install-24.1.1.9-r2411.CSCwn05862.x86_64.rpm"],
            #     },
            #     {
            #         "platform": "ncs5500",
            #         "bridge_smus": ["ncs5500-sysadmin-install-24.1.1.9-r2411.CSCwn05862.x86_64.rpm"],
            #         "bridge_prereqs": []
            #     }
            # ]
            if not isinstance(platform_data, list):
                raise MatrixError(
                    where=json.dumps(platform_data),
                    message=f"Matrix file {self.matrix_file} compatibility data should be a list.",
                )
            for platform_info in platform_data:
                try:
                    if platform_info["platform"] != platform:
                        continue
                    if not isinstance(platform_info["bridge_smus"], list):
                        raise ValueError(
                            where=json.dumps(platform_info),
                            message=f"Matrix file {self.matrix_file} 'bridge_smus' should be a list.",
                        )
                    all_smus = platform_info.get("bridge_smus")
                    all_smus.extend(platform_info.get("bridge_prereqs", []))
                    for smu in all_smus:
                        if not isinstance(smu, str) and not smu.endswith(
                            ".rpm"
                        ):
                            raise ValueError(
                                where=json.dumps(platform_info),
                                message=f"Matrix file {self.matrix_file} 'bridge_smus' "
                                "should contain valid RPM filenames ending with '.rpm'.",
                            )
                    return all_smus
                except KeyError as e:
                    raise MatrixError(
                        where=json.dumps(platform_info),
                        message=f"Encountered error while parsing: {platform}",
                    ) from e
                except ValueError as e:
                    raise MatrixError(
                        where=json.dumps(platform_info),
                        message=f"Encountered error while parsing: {platform}",
                    ) from e

        def validate_permitted_field(permitted_data: dict) -> List[str]:
            # Structure:
            # {
            #     "from_version_1": {
            #         "to_version_1": [ {platform - 1 info}, {platform - 2 info}, ... ],
            #         "to_version_2": [ {platform - 1 info}, {platform - 2 info}, ... ]
            #     },
            #     "from_version_2": {
            #         "to_version_1": [ {platform - 1 info}, {platform - 2 info}, ... ],
            #         "to_version_2": [ {platform - 1 info}, {platform - 2 info}, ... ]
            #     }
            # }

            if not isinstance(permitted_data, dict):
                raise MatrixError(
                    where=json.dumps(permitted_data),
                    message=f"Matrix file {self.matrix_file} 'permitted' field should be a dictionary.",
                )
            for v1, v2_data in permitted_data.items():
                try:
                    if not isinstance(v2_data, dict):
                        raise MatrixError(
                            where=json.dumps(v2_data),
                            message=f"Matrix file {self.matrix_file} compatibility data for {v2_data} should be a dictionary.",
                        )
                    v1 = v1.replace(".", "")
                    for req_v1 in from_version:
                        if not req_v1.startswith(v1):
                            continue
                        for v2, platforms_data in v2_data.items():
                            v2 = v2.replace(".", "")
                            if to_version.startswith(v2):
                                compatibility_data[v1] = (
                                    validate_n_get_platform_data(
                                        platforms_data
                                    )
                                )
                except ValueError as e:
                    raise MatrixError(
                        where=json.dumps(v2_data),
                        message=f"Encountered error while parsing: {v1} : {v2_data}",
                    ) from e
                except KeyError as e:
                    raise MatrixError(
                        where=json.dumps(v2_data),
                        message=f"Encountered error while parsing: {v1} : {v2_data}",
                    ) from e

        # Validate mandatory fields
        mandetory_fields = ["file_version", "release", "permitted"]
        for field in mandetory_fields:
            if field not in self.matrix_data:
                raise MatrixError(
                    where=json.dumps(self.matrix_data),
                    message=f"Matrix file {self.matrix_file} is missing mandatory field: {field}",
                )

        # Validate matrix for each permitted upgrade path limit the search to the specified:
        # platform and to_version and from_version.
        validate_permitted_field(self.matrix_data["permitted"])
        return compatibility_data
