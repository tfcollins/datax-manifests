datax-manifests
===============

`cim <https://github.com/analogdevicesinc/cim>`_ manifests for Analog Devices
HDL and Linux kernel workspaces. Each target describes the repositories, host
dependencies and build recipes cim uses to set up a ready-to-build workspace;
the targets work with upstream cim.

.. code-block:: bash

   cim list-targets --source https://github.com/tfcollins/datax-manifests.git
   cim init --source https://github.com/tfcollins/datax-manifests.git -t hdl --workspace ~/cim-hdl
   cd ~/cim-hdl && cim makefile && make guide

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
   :caption: Repository

   repository
