=====
confu
=====

.. image:: https://travis-ci.org/bninja/confu.png
   :target: https://travis-ci.org/bninja/confu

.. image:: https://coveralls.io/repos/bninja/confu/badge.png
   :target: https://coveralls.io/r/bninja/confu

Helpers for using these infrastructure tools:

- `troposphere <https://github.com/cloudtools/troposphere>`_
- `aws cfn <http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/Welcome.html>`_
- `ansible <http://docs.ansible.com/>`_

dev
---

.. code:: bash

   $ git clone git@github.com:bninja/confu.git
   $ cd confu
   $ mkvirtualenv confu
   (confu)$ pip install -e .[tests]
   (confu)$ py.test tests/ --cov=confu

shell
-----

Source completion and functions like:

.. code:: bash

   $ source <(confu shell env; confu shell complete)

or use in all shells like:

.. code:: bash

   $ (confu shell env; confu shell complete) > ~/confu.sh
   $ cat >> ~/.bashrc <<EOF
   
   . ~/confu.sh
   EOF

confue
------

Shell function for managing ``confu`` environments which are just these environment variables:

- ``CONFU_PROFILE``
- ``CONFU_REGION``
- ``CONFU_LOG`` 

like this:

.. code:: bash

   $ confue
   CONFUE_NAME=
   CONFU_PROFILE=
   CONFU_REGION=
   CONFU_LOG=
   $ confue ppw1
   $ confue -p julius -r us-west-1 -l i
   $ confue
   CONFUE_NAME=ppw1
   CONFU_PROFILE=julius
   CONFU_REGION=us-west-1
   CONFU_LOG=i
   $ confue off
   $ confue
   CONFUE_NAME=
   CONFU_PROFILE=
   CONFU_REGION=
   CONFU_LOG=
   $ confue ls
   ppw1
