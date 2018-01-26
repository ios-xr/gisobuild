# gisobuild
Golden ISO build tool for ios-xr

usage: gisobuild.py [-h] -i BUNDLE_ISO [-r RPMREPO] [-c XRCONFIG]
[-l GISOLABEL] [-m] [-v]

Utility to build Golden/Custom iso. Please provide atleast repo path or config
file along with bundle iso

```
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
```

Required arguments:
```
-i BUNDLE_ISO / --iso BUNDLE_ISO  
```

Where BUNDLE_ISO= Path to Mini.iso/Full.iso file  


## Golden ISO tool (GISO):

Typically Cisco releases IOS-XR software as mini ISO which contains mandatory IOS-XR packages for a given platform, set of optional packages as RPMs and software patches for any fixes/enhancement in in release mini ISO and optional packages. Optional package and SMU are in RPM packaging format.

Customer asked for single image to avoid complexity and confusion of many packages and to server this Cisco have release full iso, but now the complexity is there are difference in requirement of optional packages for different customer , single full ISO is not applicable for all customers , also there are SMUs which gets release as and when there is enhancement or fix for any mandatory and optional packages. Inserting these SMUs in full ISO is not possible.

To solve this Golden ISO / Custom ISO tool is develloped which can be used on customers site on any linux machine to create ISO with mini image and optional package and SMUs of his choice. Once ISO is created it can be used for iPXE booting router or SU (system upgrade) from any version to another version.



How to create the custom ISO/ Golden ISO :

Tool will be available on router which needs to copied to a linux machine where golden ISO needs to be created. Technically golden ISO can be created on router but due to resource disk/ram and CPUs available are not sufficient , golden ISO creation on router is not supported.

Requirement on Linux machine for creating golden ISO is following utilities :

Python 2.6 or higher version
chroot,
mount
mkiso
zcat
Atleast 6 GB of free disk space , 1 GB RAM is needed on linux machine where ISO is being created
RPM version 5.x is required to be installed



/pkg/bin/Gisobuild.py will be available in RPs(RSPs) IOS-XR. XR's or Linux copy command can be used to

copy this tool to linux machine. The tool will have help message for it's usage info.

