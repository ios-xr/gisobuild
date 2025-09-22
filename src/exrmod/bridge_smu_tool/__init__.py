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
This module provides the Bridge SMU Packaging functionality.
The main class is `BridgeSMUPackager`, which handles the packaging of bridge SMUs based on the provided input.
Since multiple types of inputs are supported, This module also includes a handy set of adapters to
convert various input formats into a unified `BridgeSMUInput` format.

USAGE:
1. Select the appropriate adapter based on your input type. and call the `adapt` method to get a
   `BridgeSMUInput` object.
2. Create an instance of `BridgeSMUPackager` with the `BridgeSMUInput` object.
3. Call the `package` method to start the packaging process.
"""

__all__ = [
    "BridgeSMUInput",
    "BridgeSMUPackager",
    "InvalidInputError",
    "InputParameter",
    "MatrixError",
    "PackagerError",
    "BridgeSMUToolError",
    "Adapter",
    "DDTSAdapter",
    "RpmAdapter",
    "ReleaseAdapter",
]

from .bridge_smu_packager import BridgeSMUInput, BridgeSMUPackager
from .adapters import Adapter, DDTSAdapter, RpmAdapter, ReleaseAdapter
from .errors import (
    InputParameter,
    MatrixError,
    PackagerError,
    InvalidInputError,
    BridgeSMUToolError,
)
