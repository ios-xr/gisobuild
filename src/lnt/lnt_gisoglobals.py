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

"""Provides shared definitions used by LNT GISO modules."""

from pathlib import Path

LNT_PLATFORM_FAMILY = "platform-family"
LNT_XR_VERSION = "xr-version"
LNT_IMAGE_NAME = "image-name"
LNT_GISO_LABEL = "giso-label"
LNT_GISO_BUILDER = "giso-builder"
LNT_GISO_BUILD_TIME = "giso-build-time"
LNT_GISO_BUILD_HOST = "giso-build-host"
LNT_GISO_BUILD_DIR = "giso-build-dir"
LNT_GISO_BUILD_CMD = "giso-build-cmd"
LNT_GISO_CDETS = "giso-cdets"
LNT_ISO_TYPE_KEY = "iso-type"
LNT_ISO_FMT_VER = "iso-format-version"

LNT_MDATA_DIR = Path("mdata")
LNT_MDATA_FILE = "mdata.json"
LNT_MDATA_PATH = LNT_MDATA_DIR / LNT_MDATA_FILE
LNT_BUILDINFO_DIR = Path("mdata")
LNT_BUILDINFO_FILE = "build-info.txt"
LNT_BUILDINFO_PATH = LNT_BUILDINFO_DIR / LNT_BUILDINFO_FILE
