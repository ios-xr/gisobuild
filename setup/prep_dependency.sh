#!/bin/bash

# Install distro and Python packages required by the GISO tool
# for Debian and Red Hat based distros
#
# Copyright (c) 2022 Cisco and/or its affiliates.
#
# This software is licensed to you under the terms of the Cisco Sample
# Code License, Version 1.1 (the "License"). You may obtain a copy of the
# License at
#
#                https://developer.cisco.com/docs/licenses
#
# All use of the material herein must be in accordance with the terms of
# the License. All rights not expressly granted by the License are
# reserved. Unless required by applicable law or agreed to separately in
# writing, software distributed under the License is distributed on an "AS
# IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
# or implied.
#
if command -v apt-get >/dev/null; then
    # Debian-based distro
    PKGS=(
        cpio
        createrepo-c
        file
        genisoimage
        openssl
        python3
        python3-defusedxml
        python3-distutils
        python3-packaging
        python3-rpm
        python3-yaml
        rpm
        squashfs-tools
    )
    set -e
    apt-get update
    apt-get install --no-install-recommends -y "${PKGS[@]}"
    if ! test -f /usr/bin/mkisofs; then
        ln -sf /usr/bin/genisoimage /usr/bin/mkisofs
    fi
elif command -v yum >/dev/null; then
    # Red Hat based distro
    PKGS=(
        cpio
        createrepo_c
        file
        genisoimage
        libcdio
        openssl
        python3
        python3-pip
        python3-rpm
        rpm
        squashfs-tools
    )
    set -e
    yum -y install "${PKGS[@]}"
    python3 -m pip install -q --user PyYAML defusedxml dataclasses packaging
else
    echo "Distro not supported: neither apt-get nor yum found" >&2
    exit 1
fi

