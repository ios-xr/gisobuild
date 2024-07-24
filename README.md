# gisobuild toolkit for IOS-XR

## Usage

```
usage: gisobuild.py [-h] [--iso ISO] [--repo REPO [REPO ...]]
                    [--bridging-fixes BRIDGE_FIXES [BRIDGE_FIXES ...]]
                    [--xrconfig XRCONFIG] [--ztp-ini ZTP_INI] [--label LABEL]
                    [--no-label] [--out-directory OUT_DIRECTORY]
                    [--create-checksum] [--yamlfile CLI_YAML] [--clean]
                    [--pkglist PKGLIST [PKGLIST ...]]
                    [--key-requests KEY_REQUESTS [KEY_REQUESTS ...]]
                    [--script SCRIPT] [--docker] [--x86-only] [--migration]
                    [--optimize] [--full-iso]
                    [--remove-packages REMOVE_PACKAGES [REMOVE_PACKAGES ...]]
                    [--skip-usb-image] [--copy-dir COPY_DIRECTORY]
                    [--clear-bridging-fixes] [--verbose-dep-check] [--debug]
                    [--isoinfo ISOINFO] [--image-script IMAGE_SCRIPT]
                    [--only-support-pids ONLY_SUPPORT_PIDS [ONLY_SUPPORT_PIDS ...]]
                    [--remove-all-key-requests]
                    [--remove-key-requests REMOVE_KEY_REQUESTS [REMOVE_KEY_REQUESTS ...]]
                    [--no-buildinfo] [--version]

Utility to build Golden ISO for IOS-XR.

optional arguments:
  -h, --help            show this help message and exit
  --iso ISO             Path to an input LNT ISO, EXR mini/full ISO, or a
                        GISO.
  --repo REPO [REPO ...]
                        Path to RPM repository. For LNT, user can specify
                        .rpm, .tgz, .tar filenames, or directories. RPMs are
                        only used if already included in the ISO, or specified
                        by the user via the --pkglist option.
  --bridging-fixes BRIDGE_FIXES [BRIDGE_FIXES ...]
                        Bridging rpms to package. For EXR, takes from-release
                        or rpm names; for LNT, the user can specify the same
                        file types as for the --repo option.
  --xrconfig XRCONFIG   Path to XR config file
  --ztp-ini ZTP_INI     Path to user ztp ini file
  --label LABEL, -l LABEL
                        Golden ISO Label
  --no-label            Indicates that no label at all should be added to the
                        GISO
  --out-directory OUT_DIRECTORY
                        Output Directory
  --create-checksum     Write a file with the checksum and size of the output
                        file(s)
  --yamlfile CLI_YAML   Cli arguments via yaml
  --clean               Delete output dir before proceeding
  --pkglist PKGLIST [PKGLIST ...]
                        Packages to be added to the output GISO. For eXR:
                        optional rpm or smu to package. For LNT: either full
                        package filenames or package names for user
                        installable packages can be specified. Full package
                        filenames can be specified to choose a particular
                        version of a package, the rest of the block that the
                        package is in will be included as well. Package names
                        can be specified to include optional packages in the
                        output GISO.
  --key-requests KEY_REQUESTS [KEY_REQUESTS ...]
                        Key requests to package to be used when validating
                        customer and partner RPMs.
  --docker, --use-container
                        Build GISO in container environment.Pulls and run pre-
                        built container image to build GISO.
  --version             Print version of this script and exit

EXR only build options:
  --script SCRIPT       Path to user executable script executed as part of
                        bootup post activate.
  --x86-only            Use only x86_64 rpms even if other architectures are
                        applicable.
  --migration           To build Migration tar only for ASR9k
  --optimize            Optimize GISO by recreating and resigning initrd
  --full-iso            To build full iso only for xrv9k

LNT only build options:
  --remove-packages REMOVE_PACKAGES [REMOVE_PACKAGES ...]
                        Remove RPMs, specified in a space separated list.
                        These are matched against user installable package
                        names, and must be the whole package name, e.g: xr-bgp
  --skip-usb-image      Do not build the USB image
  --copy-dir COPY_DIRECTORY
                        Copy built artefacts to specified directory if
                        provided. The specified directory must already exist,
                        be writable by the builder and must not contain a
                        previously built artefact with the same name.
  --clear-bridging-fixes
                        Remove all bridging bugfixes from the input ISO
  --verbose-dep-check   Verbose output for the dependency check.
  --debug               Output debug logs to console
  --isoinfo ISOINFO     User specified isoinfo executable to use instead of
                        the default version
  --image-script IMAGE_SCRIPT
                        User specified image.py script to be used for
                        packing/unpacking instead of the version extracted
                        from the ISO. It will not be inserted into the GISO.
                        Intended for debugging purposes only.
  --only-support-pids ONLY_SUPPORT_PIDS [ONLY_SUPPORT_PIDS ...]
                        Support only these hardware PIDs in the output ISO
                        (e.g. '8800-RP' '8800-LC-36FH' '8800-LC-48H'); other
                        PIDs from the input ISO will be removed. This option
                        is generally used to reduce the size of the output
                        ISO. Do not use this option before discussing with
                        Cisco support.
  --remove-all-key-requests
                        Remove all key requests from the input ISO
  --remove-key-requests REMOVE_KEY_REQUESTS [REMOVE_KEY_REQUESTS ...]
                        Remove key requests, specified in a space separated
                        list. These are matched against the filename, e.g.
                        key_request.kpkg
  --no-buildinfo        Do not update the build metadata in mdata.json with
                        the GISO build information

```

## Description

Typically, Cisco releases IOS-XR software as a mini/base ISO, which contains
mandatory IOS-XR packages for a given platform and, separately, a set of
optional packages and software patches for any bug fixes (SMU).
Optional packages and SMUs are in RPM packaging format.

The Golden ISO tool creates an ISO containing the full contents of
the mini/base ISO, together with optional packages and SMU of the user's
choice. Once the Golden ISO is created, it can be used either for iPXE booting
a router or for SU (system upgrade) from the current running version to
a new version of IOS-XR.


### Reducing ISO size

The tool also supports the creation of an ISO with certain hardware PIDs
removed (via `--only-support-pids`), which can be used to reduce the size of
the ISO. This option should be used with the following considerations:

- The list of PIDs to support must all be supported by the input ISO. You can
  check the supported PIDs with the `isols.py --dump-mdata` command.
- If a distributed Route Processor PID is specified, then you must also specify
  a distributed Line Card to support (and vice versa), otherwise the system
  may not boot. Again, `isols.py --dump-mdata` can give you information about a
  PID's card class.
- Once support for a PID has been removed from an image, support cannot be
  re-added to the output ISO - it's a one-way operation.
- You should only remove support for hardware PIDs that you know won't ever be
  present in the system that the GISO is intended for. Using such a GISO on a
  system with unsupported hardware PIDs can lead to the system being unbootable.

With this in mind, it is not recommended to use this option unless you have
discussed it with Cisco support.

### Key requests

Key requests (AKA key packages) that should be onboarded for validating owner
and partner RPMs can be specified using the `--key-requests <file1> <file2>`
argument and removed using `--remove-all-key-requests` or
`--remove-key-requests <file1> <file2>`.

For instructions on creating and verifying key requests, see the
[key-package-scripts repo](https://github.com/ios-xr/key-package-scripts/tree/master).

## Requirements

This tool has the following executable requirements:
* python3 >= 3.6
* rpm >= 4.14
* cpio >= 2.10
* gzip >= 1.9
* createrepo_c
* file
* isoinfo
* mkisofs
* mksquashfs
* openssl
* unsquashfs
* 7z (Optional - but functionality may be reduced without)
* iso-read (Optional - but functionality may be reduced without)
* zip (Optional - but functionality may be reduced without)
* unzip (Optional - but functionality may be reduced without)

It also requires the following Python (>= 3.6) modules:
* dataclasses
* defusedxml
* distutils
* packaging
* rpm
* yaml

## Invocation

This tool can be run natively on a Linux host if the dependencies above are met.
Alternatively, the tool can also be run on a Linux system with Docker enabled
and the ability to pull the published 'cisco-xr-gisobuild' image from Docker
Hub, in which case the above dependencies are met by the published image.

To run natively on a Linux host, the following distributions have been tested.
* Alma Linux 8
* Fedora 34
* Debian 11.2

On a native Linux system, which does not have all dependencies met,
the tool dependencies can be installed on supported distributions above
by running the following command (possibly via sudo)
              
    ./setup/prep_dependency.sh

To load and run the pre-built cisco-xr-gisobuild docker image, ensure that the
docker service is enabled and it's possible to pull and run published docker
images.

Run the following command to check docker service parameters.

    docker info

Running the tool:

To run natively on a linux host which has dependency requirements met:

    ./src/gisobuild.py --iso <input iso> --repo <rpm repo1 rpm_repo2> \
        --pkglist <pkg1 pkg2 pkg3> --bridging-fixes <smu1 smu2 smu3> \
        --xrconfig <config.cfg> --ztp-ini <ztp.ini> --script <user_script.sh> \
        --label <label> --out-directory <out_directory> --clean

The tool has a helpful usage info which lists down the options supported.

When user does not want to specify the inputs via cli, an alternate would be to populate the yaml file template
provided in the toolkit and pass the same via:

    ./src/gisobuild.py --yamlfile <input_yaml_cfg>

To override any input in the yaml config file, please use the corresponding cli option and parameter.

    ./src/gisobuild.py --yamlfile <input_yaml_cfg> --label <new_label>

The above command will override the label specified in yaml file with new option provided via cli option --label.

When the host machine does not have its dependency met, but allows pulling and running docker images, enable 
docker option in yaml file to true and run as (possible with GISO for eXR variants of IOS-XR):

    ./src/gisobuild.py --yamlfile <input_yaml_cfg>

where input_yaml_cfg has:

    docker: true

Output:

The corresponding GISO and build logs are available under the directory
specified in `--out-directory`. The default if not specified is
`<pwd>/output_gisobuild`.

### Tips

#### Specifying LNT bugfixes and packages

> In the context of the LNT gisobuild tool, and LNT install operations, an XR
package name refers to the "user installable" RPM and is the string prefix
common to all RPMs associated with a block.

You can put all your bugfixes and any optional packages in the same repository,
and pass that to the CLI using the `--repo` flag. The tool will pick the correct
RPMs to add to the GISO using the following logic:

1. If no packages are specified via the `--pkglist` flag, then the latest
of any packages in the repository that upgrade packages already in the input ISO
will be included in the output GISO. Other optional packages, including those
part of bugfixes that were incorporated into the GISO, will not be added to the
output GISO.
1. If any optional package names are given via the `--pkglist` flag, where the
package is not part of the input ISO, the latest version of the package in the
specified repository will be added to the output GISO. For XR packages all other
RPMs in the same block will also be added to the output GISO.
1. If full package filenames are given via the `--pkglist` flag, the specific
version passed in will be included in the output GISO. If the package is part of
a block, then all the packages in the block are added.

Note that to specify a package in the way described by option 2, you just need
to give the beginning part of the RPM filename that provides the package name,
for example, if you have the following RPMs:

```text
$ ls /path/to/repo/optional-rpms/cdp/
xr-cdp-0deb3755978fea2a-24.3.1v1.0.0-1.x86_64.rpm*
xr-cdp-1b7551b6d2623937-24.3.1v1.0.0-1.x86_64.rpm*
xr-cdp-24.3.1v1.0.0-1.x86_64.rpm*
xr-cdp-734eb3104a06f199-24.3.1v1.0.0-1.x86_64.rpm*
xr-cdp-8101-32h-24.3.1v1.0.0-1.x86_64.rpm*
<snip>
```

instead of specifying each one, you can just run the gisobuild command as shown
below:

```text
./gisobuild.py --iso /path/to/iso/8000-x64-24.1.2.iso --repo /path/to/repo/ --pkglist xr-cdp
```

Note that you do not need to provide the whole file name, or manually filter the
RPMs added to the provided repository, as the script will do this for you.

Regardless of what specific PIDs your devices include it is the default to
include all RPMs in the GISOs built so there is no need to try to select for
particular PIDs. You can create the GISO with the full set of RPMs, and when you
come to installing the GISO on your router, the correct packages for the PIDs
available will be installed, and any unsuitable ones will be ignored.

Bugfixes can be included in the same repository as your packages.

```text
$ ls /path/to/repo/bugfixes/
8000-x64-24.3.1-CSCab12345.tar.gz
8000-x64-24.3.1-CSCzy54321.tar.gz
```

They do not need to be manually unpacked before building the GISO. Any bugfixes
present in the given repository will be included in the GISO without needing to
specify them.

```text
./gisobuild.py --iso /path/to/iso/8000-x64-24.3.1.iso --repo /path/to/repo/
```

Both RPMs and bugfixes can included in the GISO in a single command, as long as
they are all in the repository. So the command above would also work if my
repository looked like:

```text
$ tree /path/to/repo/
/path/to/repo/
├── bugfixes
│   ├── 8000-x64-24.3.1-CSCab12345.tar.gz
│   ├── 8000-x64-24.3.1-CSCzy54321.tar.gz
│   ...
└── optional-rpms
    ├── cdp
    │   ├── xr-cdp-0deb3755978fea2a-24.3.1v1.0.0-1.x86_64.rpm*
    │   ├── xr-cdp-1b7551b6d2623937-24.3.1v1.0.0-1.x86_64.rpm*
    │   ├── xr-cdp-24.3.1v1.0.0-1.x86_64.rpm*
    │       ...
    ├── telnet
    │   ├── xr-telnet-0deb3755978fea2a-24.3.1.22Iv1.0.0-1.x86_64.rpm
    │   ├── xr-telnet-24.3.1.22Iv1.0.0-1.x86_64.rpm
    │       ...
        ...

## Note: older version of the tool

The legacy eXR python2-based gisobuild utility is available at:

 https://github.com/ios-xr/gisobuild/tree/gisobuild-exr-legacy

The command to pull the above code base is:

    git clone  --branch gisobuild-exr-legacy https://github.com/ios-xr/gisobuild/
