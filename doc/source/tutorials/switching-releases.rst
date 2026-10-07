Switching HDL releases in one workspace
=======================================

The ``gits:`` pin in a manifest is only the initial checkout. ``HDL_RELEASE``
selects the release at make time; the helper switches the ``hdl/`` clone,
re-derives the Vivado version and refuses to touch a dirty worktree. One
workspace therefore serves every release.

.. code-block:: bash

   cim init --target hdl --source https://github.com/tfcollins/datax-manifests.git --workspace ~/cim-hdl
   cd ~/cim-hdl && cim makefile

Compare the project matrix across releases:

.. code-block:: bash

   make list-combos | tail -2
   make list-combos HDL_RELEASE=hdl_2023_r2 | tail -2

::

   Total: 93 project-carrier board combinations available.
   [INFO] Switching hdl/ to release 'hdl_2023_r2'...
   Total: 140 project-carrier board combinations available.

``git -C hdl rev-parse --abbrev-ref HEAD`` now reports ``hdl_2023_r2``.
Each switch fetches the ref if the clone lacks it, so the first switch needs
network access; after that it is a local checkout.

Tools follow the release:

.. code-block:: bash

   make check-tools HDL_RELEASE=hdl_2026_r1    # Vivado 2025.1
   make check-tools HDL_RELEASE=hdl_2023_r2    # Vivado 2023.2
   make check-tools HDL_RELEASE=main VIVADO=/opt/Xilinx/2025.2/Vivado

Any branch, tag or commit of ``analogdevicesinc/hdl`` is accepted. For a
release the helper does not know, ``VIVADO=auto`` cannot resolve a version
and the build stops with a message asking for ``VIVADO=/path``; the third
line above shows the override.

Building the same design from two releases keeps separate outputs, because
each lives in the project directory of the checkout that built it:

.. code-block:: bash

   make sdk-build HDL_RELEASE=hdl_2026_r1 HDL_PROJECT=fmcomms2 HDL_BOARD=zcu102
   make sdk-build HDL_RELEASE=hdl_2023_r2 HDL_PROJECT=fmcomms2 HDL_BOARD=zcu102 DIR_NAME=build_2023

Use ``DIR_NAME`` to keep both build directories when the project path is the
same in both releases.

If a switch is refused::

   [ERROR] hdl/ worktree is dirty; refusing to switch to release 'hdl_2023_r2'.

commit, stash or ``git -C hdl checkout -- .`` first. Untracked build output is
ignored by the check.
