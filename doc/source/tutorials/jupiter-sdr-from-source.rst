Jupiter SDR with u-boot and BL31 from source
============================================

``jupiter_sdr`` is a ZynqMP SOM design with no carrier board. This tutorial
builds it with the :doc:`hdl-boot </targets/hdl-boot>` target, which compiles
u-boot and Arm Trusted Firmware in the same workspace before Vivado runs, so
the resulting ``BOOT.BIN`` contains no downloaded binaries.

Requirements
------------

- Vivado 2025.1 with Vitis (``hdl_2026_r1`` is validated against it).
- ``gcc-aarch64-linux-gnu`` and the u-boot host build dependencies —
  installed by ``--install`` below.

1. Create the workspace
-----------------------

.. code-block:: bash

   GIT_LFS_SKIP_SMUDGE=1 cim init --target hdl-boot \
       --source https://github.com/tfcollins/datax-manifests.git \
       --workspace ~/cim-jupiter --install
   cd ~/cim-jupiter
   cim makefile

Three repositories are cloned: ``hdl/`` (at ``hdl_2026_r1``), ``u-boot-xlnx/``
and ``arm-trusted-firmware/``. The generated Makefile has
``sdk-build: u-boot-xlnx arm-trusted-firmware``.

2. See what will be built
-------------------------

.. code-block:: bash

   make boot-dry-run HDL_PROJECT=jupiter_sdr

::

   u-boot-xlnx build
     Board:         jupiter_sdr
     Ref:           jupiter-sdr
     Defconfig:     xilinx_zynqmp_virt_defconfig
     DEVICE_TREE:   zynqmp-jupiter-sdr
     CROSS_COMPILE: aarch64-linux-gnu-
   arm-trusted-firmware build
     PLAT:          zynqmp
     Ref:           xilinx-v2025.1

Everything was derived from the project: the u-boot preset comes from the
design name (Jupiter's u-boot lives on ADI's ``jupiter-sdr`` branch), the ATF
platform from the device in ``system_project.tcl`` (``xczu3eg`` → ZynqMP) and
its tag from the Vivado release. ``HDL_BOARD`` is not needed and is ignored
if set.

Confirm the host can compile u-boot before starting:

.. code-block:: bash

   bash scripts/build-uboot.sh --board jupiter_sdr --check-deps

3. Build
--------

.. code-block:: bash

   make sdk-build HDL_PROJECT=jupiter_sdr

In order: ``make boot-uboot`` (~2 min, ``u-boot-xlnx/u-boot.elf``),
``make boot-atf`` (~10 s, ``arm-trusted-firmware/bl31.elf``), then the Vivado
build and ``build_zynqmp_boot_bin.sh`` — FSBL and PMUFW generated from the XSA
with ``xsct``, then ``bootgen`` packs FSBL + PMUFW + bitstream + BL31 + u-boot.

Or interactively: ``make guide``, pick ``jupiter_sdr``, accept BOOT.BIN and
"from source" — the wizard shows the same resolution and runs this command.

4. Results
----------

::

   u-boot-xlnx/u-boot.elf
   arm-trusted-firmware/bl31.elf
   hdl/projects/jupiter_sdr/build/jupiter_sdr.sdk/system_top.xsa
   hdl/projects/jupiter_sdr/output_boot_bin/BOOT.BIN

Variations
----------

- Fall back to ADI's prebuilt u-boot for one build:
  ``make sdk-build HDL_PROJECT=jupiter_sdr BOOT_BIN_UBOOT=download BOOT_BIN_ATF=download``.
- A ZynqMP carrier design works the same way:
  ``make sdk-build HDL_PROJECT=fmcomms2 HDL_BOARD=zcu102`` (u-boot from the
  ``xlnx_rebase_v2025.01_2025.1`` tag, ``zynqmp-zcu102-rev1.0`` device tree).
- Build only the boot components, no Vivado: use the standalone
  :doc:`u-boot-xlnx </targets/u-boot-xlnx>` and
  :doc:`arm-trusted-firmware </targets/arm-trusted-firmware>` targets — they
  need no EDA tools and run on any x86 host.
