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
This module defines custom exceptions for the bridge SMU tool.
There are majorly three types of exceptions:
0. BridgeSMUToolError: Base class for all exceptions raised by the Bridge SMU Tool.
1. InvalidInputError: Raised when the input provided to the packager is invalid.
2. MatrixError: Raised when there is an issue with the matrix file.
3. PackagerError: A generic error for all issues related to building bridge SMUs
"""

from enum import Enum


class InputParameter(Enum):
    """
    Enum to represent the type of input provided to the Bridge SMU Tool.
    """

    OUT_DIR = "output directory"
    PLATFORM = "platform name"
    ISOREL = "IOS-XR Release"
    REPOLIST = "List of repositories"
    FSROOT = "filesystem root"
    MATRIXFILE = "Matrix File"
    BRIDGE_RPMS = "Bridge rpms in input"


class BridgeSMUToolError(Exception):
    """
    Base class for all exceptions raised by the Bridge SMU Tool.
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidInputError(BridgeSMUToolError):
    """
    Custom exception for handling invalid input errors.
    :param parameter: The parameter that caused the error. This helps in identifying which input was invalid.
    :param message: A descriptive error message.
    """

    def __init__(self, parameter: InputParameter, message: str):
        super().__init__(message)
        self.message: str = message
        self.parameter: InputParameter = parameter

    def __str__(self):
        return f"InvalidInputError: {self.parameter.value} - {self.message}"


class MatrixError(BridgeSMUToolError):
    """
    Custom exception for handling matrix file errors.
    :param where: The location in the matrix where the error occurred. This is json string that can be logged for debugging.
    :param message: A descriptive error message.
    """

    def __init__(self, where: str, message: str):
        super().__init__(message)
        self.message = message
        self.where = where

    def __str__(self):
        return f"MatrixError: {self.message}"


class PackagerError(BridgeSMUToolError):
    """
    Custom exception for handling errors related to the Bridge SMU packager. For example,
    Copy errors, delete errors, etc.
    :param message: A descriptive error message.
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self):
        return f"PackagerError: {self.message}"
