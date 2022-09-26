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

# Determine what sort of distribution this is
test -e /etc/os-release && os_release='/etc/os-release' || os_release='/usr/lib/os-release'
. "${os_release}"
use_apt=""
use_rpm=""
install_epel=""
case " $ID $ID_LIKE " in
    *" debian "*)
        use_apt="y"
        ;;
    *" rhel "*)
        use_rpm="y"
        install_epel="y"
        epel_release="${VERSION_ID%%.*}"
        ;;
    *" fedora "*)
        use_rpm="y"
        ;;
    *)
        echo "Distro not supported: need a distro based on RedHat(/Fedora) or Debian(/Ubuntu" 1>&2
        exit 1
        ;;
esac



if [ -n "$use_apt" ]; then
    # Debian-based distro
    PKGS=(
        cpio
        createrepo-c
        file
        genisoimage
        gzip
        openssl
        p7zip-full
        python3
        python3-distutils
        python3-pip
        python3-rpm
        rpm
        squashfs-tools
    )
    set -e
    apt-get update
    apt-get install --no-install-recommends -y "${PKGS[@]}"
    if ! test -f /usr/bin/mkisofs; then
        ln -sf /usr/bin/genisoimage /usr/bin/mkisofs
    fi
    PIP_PKGS=(
        dataclasses
        defusedxml
        packaging
        rpm
        PyYAML
    )
    python3 -m pip install -q --user "${PIP_PKGS[@]}"
elif [ -n "$use_rpm" ]; then
    # Red Hat based distro
    PKGS=(
        cpio
        createrepo_c
        file
        genisoimage
        gzip
        openssl
        p7zip-plugins
        python3
        python3-pip
        python3-rpm
        rpm
        squashfs-tools
    )
    set -e
    if [ -n "$install_epel" ]; then
        yum install -y "https://dl.fedoraproject.org/pub/epel/epel-release-latest-${epel_release}.noarch.rpm"
    fi
    yum -y install "${PKGS[@]}"
    PIP_PKGS=(
        dataclasses
        defusedxml
        packaging
        rpm
        PyYAML
    )
    python3 -m pip install -q --user "${PIP_PKGS[@]}"
else
    echo "Distro not supported: only RedHat/Debian-based distros are supported" >&2
    exit 1
fi

