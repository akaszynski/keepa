{{ fullname | escape | underline }}

.. currentmodule:: {{ module }}

.. autoclass:: {{ objname }}

{% if attributes %}
   .. rubric:: Members

   .. autosummary::
{% for item in attributes %}
      ~{{ objname }}.{{ item }}
{% endfor %}

{% for item in attributes %}
   .. autoattribute:: {{ objname }}.{{ item }}
{% endfor %}
{% endif %}
