#!/usr/bin/env python3

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