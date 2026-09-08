from django.template import Context, Template


INVOICE_TEMPLATE = """
<html>
  <head>
    <style>table, th, td { border: 1px solid black; border-collapse: collapse; padding: 5px; }</style>
  </head>
  <body>
    <h1>Invoice: {{ invoice.invoice_number }}</h1>
    {% if invoice.state == 'CANCELLED' %}<h2>CANCELLED</h2><p>{{ invoice.cancellation_reason }}</p>{% endif %}

    <div>
      <h3>Seller Details</h3>
      <p>Name: {{ invoice.seller_business_name_snapshot }}<br/>
      GSTIN: {{ invoice.seller_gstin_snapshot }}<br/>
      State: {{ invoice.seller_state_snapshot }} ({{ invoice.seller_state_code_snapshot }})</p>
    </div>

    <div>
      <h3>Customer Details</h3>
      <p>Name: {{ customer_name|default:'Walk-in' }}<br/>
      GSTIN: {{ invoice.customer_gstin_snapshot|default:'Unregistered' }}</p>
    </div>

    <p><strong>Place of Supply:</strong> {{ invoice.place_of_supply }}</p>
    <p><strong>Date:</strong> {{ invoice.invoice_date }}</p>

    <table width="100%">
      <thead>
        <tr>
          <th>Item</th>
          <th>HSN/SAC</th>
          <th>Qty</th>
          <th>Rate</th>
          <th>Discount</th>
          <th>Taxable Val</th>
          <th>CGST</th>
          <th>SGST</th>
          <th>IGST</th>
          <th>Total</th>
        </tr>
      </thead>
      <tbody>
        {% for item in line_items %}
        <tr>
          <td>{{ item.product_name_snapshot|default:item.product.name }}</td>
          <td>{{ item.hsn_sac_snapshot|default:'-' }}</td>
          <td>{{ item.quantity }}</td>
          <td>{{ item.rate_charged }}</td>
          <td>{{ item.discount_amount }}</td>
          <td>{{ item.taxable_value_snapshot }}</td>
          <td>{{ item.cgst_amount }} ({{ item.cgst_rate }}%)</td>
          <td>{{ item.sgst_amount }} ({{ item.sgst_rate }}%)</td>
          <td>{{ item.igst_amount }} ({{ item.igst_rate }}%)</td>
          <td>{{ item.line_total }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <br/>
    <p align="right"><strong>Grand Total:</strong> {{ total }}</p>
  </body>
</html>
"""


def invoice_pdf_context(invoice):
    return {
        "invoice": invoice,
        "line_items": invoice.line_items.all(),
        "customer_name": invoice.customer_name_snapshot,
        "total": invoice.total_amount,
    }


def render_invoice_html(invoice):
    return Template(INVOICE_TEMPLATE).render(Context(invoice_pdf_context(invoice)))
