Asynchronous Client
-------------------
Create ``AsyncKeepa`` with its asynchronous classmethod, then await endpoint
calls.

.. code:: python

   import keepa

   api = await keepa.AsyncKeepa.create("<REAL_KEEPA_KEY>")
   products = await api.query("B0088PUEPK")

.. autoclass:: keepa.AsyncKeepa
   :members:
