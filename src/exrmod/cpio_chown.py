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

import sys

hdrsz = 110

if len(sys.argv) == 2:
    infile = open(sys.argv[1], 'r+b')
    outfile = infile
else:
    infile = sys.stdin.buffer
    outfile = sys.stdout.buffer

while True:
    header = bytearray(infile.read(hdrsz))

    if len(header) < hdrsz:
        break  # End of file or incomplete header

    if header[0:6] != b'070701':
        raise AssertionError('Unexpected cpio format')

    # Modify owner
    header[22:30] = b"00000000"
    # Modify group
    header[30:38] = b"00000000"

    namesize = int(header[96:102].decode('ascii'), 16)
    filesize = int(header[54:62].decode('ascii'), 16)

    if infile == outfile:
        outfile.seek(-hdrsz, 1)
    outfile.write(header)  # Write the modified header as bytes

    filename = infile.read(((namesize + hdrsz + 3) & ~3) - hdrsz)
    if infile != outfile:
        outfile.write(filename)  # Write the filename as bytes

    filesize = (filesize + 3) & ~3
    if infile != outfile:
        while filesize > 0:
            readsize = min(1048576, filesize)
            outfile.write(infile.read(readsize))
            filesize -= readsize
    else:
        infile.seek(filesize, 1)

    if filename.rstrip(b'\0') == b'TRAILER!!!':  # Compare with byte literal
        if infile != outfile:
            outfile.write(infile.read(1048576))
        break