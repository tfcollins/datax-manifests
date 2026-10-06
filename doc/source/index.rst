DataX build manifests
=====================

**DataX** is Analog Devices' integrated stack for getting data out of a signal
chain and into an application: one hardware-abstraction API (`libiio`_) with
Python, MATLAB, ROS 2 and GNU Radio bindings on top, so the same application
code runs whether the converter hangs off a laptop over USB or sits next to an
FPGA on a Zynq board. Underneath that API are the pieces that have to be
*built* for a given board — FPGA reference designs, boot firmware and the
Linux kernel. This repository is where those builds are defined.

`cim`_ turns each target here into a ready-to-build workspace: it clones the
pinned source trees, installs host dependencies, copies in the build helpers
and generates a ``Makefile`` whose variables select release, project, board
and platform at build time.

.. code-block:: bash

   cim init --source https://github.com/tfcollins/datax-manifests.git -t hdl-boot --workspace ~/cim-jupiter --install
   cd ~/cim-jupiter && cim makefile
   make guide                                 # interactive: release → project → board → BOOT.BIN
   make sdk-build HDL_PROJECT=jupiter_sdr     # u-boot + BL31 + Vivado + BOOT.BIN, all from source

Where these targets sit in the stack
------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 22 38 40

   * - DataX layer
     - What it is
     - Built by
   * - 7 · Applications
     - Scopy, IIO Oscilloscope, MATLAB toolboxes
     - —
   * - 6 · Language bindings
     - `pyadi-iio`_, MATLAB, C/C++
     - —
   * - 5 · Libraries
     - `libiio`_ / iiod — local, USB, network, serial backends
     - —
   * - 4 · Drivers
     - Linux IIO drivers for 1500+ ADI parts
     - :doc:`adi-linux <targets/adi-linux>` — pinned ``analogdevicesinc/linux`` kernels for Zynq / ZynqMP
   * - 3 · HDL & firmware
     - `ADI HDL`_ FPGA reference designs, boot firmware
     - :doc:`hdl <targets/hdl>`, :doc:`hdl-boot <targets/hdl-boot>`, :doc:`u-boot-xlnx <targets/u-boot-xlnx>`, :doc:`arm-trusted-firmware <targets/arm-trusted-firmware>`
   * - 2 · Hardware interface
     - Zynq-7000, Zynq UltraScale+, Versal, Intel SoC, Lattice carriers
     - selected per target (``HDL_BOARD``, ``KERNEL_PLATFORM``)
   * - 1 · Hardware
     - ADCs, DACs, RF transceivers (AD9361, AD9081, ADRV9002, …)
     - selected per target (``HDL_PROJECT``)

Everything above layer 4 consumes what these targets produce: a bitstream /
XSA and BOOT.BIN to boot the board, a kernel image for `pyadi-dt`_ and
hardware-in-the-loop testing, with the IIO devices then visible to libiio and
pyadi-iio over any backend.

Targets
-------

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Target
     - Produces
   * - :doc:`hdl <targets/hdl>`
     - Any `ADI HDL`_ project/carrier for Vivado, Quartus or Radiant. ``HDL_RELEASE``
       picks the branch/tag and the matching Vivado; guided wizard and
       project/board matrix inspection; optional BOOT.BIN from ADI's prebuilt
       u-boot.
   * - :doc:`hdl-boot <targets/hdl-boot>`
     - ``extends: hdl`` — the same workspace with ``u-boot-xlnx`` and
       ``arm-trusted-firmware`` built from source first, so the BOOT.BIN has
       no downloaded blobs.
   * - :doc:`u-boot-xlnx <targets/u-boot-xlnx>`
     - ``u-boot.elf`` for ADI / AMD Zynq boards from ``analogdevicesinc/u-boot-xlnx``
       (``UBOOT_BOARD`` presets). No EDA tools needed.
   * - :doc:`arm-trusted-firmware <targets/arm-trusted-firmware>`
     - ``bl31.elf`` for ZynqMP / Versal, tag matched to the Vivado release.
   * - :doc:`adi-linux <targets/adi-linux>`
     - Kernel-only ``uImage`` / ``Image`` from checksum-pinned source and
       toolchains, publishing an ``artifacts.json`` contract for consumers.

Every target works with upstream `cim`_ — no fork — and is exercised in CI
against the pinned cim release: u-boot and BL31 compile on hosted runners,
the HDL targets on a self-hosted Vivado host.

How a build is selected
-----------------------

The ``gits:`` pins in a manifest are only the starting checkout. The release
you actually build is a make variable, and the helper scripts switch the
clone to it, derive the right tool version, and reject a dirty worktree:

.. code-block:: bash

   make list-combos HDL_RELEASE=hdl_2023_r2            # hdl/ → hdl_2023_r2, Vivado 2023.2
   make sdk-build  HDL_RELEASE=hdl_2023_r2 HDL_PROJECT=fmcomms2 HDL_BOARD=zed BUILD_BOOT_BIN=true
   make sdk-build  KERNEL_RELEASE=2026_R1 KERNEL_PLATFORM=zynqmp     # adi-linux

The u-boot and ATF refs follow the same release (Xilinx reference boards
track ``xlnx_rebase_*`` / ``xilinx-v*`` tags; ADI SOM designs such as
``jupiter_sdr`` pin their own branches), so ``hdl-boot`` only ever asks for
the HDL release, project and board.

.. toctree::
   :maxdepth: 1
   :caption: Targets
   :hidden:

   targets/hdl
   targets/hdl-boot
   targets/u-boot-xlnx
   targets/arm-trusted-firmware
   targets/adi-linux

.. toctree::
   :maxdepth: 1
   :caption: Repository
   :hidden:

   repository

Related DataX projects
----------------------

- `cim`_ — the workspace/manifest tool these targets are written for
- `ADI HDL`_ — FPGA reference designs built by the ``hdl`` targets
- `analogdevicesinc/linux`_ — the kernel built by ``adi-linux``
- `libiio`_ and `pyadi-iio`_ — the API and Python bindings that sit on top
- `pyadi-dt`_ — device-tree generation; consumes ``adi-linux`` artifacts
- `wiki-scripts`_ — source of the BOOT.BIN helper scripts

.. _cim: https://github.com/analogdevicesinc/cim
.. _ADI HDL: https://github.com/analogdevicesinc/hdl
.. _analogdevicesinc/linux: https://github.com/analogdevicesinc/linux
.. _libiio: https://github.com/analogdevicesinc/libiio
.. _pyadi-iio: https://github.com/analogdevicesinc/pyadi-iio
.. _pyadi-dt: https://github.com/analogdevicesinc/pyadi-dt
.. _wiki-scripts: https://github.com/analogdevicesinc/wiki-scripts
