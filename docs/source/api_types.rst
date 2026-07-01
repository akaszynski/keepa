Request Types
-------------
These types validate domains and product-finder parameters.

.. autoclass:: keepa.Domain
   :members:
   :undoc-members:
   :member-order: bysource

.. py:class:: keepa.ProductParams(**parameters)

   Pydantic model for product-finder parameters. Unknown parameters are
   rejected so backend spelling mistakes fail before consuming API tokens.

   The backend exposes more than a thousand filter fields, making a rendered
   constructor signature impractical. Inspect field names and their complete
   JSON schema programmatically:

   .. code:: python

      import keepa

      field_names = keepa.ProductParams.model_fields
      schema = keepa.ProductParams.model_json_schema()

   Pass an instance directly to :meth:`keepa.Keepa.product_finder` or
   :meth:`keepa.AsyncKeepa.product_finder`.
