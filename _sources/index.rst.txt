DataX build manifests
=====================

`cim`_ manifests that build the FPGA designs, boot firmware and Linux kernels
underneath the `DataX`_ stack — ADI HDL reference designs for Vivado /
Quartus / Radiant, u-boot and Arm Trusted Firmware from source, and pinned
``analogdevicesinc/linux`` kernels — each as a ready-to-build workspace whose
release, project, board and platform are make variables.

.. code-block:: bash

   cim init --source https://github.com/tfcollins/datax-manifests.git -t hdl-boot --workspace ~/cim-jupiter --install
   cd ~/cim-jupiter && cim makefile && make guide

Start with :doc:`introduction` for where these targets sit in DataX and how
a build is selected, follow a tutorial, then use the target pages as the
reference.

.. toctree::
   :maxdepth: 1

   introduction

.. toctree::
   :maxdepth: 1
   :caption: Tutorials

   FMCOMMS2 + BOOT.BIN <tutorials/fmcomms2-zed-boot-bin>
   Jupiter from source <tutorials/jupiter-sdr-from-source>
   Switching releases <tutorials/switching-releases>
   Kernel for pyadi-dt <tutorials/kernel-for-pyadi-dt>

.. toctree::
   :maxdepth: 1
   :caption: Targets

   targets/hdl
   targets/hdl-boot
   targets/u-boot-xlnx
   targets/arm-trusted-firmware
   targets/adi-linux

.. toctree::
   :maxdepth: 1

   repository

.. _cim: https://github.com/analogdevicesinc/cim
.. _DataX: introduction.html
