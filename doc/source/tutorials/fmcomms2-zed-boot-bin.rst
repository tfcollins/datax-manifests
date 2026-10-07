FMCOMMS2 on ZedBoard with a BOOT.BIN
====================================

The classic Zynq-7000 flow: build ``fmcomms2`` for the ``zed`` carrier from
the ``hdl_2023_r2`` release with Vivado 2023.2 and produce a bootable
``BOOT.BIN`` using ADI's prebuilt u-boot. Uses the :doc:`hdl </targets/hdl>`
target.

Requirements
------------

- Vivado 2023.2 (``/opt/Xilinx/Vivado/2023.2`` or ``/opt/Xilinx/2023.2/Vivado``)
  with Vitis — the BOOT.BIN step needs ``xsct`` and ``bootgen``.
- `cim`_ on ``PATH``.

1. Create the workspace
-----------------------

.. code-block:: bash

   cim init --target hdl --source https://github.com/tfcollins/datax-manifests.git \
            --workspace ~/cim-fmcomms2 --install
   cd ~/cim-fmcomms2
   cim makefile

``--install`` installs the host packages from ``os-dependencies.yml``
(``unzip``, ``wget``, cross compilers for the BOOT.BIN helpers). If your host
has ``git-lfs``, prefix the init with ``GIT_LFS_SKIP_SMUDGE=1`` — the hdl
repository has documentation images in LFS that are missing upstream.

2. Check the tools and the matrix
---------------------------------

.. code-block:: bash

   make check-tools HDL_RELEASE=hdl_2023_r2
   make list-boards HDL_PROJECT=fmcomms2 HDL_RELEASE=hdl_2023_r2

The first command switches ``hdl/`` to the ``hdl_2023_r2`` branch and reports
which Vivado it resolved::

   Checking EDA Tool Installation Status (release: hdl_2023_r2):
     - Vivado version:  2023.2 (/opt/Xilinx/Vivado/2023.2)
     - Xilinx Vivado:   Found (at /opt/Xilinx/Vivado/2023.2)

The second lists ``zed`` among the carriers, all Vivado.

3. Dry-run, then build
----------------------

.. code-block:: bash

   bash scripts/build-hdl.sh --release hdl_2023_r2 --project fmcomms2 --board zed --boot-bin --dry-run
   make sdk-build HDL_RELEASE=hdl_2023_r2 HDL_PROJECT=fmcomms2 HDL_BOARD=zed BUILD_BOOT_BIN=true

The dry-run prints the three commands the build will execute — sourcing
``settings64.sh``, the project ``make``, and ``build_boot_bin.sh`` — so you
can see the resolved paths before committing an hour of synthesis. The real
build takes 30–60 minutes on a workstation; run it in the background.

The equivalent interactive path is ``make guide``: choose ``hdl_2023_r2``,
``fmcomms2``, ``zed``, answer ``y`` to BOOT.BIN, and the wizard prints the same
``make`` line before running it.

4. Results
----------

::

   hdl/projects/fmcomms2/zed/build/fmcomms2_zed.sdk/system_top.xsa
   hdl/projects/fmcomms2/zed/output_boot_bin/BOOT.BIN

Copy ``BOOT.BIN`` to the FAT partition of a Kuiper SD card alongside the
kernel and device tree for ``zynq-zed-adv7511-ad9361-fmcomms2-3``.

Variations
----------

- Another ZedBoard design: ``HDL_PROJECT=ad9361_fmc HDL_BOARD=zed`` — same
  carrier, same u-boot download.
- Your own u-boot: ``BOOT_BIN_UBOOT=/path/to/u-boot.elf``.
- Clean: ``make sdk-clean HDL_RELEASE=hdl_2023_r2 HDL_PROJECT=fmcomms2 HDL_BOARD=zed``.

.. _cim: https://github.com/analogdevicesinc/cim
