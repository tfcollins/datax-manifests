Kernel images for pyadi-dt hardware tests
=========================================

The :doc:`adi-linux </targets/adi-linux>` target builds kernel-only images
from checksum-pinned ``analogdevicesinc/linux`` source and toolchains and
publishes an ``artifacts.json`` that `pyadi-dt`_ consumes for its hardware
CI. No Vivado, no root filesystem — a Linux x86_64 host with the packages
from ``os-dependencies.yml`` is enough.

.. code-block:: bash

   cim init --target adi-linux --source https://github.com/tfcollins/datax-manifests.git \
            --workspace ~/cim-linux --install
   cd ~/cim-linux && cim makefile
   make list-combos

::

   2023_R2 / zynq (2023_R2)
   2023_R2 / zynqmp (2023_R2)
   2026_R1 / zynq (xlnx_2026.1.0)
   2026_R1 / zynqmp (xlnx_2026.1.0)

Build both ZynqMP and Zynq images for the 2026_R1 release and verify them
strictly:

.. code-block:: bash

   for platform in zynq zynqmp; do
     make sdk-build KERNEL_RELEASE=2026_R1 KERNEL_PLATFORM="$platform" KERNEL_JOBS=8
     python3 scripts/build-kernel.py --release 2026_R1 --platform "$platform" \
       --output "artifacts/2026_R1/$platform" --verify
   done

The first run downloads the pinned source and GCC 12.2.0 cross-toolchain
archives into ``~/.cache/cim/adi-linux`` (rehashed on every reuse); a
rebuild with the same inputs is a no-op. ``--verify`` prints only the
absolute ``artifacts.json`` path on success.

To also get the board's devicetree, name it (or look it up from the HDL
project in the release's boot-pairings map):

.. code-block:: bash

   make list-dts HDL_PROJECT=jupiter_sdr
   make sdk-build KERNEL_RELEASE=2026_R1 KERNEL_PLATFORM=zynqmp KERNEL_DTS=zynqmp-jupiter-sdr

The artifacts then live in ``artifacts/2026_R1/zynqmp/zynqmp-jupiter-sdr/``
with ``system.dtb`` next to ``Image`` and a ``devicetree`` entry in
``artifacts.json``.

Hand the manifests to pyadi-dt from the same shell:

.. code-block:: bash

   export ADIDT_CIM_RELEASE=2026-R1
   export ADIDT_KERNEL_ARTIFACTS_ZYNQ="$PWD/artifacts/2026_R1/zynq/artifacts.json"
   export ADIDT_KERNEL_ARTIFACTS_ZYNQMP="$PWD/artifacts/2026_R1/zynqmp/artifacts.json"

Note the two spellings: pyadi-dt's public selector is ``2026-R1``; the cim
variable and helper flag are ``2026_R1``. The manifest records release, source
commit, toolchain and image checksum, so a mismatch fails rather than
silently booting the wrong kernel.

To preview a selection without downloading anything:

.. code-block:: bash

   make guide-dry-run
   python3 scripts/guide-linux.py --dry-run --release 2023_R2 --platform zynq --jobs 4

.. _pyadi-dt: https://github.com/analogdevicesinc/pyadi-dt
