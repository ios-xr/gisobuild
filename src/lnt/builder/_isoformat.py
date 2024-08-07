# -----------------------------------------------------------------------------

""" Constants describing the (unpacked) ISO format

Copyright (c) 2022 Cisco and/or its affiliates.
This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at

        https://developer.cisco.com/docs/licenses

All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.

"""

__all__ = (
    "get_installable_groups",
    "PackageGroup",
)

import dataclasses
import enum
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .. import gisoutils, lnt_gisoglobals


@dataclasses.dataclass(frozen=True)
class GroupAttribute:
    """
    An attribute that may be associated with a group
    """

    name: str
    essential: bool
    message: str = ""
    value: Optional[str] = None

    def to_json(self) -> str:
        """
        Return the JSON string to be stored in this attribute's ".attr.json"
        file.
        """
        value = {
            "name": self.name,
            "type": "essential" if self.essential else "informational",
            "value": self.value,
            "message": self.message,
        }
        return json.dumps(value)


ATTR_INSTALL = GroupAttribute(
    "install",
    True,
    "This software can only be installed on versions of IOS XR that support installing software",
)
ATTR_BMC = GroupAttribute("bmc", False)
ATTR_OWNER_PKGS = GroupAttribute("owner_packages", False)
ATTR_PARTNER_PKGS = GroupAttribute("partner_packages", False)
ATTR_BRIDGING = GroupAttribute("bridging", False)
ATTR_PRIORITY = GroupAttribute(
    "priority",
    True,
    "This software can only be installed on versions of IOS XR that support priority installation",
)
ATTR_KEY_PACKAGES = GroupAttribute("key_packages", True)


INSTALLABLE_PKG_GROUP_ATTRS = [
    ATTR_INSTALL.name,
    ATTR_OWNER_PKGS.name,
    ATTR_PARTNER_PKGS.name,
]


def get_installable_groups(groups_mdata: List[Dict[str, Any]]) -> Set[str]:
    """
    Return the set of names for the installable package groups.

    :param groups_mdata:
        ISO groups metadata, as returned from query-content.

    :returns:
        Set of names of installable groups.
    """
    installable_groups = set()
    for attr in INSTALLABLE_PKG_GROUP_ATTRS:
        installable_groups.update(
            gisoutils.get_groups_with_attr(groups_mdata, attr)
        )
    return installable_groups


class PackageGroup(enum.Enum):
    """
    Groups into which we put packages in the ISO
    """

    INSTALLABLE_XR_PKGS = ("main", True, {ATTR_INSTALL, ATTR_BMC})
    INSTALLABLE_OWNER_PKGS = ("owner", False, {ATTR_OWNER_PKGS})
    INSTALLABLE_PARTNER_PKGS = ("partner", False, {ATTR_PARTNER_PKGS})
    KEY_PKGS = ("keys", False, {ATTR_KEY_PACKAGES})
    BRIDGING_PKGS = ("bridging", False, {ATTR_BRIDGING, ATTR_PRIORITY})

    def __init__(
        self,
        group_name: str,
        verify_signatures: bool,
        attributes: Set[GroupAttribute],
    ):
        self.group_name = group_name
        self.verify_signatures = verify_signatures
        self.attributes = attributes | {
            GroupAttribute("name", False, "", group_name)
        }


# ------------------------------------------------------------------------------
# Paths to elements of the unpacked ISO

ISO_PATH_GROUPS = "groups"
ISO_GROUP_PKG_DIR = "groups/group.{}/packages"
ISO_GROUP_ATTR_DIR = "groups/group.{}/attributes"
ISO_GROUP_ATTR_FILE = "groups/group.{}/attributes/{}.attr.json"

ISO_PATH_MISC = Path("misc")

# Path to the optional ztp.ini config file
ISO_PATH_ZTP = str(ISO_PATH_MISC / "ztp.ini")

# Path to the initial configuration file
ISO_PATH_INIT_CFG = str(ISO_PATH_MISC / "config")

# Path to the label
ISO_PATH_LABEL = str(ISO_PATH_MISC / "label")

# Path to mdata.json (including old 7.5.1 location)
ISO_PATH_MDATA_751 = "private/mdata/mdata.json"
ISO_PATH_MDATA = str(ISO_PATH_MISC / lnt_gisoglobals.LNT_MDATA_PATH)

# Path to build-info.txt
ISO_PATH_BUILDINFO = str(ISO_PATH_MISC / lnt_gisoglobals.LNT_BUILDINFO_PATH)

# ------------------------------------------------------------------------------
# Significant 'provides' tags / package names

CISCO_PID_PREFIX = "cisco-pid-"
CISCO_CARD_TYPE_PREFIX = "cisco-card-type-"
XR_FOUNDATION = "xr-foundation"

# ------------------------------------------------------------------------------
# Card types
LC_CARD_TYPES = {"lc-distributed"}
RP_CARD_TYPES = {"rp-distributed", "rplc-centralized", "rplc-sff"}

CARD_CLASS_READABLE = {
    "lc-distributed": "Line Card (modular)",
    "rp-distributed": "Route Processor (modular)",
    "rplc-centralized": "Centralized form factor",
    "rplc-sff": "Fixed form factor",
}
