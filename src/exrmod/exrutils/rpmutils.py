# -----------------------------------------------------------------------------

""" Utility functions towards running rpm commands.

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

import re
import os
import functools
try:
    from itertools import zip_longest
except ImportError:
    from itertools import izip_longest as zip_longest
_subfield_pattern = re.compile(
    r'(?P<junk>[^a-zA-Z0-9]*)((?P<text>[a-zA-Z]+)|(?P<num>[0-9]+))'
)

def _iter_rpm_subfields(field):
    for subfield in _subfield_pattern.finditer(field):
        text = subfield.group('text')
        if text is not None:
            yield (0, text)
        else:
            yield (1, int(subfield.group('num')))

def _compare_rpm_field(lhs, rhs):
    # Short circuit for exact matches (including both being None)
    if lhs == rhs:
        return 0
    # Otherwise assume both inputs are strings
    lhs_subfields = _iter_rpm_subfields(lhs)
    rhs_subfields = _iter_rpm_subfields(rhs)
    for lhs_sf, rhs_sf in zip_longest(lhs_subfields, rhs_subfields):
        if lhs_sf == rhs_sf:
            # When both subfields are the same, move to next subfield
            continue
        if lhs_sf is None:
            # Fewer subfields in LHS, so it's less than/older than RHS
            return -1
        if rhs_sf is None:
            # More subfields in LHS, so it's greater than/newer than RHS
            return 1
        # Found a differing subfield, so it determines the relative order
        return -1 if lhs_sf < rhs_sf else 1
    # No relevant differences found between LHS and RHS
    return 0

def compare_rpm_ver (v1, v2):
    return _compare_rpm_field (v1, v2)

'''
    Remove base package dependency for Cisco rpms.    
'''
def sanitize_reqs_rpm (rpmfile, repomdata, rel, platform):
    requires = []
    provides = []
    for rpmdata in repomdata:
        rpm2check = os.path.basename (rpmfile)
        if rpmdata.file_name == rpm2check:
            provides.extend (rpmdata.provides.strip().split ('\n'))
            for reqs in rpmdata.requires:
                if reqs and is_tp_rpm (platform, reqs):
                    continue
                # Cisco packages have dependency of type <pkg_name> <=> <d.d.d.d>
                if reqs and reqs.split()[1] == '=':
                    req_pkg_name, req_pkg_ver =  \
                           re.search(r'(.*) = ([0-9]*.[0-9]*.[0-9]*.[0-9]*[a-zA-Z]?).*', reqs).groups()
                    # For sysadmin, base package version is same as release number.
                    if 'sysadmin' in req_pkg_name and \
                           "r{}".format(''.join(req_pkg_ver.split('.'))) \
                           == rel:
                        continue
                    # For XR, base packages will have 4th digit as 0.
                    last_digit = re.search (r'[0-9]*.[0-9]*.[0-9]*.(.*)', req_pkg_ver).groups()[0]
                    if last_digit == '0':
                        continue
                                    
                    if reqs not in requires:
                        requires.append (reqs)
    return requires, provides

'''
    Given List of Rpm() objects, check which rpm provides a needed requires.
'''
def whatprovides (reqstr, repodata):
    for rpmdata in repodata:
        provides = rpmdata.provides.strip().split ('\n')
        for prov in provides:
            prov_pkg_name, prov_pkg_ver =  \
                    re.search(r'(.*) = ([0-9]*.[0-9]*.[0-9]*.[0-9]*[a-zA-Z]?.*)-.*', prov).groups()
            provstr = "{} = {}".format (prov_pkg_name, prov_pkg_ver)
            if reqstr == provstr:
                return rpmdata
    return None

'''
    Remove reqs being met with provides of considered rpms.
'''
def get_unresolved_reqs (requires, provides):
    unresolved_reqs = optimise_reqlist (requires)
    for reqs in optimise_reqlist(requires):
        req_pkg_name, req_pkg_ver =  \
                         re.search(r'(.*) = ([0-9]*.[0-9]*.[0-9]*.[0-9]*[a-zA-Z]?).*', reqs).groups()
        for prov in provides:
            prov_pkg_name, prov_pkg_ver =  \
                              re.search(r'(.*) = ([0-9]*.[0-9]*.[0-9]*.[0-9]*[a-zA-Z]?).*', prov).groups()
            if req_pkg_name == prov_pkg_name and req_pkg_ver == prov_pkg_ver:
                unresolved_reqs.remove(reqs)
                break
    return unresolved_reqs

'''
    Remove superseded requires given a list of required caps.
'''
def optimise_reqlist (requires):
    reqList = sorted (requires, key = functools.cmp_to_key(compare_rpm_ver), reverse=True)
    pkgconsidered = []
    totalreqs = []
    for reqs in reqList:
        req_pkg_name, req_pkg_ver =  \
              re.search(r'(.*) = ([0-9]*.[0-9]*.[0-9]*.[0-9]*[a-zA-Z]?).*', reqs).groups()
        if req_pkg_name not in pkgconsidered:
            pkgconsidered.append (req_pkg_name)
            totalreqs.append (reqs)
        else:
            continue
    return totalreqs
def is_cisco_rpm (platform, rpmfile):
    return (platform in rpmfile)

def is_tp_rpm (platform, rpmfile):
    return not is_cisco_rpm (platform, rpmfile)
   
 
