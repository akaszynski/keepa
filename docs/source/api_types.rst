Client and Backend Types
------------------------
These hand-written types validate domains and product-finder parameters.

.. autosummary::
   :toctree: api/types

   keepa.Domain

.. autosummary::
   :toctree: api/types
   :template: pydantic_model

   keepa.ProductParams

Generated Request Models
~~~~~~~~~~~~~~~~~~~~~~~~
The backend schema also defines request-shaped structs. They are exported from
``keepa.backend_models`` and documented here for schema tooling and advanced
users. High-level client methods still accept the existing Python arguments by
default for backwards compatibility.

* :class:`keepa.models.backend.DealRequest`
* :class:`keepa.models.backend.ProductFinderRequest`
* :class:`keepa.models.backend.Request`
* :class:`keepa.models.backend.TrackingRequest`

Common Response Models
~~~~~~~~~~~~~~~~~~~~~~
The full generated model reference is available in
:doc:`backend_model_reference`. These are the response models returned directly
by high-level client methods with ``typed=True``.

* :class:`keepa.models.backend.BestSellers`
* :class:`keepa.models.backend.Category`
* :class:`keepa.models.backend.DealResponse`
* :class:`keepa.models.backend.Product`
* :class:`keepa.models.backend.Seller`
