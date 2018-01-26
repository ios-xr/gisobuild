# gisobuild
Golden ISO build tool for ios-xr

usage: gisobuild.py [-h] -i BUNDLE_ISO [-r RPMREPO] [-c XRCONFIG]
[-l GISOLABEL] [-m] [-v]

Utility to build Golden/Custom iso. Please provide atleast repo path or config
file along with bundle iso

optional arguments:
-h, --help show this help message and exit
-r RPMREPO, --repo RPMREPO
Path to RPM repository
-c XRCONFIG, --xrconfig XRCONFIG
Path to XR config file
-l GISOLABEL, --label GISOLABEL
Golden ISO Label
-m, --migration To build Migration tar only for ASR9k
-v, --version Print version of this script and exit

required arguments:
-i BUNDLE_ISO, --iso BUNDLE_ISO
Path to Mini.iso/Full.iso file
